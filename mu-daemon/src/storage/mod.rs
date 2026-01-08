//! Storage layer for MU daemon.
//!
//! Provides DuckDB-based storage for the code graph with:
//! - Schema management
//! - Node and edge CRUD operations
//! - Graph loading into petgraph
//! - Embedding storage and vector search
//! - Database migrations between schema versions

mod edges;
mod embeddings;
mod graph_engine;
pub mod migrations;
mod mubase;
mod nodes;
mod schema;

pub use edges::Edge;
pub use embeddings::{EmbeddingStats, VectorSearchResult};
pub use graph_engine::GraphEngine;
pub use mubase::{AccessMode, MUbase, QueryResult};
pub use nodes::Node;
pub use schema::{EdgeType, NodeType};
