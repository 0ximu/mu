//! File watcher for live graph updates.
//!
//! Uses notify crate to watch for file changes and trigger incremental updates.

use anyhow::Result;
use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc;
use tokio::time;
use tracing::{debug, info, warn};

use crate::build::BuildPipeline;
use crate::server::state::{AppState, GraphEvent};

/// Supported file extensions for watching.
const SUPPORTED_EXTENSIONS: &[&str] = &[
    "py", "ts", "tsx", "js", "jsx", "go", "java", "rs", "cs",
];

/// Watch a directory for file changes and trigger incremental updates.
pub async fn watch_directory(root: PathBuf, state: AppState) -> Result<()> {
    let (tx, mut rx) = mpsc::channel::<PathBuf>(1000);

    // Set up the watcher
    let tx_clone = tx.clone();
    let root_clone = root.clone();

    let mut watcher = RecommendedWatcher::new(
        move |res: Result<Event, notify::Error>| {
            if let Ok(event) = res {
                for path in event.paths {
                    // Filter to supported files
                    if is_supported_file(&path) {
                        let _ = tx_clone.blocking_send(path);
                    }
                }
            }
        },
        Config::default().with_poll_interval(Duration::from_millis(500)),
    )?;

    watcher.watch(&root, RecursiveMode::Recursive)?;
    info!("Watching {:?} for changes", root);

    // Debounce changes and process in batches
    let mut pending: HashSet<PathBuf> = HashSet::new();
    let debounce_delay = Duration::from_millis(100);

    loop {
        tokio::select! {
            // Receive file change events
            Some(path) = rx.recv() => {
                debug!("File changed: {:?}", path);
                pending.insert(path);
            }

            // Process pending changes after debounce delay
            _ = time::sleep(debounce_delay), if !pending.is_empty() => {
                let changed_files: Vec<PathBuf> = pending.drain().collect();

                if !changed_files.is_empty() {
                    info!("Processing {} file changes", changed_files.len());

                    // Broadcast events for each file
                    for path in &changed_files {
                        if path.exists() {
                            state.broadcast(GraphEvent::FileModified(path.clone()));
                        } else {
                            state.broadcast(GraphEvent::FileDeleted(path.clone()));
                        }
                    }

                    // Perform incremental update
                    let pipeline = BuildPipeline::new(state.clone());
                    match pipeline.incremental_update(&changed_files).await {
                        Ok(result) => {
                            info!(
                                "Incremental update: {} nodes, {} edges in {:?}",
                                result.node_count, result.edge_count, result.duration
                            );
                        }
                        Err(e) => {
                            warn!("Incremental update failed: {}", e);
                        }
                    }
                }
            }
        }
    }
}

/// Check if a file has a supported extension.
fn is_supported_file(path: &PathBuf) -> bool {
    if let Some(ext) = path.extension() {
        if let Some(ext_str) = ext.to_str() {
            return SUPPORTED_EXTENSIONS.contains(&ext_str);
        }
    }
    false
}

/// Check if a path should be ignored (e.g., hidden files, node_modules).
fn should_ignore(path: &PathBuf) -> bool {
    let path_str = path.to_string_lossy();

    // Ignore hidden files and directories
    if path_str.contains("/.") {
        return true;
    }

    // Ignore common non-source directories
    let ignore_patterns = [
        "node_modules",
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "target",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    ];

    for pattern in ignore_patterns {
        if path_str.contains(pattern) {
            return true;
        }
    }

    false
}
