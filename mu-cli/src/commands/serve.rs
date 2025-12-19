//! HTTP server with file watching for MU
//!
//! Provides:
//! - HTTP API on localhost:1337 (configurable)
//! - File watching with incremental graph updates
//! - Endpoints mirroring MCP tools (compress, search, oracle, etc.)

use anyhow::{Context, Result};
use axum::{
    extract::{Query, State},
    response::IntoResponse,
    routing::get,
    Json, Router,
};
use notify_debouncer_mini::{new_debouncer, notify::RecursiveMode, DebounceEventResult};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::RwLock;
use tower_http::cors::{Any, CorsLayer};
use tracing::{error, info, warn};

use crate::output::OutputFormat;

/// Default port for the serve command
pub const DEFAULT_PORT: u16 = 1337;

/// Shared state for the HTTP server
pub struct AppState {
    mubase: Arc<RwLock<mu_daemon::storage::MUbase>>,
    project_root: PathBuf,
    config: ServeConfig,
}

/// Configuration for the serve command
#[derive(Clone)]
#[allow(dead_code)]
pub struct ServeConfig {
    pub port: u16,
    pub watch: bool,
    pub embed: bool,
}

impl Default for ServeConfig {
    fn default() -> Self {
        Self {
            port: DEFAULT_PORT,
            watch: true,
            embed: false,
        }
    }
}

/// Response wrapper for API
#[derive(Serialize)]
pub struct ApiResponse<T> {
    pub success: bool,
    pub data: Option<T>,
    pub error: Option<String>,
    pub duration_ms: u64,
}

impl<T: Serialize> ApiResponse<T> {
    pub fn ok(data: T, duration_ms: u64) -> Self {
        Self {
            success: true,
            data: Some(data),
            error: None,
            duration_ms,
        }
    }

    pub fn err(error: String) -> Self {
        Self {
            success: false,
            data: None,
            error: Some(error),
            duration_ms: 0,
        }
    }
}

// ============================================================================
// Query parameters for endpoints
// ============================================================================

#[derive(Deserialize)]
pub struct SearchParams {
    pub q: String,
    #[serde(default = "default_limit")]
    pub limit: usize,
    #[serde(default = "default_threshold")]
    pub threshold: f32,
}

#[derive(Deserialize)]
pub struct CompressParams {
    #[serde(default = "default_detail")]
    pub detail: String,
}

#[derive(Deserialize)]
pub struct FindParams {
    pub symbol: String,
}

#[derive(Deserialize)]
pub struct ImpactParams {
    pub symbol: String,
}

// OracleParams will be used in future for /oracle endpoint
#[allow(dead_code)]
#[derive(Deserialize)]
pub struct OracleParams {
    pub task: String,
}

fn default_limit() -> usize {
    10
}
fn default_threshold() -> f32 {
    0.1
}
fn default_detail() -> String {
    "medium".to_string()
}

// ============================================================================
// Response types
// ============================================================================

#[derive(Serialize)]
pub struct StatusResponse {
    pub node_count: usize,
    pub edge_count: usize,
    pub has_embeddings: bool,
    pub project_root: String,
    pub watching: bool,
}

#[derive(Serialize)]
pub struct SearchResult {
    pub node_id: String,
    pub name: String,
    pub node_type: String,
    pub file_path: Option<String>,
    pub similarity: f32,
}

#[derive(Serialize)]
pub struct FindResult {
    pub name: String,
    pub node_type: String,
    pub file_path: Option<String>,
    pub line_start: Option<i64>,
    pub line_end: Option<i64>,
    pub snippet: Option<String>,
}

// ============================================================================
// HTTP Handlers
// ============================================================================

async fn health() -> &'static str {
    "OK"
}

