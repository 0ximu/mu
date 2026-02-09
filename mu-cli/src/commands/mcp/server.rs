//! MCP Server implementation for MU
//!
//! Exposes MU capabilities as MCP tools that can be called by AI assistants.

use super::find_project_root;
use crate::config::MuConfig;
use regex::Regex;
use std::collections::VecDeque;
use std::fs;
use std::future::Future;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tokio::sync::Mutex;

use rmcp::{
    handler::server::{router::tool::ToolRouter, tool::Parameters},
    model::{ErrorData as McpError, *},
    schemars::JsonSchema,
    tool, tool_handler, tool_router, ServerHandler,
};
use serde::{Deserialize, Serialize};
use tokio::sync::{OnceCell, RwLock};

static COLLAB_MESSAGE_COUNTER: AtomicU64 = AtomicU64::new(1);

/// Lazily-initialized project state
struct ProjectState {
    mubase: mu_daemon::storage::MUbase,
    project_root: PathBuf,
    config: MuConfig,
}

/// MU MCP Server - exposes codebase intelligence tools
///
/// Now with session state for activity-dependent awareness.
/// MU remembers what you've looked at and can detect patterns.
///
/// Supports dynamic project detection via MCP client roots - the server will
/// use the client's working directory instead of its own CWD.
#[derive(Clone)]
pub struct MuMcpServer {
    /// Lazily-initialized project state (mubase + project_root)
    /// Initialized on first tool call using client roots or fallback directory
    state: Arc<OnceCell<ProjectState>>,
    /// Client roots received during MCP initialization
    /// Used to determine which project the client is working in
    client_roots: Arc<RwLock<Option<Vec<Root>>>>,
    /// Fallback directory if no client roots are provided
    fallback_dir: PathBuf,
    /// Embedding model (lazily loaded)
    model: Arc<OnceCell<mu_embeddings::MuSigmaModel>>,
    tool_router: ToolRouter<MuMcpServer>,
    /// Session state for cognitive layer - tracks accessed nodes and queries
    session: Arc<Mutex<SessionState>>,
}

