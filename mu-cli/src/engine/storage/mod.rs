//! Storage layer for MU daemon.
//!
//! Provides DuckDB-based storage for the code graph with:
//! - Schema management
//! - Node and edge CRUD operations
//! - Graph loading into petgraph
//! - Database migrations between schema versions

mod edges;
pub mod migrations;
mod mubase;
mod nodes;
pub(crate) mod schema;

pub use edges::Edge;
pub use mubase::MUbase;
pub use nodes::Node;
pub use schema::{NodeType, CROSS_SERVICE_EDGE_TYPES};