async fn status(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    let start = std::time::Instant::now();

    let mubase = state.mubase.read().await;

    // Query stats directly
    let node_count: usize = mubase
        .query("SELECT COUNT(*) FROM nodes")
        .ok()
        .and_then(|r| r.rows.first()?.first()?.as_i64())
        .map(|n| n as usize)
        .unwrap_or(0);

    let edge_count: usize = mubase
        .query("SELECT COUNT(*) FROM edges")
        .ok()
        .and_then(|r| r.rows.first()?.first()?.as_i64())
        .map(|n| n as usize)
        .unwrap_or(0);

    let has_embeddings = mubase.has_embeddings().unwrap_or(false);

    let response = StatusResponse {
        node_count,
        edge_count,
        has_embeddings,
        project_root: state.project_root.display().to_string(),
        watching: state.config.watch,
    };

    Json(ApiResponse::ok(response, start.elapsed().as_millis() as u64))
}

async fn compress(
    State(state): State<Arc<AppState>>,
    Query(params): Query<CompressParams>,
) -> impl IntoResponse {
    let start = std::time::Instant::now();

    let mubase = state.mubase.read().await;

    // Build compressed output from database
    let stats = match mubase.stats() {
        Ok(s) => s,
        Err(e) => return Json(ApiResponse::<String>::err(format!("Failed to get stats: {}", e))),
    };

    let detail = params.detail.as_str();
    let show_complexity = detail == "high";

    // Query nodes grouped by file
    let sql = "SELECT type, name, file_path, complexity FROM nodes ORDER BY file_path, line_start";
    let result = match mubase.query(sql) {
        Ok(r) => r,
        Err(e) => return Json(ApiResponse::<String>::err(format!("Query failed: {}", e))),
    };

    let mut output = String::new();
    output.push_str(&format!("# MU Codebase Overview\n\n"));
    output.push_str(&format!("Files: {} | Symbols: {} | Edges: {}\n\n",
        stats.type_counts.get("module").unwrap_or(&0),
        stats.node_count,
        stats.edge_count
    ));

    let mut current_file = String::new();
    for row in &result.rows {
        let node_type = row.first().and_then(|v| v.as_str()).unwrap_or("?");
        let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
        let file_path = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
        let complexity = row.get(3).and_then(|v| v.as_i64());

        if file_path != current_file {
            if !current_file.is_empty() {
                output.push('\n');
            }
            output.push_str(&format!("## {}\n", file_path));
            current_file = file_path.to_string();
        }

        let sigil = match node_type {
            "module" => "!",
            "class" => "$",
            "function" => "#",
            _ => "@",
        };

        if show_complexity {
            if let Some(c) = complexity {
                output.push_str(&format!("  {}{} c={}\n", sigil, name, c));
            } else {
                output.push_str(&format!("  {}{}\n", sigil, name));
            }
        } else {
            output.push_str(&format!("  {}{}\n", sigil, name));
        }
    }

    Json(ApiResponse::ok(output, start.elapsed().as_millis() as u64))
}

async fn search(
    State(state): State<Arc<AppState>>,
    Query(params): Query<SearchParams>,
) -> impl IntoResponse {
    let start = std::time::Instant::now();

    let mubase = state.mubase.read().await;

    // Check if we have embeddings
    if !mubase.has_embeddings().unwrap_or(false) {
        return Json(ApiResponse::<Vec<SearchResult>>::err(
            "No embeddings available. Run `mu embed` first.".to_string(),
        ));
    }

    // Load embedding model lazily (use embedded model)
    let model = match mu_embeddings::MuSigmaModel::embedded() {
        Ok(m) => m,
        Err(e) => {
            return Json(ApiResponse::<Vec<SearchResult>>::err(format!(
                "Failed to load embedding model: {}",
                e
            )));
        }
    };

    // Embed the query (embed takes &[&str] and returns Vec<Vec<f32>>)
    let texts: Vec<&str> = vec![&params.q];
    let embeddings = match model.embed(&texts) {
        Ok(e) => e,
        Err(e) => {
            return Json(ApiResponse::<Vec<SearchResult>>::err(format!(
                "Failed to embed query: {}",
                e
            )));
        }
    };

    let query_embedding = match embeddings.first() {
        Some(e) => e,
        None => {
            return Json(ApiResponse::<Vec<SearchResult>>::err(
                "Empty embedding result".to_string(),
            ));
        }
    };

    // Search
    let results = match mubase.vector_search(query_embedding, params.limit, Some(params.threshold)) {
        Ok(r) => r,
        Err(e) => {
            return Json(ApiResponse::<Vec<SearchResult>>::err(format!(
                "Search failed: {}",
                e
            )));
        }
    };

    let search_results: Vec<SearchResult> = results
        .into_iter()
        .map(|r| SearchResult {
            node_id: r.node_id,
            name: r.name,
            node_type: r.node_type,
            file_path: r.file_path,
            similarity: r.similarity,
        })
        .collect();

    Json(ApiResponse::ok(search_results, start.elapsed().as_millis() as u64))
}

