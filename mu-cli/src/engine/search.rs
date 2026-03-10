//! Unified search: exact match -> BM25 -> importance tiebreak.
//!
//! Three-phase cascade:
//! 1. Exact match on name/qualified_name (score = 1.0, always wins)
//! 2. BM25 full-text search on search_text
//! 3. Importance tiebreak: 85% BM25 + 15% PageRank

use std::collections::HashMap;

use anyhow::Result;
use duckdb::{params, Connection};
use serde::Serialize;

/// Confidence in search results based on score distribution.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub enum SearchConfidence {
    High,
    Medium,
    Low,
    NoResults,
}

/// Compute confidence from search result scores using distribution analysis.
///
/// Uses score spread (top vs median) and coefficient of variation instead
/// of absolute thresholds — works identically on small and large codebases.
///
/// When `query` is non-empty, also checks if the top result's name contains
/// significant query terms — a strong signal of a direct hit.
pub fn compute_confidence(results: &[SearchResult], query: &str) -> SearchConfidence {
    if results.is_empty() {
        return SearchConfidence::NoResults;
    }

    // Exact match always HIGH
    if results
        .iter()
        .any(|r| r.match_type == MatchType::ExactName || r.match_type == MatchType::ExactQualifiedName)
    {
        return SearchConfidence::High;
    }

    // Check if top result name contains significant query terms.
    // Uses a 5-char prefix check as poor-man's stemming so "validation" matches "Validate".
    if !query.is_empty() && !results.is_empty() {
        let query_terms: Vec<&str> = query
            .split_whitespace()
            .filter(|t| t.len() > 3) // skip short words like "how", "does", "the"
            .collect();

        if query_terms.len() >= 2 {
            let top_name = results[0].name.to_lowercase();
            let matching_terms = query_terms
                .iter()
                .filter(|t| {
                    let tl = t.to_lowercase();
                    top_name.contains(&tl)
                        || (tl.len() >= 5 && top_name.contains(&tl[..5]))
                })
                .count();
            if matching_terms >= 2 {
                return SearchConfidence::High;
            }
        }
    }

    let scores: Vec<f32> = results.iter().map(|r| r.score).collect();
    let top = scores[0];
    let count = scores.len();

    // If only 1-2 results, use simple threshold
    if count <= 2 {
        return if top > 0.10 {
            SearchConfidence::Medium
        } else {
            SearchConfidence::Low
        };
    }

    // Distribution-based confidence:
    // Compare top score to the MEDIAN score, not to absolute thresholds
    let median = scores[count / 2];
    let mean: f32 = scores.iter().sum::<f32>() / count as f32;

    // Score spread: how much does the top result stand out?
    let spread = if median > 0.001 {
        top / median
    } else {
        top * 100.0
    };

    // Variance: are scores clustered or spread out?
    let variance: f32 = scores.iter().map(|s| (s - mean).powi(2)).sum::<f32>() / count as f32;
    let cv = if mean > 0.001 {
        variance.sqrt() / mean
    } else {
        0.0
    };

    // Decision matrix:
    // High spread (top >> median) + any variance = the query found something specific
    // Low spread (top ≈ median) + low variance = flat results, probably noise

    // Count how many results clear the "decent match" floor
    let above_floor = scores.iter().filter(|&&s| s > 0.10).count();

    if top < 0.08 {
        // Absolute floor — even relative scoring can't save truly terrible matches
        SearchConfidence::Low
    } else if spread > 2.0 {
        // Top result is 2x+ the median — clear winner
        SearchConfidence::High
    } else if spread > 1.3 && cv > 0.2 {
        // Moderate separation with meaningful score variance
        SearchConfidence::Medium
    } else if cv < 0.1 && above_floor >= 3 {
        // Flat but multiple results above floor — topic query hitting a real subsystem
        SearchConfidence::Medium
    } else if cv < 0.1 {
        // Flat and few decent matches — likely noise
        SearchConfidence::Low
    } else {
        SearchConfidence::Medium
    }
}

/// How a result was matched.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub enum MatchType {
    ExactName,
    ExactQualifiedName,
    Bm25,
}

