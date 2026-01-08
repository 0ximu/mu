//! Review command - PR Intelligence
//!
//! Analyzes code changes and provides intelligent review insights:
//! - Risk scoring based on impact, complexity, and caller count
//! - Test coverage gap detection
//! - Suggested reviewers based on code ownership
//!
//! This is the flagship command for mu v0.0.2

use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::process::Command;

use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::Connection;
use serde::Serialize;

use super::graph::GraphData;
use crate::output::{Output, OutputFormat, TableDisplay};

/// Risk levels for changes
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum RiskLevel {
    Low,
    Medium,
    High,
    Critical,
}

impl RiskLevel {
    fn from_score(score: f64) -> Self {
        if score > 100.0 {
            RiskLevel::Critical
        } else if score > 50.0 {
            RiskLevel::High
        } else if score > 20.0 {
            RiskLevel::Medium
        } else {
            RiskLevel::Low
        }
    }

    fn as_str(&self) -> &'static str {
        match self {
            RiskLevel::Low => "LOW",
            RiskLevel::Medium => "MEDIUM",
            RiskLevel::High => "HIGH",
            RiskLevel::Critical => "CRITICAL",
        }
    }
}

/// A changed function with risk analysis
#[derive(Debug, Clone, Serialize)]
pub struct AnalyzedChange {
    pub name: String,
    pub entity_type: String,
    pub file_path: String,
    pub change_type: String, // added, modified, removed
    pub risk_level: RiskLevel,
    pub risk_score: f64,
    pub caller_count: usize,
    pub transitive_dependents: usize,
    pub complexity: Option<u32>,
    pub complexity_delta: Option<i32>,
    pub last_modified: Option<String>,
    pub last_author: Option<String>,
}

/// A suggested reviewer with ownership percentage
#[derive(Debug, Clone, Serialize)]
pub struct SuggestedReviewer {
    pub name: String,
    pub ownership_percent: u32,
    pub files_owned: Vec<String>,
}

/// Test coverage gap
#[derive(Debug, Clone, Serialize)]
pub struct TestGap {
    pub function_name: String,
    pub file_path: String,
    pub reason: String,
}

/// Result of the review command
#[derive(Debug, Serialize)]
pub struct ReviewResult {
    pub title: String,
    pub summary: ReviewSummary,
    pub high_risk_changes: Vec<AnalyzedChange>,
    pub all_changes: Vec<AnalyzedChange>,
    pub suggested_reviewers: Vec<SuggestedReviewer>,
    pub test_gaps: Vec<TestGap>,
    pub recommendations: Vec<String>,
}

/// Summary statistics
#[derive(Debug, Serialize)]
pub struct ReviewSummary {
    pub files_changed: usize,
    pub functions_modified: usize,
    pub functions_added: usize,
    pub functions_removed: usize,
    pub total_risk_score: f64,
}

