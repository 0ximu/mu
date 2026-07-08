//! Structured response types for MCP tools.
//!
//! Every tool returns one of these structs. The formatted text output
//! (sigils, tables, markdown) is built FROM these structs via format methods.

use serde::Serialize;
use std::fmt::Write;
use std::path::Path;

/// A node in tool output -- always includes the stable database ID.
#[derive(Debug, Clone, Serialize)]
pub struct NodeResult {
    pub node_id: String,
    pub name: String,
    pub kind: String,
    pub file_path: String,
    pub line_start: u32,
    pub line_end: u32,
    pub score: Option<f32>,
    pub match_type: Option<String>,
    pub importance: f32,
    pub summary: Option<String>,
    pub node_category: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct EdgeResult {
    pub source_id: String,
    pub source_name: String,
    pub target_id: String,
    pub target_name: String,
    pub edge_type: String,
}

#[derive(Debug, Clone, Serialize)]
pub enum SearchConfidence {
    High,
    Medium,
    Low,
    NoResults,
}

#[derive(Debug, Clone, Serialize)]
pub struct EnrichmentHint {
    pub node_ids: Vec<String>,
    pub message: String,
}

/// Search response.
#[derive(Debug, Clone, Serialize)]
pub struct SearchResponse {
    pub results: Vec<NodeResult>,
    pub query: String,
    pub confidence: SearchConfidence,
    pub enrichment_opportunity: Option<EnrichmentHint>,
}

/// Expand response.
#[derive(Debug, Clone, Serialize)]
pub struct ExpandResponse {
    pub seed_nodes: Vec<NodeResult>,
    pub neighbors: Vec<NodeResult>,
    pub edges: Vec<EdgeResult>,
}

/// Impact response.
#[derive(Debug, Clone, Serialize)]
pub struct ImpactResponse {
    pub target: NodeResult,
    pub dependents: Vec<NodeResult>,
    pub edges: Vec<EdgeResult>,
}

/// A single node's read result with optional source/neighbors.
#[derive(Debug, Clone, Serialize)]
pub struct ReadNodeResult {
    pub node: NodeResult,
    pub source_text: Option<String>,
    pub signature: Option<String>,
    pub neighbors: Vec<(String, NodeResult)>,
}

/// Read response.
#[derive(Debug, Clone, Serialize)]
pub struct ReadResponse {
    pub nodes: Vec<ReadNodeResult>,
    pub mode: String,
}

// ============================================================================
// Formatting helpers -- produce the existing markdown output from structs
// ============================================================================

fn type_sigil(kind: &str) -> &'static str {
    match kind {
        "module" => "!",
        "class" => "$",
        "function" => "#",
        "message" => "@",
        _ => "@",
    }
}

fn category_tag(cat: &str) -> &'static str {
    match cat {
        "production" | "" => "",
        "test" => " [test]",
        "generated" => " [generated]",
        "infrastructure" | "infra" => " [infra]",
        _ => " [other]",
    }
}

use crate::output::truncate_str;

fn read_source_lines(
    path: &Path,
    line_start: u32,
    line_end: u32,
    max_lines: usize,
) -> Option<String> {
    let content = std::fs::read_to_string(path).ok()?;
    let lines: Vec<&str> = content.lines().collect();

    let start = if line_start == 0 {
        0
    } else {
        (line_start - 1) as usize
    };
    let end = (line_end as usize).min(lines.len());

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

fn confidence_label(c: &SearchConfidence) -> &'static str {
    match c {
        SearchConfidence::High => "HIGH",
        SearchConfidence::Medium => "MEDIUM",
        SearchConfidence::Low => "LOW",
        SearchConfidence::NoResults => "NONE",
    }
}