async fn find(
    State(state): State<Arc<AppState>>,
    Query(params): Query<FindParams>,
) -> impl IntoResponse {
    let start = std::time::Instant::now();

    let mubase = state.mubase.read().await;

    let sql = format!(
        "SELECT type, name, file_path, line_start, line_end FROM nodes \
         WHERE name = '{}' OR name LIKE '%.{}' LIMIT 20",
        params.symbol.replace('\'', "''"),
        params.symbol.replace('\'', "''")
    );

    let result = match mubase.query(&sql) {
        Ok(r) => r,
        Err(e) => {
            return Json(ApiResponse::<Vec<FindResult>>::err(format!(
                "Query failed: {}",
                e
            )));
        }
    };

    let mut results = Vec::new();
    for row in &result.rows {
        let node_type = row.first().and_then(|v| v.as_str()).unwrap_or("?").to_string();
        let name = row.get(1).and_then(|v| v.as_str()).unwrap_or("?").to_string();
        let file_path = row.get(2).and_then(|v| v.as_str()).map(String::from);
        let line_start = row.get(3).and_then(|v| v.as_i64());
        let line_end = row.get(4).and_then(|v| v.as_i64());

        // Try to read snippet
        let snippet = if let (Some(ref path), Some(start), Some(end)) = (&file_path, line_start, line_end) {
            let full_path = state.project_root.join(path);
            std::fs::read_to_string(&full_path)
                .ok()
                .and_then(|content| {
                    let lines: Vec<&str> = content.lines().collect();
                    let start_idx = (start as usize).saturating_sub(1);
                    let end_idx = (end as usize).min(lines.len());
                    if start_idx < lines.len() {
                        Some(lines[start_idx..end_idx].join("\n"))
                    } else {
                        None
                    }
                })
        } else {
            None
        };

        results.push(FindResult {
            name,
            node_type,
            file_path,
            line_start,
            line_end,
            snippet,
        });
    }

    Json(ApiResponse::ok(results, start.elapsed().as_millis() as u64))
}

async fn impact(
    State(state): State<Arc<AppState>>,
    Query(params): Query<ImpactParams>,
) -> impl IntoResponse {
    let start = std::time::Instant::now();

    let mubase = state.mubase.read().await;

    // Find the node
    let sql = format!(
        "SELECT id, name, type, file_path FROM nodes WHERE name = '{}' OR name LIKE '%.{}' LIMIT 1",
        params.symbol.replace('\'', "''"),
        params.symbol.replace('\'', "''")
    );

    let node_result = match mubase.query(&sql) {
        Ok(r) => r,
        Err(e) => return Json(ApiResponse::<serde_json::Value>::err(format!("Query failed: {}", e))),
    };

    if node_result.rows.is_empty() {
        return Json(ApiResponse::<serde_json::Value>::err(format!("Symbol '{}' not found", params.symbol)));
    }

    let node_id = node_result.rows[0].first().and_then(|v| v.as_str()).unwrap_or("");
    let node_name = node_result.rows[0].get(1).and_then(|v| v.as_str()).unwrap_or("");

    // Find all nodes that depend on this one (reverse edges)
    let impact_sql = format!(
        "SELECT DISTINCT n.id, n.name, n.type, n.file_path, e.type as edge_type \
         FROM edges e \
         JOIN nodes n ON e.source_id = n.id \
         WHERE e.target_id = '{}' \
         LIMIT 50",
        node_id.replace('\'', "''")
    );

    let impact_result = match mubase.query(&impact_sql) {
        Ok(r) => r,
        Err(e) => return Json(ApiResponse::<serde_json::Value>::err(format!("Impact query failed: {}", e))),
    };

    let mut impacted: Vec<serde_json::Value> = Vec::new();
    for row in &impact_result.rows {
        impacted.push(serde_json::json!({
            "id": row.first().and_then(|v| v.as_str()).unwrap_or(""),
            "name": row.get(1).and_then(|v| v.as_str()).unwrap_or(""),
            "type": row.get(2).and_then(|v| v.as_str()).unwrap_or(""),
            "file_path": row.get(3).and_then(|v| v.as_str()),
            "edge_type": row.get(4).and_then(|v| v.as_str()).unwrap_or(""),
        }));
    }

    let response = serde_json::json!({
        "symbol": node_name,
        "node_id": node_id,
        "impacted_count": impacted.len(),
        "impacted": impacted,
    });

    Json(ApiResponse::ok(response, start.elapsed().as_millis() as u64))
}

