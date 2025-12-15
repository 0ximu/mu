//! Doctor command - Health check for MU installation
//!
//! Performs comprehensive health checks on the MU installation:
//! - Database existence and integrity
//! - Schema version compatibility
//! - Graph statistics
//! - Embeddings coverage
//! - MCP configuration

use std::path::{Path, PathBuf};

use colored::Colorize;
use duckdb::Connection;
use serde::Serialize;

use crate::output::{Output, OutputFormat, TableDisplay};

/// Current schema version expected by this CLI
const CURRENT_SCHEMA_VERSION: &str = "1.0.0";

/// Status of a health check item
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum CheckStatus {
    Ok,
    Warning,
    Error,
}

impl CheckStatus {
    fn colored_icon(&self) -> String {
        match self {
            CheckStatus::Ok => "[OK]".green().to_string(),
            CheckStatus::Warning => "[!!]".yellow().to_string(),
            CheckStatus::Error => "[!!]".red().to_string(),
        }
    }
}

/// A single health check item
#[derive(Debug, Clone, Serialize)]
pub struct CheckItem {
    pub status: CheckStatus,
    pub label: String,
    pub value: String,
}

impl CheckItem {
    fn ok(label: impl Into<String>, value: impl Into<String>) -> Self {
        Self {
            status: CheckStatus::Ok,
            label: label.into(),
            value: value.into(),
        }
    }

    fn warning(label: impl Into<String>, value: impl Into<String>) -> Self {
        Self {
            status: CheckStatus::Warning,
            label: label.into(),
            value: value.into(),
        }
    }

    fn error(label: impl Into<String>, value: impl Into<String>) -> Self {
        Self {
            status: CheckStatus::Error,
            label: label.into(),
            value: value.into(),
        }
    }
}

/// Result of health check
#[derive(Debug, Serialize)]
pub struct DoctorResult {
    pub checks: Vec<CheckItem>,
    pub recommendations: Vec<String>,
}

impl TableDisplay for DoctorResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!("{}\n", "MU Health Check".cyan().bold()));
        output.push_str(&format!("{}\n", "\u{2500}".repeat(40).dimmed()));

        for check in &self.checks {
            output.push_str(&format!(
                "{} {}: {}\n",
                check.status.colored_icon(),
                check.label,
                check.value
            ));
        }

        if !self.recommendations.is_empty() {
            output.push_str(&format!("\n{}\n", "Recommendations:".yellow().bold()));
            for rec in &self.recommendations {
                output.push_str(&format!("  - {}\n", rec));
            }
        }

        output
    }

    fn to_mu(&self) -> String {
        let mut lines = vec![":: doctor".to_string()];

        for check in &self.checks {
            let status_str = match check.status {
                CheckStatus::Ok => "ok",
                CheckStatus::Warning => "warn",
                CheckStatus::Error => "error",
            };
            lines.push(format!(
                "# {} [{}]: {}",
                check.label, status_str, check.value
            ));
        }

        if !self.recommendations.is_empty() {
            lines.push("# recommendations:".to_string());
            for rec in &self.recommendations {
                lines.push(format!("  -> {}", rec));
            }
        }

        lines.join("\n")
    }
}

/// Find the mubase database path
fn find_mubase_path(root: &Path) -> Option<PathBuf> {
    let new_path = root.join(".mu").join("mubase");
    if new_path.exists() {
        return Some(new_path);
    }

    let legacy_path = root.join(".mubase");
    if legacy_path.exists() {
        return Some(legacy_path);
    }

    None
}

/// Get file size in human-readable format
fn format_file_size(bytes: u64) -> String {
    const KB: u64 = 1024;
    const MB: u64 = KB * 1024;
    const GB: u64 = MB * 1024;

    if bytes >= GB {
        format!("{:.1} GB", bytes as f64 / GB as f64)
    } else if bytes >= MB {
        format!("{:.0} MB", bytes as f64 / MB as f64)
    } else if bytes >= KB {
        format!("{:.0} KB", bytes as f64 / KB as f64)
    } else {
        format!("{} bytes", bytes)
    }
}

/// Check for MCP configuration
fn check_mcp_config(root: &Path) -> Option<String> {
    // Check for .claude.json
    let claude_config = root.join(".claude.json");
    if claude_config.exists() {
        return Some(".claude.json".to_string());
    }

    // Check for mcp.json
    let mcp_config = root.join("mcp.json");
    if mcp_config.exists() {
        return Some("mcp.json".to_string());
    }

    // Check home directory for global Claude config
    if let Some(home) = dirs::home_dir() {
        let global_claude = home.join(".claude.json");
        if global_claude.exists() {
            return Some("~/.claude.json".to_string());
        }
    }

    None
}

