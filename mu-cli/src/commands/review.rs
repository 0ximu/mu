//! Review command - PR risk analysis combining semantic diff + impact + audit
//!
//! Produces a single report showing what changed, what might break,
//! code quality issues in changed code, and an overall risk score.

use std::collections::{HashMap, HashSet};
use std::time::Instant;

use colored::Colorize;
use serde::Serialize;

use crate::commands::audit::{self, Severity, Violation};
#[cfg(test)]
use crate::commands::diff::SemanticChange;
use crate::commands::diff::{self, DiffResult};
use crate::mubase;
use crate::output::{Output, OutputFormat, TableDisplay};

/// Impact info for a single changed symbol.
#[derive(Debug, Clone, Serialize)]
pub struct SymbolImpact {
    pub name: String,
    pub entity_type: String,
    pub change_type: String,
    pub is_breaking: bool,
    pub dependents: usize,
    pub file_path: Option<String>,
    /// Names of files containing dependents
    pub affected_files: Vec<String>,
}

/// Risk level for the review.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum RiskLevel {
    Low,
    Medium,
    High,
    Critical,
}

impl RiskLevel {
    fn label(&self) -> &'static str {
        match self {
            RiskLevel::Low => "LOW",
            RiskLevel::Medium => "MEDIUM",
            RiskLevel::High => "HIGH",
            RiskLevel::Critical => "CRITICAL",
        }
    }
}

impl std::fmt::Display for RiskLevel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.label())
    }
}

/// Full review result.
#[derive(Debug, Serialize)]
pub struct ReviewResult {
    pub base_ref: String,
    pub head_ref: String,
    pub risk_level: RiskLevel,
    pub risk_score: u32,
    pub diff: DiffResult,
    pub symbol_impacts: Vec<SymbolImpact>,
    pub audit_violations: Vec<Violation>,
    pub total_dependents: usize,
    pub affected_files: Vec<String>,
    pub duration_ms: u64,
}

impl TableDisplay for ReviewResult {
    fn to_table(&self) -> String {
        let mut out = String::new();

        // Header
        let risk_colored = match self.risk_level {
            RiskLevel::Low => self.risk_level.label().green().bold(),
            RiskLevel::Medium => self.risk_level.label().yellow().bold(),
            RiskLevel::High => self.risk_level.label().red().bold(),
            RiskLevel::Critical => self.risk_level.label().on_red().white().bold(),
        };
        out.push_str(&format!(
            "{} {} -> HEAD\n",
            "REVIEW:".cyan().bold(),
            self.base_ref.yellow()
        ));
        out.push_str(&format!(
            "Risk: {} | {} symbols changed | {} breaking | {} downstream impact ({}ms)\n\n",
            risk_colored,
            self.diff.changes.len(),
            self.diff.breaking_changes.len(),
            self.total_dependents,
            self.duration_ms
        ));

        // Breaking changes
        if !self.diff.breaking_changes.is_empty() {
            out.push_str(&format!("{}\n", "BREAKING CHANGES:".red().bold()));
            out.push_str(&format!("{}\n", "-".repeat(60)));
            for change in &self.diff.breaking_changes {
                // Find impact for this symbol
                let impact = self
                    .symbol_impacts
                    .iter()
                    .find(|i| i.name == change.entity_name);
                let dep_count = impact.map(|i| i.dependents).unwrap_or(0);

                out.push_str(&format!(
                    "  {} {} [{}] -- {} ({} dependents)\n",
                    "X".red().bold(),
                    change.entity_name.red().bold(),
                    change.entity_type,
                    change.change_type,
                    dep_count,
                ));
                if let Some(ref path) = change.file_path {
                    out.push_str(&format!("    {}\n", path.dimmed()));
                }
                if let Some(ref desc) = change.description {
                    out.push_str(&format!("    {}\n", desc.dimmed()));
                }
                if let Some(impact) = impact {
                    if !impact.affected_files.is_empty() {
                        let files: Vec<&str> = impact
                            .affected_files
                            .iter()
                            .take(5)
                            .map(|s| s.as_str())
                            .collect();
                        out.push_str(&format!("    affects: {}\n", files.join(", ").dimmed()));
                    }
                }
            }
            out.push('\n');
        }

        // Changed symbols table
        if !self.symbol_impacts.is_empty() {
            out.push_str(&format!(
                "{} ({})\n",
                "CHANGED SYMBOLS".cyan().bold(),
                self.symbol_impacts.len()
            ));
            out.push_str(&format!(
                "  {:<30} {:<12} {:<18} {}\n",
                "Symbol".bold(),
                "Type".bold(),
                "Change".bold(),
                "Impact".bold()
            ));
            out.push_str(&format!("  {}\n", "-".repeat(76)));
            for si in &self.symbol_impacts {
                let change_colored = match si.change_type.as_str() {
                    "added" => si.change_type.green(),
                    "removed" => si.change_type.red(),
                    _ => si.change_type.yellow(),
                };
                let name_display = if si.name.len() > 28 {
                    crate::output::truncate_str(&si.name, 25)
                } else {
                    si.name.clone()
                };
                out.push_str(&format!(
                    "  {:<30} {:<12} {:<18} {} dependents\n",
                    name_display, si.entity_type, change_colored, si.dependents
                ));
            }
            out.push('\n');
        }

        // Audit findings
        if !self.audit_violations.is_empty() {
            out.push_str(&format!(
                "{} (changed code only)\n",
                "AUDIT FINDINGS".yellow().bold()
            ));
            out.push_str(&format!("{}\n", "-".repeat(60)));
            for v in &self.audit_violations {
                let tag = match v.severity {
                    Severity::Error => format!("[{}]", v.rule_id).red(),
                    Severity::Warning => format!("[{}]", v.rule_id).yellow(),
                    Severity::Info => format!("[{}]", v.rule_id).dimmed(),
                };
                out.push_str(&format!(
                    "  {} {}: {}\n",
                    tag,
                    v.node_name.bright_white(),
                    v.message.dimmed()
                ));
            }
            out.push('\n');
        }

        // Blast radius
        out.push_str(&format!("{}\n", "BLAST RADIUS".cyan().bold()));
        out.push_str(&format!(
            "{} nodes affected across {} files\n",
            self.total_dependents,
            self.affected_files.len()
        ));
        if !self.affected_files.is_empty() {
            out.push_str("Top affected files:\n");
            for file in self.affected_files.iter().take(8) {
                out.push_str(&format!("  {}\n", file));
            }
        }

        out
    }
}

