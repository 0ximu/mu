//! Storage layer for MU daemon.
//!
//! Provides DuckDB-based storage for the code graph with:
//! - Schema management
//! - Node and edge CRUD operations
//! - Graph loading into petgraph

mod edges;
mod mubase;
mod nodes;
mod schema;

pub use edges::Edge;
pub use mubase::{GraphEngine, MUbase, QueryResult};
pub use nodes::Node;
pub use schema::{EdgeType, NodeType};
