//! Shared application state for the server.

use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::{broadcast, RwLock};

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
    /// DuckDB connection for persistent storage
    pub mubase: Arc<RwLock<MUbase>>,
    /// In-memory graph for fast traversal
    pub graph: Arc<RwLock<GraphEngine>>,
    /// Channel for broadcasting graph events
    pub watcher_tx: broadcast::Sender<GraphEvent>,
    /// Root directory being analyzed
    pub root: PathBuf,
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
}
