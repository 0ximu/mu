//! Sus command - Risk assessment / warnings before touching code
//!
//! Analyzes a file or node to identify potential issues before modification:
//! - High impact (many dependents)
//! - Stale code (not modified recently)
//! - Security sensitive (auth/crypto logic)
//! - No tests detected
//! - High complexity
//!
//! When run without arguments, scans the entire codebase for suspicious files.

use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::{params, Connection};
use std::path::PathBuf;

use crate::output::OutputFormat;

/// Warning level for sus checks
#[derive(Debug, Clone, Copy, serde::Serialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum WarningLevel {
    Info,
    Warn,
    Error,
}

/// A single warning from the sus check
#[derive(Debug, Clone, serde::Serialize)]
pub struct SusWarning {
    pub level: WarningLevel,
    pub category: String,
    pub message: String,
    pub suggestion: Option<String>,
}

/// Result of a sus check
#[derive(Debug, Clone, serde::Serialize)]
pub struct SusResult {
    pub target: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub file_path: Option<String>,
    pub warnings: Vec<SusWarning>,
    pub risk_score: u8,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub db_found: bool,
}

impl SusResult {
    fn is_sus(&self) -> bool {
        !self.warnings.is_empty()
    }
}

/// Result of a codebase-wide scan
#[derive(Debug, serde::Serialize)]
pub struct ScanResult {
    pub total_scanned: usize,
    pub suspicious_count: usize,
    pub results: Vec<SusResult>,
}

