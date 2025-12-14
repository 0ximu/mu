//! Yolo command - Impact analysis (what breaks if you change something?)
//!
//! Shows downstream impact of modifying a file or node using BFS traversal
//! to find all dependents. Fun, colorful output with personality.
//!
//! ## Implementation Details
//!
//! 1. **MUbase Discovery**: Searches for `.mu/codebase.mubase` in current directory
//!    and parent directories (same as deps command).
//!
//! 2. **Target Resolution**: Accepts file paths or node IDs. Resolution order:
//!    - Exact node ID match
//!    - Exact file path match
//!    - Partial match (LIKE query)
//!
//! 3. **Impact Analysis**: Uses BFS traversal to find reverse dependencies
//!    (nodes that depend on the target). Query: `SELECT source_id FROM edges WHERE target_id = ?`
//!
//! 4. **Risk Classification**:
//!    - Low: 0-5 impacted nodes
//!    - Medium: 6-15 impacted nodes
//!    - High: 16-50 impacted nodes
//!    - Extreme: 51+ impacted nodes
//!
//! 5. **Output**: Displays up to 15 impacted nodes with file paths, sorted by file path
//!    then by name. Uses colorful formatting based on risk level.

use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::{params, Connection};
use std::collections::{HashSet, VecDeque};
use std::path::PathBuf;

use crate::output::OutputFormat;

/// Impact analysis result for a target
#[derive(Debug, serde::Serialize)]
pub struct YoloResult {
    pub target: String,
    pub node_id: Option<String>,
    pub impacted_count: usize,
    pub impacted_nodes: Vec<String>,
    pub risk_level: RiskLevel,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub db_found: bool,
}

/// Risk level based on impact count
#[derive(Debug, Clone, Copy, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum RiskLevel {
    Low,
    Medium,
    High,
    Extreme,
}

impl RiskLevel {
    fn from_count(count: usize) -> Self {
        match count {
            0..=5 => RiskLevel::Low,
            6..=15 => RiskLevel::Medium,
            16..=50 => RiskLevel::High,
            _ => RiskLevel::Extreme,
        }
    }

    fn message(&self) -> &'static str {
        match self {
            RiskLevel::Low => "Low impact. Go ahead, YOLO!",
            RiskLevel::Medium => "Medium impact. Proceed with care.",
            RiskLevel::High => "High impact! Consider testing thoroughly.",
            RiskLevel::Extreme => "EXTREME IMPACT! This touches EVERYTHING. Are you sure?",
        }
    }

    fn color(&self) -> colored::Color {
        match self {
            RiskLevel::Low => colored::Color::Green,
            RiskLevel::Medium => colored::Color::Yellow,
            RiskLevel::High => colored::Color::Red,
            RiskLevel::Extreme => colored::Color::BrightRed,
        }
    }
}