// ============================================================================
// File Watcher & Incremental Updates
// ============================================================================

/// File extensions we care about
fn is_source_file(path: &Path) -> bool {
    let extensions = ["py", "ts", "tsx", "js", "jsx", "go", "rs", "java", "cs"];
    path.extension()
        .and_then(|e| e.to_str())
        .is_some_and(|ext| extensions.contains(&ext))
}

/// Check if path should be ignored
fn should_ignore(path: &Path) -> bool {
    let path_str = path.to_string_lossy();

    // Ignore common directories
    let ignore_patterns = [
        "node_modules",
        ".git",
        ".mu",
        "__pycache__",
        ".venv",
        "venv",
        "target",
        "build",
        "dist",
        ".next",
    ];

    ignore_patterns.iter().any(|pattern| path_str.contains(pattern))
}

/// Handle file change - incrementally update the graph
async fn handle_file_change(
    path: &Path,
    mubase: &Arc<RwLock<mu_daemon::storage::MUbase>>,
    project_root: &Path,
) -> Result<()> {
    let relative_path = path
        .strip_prefix(project_root)
        .unwrap_or(path)
        .to_string_lossy()
        .to_string();

    info!("File changed: {}", relative_path);

    // Read new content
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(e) => {
            // File might have been deleted
            warn!("Could not read {}: {}", relative_path, e);

            // Delete nodes for this file
            let mubase = mubase.write().await;
            if let Err(e) = mubase.delete_nodes_for_file(&relative_path) {
                error!("Failed to delete nodes for {}: {}", relative_path, e);
            }
            return Ok(());
        }
    };

    // Detect language
    let lang = path
        .extension()
        .and_then(|e| e.to_str())
        .map(|ext| match ext {
            "py" => "python",
            "ts" | "tsx" => "typescript",
            "js" | "jsx" => "javascript",
            "go" => "go",
            "rs" => "rust",
            "java" => "java",
            "cs" => "csharp",
            _ => "unknown",
        })
        .unwrap_or("unknown");

    if lang == "unknown" {
        return Ok(());
    }

    // Parse the file
    let parse_result = mu_core::parser::parse_source(&content, &relative_path, lang);
    let module = match parse_result.module {
        Some(m) => m,
        None => {
            warn!("Failed to parse {}: {:?}", relative_path, parse_result.error);
            return Ok(());
        }
    };

    // Convert to nodes and edges
    let nodes = module_to_nodes(&module, &relative_path);
    let edges = module_to_edges(&module, &relative_path);

    // Update database
    let mubase = mubase.write().await;

    // Delete old nodes for this file
    mubase.delete_nodes_for_file(&relative_path)?;

    // Insert new nodes and edges
    for node in &nodes {
        mubase.insert_node(node)?;
    }
    for edge in &edges {
        mubase.insert_edge(edge)?;
    }

    info!(
        "Updated {}: {} nodes, {} edges",
        relative_path,
        nodes.len(),
        edges.len()
    );

    Ok(())
}

