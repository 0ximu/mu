//! MCP Server implementation for MU
//!
//! Exposes MU capabilities as MCP tools that can be called by AI assistants.
//! V3: search_nodes, expand_nodes, read_nodes, pack_context, enrich_nodes.

use crate::mubase::find_project_root;
use std::fs;
#[allow(unused_imports)]
use std::future::Future;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;

use rmcp::{
    handler::server::{router::tool::ToolRouter, tool::Parameters},
    model::{ErrorData as McpError, *},
    schemars::JsonSchema,
    tool, tool_handler, tool_router, ServerHandler,
};
use serde::Deserialize;
use tokio::sync::{OnceCell, RwLock};

use super::tools_v3;

/// Lazily-initialized project state
struct ProjectState {
    mubase: mu_daemon::storage::MUbase,
    project_root: PathBuf,
}

/// MU MCP Server - exposes codebase intelligence tools via MCP.
///
/// V3 tools provide structured graph access: search, expand, read, pack, enrich.
///
/// Supports dynamic project detection via MCP client roots - the server will
/// use the client's working directory instead of its own CWD.
#[derive(Clone)]
pub struct MuMcpServer {
    /// Lazily-initialized project state (mubase + project_root)
    state: Arc<OnceCell<ProjectState>>,
    /// Client roots received during MCP initialization
    client_roots: Arc<RwLock<Option<Vec<Root>>>>,
    /// Fallback directory if no client roots are provided
    fallback_dir: PathBuf,
    tool_router: ToolRouter<MuMcpServer>,
}

// ============================================================================
// V3 Tool Parameter Structs
// ============================================================================

