//! V3 MCP tool implementations.
//!
//! Pure functions that take a MUbase and return formatted strings.
//! Each tool builds a structured response (from super::responses) first,
//! then formats it into markdown. Called from the tool handlers in server.rs.

use anyhow::Result;
use crate::engine::storage::{MUbase, Node};
use super::responses::{
    NodeResult, EdgeResult, SearchResponse, SearchConfidence, EnrichmentHint,
    ExpandResponse, ReadResponse, ReadNodeResult,
    format_search_response, format_expand_response, format_read_response,
};
use crate::engine::search::{
    SearchConfidence as EngineConfidence,
    compute_confidence,
};
use rmcp::schemars::JsonSchema;
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::fmt::Write;
use std::fs;
use std::path::Path;

// ============================================================================
// Lenient serde deserializers for MCP parameter tolerance
//
// MCP clients (Claude Code, etc.) sometimes send numbers as strings ("3"
// instead of 3) and arrays as JSON-encoded strings ("[\"a\"]" instead of
// ["a"]). These deserializers accept both forms.
// ============================================================================

pub mod lenient {
    use serde::{Deserialize, Deserializer, de};

    /// Accepts both `3` and `"3"` → `Option<usize>`
    pub fn option_usize<'de, D: Deserializer<'de>>(d: D) -> Result<Option<usize>, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Val {
            Num(usize),
            Str(String),
            Null,
        }
        match Option::<Val>::deserialize(d)? {
            None | Some(Val::Null) => Ok(None),
            Some(Val::Num(n)) => Ok(Some(n)),
            Some(Val::Str(s)) => s.parse().map(Some).map_err(de::Error::custom),
        }
    }

    /// Accepts both `1` and `"1"` → `Option<u8>`
    pub fn option_u8<'de, D: Deserializer<'de>>(d: D) -> Result<Option<u8>, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Val {
            Num(u8),
            Str(String),
            Null,
        }
        match Option::<Val>::deserialize(d)? {
            None | Some(Val::Null) => Ok(None),
            Some(Val::Num(n)) => Ok(Some(n)),
            Some(Val::Str(s)) => s.parse().map(Some).map_err(de::Error::custom),
        }
    }

    /// Accepts both `15` and `"15"` → `Option<i64>`
    pub fn option_i64<'de, D: Deserializer<'de>>(d: D) -> Result<Option<i64>, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Val {
            Num(i64),
            Str(String),
            Null,
        }
        match Option::<Val>::deserialize(d)? {
            None | Some(Val::Null) => Ok(None),
            Some(Val::Num(n)) => Ok(Some(n)),
            Some(Val::Str(s)) => s.parse().map(Some).map_err(de::Error::custom),
        }
    }

    /// Accepts both `30` and `"30"` → `Option<u32>`
    pub fn option_u32<'de, D: Deserializer<'de>>(d: D) -> Result<Option<u32>, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Val {
            Num(u32),
            Str(String),
            Null,
        }
        match Option::<Val>::deserialize(d)? {
            None | Some(Val::Null) => Ok(None),
            Some(Val::Num(n)) => Ok(Some(n)),
            Some(Val::Str(s)) => s.parse().map(Some).map_err(de::Error::custom),
        }
    }

    /// Accepts both `true` and `"true"` → `Option<bool>`
    pub fn option_bool<'de, D: Deserializer<'de>>(d: D) -> Result<Option<bool>, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Val {
            Bool(bool),
            Str(String),
            Null,
        }
        match Option::<Val>::deserialize(d)? {
            None | Some(Val::Null) => Ok(None),
            Some(Val::Bool(b)) => Ok(Some(b)),
            Some(Val::Str(s)) => match s.as_str() {
                "true" | "1" | "yes" => Ok(Some(true)),
                "false" | "0" | "no" => Ok(Some(false)),
                _ => Err(de::Error::custom(format!("invalid bool string: {}", s))),
            },
        }
    }

    /// Accepts `["a","b"]`, `"[\"a\",\"b\"]"`, or single `"a"` → `Vec<String>`
    pub fn vec_string<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<String>, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Val {
            Arr(Vec<String>),
            Str(String),
        }
        match Val::deserialize(d)? {
            Val::Arr(v) => Ok(v),
            Val::Str(s) => {
                // Try JSON-encoded array first, then treat as single element
                if s.starts_with('[') {
                    serde_json::from_str::<Vec<String>>(&s).map_err(de::Error::custom)
                } else {
                    Ok(vec![s])
                }
            }
        }
    }

    /// Same as `vec_string` but for `Option<Vec<String>>`
    pub fn option_vec_string<'de, D: Deserializer<'de>>(d: D) -> Result<Option<Vec<String>>, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Val {
            Arr(Vec<String>),
            Str(String),
            Null,
        }
        match Option::<Val>::deserialize(d)? {
            None | Some(Val::Null) => Ok(None),
            Some(Val::Arr(v)) => Ok(Some(v)),
            Some(Val::Str(s)) => {
                if s.starts_with('[') {
                    serde_json::from_str::<Vec<String>>(&s).map(Some).map_err(de::Error::custom)
                } else {
                    Ok(Some(vec![s]))
                }
            }
        }
    }
}

// ============================================================================
// MCP parameter structs
// ============================================================================

