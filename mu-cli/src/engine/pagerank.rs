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

/// Metadata needed for composite scoring (extracted from nodes table).
pub struct NodeMeta {
    pub complexity: u32,
    pub loc: u32,
    pub is_public: bool,
    pub is_test: bool,
    pub in_degree: u32,
}

/// Compute composite importance scores combining PageRank, complexity, LOC, and visibility.
///
/// Formula:
///   importance = (0.40 * pagerank + 0.30 * complexity + 0.20 * loc + 0.10 * public_boost)
///                * trivial_penalty * test_penalty
///
/// Key design choices for scale independence:
/// - PageRank normalized to [0,1] within this codebase (max PR -> 1.0)
/// - Complexity normalized to codebase max (not P95)
/// - LOC: sigmoid saturation at 200 lines
/// - Public boost: 1.0 if public, 0.8 if private (not zero)
/// - No final [0,1] normalization -- scores spread naturally
pub fn compute_composite_importance(
    pagerank_scores: &HashMap<String, f32>,
    node_metadata: &[(String, NodeMeta)],
) -> HashMap<String, f32> {
    if node_metadata.is_empty() {
        return HashMap::new();
    }

    // Use max complexity (not P95) for normalization -- avoids compressing high-complexity outliers
    let max_complexity = node_metadata
        .iter()
        .map(|(_, m)| m.complexity as f32)
        .fold(0.0_f32, f32::max)
        .max(1.0);

    // Normalize PageRank to [0, 1] within this codebase
    let pr_max = pagerank_scores
        .values()
        .cloned()
        .fold(0.0_f32, f32::max)
        .max(f32::EPSILON);

    let mut scores: HashMap<String, f32> = HashMap::with_capacity(node_metadata.len());

    for (node_id, meta) in node_metadata {
        let pr = pagerank_scores
            .get(node_id)
            .copied()
            .unwrap_or(0.0)
            / pr_max;

        let complexity_norm = (meta.complexity as f32 / max_complexity).min(1.0);
        let loc_norm = (meta.loc as f32).min(200.0) / 200.0;
        let public_boost = if meta.is_public { 1.0_f32 } else { 0.8 };

        let mut score = 0.40 * pr
            + 0.30 * complexity_norm
            + 0.20 * loc_norm
            + 0.10 * public_boost;

        // Dampen trivial high-fan-in utilities (tiny body + many callers = helper, not core)
        if meta.loc < 10 && meta.in_degree > 20 {
            score *= 0.3;
        }

        // Test file penalty
        if meta.is_test {
            score *= 0.5;
        }

        scores.insert(node_id.clone(), score);
    }

    scores
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

    // ===== Composite importance tests =====

    fn meta(complexity: u32, loc: u32, is_public: bool, is_test: bool) -> NodeMeta {
        NodeMeta {
            complexity,
            loc,
            is_public,
            is_test,
            in_degree: 0,
        }
    }

    fn meta_with_indegree(complexity: u32, loc: u32, is_public: bool, is_test: bool, in_degree: u32) -> NodeMeta {
        NodeMeta {
            complexity,
            loc,
            is_public,
            is_test,
            in_degree,
        }
    }

    #[test]
    fn composite_high_complexity_beats_trivial_utility() {
        // Simulate: "pack_context" has high complexity, large body, moderate PageRank
        //           "get_node_text" has low complexity, small body, high PageRank
        let mut pr = HashMap::new();
        pr.insert("pack_context".to_string(), 0.5);
        pr.insert("get_node_text".to_string(), 1.0);

        let metadata = vec![
            ("pack_context".to_string(), meta(15, 150, true, false)),
            ("get_node_text".to_string(), meta(1, 7, true, false)),
        ];

        let scores = compute_composite_importance(&pr, &metadata);

        assert!(
            scores["pack_context"] > scores["get_node_text"],
            "pack_context ({}) should outrank get_node_text ({}) despite lower PageRank",
            scores["pack_context"],
            scores["get_node_text"],
        );
    }

    #[test]
    fn composite_test_file_penalty() {
        let mut pr = HashMap::new();
        pr.insert("prod_fn".to_string(), 0.5);
        pr.insert("test_fn".to_string(), 0.5);

        let metadata = vec![
            ("prod_fn".to_string(), meta(5, 50, true, false)),
            ("test_fn".to_string(), meta(5, 50, true, true)),
        ];

        let scores = compute_composite_importance(&pr, &metadata);

        // test_fn should be exactly half of prod_fn (before normalization, same components * 0.5)
        assert!(
            scores["prod_fn"] > scores["test_fn"],
            "prod ({}) should outrank test ({}) due to 0.5x penalty",
            scores["prod_fn"],
            scores["test_fn"],
        );

        // The ratio should be 2:1
        let ratio = scores["prod_fn"] / scores["test_fn"];
        assert!(
            (ratio - 2.0).abs() < 0.01,
            "ratio should be ~2.0, got {}",
            ratio,
        );
    }

    #[test]
    fn composite_scores_spread_meaningfully() {
        let mut pr = HashMap::new();
        pr.insert("a".to_string(), 1.0);
        pr.insert("b".to_string(), 0.5);
        pr.insert("c".to_string(), 0.1);

        let metadata = vec![
            ("a".to_string(), meta(10, 100, true, false)),
            ("b".to_string(), meta(5, 50, false, false)),
            ("c".to_string(), meta(1, 10, false, true)),
        ];

        let scores = compute_composite_importance(&pr, &metadata);

        // All scores should be positive
        for (id, score) in &scores {
            assert!(*score > 0.0, "node {} should have positive score, got {}", id, score);
        }

        // Scores should be ordered: a > b > c
        assert!(
            scores["a"] > scores["b"],
            "a ({}) should outrank b ({})",
            scores["a"],
            scores["b"],
        );
        assert!(
            scores["b"] > scores["c"],
            "b ({}) should outrank c ({})",
            scores["b"],
            scores["c"],
        );

        // Score range should be meaningful (not all clustered near 0)
        let max = scores.values().cloned().fold(0.0_f32, f32::max);
        let min = scores.values().cloned().fold(f32::MAX, f32::min);
        assert!(
            max - min > 0.1,
            "scores should spread meaningfully, range = {}",
            max - min,
        );
    }

    #[test]
    fn composite_empty_metadata() {
        let pr = HashMap::new();
        let metadata: Vec<(String, NodeMeta)> = vec![];
        let scores = compute_composite_importance(&pr, &metadata);
        assert!(scores.is_empty());
    }

    #[test]
    fn composite_loc_saturates_at_200() {
        // A 500-line function should score the same LOC component as a 200-line one
        let mut pr = HashMap::new();
        pr.insert("big".to_string(), 0.5);
        pr.insert("medium".to_string(), 0.5);

        let metadata = vec![
            ("big".to_string(), meta(5, 500, true, false)),
            ("medium".to_string(), meta(5, 200, true, false)),
        ];

        let scores = compute_composite_importance(&pr, &metadata);

        assert!(
            (scores["big"] - scores["medium"]).abs() < 1e-5,
            "500 LOC ({}) should score same as 200 LOC ({})",
            scores["big"],
            scores["medium"],
        );
    }

    #[test]
    fn composite_trivial_utility_dampening() {
        let mut pr = HashMap::new();
        pr.insert("utility".to_string(), 0.8);
        pr.insert("normal".to_string(), 0.8);

        let metadata = vec![
            ("utility".to_string(), meta_with_indegree(2, 5, true, false, 30)),
            ("normal".to_string(), meta_with_indegree(2, 5, true, false, 5)),
        ];

        let scores = compute_composite_importance(&pr, &metadata);

        assert!(
            scores["normal"] > scores["utility"],
            "normal ({}) should outrank utility ({}) due to trivial dampening",
            scores["normal"],
            scores["utility"],
        );

        // Ratio should be ~3.33 (dampened by 0.3x)
        let ratio = scores["normal"] / scores["utility"];
        assert!(
            (ratio - (1.0 / 0.3)).abs() < 0.1,
            "ratio should be ~3.33, got {}",
            ratio,
        );
    }

    #[test]
    fn composite_private_gets_partial_boost() {
        // Private nodes get 0.8 boost, not 0.0
        let mut pr = HashMap::new();
        pr.insert("pub_fn".to_string(), 0.5);
        pr.insert("priv_fn".to_string(), 0.5);

        let metadata = vec![
            ("pub_fn".to_string(), meta(5, 50, true, false)),
            ("priv_fn".to_string(), meta(5, 50, false, false)),
        ];

        let scores = compute_composite_importance(&pr, &metadata);

        // Public should score higher than private
        assert!(
            scores["pub_fn"] > scores["priv_fn"],
            "public ({}) should outrank private ({})",
            scores["pub_fn"],
            scores["priv_fn"],
        );

        // But private should NOT be zero — difference should be small (only 10% weight * 0.2 diff)
        let diff = scores["pub_fn"] - scores["priv_fn"];
        assert!(
            diff < 0.05,
            "difference should be small (only 10% * 0.2 = 0.02), got {}",
            diff,
        );
        assert!(
            diff > 0.0,
            "difference should be positive, got {}",
            diff,
        );
    }
}