/// Get database schema version
fn get_schema_version(conn: &Connection) -> Option<String> {
    conn.query_row(
        "SELECT value FROM metadata WHERE key = 'schema_version'",
        [],
        |row| row.get::<_, String>(0),
    )
    .ok()
}

/// Parse the major version number from a semver string (e.g., "1.0.0" -> 1)
fn parse_major_version(version: &str) -> Option<u32> {
    version.split('.').next()?.parse().ok()
}

/// Compare stored version against current version
/// Returns a tuple of (display message, is_ok)
fn compare_versions(stored: &str, current: &str) -> (&'static str, bool) {
    if stored == current {
        return ("current", true);
    }

    let stored_major = parse_major_version(stored);
    let current_major = parse_major_version(current);

    match (stored_major, current_major) {
        (Some(s), Some(c)) if s < c => ("outdated", false),
        (Some(s), Some(c)) if s > c => ("newer than CLI", false),
        _ => {
            // Fall back to string comparison if major versions are equal but full versions differ
            if stored < current {
                ("outdated", false)
            } else {
                ("newer than CLI", false)
            }
        }
    }
}

/// Get node count from database
fn get_node_count(conn: &Connection) -> usize {
    conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))
        .unwrap_or(0)
}

/// Get edge count from database
fn get_edge_count(conn: &Connection) -> usize {
    conn.query_row("SELECT COUNT(*) FROM edges", [], |row| row.get(0))
        .unwrap_or(0)
}

/// Get embeddings stats
fn get_embeddings_stats(conn: &Connection) -> Option<(usize, usize)> {
    // Check if embeddings table exists
    let table_exists: bool = conn
        .query_row(
            "SELECT COUNT(*) > 0 FROM information_schema.tables WHERE table_name = 'embeddings'",
            [],
            |row| row.get(0),
        )
        .unwrap_or(false);

    if !table_exists {
        return None;
    }

    let embedding_count: usize = conn
        .query_row("SELECT COUNT(*) FROM embeddings", [], |row| row.get(0))
        .unwrap_or(0);

    let node_count: usize = conn
        .query_row(
            "SELECT COUNT(*) FROM nodes WHERE type != 'external'",
            [],
            |row| row.get(0),
        )
        .unwrap_or(0);

    Some((embedding_count, node_count))
}

