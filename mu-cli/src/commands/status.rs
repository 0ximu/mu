//! Status command - Show project status and recommended next steps
//!
//! Checks configuration, graph database, and provides actionable guidance
//! for what to do next.

use crate::output::{Output, OutputFormat, TableDisplay};
use anyhow::Result;
use colored::Colorize;
use duckdb::Connection;
use serde::Serialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Instant;

/// Find the mubase database path.
///
/// Checks in order:
/// 1. `.mu/mubase` (new standard path)
/// 2. `.mubase` (legacy path for backward compatibility)
fn find_mubase_path(root: &Path) -> Option<PathBuf> {
    // New standard path: .mu/mubase
    let new_path = root.join(".mu").join("mubase");
    if new_path.exists() {
        return Some(new_path);
    }

    // Legacy path: .mubase
    let legacy_path = root.join(".mubase");
    if legacy_path.exists() {
        return Some(legacy_path);
    }

    None
}

/// Statistics about the code graph.
#[derive(Debug, Clone, Serialize)]
pub struct GraphStats {
    pub node_count: usize,
    pub edge_count: usize,
    pub type_counts: HashMap<String, usize>,
}

/// Get graph statistics from the database.
fn get_stats(conn: &Connection) -> Result<GraphStats> {
    let node_count: usize = conn
        .query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))
        .unwrap_or(0);

    let edge_count: usize = conn
        .query_row("SELECT COUNT(*) FROM edges", [], |row| row.get(0))
        .unwrap_or(0);

    // Get counts by type
    let mut type_counts = HashMap::new();
    if let Ok(mut stmt) = conn.prepare("SELECT type, COUNT(*) FROM nodes GROUP BY type") {
        if let Ok(mut rows) = stmt.query([]) {
            while let Ok(Some(row)) = rows.next() {
                if let (Ok(type_name), Ok(count)) =
                    (row.get::<_, String>(0), row.get::<_, usize>(1))
                {
                    type_counts.insert(type_name, count);
                }
            }
        }
    }

    Ok(GraphStats {
        node_count,
        edge_count,
        type_counts,
    })
}

/// Status information for a MU project.
#[derive(Debug, Clone, Serialize)]
pub struct StatusInfo {
    /// Whether the config file (.murc.toml) exists
    pub config_exists: bool,
    /// Whether the mubase database exists
    pub mubase_exists: bool,
    /// Path to the mubase database (if it exists)
    pub mubase_path: Option<String>,
    /// Graph statistics (if database exists)
    pub stats: Option<GraphStats>,
    /// Recommended next action
    pub next_action: Option<String>,
    /// Human-readable status message
    pub message: String,
    /// Time taken to gather status (in milliseconds)
    pub duration_ms: u64,
}

impl TableDisplay for StatusInfo {
    fn to_table(&self) -> String {
        let mut lines = Vec::new();

        if self.mubase_exists {
            lines.push(format!("{}", "MU Status: Ready".green().bold()));

            if let Some(path) = &self.mubase_path {
                lines.push(format!("  {}: {}", "Database".cyan(), path));
            }

            if let Some(stats) = &self.stats {
                lines.push(format!("  {}: {}", "Nodes".cyan(), stats.node_count));
                lines.push(format!("  {}: {}", "Edges".cyan(), stats.edge_count));

                // Show type breakdown if we have it
                if !stats.type_counts.is_empty() {
                    lines.push(format!("  {}:", "By Type".cyan()));
                    for (node_type, count) in &stats.type_counts {
                        lines.push(format!("    {}: {}", node_type, count));
                    }
                }
            }

            lines.push(format!(
                "  {}: {}",
                "Config".cyan(),
                if self.config_exists { "Yes" } else { "No" }
            ));
        } else {
            lines.push(format!("{}", "MU Status: Not initialized".yellow().bold()));
            lines.push(format!(
                "  {}: {}",
                "Config".cyan(),
                if self.config_exists { "Yes" } else { "No" }
            ));
        }

        if let Some(action) = &self.next_action {
            lines.push(String::new());
            lines.push(format!("{}: {}", "Next action".yellow(), action));
        }

        lines.push(format!(
            "\n{}",
            format!("({} ms)", self.duration_ms).dimmed()
        ));

        lines.join("\n")
    }

    fn to_mu(&self) -> String {
        let mut lines = Vec::new();
        lines.push(":: status".to_string());

        if self.mubase_exists {
            lines.push("# MU: Ready".to_string());
            if let Some(stats) = &self.stats {
                lines.push(format!("  nodes: {}", stats.node_count));
                lines.push(format!("  edges: {}", stats.edge_count));
            }
        } else {
            lines.push("# MU: Not initialized".to_string());
        }

        if let Some(action) = &self.next_action {
            lines.push(format!("  -> {}", action));
        }

        lines.join("\n")
    }
}

/// Run the status command.
///
/// Shows MU status and recommended next steps:
/// - Configuration status
/// - Database status and statistics
/// - Actionable guidance for what to do next
pub async fn run(path: &str, format: OutputFormat) -> Result<()> {
    let start = Instant::now();

    // Resolve the path
    let root = std::path::Path::new(path)
        .canonicalize()
        .unwrap_or_else(|_| std::path::PathBuf::from(path));

    // Check if config exists
    let config_exists = root.join(".murc.toml").exists();

    // Find mubase
    let mubase_path = find_mubase_path(&root);
    let mubase_exists = mubase_path.is_some();

    let mut stats = None;
    let message;
    let mut next_action = None;

    if let Some(ref db_path) = mubase_path {
        // Open database in read-only mode
        match Connection::open_with_flags(
            db_path,
            duckdb::Config::default()
                .access_mode(duckdb::AccessMode::ReadOnly)
                .unwrap_or_default(),
        ) {
            Ok(conn) => {
                stats = get_stats(&conn).ok();
                message = "MU ready. All systems operational.".to_string();
            }
            Err(e) => {
                message = format!("Database exists but could not be opened: {}", e);
                next_action = Some("mu bootstrap --force".to_string());
            }
        }
    } else {
        message = "No .mu/mubase found. Run 'mu bootstrap' to initialize.".to_string();
        next_action = Some("mu bootstrap".to_string());
    }

    let duration_ms = start.elapsed().as_millis() as u64;

    let status = StatusInfo {
        config_exists,
        mubase_exists,
        mubase_path: mubase_path.map(|p| p.display().to_string()),
        stats,
        next_action,
        message,
        duration_ms,
    };

    Output::new(status, format).render()
}
