//! Graph-aware reranking for vector search results.
//!
//! Combines cosine similarity with graph structure signals to surface
//! results that are both semantically relevant and structurally important.

use crate::storage::{GraphEngine, VectorSearchResult};
use std::collections::{HashMap, HashSet, VecDeque};

/// Configuration for graph-aware reranking.
pub struct RerankConfig {
    /// Weight for vector similarity score (alpha).
    pub similarity_weight: f32,
    /// Weight for graph structure score (beta).
    pub graph_weight: f32,
    /// Number of candidates to fetch from vector search before reranking.
    pub candidate_pool: usize,
    /// Number of results to return after reranking.
    pub final_count: usize,
}

impl Default for RerankConfig {
    fn default() -> Self {
        Self {
            similarity_weight: 0.6,
            graph_weight: 0.4,
            candidate_pool: 50,
            final_count: 10,
        }
    }
}

/// Rerank vector search candidates using graph topology signals.
///
/// Final score = alpha * similarity + beta * graph_score
/// where graph_score = (connectivity + centrality + cluster_relevance) / 3
pub fn rerank(
    candidates: Vec<VectorSearchResult>,
    graph: &GraphEngine,
    config: &RerankConfig,
) -> Vec<VectorSearchResult> {
    if candidates.is_empty() {
        return candidates;
    }

    // Build adjacency lists from graph edges for fast lookups
    let mut outgoing: HashMap<&str, Vec<&str>> = HashMap::new();
    let mut incoming: HashMap<&str, Vec<&str>> = HashMap::new();
    for (src, tgt, _) in graph.get_edges() {
        outgoing.entry(src.as_str()).or_default().push(tgt.as_str());
        incoming.entry(tgt.as_str()).or_default().push(src.as_str());
    }

    // Candidate node IDs for cluster relevance (owned to avoid borrow issues)
    let candidate_ids: HashSet<String> = candidates.iter().map(|c| c.node_id.clone()).collect();
    let candidate_ids_ref: HashSet<&str> = candidate_ids.iter().map(|s| s.as_str()).collect();

    // Score each candidate
    let mut scored: Vec<(f32, VectorSearchResult)> = candidates
        .into_iter()
        .map(|c| {
            let graph_score = if graph.has_node(&c.node_id) {
                let connectivity = compute_connectivity(&c.node_id, &outgoing, &incoming);
                let centrality = compute_centrality(&c.node_id, &outgoing, &incoming);
                let cluster =
                    compute_cluster_relevance(&c.node_id, &candidate_ids_ref, &outgoing, &incoming);
                (connectivity + centrality + cluster) / 3.0
            } else {
                0.0
            };

            let final_score =
                config.similarity_weight * c.similarity + config.graph_weight * graph_score;
            (final_score, c)
        })
        .collect();

    // Sort by final score descending
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

    // Return top final_count results, updating similarity to the blended score
    scored
        .into_iter()
        .take(config.final_count)
        .map(|(score, mut result)| {
            result.similarity = score;
            result
        })
        .collect()
}

/// Connectivity = (in_degree + out_degree) / 20.0, capped at 1.0
fn compute_connectivity(
    node_id: &str,
    outgoing: &HashMap<&str, Vec<&str>>,
    incoming: &HashMap<&str, Vec<&str>>,
) -> f32 {
    let out_degree = outgoing.get(node_id).map_or(0, |v| v.len());
    let in_degree = incoming.get(node_id).map_or(0, |v| v.len());
    ((out_degree + in_degree) as f32 / 20.0).min(1.0)
}

