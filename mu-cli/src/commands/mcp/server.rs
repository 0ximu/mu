//! MCP Server implementation for MU
//!
//! Exposes MU capabilities as MCP tools that can be called by AI assistants.

use std::collections::VecDeque;
use std::fs;
use std::future::Future;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::time::Instant;

use tokio::sync::Mutex;

use rmcp::{
    handler::server::{router::tool::ToolRouter, tool::Parameters},
    model::{ErrorData as McpError, *},
    schemars::JsonSchema,
    tool, tool_handler, tool_router, ServerHandler,
};
use serde::Deserialize;
use tokio::sync::OnceCell;

/// MU MCP Server - exposes codebase intelligence tools
///
/// Now with session state for activity-dependent awareness.
/// MU remembers what you've looked at and can detect patterns.
#[derive(Clone)]
pub struct MuMcpServer {
    mubase: Arc<mu_daemon::storage::MUbase>,
    model: Arc<OnceCell<mu_embeddings::MuSigmaModel>>,
    project_root: PathBuf,
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
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct OracleParams {
    /// The task you want to accomplish (e.g., "fix the login bug where sessions expire too early")
    #[schemars(description = "Natural language description of the task you want to accomplish")]
    pub task: String,
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
    pub accessed_at: Instant,
    pub query: String, // The query that led to this access
}

/// Session state tracking - gives MU memory across MCP calls
#[derive(Debug, Default)]
pub struct SessionState {
    /// Recently accessed nodes (most recent first)
    accessed_nodes: VecDeque<AccessedNode>,
    /// Query history for pattern detection
    query_history: VecDeque<String>,
    /// Session start time
    started_at: Option<Instant>,
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
            started_at: Some(Instant::now()),
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
        let now = Instant::now();
        for node in nodes {
            self.accessed_nodes.push_front(AccessedNode {
                name: node.name.clone(),
                node_type: node.node_type.clone(),
                file_path: node.file_path.clone(),
                accessed_at: now,
                query: query.to_string(),
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
        self.accessed_nodes.iter().filter(|n| n.name == name).count()
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

    /// Get the git recency boost for a file path.
    /// Returns 0.0-1.0 based on how "hot" (recently modified) the file is.
    pub fn git_recency_boost(&self, file_path: &str) -> f32 {
        if let Some(ref recency) = self.git_recency {
            if let Some(&commit_count) = recency.get(file_path) {
                // More commits = hotter file
                // Scale: 1 commit = 0.1, 5+ commits = 0.5 (capped)
                return (commit_count as f32 * 0.1).min(0.5);
            }
        }
        0.0
    }

    /// Get all hot files (for debugging/display)
    pub fn hot_files(&self) -> Vec<(&str, u32)> {
        if let Some(ref recency) = self.git_recency {
            let mut files: Vec<_> = recency.iter().map(|(k, v)| (k.as_str(), *v)).collect();
            files.sort_by(|a, b| b.1.cmp(&a.1));
            files.truncate(10);
            files
        } else {
            vec![]
        }
    }
}

#[tool_router]
impl MuMcpServer {
    pub fn new(mubase: mu_daemon::storage::MUbase, project_root: PathBuf) -> Self {
        Self {
            mubase: Arc::new(mubase),
            model: Arc::new(OnceCell::new()),
            project_root,
            tool_router: Self::tool_router(),
            session: Arc::new(Mutex::new(SessionState::new())),
        }
    }

    /// Grok: Semantic search with actual code snippets
    #[tool(
        description = "Find and show relevant code for a question. Returns actual code snippets, not just locations. Use this to understand how something works."
    )]
    async fn mu_grok(
        &self,
        Parameters(params): Parameters<GrokParams>,
    ) -> Result<CallToolResult, McpError> {
        let start = Instant::now();
        let limit = params.limit.unwrap_or(3).clamp(1, 10);

        // Get search results
        let results = if self.mubase.has_embeddings().unwrap_or(false) {
            self.run_semantic_search(&params.query, limit)
                .await
                .unwrap_or_default()
        } else {
            self.run_keyword_search(&params.query, limit)
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

        // For each result, read and show the actual code
        for (i, result) in results.iter().enumerate() {
            let sigil = match result.node_type.as_str() {
                "module" => "!",
                "class" => "$",
                "function" => "#",
                _ => "@",
            };

            output.push_str(&format!(
                "## {}. {}{} [{}] — {:.0}% match\n",
                i + 1,
                sigil,
                result.name,
                result.node_type,
                result.similarity * 100.0
            ));

            if let Some(ref path) = result.file_path {
                output.push_str(&format!("File: {}\n", path));

                // Read and show actual code snippet
                let full_path = self.project_root.join(path);
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
        let sql = format!(
            "SELECT type, name, file_path, line_start, line_end FROM nodes WHERE name = '{}' OR name LIKE '%.{}' LIMIT 10",
            params.symbol.replace('\'', "''"),
            params.symbol.replace('\'', "''")
        );

        let result = self
            .mubase
            .query(&sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let mut output = String::new();
        output.push_str(&format!("# find: \"{}\"\n", params.symbol));
        output.push_str(&format!("# {} matches\n\n", result.rows.len()));

        for row in &result.rows {
            let node_type = row.first().and_then(|v| v.as_str()).unwrap_or("?");
            let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
            let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
            let start_line = row.get(3).and_then(|v| v.as_i64()).unwrap_or(0);
            let end_line = row.get(4).and_then(|v| v.as_i64()).unwrap_or(0);

            let sigil = match node_type {
                "module" => "!",
                "class" => "$",
                "function" => "#",
                _ => "@",
            };

            output.push_str(&format!("## {}{} [{}]\n", sigil, name, node_type));
            output.push_str(&format!("{}:{}-{}\n", file_path, start_line, end_line));

            // Show the actual code
            let full_path = self.project_root.join(file_path);
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

        if result.rows.is_empty() {
            output.push_str("No exact matches. Try mu_grok for semantic search.\n");
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Compress: Token-efficient codebase overview
    #[tool(
        description = "Get a compressed overview of the entire codebase structure. Use this first to understand what's in the project."
    )]
    async fn mu_compress(&self) -> Result<CallToolResult, McpError> {
        // Get stats
        let stats = self
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
        let langs = self
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
        let nodes_result = self.mubase.query(
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

        let result = self
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

        // If graph is sparse, supplement with grep
        if graph_count < 5 {
            output.push_str("## Text References (grep)\n");

            let grep_result = Command::new("grep")
                .args([
                    "-rn",
                    "--include=*.rs",
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.js",
                    "--include=*.go",
                    "--include=*.java",
                    "-l",
                    &params.symbol,
                ])
                .current_dir(&self.project_root)
                .output();

            if let Ok(grep_out) = grep_result {
                let files = String::from_utf8_lossy(&grep_out.stdout);
                let file_list: Vec<&str> = files.lines().take(20).collect();

                if file_list.is_empty() {
                    output.push_str("  No text references found.\n");
                } else {
                    output.push_str(&format!("  Found in {} files:\n", file_list.len()));
                    for file in file_list {
                        output.push_str(&format!("    {}\n", file));
                    }

                    // Show a sample of actual usages
                    output.push_str("\n## Sample Usages\n");
                    let context_result = Command::new("grep")
                        .args([
                            "-rn",
                            "--include=*.rs",
                            "--include=*.py",
                            "--include=*.ts",
                            "--include=*.js",
                            "--include=*.go",
                            "--include=*.java",
                            "-C1",
                            &params.symbol,
                        ])
                        .current_dir(&self.project_root)
                        .output();

                    if let Ok(ctx) = context_result {
                        let context = String::from_utf8_lossy(&ctx.stdout);
                        let lines: Vec<&str> = context.lines().take(30).collect();
                        output.push_str("```\n");
                        for line in lines {
                            output.push_str(line);
                            output.push('\n');
                        }
                        output.push_str("```\n");
                    }
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
        // Detect default branch
        let base = params.base_ref.unwrap_or_else(|| {
            let result = Command::new("git")
                .args(["symbolic-ref", "refs/remotes/origin/HEAD"])
                .current_dir(&self.project_root)
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
            .current_dir(&self.project_root)
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
                if let Ok(nodes) = self.mubase.query(&sql) {
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
        let min_complexity = params.min_complexity.unwrap_or(15);

        let mut output = String::new();
        output.push_str("# Suspicious Code Report\n\n");

        // High complexity
        let complex_sql = format!(
            "SELECT name, type, file_path, complexity FROM nodes
             WHERE complexity >= {} AND type = 'function'
             ORDER BY complexity DESC LIMIT 15",
            min_complexity
        );
        let complex = self
            .mubase
            .query(&complex_sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        if !complex.rows.is_empty() {
            output.push_str(&format!(
                "## High Complexity (≥{}) — {} found\n",
                min_complexity,
                complex.rows.len()
            ));
            output.push_str("Functions that are hard to understand and maintain:\n\n");
            for row in &complex.rows {
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
            ORDER BY file_path LIMIT 20";
        let security = self
            .mubase
            .query(security_sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        if !security.rows.is_empty() {
            output.push_str(&format!(
                "## Security-Sensitive — {} found\n",
                security.rows.len()
            ));
            output.push_str("Code handling authentication, secrets, or credentials:\n\n");
            for row in &security.rows {
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
            ORDER BY lines DESC LIMIT 10";
        if let Ok(large) = self.mubase.query(large_sql) {
            if !large.rows.is_empty() {
                output.push_str("## Large Functions (by lines)\n");
                output.push_str("Long functions that might need refactoring:\n\n");
                for row in &large.rows {
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
        let file_path = &params.file;
        let full_path = self.project_root.join(file_path);

        let mut output = String::new();
        output.push_str(&format!("# WTF: {}\n\n", file_path));

        // Check if file exists
        let file_exists = full_path.exists();
        let is_tracked = Command::new("git")
            .args(["ls-files", file_path])
            .current_dir(&self.project_root)
            .output()
            .map(|o| !o.stdout.is_empty())
            .unwrap_or(false);

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

        output.push_str(&format!(
            "Git tracked: {}\n\n",
            if is_tracked { "Yes" } else { "No" }
        ));

        if is_tracked {
            // Recent commits
            output.push_str("## Recent Commits\n");
            let log = Command::new("git")
                .args([
                    "log",
                    "--format=%h %ad %an: %s",
                    "--date=short",
                    "-10",
                    "--",
                    file_path,
                ])
                .current_dir(&self.project_root)
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
                .args(["shortlog", "-sn", "--", file_path])
                .current_dir(&self.project_root)
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
                    "log",
                    "--format=%ad %an: %s",
                    "--date=short",
                    "--diff-filter=A",
                    "--",
                    file_path,
                ])
                .current_dir(&self.project_root)
                .output();

            if let Ok(first_out) = first {
                let first_str = String::from_utf8_lossy(&first_out.stdout);
                if let Some(line) = first_str.lines().last() {
                    output.push_str(&format!("  Created: {}\n", line));
                }
            }
        } else if file_exists {
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
            file_path.replace('\'', "''")
        );
        if let Ok(nodes) = self.mubase.query(&sql) {
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
        let start = Instant::now();

        // Extract task-aware keywords (used for context expansion)
        let keywords = self.extract_task_keywords(&params.task);

        let mut output = String::new();
        output.push_str(&format!("# Oracle: \"{}\"\n", params.task));

        // Get must-read nodes via hybrid search (BM25 + semantic with RRF)
        // This combines keyword matching (finds exact symbol names like "create_hnsw_index")
        // with semantic search (finds conceptually related code)
        let must_read = self.hybrid_search(&params.task, 7).await;

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
        let context_nodes = self.get_context_nodes(&must_read_ids, &keywords);

        // Extract patterns from the codebase relevant to this task
        let patterns = self.extract_patterns(&keywords, &must_read_files);

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
                    let full_path = self.project_root.join(path);
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
                output.push_str(&format!("- {} ({}× accessed)\n", node, session.access_count(node)));
            }

            // Find unexplored neighbors as escape routes
            let escape_routes = self.find_unexplored_neighbors(&repeated_nodes, &session);
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
}

// Helper methods
impl MuMcpServer {
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
    async fn hybrid_search(&self, query: &str, limit: usize) -> Vec<SearchResult> {
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
        let bm25_results = self
            .mubase
            .bm25_search(query, limit * 2)
            .unwrap_or_default();
        let semantic_results = self
            .run_semantic_search(query, limit * 2)
            .await
            .unwrap_or_default();

        // Convert BM25 results to SearchResult format
        let bm25_converted: Vec<SearchResult> = bm25_results
            .into_iter()
            .map(|r| SearchResult {
                name: r.name,
                node_type: r.node_type,
                file_path: r.file_path,
                similarity: r.similarity,
            })
            .collect();

        // Apply RRF merge with both activity boosts
        self.rrf_merge(bm25_converted, semantic_results, limit, &recent_nodes, &git_boosts)
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
        bm25_results: Vec<SearchResult>,
        semantic_results: Vec<SearchResult>,
        limit: usize,
        recent_nodes: &[String],
        git_boosts: &std::collections::HashMap<String, u32>,
    ) -> Vec<SearchResult> {
        use std::collections::HashMap;

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
            let key = result.name.clone();
            *scores.entry(key.clone()).or_default() += BM25_WEIGHT / (K + rank as f32 + 1.0);
            result_data.entry(key).or_insert(result);
        }

        // Score from semantic ranking (conceptual matches)
        for (rank, result) in semantic_results.into_iter().enumerate() {
            let key = result.name.clone();
            *scores.entry(key.clone()).or_default() += SEMANTIC_WEIGHT / (K + rank as f32 + 1.0);
            result_data.entry(key).or_insert(result);
        }

        // Activity-dependent boost: strengthen nodes connected to recent session activity
        if !recent_nodes.is_empty() {
            let activity_boosts = self.compute_activity_boosts(&scores, recent_nodes);
            for (name, boost) in activity_boosts {
                if let Some(score) = scores.get_mut(&name) {
                    *score += boost * ACTIVITY_WEIGHT;
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

            if let Ok(result) = self.mubase.query(&sql) {
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
                            self.get_function_signature(&file_path, line_start, line_end)
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

            if let Ok(result) = self.mubase.query(&sql) {
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
                            self.get_function_signature(&file_path, line_start, line_end)
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
        file_path: &str,
        line_start: Option<i64>,
        _line_end: Option<i64>,
    ) -> Option<String> {
        let full_path = self.project_root.join(file_path);
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
    fn extract_patterns(&self, keywords: &[String], relevant_files: &[String]) -> Vec<String> {
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

        if let Ok(result) = self.mubase.query(error_sql) {
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

            if let Ok(result) = self.mubase.query(config_sql) {
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

                if let Ok(result) = self.mubase.query(&test_sql) {
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
        query: &str,
        limit: usize,
    ) -> anyhow::Result<Vec<SearchResult>> {
        let model = self
            .model
            .get_or_try_init(|| async { mu_embeddings::MuSigmaModel::embedded() })
            .await?;
        let embedding = model.embed_one(query)?;
        let results = self.mubase.vector_search(&embedding, limit, Some(0.3))?;

        Ok(results
            .into_iter()
            .map(|r| SearchResult {
                name: r.name,
                node_type: r.node_type,
                file_path: r.file_path,
                similarity: r.similarity,
            })
            .collect())
    }

    fn run_keyword_search(&self, query: &str, limit: usize) -> anyhow::Result<Vec<SearchResult>> {
        let sql = format!(
            "SELECT type, name, file_path FROM nodes WHERE LOWER(name) LIKE '%{}%' LIMIT {}",
            query.to_lowercase().replace('\'', "''"),
            limit
        );
        let result = self.mubase.query(&sql)?;

        Ok(result
            .rows
            .iter()
            .map(|row| SearchResult {
                name: row
                    .get(1)
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                node_type: row
                    .first()
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                file_path: row.get(2).and_then(|v| v.as_str()).map(|s| s.to_string()),
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

            if let Ok(result) = self.mubase.query(&sql) {
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
        candidates: &std::collections::HashMap<String, f32>,
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
        for candidate_name in candidates.keys() {
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

            if let Ok(result) = self.mubase.query(&sql) {
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

#[derive(Debug, Default)]
struct SearchResult {
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
                 • mu_wtf: Git archaeology for a file".into()
            ),
        }
    }
}
