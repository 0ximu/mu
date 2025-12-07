//! Graph Reasoning Engine powered by petgraph.
//!
//! This module provides high-performance graph algorithms for code dependency analysis.
//! It loads node/edge data from DuckDB into an in-memory petgraph DiGraph and exposes
//! algorithms like cycle detection, impact analysis, and path finding to Python.
//!
//! # Architecture
//!
//! ```text
//! DuckDB (storage) -> GraphEngine (in-memory) -> Python (MUQL/MCP)
//! ```
//!
//! # Key Features
//!
//! - **Edge Type Filtering**: All traversal methods support filtering by relationship type
//!   (imports, calls, inherits) for precise dependency analysis.
//! - **O(V+E) Algorithms**: Kosaraju for cycles, BFS for impact/ancestors
//! - **Bidirectional Traversal**: Find what depends on X (impact) or what X depends on (ancestors)

use petgraph::algo::kosaraju_scc;
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::visit::EdgeRef;
use petgraph::Direction;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet, VecDeque};

/// High-performance graph engine for code dependency analysis.
///
/// Holds an in-memory directed graph where:
/// - Nodes are string IDs (e.g., "mod:src/auth.py", "func:login")
/// - Edges are string types (e.g., "imports", "calls", "inherits")
#[pyclass]
pub struct GraphEngine {
    graph: DiGraph<String, String>,
    node_map: HashMap<String, NodeIndex>,
    reverse_map: HashMap<NodeIndex, String>,
}

#[pymethods]
impl GraphEngine {
    /// Create a new GraphEngine from node IDs and edge tuples.
    ///
    /// # Arguments
    ///
    /// * `nodes` - List of node ID strings
    /// * `edges` - List of (source_id, target_id, edge_type) tuples
    ///
    /// # Example
    ///
    /// ```python
    /// engine = GraphEngine(
    ///     ["a.py", "b.py", "c.py"],
    ///     [("a.py", "b.py", "imports"), ("b.py", "c.py", "imports")]
    /// )
    /// ```
    #[new]
    fn new(nodes: Vec<String>, edges: Vec<(String, String, String)>) -> Self {
        let mut graph = DiGraph::new();
        let mut node_map = HashMap::with_capacity(nodes.len());
        let mut reverse_map = HashMap::with_capacity(nodes.len());

        // Load nodes
        for node_id in nodes {
            let idx = graph.add_node(node_id.clone());
            node_map.insert(node_id.clone(), idx);
            reverse_map.insert(idx, node_id);
        }

        // Load edges (skip if source/target doesn't exist)
        for (src, dst, edge_type) in edges {
            if let (Some(&s), Some(&d)) = (node_map.get(&src), node_map.get(&dst)) {
                graph.add_edge(s, d, edge_type);
            }
        }

        GraphEngine {
            graph,
            node_map,
            reverse_map,
        }
    }

    /// Find all strongly connected components with more than one node (cycles).
    ///
    /// Uses Kosaraju's algorithm: O(V + E)
    ///
    /// # Arguments
    ///
    /// * `edge_types` - Optional list of edge types to consider. If None, all edges are used.
    ///
    /// # Returns
    ///
    /// List of cycles, where each cycle is a list of node IDs.
    ///
    /// # Example
    ///
    /// ```python
    /// cycles = engine.find_cycles()  # All edge types
    /// cycles = engine.find_cycles(["imports"])  # Only import cycles
    /// ```
    #[pyo3(signature = (edge_types=None))]
    fn find_cycles(&self, edge_types: Option<Vec<String>>) -> Vec<Vec<String>> {
        let allowed: Option<HashSet<String>> = edge_types.map(|t| t.into_iter().collect());

        // If filtering, create a filtered graph
        let sccs = if let Some(ref allowed_types) = allowed {
            // Build filtered graph with only allowed edge types
            let mut filtered = DiGraph::new();
            let mut idx_map: HashMap<NodeIndex, NodeIndex> = HashMap::new();

            // Copy all nodes
            for node_idx in self.graph.node_indices() {
                let new_idx = filtered.add_node(self.graph[node_idx].clone());
                idx_map.insert(node_idx, new_idx);
            }

            // Copy only edges with allowed types
            for edge in self.graph.edge_references() {
                if allowed_types.contains(edge.weight()) {
                    let src = idx_map[&edge.source()];
                    let tgt = idx_map[&edge.target()];
                    filtered.add_edge(src, tgt, edge.weight().clone());
                }
            }

            // Find SCCs in filtered graph and map back to original IDs
            kosaraju_scc(&filtered)
                .into_iter()
                .filter(|scc| scc.len() > 1)
                .map(|scc| {
                    scc.into_iter()
                        .map(|idx| filtered[idx].clone())
                        .collect()
                })
                .collect()
        } else {
            // No filtering - use original graph
            kosaraju_scc(&self.graph)
                .into_iter()
                .filter(|scc| scc.len() > 1)
                .map(|scc| {
                    scc.into_iter()
                        .map(|idx| self.reverse_map[&idx].clone())
                        .collect()
                })
                .collect()
        };

        sccs
    }