/// Centrality approximation using second-order neighbor count.
/// Counts total unique neighbors at distance 1 and 2, normalized.
fn compute_centrality(
    node_id: &str,
    outgoing: &HashMap<&str, Vec<&str>>,
    incoming: &HashMap<&str, Vec<&str>>,
) -> f32 {
    let mut visited = HashSet::new();
    visited.insert(node_id);

    // Collect direct neighbors (distance 1)
    let mut neighbors_1 = Vec::new();
    if let Some(out) = outgoing.get(node_id) {
        for &n in out {
            if visited.insert(n) {
                neighbors_1.push(n);
            }
        }
    }
    if let Some(inc) = incoming.get(node_id) {
        for &n in inc {
            if visited.insert(n) {
                neighbors_1.push(n);
            }
        }
    }

    // Collect distance-2 neighbors
    for n1 in &neighbors_1 {
        if let Some(out) = outgoing.get(n1) {
            for &n in out {
                visited.insert(n);
            }
        }
        if let Some(inc) = incoming.get(n1) {
            for &n in inc {
                visited.insert(n);
            }
        }
    }

    // visited includes the node itself, subtract 1
    let total_reachable = visited.len().saturating_sub(1);
    // Normalize: 50 reachable nodes = 1.0
    (total_reachable as f32 / 50.0).min(1.0)
}