#[derive(Debug, Deserialize, JsonSchema)]
pub struct SearchNodesParams {
    /// Natural language query or symbol name to search for
    #[schemars(description = "Natural language query or exact symbol name")]
    pub query: String,
    /// Maximum results to return (default: 5)
    #[schemars(description = "Number of results (1-20, default: 5)")]
    pub limit: Option<usize>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ExpandNodesParams {
    /// Node IDs to expand from (e.g., ["fn:src/lib.rs:main"])
    #[schemars(description = "Node IDs to expand from")]
    pub node_ids: Vec<String>,
    /// How many hops to traverse (default: 1)
    #[schemars(description = "Graph traversal depth (1-3, default: 1)")]
    pub depth: Option<u8>,
    /// Filter to specific edge types (e.g., ["calls", "uses"])
    #[schemars(description = "Edge types to follow (e.g., calls, uses, imports, contains, inherits)")]
    pub edge_types: Option<Vec<String>>,
    /// Direction: "outgoing", "incoming", or "both" (default: "outgoing")
    #[schemars(description = "Traversal direction: outgoing, incoming, or both")]
    pub direction: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ReadNodesParams {
    /// Node IDs to read
    #[schemars(description = "Node IDs to read")]
    pub node_ids: Vec<String>,
    /// Detail level: "signature", "summary", "source", "full" (default: "source")
    #[schemars(description = "Detail mode: signature (first line), summary (text summary), source (full code), full (source + neighbors)")]
    pub mode: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct PackContextParams {
    /// Specific node IDs to pack (omit for project overview)
    #[schemars(description = "Node IDs to pack. Omit for automatic project overview.")]
    pub node_ids: Option<Vec<String>>,
    /// Token budget (default: 4000)
    #[schemars(description = "Approximate token budget (default: 4000)")]
    pub budget: Option<usize>,
    /// Layout style: "grouped" (by file) or "flat" (default: "grouped")
    #[schemars(description = "Layout: grouped (by file) or flat")]
    pub style: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct EnrichNodesParams {
    /// Filter to specific node IDs when requesting candidates
    #[schemars(description = "Filter candidates to these node IDs")]
    pub node_ids: Option<Vec<String>>,
    /// Store LLM-generated summaries for nodes
    #[schemars(description = "Summaries to store: [{node_id, summary}, ...]")]
    pub summaries: Option<Vec<NodeSummaryInput>>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct NodeSummaryInput {
    /// The node ID
    #[schemars(description = "Node ID")]
    pub node_id: String,
    /// LLM-generated summary text
    #[schemars(description = "Summary text")]
    pub summary: String,
}

// Unchanged tool parameter structs

#[derive(Debug, Deserialize, JsonSchema)]
pub struct FindParams {
    #[schemars(description = "Exact symbol name to find (e.g., 'parse_config', 'UserService')")]
    pub symbol: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ImpactParams {
    #[schemars(description = "Symbol name to analyze (e.g., 'DatabaseConnection')")]
    pub symbol: String,
    #[schemars(description = "Include cross-service edges like MassTransit pub/sub, HTTP calls, shared contracts (default: false)")]
    pub cross_service: Option<bool>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct DiffParams {
    #[schemars(description = "Base git ref (e.g., 'main', 'HEAD~5', 'v1.0.0')")]
    pub base_ref: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct WtfParams {
    #[schemars(description = "File path to investigate (e.g., 'src/auth/login.rs')")]
    pub file: String,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct SusParams {
    #[schemars(description = "Minimum complexity score to flag (default: 15)")]
    pub min_complexity: Option<i64>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct AuditParams {
    #[schemars(description = "Complexity threshold (default: 30)")]
    pub min_complexity: Option<u32>,
    #[schemars(description = "Git ref to scope audit to changed files only")]
    pub diff_base: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ReviewParams {
    #[schemars(description = "Base git ref to compare against (e.g., 'main', 'develop', 'HEAD~5')")]
    pub base_ref: Option<String>,
    #[schemars(description = "Include downstream impact analysis (default: true)")]
    pub include_impact: Option<bool>,
    #[schemars(description = "Complexity threshold for audit (default: 15)")]
    pub min_complexity: Option<u32>,
}

// ============================================================================
// Server implementation
// ============================================================================

#[tool_router]
impl MuMcpServer {
    pub fn new(fallback_dir: PathBuf) -> Self {
        Self {
            state: Arc::new(OnceCell::new()),
            client_roots: Arc::new(RwLock::new(None)),
            fallback_dir,
            tool_router: Self::tool_router(),
        }
    }

    async fn ensure_state(&self) -> Result<&ProjectState, McpError> {
        self.state
            .get_or_try_init(|| async {
                let start_dir = {
                    let roots = self.client_roots.read().await;
                    if let Some(ref root_list) = *roots {
                        if let Some(first_root) = root_list.first() {
                            let uri = &first_root.uri;
                            if let Some(path) = uri.strip_prefix("file://") {
                                PathBuf::from(path)
                            } else {
                                PathBuf::from(uri)
                            }
                        } else {
                            self.fallback_dir.clone()
                        }
                    } else {
                        self.fallback_dir.clone()
                    }
                };

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

                Ok(ProjectState { mubase, project_root })
            })
            .await
    }

    // ========================================================================
    // V3 Tools
    // ========================================================================

    #[tool(description = "Search the code graph by name or concept. Three-phase cascade: exact match, BM25 full-text, importance-weighted. Returns ranked results with node IDs for use with other tools.")]
    async fn mu_search(
        &self,
        Parameters(params): Parameters<SearchNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let limit = params.limit.unwrap_or(5).clamp(1, 20);
        let output = tools_v3::search_nodes_tool(&state.mubase, &state.project_root, &params.query, limit)
            .map_err(|e| McpError::internal_error(format!("search failed: {}", e), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Expand the code graph from seed nodes. Walk edges (calls, uses, imports, contains) outward/inward up to N hops. Use this to discover dependencies and dependents.")]
    async fn mu_expand(
        &self,
        Parameters(params): Parameters<ExpandNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let depth = params.depth.unwrap_or(1).clamp(1, 3);
        let direction = params.direction.as_deref().unwrap_or("outgoing");
        let edge_types_vec = params.edge_types.unwrap_or_default();
        let edge_types: Option<&[String]> = if edge_types_vec.is_empty() { None } else { Some(&edge_types_vec) };
        let output = tools_v3::expand_nodes_tool(&state.mubase, &params.node_ids, depth, edge_types, direction)
            .map_err(|e| McpError::internal_error(format!("expand failed: {}", e), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Read node details by ID. Modes: 'signature' (declaration line), 'summary' (text summary), 'source' (full code), 'full' (source + neighbors). Use node IDs from mu_search or mu_expand.")]
    async fn mu_read(
        &self,
        Parameters(params): Parameters<ReadNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let mode = params.mode.as_deref().unwrap_or("source");
        let output = tools_v3::read_nodes_tool(&state.mubase, &state.project_root, &params.node_ids, mode)
            .map_err(|e| McpError::internal_error(format!("read failed: {}", e), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Pack code context within a token budget. With node IDs: packs those nodes (full source, degrading to signature+summary). Without: packs project overview by importance. Use before asking an LLM about code.")]
    async fn mu_context(
        &self,
        Parameters(params): Parameters<PackContextParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let budget = params.budget.unwrap_or(4000).clamp(500, 50000);
        let style = params.style.as_deref().unwrap_or("grouped");
        let node_ids = params.node_ids.unwrap_or_default();
        let node_ids_ref: Option<&[String]> = if node_ids.is_empty() { None } else { Some(&node_ids) };
        let output = tools_v3::pack_context_tool(&state.mubase, &state.project_root, node_ids_ref, budget, style)
            .map_err(|e| McpError::internal_error(format!("context pack failed: {}", e), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Improve search quality by adding LLM summaries. Without summaries: returns high-importance nodes needing enrichment with source previews and prompt guidance. With summaries: stores them and rebuilds search index.")]
    async fn mu_enrich(
        &self,
        Parameters(params): Parameters<EnrichNodesParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let node_ids = params.node_ids.unwrap_or_default();
        let node_ids_ref: Option<&[String]> = if node_ids.is_empty() { None } else { Some(&node_ids) };
        let summaries_vec: Vec<(String, String)> = params.summaries.unwrap_or_default()
            .into_iter().map(|s| (s.node_id, s.summary)).collect();
        let summaries_ref: Option<&[(String, String)]> = if summaries_vec.is_empty() { None } else { Some(&summaries_vec) };
        let output = tools_v3::enrich_nodes_tool(&state.mubase, node_ids_ref, summaries_ref)
            .map_err(|e| McpError::internal_error(format!("enrich failed: {}", e), None))?;
        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    // ========================================================================
    // Unchanged tools
    // ========================================================================

    #[tool(description = "Find a specific symbol by exact name. Use this when you know the function/class name you're looking for.")]
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

        let result = state.mubase.query(&sql)
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
                "module" => "!", "class" => "$", "function" => "#", _ => "@",
            };

            output.push_str(&format!("## {}{} [{}]\n", sigil, name, node_type));
            output.push_str(&format!("{}:{}-{}\n", file_path, start_line, end_line));

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
                    if end > start + 30 { output.push_str("... (truncated)\n"); }
                    output.push_str("```\n");
                }
            }
            output.push('\n');
        }

        if result.rows.is_empty() {
            output.push_str("No exact matches. Try mu_search for fuzzy/semantic search.\n");
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Get a compressed overview of the entire codebase structure. Use this first to understand what's in the project.")]
    async fn mu_compress(&self) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let stats = state.mubase.query(
            "SELECT (SELECT COUNT(*) FROM nodes) as nodes, (SELECT COUNT(*) FROM edges) as edges, (SELECT COUNT(DISTINCT file_path) FROM nodes) as files")
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let (node_count, edge_count, file_count) = stats.rows.first()
            .map(|r| (
                r.first().and_then(|v| v.as_i64()).unwrap_or(0),
                r.get(1).and_then(|v| v.as_i64()).unwrap_or(0),
                r.get(2).and_then(|v| v.as_i64()).unwrap_or(0),
            ))
            .unwrap_or((0, 0, 0));

        let langs = state.mubase.query(
            "SELECT DISTINCT CASE WHEN file_path LIKE '%.rs' THEN 'Rust' WHEN file_path LIKE '%.py' THEN 'Python' WHEN file_path LIKE '%.ts' THEN 'TypeScript' WHEN file_path LIKE '%.js' THEN 'JavaScript' WHEN file_path LIKE '%.go' THEN 'Go' WHEN file_path LIKE '%.java' THEN 'Java' WHEN file_path LIKE '%.cs' THEN 'C#' ELSE 'Other' END as lang FROM nodes WHERE file_path IS NOT NULL")
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let languages: Vec<String> = langs.rows.iter()
            .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
            .filter(|s| s != "Other")
            .collect();

        let mut output = String::new();
        output.push_str("# MU Codebase Overview\n\n");
        output.push_str(&format!("Files: {} | Symbols: {} | Edges: {}\n", file_count, node_count, edge_count));
        output.push_str(&format!("Languages: {}\n\n", if languages.is_empty() { "Unknown".to_string() } else { languages.join(", ") }));

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

            let dir = file_path.rsplit_once('/').map(|(d, _)| d).unwrap_or("");
            if dir != current_dir && !dir.is_empty() {
                current_dir = dir.to_string();
                output.push_str(&format!("\n## {}/\n", dir));
            }

            if file_path != current_file && !file_path.is_empty() {
                current_file = file_path.to_string();
                let filename = file_path.rsplit_once('/').map(|(_, f)| f).unwrap_or(file_path);
                output.push_str(&format!("  ! {}\n", filename));
            }

            let sigil = match node_type {
                "module" => continue, "class" => "$", "function" => "#", _ => "@",
            };

            let complexity_indicator = if complexity > 20 { " !!" } else { "" };
            output.push_str(&format!("    {}{}{}\n", sigil, name, complexity_indicator));
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Find what code depends on a symbol. Shows what might break if you change it.")]
    async fn mu_impact(
        &self,
        Parameters(params): Parameters<ImpactParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;

        let mut output = String::new();
        output.push_str(&format!("# Impact Analysis: {}\n\n", params.symbol));

        let sql = format!(
            "SELECT DISTINCT n.name, n.type, n.file_path FROM edges e JOIN nodes n ON n.id = e.source_id WHERE e.target_id IN (SELECT id FROM nodes WHERE name = '{}') LIMIT 50",
            params.symbol.replace('\'', "''")
        );
        let result = state.mubase.query(&sql).map_err(|e| McpError::internal_error(e.to_string(), None))?;
        let graph_count = result.rows.len();

        if graph_count > 0 {
            output.push_str(&format!("## Graph Dependencies ({} found)\n", graph_count));
            for row in &result.rows {
                let name = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                output.push_str(&format!("  {} [{}] -- {}\n", name, node_type, file_path));
            }
            output.push('\n');
        }

        if params.cross_service.unwrap_or(false) {
            let cs_sql = format!(
                "SELECT DISTINCT e.type, n2.name, n2.type, n2.file_path, e.properties FROM edges e JOIN nodes n ON n.id = e.source_id OR n.id = e.target_id JOIN nodes n2 ON (n2.id = e.source_id OR n2.id = e.target_id) AND n2.id != n.id WHERE n.name = '{}' AND e.type IN ('publishes', 'subscribes', 'calls_http', 'uses_contract') LIMIT 30",
                params.symbol.replace('\'', "''")
            );
            if let Ok(cs_result) = state.mubase.query(&cs_sql) {
                if !cs_result.rows.is_empty() {
                    output.push_str(&format!("## Cross-Service Edges ({} found)\n", cs_result.rows.len()));
                    for row in &cs_result.rows {
                        let edge_type = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                        let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                        let node_type = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                        let file_path = row.get(3).and_then(|v| v.as_str()).unwrap_or("?");
                        output.push_str(&format!("  {} {} [{}] -- {}\n", edge_type, name, node_type, file_path));
                    }
                    output.push('\n');
                }
            }
        }

        if graph_count < 5 {
            output.push_str("## Text References (grep)\n");
            let grep_result = Command::new("grep")
                .args(["-rn", "--include=*.rs", "--include=*.py", "--include=*.ts", "--include=*.js", "--include=*.go", "--include=*.java", "-l", &params.symbol])
                .current_dir(&state.project_root).output();

            if let Ok(grep_out) = grep_result {
                let files = String::from_utf8_lossy(&grep_out.stdout);
                let file_list: Vec<&str> = files.lines().take(20).collect();
                if file_list.is_empty() {
                    output.push_str("  No text references found.\n");
                } else {
                    output.push_str(&format!("  Found in {} files:\n", file_list.len()));
                    for file in &file_list { output.push_str(&format!("    {}\n", file)); }

                    output.push_str("\n## Sample Usages\n");
                    let context_result = Command::new("grep")
                        .args(["-rn", "--include=*.rs", "--include=*.py", "--include=*.ts", "--include=*.js", "--include=*.go", "--include=*.java", "-C1", &params.symbol])
                        .current_dir(&state.project_root).output();
                    if let Ok(ctx) = context_result {
                        let context = String::from_utf8_lossy(&ctx.stdout);
                        output.push_str("```\n");
                        for line in context.lines().take(30) { output.push_str(line); output.push('\n'); }
                        output.push_str("```\n");
                    }
                }
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "See what symbols changed between git refs. Parses both versions and compares at the entity level -- shows functions/classes added, modified, or removed with breaking change detection.")]
    async fn mu_diff(
        &self,
        Parameters(params): Parameters<DiffParams>,
    ) -> Result<CallToolResult, McpError> {
        let _state = self.ensure_state().await?;
        let base = params.base_ref.unwrap_or_else(crate::commands::diff::detect_default_branch);
        let diff_result = crate::commands::diff::semantic_diff(&base, "HEAD")
            .map_err(|e| McpError::internal_error(format!("diff failed: {}", e), None))?;

        let mut output = String::new();
        output.push_str(&format!("# Semantic Diff: {} -> HEAD\n\n", base));
        output.push_str(&format!("{} changes ({} breaking) in {} files ({}ms)\n\n",
            diff_result.changes.len(), diff_result.breaking_changes.len(), diff_result.files_changed, diff_result.duration_ms));

        if !diff_result.breaking_changes.is_empty() {
            output.push_str("## Breaking Changes\n\n");
            for change in &diff_result.breaking_changes {
                output.push_str(&format!("- `{}` [{}] {} {}\n", change.entity_name, change.entity_type, change.change_type, change.description.as_deref().unwrap_or("")));
                if let Some(ref path) = change.file_path { output.push_str(&format!("  - {}\n", path)); }
            }
            output.push('\n');
        }

        let added: Vec<_> = diff_result.changes.iter().filter(|c| c.change_type == "added").collect();
        let modified: Vec<_> = diff_result.changes.iter().filter(|c| c.change_type == "modified" || c.change_type == "signature_changed").collect();
        let removed: Vec<_> = diff_result.changes.iter().filter(|c| c.change_type == "removed").collect();

        for (label, items) in [("Added", &added), ("Modified", &modified), ("Removed", &removed)] {
            if !items.is_empty() {
                output.push_str(&format!("## {} ({})\n\n", label, items.len()));
                for change in items {
                    let marker = if change.is_breaking { " **BREAKING**" } else { "" };
                    output.push_str(&format!("- `{}` [{}]{}", change.entity_name, change.entity_type, marker));
                    if let Some(ref path) = change.file_path { output.push_str(&format!(" -- {}", path)); }
                    output.push('\n');
                }
                output.push('\n');
            }
        }

        if diff_result.changes.is_empty() { output.push_str("No semantic changes detected.\n"); }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Find suspicious code: high complexity, security-sensitive names, large functions. Good for code review.")]
    async fn mu_sus(
        &self,
        Parameters(params): Parameters<SusParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let min_complexity = params.min_complexity.unwrap_or(15);

        let mut output = String::new();
        output.push_str("# Suspicious Code Report\n\n");

        let complex_sql = format!(
            "SELECT name, type, file_path, complexity FROM nodes WHERE complexity >= {} AND type = 'function' ORDER BY complexity DESC LIMIT 15",
            min_complexity
        );
        let complex = state.mubase.query(&complex_sql).map_err(|e| McpError::internal_error(e.to_string(), None))?;

        if !complex.rows.is_empty() {
            output.push_str(&format!("## High Complexity (>={}) -- {} found\n", min_complexity, complex.rows.len()));
            output.push_str("Functions that are hard to understand and maintain:\n\n");
            for row in &complex.rows {
                let name = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                let complexity = row.get(3).and_then(|v| v.as_i64()).unwrap_or(0);
                output.push_str(&format!("  #{} c={} -- {}\n", name, complexity, file_path));
            }
            output.push('\n');
        }

        let security_sql = "SELECT name, type, file_path FROM nodes WHERE LOWER(name) LIKE '%auth%' OR LOWER(name) LIKE '%token%' OR LOWER(name) LIKE '%password%' OR LOWER(name) LIKE '%secret%' OR LOWER(name) LIKE '%crypt%' OR LOWER(name) LIKE '%credential%' OR LOWER(name) LIKE '%api_key%' ORDER BY file_path LIMIT 20";
        let security = state.mubase.query(security_sql).map_err(|e| McpError::internal_error(e.to_string(), None))?;

        if !security.rows.is_empty() {
            output.push_str(&format!("## Security-Sensitive -- {} found\n", security.rows.len()));
            output.push_str("Code handling authentication, secrets, or credentials:\n\n");
            for row in &security.rows {
                let name = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                let sigil = match node_type { "class" => "$", "function" => "#", _ => "@" };
                output.push_str(&format!("  {}{} -- {}\n", sigil, name, file_path));
            }
            output.push('\n');
        }

        let large_sql = "SELECT name, file_path, (line_end - line_start) as lines FROM nodes WHERE type = 'function' AND line_end > line_start ORDER BY lines DESC LIMIT 10";
        if let Ok(large) = state.mubase.query(large_sql) {
            if !large.rows.is_empty() {
                output.push_str("## Large Functions (by lines)\nLong functions that might need refactoring:\n\n");
                for row in &large.rows {
                    let name = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                    let file_path = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                    let lines = row.get(2).and_then(|v| v.as_i64()).unwrap_or(0);
                    if lines > 50 { output.push_str(&format!("  #{} ({} lines) -- {}\n", name, lines, file_path)); }
                }
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Understand why code exists. Shows git history, recent changes, and who works on a file.")]
    async fn mu_wtf(
        &self,
        Parameters(params): Parameters<WtfParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let file_path = &params.file;
        let full_path = state.project_root.join(file_path);

        let mut output = String::new();
        output.push_str(&format!("# WTF: {}\n\n", file_path));

        let file_exists = full_path.exists();
        let is_tracked = Command::new("git").args(["ls-files", file_path]).current_dir(&state.project_root)
            .output().map(|o| !o.stdout.is_empty()).unwrap_or(false);

        if file_exists {
            if let Ok(metadata) = fs::metadata(&full_path) { output.push_str(&format!("Size: {} bytes\n", metadata.len())); }
            if let Ok(content) = fs::read_to_string(&full_path) { output.push_str(&format!("Lines: {}\n", content.lines().count())); }
        } else {
            output.push_str("File not found on disk\n");
        }

        output.push_str(&format!("Git tracked: {}\n\n", if is_tracked { "Yes" } else { "No" }));

        if is_tracked {
            output.push_str("## Recent Commits\n");
            if let Ok(log_out) = Command::new("git").args(["log", "--format=%h %ad %an: %s", "--date=short", "-10", "--", file_path]).current_dir(&state.project_root).output() {
                let log_str = String::from_utf8_lossy(&log_out.stdout);
                if log_str.is_empty() { output.push_str("  No commits yet (new file?)\n"); }
                else { for line in log_str.lines() { output.push_str(&format!("  {}\n", line)); } }
            }

            output.push_str("\n## Contributors\n");
            if let Ok(auth_out) = Command::new("git").args(["shortlog", "-sn", "--", file_path]).current_dir(&state.project_root).output() {
                let auth_str = String::from_utf8_lossy(&auth_out.stdout);
                for line in auth_str.lines().take(5) { output.push_str(&format!("  {}\n", line.trim())); }
            }

            output.push_str("\n## Origin\n");
            if let Ok(first_out) = Command::new("git").args(["log", "--format=%ad %an: %s", "--date=short", "--diff-filter=A", "--", file_path]).current_dir(&state.project_root).output() {
                let first_str = String::from_utf8_lossy(&first_out.stdout);
                if let Some(line) = first_str.lines().last() { output.push_str(&format!("  Created: {}\n", line)); }
            }
        } else if file_exists {
            output.push_str("## Status: Untracked file\nThis file exists but isn't in git yet.\n");
            if let Ok(content) = fs::read_to_string(&full_path) {
                output.push_str("\n## Preview\n```\n");
                for line in content.lines().take(10) { output.push_str(line); output.push('\n'); }
                output.push_str("```\n");
            }
        }

        let sql = format!("SELECT type, name, complexity FROM nodes WHERE file_path = '{}' ORDER BY line_start", file_path.replace('\'', "''"));
        if let Ok(nodes) = state.mubase.query(&sql) {
            if !nodes.rows.is_empty() {
                output.push_str("\n## Symbols in file\n");
                for row in &nodes.rows {
                    let node_type = row.first().and_then(|v| v.as_str()).unwrap_or("?");
                    let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                    let complexity = row.get(2).and_then(|v| v.as_i64()).unwrap_or(0);
                    if node_type == "module" { continue; }
                    let sigil = match node_type { "class" => "$", "function" => "#", _ => "@" };
                    output.push_str(&format!("  {}{}", sigil, name));
                    if complexity > 15 { output.push_str(&format!(" (c={})", complexity)); }
                    output.push('\n');
                }
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    #[tool(description = "Run code quality audit on the codebase. Finds dead code, high complexity, missing docs, hardcoded secrets, TODO/FIXMEs, unwrap abuse, and long parameter lists.")]
    async fn mu_audit(
        &self,
        Parameters(params): Parameters<AuditParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let result = crate::commands::audit::run_audit_for_mcp(&state.mubase, &state.project_root, params.min_complexity, params.diff_base.as_deref())
            .map_err(|e| McpError::internal_error(e, None))?;
        let md = crate::commands::audit::format_as_markdown(&result);
        Ok(CallToolResult::success(vec![Content::text(md)]))
    }

    #[tool(description = "Full PR review: semantic diff, downstream impact analysis, code audit, and risk scoring. Use this before merging.")]
    async fn mu_review(
        &self,
        Parameters(params): Parameters<ReviewParams>,
    ) -> Result<CallToolResult, McpError> {
        let state = self.ensure_state().await?;
        let base = params.base_ref.unwrap_or_else(crate::commands::diff::detect_default_branch);
        let include_impact = params.include_impact.unwrap_or(true);
        let min_complexity = params.min_complexity;
        let result = crate::commands::review::run_review(&state.mubase, &state.project_root, &base, include_impact, min_complexity)
            .map_err(|e| McpError::internal_error(e, None))?;
        let md = crate::commands::review::format_as_markdown(&result);
        Ok(CallToolResult::success(vec![Content::text(md)]))
    }
}

// ============================================================================
// ServerHandler
// ============================================================================

#[tool_handler]
impl ServerHandler for MuMcpServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: Default::default(),
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation {
                name: "mu".into(),
                version: env!("CARGO_PKG_VERSION").into(),
            },
            instructions: Some(
                "MU - semantic code intelligence (V3 tools).\n\n\
                 ## Primary workflow: search -> read/expand -> context\n\
                 1. `mu_search` -- find nodes by name or concept (returns node IDs)\n\
                 2. `mu_read` -- read node source/summary/signature by ID\n\
                 3. `mu_expand` -- walk graph edges from a node (calls, uses, imports)\n\
                 4. `mu_context` -- pack multiple nodes into a token budget\n\
                 5. `mu_enrich` -- improve search quality with LLM summaries\n\n\
                 ## Utility tools\n\
                 - `mu_find` -- exact symbol name lookup with code\n\
                 - `mu_compress` -- codebase structure overview\n\
                 - `mu_impact` -- downstream dependency analysis\n\
                 - `mu_diff` -- semantic diff between git refs\n\
                 - `mu_review` -- full PR review (diff + impact + audit)\n\
                 - `mu_audit` -- code quality rules\n\
                 - `mu_sus` -- suspicious/complex code finder\n\
                 - `mu_wtf` -- git archaeology for a file".into()
            ),
        }
    }

    async fn on_roots_list_changed(
        &self,
        context: rmcp::service::NotificationContext<rmcp::service::RoleServer>,
    ) {
        if let Ok(roots_result) = context.peer.list_roots().await {
            let mut client_roots = self.client_roots.write().await;
            *client_roots = Some(roots_result.roots);
        }
    }
}
