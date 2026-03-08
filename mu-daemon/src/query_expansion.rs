//! Query expansion for semantic search.
//!
//! Expands a search query using graph vocabulary to improve recall.
//! The expansion works by splitting node names (camelCase, snake_case)
//! into individual words, counting frequency, and using the most common
//! terms as additional query variants.

use crate::storage::VectorSearchResult;
use std::collections::HashMap;

/// Split an identifier (camelCase or snake_case) into lowercase words.
fn split_identifier(name: &str) -> Vec<String> {
    let mut words = Vec::new();
    for part in name.split('_') {
        let mut current = String::new();
        for ch in part.chars() {
            if ch.is_uppercase() && !current.is_empty() {
                words.push(current.to_lowercase());
                current = String::new();
            }
            current.push(ch);
        }
        if !current.is_empty() {
            words.push(current.to_lowercase());
        }
    }
    words
}

/// Expand a query using graph vocabulary (no external deps).
///
/// Takes the original query and a list of node names from graph neighbors.
/// Splits names into words, deduplicates, and returns the most frequent
/// terms as additional query variants.
///
/// Returns `[original_query, term1, term2, ...]` with at most `max_variants` entries.
pub fn expand_query(query: &str, node_names: &[String], max_variants: usize) -> Vec<String> {
    if max_variants == 0 {
        return vec![];
    }

    let mut result = vec![query.to_string()];

    if max_variants == 1 || node_names.is_empty() {
        return result;
    }

    // Split all node names into words and count frequency
    let query_lower = query.to_lowercase();
    let mut freq: HashMap<String, usize> = HashMap::new();

    for name in node_names {
        for word in split_identifier(name) {
            // Skip very short words, the query itself, and common noise
            if word.len() < 3 || word == query_lower {
                continue;
            }
            *freq.entry(word).or_insert(0) += 1;
        }
    }

    // Sort by frequency descending, take top (max_variants - 1)
    let mut terms: Vec<(String, usize)> = freq.into_iter().collect();
    terms.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));

    let take = max_variants - 1;
    for (term, _) in terms.into_iter().take(take) {
        result.push(term);
    }

    result
}