/// Cluster relevance = (# other candidates reachable within 2 hops) / 5.0, capped at 1.0
fn compute_cluster_relevance(
    node_id: &str,
    candidate_ids: &HashSet<&str>,
    outgoing: &HashMap<&str, Vec<&str>>,
    incoming: &HashMap<&str, Vec<&str>>,
) -> f32 {
    // BFS up to depth 2, count how many other candidates we find
    let mut visited = HashSet::new();
    visited.insert(node_id);

    let mut queue = VecDeque::new();
    queue.push_back((node_id, 0u8));

    let mut candidate_count: usize = 0;

    while let Some((current, depth)) = queue.pop_front() {
        if depth >= 2 {
            continue;
        }

        // Explore outgoing
        if let Some(out) = outgoing.get(current) {
            for &neighbor in out {
                if visited.insert(neighbor) {
                    if candidate_ids.contains(neighbor) {
                        candidate_count += 1;
                    }
                    queue.push_back((neighbor, depth + 1));
                }
            }
        }

        // Explore incoming
        if let Some(inc) = incoming.get(current) {
            for &neighbor in inc {
                if visited.insert(neighbor) {
                    if candidate_ids.contains(neighbor) {
                        candidate_count += 1;
                    }
                    queue.push_back((neighbor, depth + 1));
                }
            }
        }
    }

    (candidate_count as f32 / 5.0).min(1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_candidate(node_id: &str, similarity: f32) -> VectorSearchResult {
        VectorSearchResult {
            node_id: node_id.to_string(),
            similarity,
            name: node_id.to_string(),
            node_type: "function".to_string(),
            file_path: Some("test.py".to_string()),
            qualified_name: None,
        }
    }

    #[test]
    fn test_default_config() {
        let config = RerankConfig::default();
        assert!((config.similarity_weight - 0.6).abs() < f32::EPSILON);
        assert!((config.graph_weight - 0.4).abs() < f32::EPSILON);
        assert_eq!(config.candidate_pool, 50);
        assert_eq!(config.final_count, 10);
    }

    #[test]
    fn test_rerank_empty() {
        let graph = GraphEngine::new();
        let config = RerankConfig::default();
        let result = rerank(vec![], &graph, &config);
        assert!(result.is_empty());
    }

    #[test]
    fn test_rerank_promotes_connected_nodes() {
        // Build a graph where node "hub" has many connections
        let nodes = vec![
            "hub".to_string(),
            "a".to_string(),
            "b".to_string(),
            "c".to_string(),
            "d".to_string(),
            "e".to_string(),
            "leaf".to_string(),
        ];
        let edges = vec![
            ("hub".to_string(), "a".to_string(), "calls".to_string()),
            ("hub".to_string(), "b".to_string(), "calls".to_string()),
            ("hub".to_string(), "c".to_string(), "calls".to_string()),
            ("hub".to_string(), "d".to_string(), "calls".to_string()),
            ("hub".to_string(), "e".to_string(), "calls".to_string()),
            ("a".to_string(), "hub".to_string(), "calls".to_string()),
            ("b".to_string(), "hub".to_string(), "calls".to_string()),
            ("c".to_string(), "hub".to_string(), "calls".to_string()),
        ];
        let graph = GraphEngine::from_data(nodes, edges);

        // "leaf" has higher similarity but no connections
        // "hub" has lower similarity but is a highly connected node
        let candidates = vec![
            make_candidate("leaf", 0.85),
            make_candidate("hub", 0.75),
            make_candidate("a", 0.60),
        ];

        let config = RerankConfig {
            similarity_weight: 0.4,
            graph_weight: 0.6,
            candidate_pool: 50,
            final_count: 3,
        };

        let results = rerank(candidates, &graph, &config);
        assert_eq!(results.len(), 3);

        // Hub should be promoted above leaf due to graph signals
        assert_eq!(results[0].node_id, "hub");
    }

    #[test]
    fn test_rerank_respects_final_count() {
        let graph = GraphEngine::new();
        let candidates: Vec<VectorSearchResult> = (0..20)
            .map(|i| make_candidate(&format!("node_{}", i), 1.0 - (i as f32 * 0.01)))
            .collect();

        let config = RerankConfig {
            final_count: 5,
            ..RerankConfig::default()
        };

        let results = rerank(candidates, &graph, &config);
        assert_eq!(results.len(), 5);
    }

    #[test]
    fn test_rerank_nodes_not_in_graph() {
        // Candidates that aren't in the graph should get graph_score = 0
        let graph = GraphEngine::from_data(vec!["other".to_string()], vec![]);

        let candidates = vec![make_candidate("missing_node", 0.9)];

        let config = RerankConfig::default();
        let results = rerank(candidates, &graph, &config);
        assert_eq!(results.len(), 1);
        // Score should be just similarity * weight: 0.6 * 0.9 = 0.54
        assert!((results[0].similarity - 0.54).abs() < 0.01);
    }

    #[test]
    fn test_cluster_relevance_boosts_co_occurring_candidates() {
        // When multiple candidates are close in the graph, cluster relevance should boost them
        let nodes: Vec<String> = (0..10).map(|i| format!("n{}", i)).collect();
        let edges = vec![
            ("n0".to_string(), "n1".to_string(), "calls".to_string()),
            ("n1".to_string(), "n2".to_string(), "calls".to_string()),
            ("n0".to_string(), "n3".to_string(), "calls".to_string()),
            // n5 is isolated
        ];
        let graph = GraphEngine::from_data(nodes, edges);

        // n0, n1, n2 are clustered together; n5 is isolated
        let candidates = vec![
            make_candidate("n5", 0.90),
            make_candidate("n0", 0.80),
            make_candidate("n1", 0.75),
            make_candidate("n2", 0.70),
        ];

        let config = RerankConfig {
            similarity_weight: 0.5,
            graph_weight: 0.5,
            candidate_pool: 50,
            final_count: 4,
        };

        let results = rerank(candidates, &graph, &config);
        // n0 should be at or near the top due to cluster + connectivity signals
        assert_eq!(results[0].node_id, "n0");
    }

    #[test]
    fn test_connectivity_score() {
        let mut outgoing: HashMap<&str, Vec<&str>> = HashMap::new();
        let mut incoming: HashMap<&str, Vec<&str>> = HashMap::new();

        outgoing.insert("a", vec!["b", "c"]);
        incoming.insert("a", vec!["d"]);

        // (2 out + 1 in) / 20 = 0.15
        let score = compute_connectivity("a", &outgoing, &incoming);
        assert!((score - 0.15).abs() < f32::EPSILON);
    }

    #[test]
    fn test_connectivity_capped_at_one() {
        let mut outgoing: HashMap<&str, Vec<&str>> = HashMap::new();
        let incoming: HashMap<&str, Vec<&str>> = HashMap::new();

        // 25 outgoing edges
        outgoing.insert("hub", (0..25).map(|_| "x").collect());

        let score = compute_connectivity("hub", &outgoing, &incoming);
        assert!((score - 1.0).abs() < f32::EPSILON);
    }
}