// Tool parameter structs
#[derive(Debug, Deserialize, JsonSchema)]
pub struct GrokParams {
    /// Natural language question about the codebase (e.g., "how does authentication work")
    #[schemars(description = "Natural language question about the codebase")]
    pub query: String,
    /// Number of code snippets to return (default: 3)
    #[schemars(description = "Number of results to return (1-10, default: 3)")]
    pub limit: Option<usize>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct FindParams {
    /// Exact symbol name to find (function, class, module)
    #[schemars(description = "Exact symbol name to find (e.g., 'parse_config', 'UserService')")]
    pub symbol: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ImpactParams {
    /// Symbol name to analyze for downstream dependencies
    #[schemars(description = "Symbol name to analyze (e.g., 'DatabaseConnection')")]
    pub symbol: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct DiffParams {
    /// Base git ref to compare against (branch, commit, tag). Defaults to 'main' or 'master'.
    #[schemars(description = "Base git ref (e.g., 'main', 'HEAD~5', 'v1.0.0')")]
    pub base_ref: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct WtfParams {
    /// File path to investigate history for
    #[schemars(description = "File path to investigate (e.g., 'src/auth/login.rs')")]
    pub file: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct SusParams {
    /// Minimum complexity threshold (default: 15)
    #[schemars(description = "Minimum complexity score to flag (default: 15)")]
    pub min_complexity: Option<i64>,
    /// Include generated files in results. Defaults to config value (`[sus].include_generated`, default false).
    #[schemars(description = "Include generated files in results (default: false)")]
    pub include_generated: Option<bool>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct OracleParams {
    /// The task you want to accomplish (e.g., "fix the login bug where sessions expire too early")
    #[schemars(description = "Natural language description of the task you want to accomplish")]
    pub task: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct CollabOpenParams {
    /// Session objective shared by collaborating agents
    #[schemars(description = "Shared objective (e.g., 'Refactor auth flow safely')")]
    pub objective: String,
    /// Optional session identifier. If omitted, MU auto-generates one.
    #[schemars(description = "Optional session id (e.g., 'auth-refactor')")]
    pub session_id: Option<String>,
    /// Optional explicit participant list. Defaults to Codex + Claude Code.
    #[schemars(description = "Optional participant list (e.g., ['codex','claude-code'])")]
    pub participants: Option<Vec<String>>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct CollabSendParams {
    /// Collaboration session id created by mu_collab_open
    #[schemars(description = "Session id from mu_collab_open")]
    pub session_id: String,
    /// Sender agent name
    #[schemars(description = "Sender agent name (e.g., 'codex', 'claude-code')")]
    pub from: String,
    /// Target agent name. Use 'all' to broadcast.
    #[schemars(description = "Optional target agent. Defaults to 'all'")]
    pub to: Option<String>,
    /// Collaboration phase (planning, implementation, audit, general)
    #[schemars(description = "Phase: planning | implementation | audit | general")]
    pub phase: Option<String>,
    /// Optional short title
    #[schemars(description = "Optional short title")]
    pub title: Option<String>,
    /// Main message content
    #[schemars(description = "Message content to send to collaborator(s)")]
    pub message: String,
    /// Optional list of related files
    #[schemars(description = "Optional related file paths")]
    pub related_files: Option<Vec<String>>,
    /// Optional list of related symbols
    #[schemars(description = "Optional related symbols/functions/classes")]
    pub related_symbols: Option<Vec<String>>,
    /// Whether this message asks for explicit follow-up
    #[schemars(description = "Whether this message requires explicit follow-up (default: false)")]
    pub requires_response: Option<bool>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct CollabInboxParams {
    /// Collaboration session id
    #[schemars(description = "Session id from mu_collab_open")]
    pub session_id: String,
    /// Reader agent name
    #[schemars(description = "Reader agent name (e.g., 'codex', 'claude-code')")]
    pub agent: String,
    /// Return only unread messages since last checkpoint (default: true)
    #[schemars(description = "Return only unread messages (default: true)")]
    pub unread_only: Option<bool>,
    /// Mark returned messages as read for this agent (default: true)
    #[schemars(description = "Mark messages as read (default: true)")]
    pub mark_read: Option<bool>,
    /// Max messages to return (default: 20, max: 100)
    #[schemars(description = "Maximum messages to return (default: 20, max: 100)")]
    pub limit: Option<usize>,
    /// Optional phase filter
    #[schemars(description = "Optional phase filter: planning | implementation | audit | general")]
    pub phase: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct CollabProtocolParams {
    /// Optional phase scope. If omitted, returns all phase templates.
    #[schemars(description = "Optional phase: planning | implementation | audit | general | all")]
    pub phase: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct CollabAskParams {
    /// Collaboration session id
    #[schemars(description = "Session id from mu_collab_open")]
    pub session_id: String,
    /// Sender agent name
    #[schemars(description = "Sender agent name (e.g., 'codex', 'claude-code')")]
    pub from: String,
    /// Target agent name
    #[schemars(description = "Target agent name (e.g., 'claude-code', 'codex')")]
    pub to: String,
    /// Outgoing message phase
    #[schemars(description = "Outgoing phase: planning | implementation | audit | general")]
    pub phase: Option<String>,
    /// Optional outgoing title
    #[schemars(description = "Optional outgoing message title")]
    pub title: Option<String>,
    /// Outgoing message content
    #[schemars(description = "Outgoing message body")]
    pub message: String,
    /// Optional related files for outgoing message
    #[schemars(description = "Optional related files for outgoing message")]
    pub related_files: Option<Vec<String>>,
    /// Optional related symbols for outgoing message
    #[schemars(description = "Optional related symbols for outgoing message")]
    pub related_symbols: Option<Vec<String>>,
    /// Whether outgoing message requires response
    #[schemars(description = "Whether outgoing message requires response (default: true)")]
    pub requires_response: Option<bool>,
    /// Executable to run for target agent (e.g. 'claude', '/usr/local/bin/codex')
    #[schemars(description = "CLI executable for target agent")]
    pub target_command: String,
    /// Optional agent preset (codex_exec, claude_print) to reduce CLI arg guesswork
    #[schemars(description = "Optional agent preset: codex_exec | claude_print")]
    pub agent_preset: Option<String>,
    /// Target CLI args. Supports placeholders:
    /// {{session_id}}, {{from}}, {{to}}, {{phase}}, {{message}}
    #[schemars(description = "Target CLI args with placeholders (e.g., ['-p','{{message}}'])")]
    pub target_args: Option<Vec<String>>,
    /// Optional working directory for target CLI execution (absolute or project-relative)
    #[schemars(description = "Optional working directory for target CLI command")]
    pub working_dir: Option<String>,
    /// Auto-resolve git root from related files when working_dir is omitted (default: true)
    #[schemars(
        description = "Auto-resolve git root from related files when working_dir is omitted (default: true)"
    )]
    pub auto_resolve_git_root: Option<bool>,
    /// Enforce protocol sections on outgoing request message (default: false)
    #[schemars(description = "Enforce protocol sections on request message (default: false)")]
    pub enforce_request_protocol: Option<bool>,
    /// Auto-wrap freeform outgoing request into phase template when missing sections (default: false)
    #[schemars(
        description = "Auto-wrap freeform outgoing request into phase template when missing sections (default: false)"
    )]
    pub auto_wrap_request_protocol: Option<bool>,
    /// Reply phase for the autogenerated response message
    #[schemars(
        description = "Reply phase: planning | implementation | audit | general (default: general)"
    )]
    pub response_phase: Option<String>,
    /// Optional reply title
    #[schemars(description = "Optional reply title")]
    pub response_title: Option<String>,
    /// Enforce protocol sections on target CLI response (default: false)
    #[schemars(description = "Enforce protocol sections on target response (default: false)")]
    pub enforce_response_protocol: Option<bool>,
    /// Timeout in seconds for target CLI execution (default: 90, max: 600)
    #[schemars(description = "CLI timeout in seconds (default: 90, max: 600)")]
    pub timeout_seconds: Option<u64>,
    /// Max response chars to persist (default: 40000, max: 200000)
    #[schemars(description = "Maximum response chars persisted (default: 40000, max: 200000)")]
    pub max_response_chars: Option<usize>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct CollabJobStatusParams {
    /// Collaboration session id
    #[schemars(description = "Session id from mu_collab_open")]
    pub session_id: String,
    /// Job id returned by mu_collab_ask_async
    #[schemars(description = "Job id from mu_collab_ask_async")]
    pub job_id: String,
    /// Include response body excerpt when available (default: true)
    #[schemars(description = "Include response excerpt when available (default: true)")]
    pub include_response_excerpt: Option<bool>,
    /// Max response excerpt chars (default: 2000, max: 20000)
    #[schemars(description = "Maximum response excerpt chars (default: 2000, max: 20000)")]
    pub response_excerpt_chars: Option<usize>,
    /// Block until job reaches terminal state (succeeded/failed) or wait timeout
    #[schemars(description = "Block until terminal state (default: false)")]
    pub wait: Option<bool>,
    /// Wait timeout in seconds when wait=true (default: 300, max: 3600)
    #[schemars(description = "Wait timeout in seconds when wait=true (default: 300, max: 3600)")]
    pub wait_timeout_seconds: Option<u64>,
    /// Poll interval in milliseconds when wait=true (default: 500, max: 5000)
    #[schemars(
        description = "Poll interval in milliseconds when wait=true (default: 500, max: 5000)"
    )]
    pub poll_interval_ms: Option<u64>,
}

#[derive(Debug, Serialize, Deserialize)]
struct CollabSessionMeta {
    session_id: String,
    objective: String,
    participants: Vec<String>,
    created_at_ms: u128,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CollabMessage {
    id: String,
    session_id: String,
    from: String,
    to: String,
    phase: String,
    title: Option<String>,
    message: String,
    related_files: Vec<String>,
    related_symbols: Vec<String>,
    requires_response: bool,
    created_at_ms: u128,
}

#[derive(Debug, Serialize, Deserialize, Default)]
struct CollabReceipt {
    agent: String,
    last_seen_message_id: Option<String>,
    updated_at_ms: u128,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CollabJobRecord {
    job_id: String,
    session_id: String,
    status: String, // queued | running | succeeded | failed
    request_message_id: String,
    request_path: String,
    target_command: String,
    target_args: Vec<String>,
    working_dir: String,
    timeout_seconds: u64,
    created_at_ms: u128,
    started_at_ms: Option<u128>,
    finished_at_ms: Option<u128>,
    response_phase: Option<String>,
    response_message_id: Option<String>,
    response_path: Option<String>,
    response_chars: Option<usize>,
    error: Option<String>,
}

// ============================================================================
// Session State - Activity-dependent awareness for the cognitive layer
// ============================================================================

/// A node that was accessed during this session
#[derive(Debug, Clone)]
pub struct AccessedNode {
    pub name: String,
    pub node_type: String,
    pub file_path: Option<String>,
}

/// Session state tracking - gives MU memory across MCP calls
#[derive(Debug, Default)]
pub struct SessionState {
    /// Recently accessed nodes (most recent first)
    accessed_nodes: VecDeque<AccessedNode>,
    /// Query history for pattern detection
    query_history: VecDeque<String>,
    /// Git recency cache: file_path -> commit count in last 30 days
    /// Lazy-loaded on first access, represents "hot" files in the codebase
    git_recency: Option<std::collections::HashMap<String, u32>>,
}

impl SessionState {
    const MAX_NODES: usize = 50;
    const MAX_QUERIES: usize = 20;

    pub fn new() -> Self {
        Self {
            accessed_nodes: VecDeque::new(),
            query_history: VecDeque::new(),
            git_recency: None, // Lazy-loaded on first search
        }
    }

    /// Record that nodes were accessed via a query
    fn record_access(&mut self, query: &str, nodes: &[SearchResult]) {
        // Record the query
        self.query_history.push_front(query.to_string());
        if self.query_history.len() > Self::MAX_QUERIES {
            self.query_history.pop_back();
        }

        // Record accessed nodes
        for node in nodes {
            self.accessed_nodes.push_front(AccessedNode {
                name: node.name.clone(),
                node_type: node.node_type.clone(),
                file_path: node.file_path.clone(),
            });
        }

        // Trim to max size
        while self.accessed_nodes.len() > Self::MAX_NODES {
            self.accessed_nodes.pop_back();
        }
    }

    /// Get unique nodes accessed (deduped by name)
    pub fn unique_nodes(&self) -> Vec<&AccessedNode> {
        let mut seen = std::collections::HashSet::new();
        self.accessed_nodes
            .iter()
            .filter(|n| seen.insert(&n.name))
            .collect()
    }

    /// Count how many times a node has been accessed
    pub fn access_count(&self, name: &str) -> usize {
        self.accessed_nodes
            .iter()
            .filter(|n| n.name == name)
            .count()
    }

    /// Detect if we're stuck in a cluster (same nodes accessed repeatedly)
    pub fn detect_rumination(&self) -> Option<Vec<String>> {
        if self.query_history.len() < 3 {
            return None;
        }

        // Count node access frequency
        let mut counts: std::collections::HashMap<&str, usize> = std::collections::HashMap::new();
        for node in &self.accessed_nodes {
            *counts.entry(&node.name).or_default() += 1;
        }

        // Find nodes accessed 3+ times
        let repeated: Vec<String> = counts
            .iter()
            .filter(|(_, count)| **count >= 3)
            .map(|(name, _)| name.to_string())
            .collect();

        if repeated.len() >= 2 {
            Some(repeated)
        } else {
            None
        }
    }

    /// Get query count
    pub fn query_count(&self) -> usize {
        self.query_history.len()
    }

    /// Check if a node has been seen
    pub fn has_seen(&self, name: &str) -> bool {
        self.accessed_nodes.iter().any(|n| n.name == name)
    }

    /// Load git recency data (files modified in last 30 days with commit counts).
    /// This represents "hot" areas of the codebase - recently active circuits.
    pub fn load_git_recency(&mut self) {
        if self.git_recency.is_some() {
            return; // Already loaded
        }

        let mut recency = std::collections::HashMap::new();

        // Get files changed in last 30 days with commit counts
        // git log --since="30 days ago" --name-only --pretty=format: gives us file names
        let output = Command::new("git")
            .args([
                "log",
                "--since=30 days ago",
                "--name-only",
                "--pretty=format:",
            ])
            .output();

        if let Ok(output) = output {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                for line in stdout.lines() {
                    let file = line.trim();
                    if !file.is_empty() {
                        *recency.entry(file.to_string()).or_insert(0) += 1;
                    }
                }
            }
        }

        self.git_recency = Some(recency);
    }
}

#[tool_router]
impl MuMcpServer {
    /// Create a new MCP server with lazy project initialization.
    ///
    /// The server won't open any database until the first tool call.
    /// At that point, it will use client roots (if provided during MCP init)
    /// or fall back to the provided directory.
    pub fn new(fallback_dir: PathBuf) -> Self {
        Self {
            state: Arc::new(OnceCell::new()),
            client_roots: Arc::new(RwLock::new(None)),
            fallback_dir,
            model: Arc::new(OnceCell::new()),
            tool_router: Self::tool_router(),
            session: Arc::new(Mutex::new(SessionState::new())),
        }
    }

    /// Ensure the project state is initialized, using client roots if available.
    ///
    /// This is called lazily on the first tool invocation.
    async fn ensure_state(&self) -> Result<&ProjectState, McpError> {
        self.state
            .get_or_try_init(|| async {
                // Determine the starting directory for project search
                let start_dir = {
                    let roots = self.client_roots.read().await;
                    if let Some(ref root_list) = *roots {
                        if let Some(first_root) = root_list.first() {
                            // Client provided roots - use the first one
                            // Root URI is typically "file:///path/to/dir"
                            let uri = &first_root.uri;
                            if let Some(path) = uri.strip_prefix("file://") {
                                PathBuf::from(path)
                            } else {
                                // Try as plain path
                                PathBuf::from(uri)
                            }
                        } else {
                            self.fallback_dir.clone()
                        }
                    } else {
                        self.fallback_dir.clone()
                    }
                };

                // Find .mu directory from start_dir
                let project_root = find_project_root(&start_dir).ok_or_else(|| {
                    McpError::internal_error(
                        format!(
                            "No .mu directory found starting from '{}'. Run 'mu bootstrap' first.",
                            start_dir.display()
                        ),
                        None,
                    )
                })?;

                let mubase_path = project_root.join(".mu").join("mubase");
                let mubase =
                    mu_daemon::storage::MUbase::open_read_only(&mubase_path).map_err(|e| {
                        McpError::internal_error(format!("Failed to open mubase: {}", e), None)
                    })?;
                let config = MuConfig::load(&project_root);

                Ok(ProjectState {
                    mubase,
                    project_root,
                    config,
                })
            })
            .await
    }

    /// Grok: Semantic search with actual code snippets
    #[tool(
        description = "Find and show relevant code for a question. Returns actual code snippets, not just locations. Use this to understand how something works."
    )]
    async fn mu_grok(
        &self,
        Parameters(params): Parameters<GrokParams>,
    ) -> Result<CallToolResult, McpError> {
        // Ensure lazy state is initialized (uses client roots if available)
        let state = self.ensure_state().await?;

        let start = Instant::now();
        let limit = params.limit.unwrap_or(3).clamp(1, 10);

        // Get search results
        let results = if state.mubase.has_embeddings().unwrap_or(false) {
            self.graph_boosted_grok_search(&state.mubase, &params.query, limit)
                .await
        } else {
            self.run_keyword_search(&state.mubase, &params.query, limit)
                .unwrap_or_default()
        };

        // Record this access in session state (activity-dependent awareness)
        {
            let mut session = self.session.lock().await;
            session.record_access(&params.query, &results);
        }

        let mut output = String::new();
        output.push_str(&format!("# grok: \"{}\"\n", params.query));
        output.push_str(&format!(
            "# {} results in {}ms\n\n",
            results.len(),
            start.elapsed().as_millis()
        ));

        let clusters = self.cluster_results_by_flow(&results);
        let mut rank = 1usize;

        for (cluster_label, indexes) in clusters {
            output.push_str(&format!(
                "### Flow Cluster: {} ({} nodes)\n\n",
                cluster_label,
                indexes.len()
            ));

            for idx in indexes {
                let result = &results[idx];
                let sigil = match result.node_type.as_str() {
                    "module" => "!",
                    "class" => "$",
                    "function" => "#",
                    "doc" => "%",
                    _ => "@",
                };

                output.push_str(&format!(
                    "## {}. {}{} [{}] — {:.0}% match\n",
                    rank,
                    sigil,
                    result.name,
                    result.node_type,
                    result.similarity * 100.0
                ));
                rank += 1;

                if let Some(ref path) = result.file_path {
                    output.push_str(&format!("File: {}\n", path));

                    // Read and show actual code snippet
                    let full_path = state.project_root.join(path);
                    if let Ok(content) = fs::read_to_string(&full_path) {
                        if let Some(snippet) =
                            self.extract_snippet(&content, &result.name, &result.node_type)
                        {
                            output.push_str("```\n");
                            output.push_str(&snippet);
                            if !snippet.ends_with('\n') {
                                output.push('\n');
                            }
                            output.push_str("```\n");
                        }
                    }
                }
                output.push('\n');
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Find: Exact symbol lookup with code
    #[tool(
        description = "Find a specific symbol by exact name. Use this when you know the function/class name you're looking for."
    )]
    async fn mu_find(
        &self,
        Parameters(params): Parameters<FindParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let sql = format!(
            "SELECT type, name, file_path, line_start, line_end FROM nodes WHERE name = '{}' OR name LIKE '%.{}' LIMIT 10",
            params.symbol.replace('\'', "''"),
            params.symbol.replace('\'', "''")
        );

        let result = state
            .mubase
            .query(&sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        #[derive(Clone)]
        struct FindRow {
            node_type: String,
            name: String,
            file_path: String,
            start_line: i64,
            end_line: i64,
        }

        let all_rows: Vec<FindRow> = result
            .rows
            .iter()
            .map(|row| FindRow {
                node_type: row
                    .first()
                    .and_then(|v| v.as_str())
                    .unwrap_or("?")
                    .to_string(),
                name: row
                    .get(1)
                    .and_then(|v| v.as_str())
                    .unwrap_or("?")
                    .to_string(),
                file_path: row
                    .get(2)
                    .and_then(|v| v.as_str())
                    .unwrap_or("?")
                    .to_string(),
                start_line: row.get(3).and_then(|v| v.as_i64()).unwrap_or(0),
                end_line: row.get(4).and_then(|v| v.as_i64()).unwrap_or(0),
            })
            .collect();

        let non_module_files: std::collections::HashSet<String> = all_rows
            .iter()
            .filter(|r| r.node_type != "module")
            .map(|r| r.file_path.clone())
            .collect();

        let total_rows = all_rows.len();
        let filtered_rows: Vec<FindRow> = all_rows
            .into_iter()
            .filter(|row| {
                // Suppress invalid ranges unless it's the only match.
                if row.end_line < row.start_line && total_rows > 1 {
                    return false;
                }

                // Suppress low-value module rows when symbol-level rows exist in the same file.
                if row.node_type == "module" && non_module_files.contains(&row.file_path) {
                    return false;
                }

                true
            })
            .collect();

        let mut output = String::new();
        output.push_str(&format!("# find: \"{}\"\n", params.symbol));
        output.push_str(&format!("# {} matches\n\n", filtered_rows.len()));

        for row in &filtered_rows {
            let node_type = row.node_type.as_str();
            let name = row.name.as_str();
            let file_path = row.file_path.as_str();
            let start_line = row.start_line;
            let end_line = row.end_line;

            let sigil = match node_type {
                "module" => "!",
                "class" => "$",
                "function" => "#",
                _ => "@",
            };

            output.push_str(&format!("## {}{} [{}]\n", sigil, name, node_type));
            output.push_str(&format!("{}:{}-{}\n", file_path, start_line, end_line));

            // Show the actual code
            let full_path = state.project_root.join(file_path);
            if let Ok(content) = fs::read_to_string(&full_path) {
                let lines: Vec<&str> = content.lines().collect();
                let start = (start_line as usize).saturating_sub(1);
                let end = (end_line as usize).min(lines.len());
                if start < lines.len() {
                    output.push_str("```\n");
                    for line in &lines[start..end.min(start + 30)] {
                        output.push_str(line);
                        output.push('\n');
                    }
                    if end > start + 30 {
                        output.push_str("... (truncated)\n");
                    }
                    output.push_str("```\n");
                }
            }
            output.push('\n');
        }

        if filtered_rows.is_empty() {
            output.push_str("No exact matches. Try mu_grok for semantic search.\n");
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Compress: Token-efficient codebase overview
    #[tool(
        description = "Get a compressed overview of the entire codebase structure. Use this first to understand what's in the project."
    )]
    async fn mu_compress(&self) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        // Get stats
        let stats = state
            .mubase
            .query(
                "SELECT
            (SELECT COUNT(*) FROM nodes) as nodes,
            (SELECT COUNT(*) FROM edges) as edges,
            (SELECT COUNT(DISTINCT file_path) FROM nodes) as files",
            )
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let (node_count, edge_count, file_count) = stats
            .rows
            .first()
            .map(|r| {
                (
                    r.first().and_then(|v| v.as_i64()).unwrap_or(0),
                    r.get(1).and_then(|v| v.as_i64()).unwrap_or(0),
                    r.get(2).and_then(|v| v.as_i64()).unwrap_or(0),
                )
            })
            .unwrap_or((0, 0, 0));

        // Detect languages
        let langs = state
            .mubase
            .query(
                "SELECT DISTINCT
            CASE
                WHEN file_path LIKE '%.rs' THEN 'Rust'
                WHEN file_path LIKE '%.py' THEN 'Python'
                WHEN file_path LIKE '%.ts' THEN 'TypeScript'
                WHEN file_path LIKE '%.js' THEN 'JavaScript'
                WHEN file_path LIKE '%.go' THEN 'Go'
                WHEN file_path LIKE '%.java' THEN 'Java'
                WHEN file_path LIKE '%.cs' THEN 'C#'
                ELSE 'Other'
            END as lang
            FROM nodes WHERE file_path IS NOT NULL",
            )
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let languages: Vec<String> = langs
            .rows
            .iter()
            .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
            .filter(|s| s != "Other")
            .collect();

        let mut output = String::new();
        output.push_str("# MU Codebase Overview\n\n");
        output.push_str(&format!(
            "Files: {} | Symbols: {} | Edges: {}\n",
            file_count, node_count, edge_count
        ));
        output.push_str(&format!(
            "Languages: {}\n\n",
            if languages.is_empty() {
                "Unknown".to_string()
            } else {
                languages.join(", ")
            }
        ));

        // Get structure grouped by directory
        let nodes_result = state.mubase.query(
            "SELECT type, name, file_path, complexity FROM nodes ORDER BY file_path, type DESC, name LIMIT 500")
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let mut current_dir = String::new();
        let mut current_file = String::new();

        for row in &nodes_result.rows {
            let node_type = row.first().and_then(|v| v.as_str()).unwrap_or("");
            let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
            let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("");
            let complexity = row.get(3).and_then(|v| v.as_i64()).unwrap_or(0);

            // Track directory changes
            let dir = file_path.rsplit_once('/').map(|(d, _)| d).unwrap_or("");
            if dir != current_dir && !dir.is_empty() {
                current_dir = dir.to_string();
                output.push_str(&format!("\n## {}/\n", dir));
            }

            // Track file changes
            if file_path != current_file && !file_path.is_empty() {
                current_file = file_path.to_string();
                let filename = file_path
                    .rsplit_once('/')
                    .map(|(_, f)| f)
                    .unwrap_or(file_path);
                output.push_str(&format!("  ! {}\n", filename));
            }

            let sigil = match node_type {
                "module" => continue, // Skip module entries, we show files
                "class" => "$",
                "function" => "#",
                _ => "@",
            };

            let complexity_indicator = if complexity > 20 { " ⚠" } else { "" };
            output.push_str(&format!("    {}{}{}\n", sigil, name, complexity_indicator));
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Impact: What depends on this symbol (with grep fallback)
    #[tool(
        description = "Find what code depends on a symbol. Shows what might break if you change it."
    )]
    async fn mu_impact(
        &self,
        Parameters(params): Parameters<ImpactParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let mut output = String::new();
        output.push_str(&format!("# Impact Analysis: {}\n\n", params.symbol));

        // First, try the graph-based approach
        let sql = format!(
            "SELECT DISTINCT n.name, n.type, n.file_path FROM edges e
             JOIN nodes n ON n.id = e.source_id
             WHERE e.target_id IN (SELECT id FROM nodes WHERE name = '{}')
             LIMIT 50",
            params.symbol.replace('\'', "''")
        );

        let result = state
            .mubase
            .query(&sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let graph_count = result.rows.len();

        if graph_count > 0 {
            output.push_str(&format!("## Graph Dependencies ({} found)\n", graph_count));
            for row in &result.rows {
                let name = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                output.push_str(&format!("  {} [{}] — {}\n", name, node_type, file_path));
            }
            output.push('\n');
        }

        // If graph is sparse, supplement with ripgrep text search.
        if graph_count < 5 {
            output.push_str("## Text References (ripgrep)\n");

            let mut rg_base_args = vec!["--fixed-strings".to_string()];
            if !state.config.impact_respect_gitignore() {
                rg_base_args.push("--no-ignore".to_string());
            }
            for glob in state.config.impact_exclude_patterns() {
                rg_base_args.push("--glob".to_string());
                rg_base_args.push(format!("!{}", glob));
            }

            let mut files_cmd = Command::new("rg");
            for arg in &rg_base_args {
                files_cmd.arg(arg);
            }
            let files_result = files_cmd
                .args(["--files-with-matches", &params.symbol])
                .current_dir(&state.project_root)
                .output();

            match files_result {
                Ok(files_out) if files_out.status.success() => {
                    let files = String::from_utf8_lossy(&files_out.stdout);
                    let all_files: Vec<&str> = files.lines().collect();
                    let file_list: Vec<&str> = all_files.iter().copied().take(20).collect();

                    if file_list.is_empty() {
                        output.push_str("  No text references found.\n");
                    } else {
                        output.push_str(&format!("  Found in {} files:\n", all_files.len()));
                        for file in &file_list {
                            output.push_str(&format!("    {}\n", file));
                        }
                        if all_files.len() > file_list.len() {
                            output.push_str(&format!(
                                "    ... and {} more\n",
                                all_files.len() - file_list.len()
                            ));
                        }

                        output.push_str("\n## Sample Usages\n");
                        let mut context_cmd = Command::new("rg");
                        for arg in &rg_base_args {
                            context_cmd.arg(arg);
                        }
                        let context_result = context_cmd
                            .args(["-n", "-C1", &params.symbol])
                            .current_dir(&state.project_root)
                            .output();

                        match context_result {
                            Ok(ctx) if ctx.status.success() => {
                                let context = String::from_utf8_lossy(&ctx.stdout);
                                let lines: Vec<&str> = context.lines().take(40).collect();
                                output.push_str("```\n");
                                for line in lines {
                                    output.push_str(line);
                                    output.push('\n');
                                }
                                output.push_str("```\n");
                            }
                            Ok(_) => {
                                output.push_str("  No usage context found.\n");
                            }
                            Err(err) => {
                                output.push_str(&format!(
                                    "  Failed to run ripgrep usage scan: {}\n",
                                    err
                                ));
                            }
                        }
                    }
                }
                Ok(files_out) if files_out.status.code() == Some(1) => {
                    output.push_str("  No text references found.\n");
                }
                Ok(files_out) => {
                    let err = String::from_utf8_lossy(&files_out.stderr);
                    output.push_str(&format!(
                        "  ripgrep fallback failed (exit {}): {}\n",
                        files_out.status.code().unwrap_or(-1),
                        err.trim()
                    ));
                }
                Err(err) => {
                    output.push_str(&format!("  Failed to run ripgrep fallback: {}\n", err));
                }
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Diff: Semantic diff showing what changed
    #[tool(
        description = "See what symbols changed between git refs. Shows functions/classes added, modified, or removed."
    )]
    async fn mu_diff(
        &self,
        Parameters(params): Parameters<DiffParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        // Detect default branch
        let base = params.base_ref.unwrap_or_else(|| {
            let result = Command::new("git")
                .args(["symbolic-ref", "refs/remotes/origin/HEAD"])
                .current_dir(&state.project_root)
                .output();

            result
                .ok()
                .and_then(|o| String::from_utf8(o.stdout).ok())
                .and_then(|s| s.trim().rsplit('/').next().map(|s| s.to_string()))
                .unwrap_or_else(|| "main".to_string())
        });

        let mut output = String::new();
        output.push_str(&format!("# Semantic Diff: {} → HEAD\n\n", base));

        // Get changed files
        let diff_result = Command::new("git")
            .args(["diff", "--name-status", &base, "HEAD"])
            .current_dir(&state.project_root)
            .output()
            .map_err(|e| McpError::internal_error(format!("git error: {}", e), None))?;

        let diff_output = String::from_utf8_lossy(&diff_result.stdout);

        let mut added_files = Vec::new();
        let mut modified_files = Vec::new();
        let mut deleted_files = Vec::new();

        for line in diff_output.lines() {
            let parts: Vec<&str> = line.split('\t').collect();
            if parts.len() >= 2 {
                let status = parts[0];
                let file = parts[1];
                match status.chars().next() {
                    Some('A') => added_files.push(file),
                    Some('M') => modified_files.push(file),
                    Some('D') => deleted_files.push(file),
                    _ => {}
                }
            }
        }

        let total = added_files.len() + modified_files.len() + deleted_files.len();
        output.push_str(&format!(
            "{} files changed: +{} ~{} -{}\n\n",
            total,
            added_files.len(),
            modified_files.len(),
            deleted_files.len()
        ));

        // For each modified file, show what symbols changed
        if !modified_files.is_empty() {
            output.push_str("## Modified Files\n");
            for file in modified_files.iter().take(10) {
                output.push_str(&format!("\n### {}\n", file));

                // Get symbols in this file
                let sql = format!(
                    "SELECT type, name FROM nodes WHERE file_path = '{}' ORDER BY line_start",
                    file.replace('\'', "''")
                );
                if let Ok(nodes) = state.mubase.query(&sql) {
                    let symbols: Vec<String> = nodes
                        .rows
                        .iter()
                        .filter_map(|r| {
                            let t = r.first().and_then(|v| v.as_str())?;
                            let n = r.get(1).and_then(|v| v.as_str())?;
                            if t == "module" {
                                return None;
                            }
                            let sigil = match t {
                                "class" => "$",
                                "function" => "#",
                                _ => "@",
                            };
                            Some(format!("{}{}", sigil, n))
                        })
                        .collect();

                    if !symbols.is_empty() {
                        output.push_str(&format!("  Contains: {}\n", symbols.join(", ")));
                    }
                }
            }
        }

        if !added_files.is_empty() {
            output.push_str("\n## Added Files\n");
            for file in added_files.iter().take(10) {
                output.push_str(&format!("  + {}\n", file));
            }
        }

        if !deleted_files.is_empty() {
            output.push_str("\n## Deleted Files\n");
            for file in deleted_files.iter().take(10) {
                output.push_str(&format!("  - {}\n", file));
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Sus: Find suspicious code with categories
    #[tool(
        description = "Find suspicious code: high complexity, security-sensitive names, large functions. Good for code review."
    )]
    async fn mu_sus(
        &self,
        Parameters(params): Parameters<SusParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let min_complexity = params.min_complexity.unwrap_or(15);
        let include_generated = params
            .include_generated
            .unwrap_or(state.config.sus_include_generated());
        let exclude_regexes = if include_generated {
            Vec::new()
        } else {
            self.compile_glob_patterns(&state.config.sus_exclude_patterns())
        };

        let mut output = String::new();
        output.push_str("# Suspicious Code Report\n\n");

        // High complexity
        let complex_sql = format!(
            "SELECT name, type, file_path, complexity FROM nodes
             WHERE complexity >= {} AND type = 'function'
             ORDER BY complexity DESC LIMIT 200",
            min_complexity
        );
        let complex = state
            .mubase
            .query(&complex_sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let complex_rows: Vec<_> = complex
            .rows
            .iter()
            .filter(|row| {
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("");
                !self.should_exclude_path(file_path, &exclude_regexes)
            })
            .take(15)
            .collect();

        if !complex_rows.is_empty() {
            output.push_str(&format!(
                "## High Complexity (≥{}) — {} found\n",
                min_complexity,
                complex_rows.len()
            ));
            output.push_str("Functions that are hard to understand and maintain:\n\n");
            for row in &complex_rows {
                let name = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                let complexity = row.get(3).and_then(|v| v.as_i64()).unwrap_or(0);
                output.push_str(&format!("  #{} c={} — {}\n", name, complexity, file_path));
            }
            output.push('\n');
        }

        // Security-sensitive
        let security_sql = "SELECT name, type, file_path FROM nodes
            WHERE LOWER(name) LIKE '%auth%'
               OR LOWER(name) LIKE '%token%'
               OR LOWER(name) LIKE '%password%'
               OR LOWER(name) LIKE '%secret%'
               OR LOWER(name) LIKE '%crypt%'
               OR LOWER(name) LIKE '%credential%'
               OR LOWER(name) LIKE '%api_key%'
            ORDER BY file_path LIMIT 250";
        let security = state
            .mubase
            .query(security_sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let security_rows: Vec<_> = security
            .rows
            .iter()
            .filter(|row| {
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("");
                !self.should_exclude_path(file_path, &exclude_regexes)
            })
            .take(20)
            .collect();

        if !security_rows.is_empty() {
            output.push_str(&format!(
                "## Security-Sensitive — {} found\n",
                security_rows.len()
            ));
            output.push_str("Code handling authentication, secrets, or credentials:\n\n");
            for row in &security_rows {
                let name = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                let sigil = match node_type {
                    "class" => "$",
                    "function" => "#",
                    _ => "@",
                };
                output.push_str(&format!("  {}{} — {}\n", sigil, name, file_path));
            }
            output.push('\n');
        }

        // Large functions (by line count if available)
        let large_sql = "SELECT name, file_path, (line_end - line_start) as lines FROM nodes
            WHERE type = 'function' AND line_end > line_start
            ORDER BY lines DESC LIMIT 200";
        if let Ok(large) = state.mubase.query(large_sql) {
            let large_rows: Vec<_> = large
                .rows
                .iter()
                .filter(|row| {
                    let file_path = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
                    !self.should_exclude_path(file_path, &exclude_regexes)
                })
                .take(30)
                .collect();

            if !large_rows.is_empty() {
                output.push_str("## Large Functions (by lines)\n");
                output.push_str("Long functions that might need refactoring:\n\n");
                for row in &large_rows {
                    let name = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                    let file_path = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                    let lines = row.get(2).and_then(|v| v.as_i64()).unwrap_or(0);
                    if lines > 50 {
                        output
                            .push_str(&format!("  #{} ({} lines) — {}\n", name, lines, file_path));
                    }
                }
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// WTF: Git archaeology with context
    #[tool(
        description = "Understand why code exists. Shows git history, recent changes, and who works on a file."
    )]
    async fn mu_wtf(
        &self,
        Parameters(params): Parameters<WtfParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let file_path = &params.file;
        let requested_path = PathBuf::from(file_path);
        let mut full_path = if requested_path.is_absolute() {
            requested_path
        } else {
            state.project_root.join(&requested_path)
        };
        if full_path.exists() {
            if let Ok(canonical) = full_path.canonicalize() {
                full_path = canonical;
            }
        }
        let db_file_path = full_path
            .strip_prefix(&state.project_root)
            .map(|p| p.to_string_lossy().replace('\\', "/"))
            .unwrap_or_else(|_| file_path.replace('\\', "/"));

        let mut output = String::new();
        output.push_str(&format!("# WTF: {}\n\n", file_path));

        // Check if file exists
        let file_exists = full_path.exists();
        let file_dir = if file_exists {
            full_path
                .parent()
                .map(|p| p.to_path_buf())
                .unwrap_or_else(|| state.project_root.clone())
        } else if full_path.is_dir() {
            full_path.clone()
        } else {
            full_path
                .parent()
                .map(|p| p.to_path_buf())
                .unwrap_or_else(|| state.project_root.clone())
        };

        let git_root = Command::new("git")
            .args([
                "-C",
                &file_dir.to_string_lossy(),
                "rev-parse",
                "--show-toplevel",
            ])
            .output()
            .ok()
            .filter(|o| o.status.success())
            .and_then(|o| String::from_utf8(o.stdout).ok())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .map(PathBuf::from);

        let repo_relative_path = git_root.as_ref().map(|root| {
            full_path
                .strip_prefix(root)
                .map(|p| p.to_string_lossy().replace('\\', "/"))
                .unwrap_or_else(|_| file_path.replace('\\', "/"))
        });

        let is_tracked = match (&git_root, repo_relative_path.as_deref()) {
            (Some(root), Some(rel_path)) => Command::new("git")
                .args(["-C", &root.to_string_lossy(), "ls-files", "--", rel_path])
                .output()
                .map(|o| o.status.success() && !o.stdout.is_empty())
                .unwrap_or(false),
            _ => false,
        };

        // File info
        if file_exists {
            if let Ok(metadata) = fs::metadata(&full_path) {
                let size = metadata.len();
                output.push_str(&format!("Size: {} bytes\n", size));
            }
            if let Ok(content) = fs::read_to_string(&full_path) {
                let lines = content.lines().count();
                output.push_str(&format!("Lines: {}\n", lines));
            }
        } else {
            output.push_str("⚠ File not found on disk\n");
        }

        if let Some(root) = &git_root {
            output.push_str(&format!("Git root: {}\n", root.display()));
            output.push_str(&format!(
                "Git tracked: {}\n\n",
                if is_tracked { "Yes" } else { "No" }
            ));
        } else {
            output.push_str("Git root: none\n");
            output.push_str("Git tracked: N/A\n\n");
            output.push_str("## Status: No git repository for file path\n");
            output.push_str("Could not find a git repository from this file's directory.\n");
        }

        if is_tracked {
            let git_root = git_root
                .as_ref()
                .ok_or_else(|| McpError::internal_error("git root missing unexpectedly", None))?;
            let rel_path = repo_relative_path
                .as_deref()
                .ok_or_else(|| McpError::internal_error("repo-relative path missing", None))?;

            // Recent commits
            output.push_str("## Recent Commits\n");
            let log = Command::new("git")
                .args([
                    "-C",
                    &git_root.to_string_lossy(),
                    "log",
                    "--format=%h %ad %an: %s",
                    "--date=short",
                    "-10",
                    "--",
                    rel_path,
                ])
                .output();

            if let Ok(log_out) = log {
                let log_str = String::from_utf8_lossy(&log_out.stdout);
                if log_str.is_empty() {
                    output.push_str("  No commits yet (new file?)\n");
                } else {
                    for line in log_str.lines() {
                        output.push_str(&format!("  {}\n", line));
                    }
                }
            }

            // Contributors
            output.push_str("\n## Contributors\n");
            let authors = Command::new("git")
                .args([
                    "-C",
                    &git_root.to_string_lossy(),
                    "shortlog",
                    "-sn",
                    "--",
                    rel_path,
                ])
                .output();

            if let Ok(auth_out) = authors {
                let auth_str = String::from_utf8_lossy(&auth_out.stdout);
                for line in auth_str.lines().take(5) {
                    output.push_str(&format!("  {}\n", line.trim()));
                }
            }

            // First created
            output.push_str("\n## Origin\n");
            let first = Command::new("git")
                .args([
                    "-C",
                    &git_root.to_string_lossy(),
                    "log",
                    "--format=%ad %an: %s",
                    "--date=short",
                    "--diff-filter=A",
                    "--",
                    rel_path,
                ])
                .output();

            if let Ok(first_out) = first {
                let first_str = String::from_utf8_lossy(&first_out.stdout);
                if let Some(line) = first_str.lines().last() {
                    output.push_str(&format!("  Created: {}\n", line));
                }
            }
        } else if git_root.is_some() && file_exists {
            output.push_str("## Status: Untracked file\n");
            output.push_str("This file exists but isn't in git yet.\n");

            // Show first few lines
            if let Ok(content) = fs::read_to_string(&full_path) {
                output.push_str("\n## Preview\n```\n");
                for line in content.lines().take(10) {
                    output.push_str(line);
                    output.push('\n');
                }
                output.push_str("```\n");
            }
        }

        // Database info
        let sql = format!(
            "SELECT type, name, complexity FROM nodes WHERE file_path = '{}' ORDER BY line_start",
            db_file_path.replace('\'', "''")
        );
        if let Ok(nodes) = state.mubase.query(&sql) {
            if !nodes.rows.is_empty() {
                output.push_str("\n## Symbols in file\n");
                for row in &nodes.rows {
                    let node_type = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                    let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                    let complexity = row.get(2).and_then(|v| v.as_i64()).unwrap_or(0);
                    if node_type == "module" {
                        continue;
                    }
                    let sigil = match node_type {
                        "class" => "$",
                        "function" => "#",
                        _ => "@",
                    };
                    output.push_str(&format!("  {}{}", sigil, name));
                    if complexity > 15 {
                        output.push_str(&format!(" (c={})", complexity));
                    }
                    output.push('\n');
                }
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Oracle: Task-aware context retrieval - THE divine feature
    #[tool(
        description = "Get exactly what you need to accomplish a task. Returns must-read code, supporting context, and relevant patterns. Use this when you have a specific task like 'fix bug X' or 'add feature Y'."
    )]
    async fn mu_oracle(
        &self,
        Parameters(params): Parameters<OracleParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let start = Instant::now();

        // Extract task-aware keywords (used for context expansion)
        let keywords = self.extract_task_keywords(&params.task);

        let mut output = String::new();
        output.push_str(&format!("# Oracle: \"{}\"\n", params.task));

        // Get must-read nodes via hybrid search (BM25 + semantic with RRF)
        // This combines keyword matching (finds exact symbol names like "create_hnsw_index")
        // with semantic search (finds conceptually related code)
        let must_read = self.hybrid_search(&state.mubase, &params.task, 7).await;

        // Record this access in session state (activity-dependent awareness)
        {
            let mut session = self.session.lock().await;
            session.record_access(&params.task, &must_read);
        }

        // Collect file paths from must-read for pattern extraction
        let must_read_files: Vec<String> = must_read
            .iter()
            .filter_map(|r| r.file_path.clone())
            .collect();

        // Get supporting context via graph expansion
        let must_read_ids: Vec<&str> = must_read.iter().map(|r| r.name.as_str()).collect();
        let context_nodes = self.get_context_nodes(
            &state.mubase,
            &state.project_root,
            &must_read_ids,
            &keywords,
        );

        // Extract patterns from the codebase relevant to this task
        let patterns = self.extract_patterns(&state.mubase, &keywords, &must_read_files);

        let duration = start.elapsed().as_millis();
        output.push_str(&format!(
            "# {} must-read, {} context, {} patterns | {}ms\n\n",
            must_read.len(),
            context_nodes.len(),
            patterns.len(),
            duration
        ));

        // === MUST READ SECTION ===
        output.push_str("## Must Read\n");
        output.push_str("Critical code for this task:\n\n");

        if must_read.is_empty() {
            output.push_str("No directly relevant code found. Try rephrasing the task.\n\n");
        } else {
            for result in &must_read {
                let sigil = match result.node_type.as_str() {
                    "module" => "!",
                    "class" => "$",
                    "function" => "#",
                    _ => "@",
                };

                output.push_str(&format!(
                    "### {}{} [{}] — {:.0}% relevant\n",
                    sigil,
                    result.name,
                    result.node_type,
                    result.similarity * 100.0
                ));

                if let Some(ref path) = result.file_path {
                    output.push_str(&format!("File: {}\n", path));

                    // Read and show full code
                    let full_path = state.project_root.join(path);
                    if let Ok(content) = fs::read_to_string(&full_path) {
                        if let Some(snippet) =
                            self.extract_snippet(&content, &result.name, &result.node_type)
                        {
                            output.push_str("```\n");
                            output.push_str(&snippet);
                            if !snippet.ends_with('\n') {
                                output.push('\n');
                            }
                            output.push_str("```\n");
                        }
                    }
                }
                output.push('\n');
            }
        }

        // === CONTEXT SECTION ===
        output.push_str("## Context\n");
        output.push_str("Supporting code you should understand:\n\n");

        if context_nodes.is_empty() {
            output.push_str("No additional context found.\n\n");
        } else {
            for (name, node_type, file_path, signature) in &context_nodes {
                let sigil = match node_type.as_str() {
                    "module" => "!",
                    "class" => "$",
                    "function" => "#",
                    _ => "@",
                };
                output.push_str(&format!("{}{} — {}\n", sigil, name, file_path));
                if let Some(sig) = signature {
                    output.push_str(&format!("  `{}`\n", sig));
                }
            }
            output.push('\n');
        }

        // === PATTERNS SECTION ===
        output.push_str("## Patterns\n");
        output.push_str("Relevant conventions in this codebase:\n\n");

        if patterns.is_empty() {
            output.push_str("No specific patterns detected.\n");
        } else {
            for pattern in &patterns {
                output.push_str(&format!("- {}\n", pattern));
            }
        }

        // === SESSION AWARENESS SECTION ===
        // This is the cognitive layer - MU telling the LLM what it knows about the exploration
        output.push_str("\n---\n\n## 🧠 Session Awareness\n\n");

        let session = self.session.lock().await;
        let unique_nodes = session.unique_nodes();
        let query_count = session.query_count();

        output.push_str(&format!(
            "**Exploration**: {} queries, {} unique symbols explored\n\n",
            query_count,
            unique_nodes.len()
        ));

        // Show recently accessed nodes (brief summary)
        if !unique_nodes.is_empty() {
            output.push_str("**Recently accessed**:\n");
            for node in unique_nodes.iter().take(5) {
                let sigil = match node.node_type.as_str() {
                    "module" => "!",
                    "class" => "$",
                    "function" => "#",
                    _ => "@",
                };
                let access_count = session.access_count(&node.name);
                if access_count > 1 {
                    output.push_str(&format!(
                        "- {}{} (×{}) — {}\n",
                        sigil,
                        node.name,
                        access_count,
                        node.file_path.as_deref().unwrap_or("unknown")
                    ));
                } else {
                    output.push_str(&format!(
                        "- {}{} — {}\n",
                        sigil,
                        node.name,
                        node.file_path.as_deref().unwrap_or("unknown")
                    ));
                }
            }
            output.push('\n');
        }

        // Rumination detection - are we stuck in a loop?
        if let Some(repeated_nodes) = session.detect_rumination() {
            output.push_str("**⚠️ Pattern Alert**: You've been revisiting the same nodes:\n");
            for node in &repeated_nodes {
                output.push_str(&format!(
                    "- {} ({}× accessed)\n",
                    node,
                    session.access_count(node)
                ));
            }

            // Find unexplored neighbors as escape routes
            let escape_routes =
                self.find_unexplored_neighbors(&state.mubase, &repeated_nodes, &session);
            if !escape_routes.is_empty() {
                output.push_str("\n**Suggested escape routes** (unexplored neighbors):\n");
                for (name, file_path, relationship) in escape_routes.iter().take(3) {
                    output.push_str(&format!("- {} — {} ({})\n", name, file_path, relationship));
                }
            }
            output.push('\n');
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Get the collaboration protocol template so agents can communicate consistently.
    #[tool(
        description = "Get the shared message template for Codex/Claude collaboration. Use before mu_collab_send to keep planning/implementation/audit handoffs consistent. mu_collab_send enforces this schema."
    )]
    async fn mu_collab_protocol(
        &self,
        Parameters(params): Parameters<CollabProtocolParams>,
    ) -> Result<CallToolResult, McpError> {
        let scope = params
            .phase
            .as_deref()
            .map(|p| p.trim().to_ascii_lowercase())
            .unwrap_or_else(|| "all".to_string());

        let mut output = String::new();
        output.push_str("# collaboration protocol\n\n");
        output.push_str("Use this schema for `mu_collab_send.message`:\n\n");
        output.push_str("Shared envelope:\n");
        output.push_str("- `from`: codex | claude-code\n");
        output.push_str("- `to`: other agent name or `all`\n");
        output.push_str("- `phase`: planning | implementation | audit | general\n");
        output.push_str("- `title`: short subject\n");
        output.push_str("- `requires_response`: true when a decision is blocked\n\n");

        let include_all = scope == "all";
        let include_planning = include_all || scope == "planning" || scope == "plan";
        let include_implementation =
            include_all || scope == "implementation" || scope == "implement";
        let include_audit = include_all || scope == "audit";
        let include_general = include_all || scope == "general" || scope == "sync";

        if !include_planning && !include_implementation && !include_audit && !include_general {
            return Err(McpError::invalid_params(
                "Invalid phase. Use planning, implementation, audit, general, or all.".to_string(),
                None,
            ));
        }

        if include_planning {
            output.push_str("## planning template\n");
            output.push_str("```text\n");
            output.push_str("[Goal]\n");
            output.push_str("<single objective>\n\n");
            output.push_str("[Context]\n");
            output.push_str("<facts + constraints + assumptions>\n\n");
            output.push_str("[Plan]\n");
            output.push_str("1. <step>\n");
            output.push_str("2. <step>\n");
            output.push_str("3. <step>\n\n");
            output.push_str("[Decision Needed]\n");
            output.push_str("<what collaborator must confirm>\n\n");
            output.push_str("[Done When]\n");
            output.push_str("<acceptance criteria>\n");
            output.push_str("```\n\n");
        }

        if include_implementation {
            output.push_str("## implementation template\n");
            output.push_str("```text\n");
            output.push_str("[Change Summary]\n");
            output.push_str("<what was changed>\n\n");
            output.push_str("[Files]\n");
            output.push_str("- <path>: <why>\n\n");
            output.push_str("[Behavior]\n");
            output.push_str("<expected runtime/user-visible behavior>\n\n");
            output.push_str("[Validation]\n");
            output.push_str("- <test/check command + result>\n\n");
            output.push_str("[Risks]\n");
            output.push_str("<known edge cases/regression risk>\n\n");
            output.push_str("[Next Action]\n");
            output.push_str("<what collaborator should do next>\n");
            output.push_str("```\n\n");
        }

        if include_audit {
            output.push_str("## audit template\n");
            output.push_str("```text\n");
            output.push_str("[Scope]\n");
            output.push_str("<what was reviewed>\n\n");
            output.push_str("[Findings]\n");
            output.push_str("1. [severity] <issue> — <file:line>\n");
            output.push_str("2. [severity] <issue> — <file:line>\n\n");
            output.push_str("[Gaps]\n");
            output.push_str("<missing tests/unknowns>\n\n");
            output.push_str("[Verdict]\n");
            output.push_str("<approve / needs changes>\n\n");
            output.push_str("[Requested Follow-up]\n");
            output.push_str("<concrete remediation>\n");
            output.push_str("```\n\n");
        }

        if include_general {
            output.push_str("## general template\n");
            output.push_str("```text\n");
            output.push_str("[Update]\n");
            output.push_str("<status update>\n\n");
            output.push_str("[Blockers]\n");
            output.push_str("<if none, write 'none'>\n\n");
            output.push_str("[Ask]\n");
            output.push_str("<explicit question/action requested>\n");
            output.push_str("```\n");
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Open a collaboration session shared across MCP clients (Codex, Claude Code, etc.)
    #[tool(
        description = "Create or reuse a cross-agent collaboration session. Use this first so Codex and Claude Code can exchange planning/implementation/audit messages."
    )]
    async fn mu_collab_open(
        &self,
        Parameters(params): Parameters<CollabOpenParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        if params.objective.trim().is_empty() {
            return Err(McpError::invalid_params(
                "objective cannot be empty".to_string(),
                None,
            ));
        }

        let requested = params
            .session_id
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string())
            .unwrap_or_else(|| Self::default_collab_session_id(&params.objective));
        let session_id = Self::sanitize_identifier(&requested)?;

        let participants = if let Some(raw) = params.participants {
            let mut out = Vec::new();
            for agent in raw {
                let canonical = Self::sanitize_identifier(&agent)?;
                if !out.contains(&canonical) {
                    out.push(canonical);
                }
            }
            if out.is_empty() {
                vec!["codex".to_string(), "claude-code".to_string()]
            } else {
                out
            }
        } else {
            vec!["codex".to_string(), "claude-code".to_string()]
        };

        let collab_root = Self::collab_root(&state.project_root);
        let session_dir = collab_root.join(&session_id);
        let messages_dir = session_dir.join("messages");
        let receipts_dir = session_dir.join("receipts");

        fs::create_dir_all(&messages_dir).map_err(|e| {
            McpError::internal_error(
                format!("Failed to create collaboration directory: {}", e),
                None,
            )
        })?;
        fs::create_dir_all(&receipts_dir).map_err(|e| {
            McpError::internal_error(
                format!("Failed to create collaboration receipts directory: {}", e),
                None,
            )
        })?;

        let meta_path = session_dir.join("session.json");
        if !meta_path.exists() {
            let meta = CollabSessionMeta {
                session_id: session_id.clone(),
                objective: params.objective.trim().to_string(),
                participants: participants.clone(),
                created_at_ms: Self::now_unix_ms(),
            };
            let payload = serde_json::to_string_pretty(&meta).map_err(|e| {
                McpError::internal_error(format!("Session serialization error: {}", e), None)
            })?;
            fs::write(&meta_path, payload).map_err(|e| {
                McpError::internal_error(
                    format!("Failed to persist collaboration session: {}", e),
                    None,
                )
            })?;
        }

        let mut output = String::new();
        output.push_str("# collaboration session ready\n\n");
        output.push_str(&format!("session_id: `{}`\n", session_id));
        output.push_str(&format!("objective: {}\n", params.objective.trim()));
        output.push_str(&format!("participants: {}\n", participants.join(", ")));
        output.push_str(&format!("storage: {}\n\n", session_dir.display()));
        output.push_str("Next steps:\n");
        output.push_str("- Use `mu_collab_protocol` to fetch the shared message template.\n");
        output.push_str("- Use `mu_collab_send` to post structured updates.\n");
        output.push_str("- Use `mu_collab_ask` for automated request/reply via target CLI.\n");
        output.push_str("- Use `mu_collab_ask_async` for long-running automated exchanges.\n");
        output.push_str("- Poll async jobs with `mu_collab_job_status`.\n");
        output.push_str("- Use `mu_collab_inbox` from each agent to read/ack messages.\n");
        output.push_str(
            "- Use `phase` = planning, implementation, or audit to coordinate work mode.\n",
        );
        output.push_str("\nQuick protocol reference:\n");
        output.push_str("- planning: [Goal] [Context] [Plan] [Decision Needed] [Done When]\n");
        output.push_str(
            "- implementation: [Change Summary] [Files] [Behavior] [Validation] [Risks] [Next Action]\n",
        );
        output.push_str("- audit: [Scope] [Findings] [Gaps] [Verdict] [Requested Follow-up]\n");
        output.push_str("- general: [Update] [Blockers] [Ask]\n");

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Send a collaboration message into a session mailbox.
    #[tool(
        description = "Send a message from one agent to another (or all) within a collaboration session. Supports planning, implementation, and audit phases with strict protocol validation."
    )]
    async fn mu_collab_send(
        &self,
        Parameters(params): Parameters<CollabSendParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        if params.message.trim().is_empty() {
            return Err(McpError::invalid_params(
                "message cannot be empty".to_string(),
                None,
            ));
        }

        let session_id = Self::sanitize_identifier(&params.session_id)?;
        let from = Self::sanitize_identifier(&params.from)?;
        let to = params
            .to
            .as_deref()
            .map(Self::sanitize_identifier)
            .transpose()?
            .unwrap_or_else(|| "all".to_string());
        let phase = Self::normalize_collab_phase(params.phase.as_deref())?;
        Self::validate_collab_message_schema(&phase, params.message.trim())?;

        let session_dir = Self::collab_root(&state.project_root).join(&session_id);
        let meta_path = session_dir.join("session.json");
        if !meta_path.exists() {
            return Err(McpError::invalid_params(
                format!(
                    "Unknown collaboration session '{}'. Call mu_collab_open first.",
                    session_id
                ),
                None,
            ));
        }

        let messages_dir = session_dir.join("messages");
        fs::create_dir_all(&messages_dir).map_err(|e| {
            McpError::internal_error(
                format!("Failed to create collaboration messages directory: {}", e),
                None,
            )
        })?;

        let message_id = Self::next_collab_message_id();
        let entry = CollabMessage {
            id: message_id.clone(),
            session_id: session_id.clone(),
            from: from.clone(),
            to: to.clone(),
            phase: phase.clone(),
            title: params
                .title
                .as_ref()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty()),
            message: params.message.trim().to_string(),
            related_files: params.related_files.unwrap_or_default(),
            related_symbols: params.related_symbols.unwrap_or_default(),
            requires_response: params.requires_response.unwrap_or(false),
            created_at_ms: Self::now_unix_ms(),
        };

        let message_path = messages_dir.join(format!("{}.json", message_id));
        let payload = serde_json::to_vec_pretty(&entry).map_err(|e| {
            McpError::internal_error(format!("Message serialization error: {}", e), None)
        })?;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&message_path)
            .map_err(|e| {
                McpError::internal_error(format!("Failed to create message file: {}", e), None)
            })?;
        file.write_all(&payload).map_err(|e| {
            McpError::internal_error(format!("Failed to write message file: {}", e), None)
        })?;

        let mut output = String::new();
        output.push_str("# collaboration message sent\n\n");
        output.push_str(&format!("id: `{}`\n", message_id));
        output.push_str(&format!("session_id: `{}`\n", session_id));
        output.push_str(&format!("from: `{}`\n", from));
        output.push_str(&format!("to: `{}`\n", to));
        output.push_str(&format!("phase: `{}`\n", phase));
        output.push_str("protocol_validated: `true`\n");
        if let Some(title) = &entry.title {
            output.push_str(&format!("title: {}\n", title));
        }
        output.push_str(&format!("stored_at: {}\n", message_path.display()));

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Send a collab message and automatically invoke the target agent CLI for a reply.
    #[tool(
        description = "Automated cross-agent handoff: stores your message, calls target CLI command, then stores target reply back into the same session. Supports agent presets and working_dir."
    )]
    async fn mu_collab_ask(
        &self,
        Parameters(params): Parameters<CollabAskParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        if params.message.trim().is_empty() {
            return Err(McpError::invalid_params(
                "message cannot be empty".to_string(),
                None,
            ));
        }
        if params.target_command.trim().is_empty() {
            return Err(McpError::invalid_params(
                "target_command cannot be empty".to_string(),
                None,
            ));
        }

        let session_id = Self::sanitize_identifier(&params.session_id)?;
        let from = Self::sanitize_identifier(&params.from)?;
        let to = Self::sanitize_identifier(&params.to)?;
        let phase = Self::normalize_collab_phase(params.phase.as_deref())?;
        let auto_wrap_request_protocol = params.auto_wrap_request_protocol.unwrap_or(false);
        let enforce_request_protocol = params.enforce_request_protocol.unwrap_or(false);

        let session_dir = Self::collab_root(&state.project_root).join(&session_id);
        if !session_dir.join("session.json").exists() {
            return Err(McpError::invalid_params(
                format!(
                    "Unknown collaboration session '{}'. Call mu_collab_open first.",
                    session_id
                ),
                None,
            ));
        }

        let request_title = params
            .title
            .as_ref()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        let request_requires_response = params.requires_response.unwrap_or(true);
        let mut request_message = params.message.trim().to_string();
        if auto_wrap_request_protocol && !Self::message_matches_protocol(&phase, &request_message) {
            request_message = Self::auto_wrap_protocol_message(&phase, &request_message);
        }
        if enforce_request_protocol {
            Self::validate_collab_message_schema(&phase, &request_message)?;
        }
        let related_files_for_resolution = params.related_files.clone().unwrap_or_default();
        let related_symbols = params.related_symbols.clone().unwrap_or_default();

        let (request_id, request_path) = Self::persist_collab_message(
            &session_dir,
            CollabMessage {
                id: Self::next_collab_message_id(),
                session_id: session_id.clone(),
                from: from.clone(),
                to: to.clone(),
                phase: phase.clone(),
                title: request_title.clone(),
                message: request_message.clone(),
                related_files: related_files_for_resolution.clone(),
                related_symbols,
                requires_response: request_requires_response,
                created_at_ms: Self::now_unix_ms(),
            },
        )?;

        let timeout_secs = params.timeout_seconds.unwrap_or(90).clamp(5, 600);
        let max_chars = params
            .max_response_chars
            .unwrap_or(40_000)
            .clamp(500, 200_000);
        let working_dir = Self::resolve_collab_working_dir(
            &state.project_root,
            params.working_dir.as_deref(),
            &related_files_for_resolution,
            params.auto_resolve_git_root.unwrap_or(true),
        )?;
        let mut raw_target_args = params.target_args.unwrap_or_default();
        raw_target_args = Self::apply_collab_agent_preset(
            params.agent_preset.as_deref(),
            params.target_command.as_str(),
            raw_target_args,
            &working_dir,
        );
        let command_args = Self::resolve_collab_command_args(
            raw_target_args,
            &session_id,
            &from,
            &to,
            &phase,
            &request_message,
        );

        let mut cmd = tokio::process::Command::new(params.target_command.trim());
        cmd.args(&command_args);
        cmd.current_dir(&working_dir);
        cmd.stdin(Stdio::null());
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let output = tokio::time::timeout(Duration::from_secs(timeout_secs), cmd.output())
            .await
            .map_err(|_| {
                McpError::internal_error(
                    format!("Target CLI timed out after {}s", timeout_secs),
                    None,
                )
            })?
            .map_err(|e| {
                McpError::internal_error(format!("Failed to execute target CLI: {}", e), None)
            })?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            let enriched = Self::enrich_target_cli_error(params.target_command.trim(), &stderr);
            return Err(McpError::internal_error(
                format!(
                    "Target CLI exited with status {}. stderr: {}",
                    output.status,
                    if enriched.is_empty() {
                        "<empty>".to_string()
                    } else {
                        enriched
                    }
                ),
                None,
            ));
        }

        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if stdout.is_empty() {
            return Err(McpError::internal_error(
                "Target CLI returned empty stdout response".to_string(),
                None,
            ));
        }

        let response_text: String = stdout.chars().take(max_chars).collect();
        let response_phase = Self::normalize_collab_phase(params.response_phase.as_deref())?;
        if params.enforce_response_protocol.unwrap_or(false) {
            Self::validate_collab_message_schema(&response_phase, &response_text)?;
        }

        let response_title = params
            .response_title
            .as_ref()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .or_else(|| Some(format!("Auto reply from {}", to)));

        let (response_id, response_path) = Self::persist_collab_message(
            &session_dir,
            CollabMessage {
                id: Self::next_collab_message_id(),
                session_id: session_id.clone(),
                from: to.clone(),
                to: from.clone(),
                phase: response_phase.clone(),
                title: response_title,
                message: response_text.clone(),
                related_files: Vec::new(),
                related_symbols: Vec::new(),
                requires_response: false,
                created_at_ms: Self::now_unix_ms(),
            },
        )?;

        let mut out = String::new();
        out.push_str("# collaboration automated exchange complete\n\n");
        out.push_str(&format!("session_id: `{}`\n", session_id));
        out.push_str(&format!("request_message_id: `{}`\n", request_id));
        out.push_str(&format!("request_stored_at: {}\n", request_path.display()));
        out.push_str(&format!("response_message_id: `{}`\n", response_id));
        out.push_str(&format!(
            "response_stored_at: {}\n",
            response_path.display()
        ));
        out.push_str(&format!("response_phase: `{}`\n", response_phase));
        out.push_str(&format!(
            "response_chars: {}\n\n",
            response_text.chars().count()
        ));
        out.push_str("## Response\n");
        out.push_str(&response_text);
        out.push('\n');

        Ok(CallToolResult::success(vec![Content::text(out)]))
    }

    /// Asynchronous variant of mu_collab_ask.
    #[tool(
        description = "Async automated handoff: stores request, launches target CLI in background, and returns a job id. Supports agent presets and working_dir. Poll/wait with mu_collab_job_status."
    )]
    async fn mu_collab_ask_async(
        &self,
        Parameters(params): Parameters<CollabAskParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        if params.message.trim().is_empty() {
            return Err(McpError::invalid_params(
                "message cannot be empty".to_string(),
                None,
            ));
        }
        if params.target_command.trim().is_empty() {
            return Err(McpError::invalid_params(
                "target_command cannot be empty".to_string(),
                None,
            ));
        }

        let session_id = Self::sanitize_identifier(&params.session_id)?;
        let from = Self::sanitize_identifier(&params.from)?;
        let to = Self::sanitize_identifier(&params.to)?;
        let phase = Self::normalize_collab_phase(params.phase.as_deref())?;
        let auto_wrap_request_protocol = params.auto_wrap_request_protocol.unwrap_or(false);
        let enforce_request_protocol = params.enforce_request_protocol.unwrap_or(false);

        let session_dir = Self::collab_root(&state.project_root).join(&session_id);
        if !session_dir.join("session.json").exists() {
            return Err(McpError::invalid_params(
                format!(
                    "Unknown collaboration session '{}'. Call mu_collab_open first.",
                    session_id
                ),
                None,
            ));
        }

        let request_title = params
            .title
            .as_ref()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        let request_requires_response = params.requires_response.unwrap_or(true);
        let mut request_message = params.message.trim().to_string();
        if auto_wrap_request_protocol && !Self::message_matches_protocol(&phase, &request_message) {
            request_message = Self::auto_wrap_protocol_message(&phase, &request_message);
        }
        if enforce_request_protocol {
            Self::validate_collab_message_schema(&phase, &request_message)?;
        }
        let related_files_for_resolution = params.related_files.clone().unwrap_or_default();
        let related_symbols = params.related_symbols.clone().unwrap_or_default();

        let (request_id, request_path) = Self::persist_collab_message(
            &session_dir,
            CollabMessage {
                id: Self::next_collab_message_id(),
                session_id: session_id.clone(),
                from: from.clone(),
                to: to.clone(),
                phase: phase.clone(),
                title: request_title.clone(),
                message: request_message.clone(),
                related_files: related_files_for_resolution.clone(),
                related_symbols,
                requires_response: request_requires_response,
                created_at_ms: Self::now_unix_ms(),
            },
        )?;

        let timeout_secs = params.timeout_seconds.unwrap_or(90).clamp(5, 600);
        let max_chars = params
            .max_response_chars
            .unwrap_or(40_000)
            .clamp(500, 200_000);
        let working_dir = Self::resolve_collab_working_dir(
            &state.project_root,
            params.working_dir.as_deref(),
            &related_files_for_resolution,
            params.auto_resolve_git_root.unwrap_or(true),
        )?;
        let target_command = params.target_command.trim().to_string();
        let mut raw_target_args = params.target_args.unwrap_or_default();
        raw_target_args = Self::apply_collab_agent_preset(
            params.agent_preset.as_deref(),
            &target_command,
            raw_target_args,
            &working_dir,
        );
        let command_args = Self::resolve_collab_command_args(
            raw_target_args,
            &session_id,
            &from,
            &to,
            &phase,
            &request_message,
        );
        let response_phase = Self::normalize_collab_phase(params.response_phase.as_deref())?;
        let response_title = params
            .response_title
            .as_ref()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .or_else(|| Some(format!("Auto reply from {}", to.clone())));
        let enforce_response_protocol = params.enforce_response_protocol.unwrap_or(false);

        let job_id = format!("job-{}", Self::next_collab_message_id());
        let jobs_dir = Self::collab_jobs_dir(&session_dir);
        fs::create_dir_all(&jobs_dir).map_err(|e| {
            McpError::internal_error(
                format!("Failed to create collaboration jobs directory: {}", e),
                None,
            )
        })?;
        let job_path = Self::collab_job_path(&session_dir, &job_id);

        let job_record = CollabJobRecord {
            job_id: job_id.clone(),
            session_id: session_id.clone(),
            status: "queued".to_string(),
            request_message_id: request_id.clone(),
            request_path: request_path.display().to_string(),
            target_command: target_command.clone(),
            target_args: command_args.clone(),
            working_dir: working_dir.display().to_string(),
            timeout_seconds: timeout_secs,
            created_at_ms: Self::now_unix_ms(),
            started_at_ms: None,
            finished_at_ms: None,
            response_phase: Some(response_phase.clone()),
            response_message_id: None,
            response_path: None,
            response_chars: None,
            error: None,
        };
        Self::persist_collab_job(&job_path, &job_record)?;

        let task_session_dir = session_dir.clone();
        let task_working_dir = working_dir.clone();
        let task_session_id = session_id.clone();
        let task_from = from.clone();
        let task_to = to.clone();
        let task_job_path = job_path.clone();
        let task_target_command = target_command.clone();

        tokio::spawn(async move {
            let mut job = job_record;
            job.status = "running".to_string();
            job.started_at_ms = Some(Self::now_unix_ms());
            let _ = Self::persist_collab_job(&task_job_path, &job);

            let mut cmd = tokio::process::Command::new(&task_target_command);
            cmd.args(&command_args);
            cmd.current_dir(&task_working_dir);
            cmd.stdin(Stdio::null());
            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let exec_result =
                tokio::time::timeout(Duration::from_secs(timeout_secs), cmd.output()).await;

            match exec_result {
                Err(_) => {
                    job.status = "failed".to_string();
                    job.error = Some(format!("Target CLI timed out after {}s", timeout_secs));
                }
                Ok(Err(err)) => {
                    job.status = "failed".to_string();
                    job.error = Some(format!("Failed to execute target CLI: {}", err));
                }
                Ok(Ok(output)) => {
                    if !output.status.success() {
                        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
                        let enriched = Self::enrich_target_cli_error(&task_target_command, &stderr);
                        job.status = "failed".to_string();
                        job.error = Some(format!(
                            "Target CLI exited with status {}. stderr: {}",
                            output.status,
                            if enriched.is_empty() {
                                "<empty>".to_string()
                            } else {
                                enriched
                            }
                        ));
                    } else {
                        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
                        if stdout.is_empty() {
                            job.status = "failed".to_string();
                            job.error =
                                Some("Target CLI returned empty stdout response".to_string());
                        } else {
                            let response_text: String = stdout.chars().take(max_chars).collect();
                            let validation_result = if enforce_response_protocol {
                                Self::validate_collab_message_schema(
                                    &response_phase,
                                    &response_text,
                                )
                            } else {
                                Ok(())
                            };

                            match validation_result {
                                Err(err) => {
                                    job.status = "failed".to_string();
                                    job.error = Some(format!(
                                        "Response protocol validation failed: {}",
                                        err
                                    ));
                                }
                                Ok(()) => {
                                    let persist_result = Self::persist_collab_message(
                                        &task_session_dir,
                                        CollabMessage {
                                            id: Self::next_collab_message_id(),
                                            session_id: task_session_id.clone(),
                                            from: task_to.clone(),
                                            to: task_from.clone(),
                                            phase: response_phase.clone(),
                                            title: response_title.clone(),
                                            message: response_text.clone(),
                                            related_files: Vec::new(),
                                            related_symbols: Vec::new(),
                                            requires_response: false,
                                            created_at_ms: Self::now_unix_ms(),
                                        },
                                    );

                                    match persist_result {
                                        Ok((response_id, response_path)) => {
                                            job.status = "succeeded".to_string();
                                            job.response_message_id = Some(response_id);
                                            job.response_path =
                                                Some(response_path.display().to_string());
                                            job.response_chars =
                                                Some(response_text.chars().count());
                                            job.error = None;
                                        }
                                        Err(err) => {
                                            job.status = "failed".to_string();
                                            job.error = Some(format!(
                                                "Failed to persist response: {}",
                                                err
                                            ));
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            job.finished_at_ms = Some(Self::now_unix_ms());
            let _ = Self::persist_collab_job(&task_job_path, &job);
        });

        let mut out = String::new();
        out.push_str("# collaboration async job queued\n\n");
        out.push_str(&format!("session_id: `{}`\n", session_id));
        out.push_str(&format!("job_id: `{}`\n", job_id));
        out.push_str(&format!("request_message_id: `{}`\n", request_id));
        out.push_str(&format!("job_status: `queued`\n"));
        out.push_str(&format!("job_path: {}\n\n", job_path.display()));
        out.push_str(
            "Poll progress with `mu_collab_job_status` (or use `wait=true` to block until done).\n",
        );

        Ok(CallToolResult::success(vec![Content::text(out)]))
    }

    /// Check status of an async collab automation job.
    #[tool(
        description = "Get status for mu_collab_ask_async job id, including response message id/path when complete. Supports blocking wait."
    )]
    async fn mu_collab_job_status(
        &self,
        Parameters(params): Parameters<CollabJobStatusParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let session_id = Self::sanitize_identifier(&params.session_id)?;
        let job_id = Self::sanitize_identifier(&params.job_id)?;
        let session_dir = Self::collab_root(&state.project_root).join(&session_id);
        let job_path = Self::collab_job_path(&session_dir, &job_id);

        if !job_path.exists() {
            return Err(McpError::invalid_params(
                format!("Unknown job '{}' for session '{}'.", job_id, session_id),
                None,
            ));
        }

        let wait = params.wait.unwrap_or(false);
        let wait_timeout_secs = params.wait_timeout_seconds.unwrap_or(300).clamp(1, 3600);
        let poll_interval_ms = params.poll_interval_ms.unwrap_or(500).clamp(100, 5000);
        let started = Instant::now();
        let wait_deadline = Duration::from_secs(wait_timeout_secs);
        let mut timed_out = false;

        let job = loop {
            match Self::load_collab_job(&job_path) {
                Ok(job) => {
                    if !wait || Self::is_terminal_job_status(&job.status) {
                        break job;
                    }
                    if started.elapsed() >= wait_deadline {
                        timed_out = true;
                        break job;
                    }
                }
                Err(err) => {
                    if !wait || started.elapsed() >= wait_deadline {
                        return Err(err);
                    }
                }
            }

            tokio::time::sleep(Duration::from_millis(poll_interval_ms)).await;
        };

        let elapsed_ms = started.elapsed().as_millis();
        let mut out = String::new();
        out.push_str("# collaboration job status\n\n");
        out.push_str(&format!("session_id: `{}`\n", job.session_id));
        out.push_str(&format!("job_id: `{}`\n", job.job_id));
        out.push_str(&format!("status: `{}`\n", job.status));
        out.push_str(&format!("waited: `{}`\n", wait));
        out.push_str(&format!("timed_out: `{}`\n", timed_out));
        out.push_str(&format!("elapsed_ms: {}\n", elapsed_ms));
        out.push_str(&format!(
            "request_message_id: `{}`\n",
            job.request_message_id
        ));
        out.push_str(&format!("request_path: {}\n", job.request_path));
        out.push_str(&format!("target_command: `{}`\n", job.target_command));
        out.push_str(&format!("working_dir: {}\n", job.working_dir));
        out.push_str(&format!("timeout_seconds: {}\n", job.timeout_seconds));
        out.push_str(&format!("created_at_ms: {}\n", job.created_at_ms));
        if let Some(started) = job.started_at_ms {
            out.push_str(&format!("started_at_ms: {}\n", started));
        }
        if let Some(finished) = job.finished_at_ms {
            out.push_str(&format!("finished_at_ms: {}\n", finished));
        }
        if let Some(ref phase) = job.response_phase {
            out.push_str(&format!("response_phase: `{}`\n", phase));
        }
        if let Some(ref response_id) = job.response_message_id {
            out.push_str(&format!("response_message_id: `{}`\n", response_id));
        }
        if let Some(ref response_path) = job.response_path {
            out.push_str(&format!("response_path: {}\n", response_path));
        }
        if let Some(chars) = job.response_chars {
            out.push_str(&format!("response_chars: {}\n", chars));
        }
        if let Some(ref err) = job.error {
            out.push_str(&format!("error: {}\n", err));
        }

        let include_excerpt = params.include_response_excerpt.unwrap_or(true);
        let excerpt_chars = params
            .response_excerpt_chars
            .unwrap_or(2000)
            .clamp(100, 20_000);
        if include_excerpt {
            if let Some(ref response_path) = job.response_path {
                if let Ok(raw) = fs::read_to_string(response_path) {
                    if let Ok(message) = serde_json::from_str::<CollabMessage>(&raw) {
                        let excerpt: String = message.message.chars().take(excerpt_chars).collect();
                        out.push_str("\n## Response Excerpt\n");
                        out.push_str(&excerpt);
                        out.push('\n');
                    }
                }
            }
        }

        Ok(CallToolResult::success(vec![Content::text(out)]))
    }

    /// Read collaboration messages for an agent, with unread checkpoints.
    #[tool(
        description = "Read collaboration inbox for an agent. Supports unread checkpoints so Codex and Claude Code can synchronize incrementally."
    )]
    async fn mu_collab_inbox(
        &self,
        Parameters(params): Parameters<CollabInboxParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let session_id = Self::sanitize_identifier(&params.session_id)?;
        let agent = Self::sanitize_identifier(&params.agent)?;
        let unread_only = params.unread_only.unwrap_or(true);
        let mark_read = params.mark_read.unwrap_or(true);
        let limit = params.limit.unwrap_or(20).clamp(1, 100);
        let phase_filter = if let Some(phase) = params.phase.as_deref() {
            Some(Self::normalize_collab_phase(Some(phase))?)
        } else {
            None
        };

        let session_dir = Self::collab_root(&state.project_root).join(&session_id);
        if !session_dir.join("session.json").exists() {
            return Err(McpError::invalid_params(
                format!(
                    "Unknown collaboration session '{}'. Call mu_collab_open first.",
                    session_id
                ),
                None,
            ));
        }

        let messages_dir = session_dir.join("messages");
        let receipts_dir = session_dir.join("receipts");
        fs::create_dir_all(&messages_dir).map_err(|e| {
            McpError::internal_error(
                format!("Failed to access collaboration messages directory: {}", e),
                None,
            )
        })?;
        fs::create_dir_all(&receipts_dir).map_err(|e| {
            McpError::internal_error(
                format!("Failed to access collaboration receipts directory: {}", e),
                None,
            )
        })?;

        let receipt_path = receipts_dir.join(format!("{}.json", agent));
        let mut receipt = if receipt_path.exists() {
            fs::read_to_string(&receipt_path)
                .ok()
                .and_then(|s| serde_json::from_str::<CollabReceipt>(&s).ok())
                .unwrap_or_else(|| CollabReceipt {
                    agent: agent.clone(),
                    ..Default::default()
                })
        } else {
            CollabReceipt {
                agent: agent.clone(),
                ..Default::default()
            }
        };

        let last_seen = receipt.last_seen_message_id.clone();
        let mut messages = Vec::new();

        let entries = fs::read_dir(&messages_dir).map_err(|e| {
            McpError::internal_error(format!("Failed to read inbox directory: {}", e), None)
        })?;
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }

            let message: CollabMessage = match fs::read_to_string(&path)
                .ok()
                .and_then(|s| serde_json::from_str::<CollabMessage>(&s).ok())
            {
                Some(m) => m,
                None => continue,
            };

            let directed_to_agent = message.to == "all" || message.to == agent;
            if !directed_to_agent {
                continue;
            }

            if let Some(ref phase) = phase_filter {
                if &message.phase != phase {
                    continue;
                }
            }

            if unread_only {
                if let Some(ref last) = last_seen {
                    if message.id <= *last {
                        continue;
                    }
                }
            }

            messages.push(message);
        }

        messages.sort_by(|a, b| a.id.cmp(&b.id));
        if messages.len() > limit {
            messages.truncate(limit);
        }

        let mut output = String::new();
        output.push_str("# collaboration inbox\n\n");
        output.push_str(&format!("session_id: `{}`\n", session_id));
        output.push_str(&format!("agent: `{}`\n", agent));
        output.push_str(&format!("messages: {}\n\n", messages.len()));

        if messages.is_empty() {
            output.push_str("No messages matched this query.\n");
        } else {
            for msg in &messages {
                output.push_str(&format!(
                    "## {} [{}] {} -> {}\n",
                    msg.id, msg.phase, msg.from, msg.to
                ));
                if let Some(title) = &msg.title {
                    output.push_str(&format!("title: {}\n", title));
                }
                if msg.requires_response {
                    output.push_str("requires_response: true\n");
                }
                if !msg.related_files.is_empty() {
                    output.push_str(&format!("files: {}\n", msg.related_files.join(", ")));
                }
                if !msg.related_symbols.is_empty() {
                    output.push_str(&format!("symbols: {}\n", msg.related_symbols.join(", ")));
                }
                output.push_str("\n");
                output.push_str(&msg.message);
                output.push_str("\n\n");
            }
        }

        if mark_read {
            if let Some(last_msg) = messages.last() {
                receipt.last_seen_message_id = Some(last_msg.id.clone());
                receipt.updated_at_ms = Self::now_unix_ms();
                let payload = serde_json::to_string_pretty(&receipt).map_err(|e| {
                    McpError::internal_error(format!("Failed to serialize receipt: {}", e), None)
                })?;
                fs::write(&receipt_path, payload).map_err(|e| {
                    McpError::internal_error(format!("Failed to persist receipt: {}", e), None)
                })?;
                output.push_str(&format!("checkpoint: `{}`\n", last_msg.id));
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }
}

// Helper methods
impl MuMcpServer {
    fn collab_root(project_root: &Path) -> PathBuf {
        project_root.join(".mu").join("collab")
    }

    fn collab_jobs_dir(session_dir: &Path) -> PathBuf {
        session_dir.join("jobs")
    }

    fn collab_job_path(session_dir: &Path, job_id: &str) -> PathBuf {
        Self::collab_jobs_dir(session_dir).join(format!("{}.json", job_id))
    }

    fn persist_collab_message(
        session_dir: &Path,
        message: CollabMessage,
    ) -> Result<(String, PathBuf), McpError> {
        let messages_dir = session_dir.join("messages");
        fs::create_dir_all(&messages_dir).map_err(|e| {
            McpError::internal_error(
                format!("Failed to create collaboration messages directory: {}", e),
                None,
            )
        })?;

        let message_id = message.id.clone();
        let message_path = messages_dir.join(format!("{}.json", message_id));
        let payload = serde_json::to_vec_pretty(&message).map_err(|e| {
            McpError::internal_error(format!("Message serialization error: {}", e), None)
        })?;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&message_path)
            .map_err(|e| {
                McpError::internal_error(format!("Failed to create message file: {}", e), None)
            })?;
        file.write_all(&payload).map_err(|e| {
            McpError::internal_error(format!("Failed to write message file: {}", e), None)
        })?;

        Ok((message_id, message_path))
    }

    fn persist_collab_job(job_path: &Path, job: &CollabJobRecord) -> Result<(), McpError> {
        if let Some(parent) = job_path.parent() {
            fs::create_dir_all(parent).map_err(|e| {
                McpError::internal_error(
                    format!("Failed to create collaboration jobs directory: {}", e),
                    None,
                )
            })?;
        }

        let payload = serde_json::to_string_pretty(job).map_err(|e| {
            McpError::internal_error(format!("Job serialization error: {}", e), None)
        })?;
        fs::write(job_path, payload)
            .map_err(|e| McpError::internal_error(format!("Failed to persist job: {}", e), None))?;

        Ok(())
    }

    fn load_collab_job(job_path: &Path) -> Result<CollabJobRecord, McpError> {
        let raw = fs::read_to_string(job_path).map_err(|e| {
            McpError::internal_error(format!("Failed to read job file: {}", e), None)
        })?;
        serde_json::from_str::<CollabJobRecord>(&raw)
            .map_err(|e| McpError::internal_error(format!("Failed to parse job file: {}", e), None))
    }

    fn is_terminal_job_status(status: &str) -> bool {
        matches!(status, "succeeded" | "failed")
    }

    fn resolve_collab_working_dir(
        project_root: &Path,
        working_dir: Option<&str>,
        related_files: &[String],
        auto_resolve_git_root: bool,
    ) -> Result<PathBuf, McpError> {
        if let Some(raw) = working_dir {
            let trimmed = raw.trim();
            if trimmed.is_empty() {
                return Err(McpError::invalid_params(
                    "working_dir cannot be empty when provided".to_string(),
                    None,
                ));
            }
            let candidate = if Path::new(trimmed).is_absolute() {
                PathBuf::from(trimmed)
            } else {
                project_root.join(trimmed)
            };
            if !candidate.exists() || !candidate.is_dir() {
                return Err(McpError::invalid_params(
                    format!(
                        "working_dir '{}' does not exist or is not a directory",
                        candidate.display()
                    ),
                    None,
                ));
            }
            return Ok(candidate);
        }

        if auto_resolve_git_root {
            if let Some(root) = Self::find_git_root_from_related_files(project_root, related_files)
            {
                return Ok(root);
            }
            if let Some(root) = Self::find_git_root(project_root) {
                return Ok(root);
            }
        }

        Ok(project_root.to_path_buf())
    }

    fn find_git_root_from_related_files(
        project_root: &Path,
        related_files: &[String],
    ) -> Option<PathBuf> {
        for raw in related_files {
            let trimmed = raw.trim();
            if trimmed.is_empty() {
                continue;
            }

            let candidate = if Path::new(trimmed).is_absolute() {
                PathBuf::from(trimmed)
            } else {
                project_root.join(trimmed)
            };

            let start = if candidate.is_dir() {
                candidate
            } else {
                candidate
                    .parent()
                    .map(Path::to_path_buf)
                    .unwrap_or(candidate)
            };

            if let Some(root) = Self::find_git_root(&start) {
                return Some(root);
            }
        }

        None
    }

    fn find_git_root(start: &Path) -> Option<PathBuf> {
        let output = Command::new("git")
            .args([
                "-C",
                &start.to_string_lossy(),
                "rev-parse",
                "--show-toplevel",
            ])
            .output()
            .ok()?;
        if !output.status.success() {
            return None;
        }
        let text = String::from_utf8_lossy(&output.stdout);
        let path = text.lines().next()?.trim();
        if path.is_empty() {
            None
        } else {
            Some(PathBuf::from(path))
        }
    }

    fn apply_collab_agent_preset(
        preset: Option<&str>,
        target_command: &str,
        args: Vec<String>,
        working_dir: &Path,
    ) -> Vec<String> {
        let preset_name = preset
            .map(|s| s.trim().to_ascii_lowercase())
            .unwrap_or_default();

        match preset_name.as_str() {
            "codex_exec" => {
                if args.is_empty() {
                    vec![
                        "exec".to_string(),
                        "-C".to_string(),
                        working_dir.display().to_string(),
                        "{{message}}".to_string(),
                    ]
                } else {
                    args
                }
            }
            "claude_print" => {
                if args.is_empty() {
                    vec!["-p".to_string(), "{{message}}".to_string()]
                } else {
                    args
                }
            }
            _ => {
                if args.is_empty() && target_command.trim().eq_ignore_ascii_case("codex") {
                    vec![
                        "exec".to_string(),
                        "-C".to_string(),
                        working_dir.display().to_string(),
                        "{{message}}".to_string(),
                    ]
                } else {
                    args
                }
            }
        }
    }

    fn enrich_target_cli_error(command: &str, stderr: &str) -> String {
        let mut hints = Vec::new();
        let cmd_name = Path::new(command)
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or(command)
            .to_ascii_lowercase();

        if stderr.contains("unexpected argument") {
            hints.push(format!(
                "Check target_args against `{}` help output.",
                cmd_name
            ));
            if cmd_name == "codex" {
                hints.push(
                    "Codex non-interactive pattern: args like [\"exec\",\"-C\",\"<git-repo>\",\"{{message}}\"]".to_string(),
                );
            }
        }

        if stderr.contains("Not inside a trusted directory")
            || stderr.contains("skip-git-repo-check")
            || stderr.contains("git repository")
        {
            hints.push(
                "Set `working_dir` to a trusted git repo (or pass `-C <repo>` in args)."
                    .to_string(),
            );
        }

        if hints.is_empty() {
            stderr.to_string()
        } else {
            format!("{}\nHints:\n- {}", stderr, hints.join("\n- "))
        }
    }

    fn resolve_collab_command_args(
        args: Vec<String>,
        session_id: &str,
        from: &str,
        to: &str,
        phase: &str,
        message: &str,
    ) -> Vec<String> {
        let source_args = if args.is_empty() {
            vec!["{{message}}".to_string()]
        } else {
            args
        };

        let mut used_message_placeholder = false;
        let mut out = Vec::with_capacity(source_args.len() + 1);
        for arg in source_args {
            if arg.contains("{{message}}") {
                used_message_placeholder = true;
            }
            let replaced = arg
                .replace("{{session_id}}", session_id)
                .replace("{{from}}", from)
                .replace("{{to}}", to)
                .replace("{{phase}}", phase)
                .replace("{{message}}", message);
            out.push(replaced);
        }

        if !used_message_placeholder {
            out.push(message.to_string());
        }

        out
    }

    fn default_collab_session_id(objective: &str) -> String {
        let mut slug = objective
            .trim()
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() {
                    c.to_ascii_lowercase()
                } else {
                    '-'
                }
            })
            .collect::<String>();
        while slug.contains("--") {
            slug = slug.replace("--", "-");
        }
        slug = slug.trim_matches('-').to_string();
        if slug.is_empty() {
            slug = "session".to_string();
        }

        format!("{}-{}", slug, Self::now_unix_ms())
    }

    fn sanitize_identifier(value: &str) -> Result<String, McpError> {
        let mut out = String::new();
        for ch in value.trim().chars() {
            if ch.is_ascii_alphanumeric() {
                out.push(ch.to_ascii_lowercase());
            } else if ch == '-' || ch == '_' || ch == '.' {
                out.push(ch);
            } else if ch.is_ascii_whitespace() {
                out.push('-');
            }
        }

        while out.contains("--") {
            out = out.replace("--", "-");
        }

        let cleaned = out
            .trim_matches(|c| c == '-' || c == '_' || c == '.')
            .to_string();
        if cleaned.is_empty() {
            return Err(McpError::invalid_params(
                "identifier resolved to empty value".to_string(),
                None,
            ));
        }
        Ok(cleaned)
    }

    fn normalize_collab_phase(phase: Option<&str>) -> Result<String, McpError> {
        let normalized = phase.unwrap_or("general").trim().to_ascii_lowercase();
        let canonical = match normalized.as_str() {
            "plan" | "planning" => "planning",
            "implement" | "implementation" | "implementing" => "implementation",
            "audit" | "auditing" => "audit",
            "general" | "sync" => "general",
            other => {
                return Err(McpError::invalid_params(
                    format!(
                        "Invalid phase '{}'. Use planning, implementation, audit, or general.",
                        other
                    ),
                    None,
                ))
            }
        };

        Ok(canonical.to_string())
    }

    fn required_collab_sections(phase: &str) -> &'static [&'static str] {
        match phase {
            "planning" => &["Goal", "Context", "Plan", "Decision Needed", "Done When"],
            "implementation" => &[
                "Change Summary",
                "Files",
                "Behavior",
                "Validation",
                "Risks",
                "Next Action",
            ],
            "audit" => &[
                "Scope",
                "Findings",
                "Gaps",
                "Verdict",
                "Requested Follow-up",
            ],
            "general" => &["Update", "Blockers", "Ask"],
            _ => &[],
        }
    }

    fn message_matches_protocol(phase: &str, message: &str) -> bool {
        let required = Self::required_collab_sections(phase);
        if required.is_empty() {
            return true;
        }
        let lower = message.to_ascii_lowercase();
        required.iter().all(|section| {
            let marker = format!("[{}]", section.to_ascii_lowercase());
            lower.contains(&marker)
        })
    }

    fn auto_wrap_protocol_message(phase: &str, raw: &str) -> String {
        let content = raw.trim();
        match phase {
            "planning" => format!(
                "[Goal]\nReview and respond to this request.\n\n[Context]\n{}\n\n[Plan]\n1. Analyze the request details.\n2. Identify risks and gaps.\n3. Recommend concrete next steps.\n\n[Decision Needed]\nProvide your recommended approach and blockers.\n\n[Done When]\nA clear actionable response is provided.",
                content
            ),
            "implementation" => format!(
                "[Change Summary]\n{}\n\n[Files]\n- (to be determined)\n\n[Behavior]\nExpected behavior pending collaborator confirmation.\n\n[Validation]\n- Pending\n\n[Risks]\n- Pending\n\n[Next Action]\nProvide implementation recommendation.",
                content
            ),
            "audit" => format!(
                "[Scope]\n{}\n\n[Findings]\n1. Pending review\n\n[Gaps]\n- Pending\n\n[Verdict]\nneeds review\n\n[Requested Follow-up]\nProvide concrete remediation guidance.",
                content
            ),
            "general" => format!(
                "[Update]\n{}\n\n[Blockers]\nnone\n\n[Ask]\nPlease respond with the recommended next action.",
                content
            ),
            _ => content.to_string(),
        }
    }

    fn validate_collab_message_schema(phase: &str, message: &str) -> Result<(), McpError> {
        let required = Self::required_collab_sections(phase);
        if required.is_empty() {
            return Ok(());
        }

        let lower = message.to_ascii_lowercase();
        let mut missing = Vec::new();
        for section in required {
            let marker = format!("[{}]", section.to_ascii_lowercase());
            if !lower.contains(&marker) {
                missing.push(format!("[{}]", section));
            }
        }

        if !missing.is_empty() {
            let template_hint = Self::protocol_template_hint(phase);
            return Err(McpError::invalid_params(
                format!(
                    "Message does not follow '{}' protocol. Missing sections: {}.\nTemplate:\n{}\nTip: call mu_collab_protocol(phase: \"{}\") for the full template, or set enforce_request_protocol=false for exploratory ask/ask_async.",
                    phase,
                    missing.join(", "),
                    template_hint,
                    phase
                ),
                None,
            ));
        }

        Ok(())
    }

    fn protocol_template_hint(phase: &str) -> &'static str {
        match phase {
            "planning" => "[Goal]\n[Context]\n[Plan]\n[Decision Needed]\n[Done When]",
            "implementation" => {
                "[Change Summary]\n[Files]\n[Behavior]\n[Validation]\n[Risks]\n[Next Action]"
            }
            "audit" => "[Scope]\n[Findings]\n[Gaps]\n[Verdict]\n[Requested Follow-up]",
            "general" => "[Update]\n[Blockers]\n[Ask]",
            _ => "",
        }
    }

    fn now_unix_ms() -> u128 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis())
            .unwrap_or(0)
    }