/// Merge results from multiple queries, deduplicating by node_id.
///
/// Nodes hit by multiple queries get boosted: `similarity *= 1 + 0.15 * (hit_count - 1)`.
/// Results are re-sorted by boosted similarity descending.
pub fn merge_search_results(
    results_per_query: Vec<Vec<VectorSearchResult>>,
) -> Vec<VectorSearchResult> {
    // Track best result per node_id and hit count
    let mut best: HashMap<String, (VectorSearchResult, usize)> = HashMap::new();

    for results in results_per_query {
        for r in results {
            let entry = best
                .entry(r.node_id.clone())
                .or_insert_with(|| (r.clone(), 0));
            entry.1 += 1;
            // Keep the highest raw similarity
            if r.similarity > entry.0.similarity {
                entry.0 = r;
            }
        }
    }

    // Apply boost and collect
    let mut merged: Vec<VectorSearchResult> = best
        .into_values()
        .map(|(mut result, hit_count)| {
            if hit_count > 1 {
                result.similarity *= 1.0 + 0.15 * (hit_count as f32 - 1.0);
                // Clamp to 1.0
                if result.similarity > 1.0 {
                    result.similarity = 1.0;
                }
            }
            result
        })
        .collect();

    merged.sort_by(|a, b| {
        b.similarity
            .partial_cmp(&a.similarity)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    merged
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_split_identifier_camel_case() {
        assert_eq!(split_identifier("getUserName"), vec!["get", "user", "name"]);
    }

    #[test]
    fn test_split_identifier_snake_case() {
        assert_eq!(
            split_identifier("get_user_name"),
            vec!["get", "user", "name"]
        );
    }

    #[test]
    fn test_split_identifier_mixed() {
        assert_eq!(
            split_identifier("getUser_name"),
            vec!["get", "user", "name"]
        );
    }

    #[test]
    fn test_split_identifier_single_word() {
        assert_eq!(split_identifier("auth"), vec!["auth"]);
    }

    #[test]
    fn test_expand_query_basic() {
        let names = vec![
            "authMiddleware".to_string(),
            "authToken".to_string(),
            "validateAuth".to_string(),
            "tokenRefresh".to_string(),
            "authService".to_string(),
        ];
        let result = expand_query("auth", &names, 5);

        // First element is always the original query
        assert_eq!(result[0], "auth");
        // Should have expansion terms
        assert!(result.len() > 1);
        assert!(result.len() <= 5);
    }

    #[test]
    fn test_expand_query_skips_query_term() {
        let names = vec!["auth".to_string(), "authService".to_string()];
        let result = expand_query("auth", &names, 5);
        // "auth" should only appear once (as the original query, not as expansion)
        assert_eq!(result.iter().filter(|s| *s == "auth").count(), 1);
    }

    #[test]
    fn test_expand_query_empty_names() {
        let result = expand_query("auth", &[], 5);
        assert_eq!(result, vec!["auth"]);
    }

    #[test]
    fn test_expand_query_max_variants_one() {
        let names = vec!["authService".to_string()];
        let result = expand_query("auth", &names, 1);
        assert_eq!(result, vec!["auth"]);
    }

    #[test]
    fn test_expand_query_max_variants_zero() {
        let result = expand_query("auth", &[], 0);
        assert!(result.is_empty());
    }

    #[test]
    fn test_merge_results_dedup_and_boost() {
        let r1 = vec![
            VectorSearchResult {
                node_id: "a".to_string(),
                similarity: 0.8,
                name: "nodeA".to_string(),
                node_type: "function".to_string(),
                file_path: Some("a.rs".to_string()),
                qualified_name: None,
            },
            VectorSearchResult {
                node_id: "b".to_string(),
                similarity: 0.6,
                name: "nodeB".to_string(),
                node_type: "function".to_string(),
                file_path: Some("b.rs".to_string()),
                qualified_name: None,
            },
        ];
        let r2 = vec![VectorSearchResult {
            node_id: "a".to_string(),
            similarity: 0.7,
            name: "nodeA".to_string(),
            node_type: "function".to_string(),
            file_path: Some("a.rs".to_string()),
            qualified_name: None,
        }];

        let merged = merge_search_results(vec![r1, r2]);

        assert_eq!(merged.len(), 2);
        // "a" was hit twice, so it gets boosted: 0.8 * 1.15 = 0.92
        let a = merged.iter().find(|r| r.node_id == "a").unwrap();
        assert!((a.similarity - 0.92).abs() < 0.01);
        // "b" was hit once, no boost
        let b = merged.iter().find(|r| r.node_id == "b").unwrap();
        assert!((b.similarity - 0.6).abs() < 0.01);
        // "a" should be first (higher similarity after boost)
        assert_eq!(merged[0].node_id, "a");
    }

    #[test]
    fn test_merge_results_empty() {
        let merged = merge_search_results(vec![]);
        assert!(merged.is_empty());
    }

    #[test]
    fn test_merge_results_single_query() {
        let r1 = vec![VectorSearchResult {
            node_id: "x".to_string(),
            similarity: 0.5,
            name: "nodeX".to_string(),
            node_type: "class".to_string(),
            file_path: None,
            qualified_name: None,
        }];
        let merged = merge_search_results(vec![r1]);
        assert_eq!(merged.len(), 1);
        assert!((merged[0].similarity - 0.5).abs() < 0.01);
    }

    #[test]
    fn test_merge_results_clamps_to_one() {
        // Create a result with high similarity that would exceed 1.0 after boost
        let r1 = vec![VectorSearchResult {
            node_id: "a".to_string(),
            similarity: 0.95,
            name: "nodeA".to_string(),
            node_type: "function".to_string(),
            file_path: None,
            qualified_name: None,
        }];
        let r2 = vec![VectorSearchResult {
            node_id: "a".to_string(),
            similarity: 0.90,
            name: "nodeA".to_string(),
            node_type: "function".to_string(),
            file_path: None,
            qualified_name: None,
        }];

        let merged = merge_search_results(vec![r1, r2]);
        assert!(merged[0].similarity <= 1.0);
    }
}
