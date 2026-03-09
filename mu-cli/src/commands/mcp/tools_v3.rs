//! V3 MCP tool implementations.
//!
//! Pure functions that take a MUbase and return formatted strings.
//! Called from the tool handlers in server.rs.

use anyhow::Result;
use mu_daemon::storage::{MUbase, Node};
use std::collections::{HashMap, HashSet};
use std::fmt::Write;
use std::fs;
use std::path::Path;

// ============================================================================
// 1. search_nodes_tool
// ============================================================================

/// Search the code graph using the V3 three-phase cascade.
pub fn search_nodes_tool(mubase: &MUbase, project_root: &Path, query: &str, limit: usize) -> Result<String> {
    let results = mubase.search_v3(query, limit)?;

    let mut out = String::new();
    writeln!(out, "# search: \"{}\"", query)?;
    writeln!(out, "# {} results\n", results.len())?;

    if results.is_empty() {
        writeln!(out, "No results found. Try broader terms or check `mu_compress` for available symbols.")?;
        return Ok(out);
    }

    let mut has_enrichment_opportunity = false;

    for (i, r) in results.iter().enumerate() {
        let sigil = type_sigil(&r.node_type);
        let match_label = match r.match_type {
            mu_daemon::search::MatchType::ExactName => "exact",
            mu_daemon::search::MatchType::ExactQualifiedName => "exact-qn",
            mu_daemon::search::MatchType::Bm25 => "bm25",
        };

        let location = match (&r.file_path, r.line_start) {
            (Some(fp), Some(ls)) => format!("{}:{}", fp, ls),
            (Some(fp), None) => fp.clone(),
            _ => "unknown".to_string(),
        };

        writeln!(
            out,
            "{}. {}{} [{}] -- {} | score={:.2} ({}) | importance={:.2}",
            i + 1, sigil, r.name, r.node_type, location, r.score, match_label, r.importance_score,
        )?;

        if let Some(ref summary) = r.summary_text {
            let snippet = truncate_str(summary, 200);
            writeln!(out, "   {}", snippet)?;
        }

        // Show source snippet for exact matches
        if r.match_type != mu_daemon::search::MatchType::Bm25 {
            if let Some(ref fp) = r.file_path {
                let full_path = project_root.join(fp);
                if let Some(snippet) = read_source_lines(&full_path, r.line_start, r.line_end, 15) {
                    writeln!(out, "   ```")?;
                    for line in snippet.lines() {
                        writeln!(out, "   {}", line)?;
                    }
                    writeln!(out, "   ```")?;
                }
            }
        }

        if r.importance_score > 0.3 && r.summary_text.is_none() {
            has_enrichment_opportunity = true;
        }

        writeln!(out)?;
    }

    if has_enrichment_opportunity {
        writeln!(out, "---")?;
        writeln!(
            out,
            "hint: Some high-importance results lack LLM summaries. \
             Use `mu_enrich` to improve search quality."
        )?;
    }

    Ok(out)
}

// ============================================================================
// 2. expand_nodes_tool
// ============================================================================