    fn next_collab_message_id() -> String {
        let now = Self::now_unix_ms();
        let pid = u128::from(std::process::id());
        let counter = u128::from(COLLAB_MESSAGE_COUNTER.fetch_add(1, Ordering::SeqCst) % 1_000_000);
        format!("{:013}-{:06}-{:06}", now, pid % 1_000_000, counter)
    }

    fn should_exclude_path(&self, path: &str, exclude_regexes: &[Regex]) -> bool {
        if exclude_regexes.is_empty() {
            return false;
        }

        let normalized = path.replace('\\', "/");
        exclude_regexes.iter().any(|re| re.is_match(&normalized))
    }

    fn compile_glob_patterns(&self, patterns: &[String]) -> Vec<Regex> {
        let mut compiled = Vec::new();

        for pattern in patterns {
            for variant in Self::expand_glob_variants(pattern) {
                match Regex::new(&Self::glob_to_regex(&variant)) {
                    Ok(re) => compiled.push(re),
                    Err(err) => {
                        tracing::warn!("Invalid MCP glob exclude pattern '{}': {}", pattern, err)
                    }
                }
            }
        }

        compiled
    }

    fn expand_glob_variants(pattern: &str) -> Vec<String> {
        if let Some(stripped) = pattern.strip_prefix("**/") {
            if stripped.is_empty() {
                vec![pattern.to_string()]
            } else {
                vec![pattern.to_string(), stripped.to_string()]
            }
        } else {
            vec![pattern.to_string()]
        }
    }