/// A search result with scoring metadata.
#[derive(Debug, Clone, Serialize)]
pub struct SearchResult {
    pub node_id: String,
    pub name: String,
    pub qualified_name: Option<String>,
    pub node_type: String,
    pub file_path: Option<String>,
    pub line_start: Option<u32>,
    pub line_end: Option<u32>,
    pub importance_score: f32,
    pub summary_text: Option<String>,
    pub source_text: Option<String>,
    pub score: f32,
    pub match_type: MatchType,
}

/// Search nodes using the three-phase cascade.
///
/// Phase 1: Exact match on name or qualified_name (score = 1.0)
/// Phase 2: BM25 on search_text (normalized to 0-1)
/// Phase 3: Importance tiebreak (85% BM25 + 15% PageRank)
///
/// `test_dampening` controls the score multiplier for test/migration files (default: 0.3).
///
/// All results are deduped by node_id (never by name -- the name-collision bug is dead).
pub fn search_nodes(conn: &Connection, query: &str, limit: usize) -> Result<Vec<SearchResult>> {
    search_nodes_with_dampening(conn, query, limit, 0.3)
}

/// Like `search_nodes` but with a configurable test dampening factor.
pub fn search_nodes_with_dampening(conn: &Connection, query: &str, limit: usize, test_dampening: f32) -> Result<Vec<SearchResult>> {
    search_nodes_with_config(conn, query, limit, test_dampening, &[], 1.0)
}

/// Full-config search: test dampening + auxiliary service dampening.
pub fn search_nodes_with_config(
    conn: &Connection,
    query: &str,
    limit: usize,
    test_dampening: f32,
    auxiliary_services: &[String],
    auxiliary_dampening: f32,
) -> Result<Vec<SearchResult>> {
    let mut results: HashMap<String, SearchResult> = HashMap::new();

    // -- Phase 1: Exact Match (highest priority) --
    // Parameterized query -- no SQL injection
    let mut stmt = conn.prepare(
        "SELECT id, type, name, qualified_name, file_path, line_start, line_end,
                importance_score, summary_text, source_text
         FROM nodes
         WHERE name = ?1
            OR qualified_name = ?1
            OR name LIKE '%.' || ?1",
    )?;

    let mut rows = stmt.query(params![query])?;

    while let Some(row) = rows.next()? {
        let node_id: String = row.get(0)?;
        let qualified_name: Option<String> = row.get(3)?;

        // Determine exact match type
        let match_type = if qualified_name.as_deref() == Some(query) {
            MatchType::ExactQualifiedName
        } else {
            MatchType::ExactName
        };

        let result = SearchResult {
            node_id: node_id.clone(),
            node_type: row.get::<_, String>(1)?,
            name: row.get(2)?,
            qualified_name,
            file_path: row.get(4)?,
            line_start: row.get(5)?,
            line_end: row.get(6)?,
            importance_score: row.get::<_, f64>(7).unwrap_or(0.0) as f32,
            summary_text: row.get(8)?,
            source_text: row.get(9)?,
            score: 1.0,
            match_type,
        };

        results.entry(node_id).or_insert(result);
    }

    if results.len() >= limit {
        return Ok(top_n(&results, limit));
    }

    // -- Phase 2: BM25 on search_text --
    let remaining = limit - results.len();
    let bm25_results = bm25_search_v3(conn, query, remaining * 3)?;

    for (node_id, raw_score, mut result) in bm25_results {
        if results.contains_key(&node_id) {
            continue; // Already found via exact match
        }

        // Normalize BM25 to 0-1: score / (score + k), k=10
        let bm25_score = raw_score / (raw_score + 10.0);

        // -- Phase 3: Importance Tiebreak --
        // 85% BM25, 15% PageRank
        let mut final_score = 0.85 * bm25_score + 0.15 * result.importance_score;

        // Dampen test/migration results so production code ranks higher
        if is_test_or_migration(result.file_path.as_deref()) {
            final_score *= test_dampening;
        }

        // Dampen auxiliary service results (e.g. chatagent, scripts)
        if !auxiliary_services.is_empty() {
            if let Some(ref fp) = result.file_path {
                if crate::engine::auto_config::is_auxiliary_service(fp, auxiliary_services) {
                    final_score *= auxiliary_dampening;
                }
            }
        }

        result.score = final_score;
        result.match_type = MatchType::Bm25;
        results.insert(node_id, result);
    }

    Ok(top_n(&results, limit))
}

