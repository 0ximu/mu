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

/// Compute confidence from search result scores and match types.
///
/// Rules (in priority order):
/// 1. Empty results -> NoResults
/// 2. Any exact match -> High
/// 3. Top score < 0.10 -> Low (barely beat random)
/// 4. Gap between #1 and #2 > 0.15 -> High (clear winner)
/// 5. Top score > 0.30 -> Medium
/// 6. Otherwise -> Low
pub fn compute_confidence(results: &[SearchResult]) -> SearchConfidence {
    if results.is_empty() {
        return SearchConfidence::NoResults;
    }

    if results
        .iter()
        .any(|r| r.match_type == MatchType::ExactName || r.match_type == MatchType::ExactQualifiedName)
    {
        return SearchConfidence::High;
    }

    let top_score = results[0].score;

    if top_score < 0.10 {
        return SearchConfidence::Low;
    }

    if results.len() >= 2 {
        let gap = results[0].score - results[1].score;
        if gap > 0.15 {
            return SearchConfidence::High;
        }
    }

    if top_score > 0.30 {
        return SearchConfidence::Medium;
    }

    SearchConfidence::Low
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
/// All results are deduped by node_id (never by name -- the name-collision bug is dead).
pub fn search_nodes(conn: &Connection, query: &str, limit: usize) -> Result<Vec<SearchResult>> {
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
        let final_score = 0.85 * bm25_score + 0.15 * result.importance_score;

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

    #[test]
    fn test_confidence_empty_results() {
        assert_eq!(compute_confidence(&[]), SearchConfidence::NoResults);
    }

    #[test]
    fn test_confidence_exact_name_is_high() {
        let results = vec![make_result(1.0, MatchType::ExactName)];
        assert_eq!(compute_confidence(&results), SearchConfidence::High);
    }

    #[test]
    fn test_confidence_exact_qualified_name_is_high() {
        let results = vec![make_result(1.0, MatchType::ExactQualifiedName)];
        assert_eq!(compute_confidence(&results), SearchConfidence::High);
    }

    #[test]
    fn test_confidence_low_top_score() {
        let results = vec![make_result(0.05, MatchType::Bm25)];
        assert_eq!(compute_confidence(&results), SearchConfidence::Low);
    }

    #[test]
    fn test_confidence_clear_gap_is_high() {
        let results = vec![
            make_result(0.50, MatchType::Bm25),
            make_result(0.20, MatchType::Bm25),
        ];
        // gap = 0.30 > 0.15
        assert_eq!(compute_confidence(&results), SearchConfidence::High);
    }

    #[test]
    fn test_confidence_strong_score_no_gap_is_medium() {
        let results = vec![
            make_result(0.40, MatchType::Bm25),
            make_result(0.35, MatchType::Bm25),
        ];
        // gap = 0.05, not > 0.15; top_score > 0.30
        assert_eq!(compute_confidence(&results), SearchConfidence::Medium);
    }

    #[test]
    fn test_confidence_weak_scores_close_together_is_low() {
        let results = vec![
            make_result(0.15, MatchType::Bm25),
            make_result(0.12, MatchType::Bm25),
        ];
        // gap = 0.03, not > 0.15; top_score = 0.15 not > 0.30
        assert_eq!(compute_confidence(&results), SearchConfidence::Low);
    }

    #[test]
    fn test_confidence_single_strong_result_is_medium() {
        // Only one result, score > 0.30, no gap check possible
        let results = vec![make_result(0.50, MatchType::Bm25)];
        assert_eq!(compute_confidence(&results), SearchConfidence::Medium);
    }
}