pub fn format_search_response(resp: &SearchResponse, project_root: &Path) -> String {
    let mut out = String::new();
    let _ = writeln!(out, "# search: \"{}\"", resp.query);

    let label = confidence_label(&resp.confidence);
    if matches!(resp.confidence, SearchConfidence::Low) {
        let _ = writeln!(
            out,
            "# {} results | confidence: {} -- results may not be relevant\n",
            resp.results.len(),
            label
        );
    } else {
        let _ = writeln!(
            out,
            "# {} results | confidence: {}\n",
            resp.results.len(),
            label
        );
    }

    if resp.results.is_empty() {
        let _ = writeln!(
            out,
            "No results found. Try broader terms or check `mu_compress` for available symbols."
        );
        return out;
    }

    for (i, r) in resp.results.iter().enumerate() {
        let sigil = type_sigil(&r.kind);
        let match_label = r.match_type.as_deref().unwrap_or("bm25");

        let location = if !r.file_path.is_empty() && r.line_start > 0 {
            format!("{}:{}", r.file_path, r.line_start)
        } else if !r.file_path.is_empty() {
            r.file_path.clone()
        } else {
            "unknown".to_string()
        };

        let cat_tag = category_tag(&r.node_category);
        let _ = writeln!(
            out,
            "{}. {}{} [{}]{} -- {} | score={:.2} ({}) | importance={:.2}",
            i + 1,
            sigil,
            r.name,
            r.kind,
            cat_tag,
            location,
            r.score.unwrap_or(0.0),
            match_label,
            r.importance,
        );

        let _ = writeln!(out, "   id: {}", r.node_id);

        if let Some(ref summary) = r.summary {
            let snippet = truncate_str(summary, 200);
            let _ = writeln!(out, "   {}", snippet);
        }

        // Show source snippet for exact matches
        if match_label != "bm25" && !r.file_path.is_empty() {
            let full_path = project_root.join(&r.file_path);
            if let Some(snippet) = read_source_lines(&full_path, r.line_start, r.line_end, 15) {
                let _ = writeln!(out, "   ```");
                for line in snippet.lines() {
                    let _ = writeln!(out, "   {}", line);
                }
                let _ = writeln!(out, "   ```");
            }
        }

        let _ = writeln!(out);
    }

    if let Some(ref hint) = resp.enrichment_opportunity {
        let _ = writeln!(out, "---");
        let _ = writeln!(out, "hint: {}", hint.message);
    }

    out
}

pub fn format_impact_response(resp: &ImpactResponse) -> String {
    let mut out = String::new();
    let sigil = type_sigil(&resp.target.kind);
    let _ = writeln!(out, "# Impact Analysis: {}{}", sigil, resp.target.name);

    if !resp.target.node_id.is_empty() {
        let _ = writeln!(out, "id: {}", resp.target.node_id);
        if !resp.target.file_path.is_empty() {
            let _ = writeln!(
                out,
                "location: {}:{}",
                resp.target.file_path, resp.target.line_start
            );
        }
    }
    let _ = writeln!(out);

    if resp.dependents.is_empty() {
        let _ = writeln!(out, "No graph dependencies found.");
        return out;
    }

    // Split dependents into production vs non-production, preserving edge alignment
    let mut prod: Vec<(usize, &NodeResult)> = Vec::new();
    let mut non_prod: Vec<(usize, &NodeResult)> = Vec::new();
    for (i, dep) in resp.dependents.iter().enumerate() {
        if dep.node_category == "production" || dep.node_category.is_empty() {
            prod.push((i, dep));
        } else {
            non_prod.push((i, dep));
        }
    }

    let _ = writeln!(
        out,
        "## Dependents ({} found — {} production, {} test/other)\n",
        resp.dependents.len(),
        prod.len(),
        non_prod.len(),
    );

    for (i, dep) in &prod {
        let dep_sigil = type_sigil(&dep.kind);
        let edge_label = resp
            .edges
            .get(*i)
            .map(|e| e.edge_type.as_str())
            .unwrap_or("calls");
        let _ = writeln!(
            out,
            "  {}{} [{}] --[{}]--> {} | importance={:.2}",
            dep_sigil, dep.name, dep.kind, edge_label, resp.target.name, dep.importance,
        );
        let _ = writeln!(out, "    id: {}", dep.node_id);
        if !dep.file_path.is_empty() {
            let _ = writeln!(out, "    {}", dep.file_path);
        }
    }

    if !non_prod.is_empty() {
        let _ = writeln!(out);
        let _ = writeln!(out, "### Tests & Other ({})\n", non_prod.len());
        for (i, dep) in &non_prod {
            let dep_sigil = type_sigil(&dep.kind);
            let edge_label = resp
                .edges
                .get(*i)
                .map(|e| e.edge_type.as_str())
                .unwrap_or("calls");
            let dep_cat = category_tag(&dep.node_category);
            let _ = writeln!(
                out,
                "  {}{} [{}]{} --[{}]--> {} | importance={:.2}",
                dep_sigil,
                dep.name,
                dep.kind,
                dep_cat,
                edge_label,
                resp.target.name,
                dep.importance,
            );
            let _ = writeln!(out, "    id: {}", dep.node_id);
            if !dep.file_path.is_empty() {
                let _ = writeln!(out, "    {}", dep.file_path);
            }
        }
    }

    out
}

