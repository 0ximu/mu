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

/// Curated bidirectional abbreviation table for query term expansion.
///
/// Code identifiers routinely tokenize to short forms ("BasicAuthMiddleware"
/// -> "auth") that neither exact matching nor the 5-char prefix stemming in
/// `compute_confidence` can bridge: "authentication" never prefix-matches
/// "auth". Each entry maps a short form to its long form(s); expansion works
/// in both directions.
///
/// "val" is deliberately absent: it is ambiguous (validation vs value).
const ABBREVIATIONS: &[(&str, &[&str])] = &[
    ("auth", &["authentication", "authorization"]),
    ("config", &["configuration"]),
    ("db", &["database"]),
    ("repo", &["repository"]),
    ("msg", &["message"]),
    ("impl", &["implementation"]),
    ("init", &["initialization"]),
    ("param", &["parameter"]),
    ("util", &["utility"]),
    ("ctx", &["context"]),
    ("svc", &["service"]),
    ("mgr", &["manager"]),
    ("conn", &["connection"]),
    ("spec", &["specification"]),
    ("env", &["environment"]),
    ("temp", &["temporary"]),
    ("doc", &["document", "documentation"]),
];

/// Abbreviation variants for a single query term (bidirectional, lowercase).
/// Returns an empty vec for terms not in the table.
fn abbreviation_variants(term: &str) -> Vec<String> {
    let lower = term.to_lowercase();
    let mut variants = Vec::new();
    for (short, longs) in ABBREVIATIONS {
        if lower == *short {
            variants.extend(longs.iter().map(|l| (*l).to_string()));
        } else if longs.contains(&lower.as_str()) {
            variants.push((*short).to_string());
        }
    }
    variants
}

/// Expand a query for the BM25 phase by appending abbreviation variants of
/// each term as extra OR terms: "authentication middleware" becomes
/// "authentication middleware auth". The exact-name phase keeps the raw query.
fn expand_query(query: &str) -> String {
    let mut expanded = query.to_string();
    for term in query.split_whitespace() {
        for variant in abbreviation_variants(term) {
            let already = expanded
                .split_whitespace()
                .any(|t| t.eq_ignore_ascii_case(&variant));
            if !already {
                expanded.push(' ');
                expanded.push_str(&variant);
            }
        }
    }
    expanded
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
    if results.iter().any(|r| {
        r.match_type == MatchType::ExactName || r.match_type == MatchType::ExactQualifiedName
    }) {
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
                        || abbreviation_variants(&tl)
                            .iter()
                            .any(|v| top_name.contains(v.as_str()))
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
    pub node_category: String,
    pub score: f32,
    pub match_type: MatchType,
}

/// Search with default production-only filter.
pub fn search_nodes(conn: &Connection, query: &str, limit: usize) -> Result<Vec<SearchResult>> {
    search_nodes_with_categories(conn, query, limit, &["production"])
}

/// Search with explicit category filter.
pub fn search_nodes_with_categories(
    conn: &Connection,
    query: &str,
    limit: usize,
    categories: &[&str],
) -> Result<Vec<SearchResult>> {
    let category_filter = if categories.is_empty() {
        String::new()
    } else {
        let quoted: Vec<String> = categories.iter().map(|c| format!("'{}'", c)).collect();
        format!(" AND node_category IN ({})", quoted.join(", "))
    };

    let mut results: HashMap<String, SearchResult> = HashMap::new();

    // -- Phase 1: Exact Match (highest priority) --
    let sql = format!(
        "SELECT id, type, name, qualified_name, file_path, line_start, line_end,
                importance_score, summary_text, source_text, node_category
         FROM nodes
         WHERE (name = ?1
            OR qualified_name = ?1
            OR name LIKE '%.' || ?1){}",
        category_filter
    );
    let mut stmt = conn.prepare(&sql)?;

    let mut rows = stmt.query(params![query])?;

    while let Some(row) = rows.next()? {
        let node_id: String = row.get(0)?;
        let qualified_name: Option<String> = row.get(3)?;

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
            node_category: row.get(10)?,
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
    let bm25_results = bm25_search_v3(conn, query, remaining * 3, &category_filter)?;

    for (node_id, raw_score, mut result) in bm25_results {
        if results.contains_key(&node_id) {
            continue;
        }

        // Normalize BM25 to 0-1: score / (score + k), k=10
        let bm25_score = raw_score / (raw_score + 10.0);

        // -- Phase 3: Importance Tiebreak --
        // 85% BM25, 15% PageRank
        result.score = 0.85 * bm25_score + 0.15 * result.importance_score;
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
    category_filter: &str,
) -> Result<Vec<(String, f32, SearchResult)>> {
    // Expand abbreviations into extra OR terms so "authentication" also
    // matches nodes indexed only under "auth" (and vice versa).
    let expanded_query = expand_query(query);

    // Try FTS first
    let sql = format!(
        "SELECT id, type, name, qualified_name, file_path, line_start, line_end,
                importance_score, summary_text, source_text, node_category,
                fts_main_nodes.match_bm25(id, ?1) AS bm25_score
         FROM nodes
         WHERE bm25_score IS NOT NULL{}
         ORDER BY bm25_score DESC
         LIMIT ?2",
        category_filter
    );
    let fts_result = conn.prepare(&sql);

    match fts_result {
        Ok(mut stmt) => {
            let mut rows = stmt.query(params![expanded_query, limit as i64])?;
            let mut results = Vec::new();

            while let Some(row) = rows.next()? {
                let node_id: String = row.get(0)?;
                let bm25_score: f64 = row.get(11)?;

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
                        node_category: row.get(10)?,
                        score: 0.0,
                        match_type: MatchType::Bm25,
                    },
                ));
            }
            Ok(results)
        }
        Err(_) => {
            // FTS not available, fall back to LIKE search
            fallback_keyword_search(conn, query, limit, category_filter)
        }
    }
}