impl TableDisplay for ReviewResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        // Header
        output.push_str(&format!("\n{}\n", "═".repeat(65).cyan()));
        output.push_str(&format!(
            "{}  MU Code Review: {}\n",
            " ".repeat(15),
            self.title.cyan().bold()
        ));
        output.push_str(&format!("{}\n\n", "═".repeat(65).cyan()));

        // Summary
        output.push_str(&format!("{}\n", "Summary".bold()));
        output.push_str(&format!(
            "   Files changed: {}\n",
            self.summary.files_changed.to_string().cyan()
        ));
        output.push_str(&format!(
            "   Functions modified: {}\n",
            self.summary.functions_modified.to_string().yellow()
        ));
        output.push_str(&format!(
            "   Functions added: {}\n",
            self.summary.functions_added.to_string().green()
        ));
        output.push_str(&format!(
            "   Functions removed: {}\n\n",
            self.summary.functions_removed.to_string().red()
        ));

        // High-risk changes
        if !self.high_risk_changes.is_empty() {
            output.push_str(&format!("{}\n", "High-Risk Changes".red().bold()));

            for change in &self.high_risk_changes {
                output.push_str(&format!(
                    "   {}\n",
                    "┌─────────────────────────────────────────────────────────┐".dimmed()
                ));
                output.push_str(&format!(
                    "   │ {}  {}\n",
                    format!("[{}]", change.entity_type).yellow(),
                    change.name.bold()
                ));

                let risk_color = match change.risk_level {
                    RiskLevel::Critical => change.risk_level.as_str().red().bold(),
                    RiskLevel::High => change.risk_level.as_str().red(),
                    RiskLevel::Medium => change.risk_level.as_str().yellow(),
                    RiskLevel::Low => change.risk_level.as_str().green(),
                };

                output.push_str(&format!(
                    "   │ Risk: {} — Called by {} functions\n",
                    risk_color, change.caller_count
                ));
                output.push_str(&format!(
                    "   │ Impact radius: {} transitive dependents\n",
                    change.transitive_dependents
                ));

                if let (Some(date), Some(author)) = (&change.last_modified, &change.last_author) {
                    output.push_str(&format!(
                        "   │ Last modified: {} by {}\n",
                        date.dimmed(),
                        format!("@{}", author).cyan()
                    ));
                }

                if let Some(complexity) = change.complexity {
                    if let Some(delta) = change.complexity_delta {
                        if delta != 0 {
                            let delta_str = if delta > 0 {
                                format!("+{}", delta).red()
                            } else {
                                format!("{}", delta).green()
                            };
                            output.push_str(&format!(
                                "   │ Complexity: {} ({})\n",
                                complexity, delta_str
                            ));
                        }
                    }
                }

                output.push_str(&format!(
                    "   {}\n",
                    "└─────────────────────────────────────────────────────────┘".dimmed()
                ));
                output.push('\n');
            }
        }

        // All changes
        output.push_str(&format!("{}\n", "All Changes".bold()));

        let added: Vec<_> = self
            .all_changes
            .iter()
            .filter(|c| c.change_type == "added")
            .collect();
        let modified: Vec<_> = self
            .all_changes
            .iter()
            .filter(|c| c.change_type == "modified")
            .collect();
        let removed: Vec<_> = self
            .all_changes
            .iter()
            .filter(|c| c.change_type == "removed")
            .collect();

        if !added.is_empty() {
            output.push_str(&format!("   {}:\n", "Added".green()));
            for change in &added {
                let complexity_str = change
                    .complexity
                    .map(|c| format!(" (complexity: {})", c))
                    .unwrap_or_default();
                output.push_str(&format!(
                    "     {} {}:{}{}\n",
                    "+".green(),
                    format!("[{}]", change.entity_type).dimmed(),
                    change.name,
                    complexity_str.dimmed()
                ));
            }
        }

        if !modified.is_empty() {
            output.push_str(&format!("   {}:\n", "Modified".yellow()));
            for change in &modified {
                let complexity_str =
                    if let (Some(c), Some(delta)) = (change.complexity, change.complexity_delta) {
                        if delta != 0 {
                            format!(" (complexity: {} → {})", c - delta as u32, c)
                        } else {
                            String::new()
                        }
                    } else {
                        String::new()
                    };
                output.push_str(&format!(
                    "     {} {}:{}{}\n",
                    "~".yellow(),
                    format!("[{}]", change.entity_type).dimmed(),
                    change.name,
                    complexity_str.dimmed()
                ));
            }
        }

        if !removed.is_empty() {
            output.push_str(&format!("   {}:\n", "Removed".red()));
            for change in &removed {
                output.push_str(&format!(
                    "     {} {}:{}\n",
                    "-".red(),
                    format!("[{}]", change.entity_type).dimmed(),
                    change.name
                ));
            }
        }

        output.push('\n');

        // Suggested reviewers
        if !self.suggested_reviewers.is_empty() {
            output.push_str(&format!(
                "{}\n",
                "Suggested Reviewers (by code ownership)".bold()
            ));
            for reviewer in &self.suggested_reviewers {
                output.push_str(&format!(
                    "   {} — {}% ownership\n",
                    format!("@{}", reviewer.name).cyan(),
                    reviewer.ownership_percent
                ));
            }
            output.push('\n');
        }

        // Test coverage gaps
        if !self.test_gaps.is_empty() {
            output.push_str(&format!("{}\n", "Test Coverage Gaps".yellow().bold()));
            for gap in &self.test_gaps {
                output.push_str(&format!(
                    "   {} {} — {}\n",
                    "⚠".yellow(),
                    gap.function_name,
                    gap.reason.dimmed()
                ));
            }
            output.push('\n');
        }

        // Recommendations
        if !self.recommendations.is_empty() {
            output.push_str(&format!("{}\n", "Recommendations".bold()));
            for (i, rec) in self.recommendations.iter().enumerate() {
                output.push_str(&format!("   {}. {}\n", i + 1, rec));
            }
        }

        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!(":: review {}\n", self.title));
        output.push_str(&format!(
            "# files_changed: {}\n",
            self.summary.files_changed
        ));
        output.push_str(&format!(
            "# functions_modified: {}\n",
            self.summary.functions_modified
        ));
        output.push_str(&format!(
            "# functions_added: {}\n",
            self.summary.functions_added
        ));
        output.push_str(&format!(
            "# functions_removed: {}\n",
            self.summary.functions_removed
        ));
        output.push_str(&format!(
            "# total_risk: {:.1}\n\n",
            self.summary.total_risk_score
        ));

        output.push_str("## HIGH_RISK\n");
        for change in &self.high_risk_changes {
            output.push_str(&format!(
                "! {} [{}] risk={:.1} callers={} dependents={}\n",
                change.name,
                change.risk_level.as_str(),
                change.risk_score,
                change.caller_count,
                change.transitive_dependents
            ));
        }

        output.push_str("\n## CHANGES\n");
        for change in &self.all_changes {
            let sigil = match change.change_type.as_str() {
                "added" => "+",
                "removed" => "-",
                _ => "~",
            };
            output.push_str(&format!(
                "{} {} [{}]\n",
                sigil, change.name, change.entity_type
            ));
        }

        output
    }
}

