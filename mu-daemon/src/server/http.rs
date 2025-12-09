//! HTTP routes and handlers for the MU daemon API.

use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use std::time::Instant;
use tower_http::cors::{Any, CorsLayer};
use tower_http::trace::TraceLayer;

use super::state::AppState;
use super::websocket::websocket_handler;
use crate::build::BuildPipeline;
use crate::context::ContextExtractor;
use crate::muql;

/// Create the main router with all routes.
pub fn create_router(state: AppState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    Router::new()
        // Health and status
        .route("/health", get(health))
        .route("/status", get(status))
        // Query endpoints
        .route("/query", post(query))
        .route("/context", post(context))
        .route("/context/omega", post(context_omega))
        // Node operations
        .route("/node/:id", get(get_node))
        .route("/nodes/:id", get(get_node)) // Alias for Python daemon compatibility
        .route("/nodes", post(get_nodes_batch))
        // Neighbors (Python daemon compatibility)
        .route("/node/:id/neighbors", get(get_neighbors))
        .route("/nodes/:id/neighbors", get(get_neighbors)) // Alias
        // Graph traversal
        .route("/deps", post(deps))
        .route("/impact", post(impact))
        .route("/ancestors", post(ancestors))
        .route("/cycles", post(cycles))
        // Build operations
        .route("/build", post(build))
        .route("/scan", post(scan))
        // Export
        .route("/export", get(export_graph))
        // Intelligence endpoints
        .route("/patterns", post(patterns))
        .route("/warn", post(warn))
        // WebSocket for live updates
        .route("/ws", get(websocket_handler))
        .route("/live", get(websocket_handler)) // Alias for Python daemon compatibility
        .layer(cors)
        .layer(TraceLayer::new_for_http())
        .with_state(Arc::new(state))
}

// =============================================================================
// Response Types
// =============================================================================

#[derive(Serialize)]
struct ApiResponse<T> {
    success: bool,
    data: Option<T>,
    error: Option<String>,
    duration_ms: u64,
}

impl<T: Serialize> ApiResponse<T> {
    fn ok(data: T, duration_ms: u64) -> Json<Self> {
        Json(Self {
            success: true,
            data: Some(data),
            error: None,
            duration_ms,
        })
    }

    fn err(error: impl ToString, duration_ms: u64) -> Json<Self> {
        Json(Self {
            success: false,
            data: None,
            error: Some(error.to_string()),
            duration_ms,
        })
    }
}

// =============================================================================
// Health & Status
// =============================================================================

async fn health() -> impl IntoResponse {
    Json(serde_json::json!({
        "status": "ok",
        "service": "mu-daemon"
    }))
}

#[derive(Deserialize)]
struct StatusParams {
    /// Client working directory for project-specific stats
    cwd: Option<String>,
}

#[derive(Serialize)]
struct StatusResponse {
    status: String,
    node_count: usize,
    edge_count: usize,
    root: String,
    mubase_path: String,
    schema_version: String,
    connections: usize,
    uptime_seconds: f64,
    active_projects: usize,
    project_paths: Vec<String>,
    language_stats: std::collections::HashMap<String, usize>,
}

async fn status(
    State(state): State<Arc<AppState>>,
    axum::extract::Query(params): axum::extract::Query<StatusParams>,
) -> impl IntoResponse {
    let start = Instant::now();

    // Get project-specific data if cwd provided
    let (graph, mubase_path) = match state.projects.get_project(params.cwd.as_deref()).await {
        Ok((_, graph, path)) => (graph, path),
        Err(_) => (state.graph.clone(), state.projects.default_path().to_path_buf()),
    };

    let graph = graph.read().await;

    // Get language stats from mubase (count modules by file extension)
    let language_stats = get_language_stats(&state, params.cwd.as_deref()).await;

    let data = StatusResponse {
        status: "running".to_string(),
        node_count: graph.node_count(),
        edge_count: graph.edge_count(),
        root: state.root.display().to_string(),
        mubase_path: mubase_path.display().to_string(),
        schema_version: "1.0.0".to_string(),
        connections: state.ws_connection_count(),
        uptime_seconds: state.uptime_seconds(),
        active_projects: state.projects.project_count().await,
        project_paths: state.projects.list_projects().await,
        language_stats,
    };

    ApiResponse::ok(data, start.elapsed().as_millis() as u64)
}

/// Get language statistics from mubase.
async fn get_language_stats(
    state: &AppState,
    cwd: Option<&str>,
) -> std::collections::HashMap<String, usize> {
    let mubase = match state.projects.get_mubase(cwd).await {
        Ok(m) => m,
        Err(_) => return std::collections::HashMap::new(),
    };

    let mubase = mubase.read().await;

    // Query language stats by file extension
    match mubase.query(
        "SELECT
            CASE
                WHEN file_path LIKE '%.py' THEN 'python'
                WHEN file_path LIKE '%.ts' OR file_path LIKE '%.tsx' THEN 'typescript'
                WHEN file_path LIKE '%.js' OR file_path LIKE '%.jsx' THEN 'javascript'
                WHEN file_path LIKE '%.go' THEN 'go'
                WHEN file_path LIKE '%.rs' THEN 'rust'
                WHEN file_path LIKE '%.java' THEN 'java'
                WHEN file_path LIKE '%.cs' THEN 'csharp'
                ELSE 'other'
            END as language,
            COUNT(*) as count
         FROM nodes
         WHERE type = 'module'
         GROUP BY language",
    ) {
        Ok(result) => {
            let mut stats = std::collections::HashMap::new();
            for row in result.rows {
                if let (Some(lang), Some(count)) = (
                    row.get(0).and_then(|v| v.as_str()),
                    row.get(1).and_then(|v| v.as_i64()),
                ) {
                    if lang != "other" || count > 0 {
                        stats.insert(lang.to_string(), count as usize);
                    }
                }
            }
            stats
        }
        Err(_) => std::collections::HashMap::new(),
    }
}

// =============================================================================
// Query Endpoints
// =============================================================================

