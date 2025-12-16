//! MCP Server implementation for MU
//!
//! Exposes MU capabilities as MCP tools that can be called by AI assistants.

use std::fs;
use std::future::Future;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::time::Instant;

use rmcp::{
    ServerHandler,
    handler::server::{router::tool::ToolRouter, tool::Parameters},
    model::{ErrorData as McpError, *},
    tool, tool_router, tool_handler,
    schemars::JsonSchema,
};
use serde::Deserialize;
use tokio::sync::OnceCell;

/// MU MCP Server - exposes codebase intelligence tools
#[derive(Clone)]
pub struct MuMcpServer {
    mubase: Arc<mu_daemon::storage::MUbase>,
    model: Arc<OnceCell<mu_embeddings::MuSigmaModel>>,
    project_root: PathBuf,
    tool_router: ToolRouter<MuMcpServer>,
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

#[tool_router]
impl MuMcpServer {
    pub fn new(mubase: mu_daemon::storage::MUbase, project_root: PathBuf) -> Self {
        Self {
            mubase: Arc::new(mubase),
            model: Arc::new(OnceCell::new()),
            project_root,
            tool_router: Self::tool_router(),
        }
    }

    /// Grok: Semantic search with actual code snippets
    #[tool(description = "Find and show relevant code for a question. Returns actual code snippets, not just locations. Use this to understand how something works.")]
    async fn mu_grok(&self, Parameters(params): Parameters<GrokParams>) -> Result<CallToolResult, McpError> {
        let start = Instant::now();
        let limit = params.limit.unwrap_or(3).min(10).max(1);

        // Get search results
        let results = if self.mubase.has_embeddings().unwrap_or(false) {
            self.run_semantic_search(&params.query, limit).await.unwrap_or_default()
        } else {
            self.run_keyword_search(&params.query, limit).unwrap_or_default()
        };

        let mut output = String::new();
        output.push_str(&format!("# grok: \"{}\"\n", params.query));
        output.push_str(&format!("# {} results in {}ms\n\n", results.len(), start.elapsed().as_millis()));

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
                i + 1, sigil, result.name, result.node_type,
                result.similarity * 100.0
            ));