/// Format review result as markdown (for MCP output).
pub fn format_as_markdown(result: &ReviewResult) -> String {
    let mut md = String::new();

    // Header
    let risk_emoji = match result.risk_level {
        RiskLevel::Low => "",
        RiskLevel::Medium => "",
        RiskLevel::High => "",
        RiskLevel::Critical => "",
    };
    md.push_str(&format!("# Review: {} -> HEAD\n", result.base_ref));
    md.push_str(&format!(
        "**Risk: {}** {} | {} symbols changed | {} breaking | {} downstream impact\n\n",
        result.risk_level,
        risk_emoji,
        result.diff.changes.len(),
        result.diff.breaking_changes.len(),
        result.total_dependents
    ));

    // Breaking changes
    if !result.diff.breaking_changes.is_empty() {
        md.push_str("## Breaking Changes\n\n");
        for change in &result.diff.breaking_changes {
            let impact = result
                .symbol_impacts
                .iter()
                .find(|i| i.name == change.entity_name);
            let dep_count = impact.map(|i| i.dependents).unwrap_or(0);

            md.push_str(&format!(
                "- `{}` {} -- affects {} callers\n",
                change.entity_name, change.change_type, dep_count
            ));
            if let Some(impact) = impact {
                if !impact.affected_files.is_empty() {
                    let files: Vec<&str> = impact
                        .affected_files
                        .iter()
                        .take(5)
                        .map(|s| s.as_str())
                        .collect();
                    md.push_str(&format!("  - {}\n", files.join(", ")));
                }
            }
        }
        md.push('\n');
    }

    // Changed symbols table
    if !result.symbol_impacts.is_empty() {
        md.push_str("## Changed Symbols\n\n");
        md.push_str("| Symbol | Type | Change | Impact |\n");
        md.push_str("|--------|------|--------|--------|\n");
        for si in &result.symbol_impacts {
            md.push_str(&format!(
                "| `{}` | {} | {} | {} dependents |\n",
                si.name, si.entity_type, si.change_type, si.dependents
            ));
        }
        md.push('\n');
    }

    // Audit findings
    if !result.audit_violations.is_empty() {
        md.push_str("## Audit Findings (changed code only)\n\n");
        for v in &result.audit_violations {
            let location = match (&v.file_path, v.line) {
                (Some(fp), Some(line)) => format!(" -- {}:{}", fp, line),
                (Some(fp), None) => format!(" -- {}", fp),
                _ => String::new(),
            };
            md.push_str(&format!(
                "- **[{}]** `{}`: {}{}\n",
                v.rule_id, v.node_name, v.message, location
            ));
        }
        md.push('\n');
    }

    // Blast radius
    md.push_str("## Blast Radius\n\n");
    md.push_str(&format!(
        "{} nodes affected across {} files\n",
        result.total_dependents,
        result.affected_files.len()
    ));
    if !result.affected_files.is_empty() {
        md.push_str("\nTop affected files:\n");
        for file in result.affected_files.iter().take(8) {
            md.push_str(&format!("- {}\n", file));
        }
    }

    md
}