    /// Find all nodes reachable FROM this node (downstream impact).
    ///
    /// "If I change X, what might break?"
    ///
    /// Uses BFS traversal: O(V + E)
    ///
    /// # Arguments
    ///
    /// * `node_id` - Starting node ID
    /// * `edge_types` - Optional list of edge types to follow
    ///
    /// # Returns
    ///
    /// List of node IDs that are downstream of the given node.
    #[pyo3(signature = (node_id, edge_types=None))]
    fn impact(&self, node_id: &str, edge_types: Option<Vec<String>>) -> Vec<String> {
        self.traverse_bfs(node_id, Direction::Outgoing, edge_types)
    }

    /// Find all nodes that can REACH this node (upstream ancestors).
    ///
    /// "What does X depend on?"
    ///
    /// Uses BFS traversal: O(V + E)
    ///
    /// # Arguments
    ///
    /// * `node_id` - Starting node ID
    /// * `edge_types` - Optional list of edge types to follow
    ///
    /// # Returns
    ///
    /// List of node IDs that are upstream of the given node.
    #[pyo3(signature = (node_id, edge_types=None))]
    fn ancestors(&self, node_id: &str, edge_types: Option<Vec<String>>) -> Vec<String> {
        self.traverse_bfs(node_id, Direction::Incoming, edge_types)
    }

    /// Find shortest path between two nodes.
    ///
    /// Uses BFS (unweighted): O(V + E)
    ///
    /// # Arguments
    ///
    /// * `from_id` - Source node ID
    /// * `to_id` - Target node ID
    /// * `edge_types` - Optional list of edge types to follow
    ///
    /// # Returns
    ///
    /// List of node IDs forming the path, or None if no path exists.
    #[pyo3(signature = (from_id, to_id, edge_types=None))]
    fn shortest_path(
        &self,
        from_id: &str,
        to_id: &str,
        edge_types: Option<Vec<String>>,
    ) -> Option<Vec<String>> {
        let start = *self.node_map.get(from_id)?;
        let end = *self.node_map.get(to_id)?;

        if start == end {
            return Some(vec![from_id.to_string()]);
        }

        let allowed: Option<HashSet<String>> = edge_types.map(|t| t.into_iter().collect());

        // BFS with parent tracking for path reconstruction
        let mut visited: HashSet<NodeIndex> = HashSet::new();
        let mut parent: HashMap<NodeIndex, NodeIndex> = HashMap::new();
        let mut queue = VecDeque::new();

        visited.insert(start);
        queue.push_back(start);

        while let Some(current) = queue.pop_front() {
            for edge in self.graph.edges_directed(current, Direction::Outgoing) {
                // Check edge type filter
                if let Some(ref allowed_types) = allowed {
                    if !allowed_types.contains(edge.weight()) {
                        continue;
                    }
                }

                let neighbor = edge.target();
                if !visited.contains(&neighbor) {
                    visited.insert(neighbor);
                    parent.insert(neighbor, current);

                    if neighbor == end {
                        // Reconstruct path
                        let mut path = vec![self.reverse_map[&end].clone()];
                        let mut curr = end;
                        while let Some(&p) = parent.get(&curr) {
                            path.push(self.reverse_map[&p].clone());
                            curr = p;
                        }
                        path.reverse();
                        return Some(path);
                    }

                    queue.push_back(neighbor);
                }
            }
        }

        None
    }