/// BM25 search using DuckDB FTS on search_text column.
/// Returns (node_id, raw_bm25_score, SearchResult) tuples.
fn bm25_search_v3(
    conn: &Connection,
    query: &str,
    limit: usize,
) -> Result<Vec<(String, f32, SearchResult)>> {
    // Try FTS first
    let fts_result = conn.prepare(
        "SELECT id, type, name, qualified_name, file_path, line_start, line_end,
                importance_score, summary_text, source_text,
                fts_main_nodes.match_bm25(id, ?1) AS bm25_score
         FROM nodes
         WHERE bm25_score IS NOT NULL
         ORDER BY bm25_score DESC
         LIMIT ?2",
    );

    match fts_result {
        Ok(mut stmt) => {
            let mut rows = stmt.query(params![query, limit as i64])?;
            let mut results = Vec::new();

            while let Some(row) = rows.next()? {
                let node_id: String = row.get(0)?;
                let bm25_score: f64 = row.get(10)?;

                results.push((
                    node_id.clone(),
                    bm25_score as f32,
                    SearchResult {
                        node_id,
                        node_type: row.get::<_, String>(1)?,
                        name: row.get(2)?,
                        qualified_name: row.get(3)?,
                        file_path: row.get(4)?,
                        line_start: row.get(5)?,
                        line_end: row.get(6)?,
                        importance_score: row.get::<_, f64>(7).unwrap_or(0.0) as f32,
                        summary_text: row.get(8)?,
                        source_text: row.get(9)?,
                        score: 0.0,
                        match_type: MatchType::Bm25,
                    },
                ));
            }
            Ok(results)
        }
        Err(_) => {
            // FTS not available, fall back to LIKE search
            fallback_keyword_search(conn, query, limit)
        }
    }
}

/// Fallback keyword search when FTS is not available.
fn fallback_keyword_search(
    conn: &Connection,
    query: &str,
    limit: usize,
) -> Result<Vec<(String, f32, SearchResult)>> {
    let keywords: Vec<&str> = query.split_whitespace().collect();
    if keywords.is_empty() {
        return Ok(Vec::new());
    }

    // Build LIKE conditions for each keyword using positional params (?1, ?2, ...)
    let conditions: Vec<String> = keywords
        .iter()
        .enumerate()
        .map(|(i, _)| {
            let p = i + 1; // 1-indexed param
            format!(
                "(search_text LIKE '%' || ?{p} || '%' OR name LIKE '%' || ?{p} || '%')"
            )
        })
        .collect();

    let limit_param = keywords.len() + 1;
    let where_clause = conditions.join(" AND ");
    let sql = format!(
        "SELECT id, type, name, qualified_name, file_path, line_start, line_end,
                importance_score, summary_text, source_text
         FROM nodes
         WHERE {where_clause}
         ORDER BY importance_score DESC
         LIMIT ?{limit_param}"
    );

    let mut stmt = conn.prepare(&sql)?;

    // Build dynamic params: keywords + limit
    let mut param_values: Vec<Box<dyn duckdb::ToSql>> = keywords
        .iter()
        .map(|k| Box::new(k.to_string()) as Box<dyn duckdb::ToSql>)
        .collect();
    param_values.push(Box::new(limit as i64));

    let param_refs: Vec<&dyn duckdb::ToSql> = param_values.iter().map(|p| p.as_ref()).collect();

    let mut rows = stmt.query(param_refs.as_slice())?;
    let mut results = Vec::new();

    while let Some(row) = rows.next()? {
        let node_id: String = row.get(0)?;
        results.push((
            node_id.clone(),
            5.0_f32, // synthetic BM25 score for LIKE matches
            SearchResult {
                node_id,
                node_type: row.get::<_, String>(1)?,
                name: row.get(2)?,
                qualified_name: row.get(3)?,
                file_path: row.get(4)?,
                line_start: row.get(5)?,
                line_end: row.get(6)?,
                importance_score: row.get::<_, f64>(7).unwrap_or(0.0) as f32,
                summary_text: row.get(8)?,
                source_text: row.get(9)?,
                score: 0.0,
                match_type: MatchType::Bm25,
            },
        ));
    }
    Ok(results)
}

