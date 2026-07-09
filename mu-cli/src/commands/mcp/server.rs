//! MCP Server implementation for MU
//!
//! Exposes MU capabilities as MCP tools that can be called by AI assistants.

use crate::mubase::find_project_root;
use std::fs;
use std::future::Future;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;

use super::responses::{format_impact_response, EdgeResult, ImpactResponse, NodeResult};
use super::tools_v3;

use super::tools_v3::lenient;
use rmcp::{
    handler::server::{router::tool::ToolRouter, tool::Parameters},
    model::{ErrorData as McpError, *},
    schemars::JsonSchema,
    tool, tool_handler, tool_router, ServerHandler,
};
use serde::Deserialize;
use tokio::sync::RwLock;

/// Lazily-initialized project state (cloneable for RwLock hand-off)
#[derive(Clone)]
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
    /// Resettable project state (mubase + project_root).
    /// Wrapped in RwLock<Option<_>> so mu_bootstrap can drop the connection,
    /// rebuild the database, then let the next tool call reinitialize.
    state: Arc<RwLock<Option<ProjectState>>>,
    /// Client roots received during MCP initialization
    /// Used to determine which project the client is working in
    client_roots: Arc<RwLock<Option<Vec<Root>>>>,
    /// Fallback directory if no client roots are provided
    fallback_dir: PathBuf,
    tool_router: ToolRouter<MuMcpServer>,
}

/// Target resolution for mu_impact. Class beats function: in C#/Java a
/// constructor shares the class name, and resolving to the constructor gives
/// a near-empty blast radius. Class beats module so "BaseService" resolves to
/// the class, not the file.
pub(crate) const IMPACT_TARGET_SQL: &str =
    "SELECT id, name, type, file_path, line_start, line_end, importance_score, summary_text, node_category
     FROM nodes WHERE id = ?1 OR name = ?1
     ORDER BY CASE type
         WHEN 'class' THEN 0
         WHEN 'function' THEN 1
         WHEN 'module' THEN 2
         ELSE 3
     END,
     importance_score DESC
     LIMIT 1";

/// Symbol lookup for mu_find: bare name, exact qualified name, dotted suffix
/// of a qualified name, and `Class.Method` inputs via the id suffix (node ids
/// end in `:Class.Method`).
pub(crate) const FIND_SYMBOL_SQL: &str =
    "SELECT type, name, file_path, line_start, line_end, node_category, id FROM nodes
     WHERE name = ?1
        OR qualified_name = ?1
        OR qualified_name LIKE '%.' || ?1
        OR id LIKE '%:' || ?1
     LIMIT 10";

