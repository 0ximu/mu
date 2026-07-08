//! Doctor command - Health check for MU installation
//!
//! Performs comprehensive health checks on the MU installation:
//! - Database existence and integrity
//! - Schema version compatibility
//! - Graph statistics
//! - MCP configuration

use std::path::Path;

use colored::Colorize;
use duckdb::Connection;
use serde::Serialize;

use crate::output::{Output, OutputFormat, TableDisplay};

/// Current schema version expected by this CLI — the same constant the
/// storage layer stamps into freshly bootstrapped databases. Duplicating
/// the value here is how doctor ended up calling its own DBs "newer than CLI".
use crate::engine::storage::schema::SCHEMA_VERSION as CURRENT_SCHEMA_VERSION;

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

/// Compare stored version against current version
/// Returns a tuple of (display message, is_ok)
fn compare_versions(stored: &str, current: &str) -> (&'static str, bool) {
    use crate::engine::storage::migrations::compare_semver;
    match compare_semver(stored, current) {
        std::cmp::Ordering::Equal => ("current", true),
        std::cmp::Ordering::Less => ("outdated", false),
        std::cmp::Ordering::Greater => ("newer than CLI", false),
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


/// Run the doctor command
pub async fn run(path: &str, format: OutputFormat) -> anyhow::Result<()> {
    let root = Path::new(path)
        .canonicalize()
        .unwrap_or_else(|_| Path::new(path).to_path_buf());

    let mut checks = Vec::new();
    let mut recommendations = Vec::new();

    // Check 1: Database existence
    let mubase_path = crate::mubase::find_mubase_in(&root);
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
    fn test_version_comparison_current() {
        let (msg, is_ok) = compare_versions("1.0.0", "1.0.0");
        assert_eq!(msg, "current");
        assert!(is_ok);
    }

    #[test]
    fn test_freshly_created_db_reports_current() {
        // Regression: doctor called a DB its own binary just created
        // "newer than CLI" because it compared against a stale constant.
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("test.mubase");
        std::mem::forget(dir);
        let db = crate::engine::storage::MUbase::open(&db_path).unwrap();

        let stored = db
            .with_connection(|conn| Ok(get_schema_version(conn)))
            .unwrap()
            .expect("fresh db must have a schema_version");

        let (msg, is_ok) = compare_versions(&stored, CURRENT_SCHEMA_VERSION);
        assert_eq!(msg, "current");
        assert!(is_ok);
    }

    #[test]
    fn test_version_comparison_not_lexicographic() {
        // "1.2.0" < "1.10.0" numerically, even though ">" lexicographically.
        let (msg, is_ok) = compare_versions("1.2.0", "1.10.0");
        assert_eq!(msg, "outdated");
        assert!(!is_ok);

        let (msg, is_ok) = compare_versions("1.10.0", "1.2.0");
        assert_eq!(msg, "newer than CLI");
        assert!(!is_ok);
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
