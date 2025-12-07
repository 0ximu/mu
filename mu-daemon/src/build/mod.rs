//! Build pipeline for constructing the code graph.
//!
//! Orchestrates:
//! 1. Scanning files (uses mu-core scanner)
//! 2. Parsing files (uses mu-core parser)
//! 3. Converting AST to nodes/edges
//! 4. Writing to DuckDB
//! 5. Loading into in-memory graph

mod pipeline;

pub use pipeline::{BuildPipeline, BuildResult};