    /// Find direct neighbors of a node.
    ///
    /// # Arguments
    ///
    /// * `node_id` - Node ID to find neighbors of
    /// * `direction` - "outgoing", "incoming", or "both"
    /// * `depth` - How many levels to traverse (default 1)
    /// * `edge_types` - Optional list of edge types to follow
    ///
    /// # Returns
    ///
    /// List of neighbor node IDs.
    #[pyo3(signature = (node_id, direction="both", depth=1, edge_types=None))]
    fn neighbors(
        &self,
        node_id: &str,
        direction: &str,
        depth: usize,
        edge_types: Option<Vec<String>>,
    ) -> Vec<String> {
        let start = match self.node_map.get(node_id) {
            Some(&idx) => idx,
            None => return vec![],
        };

        let dir = match direction {
            "outgoing" => Some(Direction::Outgoing),
            "incoming" => Some(Direction::Incoming),
            _ => None, // "both"
        };

        let allowed: Option<HashSet<String>> = edge_types.map(|t| t.into_iter().collect());

        let mut result: HashSet<NodeIndex> = HashSet::new();
        let mut current_level: HashSet<NodeIndex> = HashSet::new();
        current_level.insert(start);

        for _ in 0..depth {
            let mut next_level: HashSet<NodeIndex> = HashSet::new();

            for &node in &current_level {
                let directions: Vec<Direction> = match dir {
                    Some(d) => vec![d],
                    None => vec![Direction::Outgoing, Direction::Incoming],
                };

                for d in directions {
                    for edge in self.graph.edges_directed(node, d) {
                        // Check edge type filter
                        if let Some(ref allowed_types) = allowed {
                            if !allowed_types.contains(edge.weight()) {
                                continue;
                            }
                        }

                        let neighbor = if d == Direction::Outgoing {
                            edge.target()
                        } else {
                            edge.source()
                        };

                        if neighbor != start && !result.contains(&neighbor) {
                            next_level.insert(neighbor);
                        }
                    }
                }
            }

            result.extend(&next_level);
            current_level = next_level;
        }

        result
            .into_iter()
            .map(|idx| self.reverse_map[&idx].clone())
            .collect()
    }

    /// Get the number of nodes in the graph.
    fn node_count(&self) -> usize {
        self.graph.node_count()
    }

    /// Get the number of edges in the graph.
    fn edge_count(&self) -> usize {
        self.graph.edge_count()
    }

    /// Check if a node exists in the graph.
    fn has_node(&self, node_id: &str) -> bool {
        self.node_map.contains_key(node_id)
    }

    /// Get all unique edge types in the graph.
    fn edge_types(&self) -> Vec<String> {
        let types: HashSet<&String> = self.graph.edge_weights().collect();
        types.into_iter().cloned().collect()
    }
}