    fn glob_to_regex(pattern: &str) -> String {
        let mut out = String::from("^");
        let normalized = pattern.replace('\\', "/");
        let mut chars = normalized.chars().peekable();

        while let Some(ch) = chars.next() {
            match ch {
                '*' => {
                    if chars.peek() == Some(&'*') {
                        chars.next();
                        out.push_str(".*");
                    } else {
                        out.push_str("[^/]*");
                    }
                }
                '?' => out.push_str("[^/]"),
                '.' | '+' | '(' | ')' | '[' | ']' | '{' | '}' | '^' | '$' | '|' => {
                    out.push('\\');
                    out.push(ch);
                }
                _ => out.push(ch),
            }
        }

        out.push('$');
        out
    }

    fn search_result_key(result: &SearchResult) -> String {
        if let Some(ref node_id) = result.node_id {
            return node_id.clone();
        }
        format!(
            "{}::{}::{}",
            result.name,
            result.node_type,
            result.file_path.as_deref().unwrap_or("")
        )
    }

    fn node_type_weight(node_type: &str) -> f32 {
        match node_type {
            // Architecture docs should be available for high-level questions,
            // but implementation code remains primary for most retrieval tasks.
            "doc" => 0.8,
            "external" => 0.7,
            _ => 1.0,
        }
    }

