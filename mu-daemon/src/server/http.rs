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
    mu_output: String,
    nodes: Vec<String>,
    tokens: usize,
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
                mu_output: ctx.mu_output,
                nodes: ctx.nodes,
                tokens: ctx.tokens,
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
