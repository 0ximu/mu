//! MU Storage Library - Core components for code intelligence.
//!
//! This library provides:
//! - Storage layer (DuckDB-based graph database)
//! - Embedding model trait for semantic search

pub mod embeddings;
pub mod storage;

/// Get the version of mu-daemon.
pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}