    fn cluster_results_by_flow(&self, results: &[SearchResult]) -> Vec<(String, Vec<usize>)> {
        if results.is_empty() {
            return Vec::new();
        }

        let mut groups: std::collections::HashMap<String, Vec<usize>> =
            std::collections::HashMap::new();

        for (idx, result) in results.iter().enumerate() {
            let label = result
                .file_path
                .as_deref()
                .map(|path| {
                    let normalized = path.replace('\\', "/");
                    let mut parts = normalized.split('/').filter(|p| !p.is_empty());
                    match (parts.next(), parts.next()) {
                        (Some(a), Some(b)) => format!("{}/{}", a, b),
                        (Some(a), None) => a.to_string(),
                        _ => "(unknown)".to_string(),
                    }
                })
                .unwrap_or_else(|| "(unknown)".to_string());

            groups.entry(label).or_default().push(idx);
        }

        let mut grouped: Vec<(String, Vec<usize>)> = groups.into_iter().collect();
        grouped.sort_by(|a, b| {
            let a_best =
                a.1.iter()
                    .map(|i| results[*i].similarity)
                    .fold(0.0_f32, f32::max);
            let b_best =
                b.1.iter()
                    .map(|i| results[*i].similarity)
                    .fold(0.0_f32, f32::max);
            b_best
                .partial_cmp(&a_best)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        for (_, indices) in &mut grouped {
            indices.sort_by(|a, b| {
                results[*b]
                    .similarity
                    .partial_cmp(&results[*a].similarity)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
        }

        grouped
    }

    async fn graph_boosted_grok_search(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        query: &str,
        limit: usize,
    ) -> Vec<SearchResult> {
        const SEMANTIC_K: usize = 20;
        const MAX_HOPS: usize = 2;
        const MAX_FRONTIER: usize = 64;
        const EMBEDDING_WEIGHT: f32 = 0.55;
        const GRAPH_WEIGHT: f32 = 0.25;
        const ACTIVITY_WEIGHT: f32 = 0.12;
        const GIT_RECENCY_WEIGHT: f32 = 0.08;

        let semantic_results = self
            .run_semantic_search(mubase, query, SEMANTIC_K)
            .await
            .unwrap_or_default();

        if semantic_results.is_empty() {
            return self
                .run_keyword_search(mubase, query, limit)
                .unwrap_or_default();
        }

        let (recent_nodes, git_boosts) = {
            let mut session = self.session.lock().await;
            session.load_git_recency();
            let nodes: Vec<String> = session
                .unique_nodes()
                .iter()
                .map(|n| n.name.clone())
                .collect();
            let boosts = session.git_recency.clone().unwrap_or_default();
            (nodes, boosts)
        };

        let seed_ids: Vec<String> = semantic_results
            .iter()
            .filter_map(|r| r.node_id.clone())
            .collect();
        if seed_ids.is_empty() {
            return semantic_results.into_iter().take(limit).collect();
        }

        let hop_map = self.expand_graph_candidates(mubase, &seed_ids, MAX_HOPS, MAX_FRONTIER);
        let candidate_ids: Vec<String> = hop_map.keys().cloned().collect();

        let mut semantic_by_id: std::collections::HashMap<String, f32> =
            std::collections::HashMap::new();
        for row in &semantic_results {
            if let Some(ref node_id) = row.node_id {
                semantic_by_id.insert(node_id.clone(), row.similarity);
            }
        }

        let mut candidates = self.fetch_nodes_by_ids(mubase, &candidate_ids);
        if candidates.is_empty() {
            return semantic_results.into_iter().take(limit).collect();
        }

        let candidate_names: Vec<String> = candidates.iter().map(|r| r.name.clone()).collect();
        let activity_boosts: std::collections::HashMap<String, f32> = if recent_nodes.is_empty() {
            std::collections::HashMap::new()
        } else {
            self.compute_activity_boosts(mubase, &candidate_names, &recent_nodes)
                .into_iter()
                .collect()
        };

        let mut scored: Vec<(SearchResult, f32)> = candidates
            .drain(..)
            .map(|mut row| {
                let node_id = row.node_id.clone().unwrap_or_default();
                let embedding_similarity = semantic_by_id.get(&node_id).copied().unwrap_or(0.0);
                let hop = hop_map.get(&node_id).copied().unwrap_or(MAX_HOPS);
                let graph_proximity = match hop {
                    0 => 1.0,
                    1 => 0.72,
                    _ => 0.45,
                };
                let activity = activity_boosts.get(&row.name).copied().unwrap_or(0.0);
                let git_boost = row
                    .file_path
                    .as_ref()
                    .and_then(|p| git_boosts.get(p))
                    .map(|commits| (*commits as f32 * 0.1).min(0.5))
                    .unwrap_or(0.0);

                let score = (embedding_similarity * EMBEDDING_WEIGHT)
                    + (graph_proximity * GRAPH_WEIGHT)
                    + (activity * ACTIVITY_WEIGHT)
                    + (git_boost * GIT_RECENCY_WEIGHT);
                let weighted = score * Self::node_type_weight(&row.node_type);
                row.similarity = weighted;
                (row, weighted)
            })
            .collect();

        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        let max_score = scored
            .first()
            .map(|(_, score)| *score)
            .unwrap_or(1.0)
            .max(1e-6);

        scored
            .into_iter()
            .take(limit)
            .map(|(mut row, score)| {
                row.similarity = score / max_score;
                row
            })
            .collect()
    }

    fn expand_graph_candidates(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        seed_ids: &[String],
        max_hops: usize,
        max_frontier: usize,
    ) -> std::collections::HashMap<String, usize> {
        let mut hop_map: std::collections::HashMap<String, usize> =
            seed_ids.iter().map(|id| (id.clone(), 0usize)).collect();
        let mut frontier: Vec<String> = seed_ids.to_vec();

        for hop in 1..=max_hops {
            if frontier.is_empty() {
                break;
            }

            let ids_sql = frontier
                .iter()
                .take(max_frontier)
                .map(|id| format!("'{}'", id.replace('\'', "''")))
                .collect::<Vec<_>>()
                .join(", ");
            if ids_sql.is_empty() {
                break;
            }

            let sql = format!(
                "SELECT DISTINCT e.target_id AS neighbor_id
                 FROM edges e
                 WHERE e.source_id IN ({ids}) AND e.type IN ('calls', 'imports', 'contains', 'uses', 'references')
                 UNION
                 SELECT DISTINCT e.source_id AS neighbor_id
                 FROM edges e
                 WHERE e.target_id IN ({ids}) AND e.type IN ('calls', 'imports', 'contains', 'uses', 'references')
                 LIMIT {limit}",
                ids = ids_sql,
                limit = max_frontier * 2
            );

            let mut next_frontier = Vec::new();
            if let Ok(result) = mubase.query(&sql) {
                for row in &result.rows {
                    let neighbor_id = row
                        .first()
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    if neighbor_id.is_empty() {
                        continue;
                    }
                    if hop_map.contains_key(&neighbor_id) {
                        continue;
                    }

                    hop_map.insert(neighbor_id.clone(), hop);
                    next_frontier.push(neighbor_id);
                    if next_frontier.len() >= max_frontier {
                        break;
                    }
                }
            }
            frontier = next_frontier;
        }

        hop_map
    }

    fn fetch_nodes_by_ids(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        node_ids: &[String],
    ) -> Vec<SearchResult> {
        if node_ids.is_empty() {
            return Vec::new();
        }

        let ids_sql = node_ids
            .iter()
            .map(|id| format!("'{}'", id.replace('\'', "''")))
            .collect::<Vec<_>>()
            .join(", ");
        if ids_sql.is_empty() {
            return Vec::new();
        }

        let sql = format!(
            "SELECT id, type, name, file_path FROM nodes WHERE id IN ({}) LIMIT 500",
            ids_sql
        );

        match mubase.query(&sql) {
            Ok(result) => result
                .rows
                .iter()
                .map(|row| SearchResult {
                    node_id: row.first().and_then(|v| v.as_str()).map(|s| s.to_string()),
                    node_type: row
                        .get(1)
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    name: row
                        .get(2)
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string(),
                    file_path: row.get(3).and_then(|v| v.as_str()).map(|s| s.to_string()),
                    similarity: 0.0,
                })
                .collect(),
            Err(_) => Vec::new(),
        }
    }

    /// Extract task-aware keywords - smarter than basic stop-word filtering
    fn extract_task_keywords(&self, task: &str) -> Vec<String> {
        // Task action words that hint at intent but aren't searchable
        const TASK_WORDS: &[&str] = &[
            "fix",
            "add",
            "implement",
            "create",
            "update",
            "change",
            "modify",
            "refactor",
            "remove",
            "delete",
            "debug",
            "investigate",
            "find",
            "bug",
            "issue",
            "error",
            "problem",
            "feature",
            "improve",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
            "and",
            "or",
            "but",
            "if",
            "then",
            "else",
            "when",
            "where",
            "what",
            "which",
            "who",
            "how",
            "why",
            "with",
            "without",
            "for",
            "from",
            "to",
            "in",
            "on",
            "at",
            "by",
            "of",
            "about",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "over",
            "i",
            "me",
            "my",
            "we",
            "our",
            "you",
            "your",
            "need",
            "want",
            "like",
            "make",
            "get",
            "set",
            "use",
            "new",
            "old",
            "some",
            "any",
            "all",
            "each",
            "every",
            "code",
            "function",
            "method",
            "class",
            "file",
            "module",
        ];

        task.split(|c: char| !c.is_alphanumeric() && c != '_' && c != '-')
            .filter(|w| w.len() > 2)
            .filter(|w| !TASK_WORDS.contains(&w.to_lowercase().as_str()))
            .map(|w| w.to_string())
            .collect()
    }

    /// Perform hybrid search combining BM25 (keyword) and semantic (embedding) results.
    ///
    /// Uses Reciprocal Rank Fusion (RRF) to merge rankings from both systems.
    /// This ensures we find both:
    /// - Exact keyword matches (e.g., "create_hnsw_index" when searching "hnsw")
    /// - Conceptually related code (e.g., storage/persistence code)
    ///
    /// Two types of activity-dependent boost:
    /// 1. Session activity: nodes connected to recently accessed symbols
    /// 2. Git recency: files modified recently in git ("hot" codebase areas)
    async fn hybrid_search(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        query: &str,
        limit: usize,
    ) -> Vec<SearchResult> {
        // Get session context for activity-dependent boosting
        let (recent_nodes, git_boosts) = {
            let mut session = self.session.lock().await;

            // Load git recency data if not already cached
            session.load_git_recency();

            // Get recently accessed nodes
            let nodes: Vec<String> = session
                .unique_nodes()
                .iter()
                .map(|n| n.name.clone())
                .collect();

            // Clone git recency for use outside the lock
            let boosts = session.git_recency.clone().unwrap_or_default();

            (nodes, boosts)
        };

        // Get results from both systems
        let bm25_results = mubase.bm25_search(query, limit * 2).unwrap_or_default();
        let semantic_results = self
            .run_semantic_search(mubase, query, limit * 2)
            .await
            .unwrap_or_default();

        // Convert BM25 results to SearchResult format
        let bm25_converted: Vec<SearchResult> = bm25_results
            .into_iter()
            .map(|r| SearchResult {
                node_id: Some(r.node_id),
                name: r.name,
                node_type: r.node_type,
                file_path: r.file_path,
                similarity: r.similarity,
            })
            .collect();

        // Apply RRF merge with both activity boosts
        self.rrf_merge(
            mubase,
            bm25_converted,
            semantic_results,
            limit,
            &recent_nodes,
            &git_boosts,
        )
    }

    /// Reciprocal Rank Fusion - merge two ranked lists into one.
    ///
    /// RRF score = Σ weight/(k + rank) for each list where the item appears.
    /// This elegantly combines rankings without needing to normalize scores.
    ///
    /// k=60 is the standard constant that balances contribution from different ranks.
    /// BM25 is weighted 2x higher because exact keyword matches are more valuable
    /// for code search than semantic similarity.
    ///
    /// Two types of activity boost:
    /// 1. Session activity: nodes connected to recently accessed symbols
    /// 2. Git recency: files modified recently ("hot" codebase areas)
    fn rrf_merge(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        bm25_results: Vec<SearchResult>,
        semantic_results: Vec<SearchResult>,
        limit: usize,
        recent_nodes: &[String],
        git_boosts: &std::collections::HashMap<String, u32>,
    ) -> Vec<SearchResult> {
        use std::collections::{HashMap, HashSet};

        const K: f32 = 60.0; // RRF constant
        const BM25_WEIGHT: f32 = 2.0; // Keyword matches weighted 2x
        const SEMANTIC_WEIGHT: f32 = 1.0;
        const ACTIVITY_WEIGHT: f32 = 0.5; // Boost for nodes near recent session activity
        const GIT_RECENCY_WEIGHT: f32 = 0.3; // Boost for recently modified files

        // Track scores and keep the result data
        let mut scores: HashMap<String, f32> = HashMap::new();
        let mut result_data: HashMap<String, SearchResult> = HashMap::new();

        // Score from BM25 ranking (keyword matches) - weighted higher
        for (rank, result) in bm25_results.into_iter().enumerate() {
            let key = Self::search_result_key(&result);
            *scores.entry(key.clone()).or_default() += BM25_WEIGHT / (K + rank as f32 + 1.0);
            result_data.entry(key).or_insert(result);
        }

        // Score from semantic ranking (conceptual matches)
        for (rank, result) in semantic_results.into_iter().enumerate() {
            let key = Self::search_result_key(&result);
            *scores.entry(key.clone()).or_default() += SEMANTIC_WEIGHT / (K + rank as f32 + 1.0);
            result_data.entry(key).or_insert(result);
        }

        // Activity-dependent boost: strengthen nodes connected to recent session activity
        if !recent_nodes.is_empty() {
            let candidate_names: Vec<String> = result_data
                .values()
                .map(|r| r.name.clone())
                .collect::<HashSet<_>>()
                .into_iter()
                .collect();
            let activity_boosts =
                self.compute_activity_boosts(mubase, &candidate_names, recent_nodes);
            for (name, boost) in activity_boosts {
                for (key, result) in &result_data {
                    if result.name == name {
                        if let Some(score) = scores.get_mut(key) {
                            *score += boost * ACTIVITY_WEIGHT;
                        }
                    }
                }
            }
        }

        // Git recency boost: strengthen nodes in recently modified files
        if !git_boosts.is_empty() {
            for (name, result) in result_data.iter() {
                if let Some(ref file_path) = result.file_path {
                    if let Some(&commit_count) = git_boosts.get(file_path) {
                        // More commits = hotter file (capped at 5 commits for max boost)
                        let boost = (commit_count as f32 * 0.1).min(0.5);
                        if let Some(score) = scores.get_mut(name) {
                            *score += boost * GIT_RECENCY_WEIGHT;
                        }
                    }
                }
            }
        }

        // Keep docs retrievable while prioritizing executable code for implementation tasks.
        for (key, result) in &result_data {
            if let Some(score) = scores.get_mut(key) {
                *score *= Self::node_type_weight(&result.node_type);
            }
        }

        // Sort by RRF score
        let mut scored: Vec<(String, f32)> = scores.into_iter().collect();
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        // Build final results with RRF score as similarity
        let max_score = scored.first().map(|(_, s)| *s).unwrap_or(1.0);
        scored
            .into_iter()
            .take(limit)
            .filter_map(|(key, score)| {
                result_data.remove(&key).map(|mut r| {
                    // Normalize RRF score to 0-1 range
                    r.similarity = score / max_score;
                    r
                })
            })
            .collect()
    }

    /// Get supporting context nodes through graph traversal
    fn get_context_nodes(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        project_root: &PathBuf,
        must_read_names: &[&str],
        keywords: &[String],
    ) -> Vec<(String, String, String, Option<String>)> {
        let mut context = Vec::new();
        let mut seen: std::collections::HashSet<String> =
            must_read_names.iter().map(|s| s.to_string()).collect();

        // Get dependencies of must-read nodes
        for name in must_read_names {
            let sql = format!(
                "SELECT DISTINCT n.name, n.type, n.file_path, n.line_start, n.line_end
                 FROM edges e
                 JOIN nodes n ON n.id = e.target_id
                 WHERE e.source_id IN (SELECT id FROM nodes WHERE name = '{}')
                   AND e.type IN ('imports', 'calls', 'uses')
                 LIMIT 5",
                name.replace('\'', "''")
            );

            if let Ok(result) = mubase.query(&sql) {
                for row in &result.rows {
                    let dep_name = row
                        .first()
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    if seen.insert(dep_name.clone()) {
                        let node_type = row
                            .get(1)
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        let file_path = row
                            .get(2)
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        let line_start = row.get(3).and_then(|v| v.as_i64());
                        let line_end = row.get(4).and_then(|v| v.as_i64());

                        // Extract signature if it's a function
                        let signature = if node_type == "function" {
                            self.get_function_signature(
                                project_root,
                                &file_path,
                                line_start,
                                line_end,
                            )
                        } else {
                            None
                        };

                        context.push((dep_name, node_type, file_path, signature));
                    }
                }
            }
        }

        // Also find nodes matching keywords that aren't already included
        for keyword in keywords.iter().take(3) {
            let sql = format!(
                "SELECT name, type, file_path, line_start, line_end FROM nodes
                 WHERE LOWER(name) LIKE '%{}%'
                 LIMIT 3",
                keyword.to_lowercase().replace('\'', "''")
            );

            if let Ok(result) = mubase.query(&sql) {
                for row in &result.rows {
                    let name = row
                        .first()
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    if seen.insert(name.clone()) {
                        let node_type = row
                            .get(1)
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        let file_path = row
                            .get(2)
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        let line_start = row.get(3).and_then(|v| v.as_i64());
                        let line_end = row.get(4).and_then(|v| v.as_i64());

                        let signature = if node_type == "function" {
                            self.get_function_signature(
                                project_root,
                                &file_path,
                                line_start,
                                line_end,
                            )
                        } else {
                            None
                        };

                        context.push((name, node_type, file_path, signature));
                    }
                }
            }
        }

        // Limit total context
        context.truncate(10);
        context
    }

    /// Get function signature (first line of definition)
    fn get_function_signature(
        &self,
        project_root: &PathBuf,
        file_path: &str,
        line_start: Option<i64>,
        _line_end: Option<i64>,
    ) -> Option<String> {
        let full_path = project_root.join(file_path);
        let content = fs::read_to_string(&full_path).ok()?;
        let lines: Vec<&str> = content.lines().collect();

        let start = line_start.unwrap_or(1) as usize;
        if start > 0 && start <= lines.len() {
            let first_line = lines[start - 1].trim();
            // Truncate long signatures
            if first_line.len() > 80 {
                Some(format!("{}...", &first_line[..77]))
            } else {
                Some(first_line.to_string())
            }
        } else {
            None
        }
    }

    /// Extract relevant patterns from the codebase
    fn extract_patterns(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        keywords: &[String],
        relevant_files: &[String],
    ) -> Vec<String> {
        let mut patterns = Vec::new();

        // Check for error handling patterns
        let error_sql = "SELECT DISTINCT
            CASE
                WHEN name LIKE '%Error%' OR name LIKE '%Exception%' THEN name
                ELSE NULL
            END as error_type
            FROM nodes
            WHERE (name LIKE '%Error%' OR name LIKE '%Exception%')
              AND type = 'class'
            LIMIT 5";

        if let Ok(result) = mubase.query(error_sql) {
            let error_types: Vec<String> = result
                .rows
                .iter()
                .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
                .collect();
            if !error_types.is_empty() {
                patterns.push(format!("Error types: {}", error_types.join(", ")));
            }
        }

        // Check if task mentions config-related keywords
        let config_keywords = ["config", "setting", "option", "timeout", "expire", "limit"];
        let has_config_keyword = keywords.iter().any(|k| {
            config_keywords
                .iter()
                .any(|ck| k.to_lowercase().contains(ck))
        });

        if has_config_keyword {
            // Look for config-related files
            let config_sql = "SELECT DISTINCT file_path FROM nodes
                WHERE LOWER(file_path) LIKE '%config%'
                   OR LOWER(file_path) LIKE '%settings%'
                   OR LOWER(file_path) LIKE '%.toml'
                   OR LOWER(file_path) LIKE '%.yaml'
                   OR LOWER(file_path) LIKE '%.json'
                LIMIT 5";

            if let Ok(result) = mubase.query(config_sql) {
                let config_files: Vec<String> = result
                    .rows
                    .iter()
                    .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
                    .collect();
                if !config_files.is_empty() {
                    patterns.push(format!("Config files: {}", config_files.join(", ")));
                }
            }
        }

        // Look for test patterns related to the files we found
        if !relevant_files.is_empty() {
            let test_paths: Vec<String> = relevant_files
                .iter()
                .filter_map(|f| {
                    // Common test file patterns
                    if f.contains("test") || f.contains("spec") {
                        return None; // Already a test file
                    }
                    let stem = f
                        .trim_end_matches(".rs")
                        .trim_end_matches(".py")
                        .trim_end_matches(".ts")
                        .trim_end_matches(".js");
                    Some(format!(
                        "{}test%' OR file_path LIKE '%{}_test%' OR file_path LIKE '%{}_spec%",
                        stem.replace('\'', "''"),
                        stem.replace('\'', "''"),
                        stem.replace('\'', "''")
                    ))
                })
                .take(3)
                .collect();

            if !test_paths.is_empty() {
                let test_sql = format!(
                    "SELECT DISTINCT file_path FROM nodes WHERE file_path LIKE '%{}' LIMIT 3",
                    test_paths.first().unwrap_or(&String::new())
                );

                if let Ok(result) = mubase.query(&test_sql) {
                    let test_files: Vec<String> = result
                        .rows
                        .iter()
                        .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
                        .collect();
                    if !test_files.is_empty() {
                        patterns.push(format!("Related tests: {}", test_files.join(", ")));
                    }
                }
            }
        }

        // Check for common architectural patterns in the must-read files
        if let Some(file_pattern) = relevant_files.first() {
            if file_pattern.contains("controller") || file_pattern.contains("handler") {
                patterns.push("Architecture: Controller/Handler pattern detected".to_string());
            } else if file_pattern.contains("service") {
                patterns.push("Architecture: Service layer pattern detected".to_string());
            } else if file_pattern.contains("repository") || file_pattern.contains("repo") {
                patterns.push("Architecture: Repository pattern detected".to_string());
            }
        }

        patterns
    }
    async fn run_semantic_search(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        query: &str,
        limit: usize,
    ) -> anyhow::Result<Vec<SearchResult>> {
        let model = self
            .model
            .get_or_try_init(|| async { mu_embeddings::MuSigmaModel::embedded() })
            .await?;
        let embedding = model.embed_one(query)?;
        let results = mubase.vector_search(&embedding, limit, Some(0.3))?;

        Ok(results
            .into_iter()
            .map(|r| SearchResult {
                node_id: Some(r.node_id),
                name: r.name,
                node_type: r.node_type,
                file_path: r.file_path,
                similarity: r.similarity,
            })
            .collect())
    }

    fn run_keyword_search(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        query: &str,
        limit: usize,
    ) -> anyhow::Result<Vec<SearchResult>> {
        let sql = format!(
            "SELECT id, type, name, file_path FROM nodes WHERE LOWER(name) LIKE '%{}%' LIMIT {}",
            query.to_lowercase().replace('\'', "''"),
            limit
        );
        let result = mubase.query(&sql)?;

        Ok(result
            .rows
            .iter()
            .map(|row| SearchResult {
                node_id: row.first().and_then(|v| v.as_str()).map(|s| s.to_string()),
                name: row
                    .get(2)
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                node_type: row
                    .get(1)
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                file_path: row.get(3).and_then(|v| v.as_str()).map(|s| s.to_string()),
                similarity: 1.0,
            })
            .collect())
    }

    /// Extract a code snippet around a symbol
    fn extract_snippet(&self, content: &str, name: &str, node_type: &str) -> Option<String> {
        let lines: Vec<&str> = content.lines().collect();

        // Find the line containing the symbol definition
        let patterns: Vec<String> = match node_type {
            "function" => vec![
                format!("fn {}", name),
                format!("def {}(", name),
                format!("func {}", name),
                format!("function {}", name),
                format!("{} = function", name),
                format!("{} = (", name),
                format!("{} = async", name),
            ],
            "class" => vec![
                format!("class {}", name),
                format!("struct {}", name),
                format!("interface {}", name),
                format!("type {} ", name),
            ],
            _ => vec![name.to_string()],
        };

        for (i, line) in lines.iter().enumerate() {
            for pattern in &patterns {
                if line.contains(pattern.as_str()) {
                    // Found it, extract context
                    let start = i;
                    let mut end = i + 1;

                    // Try to find the end of the block (simple heuristic)
                    let mut brace_count = 0;
                    let mut found_open = false;
                    for (offset, l) in lines.iter().skip(i).take(50).enumerate() {
                        for c in l.chars() {
                            if c == '{' || c == '(' && !found_open {
                                brace_count += 1;
                                found_open = true;
                            } else if c == '}' || (c == ')' && found_open && brace_count == 1) {
                                brace_count -= 1;
                            }
                        }
                        end = i + offset + 1;
                        if found_open && brace_count <= 0 {
                            break;
                        }
                    }

                    // Limit to 25 lines
                    let snippet_end = end.min(start + 25);
                    let mut snippet = lines[start..snippet_end].join("\n");
                    if end > snippet_end {
                        snippet.push_str("\n  // ... (truncated)");
                    }
                    return Some(snippet);
                }
            }
        }

        None
    }

    /// Find unexplored neighbors of nodes the user has been revisiting.
    /// These are potential "escape routes" from rumination loops.
    fn find_unexplored_neighbors(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        repeated_nodes: &[String],
        session: &SessionState,
    ) -> Vec<(String, String, String)> {
        let mut neighbors = Vec::new();
        let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();

        for node_name in repeated_nodes {
            // Find both incoming and outgoing edges from this node
            let sql = format!(
                "SELECT DISTINCT n.name, n.file_path, e.type
                 FROM edges e
                 JOIN nodes n ON (n.id = e.target_id OR n.id = e.source_id)
                 WHERE (e.source_id IN (SELECT id FROM nodes WHERE name = '{}')
                    OR e.target_id IN (SELECT id FROM nodes WHERE name = '{}'))
                   AND n.name != '{}'
                 LIMIT 10",
                node_name.replace('\'', "''"),
                node_name.replace('\'', "''"),
                node_name.replace('\'', "''")
            );

            if let Ok(result) = mubase.query(&sql) {
                for row in &result.rows {
                    let name = row
                        .first()
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();

                    // Skip if already seen in session or already in our list
                    if session.has_seen(&name) || !seen.insert(name.clone()) {
                        continue;
                    }

                    let file_path = row
                        .get(1)
                        .and_then(|v| v.as_str())
                        .unwrap_or("unknown")
                        .to_string();
                    let relationship = row
                        .get(2)
                        .and_then(|v| v.as_str())
                        .unwrap_or("related")
                        .to_string();

                    neighbors.push((name, file_path, relationship));
                }
            }
        }

        neighbors
    }

    /// Compute activity boosts for search results based on graph proximity to recent nodes.
    ///
    /// Neural plasticity principle: nodes connected to recently "active" (accessed) nodes
    /// should be boosted in search results. This implements "activity-dependent strengthening".
    ///
    /// Returns: Vec of (node_name, boost_factor) for nodes that deserve a boost.
    fn compute_activity_boosts(
        &self,
        mubase: &mu_daemon::storage::MUbase,
        candidate_names: &[String],
        recent_nodes: &[String],
    ) -> Vec<(String, f32)> {
        let mut boosts = Vec::new();

        // Skip if no recent activity
        if recent_nodes.is_empty() {
            return boosts;
        }

        // Build a set of recent node names for quick lookup
        let recent_set: std::collections::HashSet<&str> =
            recent_nodes.iter().map(|s| s.as_str()).collect();

        // For each candidate, check if it's connected to any recent node
        for candidate_name in candidate_names {
            // Skip if the candidate IS a recent node (don't double-boost)
            if recent_set.contains(candidate_name.as_str()) {
                // Direct hit: strong boost
                boosts.push((candidate_name.clone(), 1.0));
                continue;
            }

            // Check if candidate is a 1-hop neighbor of any recent node
            let sql = format!(
                "SELECT COUNT(*) FROM edges e
                 JOIN nodes n1 ON n1.id = e.source_id
                 JOIN nodes n2 ON n2.id = e.target_id
                 WHERE (n1.name = '{}' AND n2.name IN ({}))
                    OR (n2.name = '{}' AND n1.name IN ({}))",
                candidate_name.replace('\'', "''"),
                recent_nodes
                    .iter()
                    .take(10) // Limit to avoid huge queries
                    .map(|n| format!("'{}'", n.replace('\'', "''")))
                    .collect::<Vec<_>>()
                    .join(", "),
                candidate_name.replace('\'', "''"),
                recent_nodes
                    .iter()
                    .take(10)
                    .map(|n| format!("'{}'", n.replace('\'', "''")))
                    .collect::<Vec<_>>()
                    .join(", ")
            );

            if let Ok(result) = mubase.query(&sql) {
                if let Some(count) = result
                    .rows
                    .first()
                    .and_then(|r| r.first())
                    .and_then(|v| v.as_i64())
                {
                    if count > 0 {
                        // Connected to recent activity: moderate boost
                        // More connections = stronger boost (capped at 0.8)
                        let boost = (count as f32 * 0.2).min(0.8);
                        boosts.push((candidate_name.clone(), boost));
                    }
                }
            }
        }

        boosts
    }
}

#[derive(Debug, Default, Clone)]
struct SearchResult {
    node_id: Option<String>,
    name: String,
    node_type: String,
    file_path: Option<String>,
    similarity: f32,
}

#[tool_handler]
impl ServerHandler for MuMcpServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: Default::default(),
            capabilities: ServerCapabilities::builder()
                .enable_tools()
                .build(),
            server_info: Implementation {
                name: "mu".into(),
                version: env!("CARGO_PKG_VERSION").into(),
            },
            instructions: Some(
                "MU - semantic code intelligence. Tools:\n\
                 • mu_oracle: THE divine tool - get exactly what you need for a task (must-read code, context, patterns)\n\
                 • mu_grok: Understand code (semantic search + snippets)\n\
                 • mu_find: Find exact symbol by name\n\
                 • mu_compress: Get codebase overview\n\
                 • mu_impact: What depends on a symbol\n\
                 • mu_diff: What changed between git refs\n\
                 • mu_sus: Find suspicious/complex code\n\
                 • mu_wtf: Git archaeology for a file\n\
                 • mu_collab_protocol: Shared planning/implementation/audit message template\n\
                 • mu_collab_open: Create a shared Codex/Claude collaboration session\n\
                 • mu_collab_send: Send phase-aware collaboration messages\n\
                 • mu_collab_ask: Automated request/reply via target CLI command\n\
                 • mu_collab_ask_async: Queue automated request/reply job in background\n\
                 • mu_collab_job_status: Poll async automation job status/results\n\
                 • mu_collab_inbox: Read and checkpoint collaboration messages".into()
            ),
        }
    }

    /// Handle roots list changed notification from the client.
    ///
    /// When Claude Code changes directories or the client's workspace changes,
    /// we receive this notification. We then fetch the new roots and store them
    /// for use in lazy project initialization.
    fn on_roots_list_changed(
        &self,
        context: rmcp::service::NotificationContext<rmcp::service::RoleServer>,
    ) -> impl Future<Output = ()> + Send + '_ {
        async move {
            // Try to fetch the current roots from the client
            if let Ok(roots_result) = context.peer.list_roots().await {
                let mut client_roots = self.client_roots.write().await;
                *client_roots = Some(roots_result.roots);
            }
        }
    }
}