#[derive(Debug, Deserialize, JsonSchema)]
pub struct SearchNodesParams {
    /// Search query (natural language or symbol name)
    #[schemars(description = "Search query — natural language question or symbol name")]
    pub query: String,
    /// Max results (default: 10)
    #[schemars(description = "Maximum number of results (default: 10)")]
    #[serde(default, deserialize_with = "lenient::option_usize")]
    pub limit: Option<usize>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ExpandNodesParams {
    /// Node IDs to expand from
    #[schemars(description = "Node IDs to use as seeds (e.g., ['fn:src/main.rs:main'])")]
    #[serde(deserialize_with = "lenient::vec_string")]
    pub node_ids: Vec<String>,
    /// Traversal depth (default: 1)
    #[schemars(description = "How many hops to traverse (default: 1)")]
    #[serde(default, deserialize_with = "lenient::option_u8")]
    pub depth: Option<u8>,
    /// Filter by edge types
    #[schemars(description = "Edge types to follow (e.g., ['calls', 'imports']). All if omitted.")]
    #[serde(default, deserialize_with = "lenient::option_vec_string")]
    pub edge_types: Option<Vec<String>>,
    /// Direction: outgoing, incoming, or both (default: both)
    #[schemars(description = "Direction: 'outgoing', 'incoming', or 'both' (default: 'both')")]
    pub direction: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct ReadNodesParams {
    /// Node IDs to read
    #[schemars(description = "Node IDs to read (e.g., ['fn:src/main.rs:main'])")]
    #[serde(deserialize_with = "lenient::vec_string")]
    pub node_ids: Vec<String>,
    /// Read mode: signature, summary, source, full (default: source)
    #[schemars(description = "Detail level: 'signature', 'summary', 'source', or 'full' (default: 'source')")]
    pub mode: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct PackContextParams {
    /// Optional task description for context-aware packing
    #[schemars(description = "Task description (e.g., 'fix the login bug'). If omitted, returns top nodes by importance.")]
    pub task: Option<String>,
    /// Specific node IDs to pack
    #[schemars(description = "Specific node IDs to include. If omitted with task, searches for relevant nodes.")]
    #[serde(default, deserialize_with = "lenient::option_vec_string")]
    pub node_ids: Option<Vec<String>>,
    /// Token budget (default: 4000)
    #[schemars(description = "Maximum approximate tokens to return (default: 4000)")]
    #[serde(default, deserialize_with = "lenient::option_usize")]
    pub budget: Option<usize>,
    /// Grouping style: grouped (by file) or flat (default: grouped)
    #[schemars(description = "Output style: 'grouped' (by file) or 'flat' (default: 'grouped')")]
    pub style: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct EnrichNodesParams {
    /// Node IDs to get enrichment candidates for
    #[schemars(description = "Filter to specific node IDs (optional)")]
    #[serde(default, deserialize_with = "lenient::option_vec_string")]
    pub node_ids: Option<Vec<String>>,
    /// Summaries to store (node_id + summary pairs)
    #[schemars(description = "Summaries to store: [{node_id: '...', summary: '...'}]")]
    pub summaries: Option<Vec<EnrichSummary>>,
}

#[derive(Debug, Deserialize, JsonSchema)]
pub struct EnrichSummary {
    pub node_id: String,
    pub summary: String,
}

// ============================================================================
// Handler wrappers (called from server.rs)
// ============================================================================

pub fn handle_search_nodes(mubase: &MUbase, project_root: &Path, params: &SearchNodesParams) -> Result<String> {
    let limit = params.limit.unwrap_or(10);
    let config = crate::engine::auto_config::AutoConfig::load(project_root);
    let dampening = config.as_ref()
        .map(|c| c.filters.search_test_dampening)
        .unwrap_or(0.3);
    let resp = build_search_response_with_dampening(mubase, &params.query, limit, dampening)?;
    Ok(format_search_response(&resp, project_root))
}

pub fn handle_expand_nodes(mubase: &MUbase, params: &ExpandNodesParams) -> Result<String> {
    let depth = params.depth.unwrap_or(1);
    let direction = params.direction.as_deref().unwrap_or("both");
    let edge_types = params.edge_types.as_deref();
    expand_nodes_tool(mubase, &params.node_ids, depth, edge_types, direction)
}

pub fn handle_read_nodes(mubase: &MUbase, project_root: &Path, params: &ReadNodesParams) -> Result<String> {
    let mode = params.mode.as_deref().unwrap_or("source");
    read_nodes_tool(mubase, project_root, &params.node_ids, mode)
}

pub fn handle_pack_context(mubase: &MUbase, project_root: &Path, params: &PackContextParams) -> Result<String> {
    let budget = params.budget.unwrap_or(4000);
    let style = params.style.as_deref().unwrap_or("grouped");
    let config = crate::engine::auto_config::AutoConfig::load(project_root);

    // If task is provided but no node_ids, search for relevant nodes first
    if let Some(ref task) = params.task {
        if params.node_ids.is_none() {
            let dampening = config.as_ref()
                .map(|c| c.filters.search_test_dampening)
                .unwrap_or(0.3);
            let search_results = mubase.search_v3_with_dampening(task, 20, dampening)?;
            let ids: Vec<String> = search_results.iter().map(|r| r.node_id.clone()).collect();
            if ids.is_empty() {
                return pack_context_tool(mubase, project_root, None, budget, style, config.as_ref());
            }
            return pack_context_tool(mubase, project_root, Some(&ids), budget, style, config.as_ref());
        }
    }

    let node_ids = params.node_ids.as_deref();
    pack_context_tool(mubase, project_root, node_ids, budget, style, config.as_ref())
}

pub fn handle_enrich_nodes(mubase: &MUbase, project_root: &Path, params: &EnrichNodesParams) -> Result<String> {
    let config = crate::engine::auto_config::AutoConfig::load(project_root);
    let node_ids = params.node_ids.as_deref();
    let summaries: Option<Vec<(String, String)>> = params.summaries.as_ref().map(|s| {
        s.iter().map(|es| (es.node_id.clone(), es.summary.clone())).collect()
    });
    let summary_refs: Option<&[(String, String)]> = summaries.as_deref();
    enrich_nodes_tool(mubase, node_ids, summary_refs, config.as_ref())
}

// ============================================================================
// 1. search_nodes_tool
// ============================================================================

/// Build a structured SearchResponse from search results.
#[allow(dead_code)]
pub fn build_search_response(mubase: &MUbase, query: &str, limit: usize) -> Result<SearchResponse> {
    let results = mubase.search_v3(query, limit)?;

    let mut enrichment_ids = Vec::new();

    let nodes: Vec<NodeResult> = results
        .iter()
        .map(|r| {
            let match_label = match r.match_type {
                crate::engine::search::MatchType::ExactName => "exact",
                crate::engine::search::MatchType::ExactQualifiedName => "exact-qn",
                crate::engine::search::MatchType::Bm25 => "bm25",
            };

            if r.importance_score > 0.3 && r.summary_text.is_none() {
                enrichment_ids.push(r.node_id.clone());
            }

            NodeResult {
                node_id: r.node_id.clone(),
                name: r.name.clone(),
                kind: r.node_type.clone(),
                file_path: r.file_path.clone().unwrap_or_default(),
                line_start: r.line_start.unwrap_or(0),
                line_end: r.line_end.unwrap_or(0),
                score: Some(r.score),
                match_type: Some(match_label.to_string()),
                importance: r.importance_score,
                summary: r.summary_text.clone(),
            }
        })
        .collect();

    let engine_confidence = compute_confidence(&results, query);
    let confidence = match engine_confidence {
        EngineConfidence::High => SearchConfidence::High,
        EngineConfidence::Medium => SearchConfidence::Medium,
        EngineConfidence::Low => SearchConfidence::Low,
        EngineConfidence::NoResults => SearchConfidence::NoResults,
    };

    let enrichment_opportunity = if enrichment_ids.is_empty() {
        None
    } else {
        Some(EnrichmentHint {
            node_ids: enrichment_ids,
            message: "Some high-importance results lack LLM summaries. \
                      Use `mu_enrich` to improve search quality.".to_string(),
        })
    };

    Ok(SearchResponse {
        results: nodes,
        query: query.to_string(),
        confidence,
        enrichment_opportunity,
    })
}

/// Search the code graph using the V3 three-phase cascade.
#[allow(dead_code)]
pub fn search_nodes_tool(mubase: &MUbase, project_root: &Path, query: &str, limit: usize) -> Result<String> {
    let resp = build_search_response(mubase, query, limit)?;
    Ok(format_search_response(&resp, project_root))
}

/// Like `build_search_response` but with configurable test dampening.
fn build_search_response_with_dampening(mubase: &MUbase, query: &str, limit: usize, dampening: f32) -> Result<SearchResponse> {
    let results = mubase.search_v3_with_dampening(query, limit, dampening)?;

    let mut enrichment_ids = Vec::new();
    let nodes: Vec<NodeResult> = results
        .iter()
        .map(|r| {
            let match_label = match r.match_type {
                crate::engine::search::MatchType::ExactName => "exact",
                crate::engine::search::MatchType::ExactQualifiedName => "exact-qn",
                crate::engine::search::MatchType::Bm25 => "bm25",
            };
            if r.importance_score > 0.3 && r.summary_text.is_none() {
                enrichment_ids.push(r.node_id.clone());
            }
            NodeResult {
                node_id: r.node_id.clone(),
                name: r.name.clone(),
                kind: r.node_type.clone(),
                file_path: r.file_path.clone().unwrap_or_default(),
                line_start: r.line_start.unwrap_or(0),
                line_end: r.line_end.unwrap_or(0),
                score: Some(r.score),
                match_type: Some(match_label.to_string()),
                importance: r.importance_score,
                summary: r.summary_text.clone(),
            }
        })
        .collect();

    let engine_confidence = compute_confidence(&results, query);
    let confidence = match engine_confidence {
        EngineConfidence::High => SearchConfidence::High,
        EngineConfidence::Medium => SearchConfidence::Medium,
        EngineConfidence::Low => SearchConfidence::Low,
        EngineConfidence::NoResults => SearchConfidence::NoResults,
    };

    let enrichment_opportunity = if enrichment_ids.is_empty() {
        None
    } else {
        Some(EnrichmentHint {
            node_ids: enrichment_ids,
            message: "Some high-importance results lack LLM summaries. \
                      Use `mu_enrich` to improve search quality.".to_string(),
        })
    };

    Ok(SearchResponse {
        results: nodes,
        query: query.to_string(),
        confidence,
        enrichment_opportunity,
    })
}

// ============================================================================
// 2. expand_nodes_tool
// ============================================================================

/// Build a structured ExpandResponse from graph traversal.
pub fn build_expand_response(
    mubase: &MUbase,
    node_ids: &[String],
    depth: u8,
    edge_types: Option<&[String]>,
    direction: &str,
) -> Result<ExpandResponse> {
    if node_ids.is_empty() {
        return Ok(ExpandResponse {
            seed_nodes: Vec::new(),
            neighbors: Vec::new(),
            edges: Vec::new(),
        });
    }

    let edge_filter = edge_types
        .filter(|et| !et.is_empty())
        .map(|et| {
            let quoted: Vec<String> = et.iter().map(|t| format!("'{}'", t.replace('\'', "''"))).collect();
            format!("AND e.type IN ({})", quoted.join(", "))
        })
        .unwrap_or_default();

    let mut visited: HashSet<String> = HashSet::new();
    let mut frontier: Vec<String> = node_ids.to_vec();
    // (source_id, source_name, target_id, target_name, edge_type)
    let mut all_edges: Vec<(String, String, String, String, String)> = Vec::new();
    // node_id -> (name, type, file_path)
    let mut node_info: HashMap<String, (String, String, Option<String>)> = HashMap::new();

    for nid in &frontier {
        if let Some(info) = fetch_node_info(mubase, nid) {
            node_info.insert(nid.clone(), info);
        }
        visited.insert(nid.clone());
    }

    for _current_depth in 0..depth {
        if frontier.is_empty() {
            break;
        }

        let mut next_frontier: Vec<String> = Vec::new();

        for nid in &frontier {
            if direction == "outgoing" || direction == "both" {
                let sql = format!(
                    "SELECT e.source_id, e.target_id, e.type, n.name, n.type AS ntype, n.file_path \
                     FROM edges e JOIN nodes n ON n.id = e.target_id \
                     WHERE e.source_id = ?1 {} LIMIT 50",
                    edge_filter
                );
                if let Ok(result) = mubase.query_params(&sql, &[&nid as &dyn duckdb::ToSql]) {
                    for row in &result.rows {
                        let source_id = row.first().and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let target_id = row.get(1).and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let etype = row.get(2).and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let target_name = row.get(3).and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let target_ntype = row.get(4).and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let target_file = row.get(5).and_then(|v| v.as_str()).map(|s| s.to_string());

                        let source_name = node_info
                            .get(&source_id)
                            .map(|(n, _, _)| n.clone())
                            .unwrap_or_else(|| source_id.clone());

                        all_edges.push((source_id.clone(), source_name, target_id.clone(), target_name.clone(), etype));
                        node_info
                            .entry(target_id.clone())
                            .or_insert((target_name, target_ntype, target_file));

                        if !visited.contains(&target_id) {
                            visited.insert(target_id.clone());
                            next_frontier.push(target_id);
                        }
                    }
                }
            }

            if direction == "incoming" || direction == "both" {
                let sql = format!(
                    "SELECT e.source_id, e.target_id, e.type, n.name, n.type AS ntype, n.file_path \
                     FROM edges e JOIN nodes n ON n.id = e.source_id \
                     WHERE e.target_id = ?1 {} LIMIT 50",
                    edge_filter
                );
                if let Ok(result) = mubase.query_params(&sql, &[&nid as &dyn duckdb::ToSql]) {
                    for row in &result.rows {
                        let source_id = row.first().and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let target_id = row.get(1).and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let etype = row.get(2).and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let source_name = row.get(3).and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let source_ntype = row.get(4).and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let source_file = row.get(5).and_then(|v| v.as_str()).map(|s| s.to_string());

                        let target_name = node_info
                            .get(&target_id)
                            .map(|(n, _, _)| n.clone())
                            .unwrap_or_else(|| target_id.clone());

                        all_edges.push((source_id.clone(), source_name.clone(), target_id.clone(), target_name, etype));
                        node_info
                            .entry(source_id.clone())
                            .or_insert((source_name, source_ntype, source_file));

                        if !visited.contains(&source_id) {
                            visited.insert(source_id.clone());
                            next_frontier.push(source_id);
                        }
                    }
                }
            }
        }

        frontier = next_frontier;
    }

    // Build structured response
    let seed_set: HashSet<&String> = node_ids.iter().collect();

    let mut seed_nodes = Vec::new();
    let mut neighbors = Vec::new();

    let mut sorted_ids: Vec<_> = node_info.keys().cloned().collect();
    sorted_ids.sort();

    for id in sorted_ids {
        let (name, ntype, file_path) = node_info.get(&id).unwrap();
        let node = NodeResult {
            node_id: id.clone(),
            name: name.clone(),
            kind: ntype.clone(),
            file_path: file_path.clone().unwrap_or_default(),
            line_start: 0,
            line_end: 0,
            score: None,
            match_type: None,
            importance: 0.0,
            summary: None,
        };
        if seed_set.contains(&id) {
            seed_nodes.push(node);
        } else {
            neighbors.push(node);
        }
    }

    // Dedup edges
    let mut seen_edges: HashSet<String> = HashSet::new();
    let edges: Vec<EdgeResult> = all_edges
        .into_iter()
        .filter(|(src_id, _, tgt_id, _, etype)| {
            let key = format!("{}->{}->{}", src_id, etype, tgt_id);
            seen_edges.insert(key)
        })
        .map(|(source_id, source_name, target_id, target_name, edge_type)| EdgeResult {
            source_id,
            source_name,
            target_id,
            target_name,
            edge_type,
        })
        .collect();

    Ok(ExpandResponse {
        seed_nodes,
        neighbors,
        edges,
    })
}

/// Expand the graph neighborhood around seed nodes.
pub fn expand_nodes_tool(
    mubase: &MUbase,
    node_ids: &[String],
    depth: u8,
    edge_types: Option<&[String]>,
    direction: &str,
) -> Result<String> {
    if node_ids.is_empty() {
        let mut out = String::new();
        writeln!(out, "# expand: 0 seed(s), depth={}, direction={}", depth, direction)?;
        writeln!(out, "No seed nodes provided.")?;
        return Ok(out);
    }

    if !["outgoing", "incoming", "both"].contains(&direction) {
        let mut out = String::new();
        writeln!(out, "Invalid direction '{}'. Use: outgoing, incoming, both", direction)?;
        return Ok(out);
    }

    let resp = build_expand_response(mubase, node_ids, depth, edge_types, direction)?;
    Ok(format_expand_response(&resp))
}

// ============================================================================
// 3. read_nodes_tool
// ============================================================================

/// Build a structured ReadResponse from node lookups.
pub fn build_read_response(
    mubase: &MUbase,
    project_root: &Path,
    node_ids: &[String],
    mode: &str,
) -> Result<ReadResponse> {
    let mut nodes = Vec::new();

    for nid in node_ids {
        let result = mubase.query_params(
            "SELECT id, type, name, qualified_name, file_path, line_start, line_end, \
                    complexity, source_text, summary_text, summary_source, importance_score \
             FROM nodes WHERE id = ?1",
            &[&nid as &dyn duckdb::ToSql],
        )?;
        if result.rows.is_empty() {
            continue;
        }

        let row = &result.rows[0];
        let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
        let name = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
        let file_path = row.get(4).and_then(|v| v.as_str());
        let line_start = row.get(5).and_then(|v| v.as_i64()).map(|v| v as u32);
        let line_end = row.get(6).and_then(|v| v.as_i64()).map(|v| v as u32);
        let source_text_db = row.get(8).and_then(|v| v.as_str());
        let summary_text = row.get(9).and_then(|v| v.as_str());
        let importance = row.get(11).and_then(|v| v.as_f64()).unwrap_or(0.0);

        let node = NodeResult {
            node_id: nid.clone(),
            name: name.to_string(),
            kind: node_type.to_string(),
            file_path: file_path.unwrap_or("").to_string(),
            line_start: line_start.unwrap_or(0),
            line_end: line_end.unwrap_or(0),
            score: None,
            match_type: None,
            importance: importance as f32,
            summary: summary_text.map(|s| s.to_string()),
        };

        // Resolve source text
        let source = source_text_db
            .map(|s| s.to_string())
            .or_else(|| {
                file_path.and_then(|fp| {
                    let full_path = project_root.join(fp);
                    read_source_lines(&full_path, line_start, line_end, 100)
                })
            });

        // Extract signature
        let signature = source_text_db
            .and_then(extract_signature_line)
            .or_else(|| source.as_deref().and_then(extract_signature_line));

        // Neighbors (only for full mode)
        let neighbors = if mode == "full" {
            if let Ok(neighbor_result) = mubase.query_params(
                "SELECT DISTINCT n.id, n.name, n.type, n.file_path, e.type AS etype \
                 FROM edges e JOIN nodes n ON (n.id = e.target_id OR n.id = e.source_id) \
                 WHERE (e.source_id = ?1 OR e.target_id = ?1) AND n.id != ?1 \
                 LIMIT 20",
                &[&nid as &dyn duckdb::ToSql],
            ) {
                neighbor_result.rows.iter().map(|nrow| {
                    let n_id = nrow.first().and_then(|v| v.as_str()).unwrap_or("?");
                    let n_name = nrow.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                    let n_type = nrow.get(2).and_then(|v| v.as_str()).unwrap_or("?");
                    let n_file = nrow.get(3).and_then(|v| v.as_str()).unwrap_or("");
                    let edge_type = nrow.get(4).and_then(|v| v.as_str()).unwrap_or("related");

                    (edge_type.to_string(), NodeResult {
                        node_id: n_id.to_string(),
                        name: n_name.to_string(),
                        kind: n_type.to_string(),
                        file_path: n_file.to_string(),
                        line_start: 0,
                        line_end: 0,
                        score: None,
                        match_type: None,
                        importance: 0.0,
                        summary: None,
                    })
                }).collect()
            } else {
                Vec::new()
            }
        } else {
            Vec::new()
        };

        nodes.push(ReadNodeResult {
            node,
            source_text: source,
            signature,
            neighbors,
        });
    }

    Ok(ReadResponse {
        nodes,
        mode: mode.to_string(),
    })
}

/// Read detailed information about specific nodes.
pub fn read_nodes_tool(
    mubase: &MUbase,
    project_root: &Path,
    node_ids: &[String],
    mode: &str,
) -> Result<String> {
    if node_ids.is_empty() {
        let mut out = String::new();
        writeln!(out, "# read: 0 node(s), mode={}\n", mode)?;
        writeln!(out, "No node IDs provided.")?;
        return Ok(out);
    }

    if !["signature", "summary", "source", "full"].contains(&mode) {
        let mut out = String::new();
        writeln!(out, "Invalid mode '{}'. Use: signature, summary, source, full", mode)?;
        return Ok(out);
    }

    let resp = build_read_response(mubase, project_root, node_ids, mode)?;

    // Check for not-found nodes
    let found_ids: HashSet<&str> = resp.nodes.iter().map(|rn| rn.node.node_id.as_str()).collect();
    let mut out = format_read_response(&resp, project_root);

    for nid in node_ids {
        if !found_ids.contains(nid.as_str()) {
            let _ = writeln!(out, "## {} -- NOT FOUND\n", nid);
        }
    }

    Ok(out)
}

// ============================================================================
// 4. pack_context_tool
// ============================================================================

/// Pack code context within a token budget, grouped by file.
pub fn pack_context_tool(
    mubase: &MUbase,
    project_root: &Path,
    node_ids: Option<&[String]>,
    budget: usize,
    style: &str,
    config: Option<&crate::engine::auto_config::AutoConfig>,
) -> Result<String> {
    let mut out = String::new();
    let approx_tokens = |s: &str| s.len() / 4;

    let nodes_to_pack: Vec<PackNode> = if let Some(ids) = node_ids {
        let mut nodes = Vec::new();
        for nid in ids {
            if let Ok(result) = mubase.query_params(
                "SELECT id, type, name, file_path, line_start, line_end, \
                        source_text, summary_text, importance_score \
                 FROM nodes WHERE id = ?1",
                &[&nid as &dyn duckdb::ToSql],
            ) {
                if let Some(row) = result.rows.first() {
                    nodes.push(pack_node_from_row(row));
                }
            }
        }
        nodes
    } else {
        let sql = "SELECT id, type, name, file_path, line_start, line_end, \
                          source_text, summary_text, importance_score \
                   FROM nodes \
                   WHERE type IN ('class', 'function') \
                   ORDER BY importance_score DESC \
                   LIMIT 100";
        mubase
            .query(sql)?
            .rows
            .iter()
            .map(|row| pack_node_from_row(row))
            .collect()
    };

    // Exclude migration/generated files — they waste token budget
    let nodes_to_pack: Vec<PackNode> = nodes_to_pack
        .into_iter()
        .filter(|n| {
            if let Some(cfg) = config {
                !crate::engine::auto_config::is_excluded_path(
                    n.file_path.as_deref().unwrap_or(""),
                    &cfg.oracle.exclude_patterns,
                )
            } else {
                !is_oracle_excluded(n.file_path.as_deref())
            }
        })
        .collect();

    // Apply test budget cap: limit test nodes to a fraction of total budget
    let test_budget_cap = config.map(|c| c.oracle.test_budget_cap).unwrap_or(1.0);
    let test_patterns = config.map(|c| &c.filters.test_patterns);
    let max_test_nodes = if test_budget_cap < 1.0 {
        (nodes_to_pack.len() as f32 * test_budget_cap).ceil() as usize
    } else {
        nodes_to_pack.len()
    };

    let mut test_count = 0usize;
    let nodes_to_pack: Vec<PackNode> = nodes_to_pack
        .into_iter()
        .filter(|n| {
            let is_test = if let Some(patterns) = test_patterns {
                crate::engine::auto_config::is_test_path(
                    n.file_path.as_deref().unwrap_or(""),
                    patterns,
                )
            } else {
                crate::engine::search::is_test_or_migration(n.file_path.as_deref())
            };
            if is_test {
                test_count += 1;
                test_count <= max_test_nodes
            } else {
                true
            }
        })
        .collect();

    let is_overview = node_ids.is_none();
    if is_overview {
        writeln!(out, "# Project Context (top by importance, budget={})\n", budget)?;
    } else {
        writeln!(out, "# Context Pack ({} node(s), budget={})\n", nodes_to_pack.len(), budget)?;
    }

    let mut used_tokens = approx_tokens(&out);
    let mut packed_count = 0;
    let mut degraded_count = 0;

    let grouped = if style == "grouped" || is_overview {
        group_by_file(&nodes_to_pack)
    } else {
        let mut flat: Vec<(String, Vec<&PackNode>)> = Vec::new();
        for node in &nodes_to_pack {
            let key = node.file_path.clone().unwrap_or_else(|| "unknown".to_string());
            if let Some(entry) = flat.iter_mut().find(|(k, _)| k == &key) {
                entry.1.push(node);
            } else {
                flat.push((key, vec![node]));
            }
        }
        flat
    };

    for (file_path, file_nodes) in &grouped {
        if used_tokens >= budget {
            break;
        }

        let file_header = format!("## {}\n", file_path);
        let header_tokens = approx_tokens(&file_header);

        if used_tokens + header_tokens >= budget {
            break;
        }

        writeln!(out, "{}", file_header.trim_end())?;
        used_tokens += header_tokens;

        for node in file_nodes {
            if used_tokens >= budget {
                break;
            }

            let sigil = type_sigil(&node.node_type);

            let source = node.source_text.as_deref()
                .map(|s| s.to_string())
                .or_else(|| {
                    node.file_path.as_ref().and_then(|fp| {
                        let full_path = project_root.join(fp);
                        read_source_lines(&full_path, node.line_start, node.line_end, 80)
                    })
                });

            if let Some(ref src) = source {
                let full_block = format!(
                    "### {}{} [{}]\nid: {}\n```\n{}\n```\n",
                    sigil, node.name, node.node_type, node.id, src
                );
                let block_tokens = approx_tokens(&full_block);

                if used_tokens + block_tokens <= budget {
                    write!(out, "{}", full_block)?;
                    used_tokens += block_tokens;
                    packed_count += 1;
                    continue;
                }
            }

            // Graceful degradation
            let sig = source
                .as_deref()
                .and_then(extract_signature_line)
                .unwrap_or_else(|| node.name.clone());
            let summary = node.summary_text.as_deref().unwrap_or("(no summary)");

            let degraded_block = format!(
                "### {}{} [{}]\nid: {}\n`{}`\n{}\n",
                sigil, node.name, node.node_type, node.id, sig, summary
            );
            let block_tokens = approx_tokens(&degraded_block);

            if used_tokens + block_tokens <= budget {
                write!(out, "{}", degraded_block)?;
                used_tokens += block_tokens;
                packed_count += 1;
                degraded_count += 1;
            } else {
                break;
            }
        }
    }

    writeln!(out)?;
    writeln!(
        out,
        "---\nPacked {} nodes (~{} tokens). {} included as signature+summary only.",
        packed_count, used_tokens, degraded_count
    )?;

    if packed_count < nodes_to_pack.len() {
        writeln!(
            out,
            "{} nodes omitted (budget exhausted). Increase budget or be more selective.",
            nodes_to_pack.len() - packed_count
        )?;
    }

    Ok(out)
}

// ============================================================================
// 5. enrich_nodes_tool
// ============================================================================

/// Enrich nodes with LLM-generated summaries, or return candidates for enrichment.
pub fn enrich_nodes_tool(
    mubase: &MUbase,
    node_ids: Option<&[String]>,
    summaries: Option<&[(String, String)]>,
    config: Option<&crate::engine::auto_config::AutoConfig>,
) -> Result<String> {
    let mut out = String::new();

    if let Some(summaries) = summaries {
        writeln!(out, "# enrich: storing {} summaries\n", summaries.len())?;

        let mut stored = 0;
        let mut errors = Vec::new();

        for (node_id, summary) in summaries {
            let code_hash = if let Ok(result) = mubase.query_params(
                "SELECT source_text FROM nodes WHERE id = ?1",
                &[&node_id as &dyn duckdb::ToSql],
            ) {
                result.rows.first()
                    .and_then(|r| r.first())
                    .and_then(|v| v.as_str())
                    .map(crate::engine::summary::compute_code_hash)
                    .unwrap_or_else(|| "unknown".to_string())
            } else {
                "unknown".to_string()
            };

            match mubase.update_summary(node_id, summary, "llm", &code_hash) {
                Ok(()) => {
                    if let Ok(result) = mubase.query_params(
                        "SELECT id, type, name, qualified_name, file_path FROM nodes WHERE id = ?1",
                        &[&node_id as &dyn duckdb::ToSql],
                    ) {
                        if let Some(row) = result.rows.first() {
                            let name = row.get(2).and_then(|v| v.as_str()).unwrap_or("");
                            let qn = row.get(3).and_then(|v| v.as_str());
                            let fp = row.get(4).and_then(|v| v.as_str());

                            let mut parts = vec![summary.as_str()];
                            parts.push(name);
                            if let Some(q) = qn { parts.push(q); }
                            if let Some(f) = fp { parts.push(f); }
                            let search_text = parts.join(" | ");
                            let _ = mubase.update_search_text(node_id, &search_text);
                        }
                    }
                    stored += 1;
                }
                Err(e) => {
                    errors.push(format!("{}: {}", node_id, e));
                }
            }
        }

        writeln!(out, "Stored {} summaries.", stored)?;
        if !errors.is_empty() {
            writeln!(out, "\nErrors:")?;
            for e in &errors { writeln!(out, "  - {}", e)?; }
        }

        match mubase.rebuild_fts_on_search_text() {
            Ok(true) => writeln!(out, "\nFTS index rebuilt.")?,
            Ok(false) => writeln!(out, "\nFTS index: no nodes to index.")?,
            Err(e) => writeln!(out, "\nFTS rebuild failed: {}", e)?,
        }
    } else {
        let top_n = config.map(|c| c.enrichment.auto_enrich_top_n).unwrap_or(20);
        let limit = top_n.min(50);
        let filter_ids: Option<HashSet<&str>> = node_ids.map(|ids| ids.iter().map(|s| s.as_str()).collect());

        let unsummarized = mubase.get_unsummarized_nodes(if filter_ids.is_some() { 200 } else { limit })?;

        let priority_ids: Option<HashSet<&str>> = config
            .filter(|c| !c.enrichment.priority_nodes.is_empty())
            .map(|c| c.enrichment.priority_nodes.iter().map(|s| s.as_str()).collect());

        let mut candidates: Vec<&Node> = if let Some(ref filter) = filter_ids {
            unsummarized.iter().filter(|n| filter.contains(n.id.as_str())).collect()
        } else {
            unsummarized.iter().take(limit).collect()
        };

        // Sort: priority nodes first, then by importance
        if let Some(ref pids) = priority_ids {
            candidates.sort_by(|a, b| {
                let a_pri = pids.contains(a.id.as_str());
                let b_pri = pids.contains(b.id.as_str());
                match (a_pri, b_pri) {
                    (true, false) => std::cmp::Ordering::Less,
                    (false, true) => std::cmp::Ordering::Greater,
                    _ => b.importance_score.partial_cmp(&a.importance_score)
                        .unwrap_or(std::cmp::Ordering::Equal),
                }
            });
        }

        writeln!(out, "# enrich: {} candidates for enrichment\n", candidates.len())?;

        if candidates.is_empty() {
            writeln!(out, "All nodes already have LLM summaries, or no nodes match the filter.")?;
            return Ok(out);
        }

        writeln!(out, "## Prompt Guidance\n")?;
        writeln!(
            out,
            "For each node below, write a 1-2 sentence summary describing what it does, \
             its role in the codebase, and key relationships. Focus on information that would \
             help someone searching for this code. Then call `mu_enrich` with the summaries.\n"
        )?;

        writeln!(out, "## Candidates\n")?;
        for node in &candidates {
            let sigil = type_sigil(node.node_type.as_str());
            let location = node.file_path.as_deref().unwrap_or("unknown");

            writeln!(
                out,
                "### {}{} [{}] -- {} (importance: {:.2})",
                sigil, node.name, node.node_type.as_str(), location, node.importance_score
            )?;
            writeln!(out, "id: `{}`", node.id)?;

            if let Some(ref src) = node.source_text {
                let preview = truncate_str(src, 500);
                writeln!(out, "```")?;
                writeln!(out, "{}", preview)?;
                writeln!(out, "```")?;
            }

            if let Some(ref summary) = node.summary_text {
                writeln!(out, "Current heuristic summary: {}", summary)?;
            }

            writeln!(out)?;
        }

        writeln!(
            out,
            "---\nCall `mu_enrich` with summaries parameter to store results. \
             Example: summaries: [{{node_id: \"...\", summary: \"...\"}}, ...]"
        )?;
    }

    Ok(out)
}

// ============================================================================
// Helpers
// ============================================================================

fn type_sigil(node_type: &str) -> &'static str {
    match node_type {
        "module" => "!",
        "class" => "$",
        "function" => "#",
        "message" => "@",
        _ => "@",
    }
}

fn truncate_str(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        let mut end = max;
        while !s.is_char_boundary(end) { end -= 1; }
        format!("{}...", &s[..end])
    }
}

fn read_source_lines(
    path: &Path,
    line_start: Option<u32>,
    line_end: Option<u32>,
    max_lines: usize,
) -> Option<String> {
    let content = fs::read_to_string(path).ok()?;
    let lines: Vec<&str> = content.lines().collect();

    let start = line_start.unwrap_or(1).saturating_sub(1) as usize;
    let end = line_end.map(|e| e as usize).unwrap_or(lines.len()).min(lines.len());

    if start >= lines.len() {
        return None;
    }

    let actual_end = end.min(start + max_lines);
    let snippet: Vec<&str> = lines[start..actual_end].to_vec();
    let mut result = snippet.join("\n");
    if actual_end < end {
        result.push_str("\n// ... (truncated)");
    }
    Some(result)
}

fn extract_signature_line(source: &str) -> Option<String> {
    let sig_prefixes = [
        "fn ", "pub fn ", "pub async fn ", "async fn ",
        "pub(crate) fn ", "pub(super) fn ",
        "def ", "async def ",
        "func ", "public func ", "private func ",
        "function ", "export function ", "async function ",
        "public ", "private ", "protected ", "internal ",
        "class ", "struct ", "trait ", "interface ", "enum ",
        "pub struct ", "pub trait ", "pub enum ",
    ];

    for line in source.lines() {
        let trimmed = line.trim();
        for prefix in &sig_prefixes {
            if trimmed.starts_with(prefix) {
                return Some(trimmed.to_string());
            }
        }
    }
    None
}

/// Check if a file path should be excluded from oracle context packing.
///
/// Migration files, obj output, and generated code are never useful for
/// understanding architecture and waste token budget.
fn is_oracle_excluded(file_path: Option<&str>) -> bool {
    let Some(path) = file_path else { return false };
    let lower = path.to_lowercase();

    (lower.contains("/migrations/") && lower.ends_with(".cs"))
        || lower.contains("/obj/")
        || lower.ends_with(".generated.cs")
}

fn fetch_node_info(mubase: &MUbase, node_id: &str) -> Option<(String, String, Option<String>)> {
    let result = mubase.query_params(
        "SELECT name, type, file_path FROM nodes WHERE id = ?1",
        &[&node_id as &dyn duckdb::ToSql],
    ).ok()?;
    let row = result.rows.first()?;
    let name = row.first().and_then(|v| v.as_str())?.to_string();
    let ntype = row.get(1).and_then(|v| v.as_str())?.to_string();
    let file_path = row.get(2).and_then(|v| v.as_str()).map(|s| s.to_string());
    Some((name, ntype, file_path))
}

struct PackNode {
    #[allow(dead_code)]
    id: String,
    name: String,
    node_type: String,
    file_path: Option<String>,
    line_start: Option<u32>,
    line_end: Option<u32>,
    source_text: Option<String>,
    summary_text: Option<String>,
    #[allow(dead_code)]
    importance_score: f64,
}

fn pack_node_from_row(row: &[serde_json::Value]) -> PackNode {
    PackNode {
        id: row.first().and_then(|v| v.as_str()).unwrap_or("").to_string(),
        node_type: row.get(1).and_then(|v| v.as_str()).unwrap_or("").to_string(),
        name: row.get(2).and_then(|v| v.as_str()).unwrap_or("").to_string(),
        file_path: row.get(3).and_then(|v| v.as_str()).map(|s| s.to_string()),
        line_start: row.get(4).and_then(|v| v.as_i64()).map(|v| v as u32),
        line_end: row.get(5).and_then(|v| v.as_i64()).map(|v| v as u32),
        source_text: row.get(6).and_then(|v| v.as_str()).map(|s| s.to_string()),
        summary_text: row.get(7).and_then(|v| v.as_str()).map(|s| s.to_string()),
        importance_score: row.get(8).and_then(|v| v.as_f64()).unwrap_or(0.0),
    }
}

fn group_by_file<'a>(nodes: &'a [PackNode]) -> Vec<(String, Vec<&'a PackNode>)> {
    let mut groups: Vec<(String, Vec<&'a PackNode>)> = Vec::new();
    for node in nodes {
        let key = node.file_path.clone().unwrap_or_else(|| "unknown".to_string());
        if let Some(entry) = groups.iter_mut().find(|(k, _)| k == &key) {
            entry.1.push(node);
        } else {
            groups.push((key, vec![node]));
        }
    }
    groups
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn search_params_limit_as_number() {
        let v = json!({"query": "test", "limit": 5});
        let p: SearchNodesParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.limit, Some(5));
    }

    #[test]
    fn search_params_limit_as_string() {
        let v = json!({"query": "test", "limit": "5"});
        let p: SearchNodesParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.limit, Some(5));
    }

