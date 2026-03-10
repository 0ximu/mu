//! Weighted PageRank for code graphs.
//!
//! Computes importance scores for nodes in a code dependency graph,
//! using edge-type-aware weights so that `calls` edges matter more
//! than structural `contains` edges.

use std::collections::HashMap;

/// Configuration for PageRank computation.
pub struct PageRankConfig {
    pub damping: f32,
    pub max_iterations: u32,
    pub tolerance: f64,
}

impl Default for PageRankConfig {
    fn default() -> Self {
        Self {
            damping: 0.85,
            max_iterations: 100,
            tolerance: 1e-6,
        }
    }
}

/// Get the weight for an edge type.
fn edge_weight(edge_type: &str) -> f32 {
    match edge_type {
        // Soft edges: zero weight in PageRank (orphan detection only)
        "macro_dispatch" | "trait_impl" | "di_registration" | "decorator_dispatch" => 0.0,
        "calls" => 1.0,
        "imports" => 0.9,
        "inherits" => 0.8,
        "uses_contract" => 0.7,
        "calls_http" => 0.7,
        "publishes" => 0.6,
        "subscribes" => 0.6,
        "uses" => 0.5,
        "contains" => 0.1,
        _ => 0.5,
    }
}

/// Compute PageRank scores for all nodes in the graph.
///
/// Returns a HashMap of node_id -> importance_score (normalized to \[0, 1\]).
pub fn compute_pagerank(
    nodes: &[String],
    edges: &[(String, String, String)],
    config: &PageRankConfig,
) -> HashMap<String, f32> {
    let n = nodes.len();
    if n == 0 {
        return HashMap::new();
    }

    // Build node index lookup.
    let idx: HashMap<&str, usize> = nodes
        .iter()
        .enumerate()
        .map(|(i, id)| (id.as_str(), i))
        .collect();

    // Build adjacency: for each source node, collect (target_idx, weight).
    // Also accumulate weighted out-degree per source.
    let mut out_edges: Vec<Vec<(usize, f32)>> = vec![Vec::new(); n];
    let mut weighted_out_degree: Vec<f32> = vec![0.0; n];

    for (src, tgt, etype) in edges {
        let Some(&si) = idx.get(src.as_str()) else {
            continue;
        };
        let Some(&ti) = idx.get(tgt.as_str()) else {
            continue;
        };
        let w = edge_weight(etype);
        out_edges[si].push((ti, w));
        weighted_out_degree[si] += w;
    }

    let d = config.damping;
    let base = (1.0 - d) / n as f32;
    let init = 1.0 / n as f32;

    let mut scores: Vec<f32> = vec![init; n];
    let mut new_scores: Vec<f32> = vec![0.0; n];

    for _iter in 0..config.max_iterations {
        // Sum up dangling node contribution (nodes with no outgoing edges).
        let dangling_sum: f32 = scores
            .iter()
            .enumerate()
            .filter(|&(i, _)| weighted_out_degree[i] == 0.0)
            .map(|(_, &s)| s)
            .sum();
        let dangling_add = d * dangling_sum / n as f32;

        // Reset new scores to base + dangling.
        for s in new_scores.iter_mut() {
            *s = base + dangling_add;
        }

        // Accumulate incoming contributions.
        for (j, neighbors) in out_edges.iter().enumerate() {
            if weighted_out_degree[j] == 0.0 {
                continue;
            }
            let share = scores[j] / weighted_out_degree[j];
            for &(target, w) in neighbors {
                new_scores[target] += d * share * w;
            }
        }

        // Convergence check (L1 norm).
        let diff: f64 = scores
            .iter()
            .zip(new_scores.iter())
            .map(|(&a, &b)| (a as f64 - b as f64).abs())
            .sum();

        std::mem::swap(&mut scores, &mut new_scores);

        if diff < config.tolerance {
            break;
        }
    }

    // Normalize to [0, 1].
    let max_score = scores.iter().cloned().fold(0.0_f32, f32::max);
    if max_score > 0.0 {
        for s in scores.iter_mut() {
            *s /= max_score;
        }
    }

    nodes
        .iter()
        .enumerate()
        .map(|(i, id)| (id.clone(), scores[i]))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn edge(src: &str, tgt: &str, etype: &str) -> (String, String, String) {
        (src.to_string(), tgt.to_string(), etype.to_string())
    }

    fn nodes(ids: &[&str]) -> Vec<String> {
        ids.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn empty_graph() {
        let result = compute_pagerank(&[], &[], &PageRankConfig::default());
        assert!(result.is_empty());
    }

    #[test]
    fn single_node() {
        let n = nodes(&["A"]);
        let result = compute_pagerank(&n, &[], &PageRankConfig::default());
        assert_eq!(result.len(), 1);
        assert!((result["A"] - 1.0).abs() < 1e-5, "single node should be 1.0");
    }

    #[test]
    fn chain_a_b_c() {
        // A→B→C: C should rank highest (most transitively linked-to).
        let n = nodes(&["A", "B", "C"]);
        let e = vec![edge("A", "B", "calls"), edge("B", "C", "calls")];
        let result = compute_pagerank(&n, &e, &PageRankConfig::default());

        assert!(
            result["C"] > result["B"],
            "C ({}) should outrank B ({})",
            result["C"],
            result["B"]
        );
        assert!(
            result["B"] > result["A"],
            "B ({}) should outrank A ({})",
            result["B"],
            result["A"]
        );
    }

    #[test]
    fn star_topology() {
        // A→B, A→C, A→D: leaves should have similar high scores, A lower.
        let n = nodes(&["A", "B", "C", "D"]);
        let e = vec![
            edge("A", "B", "calls"),
            edge("A", "C", "calls"),
            edge("A", "D", "calls"),
        ];
        let result = compute_pagerank(&n, &e, &PageRankConfig::default());

        // B, C, D should be close to each other.
        let spread = (result["B"] - result["C"])
            .abs()
            .max((result["C"] - result["D"]).abs());
        assert!(
            spread < 0.01,
            "leaf scores should be similar, spread={}",
            spread
        );

        // All leaves should outrank A.
        assert!(result["B"] > result["A"], "B should outrank A");
        assert!(result["C"] > result["A"], "C should outrank A");
        assert!(result["D"] > result["A"], "D should outrank A");
    }

    #[test]
    fn contains_less_than_calls() {
        // A→B via calls, A→C via contains.
        // B should rank higher than C because calls has a higher weight.
        let n = nodes(&["A", "B", "C"]);
        let e = vec![edge("A", "B", "calls"), edge("A", "C", "contains")];
        let result = compute_pagerank(&n, &e, &PageRankConfig::default());

        assert!(
            result["B"] > result["C"],
            "calls target B ({}) should outrank contains target C ({})",
            result["B"],
            result["C"]
        );
    }

    #[test]
    fn scores_normalized_zero_to_one() {
        let n = nodes(&["A", "B", "C", "D"]);
        let e = vec![
            edge("A", "B", "calls"),
            edge("B", "C", "imports"),
            edge("C", "D", "uses"),
            edge("D", "A", "inherits"),
        ];
        let result = compute_pagerank(&n, &e, &PageRankConfig::default());

        let max = result.values().cloned().fold(0.0_f32, f32::max);
        let min = result.values().cloned().fold(f32::MAX, f32::min);

        assert!(
            (max - 1.0).abs() < 1e-5,
            "max should be ~1.0, got {}",
            max
        );
        assert!(min >= 0.0, "min should be >= 0, got {}", min);
    }

    #[test]
    fn soft_edges_zero_weight() {
        // A→B via calls, A→C via macro_dispatch (soft edge).
        // C should not get any PageRank boost from the soft edge.
        let n = nodes(&["A", "B", "C"]);
        let e = vec![edge("A", "B", "calls"), edge("A", "C", "macro_dispatch")];
        let result = compute_pagerank(&n, &e, &PageRankConfig::default());

        assert!(
            result["B"] > result["C"],
            "calls target B ({}) should outrank soft-edge target C ({})",
            result["B"],
            result["C"]
        );
    }

    #[test]
    fn convergence_within_limit() {
        // A larger graph to make sure we converge in time.
        let n = nodes(&["A", "B", "C", "D", "E"]);
        let e = vec![
            edge("A", "B", "calls"),
            edge("B", "C", "calls"),
            edge("C", "D", "calls"),
            edge("D", "E", "calls"),
            edge("E", "A", "calls"),
            edge("A", "C", "imports"),
            edge("B", "D", "uses"),
        ];

        let config = PageRankConfig {
            max_iterations: 100,
            ..Default::default()
        };
        let result = compute_pagerank(&n, &e, &config);

        // Should produce scores for all 5 nodes.
        assert_eq!(result.len(), 5);
        // All scores should be > 0 (cyclic graph, everyone gets some rank).
        for (id, score) in &result {
            assert!(*score > 0.0, "node {} should have positive score", id);
        }
    }
}