/// Check if a file path belongs to test or migration code.
///
/// Used to dampen search scores — these results stay in the list but
/// rank below production code at the same BM25 relevance.
pub fn is_test_or_migration(file_path: Option<&str>) -> bool {
    let Some(path) = file_path else { return false };
    let lower = path.to_lowercase();
    let file_name = path.rsplit('/').next().unwrap_or("");
    let file_name_lower = file_name.to_lowercase();

    // Match /test/, /tests/, or paths starting with test(s)/
    lower.contains("/test/") || lower.starts_with("test/")
        || lower.contains("/tests/") || lower.starts_with("tests/")
        || file_name_lower.ends_with("tests.cs")
        || file_name_lower.starts_with("test_")
        || lower.contains("/migrations/") || lower.starts_with("migrations/")
}

/// Sort results by score descending and take top N.
fn top_n(results: &HashMap<String, SearchResult>, limit: usize) -> Vec<SearchResult> {
    let mut sorted: Vec<_> = results.values().cloned().collect();
    sorted.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    sorted.truncate(limit);
    sorted
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_top_n_sorts_by_score_descending() {
        let mut results = HashMap::new();
        for (id, score) in [("a", 0.3), ("b", 0.9), ("c", 0.1), ("d", 0.7)] {
            results.insert(
                id.to_string(),
                SearchResult {
                    node_id: id.to_string(),
                    name: id.to_string(),
                    qualified_name: None,
                    node_type: "function".to_string(),
                    file_path: None,
                    line_start: None,
                    line_end: None,
                    importance_score: 0.0,
                    summary_text: None,
                    source_text: None,
                    score,
                    match_type: MatchType::Bm25,
                },
            );
        }

        let top = top_n(&results, 3);
        assert_eq!(top.len(), 3);
        assert_eq!(top[0].node_id, "b");
        assert_eq!(top[1].node_id, "d");
        assert_eq!(top[2].node_id, "a");
    }

    #[test]
    fn test_top_n_limit_exceeds_results() {
        let mut results = HashMap::new();
        results.insert(
            "only".to_string(),
            SearchResult {
                node_id: "only".to_string(),
                name: "only".to_string(),
                qualified_name: None,
                node_type: "class".to_string(),
                file_path: None,
                line_start: None,
                line_end: None,
                importance_score: 0.5,
                summary_text: None,
                source_text: None,
                score: 0.8,
                match_type: MatchType::ExactName,
            },
        );

        let top = top_n(&results, 10);
        assert_eq!(top.len(), 1);
        assert_eq!(top[0].node_id, "only");
    }

    #[test]
    fn test_top_n_empty() {
        let results: HashMap<String, SearchResult> = HashMap::new();
        let top = top_n(&results, 5);
        assert!(top.is_empty());
    }

    #[test]
    fn test_match_type_serialization() {
        let json = serde_json::to_string(&MatchType::ExactName).unwrap();
        assert_eq!(json, r#""ExactName""#);

        let json = serde_json::to_string(&MatchType::ExactQualifiedName).unwrap();
        assert_eq!(json, r#""ExactQualifiedName""#);

        let json = serde_json::to_string(&MatchType::Bm25).unwrap();
        assert_eq!(json, r#""Bm25""#);
    }

    #[test]
    fn test_match_type_equality() {
        assert_eq!(MatchType::ExactName, MatchType::ExactName);
        assert_ne!(MatchType::ExactName, MatchType::Bm25);
        assert_ne!(MatchType::ExactQualifiedName, MatchType::Bm25);
    }

    #[test]
    fn test_search_result_clone() {
        let result = SearchResult {
            node_id: "fn:foo".to_string(),
            name: "foo".to_string(),
            qualified_name: Some("bar.foo".to_string()),
            node_type: "function".to_string(),
            file_path: Some("src/bar.rs".to_string()),
            line_start: Some(10),
            line_end: Some(20),
            importance_score: 0.42,
            summary_text: Some("Does stuff".to_string()),
            source_text: Some("fn foo() {}".to_string()),
            score: 0.95,
            match_type: MatchType::ExactName,
        };
        let cloned = result.clone();
        assert_eq!(cloned.node_id, "fn:foo");
        assert_eq!(cloned.score, 0.95);
        assert_eq!(cloned.match_type, MatchType::ExactName);
    }

    #[test]
    fn test_bm25_normalization() {
        // Verify the normalization formula: score / (score + 10)
        // score=0  -> 0.0
        // score=10 -> 0.5
        // score=90 -> 0.9
        let normalize = |raw: f32| raw / (raw + 10.0);

        assert!((normalize(0.0) - 0.0).abs() < f32::EPSILON);
        assert!((normalize(10.0) - 0.5).abs() < f32::EPSILON);
        assert!((normalize(90.0) - 0.9).abs() < f32::EPSILON);
    }

    #[test]
    fn test_importance_tiebreak_formula() {
        // 85% BM25 + 15% PageRank
        let bm25_normalized = 0.5_f32;
        let importance = 1.0_f32;
        let final_score = 0.85 * bm25_normalized + 0.15 * importance;
        assert!((final_score - 0.575).abs() < 0.001);

        // With zero importance, final score is just 85% of BM25
        let final_score_no_importance = 0.85 * bm25_normalized + 0.15 * 0.0;
        assert!((final_score_no_importance - 0.425).abs() < 0.001);
    }

    #[test]
    fn test_exact_match_always_wins() {
        // Exact matches get score=1.0, BM25 max approaches 0.85 + 0.15 = 1.0
        // but never reaches it, so exact always sorts first
        let mut results = HashMap::new();
        results.insert(
            "exact".to_string(),
            SearchResult {
                node_id: "exact".to_string(),
                name: "foo".to_string(),
                qualified_name: None,
                node_type: "function".to_string(),
                file_path: None,
                line_start: None,
                line_end: None,
                importance_score: 0.0,
                summary_text: None,
                source_text: None,
                score: 1.0,
                match_type: MatchType::ExactName,
            },
        );
        results.insert(
            "bm25".to_string(),
            SearchResult {
                node_id: "bm25".to_string(),
                name: "foobar".to_string(),
                qualified_name: None,
                node_type: "function".to_string(),
                file_path: None,
                line_start: None,
                line_end: None,
                importance_score: 1.0,
                summary_text: None,
                source_text: None,
                // Best possible BM25: 0.85 * (huge/(huge+10)) + 0.15 * 1.0 < 1.0
                score: 0.85 * 0.999 + 0.15 * 1.0,
                match_type: MatchType::Bm25,
            },
        );

        let top = top_n(&results, 2);
        assert_eq!(top[0].node_id, "exact");
        assert_eq!(top[0].match_type, MatchType::ExactName);
    }

    #[test]
    fn test_search_result_serialization() {
        let result = SearchResult {
            node_id: "fn:bar".to_string(),
            name: "bar".to_string(),
            qualified_name: Some("Foo.bar".to_string()),
            node_type: "function".to_string(),
            file_path: Some("src/foo.rs".to_string()),
            line_start: Some(5),
            line_end: Some(15),
            importance_score: 0.7,
            summary_text: None,
            source_text: None,
            score: 0.88,
            match_type: MatchType::Bm25,
        };

        let json = serde_json::to_value(&result).unwrap();
        assert_eq!(json["node_id"], "fn:bar");
        assert_eq!(json["match_type"], "Bm25");
        let score = json["score"].as_f64().unwrap();
        assert!((score - 0.88).abs() < 0.001, "score was {}", score);
        assert!(json["summary_text"].is_null());
    }

    #[test]
    #[ignore = "Requires V3 schema with search_text and importance_score columns"]
    fn test_search_nodes_exact_match() {
        // Would test: insert node with name "Foo", search for "Foo",
        // verify score=1.0 and match_type=ExactName
    }

    #[test]
    #[ignore = "Requires FTS index on search_text column"]
    fn test_search_nodes_bm25_with_importance() {
        // Would test: insert nodes with search_text, create FTS index,
        // search and verify 85/15 scoring blend
    }

    #[test]
    #[ignore = "Requires V3 schema with search_text column"]
    fn test_search_nodes_fallback_keyword() {
        // Would test: search without FTS index, verify LIKE fallback
        // produces results with synthetic BM25 score
    }

    #[test]
    #[ignore = "Requires V3 schema"]
    fn test_search_nodes_dedup_exact_over_bm25() {
        // Would test: node appears in both exact and BM25 results,
        // verify it keeps the exact match (score=1.0) and is not duplicated
    }

    // -- confidence model tests --

    fn make_result(score: f32, match_type: MatchType) -> SearchResult {
        SearchResult {
            node_id: "n".to_string(),
            name: "n".to_string(),
            qualified_name: None,
            node_type: "function".to_string(),
            file_path: None,
            line_start: None,
            line_end: None,
            importance_score: 0.0,
            summary_text: None,
            source_text: None,
            score,
            match_type,
        }
    }

    fn make_results(scores: &[f32]) -> Vec<SearchResult> {
        scores
            .iter()
            .map(|&s| make_result(s, MatchType::Bm25))
            .collect()
    }

    #[test]
    fn test_confidence_empty_results() {
        assert_eq!(compute_confidence(&[], ""), SearchConfidence::NoResults);
    }

    #[test]
    fn test_confidence_exact_name_is_high() {
        let results = vec![make_result(1.0, MatchType::ExactName)];
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::High);
    }

    #[test]
    fn test_confidence_exact_qualified_name_is_high() {
        let results = vec![make_result(1.0, MatchType::ExactQualifiedName)];
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::High);
    }

    #[test]
    fn test_confidence_single_low_score_is_low() {
        // count <= 2, top <= 0.10
        let results = vec![make_result(0.05, MatchType::Bm25)];
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Low);
    }

    #[test]
    fn test_confidence_single_decent_score_is_medium() {
        // count <= 2, top > 0.10
        let results = vec![make_result(0.50, MatchType::Bm25)];
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Medium);
    }

    #[test]
    fn test_confidence_clear_winner_high_spread() {
        // Top result is 2x+ the median → HIGH
        // scores: 0.50, 0.25, 0.20, 0.15, 0.10
        // median (index 2) = 0.20, spread = 0.50/0.20 = 2.5
        let results = make_results(&[0.50, 0.25, 0.20, 0.15, 0.10]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::High);
    }

    #[test]
    fn test_confidence_flat_distribution_is_low() {
        // Flat scores with few above floor → noise → LOW
        // scores: 0.09, 0.09, 0.08, 0.08, 0.08
        // only 0 above 0.10, so above_floor < 3
        let results = make_results(&[0.09, 0.09, 0.08, 0.08, 0.08]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Low);
    }

    #[test]
    fn test_confidence_flat_but_decent_is_medium() {
        // Flat scores but 3+ results above floor → topic match → MEDIUM
        // scores: 0.22, 0.22, 0.21 — the "search ranking" pattern
        let results = make_results(&[0.22, 0.22, 0.21]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Medium);
    }

    #[test]
    fn test_confidence_moderate_spread_with_variance_is_medium() {
        // spread 1.3-2.0 with cv > 0.2 → MEDIUM
        // scores: 0.40, 0.35, 0.25, 0.15, 0.10
        // median = 0.25, spread = 0.40/0.25 = 1.6, decent variance
        let results = make_results(&[0.40, 0.35, 0.25, 0.15, 0.10]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Medium);
    }

    #[test]
    fn test_confidence_absolute_floor() {
        // Even with some spread, top < 0.08 → LOW
        let results = make_results(&[0.06, 0.03, 0.02, 0.01, 0.01]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Low);
    }

    #[test]
    fn test_confidence_two_results_above_threshold() {
        // count <= 2, top > 0.10
        let results = make_results(&[0.40, 0.35]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Medium);
    }

    #[test]
    fn test_confidence_two_results_below_threshold() {
        // count <= 2, top <= 0.10
        let results = make_results(&[0.08, 0.05]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Low);
    }

    // -- substring match confidence tests --

    fn make_named_result(name: &str, score: f32) -> SearchResult {
        SearchResult {
            node_id: name.to_string(),
            name: name.to_string(),
            qualified_name: None,
            node_type: "function".to_string(),
            file_path: None,
            line_start: None,
            line_end: None,
            importance_score: 0.0,
            summary_text: None,
            source_text: None,
            score,
            match_type: MatchType::Bm25,
        }
    }

    #[test]
    fn test_confidence_substring_match_promotes_to_high() {
        // "webhook signature validation" → ValidateSignature contains "validate" + "signature"
        let results = vec![
            make_named_result("ValidateSignature", 0.35),
            make_named_result("OtherThing", 0.30),
            make_named_result("Random", 0.25),
        ];
        assert_eq!(
            compute_confidence(&results, "webhook signature validation"),
            SearchConfidence::High
        );
    }

    #[test]
    fn test_confidence_substring_match_single_term_no_promote() {
        // Only 1 significant term ("rate" is 4 chars, "limiting" is 8) but if the name
        // only matches one term, it should NOT promote
        let results = vec![
            make_named_result("RateController", 0.35),
            make_named_result("OtherThing", 0.30),
            make_named_result("Random", 0.25),
        ];
        // "rate limiting" → RateController has "rate" but not "limit" → no promote
        // Still goes through normal distribution logic → MEDIUM (spread ~1.4, cv decent)
        let conf = compute_confidence(&results, "rate limiting");
        assert_ne!(conf, SearchConfidence::High);
    }

    #[test]
    fn test_confidence_substring_match_short_words_skipped() {
        // "how does the search work" → only "search" and "work" are >3 chars
        let results = vec![
            make_named_result("SearchEngine", 0.35),
            make_named_result("Other", 0.30),
            make_named_result("Random", 0.25),
        ];
        // "search" matches but "work" doesn't → only 1 match → no promote
        let conf = compute_confidence(&results, "how does the search work");
        assert_ne!(conf, SearchConfidence::High);
    }

    #[test]
    fn test_confidence_no_query_no_substring_check() {
        // Empty query should behave the same as before
        let results = make_results(&[0.40, 0.35, 0.25, 0.15, 0.10]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Medium);
    }

    // -- test/migration dampening tests --

    #[test]
    fn test_is_test_or_migration_test_dir() {
        assert!(is_test_or_migration(Some("src/tests/foo.rs")));
        assert!(is_test_or_migration(Some("tests/unit/bar.rs")));
        assert!(is_test_or_migration(Some("src/test/helpers.rs")));
    }

    #[test]
    fn test_is_test_or_migration_cs_test_suffix() {
        assert!(is_test_or_migration(Some("src/Services/PaymentServiceTests.cs")));
        assert!(is_test_or_migration(Some("tests/MyTests.cs")));
    }

    #[test]
    fn test_is_test_or_migration_test_prefix() {
        assert!(is_test_or_migration(Some("src/test_search.py")));
        assert!(is_test_or_migration(Some("lib/test_utils.rs")));
    }

    #[test]
    fn test_is_test_or_migration_migrations() {
        assert!(is_test_or_migration(Some("src/Migrations/20240101_Init.cs")));
        assert!(is_test_or_migration(Some("db/migrations/001_create.sql")));
    }

    #[test]
    fn test_is_test_or_migration_production_code() {
        assert!(!is_test_or_migration(Some("src/engine/search.rs")));
        assert!(!is_test_or_migration(Some("src/Services/PaymentService.cs")));
        assert!(!is_test_or_migration(Some("src/main.rs")));
        assert!(!is_test_or_migration(None));
    }
}