/// Run the review: diff + impact + audit + risk scoring.
///
/// Shared between CLI and MCP.
pub fn run_review(
    mubase: &crate::engine::storage::MUbase,
    project_root: &std::path::Path,
    base_ref: &str,
    include_impact: bool,
    min_complexity: Option<u32>,
) -> Result<ReviewResult, String> {
    let start = Instant::now();

    // Stage 1: Semantic diff
    let diff_result = diff::semantic_diff(project_root, base_ref, "HEAD")
        .map_err(|e| format!("diff failed: {}", e))?;

    // Stage 2: Impact analysis
    let mut symbol_impacts = Vec::new();
    let mut total_dependents_set: HashSet<String> = HashSet::new();
    let mut affected_file_counts: HashMap<String, usize> = HashMap::new();

    if include_impact && !diff_result.changes.is_empty() {
        for change in &diff_result.changes {
            let (dep_count, affected_files) =
                lookup_impact(mubase, &change.entity_name, change.file_path.as_deref());

            for f in &affected_files {
                *affected_file_counts.entry(f.clone()).or_default() += 1;
            }

            // Track unique dependents across all changes
            let dep_names = lookup_dependent_names(mubase, &change.entity_name);
            total_dependents_set.extend(dep_names);

            symbol_impacts.push(SymbolImpact {
                name: change.entity_name.clone(),
                entity_type: change.entity_type.clone(),
                change_type: change.change_type.clone(),
                is_breaking: change.is_breaking,
                dependents: dep_count,
                file_path: change.file_path.clone(),
                affected_files,
            });
        }
    }

    let total_dependents = total_dependents_set.len();

    let affected_files = sort_files_by_impact(affected_file_counts);

    // Stage 3: Audit on changed code
    let complexity_threshold = min_complexity.unwrap_or(15);
    let audit_result = audit::run_audit_for_mcp(
        mubase,
        project_root,
        Some(complexity_threshold),
        Some(base_ref),
    )
    .unwrap_or_else(|_| audit::AuditResult {
        violations: Vec::new(),
        total_violations: 0,
        rules_run: 0,
        nodes_checked: 0,
        error_count: 0,
        warning_count: 0,
        info_count: 0,
        duration_ms: 0,
        diff_scope: Some(base_ref.to_string()),
    });

    // Stage 4: Risk scoring
    let risk_score = compute_risk_score(
        &diff_result,
        &symbol_impacts,
        &audit_result,
        total_dependents,
    );
    let risk_level = score_to_level(risk_score);

    Ok(ReviewResult {
        base_ref: base_ref.to_string(),
        head_ref: "HEAD".to_string(),
        risk_level,
        risk_score,
        diff: diff_result,
        symbol_impacts,
        audit_violations: audit_result.violations,
        total_dependents,
        affected_files,
        duration_ms: start.elapsed().as_millis() as u64,
    })
}

/// Sort files by impact count descending, ties broken alphabetically.
/// The "Top affected files" list claims impact order — this is that order.
fn sort_files_by_impact(counts: HashMap<String, usize>) -> Vec<String> {
    let mut entries: Vec<(String, usize)> = counts.into_iter().collect();
    entries.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    entries.into_iter().map(|(f, _)| f).collect()
}

/// Look up how many dependents a symbol has and which files they're in.
fn lookup_impact(
    mubase: &crate::engine::storage::MUbase,
    symbol_name: &str,
    _file_path: Option<&str>,
) -> (usize, Vec<String>) {
    let result = match mubase.query_params(
        "SELECT DISTINCT n.name, n.file_path FROM edges e
         JOIN nodes n ON n.id = e.source_id
         WHERE e.target_id IN (SELECT id FROM nodes WHERE name = ?1)
         LIMIT 50",
        &[&symbol_name as &dyn duckdb::ToSql],
    ) {
        Ok(r) => r,
        Err(_) => return (0, Vec::new()),
    };

    let mut files = HashSet::new();
    for row in &result.rows {
        if let Some(fp) = row.get(1).and_then(|v| v.as_str()) {
            files.insert(fp.to_string());
        }
    }

    (result.rows.len(), files.into_iter().collect())
}