/// Run the review command
pub async fn run(range: Option<&str>, format: OutputFormat) -> Result<()> {
    let db_path = find_mubase(".")?;
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    // Load graph for impact analysis
    let graph = GraphData::from_db(&conn)?;

    // Parse the git range
    let (base_ref, head_ref, title) = parse_git_range(range)?;

    // Get changed files
    let changed_files = get_changed_files(&base_ref, &head_ref)?;

    if changed_files.is_empty() {
        let result = ReviewResult {
            title,
            summary: ReviewSummary {
                files_changed: 0,
                functions_modified: 0,
                functions_added: 0,
                functions_removed: 0,
                total_risk_score: 0.0,
            },
            high_risk_changes: vec![],
            all_changes: vec![],
            suggested_reviewers: vec![],
            test_gaps: vec![],
            recommendations: vec!["No changes detected.".to_string()],
        };
        return Output::new(result, format).render();
    }

    // Detect test file changes
    let test_files_changed: HashSet<String> = changed_files
        .iter()
        .filter(|f| is_test_file(f))
        .cloned()
        .collect();

    // Get semantic changes
    let semantic_changes = get_semantic_changes(&base_ref, &head_ref, &changed_files)?;

    // Analyze each change for risk
    let mut analyzed_changes: Vec<AnalyzedChange> = Vec::new();

    for change in semantic_changes {
        let analyzed = analyze_change(&conn, &graph, &change, &base_ref)?;
        analyzed_changes.push(analyzed);
    }

    // Sort by risk score descending
    analyzed_changes.sort_by(|a, b| {
        b.risk_score
            .partial_cmp(&a.risk_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    // Separate high-risk changes
    let high_risk_changes: Vec<AnalyzedChange> = analyzed_changes
        .iter()
        .filter(|c| matches!(c.risk_level, RiskLevel::High | RiskLevel::Critical))
        .cloned()
        .collect();

    // Detect test coverage gaps
    let test_gaps = detect_test_gaps(&analyzed_changes, &test_files_changed);

    // Get suggested reviewers
    let suggested_reviewers = get_suggested_reviewers(&changed_files)?;

    // Generate recommendations
    let recommendations =
        generate_recommendations(&analyzed_changes, &test_gaps, &suggested_reviewers);

    // Build summary
    let summary = ReviewSummary {
        files_changed: changed_files.len(),
        functions_modified: analyzed_changes
            .iter()
            .filter(|c| c.change_type == "modified")
            .count(),
        functions_added: analyzed_changes
            .iter()
            .filter(|c| c.change_type == "added")
            .count(),
        functions_removed: analyzed_changes
            .iter()
            .filter(|c| c.change_type == "removed")
            .count(),
        total_risk_score: analyzed_changes.iter().map(|c| c.risk_score).sum(),
    };

    let result = ReviewResult {
        title,
        summary,
        high_risk_changes,
        all_changes: analyzed_changes,
        suggested_reviewers,
        test_gaps,
        recommendations,
    };

    Output::new(result, format).render()
}

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

/// Parse git range into base_ref, head_ref, and title
fn parse_git_range(range: Option<&str>) -> Result<(String, String, String)> {
    match range {
        None => {
            // No range = uncommitted changes
            Ok((
                "HEAD".to_string(),
                "".to_string(),
                "uncommitted changes".to_string(),
            ))
        }
        Some(r) if r.contains("..") => {
            // Range like "main..feature" or "HEAD~3..HEAD"
            let parts: Vec<&str> = r.split("..").collect();
            if parts.len() == 2 {
                let base = parts[0].to_string();
                let head = parts[1].to_string();
                let title = format!("{}..{}", base, head);
                Ok((base, head, title))
            } else {
                Err(anyhow::anyhow!("Invalid range format: {}", r))
            }
        }
        Some(r) => {
            // Single ref - compare to HEAD
            Ok((r.to_string(), "HEAD".to_string(), format!("{}..HEAD", r)))
        }
    }
}

/// Get list of changed files
fn get_changed_files(base_ref: &str, head_ref: &str) -> Result<Vec<String>> {
    let output = if head_ref.is_empty() {
        // Uncommitted changes
        Command::new("git")
            .args(["diff", "--name-only", "HEAD"])
            .output()?
    } else {
        Command::new("git")
            .args([
                "diff",
                "--name-only",
                &format!("{}...{}", base_ref, head_ref),
            ])
            .output()?
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("git diff failed: {}", stderr);
    }

    let files: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|l| !l.is_empty())
        .map(|s| s.to_string())
        .collect();

    Ok(files)
}

/// Check if a file is a test file
fn is_test_file(path: &str) -> bool {
    let path_lower = path.to_lowercase();
    path_lower.contains("test")
        || path_lower.contains("spec")
        || path_lower.contains("_test.")
        || path_lower.contains(".test.")
}

/// A raw semantic change before analysis
#[derive(Debug)]
struct RawChange {
    name: String,
    entity_type: String,
    file_path: String,
    change_type: String,
}

/// Get semantic changes from git diff
fn get_semantic_changes(
    base_ref: &str,
    head_ref: &str,
    changed_files: &[String],
) -> Result<Vec<RawChange>> {
    let mut changes = Vec::new();

    for file_path in changed_files {
        // Skip test files for analysis (but track them for coverage detection)
        if is_test_file(file_path) {
            continue;
        }

        // Skip non-code files
        let Some(language) = detect_language(file_path) else {
            continue;
        };

        // Get file content at base and head
        let base_content = get_file_at_ref(file_path, base_ref)?;
        let head_content = if head_ref.is_empty() {
            // Read current file for uncommitted changes
            std::fs::read_to_string(file_path).ok()
        } else {
            get_file_at_ref(file_path, head_ref)?
        };

        match (&base_content, &head_content) {
            (None, Some(head)) => {
                // New file
                let entities = extract_entities(head, file_path, language);
                for (name, entity_type) in entities {
                    if entity_type == "function" || entity_type == "method" {
                        changes.push(RawChange {
                            name,
                            entity_type,
                            file_path: file_path.clone(),
                            change_type: "added".to_string(),
                        });
                    }
                }
            }
            (Some(base), None) => {
                // Deleted file
                let entities = extract_entities(base, file_path, language);
                for (name, entity_type) in entities {
                    if entity_type == "function" || entity_type == "method" {
                        changes.push(RawChange {
                            name,
                            entity_type,
                            file_path: file_path.clone(),
                            change_type: "removed".to_string(),
                        });
                    }
                }
            }
            (Some(base), Some(head)) => {
                // Modified file - compare entities
                let base_entities = extract_entities(base, file_path, language);
                let head_entities = extract_entities(head, file_path, language);

                let base_set: HashSet<_> = base_entities.iter().map(|(n, _)| n).collect();
                let head_set: HashSet<_> = head_entities.iter().map(|(n, _)| n).collect();

                // Added
                for (name, entity_type) in &head_entities {
                    if !base_set.contains(name)
                        && (entity_type == "function" || entity_type == "method")
                    {
                        changes.push(RawChange {
                            name: name.clone(),
                            entity_type: entity_type.clone(),
                            file_path: file_path.clone(),
                            change_type: "added".to_string(),
                        });
                    }
                }

                // Removed
                for (name, entity_type) in &base_entities {
                    if !head_set.contains(name)
                        && (entity_type == "function" || entity_type == "method")
                    {
                        changes.push(RawChange {
                            name: name.clone(),
                            entity_type: entity_type.clone(),
                            file_path: file_path.clone(),
                            change_type: "removed".to_string(),
                        });
                    }
                }

                // Modified (entities that exist in both but file changed)
                // For simplicity, mark all existing functions as modified if file changed
                for (name, entity_type) in &head_entities {
                    if base_set.contains(name)
                        && (entity_type == "function" || entity_type == "method")
                    {
                        changes.push(RawChange {
                            name: name.clone(),
                            entity_type: entity_type.clone(),
                            file_path: file_path.clone(),
                            change_type: "modified".to_string(),
                        });
                    }
                }
            }
            (None, None) => {}
        }
    }

    Ok(changes)
}

/// Analyze a change and calculate risk score
fn analyze_change(
    conn: &Connection,
    graph: &GraphData,
    change: &RawChange,
    _base_ref: &str,
) -> Result<AnalyzedChange> {
    // Try to find the node in the graph
    let node_id = find_node_id(conn, &change.name, &change.file_path)?;

    // Calculate caller count (direct callers)
    let caller_count = if let Some(ref id) = node_id {
        count_callers(conn, id)?
    } else {
        0
    };

    // Calculate transitive dependents (impact)
    let transitive_dependents = if let Some(ref id) = node_id {
        if graph.has_node(id) {
            graph.ancestors(id, None, None).len()
        } else {
            0
        }
    } else {
        0
    };

    // Get complexity
    let complexity = if let Some(ref id) = node_id {
        get_complexity(conn, id)?
    } else {
        None
    };

    // Calculate complexity delta (compare to base)
    let complexity_delta = if change.change_type == "modified" {
        // For now, assume small delta if we can't calculate it
        complexity.map(|_| 0)
    } else {
        None
    };

    // Get last modified info
    let (last_modified, last_author) = get_last_modified(&change.file_path)?;

    // Calculate risk score using the formula:
    // risk = (caller_count * 2) + (transitive_dependents * 0.5) + (complexity_delta * 3)
    let complexity_penalty = complexity_delta.unwrap_or(0i32).abs() as f64 * 3.0;
    let risk_score =
        (caller_count as f64 * 2.0) + (transitive_dependents as f64 * 0.5) + complexity_penalty;

    let risk_level = RiskLevel::from_score(risk_score);

    Ok(AnalyzedChange {
        name: change.name.clone(),
        entity_type: change.entity_type.clone(),
        file_path: change.file_path.clone(),
        change_type: change.change_type.clone(),
        risk_level,
        risk_score,
        caller_count,
        transitive_dependents,
        complexity,
        complexity_delta,
        last_modified,
        last_author,
    })
}

/// Find a node ID in the graph by name and file path
fn find_node_id(conn: &Connection, name: &str, file_path: &str) -> Result<Option<String>> {
    let mut stmt = conn.prepare(
        "SELECT id FROM nodes
         WHERE name = ?1
         AND (file_path = ?2 OR file_path LIKE '%' || ?2)
         LIMIT 1",
    )?;

    let mut rows = stmt.query([name, file_path])?;
    if let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        return Ok(Some(id));
    }

    // Try fuzzy match on name only
    let mut stmt = conn.prepare("SELECT id FROM nodes WHERE name = ?1 LIMIT 1")?;
    let mut rows = stmt.query([name])?;
    if let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        return Ok(Some(id));
    }

    Ok(None)
}