// Tool parameter structs
#[derive(Debug, Deserialize, JsonSchema)]
pub struct FindParams {
    /// Exact symbol name or node ID to find
    #[schemars(
        description = "Symbol name (e.g., 'parse_config') or node ID (e.g., 'fn:src/main.rs:main')"
    )]
    pub symbol: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ImpactParams {
    /// Symbol name to analyze for downstream dependencies
    #[schemars(description = "Symbol name to analyze (e.g., 'DatabaseConnection')")]
    pub symbol: String,
    /// Kept for API compatibility; BFS now traverses all edge types including cross-service.
    #[schemars(
        description = "Kept for compatibility. BFS now always includes cross-service edges."
    )]
    #[serde(default, deserialize_with = "lenient::option_bool")]
    #[allow(dead_code)]
    pub cross_service: Option<bool>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct DiffParams {
    /// Base git ref to compare against (branch, commit, tag). Defaults to 'main' or 'master'.
    #[schemars(description = "Base git ref (e.g., 'main', 'HEAD~5', 'v1.0.0')")]
    pub base_ref: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct SusParams {
    /// Minimum complexity threshold (default: 15)
    #[schemars(description = "Minimum complexity score to flag (default: 15)")]
    #[serde(default, deserialize_with = "lenient::option_i64")]
    pub min_complexity: Option<i64>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct AuditParams {
    /// Minimum complexity threshold to flag (default: 30)
    #[schemars(description = "Complexity threshold (default: 30)")]
    #[serde(default, deserialize_with = "lenient::option_u32")]
    pub min_complexity: Option<u32>,
    /// Scope audit to files changed since this git ref (e.g., "main", "HEAD~5")
    #[schemars(description = "Git ref to scope audit to changed files only")]
    pub diff_base: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ReviewParams {
    /// Base git ref (defaults to main/develop)
    #[schemars(
        description = "Base git ref to compare against (e.g., 'main', 'develop', 'HEAD~5')"
    )]
    pub base_ref: Option<String>,
    /// Whether to include impact analysis (default: true)
    #[schemars(description = "Include downstream impact analysis (default: true)")]
    #[serde(default, deserialize_with = "lenient::option_bool")]
    pub include_impact: Option<bool>,
    /// Min complexity threshold for audit (default: 15, lower for review)
    #[schemars(description = "Complexity threshold for audit (default: 15)")]
    #[serde(default, deserialize_with = "lenient::option_u32")]
    pub min_complexity: Option<u32>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ConfigureParams {
    /// JSON corrections to apply to the draft config. Omit for discovery mode.
    #[schemars(
        description = "JSON object with corrections: service_classifications, domain_concepts, add_priority_nodes, remove_priority_nodes, test_handling. Omit to get the draft config with review questions."
    )]
    pub corrections: Option<String>,
    /// Action: omit for normal flow, "enrich_more" for next enrichment batch.
    #[schemars(
        description = "Action: omit for normal flow, 'enrich_more' to get the next batch of enrichment candidates."
    )]
    pub action: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct BootstrapParams {
    /// Project directory to bootstrap. Omit to use the current project root.
    #[schemars(description = "Project directory path. Omit to use the current project root.")]
    pub path: Option<String>,
    /// Force rebuild even if mubase already exists (default: true for MCP usage).
    #[schemars(description = "Force rebuild (default: true)")]
    #[serde(default, deserialize_with = "lenient::option_bool")]
    pub force: Option<bool>,
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
            state: Arc::new(RwLock::new(None)),
            client_roots: Arc::new(RwLock::new(None)),
            fallback_dir,
            tool_router: Self::tool_router(),
        }
    }

    /// Resolve the starting directory from client roots or fallback.
    async fn start_dir(&self) -> PathBuf {
        let roots = self.client_roots.read().await;
        if let Some(ref root_list) = *roots {
            if let Some(first_root) = root_list.first() {
                let uri = &first_root.uri;
                if let Some(path) = uri.strip_prefix("file://") {
                    return PathBuf::from(path);
                }
                return PathBuf::from(uri);
            }
        }
        self.fallback_dir.clone()
    }

    /// Resolve a project directory, optionally from an explicit path.
    /// Does NOT require an existing mubase (used by mu_bootstrap).
    async fn resolve_project_dir(&self, path: Option<&str>) -> Result<PathBuf, McpError> {
        let dir = match path {
            Some(p) => {
                let pb = PathBuf::from(p);
                pb.canonicalize().unwrap_or(pb)
            }
            None => {
                let start = self.start_dir().await;
                // Try to find existing .mu, otherwise use start_dir directly
                find_project_root(&start).unwrap_or(start)
            }
        };
        if !dir.is_dir() {
            return Err(McpError::internal_error(
                format!("Not a directory: '{}'", dir.display()),
                None,
            ));
        }
        Ok(dir)
    }

    /// Ensure the project state is initialized. Returns an owned clone.
    ///
    /// Fast path: read lock, clone if Some.
    /// Slow path: write lock, double-check, initialize, clone.
    async fn ensure_state(&self) -> Result<ProjectState, McpError> {
        // Fast path
        {
            let guard = self.state.read().await;
            if let Some(ref s) = *guard {
                return Ok(s.clone());
            }
        }
        // Slow path
        let mut guard = self.state.write().await;
        if let Some(ref s) = *guard {
            return Ok(s.clone());
        }

        let start_dir = self.start_dir().await;

        let project_root = find_project_root(&start_dir).ok_or_else(|| {
            McpError::internal_error(
                format!(
                    "No .mu directory found starting from '{}'. Run mu_bootstrap or 'mu bootstrap' first.",
                    start_dir.display()
                ),
                None,
            )
        })?;

        let mubase_path = project_root.join(".mu").join("mubase");
        let mubase = crate::engine::storage::MUbase::open(&mubase_path)
            .map_err(|e| McpError::internal_error(format!("Failed to open mubase: {}", e), None))?;

        let state = ProjectState {
            mubase,
            project_root,
        };
        let cloned = state.clone();
        *guard = Some(state);
        Ok(cloned)
    }

    /// Drop the current state (closes the DuckDB connection).
    /// The next tool call will reinitialize via `ensure_state`.
    async fn reset_state(&self) {
        let mut guard = self.state.write().await;
        *guard = None;
    }

    /// Grok: Search + code snippets (V3: BM25 + importance, no embeddings)
    #[tool(
        description = "Keyword search across the codebase. Best for: finding functions by name or concept when you know roughly what you're looking for. Returns ranked results with confidence level. NOT for: tracing dependencies (use mu_impact), understanding code flow (use mu_expand then mu_read), or getting a project overview (use mu_compress). If confidence is LOW, try more specific terms or use mu_find for exact symbol lookup."
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

    /// Find: Exact symbol lookup with code (accepts symbol names or node IDs)
    #[tool(
        description = "Exact symbol lookup by name or full node ID. Use when you know the exact function/class name or have a node_id from another tool's output. Returns full source code. This is the fastest, most precise tool — prefer it over mu_grok when you have a specific symbol name."
    )]
    async fn mu_find(
        &self,
        Parameters(params): Parameters<FindParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let symbol = &params.symbol;

        // Detect if input is a node ID (has known prefix)
        let is_node_id = symbol.starts_with("fn:")
            || symbol.starts_with("cls:")
            || symbol.starts_with("mod:")
            || symbol.starts_with("ext:")
            || symbol.starts_with("msg:");

        let result = if is_node_id {
            state.mubase.query_params(
                "SELECT type, name, file_path, line_start, line_end, node_category, id FROM nodes WHERE id = ?1 LIMIT 1",
                &[&symbol.as_str()],
            )
        } else {
            state
                .mubase
                .query_params(FIND_SYMBOL_SQL, &[&symbol.as_str()])
        }
        .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let mut output = String::new();
        if is_node_id {
            output.push_str(&format!("# find: \"{}\" (node ID lookup)\n", symbol));
        } else {
            output.push_str(&format!("# find: \"{}\"\n", symbol));
        }
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
            let category = row.get(5).and_then(|v| v.as_str()).unwrap_or("production");
            let cat_tag = match category {
                "production" | "" => "",
                "test" => " [test]",
                "generated" => " [generated]",
                "infrastructure" | "infra" => " [infra]",
                _ => " [other]",
            };

            output.push_str(&format!(
                "## {}{} [{}]{}\n",
                sigil, name, node_type, cat_tag
            ));
            if let Some(node_id) = row.get(6).and_then(|v| v.as_str()) {
                output.push_str(&format!("id: {}\n", node_id));
            }
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
        description = "Token-efficient overview of the entire codebase structure. Shows all modules, classes, and functions with importance markers. Use for initial orientation on an unfamiliar codebase or to answer 'what services/modules exist?' NOT for: finding specific code (use mu_grok or mu_find)."
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
        description = "Find everything that depends on a symbol — the blast radius. Use when asking 'what breaks if I change X?' Returns all downstream dependents across the entire codebase including cross-service dependencies. This is MU's strongest tool for understanding change risk. NOT for: finding code (use mu_grok), understanding what a function calls (use mu_expand with direction='outgoing')."
    )]
    async fn mu_impact(
        &self,
        Parameters(params): Parameters<ImpactParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        // Find the target node — try exact ID first, then name with priority ordering.
        // Class beats function: in C#/Java a constructor function shares the class
        // name, and resolving "NotificationsService" to the constructor gives a
        // near-empty blast radius. Class beats module so "BaseService" resolves to
        // the class, not the file.
        let target_result = state
            .mubase
            .query_params(IMPACT_TARGET_SQL, &[&params.symbol as &dyn duckdb::ToSql])
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let target = target_result
            .rows
            .first()
            .map(|row| NodeResult {
                node_id: row
                    .first()
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                name: row
                    .get(1)
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                kind: row
                    .get(2)
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                file_path: row
                    .get(3)
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                line_start: row.get(4).and_then(|v| v.as_u64()).unwrap_or(0) as u32,
                line_end: row.get(5).and_then(|v| v.as_u64()).unwrap_or(0) as u32,
                score: None,
                match_type: None,
                importance: row.get(6).and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                summary: row.get(7).and_then(|v| v.as_str()).map(|s| s.to_string()),
                node_category: row
                    .get(8)
                    .and_then(|v| v.as_str())
                    .unwrap_or("production")
                    .to_string(),
            })
            .unwrap_or_else(|| NodeResult {
                node_id: String::new(),
                name: params.symbol.clone(),
                kind: "unknown".to_string(),
                file_path: String::new(),
                line_start: 0,
                line_end: 0,
                score: None,
                match_type: None,
                importance: 0.0,
                summary: None,
                node_category: "production".to_string(),
            });

        // Full BFS traversal for transitive dependents (incoming edges)
        let graph = crate::commands::graph::GraphData::from_mubase(&state.mubase)
            .map_err(|e| McpError::internal_error(format!("Failed to load graph: {}", e), None))?;

        let dependent_ids = if !target.node_id.is_empty() {
            if target.kind == "class" {
                // Callers point at method nodes, not the class node. Seed the BFS
                // with the class AND its members so "what breaks if this class
                // changes" includes everything that calls any of its methods.
                let members = graph.contained_members(&target.node_id);
                let mut seeds: Vec<&str> = vec![target.node_id.as_str()];
                seeds.extend(members.iter().map(|s| s.as_str()));
                graph.dependents_many(&seeds, None, None)
            } else {
                graph.dependents(&target.node_id, None, None)
            }
        } else {
            vec![]
        };

        let mut dependents = Vec::new();
        let mut edges = Vec::new();

        if !dependent_ids.is_empty() {
            // Bulk-fetch node details for all BFS-discovered dependents
            // DuckDB doesn't support parameterized IN-lists, so use a temp table
            let ids_csv: String = dependent_ids
                .iter()
                .map(|id| format!("('{}')", id.replace('\'', "''")))
                .collect::<Vec<_>>()
                .join(",");

            let detail_sql = format!(
                "SELECT n.id, n.name, n.type, n.file_path, n.line_start, n.line_end,
                        n.importance_score, n.summary_text, n.node_category
                 FROM nodes n
                 WHERE n.id IN (SELECT col0 FROM (VALUES {}) AS t(col0))
                 ORDER BY n.importance_score DESC",
                ids_csv
            );

            if let Ok(detail_result) = state.mubase.query_params(&detail_sql, &[]) {
                for row in &detail_result.rows {
                    let dep_id = row
                        .first()
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    let dep_name = row
                        .get(1)
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();

                    dependents.push(NodeResult {
                        node_id: dep_id.clone(),
                        name: dep_name.clone(),
                        kind: row
                            .get(2)
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        file_path: row
                            .get(3)
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        line_start: row.get(4).and_then(|v| v.as_u64()).unwrap_or(0) as u32,
                        line_end: row.get(5).and_then(|v| v.as_u64()).unwrap_or(0) as u32,
                        score: None,
                        match_type: None,
                        importance: row.get(6).and_then(|v| v.as_f64()).unwrap_or(0.0) as f32,
                        summary: row.get(7).and_then(|v| v.as_str()).map(|s| s.to_string()),
                        node_category: row
                            .get(8)
                            .and_then(|v| v.as_str())
                            .unwrap_or("production")
                            .to_string(),
                    });

                    edges.push(EdgeResult {
                        source_id: dep_id,
                        source_name: dep_name,
                        target_id: target.node_id.clone(),
                        target_name: target.name.clone(),
                        edge_type: "depends_on".to_string(),
                    });
                }
            }
        }

        // If the symbol didn't match any node, suggest similar names via fuzzy LIKE
        if target.node_id.is_empty() && dependents.is_empty() {
            // Try full name first, then strip last PascalCase word to find core concept
            // "CreditNoteService" → try "%CreditNoteService%", then "%CreditNote%"
            let mut patterns = vec![format!("%{}%", params.symbol)];
            let core = strip_trailing_pascal_word(&params.symbol);
            if core.len() >= 3 && core != params.symbol {
                patterns.push(format!("%{}%", core));
            }

            for like_pattern in &patterns {
                let suggestions = state
                    .mubase
                    .query_params(
                        "SELECT name, type, file_path FROM nodes
                     WHERE name LIKE ?1 AND node_category = 'production'
                     ORDER BY importance_score DESC LIMIT 5",
                        &[like_pattern as &dyn duckdb::ToSql],
                    )
                    .map_err(|e| McpError::internal_error(e.to_string(), None))?;

                if !suggestions.rows.is_empty() {
                    let names: Vec<String> = suggestions
                        .rows
                        .iter()
                        .map(|row| {
                            let name = row.first().and_then(|v| v.as_str()).unwrap_or("");
                            let kind = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
                            let file = row
                                .get(2)
                                .and_then(|v| v.as_str())
                                .and_then(|p| p.rsplit('/').next())
                                .unwrap_or("");
                            format!("  - {} ({}, {})", name, kind, file)
                        })
                        .collect();
                    return Ok(CallToolResult::success(vec![Content::text(format!(
                        "No symbol '{}' found. Did you mean:\n{}\n\nTry mu_impact with one of these exact names.",
                        params.symbol, names.join("\n")
                    ))]));
                }
            }
            return Ok(CallToolResult::success(vec![Content::text(format!(
                "No symbol '{}' found, and no similar names in the codebase.",
                params.symbol
            ))]));
        }

        let response = ImpactResponse {
            target: target.clone(),
            dependents,
            edges,
        };

        // Format structured response
        let mut output = format_impact_response(&response);

        // If graph is sparse, supplement with grep
        if response.dependents.len() < 5 {
            output.push_str("\n## Text References (grep)\n");

            let grep_result = Command::new("grep")
                .args([
                    "-rn",
                    "--include=*.rs",
                    "--include=*.py",
                    "--include=*.ts",
                    "--include=*.js",
                    "--include=*.go",
                    "--include=*.java",
                    "--include=*.cs",
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
                    for file in &file_list {
                        output.push_str(&format!("    {}\n", file));
                    }

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
                            "--include=*.cs",
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
        description = "Semantic diff between git refs. Shows what changed structurally between branches or commits — new functions, removed classes, changed signatures, breaking changes. Use for understanding what changed in a branch. NOT for: full PR review with risk scoring (use mu_review)."
    )]
    async fn mu_diff(
        &self,
        Parameters(params): Parameters<DiffParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let base = params
            .base_ref
            .unwrap_or_else(|| crate::commands::diff::detect_default_branch(&state.project_root));

        let diff_result = crate::commands::diff::semantic_diff(&state.project_root, &base, "HEAD")
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
        let added: Vec<_> = diff_result
            .changes
            .iter()
            .filter(|c| c.change_type == "added")
            .collect();
        let modified: Vec<_> = diff_result
            .changes
            .iter()
            .filter(|c| c.change_type == "modified" || c.change_type == "signature_changed")
            .collect();
        let removed: Vec<_> = diff_result
            .changes
            .iter()
            .filter(|c| c.change_type == "removed")
            .collect();

        if !added.is_empty() {
            output.push_str(&format!("## Added ({})\n\n", added.len()));
            for change in &added {
                output.push_str(&format!(
                    "- `{}` [{}]",
                    change.entity_name, change.entity_type
                ));
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
                let marker = if change.is_breaking {
                    " **BREAKING**"
                } else {
                    ""
                };
                output.push_str(&format!(
                    "- `{}` [{}]{}",
                    change.entity_name, change.entity_type, marker
                ));
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
                let marker = if change.is_breaking {
                    " **BREAKING**"
                } else {
                    ""
                };
                output.push_str(&format!(
                    "- `{}` [{}]{}",
                    change.entity_name, change.entity_type, marker
                ));
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
        description = "Find suspicious, risky, or complex code. Returns high-complexity functions, security-sensitive code, and large functions. Use for code review, pre-release audits, or finding refactoring targets. Respects config filters — run mu_configure first for best results. NOT for: reviewing a specific PR (use mu_review), or checking code quality rules (use mu_audit)."
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
        let complex = state
            .mubase
            .query_params(
                "SELECT name, type, file_path, complexity FROM nodes
                 WHERE complexity >= ?1 AND type = 'function'
                   AND node_category = 'production'
                 ORDER BY complexity DESC LIMIT 15",
                &[&min_complexity as &dyn duckdb::ToSql],
            )
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
            WHERE node_category = 'production'
              AND (LOWER(name) LIKE '%auth%'
               OR LOWER(name) LIKE '%token%'
               OR LOWER(name) LIKE '%password%'
               OR LOWER(name) LIKE '%secret%'
               OR LOWER(name) LIKE '%crypt%'
               OR LOWER(name) LIKE '%credential%'
               OR LOWER(name) LIKE '%api_key%')
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
              AND node_category = 'production'
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

    /// Expand: Graph traversal from seed nodes
    #[tool(
        description = "Explore the dependency graph around a node. Use to understand what a function calls, what calls it, what it inherits from, and what it contains. Start with a node_id from mu_grok or mu_find, then expand to see its neighborhood. Use depth=1 for immediate neighbors, depth=2 for the extended graph. Best for: understanding how code connects, tracing call chains, finding related code. For full impact analysis across the whole codebase, use mu_impact instead."
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
        description = "Read the full source code of specific nodes by ID. Use after mu_grok or mu_expand to see the actual implementation. Modes: 'source' for full code, 'signature' for just the function signature, 'summary' for the description, 'full' for source + neighbor signatures. Requires node_ids from a previous tool call."
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
        description = "Improve search quality by writing better summaries for important nodes. Call with no args to get the highest-priority nodes that need enrichment. Call with summaries to store them. Each enrichment cycle makes future mu_grok searches more accurate. Use after mu_configure for best results."
    )]
    async fn mu_enrich(
        &self,
        Parameters(params): Parameters<tools_v3::EnrichNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let output = tools_v3::handle_enrich_nodes(&state.mubase, &state.project_root, &params)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Configure: Auto-detect codebase patterns (interactive)
    #[tool(
        description = "Interactive codebase configuration. Three modes: (1) Discovery — call with no args to auto-detect patterns, get a draft config with review questions. (2) Corrections — call with `corrections` JSON to refine the config; returns confirmation plus enrichment candidates to summarize inline. (3) Enrich more — call with action='enrich_more' to get the next batch of enrichment candidates."
    )]
    async fn mu_configure(
        &self,
        Parameters(params): Parameters<ConfigureParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        if let Some(ref corrections_json) = params.corrections {
            // Correction mode: apply corrections, save, then append enrichment candidates
            let mut config = crate::engine::auto_config::AutoConfig::load(&state.project_root)
                .unwrap_or_else(|| {
                    crate::engine::auto_config::AutoConfig::generate(&state.mubase)
                        .unwrap_or_default()
                });

            let result = crate::engine::auto_config::apply_corrections(
                &mut config,
                corrections_json,
                &state.mubase,
            )
            .map_err(|e| McpError::internal_error(format!("corrections failed: {}", e), None))?;

            config.save(&state.project_root).map_err(|e| {
                McpError::internal_error(format!("failed to save config: {}", e), None)
            })?;

            let mut output = result;
            output.push_str("\n\n");
            output.push_str(&crate::engine::auto_config::format_summary(&config));

            // Append enrichment candidates so the LLM can write summaries inline
            output.push_str("\n\n---\n\n## Enrichment — Phase 1\n\n");
            let candidates = tools_v3::format_enrichment_candidates(
                &state.mubase,
                Some(&config),
                None,
                Some(20),
            )
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;
            output.push_str(&candidates);
            output.push_str(
                "\n\nAfter writing summaries, call `mu_enrich` to store them, \
                then `mu_configure(action=\"enrich_more\")` for the next batch.",
            );

            Ok(CallToolResult::success(vec![Content::text(output)]))
        } else if params.action.as_deref() == Some("enrich_more") {
            // Enrich-more mode: load config, return next batch of candidates
            let config = crate::engine::auto_config::AutoConfig::load(&state.project_root);
            let candidates = tools_v3::format_enrichment_candidates(
                &state.mubase,
                config.as_ref(),
                None,
                Some(20),
            )
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

            let mut output = String::from("## Enrichment — Next Batch\n\n");
            output.push_str(&candidates);
            output.push_str(
                "\n\nAfter writing summaries, call `mu_enrich` to store them, \
                then `mu_configure(action=\"enrich_more\")` for more.",
            );

            Ok(CallToolResult::success(vec![Content::text(output)]))
        } else {
            // Discovery mode: generate draft, questions, enrichment suggestions
            let config =
                crate::engine::auto_config::AutoConfig::generate(&state.mubase).map_err(|e| {
                    McpError::internal_error(format!("config generation failed: {}", e), None)
                })?;

            // Save the draft so tools can use it immediately
            config.save(&state.project_root).map_err(|e| {
                McpError::internal_error(format!("failed to save config: {}", e), None)
            })?;

            let questions = crate::engine::auto_config::generate_questions(&config, &state.mubase)
                .unwrap_or_default();

            let enrichment_ids =
                crate::engine::auto_config::suggest_enrichment_nodes(&state.mubase)
                    .unwrap_or_default();

            let summary = crate::engine::auto_config::format_discovery_summary(
                &config,
                &questions,
                &enrichment_ids,
            );
            Ok(CallToolResult::success(vec![Content::text(summary)]))
        }
    }

    /// Bootstrap: Build or rebuild the MU code graph from within MCP
    #[tool(
        description = "Build or rebuild the MU code graph without leaving the MCP session. Use this instead of asking the user to run 'mu bootstrap' in a terminal. Drops the current database connection, rebuilds the graph, then the next tool call reconnects automatically. Defaults to force=true (full rebuild). Use after code changes to refresh the index, or on first setup."
    )]
    async fn mu_bootstrap(
        &self,
        Parameters(params): Parameters<BootstrapParams>,
    ) -> Result<CallToolResult, McpError> {
        let dir = self.resolve_project_dir(params.path.as_deref()).await?;
        let force = params.force.unwrap_or(true);

        // Drop existing connection so bootstrap can write
        self.reset_state().await;

        let result = crate::commands::bootstrap::bootstrap_pipeline(&dir, force, None)
            .map_err(|e| McpError::internal_error(format!("bootstrap failed: {}", e), None))?;

        // Format result as markdown
        let mut output = String::new();
        if result.already_existed {
            output.push_str("# Bootstrap: Already Initialized\n\n");
            output.push_str(&format!(
                "Nodes: {} | Edges: {}\n",
                result.node_count, result.edge_count
            ));
            output.push_str("\nPass `force: true` to rebuild.\n");
        } else if result.files_scanned == 0 {
            output.push_str("# Bootstrap: No Files Found\n\n");
            output.push_str(&format!(
                "No supported source files in `{}`.\n",
                dir.display()
            ));
        } else {
            output.push_str("# Bootstrap Complete\n\n");
            output.push_str(&format!(
                "Scanned {} files, parsed {} ({} cached) in {}ms\n",
                result.files_scanned, result.files_parsed, result.files_cached, result.duration_ms
            ));
            output.push_str(&format!(
                "Graph: {} nodes, {} edges\n",
                result.node_count, result.edge_count
            ));
            if result.importance_scores_computed > 0 {
                output.push_str(&format!(
                    "PageRank: {} scores | Summaries: {} | FTS: {}\n",
                    result.importance_scores_computed,
                    result.summaries_generated,
                    if result.fts_index_created {
                        "rebuilt"
                    } else {
                        "skipped"
                    }
                ));
            }
            if result.config_created || result.gitignore_updated {
                output.push_str("\nSetup: ");
                if result.config_created {
                    output.push_str(".murc.toml created ");
                }
                if result.gitignore_updated {
                    output.push_str(".gitignore updated");
                }
                output.push('\n');
            }
        }

        // State will auto-reinitialize on the next tool call
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// Audit: Run code quality rules and report violations
    #[tool(
        description = "Code quality rules — finds complexity violations, missing docs, code smells, hardcoded secrets, TODO/FIXMEs, and suspicious patterns. Supports scoping to changed files via diff_base. NOT for: finding the riskiest functions globally (use mu_sus), or full PR review with impact analysis (use mu_review)."
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
        description = "Full PR/code review combining diff + impact + audit + risk scoring. Use before merging to understand what changed, what might break, and how risky the changes are. This is the all-in-one tool for PR review — it runs mu_diff, mu_impact, and mu_audit together. NOT for: just seeing what changed (use mu_diff), or just checking quality rules (use mu_audit)."
    )]
    async fn mu_review(
        &self,
        Parameters(params): Parameters<ReviewParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let base = params
            .base_ref
            .unwrap_or_else(|| crate::commands::diff::detect_default_branch(&state.project_root));
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
                "MU gives you deep codebase understanding through 13 tools. Here's how to pick the right one:\n\
                 \n\
                 FINDING CODE:\n\
                 • Know the exact name? → mu_find (fastest, most precise)\n\
                 • Know roughly what you want? → mu_grok (keyword search, ranked results)\n\
                 • Need the full source after find/grok? → mu_read (pass node_ids from previous results)\n\
                 \n\
                 UNDERSTANDING STRUCTURE:\n\
                 • What does this function call / what calls it? → mu_expand (graph neighbors)\n\
                 • What breaks if I change this? → mu_impact (full downstream blast radius)\n\
                 • What services/modules exist? → mu_compress (codebase overview)\n\
                 \n\
                 CODE QUALITY:\n\
                 • Risky/complex code? → mu_sus\n\
                 • Full PR review? → mu_review (diff + impact + audit + risk score)\n\
                 • Quality rules only? → mu_audit\n\
                 • What changed in a branch? → mu_diff\n\
                 \n\
                 SETUP & IMPROVEMENT:\n\
                 • First time? Run mu_bootstrap then mu_configure. After corrections, MU suggests nodes to enrich — write summaries, call mu_enrich. Use mu_configure(action=\"enrich_more\") for more batches.\n\
                 • Need to rebuild the index? → mu_bootstrap (rebuilds without leaving the session)\n\
                 • Improve search quality? → mu_enrich\n\
                 \n\
                 TIPS:\n\
                 • Chain tools: mu_grok to find → mu_expand to understand neighbors → mu_read for source\n\
                 • If mu_grok returns LOW confidence, try mu_find with a specific name instead\n\
                 • For 'how does X flow work', start with mu_grok, then mu_expand + mu_read on the hits\n\
                 • For 'what depends on X', always use mu_impact, not mu_grok".into()
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

/// Strip the last PascalCase word from a symbol name.
/// "CreditNoteService" → "CreditNote", "PaymentProcessor" → "Payment"
fn strip_trailing_pascal_word(s: &str) -> &str {
    let bytes = s.as_bytes();
    // Walk backwards to find the last uppercase letter that starts a word
    for i in (1..bytes.len()).rev() {
        if bytes[i].is_ascii_uppercase() {
            return &s[..i];
        }
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::storage::MUbase;

    fn seed_db() -> MUbase {
        let dir = tempfile::tempdir().unwrap();
        let mubase = MUbase::open(dir.path().join("mubase")).unwrap();
        mubase
            .with_connection(|conn| {
                conn.execute_batch(
                    r#"
                    INSERT INTO nodes (id, type, name, qualified_name, file_path, line_start, line_end, importance_score)
                    VALUES
                        ('cls:svc.cs:NotificationsService', 'class', 'NotificationsService',
                         'NotificationsService', 'svc.cs', 10, 400, 0.5),
                        ('fn:svc.cs:NotificationsService.NotificationsService', 'function', 'NotificationsService',
                         'NotificationsService.NotificationsService', 'svc.cs', 20, 40, 0.9),
                        ('fn:svc.cs:NotificationsService.SendEmailAsync', 'function', 'SendEmailAsync',
                         'NotificationsService.SendEmailAsync', 'svc.cs', 50, 120, 0.4),
                        ('mod:svc.cs', 'module', 'NotificationsService', NULL, 'svc.cs', 1, 400, 0.6)
                    "#,
                )?;
                Ok(())
            })
            .unwrap();
        std::mem::forget(mubase.clone());
        mubase
    }

    #[test]
    fn test_impact_target_prefers_class_over_constructor() {
        // C#: the constructor function shares the class name and here even has
        // higher importance. The class must still win, or blast radius starts
        // from a node with no meaningful incoming edges.
        let mubase = seed_db();
        let result = mubase
            .query_params(
                IMPACT_TARGET_SQL,
                &[&"NotificationsService" as &dyn duckdb::ToSql],
            )
            .unwrap();
        let row = result.rows.first().expect("target row");
        assert_eq!(row.get(2).and_then(|v| v.as_str()), Some("class"));
        assert_eq!(
            row.first().and_then(|v| v.as_str()),
            Some("cls:svc.cs:NotificationsService")
        );
    }

    #[test]
    fn test_impact_target_exact_id_still_wins() {
        let mubase = seed_db();
        let result = mubase
            .query_params(
                IMPACT_TARGET_SQL,
                &[&"fn:svc.cs:NotificationsService.SendEmailAsync" as &dyn duckdb::ToSql],
            )
            .unwrap();
        let row = result.rows.first().expect("target row");
        assert_eq!(row.get(2).and_then(|v| v.as_str()), Some("function"));
    }

    #[test]
    fn test_find_symbol_accepts_qualified_name() {
        // "Class.Method" inputs must resolve; the eval showed agents naturally
        // pass qualified names and previously got zero matches.
        let mubase = seed_db();
        let result = mubase
            .query_params(
                FIND_SYMBOL_SQL,
                &[&"NotificationsService.SendEmailAsync" as &dyn duckdb::ToSql],
            )
            .unwrap();
        assert!(!result.rows.is_empty(), "qualified name should match");
        let ids: Vec<&str> = result
            .rows
            .iter()
            .filter_map(|r| r.get(6).and_then(|v| v.as_str()))
            .collect();
        assert!(ids.contains(&"fn:svc.cs:NotificationsService.SendEmailAsync"));
    }

    #[test]
    fn test_find_symbol_bare_name_unchanged() {
        let mubase = seed_db();
        let result = mubase
            .query_params(FIND_SYMBOL_SQL, &[&"SendEmailAsync" as &dyn duckdb::ToSql])
            .unwrap();
        assert!(!result.rows.is_empty());
    }
}