/// Get names of dependent nodes.
fn lookup_dependent_names(
    mubase: &crate::engine::storage::MUbase,
    symbol_name: &str,
) -> Vec<String> {
    match mubase.query_params(
        "SELECT DISTINCT n.name FROM edges e
         JOIN nodes n ON n.id = e.source_id
         WHERE e.target_id IN (SELECT id FROM nodes WHERE name = ?1)
         LIMIT 100",
        &[&symbol_name as &dyn duckdb::ToSql],
    ) {
        Ok(r) => r
            .rows
            .iter()
            .filter_map(|row| row.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
            .collect(),
        Err(_) => Vec::new(),
    }
}

/// Compute risk score from diff, impact, and audit data.
fn compute_risk_score(
    diff: &DiffResult,
    impacts: &[SymbolImpact],
    audit: &audit::AuditResult,
    total_dependents: usize,
) -> u32 {
    let mut score: u32 = 0;

    // Breaking changes are heavily weighted
    score += diff.breaking_changes.len() as u32 * 5;

    // Total blast radius
    score += match total_dependents {
        0..=5 => 0,
        6..=20 => 3,
        21..=50 => 6,
        _ => 10,
    };

    // High-impact breaking changes (breaking + many dependents)
    for impact in impacts {
        if impact.is_breaking && impact.dependents > 5 {
            score += 3;
        }
    }

    // Audit errors (especially security)
    let security_violations = audit
        .violations
        .iter()
        .filter(|v| v.rule_id == "R9-secrets")
        .count();
    score += security_violations as u32 * 8;
    score += audit.error_count as u32 * 2;
    score += audit.warning_count as u32;

    score
}

/// Map a numeric score to a risk level.
fn score_to_level(score: u32) -> RiskLevel {
    match score {
        0..=5 => RiskLevel::Low,
        6..=15 => RiskLevel::Medium,
        16..=30 => RiskLevel::High,
        _ => RiskLevel::Critical,
    }
}

/// CLI entry point.
pub async fn run(base_ref: Option<&str>, format: OutputFormat) -> anyhow::Result<()> {
    let mubase_path = mubase::find_mubase_optional(".")
        .ok_or_else(|| anyhow::anyhow!("No .mu/mubase found. Run 'mu bootstrap' first."))?;

    let cwd = std::env::current_dir()?;
    let project_root = mubase::find_project_root(&cwd)
        .ok_or_else(|| anyhow::anyhow!("Could not determine project root."))?;

    let base = base_ref
        .map(|s| s.to_string())
        .unwrap_or_else(|| diff::detect_default_branch(&project_root));

    let db = crate::engine::storage::MUbase::open_read_only(&mubase_path)?;

    let result =
        run_review(&db, &project_root, &base, true, None).map_err(|e| anyhow::anyhow!(e))?;

    Output::new(result, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_risk_score_low() {
        let diff = DiffResult {
            base_ref: "main".into(),
            head_ref: "HEAD".into(),
            changes: vec![SemanticChange {
                change_type: "added".into(),
                entity_type: "function".into(),
                entity_name: "new_fn".into(),
                file_path: Some("src/lib.rs".into()),
                is_breaking: false,
                description: None,
            }],
            breaking_changes: vec![],
            files_changed: 1,
            duration_ms: 10,
        };
        let impacts = vec![SymbolImpact {
            name: "new_fn".into(),
            entity_type: "function".into(),
            change_type: "added".into(),
            is_breaking: false,
            dependents: 0,
            file_path: Some("src/lib.rs".into()),
            affected_files: vec![],
        }];
        let audit = audit::AuditResult {
            violations: vec![],
            total_violations: 0,
            rules_run: 7,
            nodes_checked: 100,
            error_count: 0,
            warning_count: 0,
            info_count: 0,
            duration_ms: 10,
            diff_scope: None,
        };

        let score = compute_risk_score(&diff, &impacts, &audit, 0);
        assert!(score <= 5, "expected LOW, got score {}", score);
        assert_eq!(score_to_level(score), RiskLevel::Low);
    }

    #[test]
    fn test_risk_score_high_breaking() {
        let breaking = SemanticChange {
            change_type: "removed".into(),
            entity_type: "function".into(),
            entity_name: "important_fn".into(),
            file_path: Some("src/core.rs".into()),
            is_breaking: true,
            description: None,
        };
        let diff = DiffResult {
            base_ref: "main".into(),
            head_ref: "HEAD".into(),
            changes: vec![breaking.clone()],
            breaking_changes: vec![breaking],
            files_changed: 1,
            duration_ms: 10,
        };
        let impacts = vec![SymbolImpact {
            name: "important_fn".into(),
            entity_type: "function".into(),
            change_type: "removed".into(),
            is_breaking: true,
            dependents: 15,
            file_path: Some("src/core.rs".into()),
            affected_files: vec!["a.rs".into(), "b.rs".into()],
        }];
        let audit = audit::AuditResult {
            violations: vec![],
            total_violations: 0,
            rules_run: 7,
            nodes_checked: 100,
            error_count: 0,
            warning_count: 0,
            info_count: 0,
            duration_ms: 10,
            diff_scope: None,
        };

        let score = compute_risk_score(&diff, &impacts, &audit, 15);
        // 5 (breaking) + 3 (blast 6-20) + 3 (breaking with >5 deps) = 11
        assert!(score >= 6, "expected at least MEDIUM, got score {}", score);
    }

    #[test]
    fn test_risk_score_critical_secrets() {
        let diff = DiffResult {
            base_ref: "main".into(),
            head_ref: "HEAD".into(),
            changes: vec![],
            breaking_changes: vec![],
            files_changed: 1,
            duration_ms: 10,
        };
        let audit = audit::AuditResult {
            violations: vec![
                Violation {
                    rule_id: "R9-secrets".into(),
                    severity: Severity::Error,
                    node_name: "connect".into(),
                    file_path: Some("db.rs".into()),
                    line: Some(10),
                    message: "hardcoded password".into(),
                },
                Violation {
                    rule_id: "R9-secrets".into(),
                    severity: Severity::Error,
                    node_name: "init".into(),
                    file_path: Some("config.rs".into()),
                    line: Some(5),
                    message: "hardcoded API key".into(),
                },
            ],
            total_violations: 2,
            rules_run: 7,
            nodes_checked: 100,
            error_count: 2,
            warning_count: 0,
            info_count: 0,
            duration_ms: 10,
            diff_scope: None,
        };

        let score = compute_risk_score(&diff, &[], &audit, 0);
        // 2 * 8 (secrets) + 2 * 2 (errors) = 20
        assert!(
            score >= 16,
            "expected HIGH or CRITICAL, got score {}",
            score
        );
    }

    #[test]
    fn test_score_to_level() {
        assert_eq!(score_to_level(0), RiskLevel::Low);
        assert_eq!(score_to_level(5), RiskLevel::Low);
        assert_eq!(score_to_level(6), RiskLevel::Medium);
        assert_eq!(score_to_level(15), RiskLevel::Medium);
        assert_eq!(score_to_level(16), RiskLevel::High);
        assert_eq!(score_to_level(30), RiskLevel::High);
        assert_eq!(score_to_level(31), RiskLevel::Critical);
    }

    #[test]
    fn test_sort_files_by_impact_descending_ties_alphabetical() {
        let mut counts = HashMap::new();
        counts.insert("zeta.rs".to_string(), 3);
        counts.insert("alpha.rs".to_string(), 1);
        counts.insert("mid_a.rs".to_string(), 2);
        counts.insert("mid_b.rs".to_string(), 2);

        let sorted = sort_files_by_impact(counts);
        assert_eq!(sorted, vec!["zeta.rs", "mid_a.rs", "mid_b.rs", "alpha.rs"]);
    }

    #[test]
    fn test_sort_files_by_impact_empty() {
        assert!(sort_files_by_impact(HashMap::new()).is_empty());
    }

    #[test]
    fn test_format_markdown_empty() {
        let result = ReviewResult {
            base_ref: "main".into(),
            head_ref: "HEAD".into(),
            risk_level: RiskLevel::Low,
            risk_score: 0,
            diff: DiffResult {
                base_ref: "main".into(),
                head_ref: "HEAD".into(),
                changes: vec![],
                breaking_changes: vec![],
                files_changed: 0,
                duration_ms: 5,
            },
            symbol_impacts: vec![],
            audit_violations: vec![],
            total_dependents: 0,
            affected_files: vec![],
            duration_ms: 10,
        };

        let md = format_as_markdown(&result);
        assert!(md.contains("# Review: main -> HEAD"));
        assert!(md.contains("Risk: LOW"));
        assert!(md.contains("0 symbols changed"));
    }
}