    #[test]
    fn search_params_limit_absent() {
        let v = json!({"query": "test"});
        let p: SearchNodesParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.limit, None);
    }

    #[test]
    fn expand_params_node_ids_as_array() {
        let v = json!({"node_ids": ["fn:a", "fn:b"], "depth": 2});
        let p: ExpandNodesParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.node_ids, vec!["fn:a", "fn:b"]);
        assert_eq!(p.depth, Some(2));
    }

    #[test]
    fn expand_params_node_ids_as_json_string() {
        let v = json!({"node_ids": "[\"fn:a\",\"fn:b\"]", "depth": "2"});
        let p: ExpandNodesParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.node_ids, vec!["fn:a", "fn:b"]);
        assert_eq!(p.depth, Some(2));
    }

    #[test]
    fn expand_params_single_node_id_string() {
        let v = json!({"node_ids": "fn:src/main.rs:main"});
        let p: ExpandNodesParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.node_ids, vec!["fn:src/main.rs:main"]);
    }

    #[test]
    fn read_params_node_ids_as_json_string() {
        let v = json!({"node_ids": "[\"fn:a\"]"});
        let p: ReadNodesParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.node_ids, vec!["fn:a"]);
    }

    #[test]
    fn pack_params_budget_as_string() {
        let v = json!({"budget": "4000"});
        let p: PackContextParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.budget, Some(4000));
    }

    #[test]
    fn pack_params_optional_node_ids_as_json_string() {
        let v = json!({"node_ids": "[\"fn:a\"]", "budget": 2000});
        let p: PackContextParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.node_ids, Some(vec!["fn:a".to_string()]));
        assert_eq!(p.budget, Some(2000));
    }

    #[test]
    fn edge_types_as_json_string() {
        let v = json!({"node_ids": ["fn:a"], "edge_types": "[\"calls\",\"imports\"]"});
        let p: ExpandNodesParams = serde_json::from_value(v).unwrap();
        assert_eq!(p.edge_types, Some(vec!["calls".to_string(), "imports".to_string()]));
    }

    // -- oracle exclusion tests --

    #[test]
    fn oracle_excludes_migration_cs_files() {
        assert!(is_oracle_excluded(Some("src/Migrations/20240101_Init.cs")));
        assert!(is_oracle_excluded(Some("src/Migrations/20240101_Init.Designer.cs")));
    }

    #[test]
    fn oracle_excludes_obj_dir() {
        assert!(is_oracle_excluded(Some("src/obj/Debug/net10.0/foo.dll")));
        assert!(is_oracle_excluded(Some("project/obj/Release/something.cs")));
    }

    #[test]
    fn oracle_excludes_generated_cs() {
        assert!(is_oracle_excluded(Some("src/Models/MyModel.generated.cs")));
    }

    #[test]
    fn oracle_keeps_production_code() {
        assert!(!is_oracle_excluded(Some("src/Services/PaymentService.cs")));
        assert!(!is_oracle_excluded(Some("src/engine/search.rs")));
        assert!(!is_oracle_excluded(None));
    }

    #[test]
    fn oracle_keeps_migration_non_cs() {
        // Non-.cs files in Migrations/ are fine (e.g., SQL scripts)
        assert!(!is_oracle_excluded(Some("db/Migrations/README.md")));
    }
}