/// Count direct callers of a node
fn count_callers(conn: &Connection, node_id: &str) -> Result<usize> {
    let mut stmt = conn.prepare(
        "SELECT COUNT(DISTINCT source_id) FROM edges WHERE target_id = ?1 AND type = 'calls'",
    )?;
    let mut rows = stmt.query([node_id])?;

    if let Some(row) = rows.next()? {
        let count: i64 = row.get(0)?;
        return Ok(count as usize);
    }

    Ok(0)
}

/// Get complexity of a node
fn get_complexity(conn: &Connection, node_id: &str) -> Result<Option<u32>> {
    let mut stmt = conn.prepare("SELECT complexity FROM nodes WHERE id = ?1")?;
    let mut rows = stmt.query([node_id])?;

    if let Some(row) = rows.next()? {
        let complexity: Option<i64> = row.get(0)?;
        return Ok(complexity.map(|c| c as u32));
    }

    Ok(None)
}

/// Get last modified date and author for a file
fn get_last_modified(file_path: &str) -> Result<(Option<String>, Option<String>)> {
    let output = Command::new("git")
        .args([
            "log",
            "-1",
            "--format=%ad|%an",
            "--date=short",
            "--",
            file_path,
        ])
        .output()?;

    if !output.status.success() {
        return Ok((None, None));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let line = stdout.trim();

    if line.is_empty() {
        return Ok((None, None));
    }

    let parts: Vec<&str> = line.splitn(2, '|').collect();
    if parts.len() == 2 {
        Ok((Some(parts[0].to_string()), Some(parts[1].to_string())))
    } else {
        Ok((None, None))
    }
}

/// Detect test coverage gaps
fn detect_test_gaps(
    changes: &[AnalyzedChange],
    test_files_changed: &HashSet<String>,
) -> Vec<TestGap> {
    let mut gaps = Vec::new();

    for change in changes {
        // Skip if it's a removal
        if change.change_type == "removed" {
            continue;
        }

        // Check if there's a corresponding test file change
        let has_test_change = test_files_changed.iter().any(|tf| {
            // Simple heuristic: test file should contain the source file name
            let source_stem = std::path::Path::new(&change.file_path)
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("");
            tf.contains(source_stem) || tf.contains(&change.name)
        });

        if !has_test_change {
            let reason = if change.change_type == "added" {
                "New function has no test coverage"
            } else {
                "Modified but no test file changes detected"
            };

            gaps.push(TestGap {
                function_name: change.name.clone(),
                file_path: change.file_path.clone(),
                reason: reason.to_string(),
            });
        }
    }

    gaps
}

/// Get suggested reviewers based on code ownership
fn get_suggested_reviewers(changed_files: &[String]) -> Result<Vec<SuggestedReviewer>> {
    let mut author_files: HashMap<String, Vec<String>> = HashMap::new();
    let mut total_files = 0;

    for file_path in changed_files {
        // Get primary author for this file
        let output = Command::new("git")
            .args(["shortlog", "-sn", "--", file_path])
            .output()?;

        if output.status.success() {
            let stdout = String::from_utf8_lossy(&output.stdout);
            // Parse "  42  Author Name" format
            if let Some(line) = stdout.lines().next() {
                let parts: Vec<&str> = line.trim().splitn(2, '\t').collect();
                if parts.len() == 2 {
                    let author = parts[1].trim().to_string();
                    author_files
                        .entry(author)
                        .or_default()
                        .push(file_path.clone());
                    total_files += 1;
                }
            }
        }
    }

    let mut reviewers: Vec<SuggestedReviewer> = author_files
        .into_iter()
        .map(|(name, files)| {
            let ownership_percent = if total_files > 0 {
                ((files.len() as f64 / total_files as f64) * 100.0) as u32
            } else {
                0
            };
            SuggestedReviewer {
                name,
                ownership_percent,
                files_owned: files,
            }
        })
        .collect();

    // Sort by ownership descending
    reviewers.sort_by(|a, b| b.ownership_percent.cmp(&a.ownership_percent));

    // Take top 3
    reviewers.truncate(3);

    Ok(reviewers)
}

/// Generate recommendations based on analysis
fn generate_recommendations(
    changes: &[AnalyzedChange],
    test_gaps: &[TestGap],
    reviewers: &[SuggestedReviewer],
) -> Vec<String> {
    let mut recommendations = Vec::new();

    // Test coverage recommendations
    let new_without_tests: Vec<_> = test_gaps
        .iter()
        .filter(|g| g.reason.contains("New"))
        .collect();

    if !new_without_tests.is_empty() {
        recommendations.push(format!(
            "Add tests for {} new function{} before merging",
            new_without_tests.len(),
            if new_without_tests.len() == 1 {
                ""
            } else {
                "s"
            }
        ));
    }

    // Complexity recommendations
    let high_complexity: Vec<_> = changes
        .iter()
        .filter(|c| c.complexity.unwrap_or(0) > 15)
        .collect();

    if !high_complexity.is_empty() {
        for change in &high_complexity {
            recommendations.push(format!(
                "Consider splitting {} — complexity is {}",
                change.name,
                change.complexity.unwrap_or(0)
            ));
        }
    }

    // Reviewer recommendations
    if let Some(top_reviewer) = reviewers.first() {
        if top_reviewer.ownership_percent > 50 {
            recommendations.push(format!(
                "Get @{} to review — they own {}% of changed files",
                top_reviewer.name, top_reviewer.ownership_percent
            ));
        }
    }

    // High-risk recommendations
    let critical_changes: Vec<_> = changes
        .iter()
        .filter(|c| matches!(c.risk_level, RiskLevel::Critical))
        .collect();

    if !critical_changes.is_empty() {
        recommendations.push(format!(
            "{} critical-risk change{} detected — consider extra review",
            critical_changes.len(),
            if critical_changes.len() == 1 { "" } else { "s" }
        ));
    }

    recommendations
}

/// Detect language from file extension
fn detect_language(file_path: &str) -> Option<&'static str> {
    let ext = std::path::Path::new(file_path).extension()?.to_str()?;
    match ext {
        "py" => Some("python"),
        "ts" | "tsx" => Some("typescript"),
        "js" | "jsx" => Some("javascript"),
        "go" => Some("go"),
        "rs" => Some("rust"),
        "java" => Some("java"),
        "cs" => Some("csharp"),
        _ => None,
    }
}

/// Get file content at a specific git ref
fn get_file_at_ref(file_path: &str, git_ref: &str) -> Result<Option<String>> {
    let output = Command::new("git")
        .args(["show", &format!("{}:{}", git_ref, file_path)])
        .output()?;

    if !output.status.success() {
        return Ok(None);
    }

    Ok(Some(String::from_utf8_lossy(&output.stdout).to_string()))
}

/// Parse file and extract entity names
fn extract_entities(content: &str, file_path: &str, language: &str) -> Vec<(String, String)> {
    let result = mu_core::parser::parse_source(content, file_path, language);

    if !result.success {
        return Vec::new();
    }

    let Some(module) = result.module else {
        return Vec::new();
    };

    let mut entities = Vec::new();

    for func in &module.functions {
        entities.push((func.name.clone(), "function".to_string()));
    }

    for class in &module.classes {
        entities.push((class.name.clone(), "class".to_string()));
        for method in &class.methods {
            entities.push((
                format!("{}.{}", class.name, method.name),
                "method".to_string(),
            ));
        }
    }

    entities
}