/// Convert a parsed module to nodes
fn module_to_nodes(module: &mu_core::types::ModuleDef, file_path: &str) -> Vec<mu_daemon::storage::Node> {
    use mu_daemon::storage::Node;
    use mu_daemon::storage::NodeType;

    let mut nodes = Vec::new();

    // Module node
    nodes.push(Node {
        id: format!("mod:{}", file_path),
        node_type: NodeType::Module,
        name: module.name.clone(),
        qualified_name: Some(module.name.clone()),
        file_path: Some(file_path.to_string()),
        line_start: Some(1),
        line_end: None,
        properties: None,
        complexity: 0,
    });

    // Function nodes
    for func in &module.functions {
        nodes.push(Node {
            id: format!("fn:{}:{}", file_path, func.name),
            node_type: NodeType::Function,
            name: func.name.clone(),
            qualified_name: Some(format!("{}::{}", module.name, func.name)),
            file_path: Some(file_path.to_string()),
            line_start: Some(func.start_line),
            line_end: Some(func.end_line),
            properties: None,
            complexity: func.body_complexity,
        });
    }

    // Class nodes
    for class in &module.classes {
        nodes.push(Node {
            id: format!("cls:{}:{}", file_path, class.name),
            node_type: NodeType::Class,
            name: class.name.clone(),
            qualified_name: Some(format!("{}::{}", module.name, class.name)),
            file_path: Some(file_path.to_string()),
            line_start: Some(class.start_line),
            line_end: Some(class.end_line),
            properties: None,
            complexity: 0,
        });

        // Methods
        for method in &class.methods {
            nodes.push(Node {
                id: format!("fn:{}:{}::{}", file_path, class.name, method.name),
                node_type: NodeType::Function,
                name: method.name.clone(),
                qualified_name: Some(format!("{}::{}::{}", module.name, class.name, method.name)),
                file_path: Some(file_path.to_string()),
                line_start: Some(method.start_line),
                line_end: Some(method.end_line),
                properties: None,
                complexity: method.body_complexity,
            });
        }
    }

    nodes
}

/// Convert a parsed module to edges
fn module_to_edges(module: &mu_core::types::ModuleDef, file_path: &str) -> Vec<mu_daemon::storage::Edge> {
    use mu_daemon::storage::Edge;
    use mu_daemon::storage::EdgeType;

    let mut edges = Vec::new();
    let module_id = format!("mod:{}", file_path);

    // Contains edges (module -> functions, classes)
    for func in &module.functions {
        edges.push(Edge {
            id: format!("contains:{}->fn:{}:{}", module_id, file_path, func.name),
            source_id: module_id.clone(),
            target_id: format!("fn:{}:{}", file_path, func.name),
            edge_type: EdgeType::Contains,
            properties: None,
        });
    }

    for class in &module.classes {
        let class_id = format!("cls:{}:{}", file_path, class.name);
        edges.push(Edge {
            id: format!("contains:{}->cls:{}:{}", module_id, file_path, class.name),
            source_id: module_id.clone(),
            target_id: class_id.clone(),
            edge_type: EdgeType::Contains,
            properties: None,
        });

        // Class contains methods
        for method in &class.methods {
            edges.push(Edge {
                id: format!("contains:{}->fn:{}:{}::{}", class_id, file_path, class.name, method.name),
                source_id: class_id.clone(),
                target_id: format!("fn:{}:{}::{}", file_path, class.name, method.name),
                edge_type: EdgeType::Contains,
                properties: None,
            });
        }
    }

    // Import edges
    for import in &module.imports {
        edges.push(Edge {
            id: format!("imports:{}->mod:{}", module_id, import.module),
            source_id: module_id.clone(),
            target_id: format!("mod:{}", import.module),
            edge_type: EdgeType::Imports,
            properties: None,
        });
    }

    edges
}

