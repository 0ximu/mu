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

/// Compute cosine similarity between two vectors.
/// Assumes query_magnitude is pre-computed for efficiency.
pub fn cosine_similarity(query: &[f32], stored: &[f32], query_magnitude: f32) -> f32 {
    if query.len() != stored.len() || query_magnitude == 0.0 {
        return 0.0;
    }

    let mut dot_product = 0.0f32;
    let mut stored_magnitude_sq = 0.0f32;

    for (q, s) in query.iter().zip(stored.iter()) {
        dot_product += q * s;
        stored_magnitude_sq += s * s;
    }

    let stored_magnitude = stored_magnitude_sq.sqrt();
    if stored_magnitude == 0.0 {
        return 0.0;
    }

    dot_product / (query_magnitude * stored_magnitude)
}
