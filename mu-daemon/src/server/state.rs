//! Shared application state for the server.

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::{broadcast, RwLock};

use super::projects::ProjectManager;
use crate::storage::{GraphEngine, MUbase};

/// Events broadcast when the graph changes.
#[derive(Debug, Clone)]
pub enum GraphEvent {
    /// A file was modified
    FileModified(PathBuf),
    /// A file was created
    FileCreated(PathBuf),
    /// A file was deleted
    FileDeleted(PathBuf),
    /// Graph was rebuilt
    GraphRebuilt { node_count: usize, edge_count: usize },
    /// Build started
    BuildStarted,
    /// Build completed
    BuildCompleted { duration_ms: u64 },
}

/// Shared application state.
#[derive(Clone)]
pub struct AppState {
    /// DuckDB connection for persistent storage (default project)
    pub mubase: Arc<RwLock<MUbase>>,
    /// In-memory graph for fast traversal (default project)
    pub graph: Arc<RwLock<GraphEngine>>,
    /// Channel for broadcasting graph events
    pub watcher_tx: broadcast::Sender<GraphEvent>,
    /// Root directory being analyzed (default project)
    pub root: PathBuf,
    /// Multi-project manager
    pub projects: Arc<ProjectManager>,
    /// Daemon start time for uptime calculation
    pub start_time: Instant,
    /// WebSocket connection counter
    pub ws_connections: Arc<AtomicUsize>,
}

impl AppState {
    /// Subscribe to graph events.
    pub fn subscribe(&self) -> broadcast::Receiver<GraphEvent> {
        self.watcher_tx.subscribe()
    }

    /// Broadcast a graph event.
    pub fn broadcast(&self, event: GraphEvent) {
        let _ = self.watcher_tx.send(event);
    }

    /// Get uptime in seconds.
    pub fn uptime_seconds(&self) -> f64 {
        self.start_time.elapsed().as_secs_f64()
    }

    /// Get current WebSocket connection count.
    pub fn ws_connection_count(&self) -> usize {
        self.ws_connections.load(Ordering::Relaxed)
    }

    /// Increment WebSocket connection count.
    pub fn ws_connect(&self) {
        self.ws_connections.fetch_add(1, Ordering::Relaxed);
    }

    /// Decrement WebSocket connection count.
    pub fn ws_disconnect(&self) {
        self.ws_connections.fetch_sub(1, Ordering::Relaxed);
    }
}