/// Start the file watcher
async fn start_watcher(
    project_root: PathBuf,
    mubase: Arc<RwLock<mu_daemon::storage::MUbase>>,
) -> Result<()> {
    let (tx, mut rx) = tokio::sync::mpsc::channel::<PathBuf>(100);

    // Spawn the notify watcher in a blocking thread
    let watch_root = project_root.clone();
    std::thread::spawn(move || {
        let tx_clone = tx.clone();
        let mut debouncer = new_debouncer(
            Duration::from_millis(500),
            move |res: DebounceEventResult| {
                match res {
                    Ok(events) => {
                        let mut seen = HashSet::new();
                        for event in events {
                            let path = event.path;
                            if is_source_file(&path) && !should_ignore(&path) && seen.insert(path.clone()) {
                                let _ = tx_clone.blocking_send(path);
                            }
                        }
                    }
                    Err(e) => error!("Watch error: {:?}", e),
                }
            },
        )
        .expect("Failed to create debouncer");

        debouncer
            .watcher()
            .watch(&watch_root, RecursiveMode::Recursive)
            .expect("Failed to watch directory");

        // Keep the watcher alive
        loop {
            std::thread::sleep(Duration::from_secs(60));
        }
    });

    // Handle file change events
    let mubase_clone = mubase.clone();
    tokio::spawn(async move {
        while let Some(path) = rx.recv().await {
            if let Err(e) = handle_file_change(&path, &mubase_clone, &project_root).await {
                error!("Failed to handle file change: {}", e);
            }
        }
    });

    Ok(())
}

// ============================================================================
// Main entry point
// ============================================================================

pub async fn run(path: &str, port: u16, watch: bool, _format: OutputFormat) -> Result<()> {
    use colored::Colorize;

    let project_root = std::fs::canonicalize(path).context("Invalid path")?;

    // Find mubase
    let mubase_path = project_root.join(".mu").join("mubase");
    if !mubase_path.exists() {
        anyhow::bail!(
            "No MU database found. Run `mu bootstrap` first.\n\
             Path checked: {}",
            mubase_path.display()
        );
    }

    // Open database - use read-write for incremental updates, read-only if --no-watch
    let mubase = if watch {
        mu_daemon::storage::MUbase::open(&mubase_path)
            .context("Failed to open database. Another process (like MCP server) may be holding a write lock.\n\
                      Try stopping other MU processes first, or use --no-watch for read-only mode.")?
    } else {
        mu_daemon::storage::MUbase::open_read_only(&mubase_path)
            .context("Failed to open database in read-only mode")?
    };

    let stats = mubase.stats()?;
    let has_embeddings = mubase.has_embeddings().unwrap_or(false);

    let config = ServeConfig {
        port,
        watch,
        embed: has_embeddings,
    };

    let mubase = Arc::new(RwLock::new(mubase));

    // Start file watcher if enabled
    if watch {
        info!("Starting file watcher...");
        start_watcher(project_root.clone(), mubase.clone()).await?;
    }

    let state = Arc::new(AppState {
        mubase,
        project_root: project_root.clone(),
        config,
    });

    // Build router
    let app = Router::new()
        .route("/health", get(health))
        .route("/status", get(status))
        .route("/compress", get(compress))
        .route("/search", get(search))
        .route("/find", get(find))
        .route("/impact", get(impact))
        .layer(CorsLayer::new().allow_origin(Any).allow_methods(Any))
        .with_state(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));

    // Print startup banner
    println!();
    println!("  {} MU Server v{}", "▲".cyan(), env!("CARGO_PKG_VERSION"));
    println!();
    println!("  {} {}", "→".green(), format!("http://localhost:{}", port).cyan());
    println!();
    println!("  {} {} nodes, {} edges", "◆".yellow(), stats.node_count, stats.edge_count);
    if has_embeddings {
        println!("  {} Embeddings enabled", "◆".yellow());
    }
    if watch {
        println!("  {} File watching enabled", "◆".yellow());
    }
    println!();
    println!("  {}", "Endpoints:".dimmed());
    println!("    GET /health              Health check");
    println!("    GET /status              Server status");
    println!("    GET /compress?detail=    Compress codebase");
    println!("    GET /search?q=&limit=    Semantic search");
    println!("    GET /find?symbol=        Find symbol");
    println!("    GET /impact?symbol=      Impact analysis");
    println!();
    println!("  Press {} to stop", "Ctrl+C".yellow());
    println!();

    // Start server
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
