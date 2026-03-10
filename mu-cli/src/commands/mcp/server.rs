//! MCP Server implementation for MU
//!
//! Exposes MU capabilities as MCP tools that can be called by AI assistants.

use crate::mubase::find_project_root;
use std::fs;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;
use std::time::Instant;

use super::tools_v3;

use rmcp::{
    handler::server::{router::tool::ToolRouter, tool::Parameters},
    model::{ErrorData as McpError, *},
    schemars::JsonSchema,
    tool, tool_handler, tool_router, ServerHandler,
};
use serde::Deserialize;
use tokio::sync::{OnceCell, RwLock};

/// Lazily-initialized project state
struct ProjectState {
    mubase: crate::engine::storage::MUbase,
    project_root: PathBuf,
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
    tool_router: ToolRouter<MuMcpServer>,
}

// Tool parameter structs
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
    /// Include cross-service edges (MassTransit pub/sub, HTTP clients, shared contracts)
    #[schemars(description = "Include cross-service edges like MassTransit pub/sub, HTTP calls, shared contracts (default: false)")]
    pub cross_service: Option<bool>,
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
pub struct AuditParams {
    /// Minimum complexity threshold to flag (default: 30)
    #[schemars(description = "Complexity threshold (default: 30)")]
    pub min_complexity: Option<u32>,
    /// Scope audit to files changed since this git ref (e.g., "main", "HEAD~5")
    #[schemars(description = "Git ref to scope audit to changed files only")]
    pub diff_base: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ReviewParams {
    /// Base git ref (defaults to main/develop)
    #[schemars(description = "Base git ref to compare against (e.g., 'main', 'develop', 'HEAD~5')")]
    pub base_ref: Option<String>,
    /// Whether to include impact analysis (default: true)
    #[schemars(description = "Include downstream impact analysis (default: true)")]
    pub include_impact: Option<bool>,
    /// Min complexity threshold for audit (default: 15, lower for review)
    #[schemars(description = "Complexity threshold for audit (default: 15)")]
    pub min_complexity: Option<u32>,
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
            tool_router: Self::tool_router(),
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
                    crate::engine::storage::MUbase::open_read_only(&mubase_path).map_err(|e| {
                        McpError::internal_error(format!("Failed to open mubase: {}", e), None)
                    })?;

                Ok(ProjectState {
                    mubase,
                    project_root,
                })
            })
            .await
    }

    /// Get the mubase, ensuring lazy initialization
    #[allow(dead_code)]
    async fn mubase(&self) -> Result<&crate::engine::storage::MUbase, McpError> {
        Ok(&self.ensure_state().await?.mubase)
    }

    /// Get the project root, ensuring lazy initialization
    #[allow(dead_code)]
    async fn project_root(&self) -> Result<&PathBuf, McpError> {
        Ok(&self.ensure_state().await?.project_root)
    }

    /// Grok: Search + code snippets (V3: BM25 + importance, no embeddings)
    #[tool(
        description = "Find and show relevant code for a question. Returns actual code snippets, not just locations. Use this to understand how something works."
    )]
    async fn mu_grok(
        &self,
        Parameters(params): Parameters<tools_v3::SearchNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let output = tools_v3::handle_search_nodes(&state.mubase, &state.project_root, &params)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;
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

        // Cross-service edges (MassTransit pub/sub, HTTP, contracts)
        if params.cross_service.unwrap_or(false) {
            let cs_sql = format!(
                "SELECT DISTINCT e.type, n2.name, n2.type, n2.file_path, e.properties
                 FROM edges e
                 JOIN nodes n ON n.id = e.source_id OR n.id = e.target_id
                 JOIN nodes n2 ON (n2.id = e.source_id OR n2.id = e.target_id) AND n2.id != n.id
                 WHERE n.name = '{}'
                 AND e.type IN ('publishes', 'subscribes', 'calls_http', 'uses_contract')
                 LIMIT 30",
                params.symbol.replace('\'', "''")
            );

            if let Ok(cs_result) = state.mubase.query(&cs_sql) {
                if !cs_result.rows.is_empty() {
                    output.push_str(&format!(
                        "## Cross-Service Edges ({} found)\n",
                        cs_result.rows.len()
                    ));
                    for row in &cs_result.rows {
                        let edge_type = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                        let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                        let node_type = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                        let file_path = row.get(3).and_then(|v| v.as_str()).unwrap_or("?");
                        output.push_str(&format!(
                            "  {} {} [{}] — {}\n",
                            edge_type, name, node_type, file_path
                        ));
                    }
                    output.push('\n');
                }
            }
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
                .current_dir(&state.project_root)
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
                        .current_dir(&state.project_root)
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

    /// Diff: Real semantic diff showing what symbols changed
    #[tool(
        description = "See what symbols changed between git refs. Parses both versions and compares at the entity level — shows functions/classes added, modified, or removed with breaking change detection."
    )]
    async fn mu_diff(
        &self,
        Parameters(params): Parameters<DiffParams>,
    ) -> Result<CallToolResult, McpError> {
        let _state = self.ensure_state().await?;

        let base = params.base_ref.unwrap_or_else(crate::commands::diff::detect_default_branch);

        let diff_result = crate::commands::diff::semantic_diff(&base, "HEAD")
            .map_err(|e| McpError::internal_error(format!("diff failed: {}", e), None))?;

        // Format as markdown
        let mut output = String::new();
        output.push_str(&format!("# Semantic Diff: {} -> HEAD\n\n", base));
        output.push_str(&format!(
            "{} changes ({} breaking) in {} files ({}ms)\n\n",
            diff_result.changes.len(),
            diff_result.breaking_changes.len(),
            diff_result.files_changed,
            diff_result.duration_ms
        ));

        if !diff_result.breaking_changes.is_empty() {
            output.push_str("## Breaking Changes\n\n");
            for change in &diff_result.breaking_changes {
                output.push_str(&format!(
                    "- `{}` [{}] {} {}\n",
                    change.entity_name,
                    change.entity_type,
                    change.change_type,
                    change.description.as_deref().unwrap_or("")
                ));
                if let Some(ref path) = change.file_path {
                    output.push_str(&format!("  - {}\n", path));
                }
            }
            output.push('\n');
        }

        // Group changes by type
        let added: Vec<_> = diff_result.changes.iter().filter(|c| c.change_type == "added").collect();
        let modified: Vec<_> = diff_result.changes.iter().filter(|c| c.change_type == "modified" || c.change_type == "signature_changed").collect();
        let removed: Vec<_> = diff_result.changes.iter().filter(|c| c.change_type == "removed").collect();

        if !added.is_empty() {
            output.push_str(&format!("## Added ({})\n\n", added.len()));
            for change in &added {
                output.push_str(&format!("- `{}` [{}]", change.entity_name, change.entity_type));
                if let Some(ref path) = change.file_path {
                    output.push_str(&format!(" -- {}", path));
                }
                output.push('\n');
            }
            output.push('\n');
        }

        if !modified.is_empty() {
            output.push_str(&format!("## Modified ({})\n\n", modified.len()));
            for change in &modified {
                let marker = if change.is_breaking { " **BREAKING**" } else { "" };
                output.push_str(&format!("- `{}` [{}]{}", change.entity_name, change.entity_type, marker));
                if let Some(ref path) = change.file_path {
                    output.push_str(&format!(" -- {}", path));
                }
                output.push('\n');
            }
            output.push('\n');
        }

        if !removed.is_empty() {
            output.push_str(&format!("## Removed ({})\n\n", removed.len()));
            for change in &removed {
                let marker = if change.is_breaking { " **BREAKING**" } else { "" };
                output.push_str(&format!("- `{}` [{}]{}", change.entity_name, change.entity_type, marker));
                if let Some(ref path) = change.file_path {
                    output.push_str(&format!(" -- {}", path));
                }
                output.push('\n');
            }
            output.push('\n');
        }

        if diff_result.changes.is_empty() {
            output.push_str("No semantic changes detected.\n");
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

        let mut output = String::new();
        output.push_str("# Suspicious Code Report\n\n");

        // High complexity
        let complex_sql = format!(
            "SELECT name, type, file_path, complexity FROM nodes
             WHERE complexity >= {} AND type = 'function'
             ORDER BY complexity DESC LIMIT 15",
            min_complexity
        );
        let complex = state
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
        let security = state
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
        if let Ok(large) = state.mubase.query(large_sql) {
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
        let state = self.ensure_state().await?;
        let file_path = &params.file;
        let full_path = state.project_root.join(file_path);

        let mut output = String::new();
        output.push_str(&format!("# WTF: {}\n\n", file_path));

        // Check if file exists
        let file_exists = full_path.exists();
        let is_tracked = Command::new("git")
            .args(["ls-files", file_path])
            .current_dir(&state.project_root)
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
                .current_dir(&state.project_root)
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
                .current_dir(&state.project_root)
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
                .current_dir(&state.project_root)
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

    /// Oracle: Task-aware context retrieval (V3: search + expand + pack)
    #[tool(
        description = "Get exactly what you need to accomplish a task. Returns must-read code, supporting context, and relevant patterns. Use this when you have a specific task like 'fix bug X' or 'add feature Y'."
    )]
    async fn mu_oracle(
        &self,
        Parameters(params): Parameters<tools_v3::PackContextParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let output = tools_v3::handle_pack_context(&state.mubase, &state.project_root, &params)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Expand: Graph traversal from seed nodes
    #[tool(
        description = "Explore the dependency graph around specific nodes. Returns neighbors with edge types (calls, imports, uses, inherits). Use after search to understand how code connects."
    )]
    async fn mu_expand(
        &self,
        Parameters(params): Parameters<tools_v3::ExpandNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let output = tools_v3::handle_expand_nodes(&state.mubase, &params)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Read: Bulk node content retrieval with mode control
    #[tool(
        description = "Read source code for specific nodes by ID. Modes: 'signature' (declaration only), 'summary' (what it does), 'source' (full code), 'full' (code + neighbor signatures). Use node IDs from search/expand results."
    )]
    async fn mu_read(
        &self,
        Parameters(params): Parameters<tools_v3::ReadNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let output = tools_v3::handle_read_nodes(&state.mubase, &state.project_root, &params)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Enrich: Discover or store LLM-quality summaries
    #[tool(
        description = "Improve search quality by enriching node summaries. Without arguments: returns high-importance nodes needing better summaries. With summaries: stores them for future search. The enrichment flywheel."
    )]
    async fn mu_enrich(
        &self,
        Parameters(params): Parameters<tools_v3::EnrichNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let output = tools_v3::handle_enrich_nodes(&state.mubase, &params)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Audit: Run code quality rules and report violations
    #[tool(
        description = "Run code quality audit on the codebase. Finds dead code, high complexity, missing docs, hardcoded secrets, TODO/FIXMEs, unwrap abuse, and long parameter lists. Supports project-local custom rules from .mu/rules/."
    )]
    async fn mu_audit(
        &self,
        Parameters(params): Parameters<AuditParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let result = crate::commands::audit::run_audit_for_mcp(
            &state.mubase,
            &state.project_root,
            params.min_complexity,
            params.diff_base.as_deref(),
        )
        .map_err(|e| McpError::internal_error(e, None))?;

        let md = crate::commands::audit::format_as_markdown(&result);
        Ok(CallToolResult::success(vec![Content::text(md)]))
    }

    /// Review: Full PR risk analysis combining diff + impact + audit
    #[tool(
        description = "Full PR review: semantic diff, downstream impact analysis, code audit, and risk scoring. Use this before merging to understand what changed, what might break, and how risky the changes are."
    )]
    async fn mu_review(
        &self,
        Parameters(params): Parameters<ReviewParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let base = params.base_ref.unwrap_or_else(crate::commands::diff::detect_default_branch);
        let include_impact = params.include_impact.unwrap_or(true);
        let min_complexity = params.min_complexity;

        let result = crate::commands::review::run_review(
            &state.mubase,
            &state.project_root,
            &base,
            include_impact,
            min_complexity,
        )
        .map_err(|e| McpError::internal_error(e, None))?;

        let md = crate::commands::review::format_as_markdown(&result);
        Ok(CallToolResult::success(vec![Content::text(md)]))
    }
}