impl GraphEngine {
    /// Internal BFS traversal with direction and edge type filtering.
    fn traverse_bfs(
        &self,
        node_id: &str,
        direction: Direction,
        edge_types: Option<Vec<String>>,
    ) -> Vec<String> {
        let start = match self.node_map.get(node_id) {
            Some(&idx) => idx,
            None => return vec![],
        };

        let allowed: Option<HashSet<String>> = edge_types.map(|t| t.into_iter().collect());

        let mut visited: HashSet<NodeIndex> = HashSet::new();
        let mut result = Vec::new();
        let mut queue = VecDeque::new();

        visited.insert(start);
        queue.push_back(start);

        while let Some(current) = queue.pop_front() {
            for edge in self.graph.edges_directed(current, direction) {
                // Check edge type filter
                if let Some(ref allowed_types) = allowed {
                    if !allowed_types.contains(edge.weight()) {
                        continue;
                    }
                }

                let neighbor = if direction == Direction::Outgoing {
                    edge.target()
                } else {
                    edge.source()
                };

                if !visited.contains(&neighbor) {
                    visited.insert(neighbor);
                    result.push(self.reverse_map[&neighbor].clone());
                    queue.push_back(neighbor);
                }
            }
        }

        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_graph() -> GraphEngine {
        // Create a graph: a -> b -> c -> a (cycle via imports)
        //                 b -> d (no cycle, calls relationship)
        let nodes = vec![
            "a".to_string(),
            "b".to_string(),
            "c".to_string(),
            "d".to_string(),
        ];
        let edges = vec![
            ("a".to_string(), "b".to_string(), "imports".to_string()),
            ("b".to_string(), "c".to_string(), "imports".to_string()),
            ("c".to_string(), "a".to_string(), "imports".to_string()),
            ("b".to_string(), "d".to_string(), "calls".to_string()),
        ];
        GraphEngine::new(nodes, edges)
    }

    #[test]
    fn test_cycle_detection_all_edges() {
        let engine = create_test_graph();
        let cycles = engine.find_cycles(None);

        assert_eq!(cycles.len(), 1);
        let cycle = &cycles[0];
        assert_eq!(cycle.len(), 3);
        assert!(cycle.contains(&"a".to_string()));
        assert!(cycle.contains(&"b".to_string()));
        assert!(cycle.contains(&"c".to_string()));
        assert!(!cycle.contains(&"d".to_string()));
    }

    #[test]
    fn test_cycle_detection_filtered() {
        let engine = create_test_graph();

        // Should find cycle with imports
        let cycles = engine.find_cycles(Some(vec!["imports".to_string()]));
        assert_eq!(cycles.len(), 1);

        // Should find no cycle with only calls
        let cycles = engine.find_cycles(Some(vec!["calls".to_string()]));
        assert_eq!(cycles.len(), 0);
    }

    #[test]
    fn test_no_cycles() {
        let nodes = vec!["a".to_string(), "b".to_string(), "c".to_string()];
        let edges = vec![
            ("a".to_string(), "b".to_string(), "imports".to_string()),
            ("b".to_string(), "c".to_string(), "imports".to_string()),
        ];
        let engine = GraphEngine::new(nodes, edges);

        let cycles = engine.find_cycles(None);
        assert!(cycles.is_empty());
    }

    #[test]
    fn test_impact_analysis() {
        let engine = create_test_graph();

        // Impact of 'a' should reach b, c (and back to a via cycle, but we start from a)
        let impact = engine.impact("a", None);
        assert!(impact.contains(&"b".to_string()));
        assert!(impact.contains(&"c".to_string()));
        assert!(impact.contains(&"d".to_string()));
    }

    #[test]
    fn test_impact_filtered() {
        let engine = create_test_graph();

        // Impact of 'b' with only imports should not include 'd'
        let impact = engine.impact("b", Some(vec!["imports".to_string()]));
        assert!(impact.contains(&"c".to_string()));
        assert!(!impact.contains(&"d".to_string()));

        // Impact of 'b' with only calls should only include 'd'
        let impact = engine.impact("b", Some(vec!["calls".to_string()]));
        assert!(!impact.contains(&"c".to_string()));
        assert!(impact.contains(&"d".to_string()));
    }

    #[test]
    fn test_ancestors() {
        let engine = create_test_graph();

        // Ancestors of 'd' should be 'b' (and transitively a, c due to cycle)
        let ancestors = engine.ancestors("d", None);
        assert!(ancestors.contains(&"b".to_string()));
    }

    #[test]
    fn test_shortest_path() {
        let nodes = vec![
            "a".to_string(),
            "b".to_string(),
            "c".to_string(),
            "d".to_string(),
        ];
        let edges = vec![
            ("a".to_string(), "b".to_string(), "imports".to_string()),
            ("b".to_string(), "c".to_string(), "imports".to_string()),
            ("c".to_string(), "d".to_string(), "imports".to_string()),
            ("a".to_string(), "d".to_string(), "calls".to_string()), // Shortcut
        ];
        let engine = GraphEngine::new(nodes, edges);

        // Shortest path a->d should be direct (a, d) via calls
        let path = engine.shortest_path("a", "d", None);
        assert!(path.is_some());
        let path = path.unwrap();
        assert_eq!(path.len(), 2);
        assert_eq!(path[0], "a");
        assert_eq!(path[1], "d");

        // With only imports, path should be longer
        let path = engine.shortest_path("a", "d", Some(vec!["imports".to_string()]));
        assert!(path.is_some());
        let path = path.unwrap();
        assert_eq!(path.len(), 4);
    }

    #[test]
    fn test_neighbors() {
        let engine = create_test_graph();

        // Outgoing neighbors of 'b' at depth 1
        let neighbors = engine.neighbors("b", "outgoing", 1, None);
        assert!(neighbors.contains(&"c".to_string()));
        assert!(neighbors.contains(&"d".to_string()));
        assert!(!neighbors.contains(&"a".to_string()));

        // Incoming neighbors of 'b' at depth 1
        let neighbors = engine.neighbors("b", "incoming", 1, None);
        assert!(neighbors.contains(&"a".to_string()));
        assert!(!neighbors.contains(&"c".to_string()));
    }

    #[test]
    fn test_node_count() {
        let engine = create_test_graph();
        assert_eq!(engine.node_count(), 4);
        assert_eq!(engine.edge_count(), 4);
    }

    #[test]
    fn test_has_node() {
        let engine = create_test_graph();
        assert!(engine.has_node("a"));
        assert!(!engine.has_node("nonexistent"));
    }

    #[test]
    fn test_edge_types() {
        let engine = create_test_graph();
        let types = engine.edge_types();
        assert!(types.contains(&"imports".to_string()));
        assert!(types.contains(&"calls".to_string()));
    }
}