/// Run the yolo command - impact analysis with personality
pub async fn run(path: &str, format: OutputFormat) -> anyhow::Result<()> {
    let db_path = match find_mubase(".") {
        Ok(p) => p,
        Err(_) => {
            let result = YoloResult {
                target: path.to_string(),
                node_id: None,
                impacted_count: 0,
                impacted_nodes: vec![],
                risk_level: RiskLevel::Low,
                db_found: false,
            };
            match format {
                OutputFormat::Json => {
                    println!("{}", serde_json::to_string_pretty(&result)?);
                }
                _ => {
                    print_yolo_output(&result);
                }
            }
            return Ok(());
        }
    };

    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    let node_id = resolve_target(&conn, path)?;

    let impacted = find_impacted_nodes(&conn, &node_id, 10)?;

    // Dedupe by file path - users care about files, not individual nodes
    let mut seen_files: HashSet<String> = HashSet::new();
    let impacted_deduped: Vec<_> = impacted
        .into_iter()
        .filter(|node| {
            let key = node.file_path.clone().unwrap_or_else(|| node.name.clone());
            seen_files.insert(key)
        })
        .collect();

    let impacted_count = impacted_deduped.len();
    let risk_level = RiskLevel::from_count(impacted_count);

    let impacted_nodes: Vec<String> = impacted_deduped
        .iter()
        .map(|node| {
            if let Some(fp) = &node.file_path {
                format!("{} ({})", node.name, fp)
            } else {
                node.name.clone()
            }
        })
        .collect();

    let result = YoloResult {
        target: path.to_string(),
        node_id: Some(node_id),
        impacted_count,
        impacted_nodes,
        risk_level,
        db_found: true,
    };

    match format {
        OutputFormat::Json => {
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
        _ => {
            print_yolo_output(&result);
        }
    }

    Ok(())
}

fn print_yolo_output(result: &YoloResult) {
    println!();
    println!("{} {}", "YOLO:".magenta().bold(), result.target.bold());
    println!();

    if !result.db_found {
        println!(
            "{}",
            "No MU database found. Run 'mu bootstrap' first.".yellow()
        );
        println!();
        println!(
            "{}",
            "Once indexed, I'll tell you what breaks if you touch this.".dimmed()
        );
    } else if result.impacted_count == 0 {
        println!("{}", "No dependents found - this node is a leaf!".green());
    } else {
        println!(
            "{}",
            format!("{} nodes affected", result.impacted_count)
                .color(result.risk_level.color())
                .bold()
        );

        if !result.impacted_nodes.is_empty() {
            println!();
            println!("{}", "Impacted nodes:".cyan());
            for (i, node) in result.impacted_nodes.iter().take(15).enumerate() {
                println!("  {} {}", format!("{}.", i + 1).dimmed(), node);
            }
            if result.impacted_nodes.len() > 15 {
                println!(
                    "  {}",
                    format!("... and {} more", result.impacted_nodes.len() - 15).dimmed()
                );
            }
        }
    }

    println!();
    println!("{}", result.risk_level.message().dimmed());
}

/// Find the MUbase database in the given directory or its parents.
fn find_mubase(start_path: &str) -> Result<PathBuf> {
    let start = std::path::Path::new(start_path).canonicalize()?;
    let mut current = start.as_path();

    loop {
        // New standard path: .mu/mubase
        let mu_dir = current.join(".mu");
        let db_path = mu_dir.join("mubase");
        if db_path.exists() {
            return Ok(db_path);
        }

        // Legacy path: .mubase
        let legacy_path = current.join(".mubase");
        if legacy_path.exists() {
            return Ok(legacy_path);
        }

        match current.parent() {
            Some(parent) => current = parent,
            None => {
                return Err(anyhow::anyhow!(
                    "No MUbase found. Run 'mu bootstrap' first to create the database."
                ))
            }
        }
    }
}

/// Resolve a target (file path or node ID) to a node ID.
fn resolve_target(conn: &Connection, target: &str) -> Result<String> {
    let mut stmt = conn.prepare("SELECT id FROM nodes WHERE id = ?")?;
    let mut rows = stmt.query(params![target])?;
    if let Some(row) = rows.next()? {
        return Ok(row.get(0)?);
    }

    let mut stmt = conn.prepare("SELECT id FROM nodes WHERE file_path = ? LIMIT 1")?;
    let mut rows = stmt.query(params![target])?;
    if let Some(row) = rows.next()? {
        return Ok(row.get(0)?);
    }

    let pattern = format!("%{}%", target);
    let mut stmt = conn
        .prepare("SELECT id, file_path FROM nodes WHERE id LIKE ? OR file_path LIKE ? LIMIT 10")?;
    let mut rows = stmt.query(params![pattern, pattern])?;

    let mut matches = Vec::new();
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        matches.push(id);
    }

    match matches.len() {
        0 => Err(anyhow::anyhow!("Node or file not found: {}", target)),
        1 => Ok(matches.into_iter().next().unwrap()),
        _ => {
            for m in &matches {
                if m.ends_with(target) || m.contains(&format!(":{}", target)) {
                    return Ok(m.clone());
                }
            }
            Ok(matches.into_iter().next().unwrap())
        }
    }
}

/// A node that is impacted by changes.
#[derive(Debug, Clone)]
struct ImpactedNode {
    name: String,
    file_path: Option<String>,
}

/// Find all nodes impacted by changes to the given node (reverse dependencies).
fn find_impacted_nodes(
    conn: &Connection,
    node_id: &str,
    max_depth: u8,
) -> Result<Vec<ImpactedNode>> {
    let mut visited: HashSet<String> = HashSet::new();
    let mut result: Vec<ImpactedNode> = Vec::new();
    let mut queue: VecDeque<(String, u8)> = VecDeque::new();

    visited.insert(node_id.to_string());
    queue.push_back((node_id.to_string(), 0));

    let edge_query = "SELECT e.source_id, n.name, n.file_path
         FROM edges e
         JOIN nodes n ON n.id = e.source_id
         WHERE e.target_id = ?";

    while let Some((current_id, current_depth)) = queue.pop_front() {
        if current_depth >= max_depth {
            continue;
        }

        let mut stmt = conn.prepare(edge_query)?;
        let mut rows = stmt.query(params![current_id])?;

        while let Some(row) = rows.next()? {
            let neighbor_id: String = row.get(0)?;
            let name: String = row.get(1)?;
            let file_path: Option<String> = row.get(2)?;

            if !visited.contains(&neighbor_id) {
                visited.insert(neighbor_id.clone());

                result.push(ImpactedNode { name, file_path });

                queue.push_back((neighbor_id, current_depth + 1));
            }
        }
    }

    result.sort_by(|a, b| {
        a.file_path
            .as_deref()
            .unwrap_or("")
            .cmp(b.file_path.as_deref().unwrap_or(""))
            .then(a.name.cmp(&b.name))
    });

    Ok(result)
}
