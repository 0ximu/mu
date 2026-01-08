//! Why command - Explain path/connection between two nodes
//!
//! Shows how two entities are connected in the codebase graph,
//! including the edge types (calls, uses, imports, inherits) at each hop.

use std::path::PathBuf;

use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::Connection;
use serde::Serialize;

use super::graph::{GraphData, PathStep};
use crate::output::{Output, OutputFormat, TableDisplay};

/// Find the MUbase database
fn find_mubase(start_path: &str) -> Result<PathBuf> {
    let start = std::path::Path::new(start_path).canonicalize()?;
    let mut current = start.as_path();

    loop {
        let mu_dir = current.join(".mu");
        let db_path = mu_dir.join("mubase");
        if db_path.exists() {
            return Ok(db_path);
        }

        let legacy_path = current.join(".mubase");
        if legacy_path.exists() {
            return Ok(legacy_path);
        }

        match current.parent() {
            Some(parent) => current = parent,
            None => {
                return Err(anyhow::anyhow!(
                    "No MUbase found. Run 'mu bootstrap' first."
                ))
            }
        }
    }
}

/// A single path between two nodes with edge annotations
#[derive(Debug, Clone, Serialize)]
pub struct AnnotatedPath {
    pub steps: Vec<PathStep>,
    pub hop_count: usize,
    pub edge_types: Vec<String>,
}

impl AnnotatedPath {
    fn from_steps(steps: Vec<PathStep>) -> Self {
        let hop_count = steps.len().saturating_sub(1);
        let edge_types: Vec<String> = steps.iter().filter_map(|s| s.edge_type.clone()).collect();

        Self {
            steps,
            hop_count,
            edge_types,
        }
    }

    /// Get a summary of edge types used (e.g., "via calls, uses")
    fn edge_summary(&self) -> String {
        let mut unique: Vec<&str> = self
            .edge_types
            .iter()
            .map(|s| s.trim_start_matches("<-"))
            .collect();
        unique.sort();
        unique.dedup();

        if unique.is_empty() {
            "direct".to_string()
        } else {
            format!("via {}", unique.join(", "))
        }
    }
}

/// Result of the why command
#[derive(Debug, Serialize)]
pub struct WhyResult {
    pub from: String,
    pub to: String,
    pub paths: Vec<AnnotatedPath>,
    pub path_count: usize,
    pub connected: bool,
}

impl TableDisplay for WhyResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        // Header
        output.push_str(&format!(
            "\n{} {} {} ({} path{} found)\n",
            extract_name(&self.from).cyan().bold(),
            "→".dimmed(),
            extract_name(&self.to).cyan().bold(),
            self.path_count,
            if self.path_count == 1 { "" } else { "s" }
        ));
        output.push_str(&format!("{}\n", "-".repeat(60)));

        if !self.connected {
            output.push_str(&format!(
                "\n  {} No connection found between these nodes.\n",
                "✗".red().bold()
            ));
            output.push_str(&format!(
                "  {}\n",
                "They may be in separate parts of the codebase.".dimmed()
            ));
            return output;
        }

        for (i, path) in self.paths.iter().enumerate() {
            output.push_str(&format!(
                "\n{} ({} hop{}, {})\n",
                format!("Path {}", i + 1).bold(),
                path.hop_count,
                if path.hop_count == 1 { "" } else { "s" },
                path.edge_summary().dimmed()
            ));

            // Draw the path
            for (j, step) in path.steps.iter().enumerate() {
                let node_name = extract_name(&step.node_id);
                let node_type = extract_type(&step.node_id);

                let type_badge = match node_type {
                    "mod" => "[mod]".blue(),
                    "cls" => "[cls]".yellow(),
                    "fn" => "[fn]".green(),
                    _ => format!("[{}]", node_type).normal(),
                };

                if j == 0 {
                    output.push_str(&format!("  {} {}\n", type_badge, node_name.bold()));
                } else {
                    output.push_str(&format!("  {} {}\n", type_badge, node_name));
                }

                // Draw edge to next node
                if let Some(edge_type) = &step.edge_type {
                    let arrow = format!("  │── {} ──→", edge_type);
                    output.push_str(&format!("  {}\n", arrow.dimmed()));
                }
            }
        }

        // Verdict
        if !self.paths.is_empty() {
            output.push_str(&format!("\n{}\n", "-".repeat(60)));
            let primary_path = &self.paths[0];
            let verdict = generate_verdict(&self.from, &self.to, primary_path);
            output.push_str(&format!("{}: {}\n", "Verdict".bold(), verdict));
        }

        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();
        output.push_str(&format!(":: why {} {}\n", self.from, self.to));
        output.push_str(&format!("# connected: {}\n", self.connected));
        output.push_str(&format!("# path_count: {}\n", self.path_count));

        for (i, path) in self.paths.iter().enumerate() {
            output.push_str(&format!("\n# path_{}: {} hops\n", i + 1, path.hop_count));
            for step in &path.steps {
                let edge = step
                    .edge_type
                    .as_ref()
                    .map(|e| format!(" --{}-->", e))
                    .unwrap_or_default();
                output.push_str(&format!("  {}{}\n", step.node_id, edge));
            }
        }

        output
    }
}