/// Fallback keyword search when FTS is not available.
fn fallback_keyword_search(
    conn: &Connection,
    query: &str,
    limit: usize,
    category_filter: &str,
) -> Result<Vec<(String, f32, SearchResult)>> {
    let keywords: Vec<&str> = query.split_whitespace().collect();
    if keywords.is_empty() {
        return Ok(Vec::new());
    }

    // Each keyword becomes an OR-group over the keyword itself plus its
    // abbreviation variants; groups stay ANDed so multi-term queries still
    // narrow. Positional params (?1, ?2, ...) are allocated per variant.
    let mut conditions: Vec<String> = Vec::new();
    let mut param_values: Vec<Box<dyn duckdb::ToSql>> = Vec::new();
    for keyword in &keywords {
        let mut terms = vec![keyword.to_string()];
        terms.extend(abbreviation_variants(keyword));

        let alternatives: Vec<String> = terms
            .into_iter()
            .map(|term| {
                param_values.push(Box::new(term) as Box<dyn duckdb::ToSql>);
                let p = param_values.len(); // 1-indexed param
                format!("search_text LIKE '%' || ?{p} || '%' OR name LIKE '%' || ?{p} || '%'")
            })
            .collect();
        conditions.push(format!("({})", alternatives.join(" OR ")));
    }

    let limit_param = param_values.len() + 1;
    let where_clause = conditions.join(" AND ");
    let sql = format!(
        "SELECT id, type, name, qualified_name, file_path, line_start, line_end,
                importance_score, summary_text, source_text, node_category
         FROM nodes
         WHERE {where_clause}{category_filter}
         ORDER BY importance_score DESC
         LIMIT ?{limit_param}"
    );

    let mut stmt = conn.prepare(&sql)?;

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
                node_category: row.get(10)?,
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
                    node_category: "production".to_string(),
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
                node_category: "production".to_string(),
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
            node_category: "production".to_string(),
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
                node_category: "production".to_string(),
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
                node_category: "production".to_string(),
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
            node_category: "production".to_string(),
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

    // -- search cascade tests against a real V3 database --

    /// MUbase::open on a fresh path creates the full V3 schema.
    fn open_test_db() -> crate::engine::storage::MUbase {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("test.mubase");
        std::mem::forget(dir);
        crate::engine::storage::MUbase::open(&db_path).unwrap()
    }

    fn insert_node(
        db: &crate::engine::storage::MUbase,
        id: &str,
        name: &str,
        search_text: &str,
        importance: f32,
    ) {
        db.with_connection(|conn| {
            conn.execute(
                "INSERT INTO nodes (id, type, name, file_path, line_start, line_end,
                                    importance_score, search_text, node_category)
                 VALUES (?, 'function', ?, 'src/lib.rs', 1, 10, ?, ?, 'production')",
                params![id, name, importance, search_text],
            )?;
            Ok(())
        })
        .unwrap();
    }

    #[test]
    fn test_search_nodes_exact_match() {
        let db = open_test_db();
        insert_node(
            &db,
            "fn:1",
            "parse_config",
            "parse configuration loader",
            0.1,
        );
        // A BM25/LIKE candidate with much higher importance must not beat the exact hit.
        insert_node(
            &db,
            "fn:2",
            "load_settings",
            "parse_config helper wrapper",
            0.9,
        );

        let results = db.search_v3("parse_config", 10).unwrap();

        assert!(!results.is_empty());
        assert_eq!(results[0].node_id, "fn:1");
        assert_eq!(results[0].match_type, MatchType::ExactName);
        assert_eq!(results[0].score, 1.0);
    }

    #[test]
    fn test_search_nodes_bm25_with_importance() {
        let db = open_test_db();
        // Identical search_text -> identical BM25 contribution, so the 15%
        // importance term decides the order (85/15 blend).
        insert_node(&db, "fn:low", "handle_a", "token stream lexer parser", 0.1);
        insert_node(&db, "fn:high", "handle_b", "token stream lexer parser", 0.9);
        // Build the FTS index when the extension is available; the LIKE
        // fallback exercises the same blend contract otherwise.
        let _ = db.rebuild_fts_on_search_text();

        let results = db.search_v3("token lexer", 10).unwrap();

        assert_eq!(results.len(), 2);
        assert_eq!(results[0].node_id, "fn:high");
        assert_eq!(results[1].node_id, "fn:low");
        assert_eq!(results[0].match_type, MatchType::Bm25);
        // Equal BM25 means the score gap is exactly 0.15 * (0.9 - 0.1).
        let gap = results[0].score - results[1].score;
        assert!((gap - 0.12).abs() < 1e-3, "score gap was {}", gap);
    }

    #[test]
    fn test_search_nodes_fallback_keyword() {
        let db = open_test_db();
        // No FTS index exists on a fresh db -> bm25_search_v3 must fall back
        // to the LIKE keyword search and still produce scored results.
        insert_node(&db, "fn:w", "build_widget", "widget factory builder", 0.4);

        let results = db.search_v3("widget factory", 10).unwrap();

        assert_eq!(results.len(), 1);
        assert_eq!(results[0].node_id, "fn:w");
        assert_eq!(results[0].match_type, MatchType::Bm25);
        // Synthetic raw score 5.0: 0.85 * (5/15) + 0.15 * 0.4
        let expected = 0.85 * (5.0 / 15.0) + 0.15 * 0.4;
        assert!(
            (results[0].score - expected).abs() < 1e-3,
            "score was {}",
            results[0].score
        );
    }

    #[test]
    fn test_search_nodes_dedup_exact_over_bm25() {
        let db = open_test_db();
        // Matches both the exact phase (name) and the keyword phase
        // (search_text contains the query) -> must appear once, as exact.
        insert_node(&db, "fn:g", "Gizmo", "Gizmo whatsit contraption", 0.5);

        let results = db.search_v3("Gizmo", 10).unwrap();

        let hits: Vec<_> = results.iter().filter(|r| r.node_id == "fn:g").collect();
        assert_eq!(hits.len(), 1, "node must not be duplicated across phases");
        assert_eq!(hits[0].match_type, MatchType::ExactName);
        assert_eq!(hits[0].score, 1.0);
    }

    // -- abbreviation expansion tests --

    #[test]
    fn test_expand_query_short_to_long() {
        let expanded = expand_query("auth flow");
        let terms: Vec<&str> = expanded.split_whitespace().collect();
        assert!(terms.contains(&"auth"));
        assert!(terms.contains(&"authentication"));
        assert!(terms.contains(&"authorization"));
        assert!(terms.contains(&"flow"));
    }

    #[test]
    fn test_expand_query_long_to_short() {
        assert_eq!(expand_query("database"), "database db");
        assert_eq!(
            expand_query("Configuration loader"),
            "Configuration loader config"
        );
    }

    #[test]
    fn test_expand_query_no_table_hit_is_identity() {
        assert_eq!(expand_query("widget factory"), "widget factory");
    }

    #[test]
    fn test_expand_query_val_is_skipped() {
        // "val" is ambiguous (validation vs value) and deliberately not expanded.
        assert_eq!(expand_query("val"), "val");
        assert_eq!(expand_query("validation"), "validation");
        assert_eq!(expand_query("value"), "value");
    }

    #[test]
    fn test_expand_query_no_duplicate_terms() {
        // Both directions present already -> nothing appended twice.
        assert_eq!(expand_query("db database"), "db database");
    }

    #[test]
    fn test_search_full_word_matches_abbreviated_node() {
        let db = open_test_db();
        // The eval failure: name tokenizes to "auth", which neither exact-
        // nor prefix-matches "authentication". The abbreviation table must
        // bridge the gap in the BM25/keyword phase.
        insert_node(
            &db,
            "fn:auth",
            "DomAuthMiddleware",
            "dom auth middleware handler",
            0.5,
        );
        insert_node(&db, "fn:other", "CacheWarmer", "cache warm preload", 0.5);
        // Exercise the FTS path when the extension is available; the LIKE
        // fallback covers the same contract otherwise.
        let _ = db.rebuild_fts_on_search_text();

        let results = db.search_v3("authentication", 10).unwrap();

        assert!(!results.is_empty(), "expansion must produce a match");
        assert_eq!(results[0].node_id, "fn:auth");
        assert!(results.iter().all(|r| r.node_id != "fn:other"));
    }

    #[test]
    fn test_search_abbreviation_matches_full_word_node() {
        let db = open_test_db();
        // Reverse direction: short query term, long form in search_text.
        insert_node(
            &db,
            "fn:cfg",
            "ConfigurationLoader",
            "configuration loader parser",
            0.5,
        );
        let _ = db.rebuild_fts_on_search_text();

        let results = db.search_v3("config loader", 10).unwrap();

        assert!(!results.is_empty());
        assert_eq!(results[0].node_id, "fn:cfg");
    }

    #[test]
    fn test_search_exact_name_phase_unaffected_by_expansion() {
        let db = open_test_db();
        // A node literally named "auth" must still be an exact match with
        // score 1.0, beating any expanded BM25 candidate.
        insert_node(&db, "fn:exact", "auth", "auth entrypoint", 0.1);
        insert_node(
            &db,
            "fn:bm25",
            "AuthenticationService",
            "authentication service",
            0.9,
        );

        let results = db.search_v3("auth", 10).unwrap();

        assert_eq!(results[0].node_id, "fn:exact");
        assert_eq!(results[0].match_type, MatchType::ExactName);
        assert_eq!(results[0].score, 1.0);
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
            node_category: "production".to_string(),
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
            node_category: "production".to_string(),
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
    fn test_confidence_abbreviation_match_promotes_to_high() {
        // "authentication middleware" -> DomAuthMiddleware: "middleware" is a
        // substring, "authentication" only matches via the abbreviation table.
        let results = vec![
            make_named_result("DomAuthMiddleware", 0.35),
            make_named_result("OtherThing", 0.30),
            make_named_result("Random", 0.25),
        ];
        assert_eq!(
            compute_confidence(&results, "authentication middleware"),
            SearchConfidence::High
        );
    }

    #[test]
    fn test_confidence_no_query_no_substring_check() {
        // Empty query should behave the same as before
        let results = make_results(&[0.40, 0.35, 0.25, 0.15, 0.10]);
        assert_eq!(compute_confidence(&results, ""), SearchConfidence::Medium);
    }
}