/// Run the sus command - risk assessment with personality
pub async fn run(path: &str, threshold: u8, format: OutputFormat) -> Result<()> {
    // Find the MUbase database
    let db_path = match find_mubase(".") {
        Ok(path) => path,
        Err(_) => {
            // No database found - show friendly message
            let result = SusResult {
                target: path.to_string(),
                file_path: None,
                warnings: vec![],
                risk_score: 0,
                db_found: false,
            };
            match format {
                OutputFormat::Json => {
                    println!("{}", serde_json::to_string_pretty(&result)?);
                }
                _ => {
                    print_sus_output(&result);
                }
            }
            return Ok(());
        }
    };

    // Open database in read-only mode
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    // If path is "." or empty, scan the entire codebase
    if path == "." || path.is_empty() {
        let scan_result = scan_all_nodes(&conn, threshold)?;
        match format {
            OutputFormat::Json => {
                println!("{}", serde_json::to_string_pretty(&scan_result)?);
            }
            _ => {
                print_scan_output(&scan_result);
            }
        }
        return Ok(());
    }

    // Resolve path to node ID for single-file analysis
    let node_id = match resolve_node_id(&conn, path) {
        Ok(id) => id,
        Err(_) => {
            // Node not found - could be a new file
            let result = SusResult {
                target: path.to_string(),
                file_path: None,
                warnings: vec![SusWarning {
                    level: WarningLevel::Info,
                    category: "unknown".to_string(),
                    message: "Node not found in database. This might be a new file.".to_string(),
                    suggestion: Some("Run 'mu bootstrap' to reindex the codebase.".to_string()),
                }],
                risk_score: 0,
                db_found: true,
            };
            match format {
                OutputFormat::Json => {
                    println!("{}", serde_json::to_string_pretty(&result)?);
                }
                _ => {
                    print_sus_output(&result);
                }
            }
            return Ok(());
        }
    };

    // Perform risk assessment on single node
    let result = analyze_risk(&conn, &node_id, threshold)?;

    match format {
        OutputFormat::Json => {
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
        _ => {
            print_sus_output(&result);
        }
    }

    Ok(())
}

/// Scan all nodes in the codebase for suspicious patterns
fn scan_all_nodes(conn: &Connection, threshold: u8) -> Result<ScanResult> {
    // Query all module-type nodes (files)
    let mut stmt = conn.prepare(
        "SELECT id, file_path FROM nodes
         WHERE type = 'module'
         AND file_path IS NOT NULL
         AND file_path NOT LIKE '%test%'
         AND file_path NOT LIKE '%spec%'
         AND file_path NOT LIKE '%mock%'
         ORDER BY file_path
         LIMIT 1000",
    )?;

    let mut rows = stmt.query([])?;
    let mut all_results: Vec<SusResult> = Vec::new();
    let mut total_scanned = 0;

    while let Some(row) = rows.next()? {
        let node_id: String = row.get(0)?;
        total_scanned += 1;

        // Analyze each node
        if let Ok(result) = analyze_risk(conn, &node_id, threshold) {
            // Only keep results with risk score > 0
            if result.risk_score > 0 {
                all_results.push(result);
            }
        }
    }

    // Sort by risk score descending
    all_results.sort_by(|a, b| b.risk_score.cmp(&a.risk_score));

    // Keep top 20 most suspicious
    all_results.truncate(20);

    let suspicious_count = all_results.len();

    Ok(ScanResult {
        total_scanned,
        suspicious_count,
        results: all_results,
    })
}

/// Print output for codebase-wide scan
fn print_scan_output(scan: &ScanResult) {
    println!();
    println!("{}", "SUS Check: Codebase Scan".yellow().bold());
    println!();

    if scan.suspicious_count == 0 {
        println!(
            "{}",
            format!("Scanned {} files. All clear, nothing sus!", scan.total_scanned).green()
        );
        println!();
        return;
    }

    println!(
        "{}",
        format!(
            "Scanned {} files. Found {} suspicious:",
            scan.total_scanned, scan.suspicious_count
        )
        .dimmed()
    );
    println!();

    for result in &scan.results {
        // Risk score badge
        let score_color = if result.risk_score >= 7 {
            colored::Color::Red
        } else if result.risk_score >= 4 {
            colored::Color::Yellow
        } else {
            colored::Color::Green
        };

        let file_display = result
            .file_path
            .as_deref()
            .unwrap_or(&result.target);

        println!(
            "{} {}",
            format!("[{}/10]", result.risk_score)
                .color(score_color)
                .bold(),
            file_display.bold()
        );

        // Show warnings compactly
        for warning in &result.warnings {
            let icon = match warning.level {
                WarningLevel::Error => "!!".red(),
                WarningLevel::Warn => "! ".yellow(),
                WarningLevel::Info => "i ".cyan(),
            };
            println!(
                "       {} {}",
                icon,
                warning.message.dimmed()
            );
        }
        println!();
    }
}

fn print_sus_output(result: &SusResult) {
    println!();
    let display_target = result.file_path.as_deref().unwrap_or(&result.target);
    println!("{} {}", "SUS Check:".yellow().bold(), display_target.bold());
    println!();

    if !result.db_found {
        println!(
            "{}",
            "No MU database found. Run 'mu bootstrap' first.".yellow()
        );
        println!();
        println!(
            "{}",
            "Once indexed, I'll sniff out anything sus about this code.".dimmed()
        );
        println!();
        println!("{}", "[OK] Nothing to check yet.".green());
    } else if !result.is_sus() {
        println!("{}", "[OK] All clear. Not sus.".green());
    } else {
        // Display warnings grouped by level
        for warning in &result.warnings {
            let (icon, color) = match warning.level {
                WarningLevel::Error => ("!!", colored::Color::Red),
                WarningLevel::Warn => ("!", colored::Color::Yellow),
                WarningLevel::Info => ("i", colored::Color::Cyan),
            };

            println!(
                "{} {}",
                icon.color(color),
                warning.category.to_uppercase().color(color).bold()
            );
            println!("   {}", warning.message);
            if let Some(suggestion) = &warning.suggestion {
                println!("   {} {}", "->".green(), suggestion);
            }
            println!();
        }

        // Risk score
        let score_color = if result.risk_score >= 7 {
            colored::Color::Red
        } else if result.risk_score >= 4 {
            colored::Color::Yellow
        } else {
            colored::Color::Green
        };

        println!(
            "{} {}{}",
            "Risk Score:".dimmed(),
            format!("{}/10", result.risk_score)
                .color(score_color)
                .bold(),
            if result.risk_score >= 5 {
                " - Proceed with caution".dimmed().to_string()
            } else {
                " - Looks OK".dimmed().to_string()
            }
        );
    }

    println!();
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

        // Move up to parent
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

/// Try to resolve a partial node ID or file path to a full node ID
fn resolve_node_id(conn: &Connection, partial: &str) -> Result<String> {
    // First try exact match
    let mut stmt = conn.prepare("SELECT id FROM nodes WHERE id = ?")?;
    let mut rows = stmt.query(params![partial])?;
    if let Some(row) = rows.next()? {
        return Ok(row.get(0)?);
    }

    // Try to find by file path
    let mut stmt =
        conn.prepare("SELECT id FROM nodes WHERE file_path = ? AND type = 'module' LIMIT 1")?;
    let mut rows = stmt.query(params![partial])?;
    if let Some(row) = rows.next()? {
        return Ok(row.get(0)?);
    }

    // Try prefix/pattern match
    let pattern = format!("%{}%", partial);
    let mut stmt =
        conn.prepare("SELECT id FROM nodes WHERE id LIKE ? OR file_path LIKE ? LIMIT 10")?;
    let mut rows = stmt.query(params![pattern, pattern])?;

    let mut matches = Vec::new();
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        matches.push(id);
    }

    match matches.len() {
        0 => Err(anyhow::anyhow!("Node not found: {}", partial)),
        1 => Ok(matches.into_iter().next().unwrap()),
        _ => {
            // Multiple matches - prefer module nodes and shorter paths
            for m in &matches {
                if m.starts_with("mod:") && m.ends_with(partial) {
                    return Ok(m.clone());
                }
            }

            // Sort by node type prefix (mod: first) then alphabetically
            matches.sort_by(|a, b| {
                let type_priority = |id: &str| {
                    if id.starts_with("cls:") {
                        0
                    } else if id.starts_with("mod:") {
                        1
                    } else if id.starts_with("fn:") {
                        2
                    } else {
                        3
                    }
                };
                type_priority(a).cmp(&type_priority(b)).then(a.cmp(b))
            });

            // Return first sorted match
            Ok(matches.into_iter().next().unwrap())
        }
    }
}

/// Analyze risk factors for a node
fn analyze_risk(conn: &Connection, node_id: &str, threshold: u8) -> Result<SusResult> {
    let mut warnings = Vec::new();
    let mut risk_score = 0u8;

    // Get node information
    let node_info = get_node_info(conn, node_id)?;
    let file_path = node_info.file_path.clone();
    let file_path_str = file_path.as_deref().unwrap_or("");
    let complexity = node_info.complexity;
    let node_name = node_info.name.to_lowercase();

    // Check 1: High impact (many dependents)
    let dependent_count = count_dependents(conn, node_id)?;
    if dependent_count > 20 {
        warnings.push(SusWarning {
            level: WarningLevel::Error,
            category: "high impact".to_string(),
            message: format!("{} files/modules depend on this code", dependent_count),
            suggestion: Some(
                "Changes here will ripple across the codebase. Consider adding tests first."
                    .to_string(),
            ),
        });
        risk_score += 3;
    } else if dependent_count > 10 {
        warnings.push(SusWarning {
            level: WarningLevel::Warn,
            category: "high impact".to_string(),
            message: format!("{} files/modules depend on this code", dependent_count),
            suggestion: Some("Moderate impact - test thoroughly before shipping.".to_string()),
        });
        risk_score += 2;
    } else if dependent_count > 5 {
        warnings.push(SusWarning {
            level: WarningLevel::Info,
            category: "impact".to_string(),
            message: format!("{} files/modules depend on this code", dependent_count),
            suggestion: None,
        });
        risk_score += 1;
    }

    // Check 2: High complexity
    if complexity > 15 {
        warnings.push(SusWarning {
            level: WarningLevel::Error,
            category: "complexity".to_string(),
            message: format!("Cyclomatic complexity is {} (very high)", complexity),
            suggestion: Some("Consider refactoring before making changes.".to_string()),
        });
        risk_score += 3;
    } else if complexity > 10 {
        warnings.push(SusWarning {
            level: WarningLevel::Warn,
            category: "complexity".to_string(),
            message: format!("Cyclomatic complexity is {} (high)", complexity),
            suggestion: Some("Complex code - changes may introduce bugs.".to_string()),
        });
        risk_score += 2;
    }

    // Check 3: Security sensitive (auth, crypto, password, token, secret, key)
    let security_keywords = [
        "auth",
        "crypto",
        "password",
        "token",
        "secret",
        "key",
        "session",
        "credential",
    ];
    let is_security_sensitive = security_keywords
        .iter()
        .any(|kw| node_name.contains(kw) || file_path_str.to_lowercase().contains(kw));

    if is_security_sensitive {
        warnings.push(SusWarning {
            level: WarningLevel::Error,
            category: "security sensitive".to_string(),
            message: "This code handles authentication, secrets, or cryptography".to_string(),
            suggestion: Some("Extra caution required. Security review recommended.".to_string()),
        });
        risk_score += 3;
    }

    // Check 4: No tests detected
    let has_tests = check_for_tests(conn, node_id, file_path_str)?;
    if !has_tests && dependent_count > 0 {
        warnings.push(SusWarning {
            level: WarningLevel::Warn,
            category: "no tests".to_string(),
            message: "No test coverage detected for this code".to_string(),
            suggestion: Some("Consider writing tests before making changes.".to_string()),
        });
        risk_score += 2;
    }

    // Cap risk score at 10
    risk_score = risk_score.min(10);

    // Filter warnings by threshold
    let filtered_warnings: Vec<SusWarning> = warnings
        .into_iter()
        .filter(|w| {
            let level_score = match w.level {
                WarningLevel::Error => 3,
                WarningLevel::Warn => 2,
                WarningLevel::Info => 1,
            };
            level_score >= threshold
        })
        .collect();

    Ok(SusResult {
        target: node_id.to_string(),
        file_path,
        warnings: filtered_warnings,
        risk_score,
        db_found: true,
    })
}

/// Node information for analysis
struct NodeInfo {
    name: String,
    file_path: Option<String>,
    complexity: u32,
}

/// Get node information
fn get_node_info(conn: &Connection, node_id: &str) -> Result<NodeInfo> {
    let mut stmt = conn.prepare("SELECT name, file_path, complexity FROM nodes WHERE id = ?")?;
    let mut rows = stmt.query(params![node_id])?;

    if let Some(row) = rows.next()? {
        Ok(NodeInfo {
            name: row.get(0)?,
            file_path: row.get(1)?,
            complexity: row.get(2).unwrap_or(0),
        })
    } else {
        Err(anyhow::anyhow!("Node not found: {}", node_id))
    }
}

/// Count how many nodes depend on this one (reverse dependencies)
fn count_dependents(conn: &Connection, node_id: &str) -> Result<usize> {
    let mut stmt =
        conn.prepare("SELECT COUNT(DISTINCT source_id) FROM edges WHERE target_id = ?")?;
    let mut rows = stmt.query(params![node_id])?;

    if let Some(row) = rows.next()? {
        let count: i64 = row.get(0)?;
        Ok(count as usize)
    } else {
        Ok(0)
    }
}

/// Check if there are test files for this code
fn check_for_tests(conn: &Connection, node_id: &str, file_path: &str) -> Result<bool> {
    // Strategy 1: Look for test files that import/call this module
    let mut stmt = conn.prepare(
        "SELECT COUNT(*) FROM edges e
         JOIN nodes n ON n.id = e.source_id
         WHERE e.target_id = ?
         AND (n.file_path LIKE '%test%' OR n.file_path LIKE '%spec%')
         LIMIT 1",
    )?;
    let mut rows = stmt.query(params![node_id])?;

    if let Some(row) = rows.next()? {
        let count: i64 = row.get(0)?;
        if count > 0 {
            return Ok(true);
        }
    }

    // Strategy 2: Look for test files with similar names
    if !file_path.is_empty() {
        // Extract base name without extension
        let path = std::path::Path::new(file_path);
        let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("");

        // Common test patterns: test_foo.py, foo_test.py, foo.test.js, FooTests.cs, etc.
        let test_patterns = vec![
            format!("%test%{}%", stem),
            format!("%{}%test%", stem),
            format!("%{}Tests%", stem),
            format!("%{}Spec%", stem),
        ];

        for pattern in test_patterns {
            let mut stmt =
                conn.prepare("SELECT COUNT(*) FROM nodes WHERE file_path LIKE ? LIMIT 1")?;
            let mut rows = stmt.query(params![pattern])?;

            if let Some(row) = rows.next()? {
                let count: i64 = row.get(0)?;
                if count > 0 {
                    return Ok(true);
                }
            }
        }
    }

    Ok(false)
}