/// Run the why command
pub async fn run(
    from: &str,
    to: &str,
    all_paths: bool,
    max_paths: usize,
    format: OutputFormat,
) -> Result<()> {
    let db_path = find_mubase(".")?;
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    // Load graph
    let graph = GraphData::from_db(&conn)?;

    // Resolve node IDs (fuzzy matching)
    let from_id = resolve_node_id(&conn, from)?;
    let to_id = resolve_node_id(&conn, to)?;

    let paths = if all_paths {
        // Find all paths up to depth 6
        let raw_paths = graph.all_paths_with_edges(&from_id, &to_id, 6, max_paths);
        raw_paths
            .into_iter()
            .map(AnnotatedPath::from_steps)
            .collect()
    } else {
        // Find just the shortest path
        match graph.shortest_path_with_edges(&from_id, &to_id) {
            Some(steps) => vec![AnnotatedPath::from_steps(steps)],
            None => vec![],
        }
    };

    let connected = !paths.is_empty();
    let path_count = paths.len();

    let result = WhyResult {
        from: from_id,
        to: to_id,
        paths,
        path_count,
        connected,
    };

    Output::new(result, format).render()
}

/// Resolve a query to a node ID with fuzzy matching
fn resolve_node_id(conn: &Connection, query: &str) -> Result<String> {
    // Try exact match first
    let mut stmt = conn.prepare("SELECT id FROM nodes WHERE id = ?1 OR name = ?1 LIMIT 1")?;
    let mut rows = stmt.query([query])?;

    if let Some(row) = rows.next()? {
        return Ok(row.get(0)?);
    }

    // Try fuzzy match
    let pattern = format!("%{}%", query);
    let mut stmt = conn.prepare(
        "SELECT id, name, type FROM nodes
         WHERE id LIKE ?1 OR name LIKE ?1
         ORDER BY
           CASE WHEN name = ?2 THEN 0
                WHEN name LIKE ?2 || '%' THEN 1
                ELSE 2 END,
           LENGTH(name)
         LIMIT 5",
    )?;
    let mut rows = stmt.query([&pattern, query])?;

    let mut matches = Vec::new();
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        let name: String = row.get(1)?;
        let node_type: String = row.get(2)?;
        matches.push((id, name, node_type));
    }

    match matches.len() {
        0 => Err(anyhow::anyhow!("Node not found: {}", query)),
        1 => Ok(matches[0].0.clone()),
        _ => {
            let suggestions: Vec<String> = matches
                .iter()
                .map(|(id, name, t)| format!("  {} [{}] {}", name, t, id.dimmed()))
                .collect();
            Err(anyhow::anyhow!(
                "Multiple nodes match '{}'. Be more specific:\n{}",
                query,
                suggestions.join("\n")
            ))
        }
    }
}

/// Extract the short name from a node ID (e.g., "cls:path/file.rs:ClassName" -> "ClassName")
fn extract_name(node_id: &str) -> &str {
    node_id.rsplit(':').next().unwrap_or(node_id)
}

/// Extract the type prefix from a node ID (e.g., "cls:path/file.rs:ClassName" -> "cls")
fn extract_type(node_id: &str) -> &str {
    node_id.split(':').next().unwrap_or("?")
}

/// Generate a human-readable verdict about the relationship
fn generate_verdict(from: &str, to: &str, path: &AnnotatedPath) -> String {
    let from_name = extract_name(from);
    let to_name = extract_name(to);

    if path.hop_count == 0 {
        return format!("{} and {} are the same node.", from_name, to_name);
    }

    if path.hop_count == 1 {
        let edge = path
            .edge_types
            .first()
            .map(|s| s.as_str())
            .unwrap_or("connected to");
        return format!("{} directly {} {}.", from_name, edge, to_name);
    }

    // Analyze the edge types to generate a narrative
    let has_uses = path.edge_types.iter().any(|e| e.contains("uses"));
    let has_calls = path.edge_types.iter().any(|e| e.contains("calls"));
    let has_contains = path.edge_types.iter().any(|e| e.contains("contains"));

    if has_uses && has_calls {
        format!(
            "{} depends on {} through composition and method calls.",
            from_name, to_name
        )
    } else if has_uses {
        format!(
            "{} has a composition relationship with {} (uses it as a field type).",
            from_name, to_name
        )
    } else if has_calls {
        format!(
            "{} reaches {} through {} function call{}.",
            from_name,
            to_name,
            path.hop_count,
            if path.hop_count == 1 { "" } else { "s" }
        )
    } else if has_contains {
        format!(
            "{} is structurally related to {} through containment.",
            from_name, to_name
        )
    } else {
        format!(
            "{} is connected to {} via {} hop{}.",
            from_name,
            to_name,
            path.hop_count,
            if path.hop_count == 1 { "" } else { "s" }
        )
    }
}