pub fn format_expand_response(resp: &ExpandResponse) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "# expand: {} seed(s), {} neighbors, {} edges",
        resp.seed_nodes.len(),
        resp.neighbors.len(),
        resp.edges.len()
    );
    let _ = writeln!(out);

    // All nodes (seeds + neighbors)
    let total = resp.seed_nodes.len() + resp.neighbors.len();
    let _ = writeln!(out, "## Nodes ({})", total);

    for n in &resp.seed_nodes {
        let sigil = type_sigil(&n.kind);
        let cat = category_tag(&n.node_category);
        let _ = writeln!(
            out,
            "  {}{} [{}]{} -- {} [seed]",
            sigil, n.name, n.kind, cat, n.file_path
        );
        let _ = writeln!(out, "    id: {}", n.node_id);
    }

    for n in &resp.neighbors {
        let sigil = type_sigil(&n.kind);
        let cat = category_tag(&n.node_category);
        let _ = writeln!(
            out,
            "  {}{} [{}]{} -- {}",
            sigil, n.name, n.kind, cat, n.file_path
        );
        let _ = writeln!(out, "    id: {}", n.node_id);
    }

    let _ = writeln!(out);

    let _ = writeln!(out, "## Edges ({})", resp.edges.len());
    for e in &resp.edges {
        let _ = writeln!(
            out,
            "  {} --[{}]--> {}",
            e.source_name, e.edge_type, e.target_name
        );
    }

    out
}

pub fn format_read_response(resp: &ReadResponse, project_root: &Path) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "# read: {} node(s), mode={}\n",
        resp.nodes.len(),
        resp.mode
    );

    for rn in &resp.nodes {
        let n = &rn.node;
        let sigil = type_sigil(&n.kind);
        let location = if !n.file_path.is_empty() && n.line_start > 0 && n.line_end > 0 {
            format!("{}:{}-{}", n.file_path, n.line_start, n.line_end)
        } else if !n.file_path.is_empty() && n.line_start > 0 {
            format!("{}:{}", n.file_path, n.line_start)
        } else if !n.file_path.is_empty() {
            n.file_path.clone()
        } else {
            "unknown".to_string()
        };

        let cat = category_tag(&n.node_category);
        let _ = writeln!(out, "## {}{} [{}]{}", sigil, n.name, n.kind, cat);
        let _ = writeln!(out, "id: {}", n.node_id);
        let _ = writeln!(out, "location: {}", location);
        let _ = writeln!(out, "importance: {:.2}", n.importance);

        match resp.mode.as_str() {
            "signature" => {
                if let Some(ref sig) = rn.signature {
                    let _ = writeln!(out, "\n```");
                    let _ = writeln!(out, "{}", sig);
                    let _ = writeln!(out, "```");
                } else if !n.file_path.is_empty() {
                    let full_path = project_root.join(&n.file_path);
                    if let Some(snippet) =
                        read_source_lines(&full_path, n.line_start, n.line_start + 1, 2)
                    {
                        let _ = writeln!(out, "\n```");
                        let _ = writeln!(out, "{}", snippet.trim_end());
                        let _ = writeln!(out, "```");
                    }
                }
            }
            "summary" => {
                if let Some(ref summary) = n.summary {
                    let _ = writeln!(out, "\n{}", summary);
                } else {
                    let _ = writeln!(
                        out,
                        "\nNo summary available. Use `mu_enrich` to generate one."
                    );
                }
            }
            "source" => {
                if let Some(ref src) = rn.source_text {
                    let _ = writeln!(out, "\n```");
                    for line in src.lines().take(100) {
                        let _ = writeln!(out, "{}", line);
                    }
                    let _ = writeln!(out, "```");
                } else {
                    let _ = writeln!(out, "\nSource not available.");
                }
            }
            "full" => {
                if let Some(ref src) = rn.source_text {
                    let _ = writeln!(out, "\n```");
                    for line in src.lines().take(100) {
                        let _ = writeln!(out, "{}", line);
                    }
                    let _ = writeln!(out, "```");
                }

                if let Some(ref summary) = n.summary {
                    let _ = writeln!(out, "\nSummary: {}", summary);
                }

                if !rn.neighbors.is_empty() {
                    let _ = writeln!(out, "\n### Neighbors");
                    for (edge_type, neighbor) in &rn.neighbors {
                        let n_sigil = type_sigil(&neighbor.kind);
                        let _ = write!(
                            out,
                            "  {} {}{} [{}]",
                            edge_type, n_sigil, neighbor.name, neighbor.kind
                        );
                        if !neighbor.file_path.is_empty() {
                            let _ = write!(out, " -- {}", neighbor.file_path);
                        }
                        let _ = writeln!(out);
                        let _ = writeln!(out, "    id: {}", neighbor.node_id);
                    }
                }
            }
            _ => {}
        }

        let _ = writeln!(out);
    }

    out
}
