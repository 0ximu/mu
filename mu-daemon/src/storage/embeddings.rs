//! Embedding storage types and utilities.

use serde::Serialize;

/// Result of a vector similarity search.
#[derive(Debug, Clone, Serialize)]
pub struct VectorSearchResult {
    /// Node ID that matched
    pub node_id: String,
    /// Cosine similarity score (0.0 to 1.0)
    pub similarity: f32,
    /// Node name
    pub name: String,
    /// Node type (module, class, function, external)
    pub node_type: String,
    /// File path (if available)
    pub file_path: Option<String>,
    /// Qualified name (if available)
    pub qualified_name: Option<String>,
}

/// Statistics about embeddings coverage.
#[derive(Debug, Clone, Serialize)]
pub struct EmbeddingStats {
    /// Total number of nodes in the database
    pub total_nodes: usize,
    /// Number of nodes that have embeddings
    pub nodes_with_embeddings: usize,
    /// Model used for embeddings (if any)
    pub model: Option<String>,
    /// Coverage percentage (nodes_with_embeddings / total_nodes * 100)
    pub coverage_percent: f32,
}

// Note: cosine_similarity() removed in v1.1.0 - now computed in-database
// using DuckDB's native array_cosine_similarity() function