/// Expand the graph neighborhood around seed nodes.
pub fn expand_nodes_tool(
    mubase: &MUbase,
    node_ids: &[String],
    depth: u8,
    edge_types: Option<&[String]>,
    direction: &str,
) -> Result<String> {
    let mut out = String::new();
    writeln!(out, "# expand: {} seed(s), depth={}, direction={}", node_ids.len(), depth, direction)?;

    if node_ids.is_empty() {
        writeln!(out, "No seed nodes provided.")?;
        return Ok(out);
    }

    if !["outgoing", "incoming", "both"].contains(&direction) {
        writeln!(out, "Invalid direction '{}'. Use: outgoing, incoming, both", direction)?;
        return Ok(out);
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
    let mut all_edges: Vec<(String, String, String, String)> = Vec::new();
    let mut node_info: HashMap<String, (String, String, Option<String>)> = HashMap::new();

    for nid in &frontier {
        if let Some(info) = fetch_node_info(mubase, nid) {
            node_info.insert(nid.clone(), info);
        }
        visited.insert(nid.clone());
    }

    for current_depth in 0..depth {
        if frontier.is_empty() {
            break;
        }

        let mut next_frontier: Vec<String> = Vec::new();

        for nid in &frontier {
            let escaped = nid.replace('\'', "''");

            if direction == "outgoing" || direction == "both" {
                let sql = format!(
                    "SELECT e.source_id, e.target_id, e.type, n.name, n.type AS ntype, n.file_path \
                     FROM edges e JOIN nodes n ON n.id = e.target_id \
                     WHERE e.source_id = '{}' {} LIMIT 50",
                    escaped, edge_filter
                );
                if let Ok(result) = mubase.query(&sql) {
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

                        all_edges.push((source_name, target_name.clone(), etype, target_id.clone()));
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
                     WHERE e.target_id = '{}' {} LIMIT 50",
                    escaped, edge_filter
                );
                if let Ok(result) = mubase.query(&sql) {
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

                        all_edges.push((source_name.clone(), target_name, etype, source_id.clone()));
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
        writeln!(out, "# depth {} -> {} new nodes discovered", current_depth + 1, frontier.len())?;
    }

    writeln!(out)?;

    writeln!(out, "## Nodes ({})", node_info.len())?;
    let mut sorted_nodes: Vec<_> = node_info.iter().collect();
    sorted_nodes.sort_by(|(a, _), (b, _)| a.cmp(b));
    for (id, (name, ntype, file_path)) in &sorted_nodes {
        let sigil = type_sigil(ntype);
        let loc = file_path.as_deref().unwrap_or("");
        let seed_marker = if node_ids.contains(id) { " [seed]" } else { "" };
        writeln!(out, "  {}{} [{}] -- {}{}", sigil, name, ntype, loc, seed_marker)?;
    }

    writeln!(out)?;

    writeln!(out, "## Edges ({})", all_edges.len())?;
    let mut seen_edges: HashSet<String> = HashSet::new();
    for (src, tgt, etype, _) in &all_edges {
        let key = format!("{}->{}->{}", src, etype, tgt);
        if seen_edges.insert(key) {
            writeln!(out, "  {} --[{}]--> {}", src, etype, tgt)?;
        }
    }

    Ok(out)
}

// ============================================================================
// 3. read_nodes_tool
// ============================================================================

/// Read detailed information about specific nodes.
pub fn read_nodes_tool(
    mubase: &MUbase,
    project_root: &Path,
    node_ids: &[String],
    mode: &str,
) -> Result<String> {
    let mut out = String::new();
    writeln!(out, "# read: {} node(s), mode={}\n", node_ids.len(), mode)?;

    if node_ids.is_empty() {
        writeln!(out, "No node IDs provided.")?;
        return Ok(out);
    }

    if !["signature", "summary", "source", "full"].contains(&mode) {
        writeln!(out, "Invalid mode '{}'. Use: signature, summary, source, full", mode)?;
        return Ok(out);
    }

    for nid in node_ids {
        let escaped = nid.replace('\'', "''");
        let sql = format!(
            "SELECT id, type, name, qualified_name, file_path, line_start, line_end, \
                    complexity, source_text, summary_text, summary_source, importance_score \
             FROM nodes WHERE id = '{}'",
            escaped
        );

        let result = mubase.query(&sql)?;
        if result.rows.is_empty() {
            writeln!(out, "## {} -- NOT FOUND\n", nid)?;
            continue;
        }

        let row = &result.rows[0];
        let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("?");
        let name = row.get(2).and_then(|v| v.as_str()).unwrap_or("?");
        let qualified_name = row.get(3).and_then(|v| v.as_str());
        let file_path = row.get(4).and_then(|v| v.as_str());
        let line_start = row.get(5).and_then(|v| v.as_i64()).map(|v| v as u32);
        let line_end = row.get(6).and_then(|v| v.as_i64()).map(|v| v as u32);
        let complexity = row.get(7).and_then(|v| v.as_i64()).unwrap_or(0);
        let source_text = row.get(8).and_then(|v| v.as_str());
        let summary_text = row.get(9).and_then(|v| v.as_str());
        let summary_source = row.get(10).and_then(|v| v.as_str());
        let importance = row.get(11).and_then(|v| v.as_f64()).unwrap_or(0.0);

        let sigil = type_sigil(node_type);
        let location = match (file_path, line_start, line_end) {
            (Some(fp), Some(ls), Some(le)) => format!("{}:{}-{}", fp, ls, le),
            (Some(fp), Some(ls), None) => format!("{}:{}", fp, ls),
            (Some(fp), _, _) => fp.to_string(),
            _ => "unknown".to_string(),
        };

        writeln!(out, "## {}{} [{}]", sigil, name, node_type)?;
        writeln!(out, "id: {}", nid)?;
        if let Some(qn) = qualified_name {
            writeln!(out, "qualified: {}", qn)?;
        }
        writeln!(out, "location: {}", location)?;
        writeln!(out, "complexity: {} | importance: {:.2}", complexity, importance)?;
        if let Some(ss) = summary_source {
            writeln!(out, "summary_source: {}", ss)?;
        }

        match mode {
            "signature" => {
                if let Some(src) = source_text {
                    if let Some(sig) = extract_signature_line(src) {
                        writeln!(out, "\n```")?;
                        writeln!(out, "{}", sig)?;
                        writeln!(out, "```")?;
                    }
                } else if let Some(fp) = file_path {
                    let full_path = project_root.join(fp);
                    if let Some(snippet) = read_source_lines(&full_path, line_start, line_start.map(|s| s + 1), 2) {
                        writeln!(out, "\n```")?;
                        writeln!(out, "{}", snippet.trim_end())?;
                        writeln!(out, "```")?;
                    }
                }
            }
            "summary" => {
                if let Some(summary) = summary_text {
                    writeln!(out, "\n{}", summary)?;
                } else {
                    writeln!(out, "\nNo summary available. Use `mu_enrich` to generate one.")?;
                }
            }
            "source" => {
                let source = if let Some(src) = source_text {
                    Some(src.to_string())
                } else if let Some(fp) = file_path {
                    let full_path = project_root.join(fp);
                    read_source_lines(&full_path, line_start, line_end, 100)
                } else {
                    None
                };

                if let Some(src) = source {
                    writeln!(out, "\n```")?;
                    for line in src.lines().take(100) {
                        writeln!(out, "{}", line)?;
                    }
                    writeln!(out, "```")?;
                } else {
                    writeln!(out, "\nSource not available.")?;
                }
            }
            "full" => {
                let source = if let Some(src) = source_text {
                    Some(src.to_string())
                } else if let Some(fp) = file_path {
                    let full_path = project_root.join(fp);
                    read_source_lines(&full_path, line_start, line_end, 100)
                } else {
                    None
                };

                if let Some(ref src) = source {
                    writeln!(out, "\n```")?;
                    for line in src.lines().take(100) {
                        writeln!(out, "{}", line)?;
                    }
                    writeln!(out, "```")?;
                }

                if let Some(summary) = summary_text {
                    writeln!(out, "\nSummary: {}", summary)?;
                }

                let neighbor_sql = format!(
                    "SELECT DISTINCT n.name, n.type, n.file_path, n.source_text, e.type AS etype \
                     FROM edges e JOIN nodes n ON (n.id = e.target_id OR n.id = e.source_id) \
                     WHERE (e.source_id = '{}' OR e.target_id = '{}') AND n.id != '{}' \
                     LIMIT 20",
                    escaped, escaped, escaped
                );
                if let Ok(neighbors) = mubase.query(&neighbor_sql) {
                    if !neighbors.rows.is_empty() {
                        writeln!(out, "\n### Neighbors")?;
                        for nrow in &neighbors.rows {
                            let n_name = nrow.first().and_then(|v| v.as_str()).unwrap_or("?");
                            let n_type = nrow.get(1).and_then(|v| v.as_str()).unwrap_or("?");
                            let n_file = nrow.get(2).and_then(|v| v.as_str()).unwrap_or("");
                            let n_source = nrow.get(3).and_then(|v| v.as_str());
                            let edge_type = nrow.get(4).and_then(|v| v.as_str()).unwrap_or("related");

                            let n_sigil = type_sigil(n_type);
                            write!(out, "  {} {}{} [{}]", edge_type, n_sigil, n_name, n_type)?;
                            if !n_file.is_empty() {
                                write!(out, " -- {}", n_file)?;
                            }
                            writeln!(out)?;

                            if let Some(src) = n_source {
                                if let Some(sig) = extract_signature_line(src) {
                                    writeln!(out, "    `{}`", truncate_str(&sig, 100))?;
                                }
                            }
                        }
                    }
                }
            }
            _ => unreachable!(),
        }

        writeln!(out)?;
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
) -> Result<String> {
    let mut out = String::new();
    let approx_tokens = |s: &str| s.len() / 4;

    let nodes_to_pack: Vec<PackNode> = if let Some(ids) = node_ids {
        let mut nodes = Vec::new();
        for nid in ids {
            let escaped = nid.replace('\'', "''");
            let sql = format!(
                "SELECT id, type, name, file_path, line_start, line_end, \
                        source_text, summary_text, importance_score \
                 FROM nodes WHERE id = '{}'",
                escaped
            );
            if let Ok(result) = mubase.query(&sql) {
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
                    "### {}{} [{}]\n```\n{}\n```\n",
                    sigil, node.name, node.node_type, src
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
                "### {}{} [{}]\n`{}`\n{}\n",
                sigil, node.name, node.node_type, sig, summary
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
) -> Result<String> {
    let mut out = String::new();

    if let Some(summaries) = summaries {
        writeln!(out, "# enrich: storing {} summaries\n", summaries.len())?;

        let mut stored = 0;
        let mut errors = Vec::new();

        for (node_id, summary) in summaries {
            let hash_sql = format!(
                "SELECT source_text FROM nodes WHERE id = '{}'",
                node_id.replace('\'', "''")
            );
            let code_hash = if let Ok(result) = mubase.query(&hash_sql) {
                result.rows.first()
                    .and_then(|r| r.first())
                    .and_then(|v| v.as_str())
                    .map(mu_daemon::summary::compute_code_hash)
                    .unwrap_or_else(|| "unknown".to_string())
            } else {
                "unknown".to_string()
            };

            match mubase.update_summary(node_id, summary, "llm", &code_hash) {
                Ok(()) => {
                    let node_sql = format!(
                        "SELECT id, type, name, qualified_name, file_path FROM nodes WHERE id = '{}'",
                        node_id.replace('\'', "''")
                    );
                    if let Ok(result) = mubase.query(&node_sql) {
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
        let limit = 20;
        let filter_ids: Option<HashSet<&str>> = node_ids.map(|ids| ids.iter().map(|s| s.as_str()).collect());

        let unsummarized = mubase.get_unsummarized_nodes(if filter_ids.is_some() { 200 } else { limit })?;

        let candidates: Vec<&Node> = if let Some(ref filter) = filter_ids {
            unsummarized.iter().filter(|n| filter.contains(n.id.as_str())).collect()
        } else {
            unsummarized.iter().take(limit).collect()
        };

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
        format!("{}...", &s[..max.min(s.len())])
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

fn fetch_node_info(mubase: &MUbase, node_id: &str) -> Option<(String, String, Option<String>)> {
    let escaped = node_id.replace('\'', "''");
    let sql = format!("SELECT name, type, file_path FROM nodes WHERE id = '{}'", escaped);
    let result = mubase.query(&sql).ok()?;
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