            if let Some(ref path) = result.file_path {
                output.push_str(&format!("File: {}\n", path));

                // Read and show actual code snippet
                let full_path = self.project_root.join(path);
                if let Ok(content) = fs::read_to_string(&full_path) {
                    if let Some(snippet) = self.extract_snippet(&content, &result.name, &result.node_type) {
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
    #[tool(description = "Find a specific symbol by exact name. Use this when you know the function/class name you're looking for.")]
    async fn mu_find(&self, Parameters(params): Parameters<FindParams>) -> Result<CallToolResult, McpError> {
        let sql = format!(
            "SELECT type, name, file_path, line_start, line_end FROM nodes WHERE name = '{}' OR name LIKE '%.{}' LIMIT 10",
            params.symbol.replace('\'', "''"),
            params.symbol.replace('\'', "''")
        );

        let result = self.mubase.query(&sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let mut output = String::new();
        output.push_str(&format!("# find: \"{}\"\n", params.symbol));
        output.push_str(&format!("# {} matches\n\n", result.rows.len()));

        for row in &result.rows {
            let node_type = row.get(0).and_then(|v| v.as_str()).unwrap_or("?");
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
    #[tool(description = "Get a compressed overview of the entire codebase structure. Use this first to understand what's in the project.")]
    async fn mu_compress(&self) -> Result<CallToolResult, McpError> {
        // Get stats
        let stats = self.mubase.query("SELECT
            (SELECT COUNT(*) FROM nodes) as nodes,
            (SELECT COUNT(*) FROM edges) as edges,
            (SELECT COUNT(DISTINCT file_path) FROM nodes) as files")
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let (node_count, edge_count, file_count) = stats.rows.first()
            .map(|r| (
                r.get(0).and_then(|v| v.as_i64()).unwrap_or(0),
                r.get(1).and_then(|v| v.as_i64()).unwrap_or(0),
                r.get(2).and_then(|v| v.as_i64()).unwrap_or(0),
            ))
            .unwrap_or((0, 0, 0));

        // Detect languages
        let langs = self.mubase.query("SELECT DISTINCT
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
            FROM nodes WHERE file_path IS NOT NULL")
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let languages: Vec<String> = langs.rows.iter()
            .filter_map(|r| r.get(0).and_then(|v| v.as_str()).map(|s| s.to_string()))
            .filter(|s| s != "Other")
            .collect();

        let mut output = String::new();
        output.push_str("# MU Codebase Overview\n\n");
        output.push_str(&format!("Files: {} | Symbols: {} | Edges: {}\n", file_count, node_count, edge_count));
        output.push_str(&format!("Languages: {}\n\n", if languages.is_empty() { "Unknown".to_string() } else { languages.join(", ") }));

        // Get structure grouped by directory
        let nodes_result = self.mubase.query(
            "SELECT type, name, file_path, complexity FROM nodes ORDER BY file_path, type DESC, name LIMIT 500")
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let mut current_dir = String::new();
        let mut current_file = String::new();

        for row in &nodes_result.rows {
            let node_type = row.get(0).and_then(|v| v.as_str()).unwrap_or("");
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
                let filename = file_path.rsplit_once('/').map(|(_, f)| f).unwrap_or(file_path);
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
    #[tool(description = "Find what code depends on a symbol. Shows what might break if you change it.")]
    async fn mu_impact(&self, Parameters(params): Parameters<ImpactParams>) -> Result<CallToolResult, McpError> {
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

        let result = self.mubase.query(&sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        let graph_count = result.rows.len();

        if graph_count > 0 {
            output.push_str(&format!("## Graph Dependencies ({} found)\n", graph_count));
            for row in &result.rows {
                let name = row.get(0).and_then(|v| v.as_str()).unwrap_or("?");
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
                .args(["-rn", "--include=*.rs", "--include=*.py", "--include=*.ts",
                       "--include=*.js", "--include=*.go", "--include=*.java",
                       "-l", &params.symbol])
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
                        .args(["-rn", "--include=*.rs", "--include=*.py", "--include=*.ts",
                               "--include=*.js", "--include=*.go", "--include=*.java",
                               "-C1", &params.symbol])
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
    #[tool(description = "See what symbols changed between git refs. Shows functions/classes added, modified, or removed.")]
    async fn mu_diff(&self, Parameters(params): Parameters<DiffParams>) -> Result<CallToolResult, McpError> {
        // Detect default branch
        let base = params.base_ref.unwrap_or_else(|| {
            let result = Command::new("git")
                .args(["symbolic-ref", "refs/remotes/origin/HEAD"])
                .current_dir(&self.project_root)
                .output();

            result.ok()
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
        output.push_str(&format!("{} files changed: +{} ~{} -{}\n\n",
            total, added_files.len(), modified_files.len(), deleted_files.len()));

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
                    let symbols: Vec<String> = nodes.rows.iter()
                        .filter_map(|r| {
                            let t = r.get(0).and_then(|v| v.as_str())?;
                            let n = r.get(1).and_then(|v| v.as_str())?;
                            if t == "module" { return None; }
                            let sigil = match t { "class" => "$", "function" => "#", _ => "@" };
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
    #[tool(description = "Find suspicious code: high complexity, security-sensitive names, large functions. Good for code review.")]
    async fn mu_sus(&self, Parameters(params): Parameters<SusParams>) -> Result<CallToolResult, McpError> {
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
        let complex = self.mubase.query(&complex_sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        if !complex.rows.is_empty() {
            output.push_str(&format!("## High Complexity (≥{}) — {} found\n", min_complexity, complex.rows.len()));
            output.push_str("Functions that are hard to understand and maintain:\n\n");
            for row in &complex.rows {
                let name = row.get(0).and_then(|v| v.as_str()).unwrap_or("?");
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
        let security = self.mubase.query(security_sql)
            .map_err(|e| McpError::internal_error(e.to_string(), None))?;

        if !security.rows.is_empty() {
            output.push_str(&format!("## Security-Sensitive — {} found\n", security.rows.len()));
            output.push_str("Code handling authentication, secrets, or credentials:\n\n");
            for row in &security.rows {
                let name = row.get(0).and_then(|v| v.as_str()).unwrap_or("?");
                let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                let sigil = match node_type { "class" => "$", "function" => "#", _ => "@" };
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
                    let name = row.get(0).and_then(|v| v.as_str()).unwrap_or("?");
                    let file_path = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                    let lines = row.get(2).and_then(|v| v.as_i64()).unwrap_or(0);
                    if lines > 50 {
                        output.push_str(&format!("  #{} ({} lines) — {}\n", name, lines, file_path));
                    }
                }
            }
        }

        Ok(CallToolResult::success(vec![Content::text(output)]))
    }

    /// WTF: Git archaeology with context
    #[tool(description = "Understand why code exists. Shows git history, recent changes, and who works on a file.")]
    async fn mu_wtf(&self, Parameters(params): Parameters<WtfParams>) -> Result<CallToolResult, McpError> {
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

        output.push_str(&format!("Git tracked: {}\n\n", if is_tracked { "Yes" } else { "No" }));

        if is_tracked {
            // Recent commits
            output.push_str("## Recent Commits\n");
            let log = Command::new("git")
                .args(["log", "--format=%h %ad %an: %s", "--date=short", "-10", "--", file_path])
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
                .args(["log", "--format=%ad %an: %s", "--date=short", "--diff-filter=A", "--", file_path])
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
                    let node_type = row.get(0).and_then(|v| v.as_str()).unwrap_or("?");
                    let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                    let complexity = row.get(2).and_then(|v| v.as_i64()).unwrap_or(0);
                    if node_type == "module" { continue; }
                    let sigil = match node_type { "class" => "$", "function" => "#", _ => "@" };
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
}

// Helper methods
impl MuMcpServer {
    async fn run_semantic_search(&self, query: &str, limit: usize) -> anyhow::Result<Vec<SearchResult>> {
        let model = self.model
            .get_or_try_init(|| async { mu_embeddings::MuSigmaModel::embedded() })
            .await?;
        let embedding = model.embed_one(query)?;
        let results = self.mubase.vector_search(&embedding, limit, Some(0.3))?;

        Ok(results.into_iter().map(|r| SearchResult {
            name: r.name,
            node_type: r.node_type,
            file_path: r.file_path,
            start_line: None,
            end_line: None,
            similarity: r.similarity,
        }).collect())
    }

    fn run_keyword_search(&self, query: &str, limit: usize) -> anyhow::Result<Vec<SearchResult>> {
        let sql = format!(
            "SELECT type, name, file_path, line_start, line_end FROM nodes WHERE LOWER(name) LIKE '%{}%' LIMIT {}",
            query.to_lowercase().replace('\'', "''"), limit
        );
        let result = self.mubase.query(&sql)?;

        Ok(result.rows.iter().map(|row| SearchResult {
            name: row.get(1).and_then(|v| v.as_str()).unwrap_or("").to_string(),
            node_type: row.get(0).and_then(|v| v.as_str()).unwrap_or("").to_string(),
            file_path: row.get(2).and_then(|v| v.as_str()).map(|s| s.to_string()),
            start_line: row.get(3).and_then(|v| v.as_i64()),
            end_line: row.get(4).and_then(|v| v.as_i64()),
            similarity: 1.0,
        }).collect())
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
                    for j in i..lines.len().min(i + 50) {
                        let l = lines[j];
                        for c in l.chars() {
                            if c == '{' || c == '(' && !found_open {
                                brace_count += 1;
                                found_open = true;
                            } else if c == '}' || (c == ')' && found_open && brace_count == 1) {
                                brace_count -= 1;
                            }
                        }
                        end = j + 1;
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

#[derive(Debug, Default)]
struct SearchResult {
    name: String,
    node_type: String,
    file_path: Option<String>,
    start_line: Option<i64>,
    end_line: Option<i64>,
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
