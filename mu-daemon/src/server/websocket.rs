//! WebSocket handler for live graph updates.

use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    response::IntoResponse,
};
use futures::{SinkExt, StreamExt};
use std::sync::Arc;
use tracing::{debug, info};

use super::state::{AppState, GraphEvent};

/// WebSocket upgrade handler.
pub async fn websocket_handler(
    ws: WebSocketUpgrade,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    ws.on_upgrade(|socket| handle_socket(socket, state))
}

/// Handle an individual WebSocket connection.
async fn handle_socket(socket: WebSocket, state: Arc<AppState>) {
    let (mut sender, mut receiver) = socket.split();

    // Subscribe to graph events
    let mut event_rx = state.subscribe();

    info!("WebSocket client connected");

    // Spawn task to forward events to WebSocket
    let send_task = tokio::spawn(async move {
        while let Ok(event) = event_rx.recv().await {
            let msg = match event {
                GraphEvent::FileModified(path) => {
                    serde_json::json!({
                        "type": "file_modified",
                        "path": path.display().to_string()
                    })
                }
                GraphEvent::FileCreated(path) => {
                    serde_json::json!({
                        "type": "file_created",
                        "path": path.display().to_string()
                    })
                }
                GraphEvent::FileDeleted(path) => {
                    serde_json::json!({
                        "type": "file_deleted",
                        "path": path.display().to_string()
                    })
                }
                GraphEvent::GraphRebuilt {
                    node_count,
                    edge_count,
                } => {
                    serde_json::json!({
                        "type": "graph_rebuilt",
                        "node_count": node_count,
                        "edge_count": edge_count
                    })
                }
                GraphEvent::BuildStarted => {
                    serde_json::json!({
                        "type": "build_started"
                    })
                }
                GraphEvent::BuildCompleted { duration_ms } => {
                    serde_json::json!({
                        "type": "build_completed",
                        "duration_ms": duration_ms
                    })
                }
            };

            let json = serde_json::to_string(&msg).unwrap_or_default();
            if sender.send(Message::Text(json)).await.is_err() {
                break;
            }
        }
    });

    // Handle incoming messages (for ping/pong or future commands)
    while let Some(Ok(msg)) = receiver.next().await {
        match msg {
            Message::Text(text) => {
                debug!("Received WebSocket message: {}", text);
                // Could handle commands here in the future
            }
            Message::Close(_) => {
                info!("WebSocket client disconnected");
                break;
            }
            _ => {}
        }
    }

    // Clean up
    send_task.abort();
}
