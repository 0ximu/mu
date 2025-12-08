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
        .route("/nodes", post(get_nodes_batch))
        // Graph traversal
        .route("/deps", post(deps))
        .route("/impact", post(impact))
        .route("/ancestors", post(ancestors))
        .route("/cycles", post(cycles))
        // Build operations
        .route("/build", post(build))
        .route("/scan", post(scan))
        // WebSocket for live updates
        .route("/ws", get(websocket_handler))
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

#[derive(Serialize)]
struct StatusResponse {
    node_count: usize,
    edge_count: usize,
    root: String,
    schema_version: String,
}

async fn status(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    let start = Instant::now();

    let graph = state.graph.read().await;
    let data = StatusResponse {
        node_count: graph.node_count(),
        edge_count: graph.edge_count(),
        root: state.root.display().to_string(),
        schema_version: "1.0.0".to_string(),
    };

    ApiResponse::ok(data, start.elapsed().as_millis() as u64)
}

// =============================================================================
// Query Endpoints
// =============================================================================

#[derive(Deserialize)]
struct QueryRequest {
    muql: String,
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
// Graph Traversal
// =============================================================================

#[derive(Deserialize)]
struct DepsRequest {
    node: String,
    #[serde(default = "default_direction")]
    direction: String,
    #[serde(default = "default_depth")]
    depth: usize,
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