// Helper methods (V2 cruft removed — search logic now in tools_v3 + engine/search)
impl MuMcpServer {
    #[allow(dead_code)]
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

    /// Get function signature (first line of definition)
    #[allow(clippy::ptr_arg)]
    fn get_function_signature(
        &self,
        project_root: &Path,
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
                 • mu_expand: Explore dependency graph around nodes\n\
                 • mu_read: Read source code for specific nodes by ID\n\
                 • mu_enrich: Improve search quality with better summaries\n\
                 • mu_compress: Get codebase overview\n\
                 • mu_impact: What depends on a symbol\n\
                 • mu_diff: What changed between git refs\n\
                 • mu_review: Full PR review (diff + impact + audit + risk score)\n\
                 • mu_audit: Run code quality rules\n\
                 • mu_sus: Find suspicious/complex code\n\
                 • mu_wtf: Git archaeology for a file".into()
            ),
        }
    }

    /// Handle roots list changed notification from the client.
    ///
    /// When Claude Code changes directories or the client's workspace changes,
    /// we receive this notification. We then fetch the new roots and store them
    /// for use in lazy project initialization.
    async fn on_roots_list_changed(
        &self,
        context: rmcp::service::NotificationContext<rmcp::service::RoleServer>,
    ) {
        // Try to fetch the current roots from the client
        if let Ok(roots_result) = context.peer.list_roots().await {
            let mut client_roots = self.client_roots.write().await;
            *client_roots = Some(roots_result.roots);
        }
    }
}