/// Run the doctor command
pub async fn run(path: &str, format: OutputFormat) -> anyhow::Result<()> {
    let root = Path::new(path)
        .canonicalize()
        .unwrap_or_else(|_| Path::new(path).to_path_buf());

    let mut checks = Vec::new();
    let mut recommendations = Vec::new();

    // Check 1: Database existence
    let mubase_path = find_mubase_path(&root);
    match &mubase_path {
        Some(path) => {
            // Get file size
            let size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
            checks.push(CheckItem::ok(
                "Database exists",
                format!("{} ({})", path.display(), format_file_size(size)),
            ));
        }
        None => {
            checks.push(CheckItem::error("Database exists", "not found"));
            recommendations.push("Initialize database: mu bootstrap".to_string());
        }
    }

    // Continue with database checks if it exists
    if let Some(ref db_path) = mubase_path {
        match Connection::open_with_flags(
            db_path,
            duckdb::Config::default()
                .access_mode(duckdb::AccessMode::ReadOnly)
                .unwrap_or_default(),
        ) {
            Ok(conn) => {
                // Check 2: Schema version
                match get_schema_version(&conn) {
                    Some(version) => {
                        let (status_msg, is_ok) =
                            compare_versions(&version, CURRENT_SCHEMA_VERSION);
                        if is_ok {
                            checks.push(CheckItem::ok(
                                "Schema version",
                                format!("{} ({})", version, status_msg),
                            ));
                        } else if status_msg == "outdated" {
                            checks.push(CheckItem::warning(
                                "Schema version",
                                format!(
                                    "{} ({}, current: {})",
                                    version, status_msg, CURRENT_SCHEMA_VERSION
                                ),
                            ));
                            recommendations
                                .push("Rebuild database: mu bootstrap --force".to_string());
                        } else {
                            // newer than CLI
                            checks.push(CheckItem::warning(
                                "Schema version",
                                format!("{} ({})", version, status_msg),
                            ));
                        }
                    }
                    None => {
                        checks.push(CheckItem::warning("Schema version", "unknown"));
                    }
                }

                // Check 3: Node count
                let node_count = get_node_count(&conn);
                if node_count > 0 {
                    checks.push(CheckItem::ok("Node count", node_count.to_string()));
                } else {
                    checks.push(CheckItem::warning("Node count", "0 (empty database)"));
                    recommendations.push("Rebuild database: mu bootstrap --force".to_string());
                }

                // Check 4: Edge count
                let edge_count = get_edge_count(&conn);
                if edge_count > 0 {
                    checks.push(CheckItem::ok("Edge count", edge_count.to_string()));
                } else {
                    checks.push(CheckItem::warning("Edge count", "0"));
                }

                // Check 5: Embeddings
                match get_embeddings_stats(&conn) {
                    Some((embedding_count, node_count)) => {
                        if node_count > 0 {
                            let percentage =
                                (embedding_count as f64 / node_count as f64 * 100.0) as usize;
                            if percentage >= 100 {
                                checks.push(CheckItem::ok(
                                    "Embeddings",
                                    format!("{} (100%)", embedding_count),
                                ));
                            } else if percentage > 0 {
                                checks.push(CheckItem::warning(
                                    "Embeddings",
                                    format!("{} ({}%)", embedding_count, percentage),
                                ));
                                recommendations.push(
                                    "Generate missing embeddings: mu bootstrap --embed".to_string(),
                                );
                            } else {
                                checks.push(CheckItem::warning("Embeddings", "0 (not generated)"));
                                recommendations.push(
                                    "Enable semantic search: mu bootstrap --embed".to_string(),
                                );
                            }
                        } else {
                            checks.push(CheckItem::warning("Embeddings", "no nodes to embed"));
                        }
                    }
                    None => {
                        checks.push(CheckItem::warning("Embeddings", "not configured"));
                        recommendations
                            .push("Enable semantic search: mu bootstrap --embed".to_string());
                    }
                }
            }
            Err(e) => {
                checks.push(CheckItem::error(
                    "Database",
                    format!("failed to open: {}", e),
                ));
                recommendations.push("Rebuild database: mu bootstrap --force".to_string());
            }
        }
    }

    // Check 6: MCP configuration
    match check_mcp_config(&root) {
        Some(config_file) => {
            checks.push(CheckItem::ok(
                "MCP config",
                format!("found in {}", config_file),
            ));
        }
        None => {
            checks.push(CheckItem::warning("MCP config", "not found"));
            recommendations
                .push("Configure MCP for AI assistant integration: mu serve --mcp".to_string());
        }
    }

    let result = DoctorResult {
        checks,
        recommendations,
    };

    Output::new(result, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_file_size() {
        assert_eq!(format_file_size(500), "500 bytes");
        assert_eq!(format_file_size(1024), "1 KB");
        assert_eq!(format_file_size(1024 * 1024), "1 MB");
        assert_eq!(format_file_size(1024 * 1024 * 1024), "1.0 GB");
        assert_eq!(format_file_size(45 * 1024 * 1024), "45 MB");
    }

    #[test]
    fn test_check_item_creation() {
        let ok = CheckItem::ok("Test", "value");
        assert_eq!(ok.status, CheckStatus::Ok);

        let warn = CheckItem::warning("Test", "value");
        assert_eq!(warn.status, CheckStatus::Warning);

        let err = CheckItem::error("Test", "value");
        assert_eq!(err.status, CheckStatus::Error);
    }

    #[test]
    fn test_parse_major_version() {
        assert_eq!(parse_major_version("1.0.0"), Some(1));
        assert_eq!(parse_major_version("2.5.3"), Some(2));
        assert_eq!(parse_major_version("10.0.0"), Some(10));
        assert_eq!(parse_major_version("0.9.0"), Some(0));
        assert_eq!(parse_major_version("invalid"), None);
        assert_eq!(parse_major_version(""), None);
    }

    #[test]
    fn test_version_comparison_current() {
        let (msg, is_ok) = compare_versions("1.0.0", "1.0.0");
        assert_eq!(msg, "current");
        assert!(is_ok);
    }

    #[test]
    fn test_version_comparison_outdated() {
        // Major version outdated
        let (msg, is_ok) = compare_versions("0.9.0", "1.0.0");
        assert_eq!(msg, "outdated");
        assert!(!is_ok);

        // Same major, minor outdated
        let (msg, is_ok) = compare_versions("1.0.0", "1.1.0");
        assert_eq!(msg, "outdated");
        assert!(!is_ok);
    }

    #[test]
    fn test_version_comparison_newer() {
        // Major version newer
        let (msg, is_ok) = compare_versions("2.0.0", "1.0.0");
        assert_eq!(msg, "newer than CLI");
        assert!(!is_ok);

        // Same major, minor newer
        let (msg, is_ok) = compare_versions("1.2.0", "1.1.0");
        assert_eq!(msg, "newer than CLI");
        assert!(!is_ok);
    }
}
