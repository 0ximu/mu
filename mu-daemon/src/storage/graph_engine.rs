//! In-memory graph engine for graph operations.

use std::collections::HashMap;

/// Graph engine wrapper for in-memory graph operations.
pub struct GraphEngine {
    nodes: Vec<String>,
    edges: Vec<(String, String, String)>,
    node_map: HashMap<String, usize>,
}

impl GraphEngine {
    /// Create a new empty graph engine.
    pub fn new() -> Self {
        Self {
            nodes: Vec::new(),
            edges: Vec::new(),
            node_map: HashMap::new(),
        }
    }

    /// Create from nodes and edges.
    pub fn from_data(nodes: Vec<String>, edges: Vec<(String, String, String)>) -> Self {
        let mut node_map = HashMap::new();
        for (i, node) in nodes.iter().enumerate() {
            node_map.insert(node.clone(), i);
        }
        Self {
            nodes,
            edges,
            node_map,
        }
    }

    /// Get the number of nodes.
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }

    /// Get the number of edges.
    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }

    /// Check if a node exists.
    pub fn has_node(&self, node_id: &str) -> bool {
        self.node_map.contains_key(node_id)
    }

    /// Get all nodes.
    pub fn get_nodes(&self) -> &[String] {
        &self.nodes
    }

    /// Get all edges as (source, target, type) tuples.
    pub fn get_edges(&self) -> &[(String, String, String)] {
        &self.edges
    }
}

impl Default for GraphEngine {
    fn default() -> Self {
        Self::new()
    }
}