#[derive(Deserialize)]
struct QueryRequest {
    muql: String,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

#[derive(Serialize)]
struct QueryResponse {
    columns: Vec<String>,
    rows: Vec<Vec<serde_json::Value>>,
    count: usize,
}

async fn query(
    State(state): State<Arc<AppState>>,
    Json(req): Json<QueryRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    // Parse and execute MUQL query
    let result = muql::execute(&req.muql, state.as_ref()).await;

    match result {
        Ok(qr) => {
            let data = QueryResponse {
                columns: qr.columns,
                rows: qr.rows.clone(),
                count: qr.rows.len(),
            };
            ApiResponse::ok(data, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<QueryResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

#[derive(Deserialize)]
struct ContextRequest {
    question: String,
    #[serde(default = "default_max_tokens")]
    max_tokens: usize,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

fn default_max_tokens() -> usize {
    8000
}

#[derive(Serialize)]
struct ContextResponse {
    /// MU format output (matches Python's mu_text field)
    mu_text: String,
    /// List of relevant node IDs
    nodes: Vec<String>,
    /// Estimated token count (matches Python's token_count field)
    token_count: usize,
}

async fn context(
    State(state): State<Arc<AppState>>,
    Json(req): Json<ContextRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let extractor = ContextExtractor::new(state.as_ref());
    let result = extractor.extract(&req.question, req.max_tokens).await;

    match result {
        Ok(ctx) => {
            let data = ContextResponse {
                mu_text: ctx.mu_output,
                nodes: ctx.nodes,
                token_count: ctx.tokens,
            };
            ApiResponse::ok(data, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<ContextResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

// =============================================================================
// Node Operations
// =============================================================================

#[derive(Serialize)]
struct NodeResponse {
    id: String,
    name: String,
    node_type: String,
    file_path: Option<String>,
    line_start: Option<u32>,
    line_end: Option<u32>,
    complexity: u32,
}

async fn get_node(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    let start = Instant::now();

    let mubase = state.mubase.read().await;
    match mubase.get_node(&id) {
        Ok(Some(node)) => {
            let data = NodeResponse {
                id: node.id,
                name: node.name,
                node_type: node.node_type.as_str().to_string(),
                file_path: node.file_path,
                line_start: node.line_start,
                line_end: node.line_end,
                complexity: node.complexity,
            };
            ApiResponse::ok(data, start.elapsed().as_millis() as u64)
        }
        Ok(None) => ApiResponse::<NodeResponse>::err(
            format!("Node not found: {}", id),
            start.elapsed().as_millis() as u64,
        ),
        Err(e) => ApiResponse::<NodeResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

#[derive(Deserialize)]
struct BatchNodesRequest {
    ids: Vec<String>,
}

async fn get_nodes_batch(
    State(state): State<Arc<AppState>>,
    Json(req): Json<BatchNodesRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let mubase = state.mubase.read().await;
    let mut nodes = Vec::new();

    for id in &req.ids {
        if let Ok(Some(node)) = mubase.get_node(id) {
            nodes.push(NodeResponse {
                id: node.id,
                name: node.name,
                node_type: node.node_type.as_str().to_string(),
                file_path: node.file_path,
                line_start: node.line_start,
                line_end: node.line_end,
                complexity: node.complexity,
            });
        }
    }

    ApiResponse::ok(nodes, start.elapsed().as_millis() as u64)
}

// =============================================================================
// Neighbors Endpoint
// =============================================================================

#[derive(Deserialize)]
struct NeighborsParams {
    /// Direction: "outgoing", "incoming", or "both"
    #[serde(default = "default_direction")]
    direction: String,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

#[derive(Serialize)]
struct NeighborsResponse {
    node_id: String,
    direction: String,
    neighbors: Vec<NodeResponse>,
}

async fn get_neighbors(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    axum::extract::Query(params): axum::extract::Query<NeighborsParams>,
) -> impl IntoResponse {
    let start = Instant::now();

    // Validate direction
    if !["outgoing", "incoming", "both"].contains(&params.direction.as_str()) {
        return ApiResponse::<NeighborsResponse>::err(
            "Invalid direction. Must be 'outgoing', 'incoming', or 'both'",
            start.elapsed().as_millis() as u64,
        );
    }

    // Get project-specific mubase
    let mubase = match state.projects.get_mubase(params.cwd.as_deref()).await {
        Ok(m) => m,
        Err(e) => {
            return ApiResponse::<NeighborsResponse>::err(e, start.elapsed().as_millis() as u64)
        }
    };

    let mubase = mubase.read().await;

    // Check if node exists
    match mubase.get_node(&id) {
        Ok(None) => {
            return ApiResponse::<NeighborsResponse>::err(
                format!("Node not found: {}", id),
                start.elapsed().as_millis() as u64,
            )
        }
        Err(e) => {
            return ApiResponse::<NeighborsResponse>::err(e, start.elapsed().as_millis() as u64)
        }
        Ok(Some(_)) => {}
    }

    // Query neighbors based on direction
    let sql = match params.direction.as_str() {
        "outgoing" => format!(
            "SELECT n.id, n.type, n.name, n.qualified_name, n.file_path, n.line_start, n.line_end, n.complexity
             FROM edges e
             JOIN nodes n ON e.target_id = n.id
             WHERE e.source_id = '{}'",
            id.replace('\'', "''")
        ),
        "incoming" => format!(
            "SELECT n.id, n.type, n.name, n.qualified_name, n.file_path, n.line_start, n.line_end, n.complexity
             FROM edges e
             JOIN nodes n ON e.source_id = n.id
             WHERE e.target_id = '{}'",
            id.replace('\'', "''")
        ),
        _ => format!(
            "SELECT DISTINCT n.id, n.type, n.name, n.qualified_name, n.file_path, n.line_start, n.line_end, n.complexity
             FROM edges e
             JOIN nodes n ON (e.target_id = n.id OR e.source_id = n.id)
             WHERE (e.source_id = '{}' OR e.target_id = '{}') AND n.id != '{}'",
            id.replace('\'', "''"),
            id.replace('\'', "''"),
            id.replace('\'', "''")
        ),
    };

    match mubase.query(&sql) {
        Ok(result) => {
            let neighbors: Vec<NodeResponse> = result
                .rows
                .iter()
                .map(|row| NodeResponse {
                    id: row.get(0).and_then(|v| v.as_str()).unwrap_or("").to_string(),
                    node_type: row.get(1).and_then(|v| v.as_str()).unwrap_or("").to_string(),
                    name: row.get(2).and_then(|v| v.as_str()).unwrap_or("").to_string(),
                    file_path: row.get(4).and_then(|v| v.as_str()).map(String::from),
                    line_start: row.get(5).and_then(|v| v.as_i64()).map(|v| v as u32),
                    line_end: row.get(6).and_then(|v| v.as_i64()).map(|v| v as u32),
                    complexity: row.get(7).and_then(|v| v.as_i64()).unwrap_or(0) as u32,
                })
                .collect();

            let data = NeighborsResponse {
                node_id: id,
                direction: params.direction,
                neighbors,
            };
            ApiResponse::ok(data, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<NeighborsResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

// =============================================================================
// Graph Traversal
// =============================================================================

#[derive(Deserialize)]
struct DepsRequest {
    node: String,
    #[serde(default = "default_direction")]
    direction: String,
    #[serde(default = "default_depth")]
    depth: usize,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

fn default_direction() -> String {
    "outgoing".to_string()
}

fn default_depth() -> usize {
    2
}

async fn deps(
    State(state): State<Arc<AppState>>,
    Json(req): Json<DepsRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    // Execute dependencies query via MUQL
    let muql_query = format!(
        "SHOW dependencies OF '{}' DEPTH {}",
        req.node.replace('\'', "''"),
        req.depth
    );

    let result = muql::execute(&muql_query, state.as_ref()).await;

    match result {
        Ok(qr) => {
            let nodes: Vec<String> = qr
                .rows
                .iter()
                .filter_map(|row| row.first().and_then(|v| v.as_str().map(String::from)))
                .collect();
            ApiResponse::ok(nodes, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<Vec<String>>::err(e, start.elapsed().as_millis() as u64),
    }
}

#[derive(Deserialize)]
struct ImpactRequest {
    node: String,
    #[serde(default)]
    edge_types: Option<Vec<String>>,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

async fn impact(
    State(state): State<Arc<AppState>>,
    Json(req): Json<ImpactRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let muql_query = format!("SHOW impact OF '{}'", req.node.replace('\'', "''"));
    let result = muql::execute(&muql_query, state.as_ref()).await;

    match result {
        Ok(qr) => {
            let nodes: Vec<String> = qr
                .rows
                .iter()
                .filter_map(|row| row.first().and_then(|v| v.as_str().map(String::from)))
                .collect();
            ApiResponse::ok(nodes, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<Vec<String>>::err(e, start.elapsed().as_millis() as u64),
    }
}

#[derive(Deserialize)]
struct AncestorsRequest {
    node: String,
    #[serde(default = "default_depth")]
    depth: usize,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

async fn ancestors(
    State(state): State<Arc<AppState>>,
    Json(req): Json<AncestorsRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let muql_query = format!(
        "SHOW ancestors OF '{}' DEPTH {}",
        req.node.replace('\'', "''"),
        req.depth
    );
    let result = muql::execute(&muql_query, state.as_ref()).await;

    match result {
        Ok(qr) => {
            let nodes: Vec<String> = qr
                .rows
                .iter()
                .filter_map(|row| row.first().and_then(|v| v.as_str().map(String::from)))
                .collect();
            ApiResponse::ok(nodes, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<Vec<String>>::err(e, start.elapsed().as_millis() as u64),
    }
}

#[derive(Deserialize)]
struct CyclesRequest {
    #[serde(default)]
    edge_types: Option<Vec<String>>,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

async fn cycles(
    State(state): State<Arc<AppState>>,
    Json(_req): Json<CyclesRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let result = muql::execute("FIND CYCLES", state.as_ref()).await;

    match result {
        Ok(qr) => {
            // Each row is a cycle (list of node IDs)
            let cycles: Vec<Vec<String>> = qr
                .rows
                .iter()
                .map(|row| {
                    row.iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect()
                })
                .collect();
            ApiResponse::ok(cycles, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<Vec<Vec<String>>>::err(e, start.elapsed().as_millis() as u64),
    }
}

// =============================================================================
// Build Operations
// =============================================================================

#[derive(Deserialize)]
struct BuildRequest {
    #[serde(default)]
    path: Option<String>,
    #[serde(default)]
    force: bool,
}

#[derive(Serialize)]
struct BuildResponse {
    node_count: usize,
    edge_count: usize,
    duration_ms: u64,
}

async fn build(
    State(state): State<Arc<AppState>>,
    Json(req): Json<BuildRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let root = req
        .path
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| state.root.clone());

    let pipeline = BuildPipeline::new((*state).clone());
    match pipeline.build(&root).await {
        Ok(result) => {
            let data = BuildResponse {
                node_count: result.node_count,
                edge_count: result.edge_count,
                duration_ms: result.duration.as_millis() as u64,
            };
            ApiResponse::ok(data, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<BuildResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

#[derive(Deserialize)]
struct ScanRequest {
    #[serde(default)]
    path: Option<String>,
}

#[derive(Serialize)]
struct ScanResponse {
    file_count: usize,
    extensions: Vec<String>,
}

async fn scan(
    State(state): State<Arc<AppState>>,
    Json(req): Json<ScanRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let root = req
        .path
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| state.root.clone());

    // Use mu-core scanner (sync version without Python GIL)
    match mu_core::scanner::scan_directory_sync(root.to_str().unwrap_or("."), None, None, false, false, false) {
        Ok(result) => {
            // Collect unique extensions from files
            let extensions: Vec<String> = result
                .files
                .iter()
                .filter_map(|f| {
                    std::path::Path::new(&f.path)
                        .extension()
                        .and_then(|e| e.to_str())
                        .map(|s| s.to_string())
                })
                .collect::<std::collections::HashSet<_>>()
                .into_iter()
                .collect();
            let data = ScanResponse {
                file_count: result.files.len(),
                extensions,
            };
            ApiResponse::ok(data, start.elapsed().as_millis() as u64)
        }
        Err(e) => ApiResponse::<ScanResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

// =============================================================================
// Export Operations
// =============================================================================

#[derive(Deserialize)]
struct ExportParams {
    /// Export format: json, mu, mermaid, d2, cytoscape
    #[serde(default = "default_export_format")]
    format: String,
    /// Comma-separated node IDs to export (optional)
    nodes: Option<String>,
    /// Comma-separated node types to export (optional)
    types: Option<String>,
    /// Maximum nodes to export (optional)
    max_nodes: Option<usize>,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

fn default_export_format() -> String {
    "json".to_string()
}

async fn export_graph(
    State(state): State<Arc<AppState>>,
    axum::extract::Query(params): axum::extract::Query<ExportParams>,
) -> impl IntoResponse {
    let start = Instant::now();

    // Get project-specific mubase
    let mubase = match state.projects.get_mubase(params.cwd.as_deref()).await {
        Ok(m) => m,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                [(axum::http::header::CONTENT_TYPE, "text/plain")],
                format!("Error: {}", e),
            )
                .into_response();
        }
    };

    let mubase = mubase.read().await;

    // Parse node type filters
    let type_filter: Option<Vec<String>> = params.types.map(|t| {
        t.split(',')
            .map(|s| s.trim().to_lowercase())
            .collect()
    });

    // Parse node ID filters
    let node_filter: Option<Vec<String>> = params.nodes.map(|n| {
        n.split(',')
            .map(|s| s.trim().to_string())
            .collect()
    });

    // Build WHERE clause
    let mut where_clauses = Vec::new();
    if let Some(ref types) = type_filter {
        let type_list = types
            .iter()
            .map(|t| format!("'{}'", t.replace('\'', "''")))
            .collect::<Vec<_>>()
            .join(", ");
        where_clauses.push(format!("type IN ({})", type_list));
    }
    if let Some(ref nodes) = node_filter {
        let node_list = nodes
            .iter()
            .map(|n| format!("'{}'", n.replace('\'', "''")))
            .collect::<Vec<_>>()
            .join(", ");
        where_clauses.push(format!("id IN ({})", node_list));
    }

    let where_sql = if where_clauses.is_empty() {
        String::new()
    } else {
        format!(" WHERE {}", where_clauses.join(" AND "))
    };

    let limit_sql = params
        .max_nodes
        .map(|n| format!(" LIMIT {}", n))
        .unwrap_or_default();

    // Query nodes
    let nodes_sql = format!(
        "SELECT id, type, name, qualified_name, file_path, line_start, line_end, complexity FROM nodes{}{}",
        where_sql, limit_sql
    );

    let nodes_result = match mubase.query(&nodes_sql) {
        Ok(r) => r,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                [(axum::http::header::CONTENT_TYPE, "text/plain")],
                format!("Error querying nodes: {}", e),
            )
                .into_response();
        }
    };

    // Query edges
    let edges_sql = if node_filter.is_some() || type_filter.is_some() {
        // Only get edges between exported nodes
        format!(
            "SELECT source_id, target_id, type FROM edges
             WHERE source_id IN (SELECT id FROM nodes{}{})
             AND target_id IN (SELECT id FROM nodes{}{})",
            where_sql, limit_sql, where_sql, limit_sql
        )
    } else {
        "SELECT source_id, target_id, type FROM edges".to_string()
    };

    let edges_result = match mubase.query(&edges_sql) {
        Ok(r) => r,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                [(axum::http::header::CONTENT_TYPE, "text/plain")],
                format!("Error querying edges: {}", e),
            )
                .into_response();
        }
    };

    // Generate output based on format
    let (content, content_type) = match params.format.to_lowercase().as_str() {
        "json" => {
            let output = serde_json::json!({
                "version": "1.0",
                "generated_at": chrono::Utc::now().to_rfc3339(),
                "stats": {
                    "node_count": nodes_result.rows.len(),
                    "edge_count": edges_result.rows.len(),
                },
                "nodes": nodes_result.rows.iter().map(|row| {
                    serde_json::json!({
                        "id": row.get(0).and_then(|v| v.as_str()).unwrap_or(""),
                        "type": row.get(1).and_then(|v| v.as_str()).unwrap_or(""),
                        "name": row.get(2).and_then(|v| v.as_str()).unwrap_or(""),
                        "qualified_name": row.get(3).and_then(|v| v.as_str()),
                        "file_path": row.get(4).and_then(|v| v.as_str()),
                        "line_start": row.get(5).and_then(|v| v.as_i64()),
                        "line_end": row.get(6).and_then(|v| v.as_i64()),
                        "complexity": row.get(7).and_then(|v| v.as_i64()).unwrap_or(0),
                    })
                }).collect::<Vec<_>>(),
                "edges": edges_result.rows.iter().map(|row| {
                    serde_json::json!({
                        "source": row.get(0).and_then(|v| v.as_str()).unwrap_or(""),
                        "target": row.get(1).and_then(|v| v.as_str()).unwrap_or(""),
                        "type": row.get(2).and_then(|v| v.as_str()).unwrap_or(""),
                    })
                }).collect::<Vec<_>>(),
            });
            (serde_json::to_string_pretty(&output).unwrap_or_default(), "application/json")
        }
        "mu" => {
            let output = export_mu_format(&nodes_result, &edges_result);
            (output, "text/plain")
        }
        "mermaid" => {
            let output = export_mermaid_format(&nodes_result, &edges_result);
            (output, "text/plain")
        }
        "d2" => {
            let output = export_d2_format(&nodes_result, &edges_result);
            (output, "text/plain")
        }
        "cytoscape" => {
            let output = export_cytoscape_format(&nodes_result, &edges_result);
            (output, "application/json")
        }
        _ => {
            return (
                StatusCode::BAD_REQUEST,
                [(axum::http::header::CONTENT_TYPE, "text/plain")],
                format!("Unknown format: {}. Supported: json, mu, mermaid, d2, cytoscape", params.format),
            )
                .into_response();
        }
    };

    (
        StatusCode::OK,
        [(axum::http::header::CONTENT_TYPE, content_type)],
        content,
    )
        .into_response()
}

/// Export to MU sigil format.
fn export_mu_format(
    nodes: &crate::storage::QueryResult,
    edges: &crate::storage::QueryResult,
) -> String {
    use std::collections::HashMap;

    // Group nodes by file_path
    let mut modules: HashMap<String, Vec<&Vec<serde_json::Value>>> = HashMap::new();

    for row in &nodes.rows {
        let file_path = row
            .get(4)
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        modules.entry(file_path).or_default().push(row);
    }

    // Build dependency map from edges
    let mut deps: HashMap<String, Vec<String>> = HashMap::new();
    for row in &edges.rows {
        let source = row.get(0).and_then(|v| v.as_str()).unwrap_or("");
        let target = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
        let edge_type = row.get(2).and_then(|v| v.as_str()).unwrap_or("");
        if edge_type == "imports" {
            deps.entry(source.to_string())
                .or_default()
                .push(target.to_string());
        }
    }

    let mut output = String::new();

    for (file_path, file_nodes) in modules {
        output.push_str(&format!("! {}\n", file_path));

        for node in file_nodes {
            let node_type = node.get(1).and_then(|v| v.as_str()).unwrap_or("");
            let name = node.get(2).and_then(|v| v.as_str()).unwrap_or("");

            match node_type {
                "class" => output.push_str(&format!("  $ {}\n", name)),
                "function" => output.push_str(&format!("  # {}\n", name)),
                _ => {}
            }
        }

        // Add dependencies
        if let Some(module_deps) = deps.get(&format!("mod:{}", file_path)) {
            let dep_names: Vec<&str> = module_deps
                .iter()
                .filter_map(|d| d.strip_prefix("mod:"))
                .collect();
            if !dep_names.is_empty() {
                output.push_str(&format!("  @ {}\n", dep_names.join(", ")));
            }
        }
        output.push('\n');
    }

    output
}

/// Export to Mermaid flowchart format.
fn export_mermaid_format(
    nodes: &crate::storage::QueryResult,
    edges: &crate::storage::QueryResult,
) -> String {
    let mut output = String::from("flowchart TB\n");

    // Add nodes
    for row in &nodes.rows {
        let id = row.get(0).and_then(|v| v.as_str()).unwrap_or("");
        let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
        let name = row.get(2).and_then(|v| v.as_str()).unwrap_or("");

        // Sanitize ID for Mermaid
        let safe_id = id
            .replace([':', '/', '.', '-', ' '], "_")
            .replace(['(', ')'], "");

        let shape = match node_type {
            "module" => format!("{}([{}])", safe_id, name),
            "class" => format!("{}[{}]", safe_id, name),
            "function" => format!("{}({})", safe_id, name),
            _ => format!("{}[{}]", safe_id, name),
        };
        output.push_str(&format!("    {}\n", shape));
    }

    output.push('\n');

    // Add edges
    for row in &edges.rows {
        let source = row.get(0).and_then(|v| v.as_str()).unwrap_or("");
        let target = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
        let edge_type = row.get(2).and_then(|v| v.as_str()).unwrap_or("");

        let safe_source = source
            .replace([':', '/', '.', '-', ' '], "_")
            .replace(['(', ')'], "");
        let safe_target = target
            .replace([':', '/', '.', '-', ' '], "_")
            .replace(['(', ')'], "");

        let arrow = match edge_type {
            "imports" => "-->",
            "contains" => "---",
            "inherits" => "-.->",
            _ => "-->",
        };
        output.push_str(&format!("    {} {} {}\n", safe_source, arrow, safe_target));
    }

    output
}

/// Export to D2 diagram format.
fn export_d2_format(
    nodes: &crate::storage::QueryResult,
    edges: &crate::storage::QueryResult,
) -> String {
    let mut output = String::from("direction: right\n\n");

    // Add nodes
    for row in &nodes.rows {
        let id = row.get(0).and_then(|v| v.as_str()).unwrap_or("");
        let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
        let name = row.get(2).and_then(|v| v.as_str()).unwrap_or("");

        let safe_id = id
            .replace([':', '/', '.', '-', ' '], "_")
            .replace(['(', ')'], "");

        let shape = match node_type {
            "module" => "package",
            "class" => "class",
            "function" => "oval",
            _ => "rectangle",
        };
        output.push_str(&format!("{}: {} {{ shape: {} }}\n", safe_id, name, shape));
    }

    output.push('\n');

    // Add edges
    for row in &edges.rows {
        let source = row.get(0).and_then(|v| v.as_str()).unwrap_or("");
        let target = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
        let edge_type = row.get(2).and_then(|v| v.as_str()).unwrap_or("");

        let safe_source = source
            .replace([':', '/', '.', '-', ' '], "_")
            .replace(['(', ')'], "");
        let safe_target = target
            .replace([':', '/', '.', '-', ' '], "_")
            .replace(['(', ')'], "");

        output.push_str(&format!("{} -> {}: {}\n", safe_source, safe_target, edge_type));
    }

    output
}

/// Export to Cytoscape.js JSON format.
fn export_cytoscape_format(
    nodes: &crate::storage::QueryResult,
    edges: &crate::storage::QueryResult,
) -> String {
    let cytoscape_nodes: Vec<serde_json::Value> = nodes
        .rows
        .iter()
        .map(|row| {
            serde_json::json!({
                "data": {
                    "id": row.get(0).and_then(|v| v.as_str()).unwrap_or(""),
                    "label": row.get(2).and_then(|v| v.as_str()).unwrap_or(""),
                    "type": row.get(1).and_then(|v| v.as_str()).unwrap_or(""),
                    "file_path": row.get(4).and_then(|v| v.as_str()),
                }
            })
        })
        .collect();

    let cytoscape_edges: Vec<serde_json::Value> = edges
        .rows
        .iter()
        .enumerate()
        .map(|(i, row)| {
            serde_json::json!({
                "data": {
                    "id": format!("edge_{}", i),
                    "source": row.get(0).and_then(|v| v.as_str()).unwrap_or(""),
                    "target": row.get(1).and_then(|v| v.as_str()).unwrap_or(""),
                    "type": row.get(2).and_then(|v| v.as_str()).unwrap_or(""),
                }
            })
        })
        .collect();

    let output = serde_json::json!({
        "elements": {
            "nodes": cytoscape_nodes,
            "edges": cytoscape_edges,
        }
    });

    serde_json::to_string_pretty(&output).unwrap_or_default()
}

// =============================================================================
// OMEGA Context Endpoint
// =============================================================================

#[derive(Deserialize)]
struct OmegaContextRequest {
    question: String,
    #[serde(default = "default_max_tokens")]
    max_tokens: usize,
    #[serde(default = "default_include_synthesized")]
    include_synthesized: bool,
    #[serde(default = "default_max_synthesized_macros")]
    max_synthesized_macros: usize,
    #[serde(default = "default_include_seed")]
    include_seed: bool,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

fn default_include_synthesized() -> bool {
    true
}

fn default_max_synthesized_macros() -> usize {
    5
}

fn default_include_seed() -> bool {
    true
}

#[derive(Serialize)]
struct OmegaContextResponse {
    seed: String,
    body: String,
    full_output: String,
    macros_used: Vec<String>,
    seed_tokens: usize,
    body_tokens: usize,
    total_tokens: usize,
    original_tokens: usize,
    compression_ratio: f64,
    nodes_included: usize,
    manifest: serde_json::Value,
}

async fn context_omega(
    State(state): State<Arc<AppState>>,
    Json(req): Json<OmegaContextRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    // First, get the regular context extraction
    let extractor = ContextExtractor::new(state.as_ref());
    let result = extractor.extract(&req.question, req.max_tokens).await;

    match result {
        Ok(ctx) => {
            // Generate OMEGA format from the context
            let omega_result = generate_omega_output(&ctx, &req, &state).await;

            match omega_result {
                Ok(data) => ApiResponse::ok(data, start.elapsed().as_millis() as u64),
                Err(e) => ApiResponse::<OmegaContextResponse>::err(e, start.elapsed().as_millis() as u64),
            }
        }
        Err(e) => ApiResponse::<OmegaContextResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

/// Generate OMEGA S-expression output from context extraction result.
async fn generate_omega_output(
    ctx: &crate::context::ContextResult,
    req: &OmegaContextRequest,
    state: &AppState,
) -> Result<OmegaContextResponse, String> {
    // OMEGA Schema v2.0 header (stable for caching)
    let seed = r#";; OMG SCHEMA v2.0 - Positional S-Expression Format
;; Forms: (module Name FilePath ...)
;;        (class Name Parent [attrs] ...)
;;        (service Name [deps] ...)
;;        (method Name [args] ReturnType Complexity)
;;        (function Name [args] ReturnType Complexity)
;;        (api HttpVerb Path Handler [args])
;;        (model Name [field:type ...])
;;        (validator Name Target [rules])
"#.to_string();

    // Generate body from nodes
    let body = generate_omega_body(&ctx.nodes, state).await?;

    // Estimate token counts (rough approximation: ~4 chars per token)
    let seed_tokens = seed.len() / 4;
    let body_tokens = body.len() / 4;
    let total_tokens = seed_tokens + body_tokens;
    let original_tokens = ctx.tokens;

    let compression_ratio = if total_tokens > 0 {
        original_tokens as f64 / total_tokens as f64
    } else {
        1.0
    };

    // Build full output based on include_seed
    let full_output = if req.include_seed {
        format!("{}\n\n;; Codebase Context\n{}", seed, body)
    } else {
        format!(";; Codebase Context\n{}", body)
    };

    // Build manifest
    let manifest = serde_json::json!({
        "version": "2.0",
        "schema": "omega",
        "forms": ["module", "class", "service", "method", "function", "api", "model", "validator"],
    });

    Ok(OmegaContextResponse {
        seed: if req.include_seed { seed } else { String::new() },
        body,
        full_output,
        macros_used: vec!["module".to_string(), "class".to_string(), "function".to_string(), "method".to_string()],
        seed_tokens: if req.include_seed { seed_tokens } else { 0 },
        body_tokens,
        total_tokens: if req.include_seed { total_tokens } else { body_tokens },
        original_tokens,
        compression_ratio,
        nodes_included: ctx.nodes.len(),
        manifest,
    })
}

/// Generate OMEGA body from node IDs.
async fn generate_omega_body(node_ids: &[String], state: &AppState) -> Result<String, String> {
    use std::collections::HashMap;

    let mubase = state.mubase.read().await;

    // Fetch nodes and group by file_path
    let mut modules: HashMap<String, Vec<serde_json::Value>> = HashMap::new();

    for node_id in node_ids {
        if let Ok(Some(node)) = mubase.get_node(node_id) {
            let file_path = node.file_path.unwrap_or_else(|| "unknown".to_string());
            modules.entry(file_path).or_default().push(serde_json::json!({
                "id": node.id,
                "name": node.name,
                "type": node.node_type.as_str(),
                "complexity": node.complexity,
                "line_start": node.line_start,
                "line_end": node.line_end,
            }));
        }
    }

    // Generate S-expression output
    let mut lines = Vec::new();

    for (file_path, file_nodes) in modules.iter() {
        // Convert file path to module name
        let module_name = path_to_module_name(file_path);

        lines.push(format!("(module {} \"{}\"", module_name, file_path));

        for node in file_nodes {
            let node_type = node.get("type").and_then(|v| v.as_str()).unwrap_or("");
            let name = node.get("name").and_then(|v| v.as_str()).unwrap_or("unknown");
            let complexity = node.get("complexity").and_then(|v| v.as_u64()).unwrap_or(0);

            match node_type {
                "class" => {
                    lines.push(format!("  (class {} nil [])", name));
                }
                "function" => {
                    lines.push(format!("  (function {} [] None {})", name, complexity));
                }
                _ => {}
            }
        }

        lines.push(")".to_string());
    }

    Ok(lines.join("\n"))
}

/// Convert file path to module name (e.g., "src/mu/cli.py" -> "mu.cli").
fn path_to_module_name(path: &str) -> String {
    let mut name = path.to_string();

    // Remove common prefixes
    for prefix in &["src/", "lib/", "app/"] {
        if name.starts_with(prefix) {
            name = name[prefix.len()..].to_string();
            break;
        }
    }

    // Remove extension
    for ext in &[".py", ".ts", ".js", ".go", ".java", ".rs", ".cs"] {
        if name.ends_with(ext) {
            name = name[..name.len() - ext.len()].to_string();
            break;
        }
    }

    // Convert path separators to dots
    name = name.replace('/', ".").replace('\\', ".");

    // Remove trailing __init__
    if name.ends_with(".__init__") {
        name = name[..name.len() - 9].to_string();
    }

    name
}

// =============================================================================
// Pattern Detection Endpoint
// =============================================================================

#[derive(Deserialize)]
struct PatternsRequest {
    category: Option<String>,
    #[serde(default)]
    refresh: bool,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

#[derive(Serialize)]
struct PatternInfo {
    name: String,
    category: String,
    description: String,
    frequency: usize,
    confidence: f64,
    examples: Vec<serde_json::Value>,
    anti_patterns: Vec<String>,
}

#[derive(Serialize)]
struct PatternsResponse {
    patterns: Vec<PatternInfo>,
    total_patterns: usize,
    categories_found: Vec<String>,
    detection_time_ms: f64,
}

async fn patterns(
    State(state): State<Arc<AppState>>,
    Json(req): Json<PatternsRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let result = detect_patterns(&state, req.category.as_deref(), req.refresh).await;

    match result {
        Ok(data) => ApiResponse::ok(data, start.elapsed().as_millis() as u64),
        Err(e) => ApiResponse::<PatternsResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

/// Detect patterns in the codebase.
async fn detect_patterns(
    state: &AppState,
    category: Option<&str>,
    _refresh: bool,
) -> Result<PatternsResponse, String> {
    let detection_start = Instant::now();
    let mubase = state.mubase.read().await;

    let mut patterns = Vec::new();
    let mut categories_found = Vec::new();

    // Detect naming patterns
    if category.is_none() || category == Some("naming") {
        let naming_patterns = detect_naming_patterns(&mubase)?;
        if !naming_patterns.is_empty() {
            categories_found.push("naming".to_string());
        }
        patterns.extend(naming_patterns);
    }

    // Detect architecture patterns (services, repositories, etc.)
    if category.is_none() || category == Some("architecture") {
        let arch_patterns = detect_architecture_patterns(&mubase)?;
        if !arch_patterns.is_empty() {
            categories_found.push("architecture".to_string());
        }
        patterns.extend(arch_patterns);
    }

    // Detect testing patterns
    if category.is_none() || category == Some("testing") {
        let test_patterns = detect_testing_patterns(&mubase)?;
        if !test_patterns.is_empty() {
            categories_found.push("testing".to_string());
        }
        patterns.extend(test_patterns);
    }

    // Detect API patterns
    if category.is_none() || category == Some("api") {
        let api_patterns = detect_api_patterns(&mubase)?;
        if !api_patterns.is_empty() {
            categories_found.push("api".to_string());
        }
        patterns.extend(api_patterns);
    }

    // Sort by frequency
    patterns.sort_by(|a, b| b.frequency.cmp(&a.frequency));

    let detection_time_ms = detection_start.elapsed().as_secs_f64() * 1000.0;

    Ok(PatternsResponse {
        total_patterns: patterns.len(),
        patterns,
        categories_found,
        detection_time_ms,
    })
}

/// Detect naming convention patterns.
fn detect_naming_patterns(mubase: &crate::storage::MUbase) -> Result<Vec<PatternInfo>, String> {
    let mut patterns = Vec::new();

    // Check for class naming suffixes
    let class_sql = "SELECT name FROM nodes WHERE type = 'class'";
    let result = mubase.query(class_sql).map_err(|e| e.to_string())?;

    let mut suffix_counts: std::collections::HashMap<String, usize> = std::collections::HashMap::new();

    for row in &result.rows {
        if let Some(name) = row.get(0).and_then(|v| v.as_str()) {
            // Extract CamelCase suffix
            let chars: Vec<char> = name.chars().collect();
            let mut last_upper_idx = chars.len();
            for (i, c) in chars.iter().enumerate().rev() {
                if c.is_uppercase() {
                    last_upper_idx = i;
                    break;
                }
            }
            if last_upper_idx < chars.len() {
                let suffix: String = chars[last_upper_idx..].iter().collect();
                if suffix.len() > 2 {
                    *suffix_counts.entry(suffix).or_insert(0) += 1;
                }
            }
        }
    }

    // Create patterns for common suffixes
    for (suffix, count) in suffix_counts {
        if count >= 3 {
            patterns.push(PatternInfo {
                name: format!("class_suffix_{}", suffix.to_lowercase()),
                category: "naming".to_string(),
                description: format!("Classes ending with '{}' ({} occurrences)", suffix, count),
                frequency: count,
                confidence: (count as f64 / result.rows.len() as f64).min(1.0),
                examples: vec![],
                anti_patterns: vec![format!("Using generic names without '{}' suffix for this type", suffix)],
            });
        }
    }

    // Check for function naming style (snake_case vs camelCase)
    let func_sql = "SELECT name FROM nodes WHERE type = 'function'";
    let func_result = mubase.query(func_sql).map_err(|e| e.to_string())?;

    let mut snake_case_count = 0;
    let mut camel_case_count = 0;

    for row in &func_result.rows {
        if let Some(name) = row.get(0).and_then(|v| v.as_str()) {
            if name.contains('_') && name.chars().all(|c| c.is_lowercase() || c == '_' || c.is_numeric()) {
                snake_case_count += 1;
            } else if !name.contains('_') && name.chars().next().map(|c| c.is_lowercase()).unwrap_or(false) {
                camel_case_count += 1;
            }
        }
    }

    let total = snake_case_count + camel_case_count;
    if total >= 3 {
        if snake_case_count > camel_case_count {
            patterns.push(PatternInfo {
                name: "snake_case_functions".to_string(),
                category: "naming".to_string(),
                description: format!("Functions use snake_case ({}/{})", snake_case_count, total),
                frequency: snake_case_count,
                confidence: snake_case_count as f64 / total as f64,
                examples: vec![],
                anti_patterns: vec!["Using camelCase for function names".to_string()],
            });
        } else if camel_case_count > snake_case_count {
            patterns.push(PatternInfo {
                name: "camel_case_functions".to_string(),
                category: "naming".to_string(),
                description: format!("Functions use camelCase ({}/{})", camel_case_count, total),
                frequency: camel_case_count,
                confidence: camel_case_count as f64 / total as f64,
                examples: vec![],
                anti_patterns: vec!["Using snake_case for function names".to_string()],
            });
        }
    }

    Ok(patterns)
}

/// Detect architectural patterns (services, repositories, etc.).
fn detect_architecture_patterns(mubase: &crate::storage::MUbase) -> Result<Vec<PatternInfo>, String> {
    let mut patterns = Vec::new();

    // Service pattern
    let service_sql = "SELECT COUNT(*) FROM nodes WHERE type = 'class' AND name LIKE '%Service'";
    let service_result = mubase.query(service_sql).map_err(|e| e.to_string())?;
    let service_count = service_result.rows.first()
        .and_then(|r| r.first())
        .and_then(|v| v.as_i64())
        .unwrap_or(0) as usize;

    if service_count >= 3 {
        patterns.push(PatternInfo {
            name: "service_layer".to_string(),
            category: "architecture".to_string(),
            description: format!("Service layer pattern ({} Service classes)", service_count),
            frequency: service_count,
            confidence: 0.9,
            examples: vec![],
            anti_patterns: vec!["Business logic in controllers/handlers".to_string()],
        });
    }

    // Repository pattern
    let repo_sql = "SELECT COUNT(*) FROM nodes WHERE type = 'class' AND (name LIKE '%Repository' OR name LIKE '%Repo' OR name LIKE '%Store')";
    let repo_result = mubase.query(repo_sql).map_err(|e| e.to_string())?;
    let repo_count = repo_result.rows.first()
        .and_then(|r| r.first())
        .and_then(|v| v.as_i64())
        .unwrap_or(0) as usize;

    if repo_count >= 3 {
        patterns.push(PatternInfo {
            name: "repository_pattern".to_string(),
            category: "architecture".to_string(),
            description: format!("Repository/Store pattern ({} classes)", repo_count),
            frequency: repo_count,
            confidence: 0.9,
            examples: vec![],
            anti_patterns: vec!["Direct database access in services".to_string()],
        });
    }

    // Controller/Handler pattern
    let controller_sql = "SELECT COUNT(*) FROM nodes WHERE type = 'class' AND (name LIKE '%Controller' OR name LIKE '%Handler' OR name LIKE '%Router')";
    let controller_result = mubase.query(controller_sql).map_err(|e| e.to_string())?;
    let controller_count = controller_result.rows.first()
        .and_then(|r| r.first())
        .and_then(|v| v.as_i64())
        .unwrap_or(0) as usize;

    if controller_count >= 3 {
        patterns.push(PatternInfo {
            name: "controller_pattern".to_string(),
            category: "architecture".to_string(),
            description: format!("Controller/Handler pattern ({} classes)", controller_count),
            frequency: controller_count,
            confidence: 0.85,
            examples: vec![],
            anti_patterns: vec![],
        });
    }

    Ok(patterns)
}

/// Detect testing patterns.
fn detect_testing_patterns(mubase: &crate::storage::MUbase) -> Result<Vec<PatternInfo>, String> {
    let mut patterns = Vec::new();

    // Test file naming
    let test_sql = "SELECT COUNT(*) FROM nodes WHERE type = 'module' AND (file_path LIKE '%test_%' OR file_path LIKE '%_test.%' OR file_path LIKE '%.test.%' OR file_path LIKE '%.spec.%')";
    let test_result = mubase.query(test_sql).map_err(|e| e.to_string())?;
    let test_count = test_result.rows.first()
        .and_then(|r| r.first())
        .and_then(|v| v.as_i64())
        .unwrap_or(0) as usize;

    if test_count >= 3 {
        patterns.push(PatternInfo {
            name: "test_file_organization".to_string(),
            category: "testing".to_string(),
            description: format!("Test files ({} found)", test_count),
            frequency: test_count,
            confidence: 0.9,
            examples: vec![],
            anti_patterns: vec!["Test files scattered without convention".to_string()],
        });
    }

    // Test function naming
    let test_func_sql = "SELECT COUNT(*) FROM nodes WHERE type = 'function' AND name LIKE 'test%'";
    let test_func_result = mubase.query(test_func_sql).map_err(|e| e.to_string())?;
    let test_func_count = test_func_result.rows.first()
        .and_then(|r| r.first())
        .and_then(|v| v.as_i64())
        .unwrap_or(0) as usize;

    if test_func_count >= 3 {
        patterns.push(PatternInfo {
            name: "test_function_naming".to_string(),
            category: "testing".to_string(),
            description: format!("Test functions with 'test' prefix ({} found)", test_func_count),
            frequency: test_func_count,
            confidence: 0.95,
            examples: vec![],
            anti_patterns: vec!["Test functions without 'test' prefix".to_string()],
        });
    }

    Ok(patterns)
}

/// Detect API patterns.
fn detect_api_patterns(mubase: &crate::storage::MUbase) -> Result<Vec<PatternInfo>, String> {
    let mut patterns = Vec::new();

    // Route/API modules
    let route_sql = "SELECT COUNT(*) FROM nodes WHERE type = 'module' AND (file_path LIKE '%route%' OR file_path LIKE '%api%' OR file_path LIKE '%endpoint%' OR file_path LIKE '%views%')";
    let route_result = mubase.query(route_sql).map_err(|e| e.to_string())?;
    let route_count = route_result.rows.first()
        .and_then(|r| r.first())
        .and_then(|v| v.as_i64())
        .unwrap_or(0) as usize;

    if route_count >= 3 {
        patterns.push(PatternInfo {
            name: "route_modules".to_string(),
            category: "api".to_string(),
            description: format!("Dedicated route/API modules ({} found)", route_count),
            frequency: route_count,
            confidence: 0.85,
            examples: vec![],
            anti_patterns: vec![],
        });
    }

    Ok(patterns)
}

// =============================================================================
// Proactive Warnings Endpoint
// =============================================================================

#[derive(Deserialize)]
struct WarnRequest {
    target: String,
    /// Client working directory for multi-project routing
    cwd: Option<String>,
}

#[derive(Serialize)]
struct WarningInfo {
    category: String,
    level: String,
    message: String,
    details: Option<serde_json::Value>,
}

#[derive(Serialize)]
struct WarnResponse {
    target: String,
    target_type: String,
    warnings: Vec<WarningInfo>,
    summary: String,
    risk_score: f64,
    analysis_time_ms: f64,
}

async fn warn(
    State(state): State<Arc<AppState>>,
    Json(req): Json<WarnRequest>,
) -> impl IntoResponse {
    let start = Instant::now();

    let result = analyze_warnings(&state, &req.target).await;

    match result {
        Ok(data) => ApiResponse::ok(data, start.elapsed().as_millis() as u64),
        Err(e) => ApiResponse::<WarnResponse>::err(e, start.elapsed().as_millis() as u64),
    }
}

/// Analyze a target for proactive warnings.
async fn analyze_warnings(state: &AppState, target: &str) -> Result<WarnResponse, String> {
    let analysis_start = Instant::now();
    let mubase = state.mubase.read().await;

    let mut warnings = Vec::new();
    let mut target_type = "unknown".to_string();
    let mut node_id = None;

    // Resolve target to node
    if target.starts_with("mod:") || target.starts_with("cls:") || target.starts_with("fn:") {
        // Direct node ID
        if let Ok(Some(node)) = mubase.get_node(target) {
            node_id = Some(target.to_string());
            target_type = node.node_type.as_str().to_string();
        }
    } else {
        // Try to find by file path or name
        let search_sql = format!(
            "SELECT id, type FROM nodes WHERE file_path LIKE '%{}' OR name = '{}' LIMIT 1",
            target.replace('\'', "''"),
            target.replace('\'', "''")
        );
        if let Ok(result) = mubase.query(&search_sql) {
            if let Some(row) = result.rows.first() {
                node_id = row.get(0).and_then(|v| v.as_str()).map(String::from);
                target_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
            }
        }
    }

    // Check impact (dependents count)
    if let Some(ref id) = node_id {
        let impact_sql = format!(
            "SELECT COUNT(*) FROM edges WHERE target_id = '{}'",
            id.replace('\'', "''")
        );
        if let Ok(result) = mubase.query(&impact_sql) {
            let dependent_count = result.rows.first()
                .and_then(|r| r.first())
                .and_then(|v| v.as_i64())
                .unwrap_or(0);

            if dependent_count > 10 {
                let level = if dependent_count > 30 { "error" } else { "warn" };
                warnings.push(WarningInfo {
                    category: "high_impact".to_string(),
                    level: level.to_string(),
                    message: format!("{} nodes depend on this - changes may have wide impact", dependent_count),
                    details: Some(serde_json::json!({
                        "dependent_count": dependent_count,
                    })),
                });
            }
        }
    }

    // Check complexity
    if let Some(ref id) = node_id {
        let complexity_sql = format!(
            "SELECT complexity FROM nodes WHERE id = '{}'",
            id.replace('\'', "''")
        );
        if let Ok(result) = mubase.query(&complexity_sql) {
            let complexity = result.rows.first()
                .and_then(|r| r.first())
                .and_then(|v| v.as_i64())
                .unwrap_or(0);

            if complexity > 50 {
                warnings.push(WarningInfo {
                    category: "complexity".to_string(),
                    level: "error".to_string(),
                    message: format!("Very high complexity ({}) - consider refactoring before changes", complexity),
                    details: Some(serde_json::json!({
                        "complexity": complexity,
                        "threshold": 50,
                    })),
                });
            } else if complexity > 20 {
                warnings.push(WarningInfo {
                    category: "complexity".to_string(),
                    level: "warn".to_string(),
                    message: format!("High complexity ({}) - changes may be risky", complexity),
                    details: Some(serde_json::json!({
                        "complexity": complexity,
                        "threshold": 20,
                    })),
                });
            }
        }
    }

    // Check for security-sensitive code
    let security_keywords = ["auth", "password", "token", "secret", "crypto", "encrypt", "session", "login"];
    let target_lower = target.to_lowercase();
    for keyword in &security_keywords {
        if target_lower.contains(keyword) {
            warnings.push(WarningInfo {
                category: "security".to_string(),
                level: "warn".to_string(),
                message: "Security-sensitive code detected - extra review recommended".to_string(),
                details: Some(serde_json::json!({
                    "indicator": keyword,
                })),
            });
            break;
        }
    }

    // Check for test coverage (simple heuristic: look for test files)
    if let Some(ref id) = node_id {
        if id.starts_with("mod:") && !id.contains("test") {
            let file_path = id.strip_prefix("mod:").unwrap_or(id);
            let stem = file_path.rsplit('/').next().unwrap_or(file_path);
            let stem = stem.rsplit('.').last().unwrap_or(stem);

            let test_patterns = vec![
                format!("test_{}", stem),
                format!("{}_test", stem),
            ];

            let mut test_found = false;
            for pattern in test_patterns {
                let test_sql = format!(
                    "SELECT COUNT(*) FROM nodes WHERE type = 'module' AND file_path LIKE '%{}%'",
                    pattern
                );
                if let Ok(result) = mubase.query(&test_sql) {
                    let count = result.rows.first()
                        .and_then(|r| r.first())
                        .and_then(|v| v.as_i64())
                        .unwrap_or(0);
                    if count > 0 {
                        test_found = true;
                        break;
                    }
                }
            }

            if !test_found {
                warnings.push(WarningInfo {
                    category: "no_tests".to_string(),
                    level: "warn".to_string(),
                    message: "No test file found - consider adding tests before modifying".to_string(),
                    details: None,
                });
            }
        }
    }

    // Calculate risk score
    let risk_score = calculate_risk_score(&warnings);

    // Generate summary
    let summary = generate_warning_summary(&warnings, target);

    let analysis_time_ms = analysis_start.elapsed().as_secs_f64() * 1000.0;

    Ok(WarnResponse {
        target: target.to_string(),
        target_type,
        warnings,
        summary,
        risk_score,
        analysis_time_ms,
    })
}

/// Calculate overall risk score based on warnings.
fn calculate_risk_score(warnings: &[WarningInfo]) -> f64 {
    if warnings.is_empty() {
        return 0.0;
    }

    let mut score: f64 = 0.0;
    for w in warnings {
        // Level weights
        let level_weight = match w.level.as_str() {
            "error" => 0.3,
            "warn" => 0.15,
            "info" => 0.05,
            _ => 0.1,
        };

        // Category weights
        let category_weight = match w.category.as_str() {
            "high_impact" => 1.2,
            "security" => 1.3,
            "complexity" => 1.1,
            "stale" => 0.9,
            "no_tests" => 0.8,
            "deprecated" => 0.7,
            _ => 1.0,
        };

        score += level_weight * category_weight;
    }

    // Normalize to 0-1 range
    score.min(1.0)
}

/// Generate a one-line summary of warnings.
fn generate_warning_summary(warnings: &[WarningInfo], target: &str) -> String {
    if warnings.is_empty() {
        return format!("No warnings for {}", target);
    }

    let error_count = warnings.iter().filter(|w| w.level == "error").count();
    let warn_count = warnings.iter().filter(|w| w.level == "warn").count();
    let info_count = warnings.iter().filter(|w| w.level == "info").count();

    let mut parts = Vec::new();
    if error_count > 0 {
        parts.push(format!("{} error{}", error_count, if error_count != 1 { "s" } else { "" }));
    }
    if warn_count > 0 {
        parts.push(format!("{} warning{}", warn_count, if warn_count != 1 { "s" } else { "" }));
    }
    if info_count > 0 {
        parts.push(format!("{} info", info_count));
    }

    // Add key categories
    let categories: std::collections::HashSet<&str> = warnings.iter()
        .map(|w| w.category.as_str())
        .collect();

    let mut key_cats = Vec::new();
    if categories.contains("high_impact") {
        key_cats.push("high-impact");
    }
    if categories.contains("security") {
        key_cats.push("security-sensitive");
    }
    if categories.contains("stale") {
        key_cats.push("stale");
    }

    let mut summary = parts.join(", ");
    if !key_cats.is_empty() {
        summary.push_str(&format!(" ({})", key_cats.join(", ")));
    }

    summary
}
