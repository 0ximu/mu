//! Audit command - Static analysis rules over the MU code graph
//!
//! Runs built-in and project-local rules against the MUbase to find
//! code smells, complexity hotspots, missing docs, and other issues.

use std::collections::HashSet;
use std::path::Path;
use std::process::Command;
use std::time::Instant;

use colored::Colorize;
use regex::Regex;
use serde::{Deserialize, Serialize};

use crate::mubase;
use crate::output::{Output, OutputFormat, TableDisplay};

// ============================================================================
// Types
// ============================================================================

/// Severity of an audit violation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Error,
    Warning,
    Info,
}

impl Severity {
    fn label(&self) -> &'static str {
        match self {
            Severity::Error => "error",
            Severity::Warning => "warning",
            Severity::Info => "info",
        }
    }
}

impl std::fmt::Display for Severity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.label())
    }
}

/// A single audit violation.
#[derive(Debug, Clone, Serialize)]
pub struct Violation {
    pub rule_id: String,
    pub severity: Severity,
    pub node_name: String,
    pub file_path: Option<String>,
    pub line: Option<u32>,
    pub message: String,
}

/// Project-local rule loaded from .mu/rules/*.toml
#[derive(Debug, Clone, Deserialize)]
pub struct ProjectRule {
    /// Rule identifier (e.g., "no-println")
    pub id: String,
    /// Human-readable description
    pub description: String,
    /// Regex pattern to match against source_text
    pub pattern: String,
    /// Severity level
    #[serde(default = "default_severity")]
    pub severity: Severity,
    /// Which node types to check (default: all)
    #[serde(default)]
    pub node_types: Vec<String>,
}

fn default_severity() -> Severity {
    Severity::Warning
}

/// Wrapper for TOML file containing a list of rules
#[derive(Debug, Deserialize)]
struct RulesFile {
    #[serde(default)]
    rule: Vec<ProjectRule>,
}

/// Config overrides from project-local .mu/rules/config.toml
#[derive(Debug, Clone, Deserialize, Default)]
pub struct AuditConfig {
    /// Override complexity threshold (default: 30)
    #[serde(default)]
    pub complexity_threshold: Option<u32>,
    /// Override max params (default: 6)
    #[serde(default)]
    pub max_params: Option<usize>,
    /// Rules to disable by ID
    #[serde(default)]
    pub disable: Vec<String>,
}

/// Wrapper for the config TOML
#[derive(Debug, Deserialize, Default)]
struct ConfigFile {
    #[serde(default)]
    audit: AuditConfig,
}

/// Audit results collection.
#[derive(Debug, Serialize)]
pub struct AuditResult {
    pub violations: Vec<Violation>,
    pub rules_run: usize,
    pub nodes_checked: usize,
    pub error_count: usize,
    pub warning_count: usize,
    pub info_count: usize,
    pub duration_ms: u64,
    pub diff_scope: Option<String>,
}

impl TableDisplay for AuditResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        // Header
        output.push_str(&format!(
            "{} Checked {} nodes with {} rules",
            "AUDIT:".cyan().bold(),
            self.nodes_checked.to_string().bright_white(),
            self.rules_run.to_string().bright_white(),
        ));

        if let Some(ref scope) = self.diff_scope {
            output.push_str(&format!(" (scoped to {})", scope.yellow()));
        }
        output.push('\n');

        // Summary counts
        let summary = format!(
            "{} errors, {} warnings, {} info",
            self.error_count.to_string().red().bold(),
            self.warning_count.to_string().yellow().bold(),
            self.info_count.to_string().dimmed(),
        );
        output.push_str(&format!("Found {} ({}ms)\n\n", summary, self.duration_ms));

        if self.violations.is_empty() {
            output.push_str(&format!(
                "{}\n",
                "No violations found. Code looks clean.".green()
            ));
            return output;
        }

        // Group by severity
        let errors: Vec<&Violation> = self
            .violations
            .iter()
            .filter(|v| v.severity == Severity::Error)
            .collect();
        let warnings: Vec<&Violation> = self
            .violations
            .iter()
            .filter(|v| v.severity == Severity::Warning)
            .collect();
        let infos: Vec<&Violation> = self
            .violations
            .iter()
            .filter(|v| v.severity == Severity::Info)
            .collect();

        // Errors
        if !errors.is_empty() {
            output.push_str(&format!(
                "{} ({})\n",
                "ERRORS".red().bold(),
                errors.len()
            ));
            output.push_str(&format!("{}\n", "-".repeat(60)));
            for v in &errors {
                format_violation(&mut output, v);
            }
            output.push('\n');
        }

        // Warnings
        if !warnings.is_empty() {
            output.push_str(&format!(
                "{} ({})\n",
                "WARNINGS".yellow().bold(),
                warnings.len()
            ));
            output.push_str(&format!("{}\n", "-".repeat(60)));
            for v in &warnings {
                format_violation(&mut output, v);
            }
            output.push('\n');
        }

        // Info
        if !infos.is_empty() {
            output.push_str(&format!(
                "{} ({})\n",
                "INFO".dimmed().bold(),
                infos.len()
            ));
            output.push_str(&format!("{}\n", "-".repeat(60)));
            for v in &infos {
                format_violation(&mut output, v);
            }
            output.push('\n');
        }

        output
    }
}

fn format_violation(output: &mut String, v: &Violation) {
    let location = match (&v.file_path, v.line) {
        (Some(fp), Some(line)) => format!("{}:{}", fp, line),
        (Some(fp), None) => fp.clone(),
        _ => String::new(),
    };

    let severity_tag = match v.severity {
        Severity::Error => format!("[{}]", v.rule_id).red(),
        Severity::Warning => format!("[{}]", v.rule_id).yellow(),
        Severity::Info => format!("[{}]", v.rule_id).dimmed(),
    };

    output.push_str(&format!(
        "  {} {} {}\n",
        severity_tag,
        v.node_name.bright_white(),
        v.message.dimmed()
    ));

    if !location.is_empty() {
        output.push_str(&format!("    {}\n", location.dimmed()));
    }
}

// ============================================================================
// Built-in Rules
// ============================================================================

/// R1: Orphaned functions — functions with no incoming call edges
fn rule_orphaned_fns(
    mubase: &crate::engine::storage::MUbase,
    scope_files: &Option<HashSet<String>>,
) -> Vec<Violation> {
    // Find functions that have no incoming call/dispatch edges and aren't entry points.
    // Exclude interface methods whose interface is implemented (inherits edge exists) —
    // these are invoked via DI, not direct calls.
    let sql = r#"
        SELECT n.name, n.file_path, n.line_start
        FROM nodes n
        WHERE n.type = 'function'
          AND n.id NOT IN (
            SELECT DISTINCT e.target_id FROM edges e
            WHERE e.type IN ('calls', 'macro_dispatch', 'trait_impl', 'di_registration', 'decorator_dispatch')
          )
          AND n.name NOT IN ('main', '__init__', '__new__', 'setup', 'teardown',
                             'setUp', 'tearDown', 'test', 'configure', 'run',
                             'build', 'create', 'init', 'new', 'default',
                             'to_table', 'fmt', 'from', 'from_str', 'clone', 'drop',
                             'deref', 'display', 'into', 'get_info', 'on_roots_list_changed')
          AND n.node_category = 'production'
          AND n.name NOT LIKE 'mu_%'
          AND (n.properties IS NULL OR n.properties NOT LIKE '%dispatch_type%')
        ORDER BY n.file_path, n.line_start
    "#;

    query_to_violations(mubase, sql, scope_files, "R1-orphan", Severity::Info,
        |name, _fp| format!("no incoming calls — possibly dead code ({})", name))
}

/// R3: High cyclomatic complexity
fn rule_high_complexity(
    mubase: &crate::engine::storage::MUbase,
    threshold: u32,
    scope_files: &Option<HashSet<String>>,
) -> Vec<Violation> {
    let sql = format!(
        r#"
        SELECT n.name, n.file_path, n.line_start, n.complexity
        FROM nodes n
        WHERE n.type = 'function'
          AND n.complexity > {}
        ORDER BY n.complexity DESC
        "#,
        threshold
    );

    let result = match mubase.query(&sql) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    result
        .rows
        .iter()
        .filter_map(|row| {
            let name = row.first()?.as_str()?.to_string();
            let file_path = row.get(1).and_then(|v| v.as_str()).map(|s| s.to_string());
            let line = row.get(2).and_then(|v| v.as_u64()).map(|l| l as u32);
            let complexity = row.get(3).and_then(|v| v.as_u64()).unwrap_or(0);

            if let Some(ref scope) = scope_files {
                if let Some(ref fp) = file_path {
                    if !scope.contains(fp) {
                        return None;
                    }
                }
            }

            Some(Violation {
                rule_id: "R3-complexity".to_string(),
                severity: if complexity > (threshold as u64 * 2) {
                    Severity::Error
                } else {
                    Severity::Warning
                },
                node_name: name,
                file_path,
                line,
                message: format!("complexity {} exceeds threshold {}", complexity, threshold),
            })
        })
        .collect()
}

/// R5: Missing docstrings on public classes/functions
fn rule_missing_docstrings(
    mubase: &crate::engine::storage::MUbase,
    scope_files: &Option<HashSet<String>>,
) -> Vec<Violation> {
    // Check the properties JSON for docstring field, and source_text for doc comments
    let sql = r#"
        SELECT n.name, n.type, n.file_path, n.line_start, n.properties, n.source_text
        FROM nodes n
        WHERE n.type IN ('function', 'class')
          AND n.node_category = 'production'
          AND n.name NOT LIKE '_%'
        ORDER BY n.file_path, n.line_start
    "#;

    let result = match mubase.query(sql) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    result
        .rows
        .iter()
        .filter_map(|row| {
            let name = row.first()?.as_str()?.to_string();
            let node_type = row.get(1)?.as_str()?;
            let file_path = row.get(2).and_then(|v| v.as_str()).map(|s| s.to_string());
            let line = row.get(3).and_then(|v| v.as_u64()).map(|l| l as u32);
            let properties = row.get(4).and_then(|v| v.as_str()).unwrap_or("");
            let source_text = row.get(5).and_then(|v| v.as_str()).unwrap_or("");

            if let Some(ref scope) = scope_files {
                if let Some(ref fp) = file_path {
                    if !scope.contains(fp) {
                        return None;
                    }
                }
            }

            // Check if docstring exists in properties JSON
            let has_docstring_in_props = properties.contains("\"docstring\"");

            // Check source_text for doc comment indicators
            let has_doc_comment = source_text.contains("///")
                || source_text.contains("/**")
                || source_text.contains("\"\"\"")
                || source_text.contains("'''")
                || source_text.starts_with("# ");

            if has_docstring_in_props || has_doc_comment {
                return None;
            }

            Some(Violation {
                rule_id: "R5-docs".to_string(),
                severity: if node_type == "class" {
                    Severity::Warning
                } else {
                    Severity::Info
                },
                node_name: name,
                file_path,
                line,
                message: format!("missing docstring on public {}", node_type),
            })
        })
        .collect()
}

/// R9: Hardcoded secrets — patterns that look like API keys, passwords, tokens
fn rule_secrets(
    mubase: &crate::engine::storage::MUbase,
    scope_files: &Option<HashSet<String>>,
) -> Vec<Violation> {
    let sql = r#"
        SELECT n.name, n.file_path, n.line_start, n.source_text
        FROM nodes n
        WHERE n.source_text IS NOT NULL
          AND n.type IN ('function', 'module')
        ORDER BY n.file_path, n.line_start
    "#;

    let result = match mubase.query(sql) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    let secret_patterns = [
        (r#"(?i)(api[_-]?key|apikey)\s*[=:]\s*["'][^"']{8,}"#, "API key"),
        (r#"(?i)(secret|password|passwd|pwd)\s*[=:]\s*["'][^"']{6,}"#, "password/secret"),
        (r#"(?i)(token|auth[_-]?token)\s*[=:]\s*["'][^"']{8,}"#, "auth token"),
        (r#"(?i)(aws_secret|aws_key|access_key)\s*[=:]\s*["'][A-Za-z0-9/+=]{16,}"#, "AWS credential"),
        (r#"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----"#, "private key"),
    ];

    let compiled: Vec<(Regex, &str)> = secret_patterns
        .iter()
        .filter_map(|(pat, label)| Regex::new(pat).ok().map(|r| (r, *label)))
        .collect();

    let mut violations = Vec::new();

    for row in &result.rows {
        let name = match row.first().and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let file_path = row.get(1).and_then(|v| v.as_str()).map(|s| s.to_string());
        let line = row.get(2).and_then(|v| v.as_u64()).map(|l| l as u32);
        let source_text = row.get(3).and_then(|v| v.as_str()).unwrap_or("");

        if let Some(ref scope) = scope_files {
            if let Some(ref fp) = file_path {
                if !scope.contains(fp) {
                    continue;
                }
            }
        }

        for (regex, label) in &compiled {
            if regex.is_match(source_text) {
                violations.push(Violation {
                    rule_id: "R9-secrets".to_string(),
                    severity: Severity::Error,
                    node_name: name.clone(),
                    file_path: file_path.clone(),
                    line,
                    message: format!("possible hardcoded {} detected", label),
                });
                break; // One violation per node
            }
        }
    }

    violations
}

/// R10: TODO/FIXME without assignee
fn rule_todo_fixme(
    mubase: &crate::engine::storage::MUbase,
    scope_files: &Option<HashSet<String>>,
) -> Vec<Violation> {
    let sql = r#"
        SELECT n.name, n.file_path, n.line_start, n.source_text
        FROM nodes n
        WHERE n.source_text IS NOT NULL
        ORDER BY n.file_path, n.line_start
    "#;

    let result = match mubase.query(sql) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    let todo_re = Regex::new(r"(?i)\b(TODO|FIXME|HACK|XXX)\b").unwrap();
    let assignee_re = Regex::new(r"(?i)(TODO|FIXME|HACK|XXX)\s*[\((@]\s*\w+").unwrap();

    let mut violations = Vec::new();

    for row in &result.rows {
        let name = match row.first().and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let file_path = row.get(1).and_then(|v| v.as_str()).map(|s| s.to_string());
        let line = row.get(2).and_then(|v| v.as_u64()).map(|l| l as u32);
        let source_text = row.get(3).and_then(|v| v.as_str()).unwrap_or("");

        if let Some(ref scope) = scope_files {
            if let Some(ref fp) = file_path {
                if !scope.contains(fp) {
                    continue;
                }
            }
        }

        // Find TODOs without assignees
        if todo_re.is_match(source_text) && !assignee_re.is_match(source_text) {
            // Extract the actual TODO line for the message
            let todo_line = source_text
                .lines()
                .find(|l| todo_re.is_match(l))
                .unwrap_or("TODO/FIXME");
            let trimmed = todo_line.trim();
            let preview = if trimmed.len() > 60 {
                let mut end = 57;
                while !trimmed.is_char_boundary(end) { end -= 1; }
                format!("{}...", &trimmed[..end])
            } else {
                trimmed.to_string()
            };

            violations.push(Violation {
                rule_id: "R10-todo".to_string(),
                severity: Severity::Info,
                node_name: name.clone(),
                file_path: file_path.clone(),
                line,
                message: format!("unassigned: {}", preview),
            });
        }
    }

    violations
}

/// R12: .unwrap()/.expect() in high-complexity functions
fn rule_unwrap_abuse(
    mubase: &crate::engine::storage::MUbase,
    scope_files: &Option<HashSet<String>>,
) -> Vec<Violation> {
    let sql = r#"
        SELECT n.name, n.file_path, n.line_start, n.complexity, n.source_text
        FROM nodes n
        WHERE n.type = 'function'
          AND n.complexity > 15
          AND n.source_text IS NOT NULL
        ORDER BY n.complexity DESC
    "#;

    let result = match mubase.query(sql) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    let unwrap_re = Regex::new(r"\.(unwrap|expect)\s*\(").unwrap();

    let mut violations = Vec::new();

    for row in &result.rows {
        let name = match row.first().and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let file_path = row.get(1).and_then(|v| v.as_str()).map(|s| s.to_string());
        let line = row.get(2).and_then(|v| v.as_u64()).map(|l| l as u32);
        let complexity = row.get(3).and_then(|v| v.as_u64()).unwrap_or(0);
        let source_text = row.get(4).and_then(|v| v.as_str()).unwrap_or("");

        if let Some(ref scope) = scope_files {
            if let Some(ref fp) = file_path {
                if !scope.contains(fp) {
                    continue;
                }
            }
        }

        let unwrap_count = unwrap_re.find_iter(source_text).count();
        if unwrap_count > 0 {
            violations.push(Violation {
                rule_id: "R12-unwrap".to_string(),
                severity: Severity::Warning,
                node_name: name,
                file_path,
                line,
                message: format!(
                    "{} unwrap/expect calls in function with complexity {}",
                    unwrap_count, complexity
                ),
            });
        }
    }

    violations
}

/// R14: Long parameter lists (>threshold params)
fn rule_long_params(
    mubase: &crate::engine::storage::MUbase,
    max_params: usize,
    scope_files: &Option<HashSet<String>>,
) -> Vec<Violation> {
    // source_text contains signatures like "fn foo(a: i32, b: String, c: bool)"
    // We'll parse the signature to count parameters
    let sql = r#"
        SELECT n.name, n.file_path, n.line_start, n.source_text
        FROM nodes n
        WHERE n.type = 'function'
          AND n.source_text IS NOT NULL
        ORDER BY n.file_path, n.line_start
    "#;

    let result = match mubase.query(sql) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    let mut violations = Vec::new();

    for row in &result.rows {
        let name = match row.first().and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let file_path = row.get(1).and_then(|v| v.as_str()).map(|s| s.to_string());
        let line = row.get(2).and_then(|v| v.as_u64()).map(|l| l as u32);
        let source_text = row.get(3).and_then(|v| v.as_str()).unwrap_or("");

        if let Some(ref scope) = scope_files {
            if let Some(ref fp) = file_path {
                if !scope.contains(fp) {
                    continue;
                }
            }
        }

        // Count parameters by finding the first parenthesized group and counting commas
        let param_count = count_params(source_text);

        if param_count > max_params {
            violations.push(Violation {
                rule_id: "R14-params".to_string(),
                severity: Severity::Warning,
                node_name: name,
                file_path,
                line,
                message: format!(
                    "{} parameters (max {}); consider a config struct",
                    param_count, max_params
                ),
            });
        }
    }

    violations
}

/// Count parameters from a function signature in source_text.
///
/// Handles nested generics/brackets so `HashMap<K, V>` counts as one param.
fn count_params(source_text: &str) -> usize {
    // Find the first '(' that's part of a function signature
    let first_line = source_text.lines().next().unwrap_or("");
    let sig_text = if first_line.contains('(') {
        first_line
    } else {
        // Maybe the signature spans multiple lines in source_text
        source_text
            .lines()
            .find(|l| l.contains('('))
            .unwrap_or("")
    };

    let open = match sig_text.find('(') {
        Some(i) => i,
        None => return 0,
    };

    // Find matching close paren, respecting nesting
    let chars: Vec<char> = sig_text.chars().collect();
    let mut depth = 0;
    let mut close = sig_text.len();
    for (i, &ch) in chars.iter().enumerate().skip(open) {
        match ch {
            '(' | '<' | '[' => depth += 1,
            ')' | '>' | ']' => {
                depth -= 1;
                if depth == 0 {
                    close = i;
                    break;
                }
            }
            _ => {}
        }
    }

    let param_str = &sig_text[open + 1..close];
    if param_str.trim().is_empty() {
        return 0;
    }

    // Filter out 'self' / '&self' / '&mut self' / 'cls' params
    let self_re = Regex::new(r"^\s*(&\s*(mut\s+)?)?self\s*$|^\s*cls\s*$").unwrap();
    let parts: Vec<&str> = split_params_at_depth_zero(param_str);
    let real_params = parts.iter().filter(|p| !self_re.is_match(p.split(':').next().unwrap_or(p).trim())).count();

    real_params
}

/// Split a parameter string by commas at depth 0.
fn split_params_at_depth_zero(s: &str) -> Vec<&str> {
    let mut result = Vec::new();
    let mut depth = 0;
    let mut start = 0;
    for (i, ch) in s.char_indices() {
        match ch {
            '<' | '(' | '[' | '{' => depth += 1,
            '>' | ')' | ']' | '}' => depth -= 1,
            ',' if depth == 0 => {
                result.push(&s[start..i]);
                start = i + 1;
            }
            _ => {}
        }
    }
    result.push(&s[start..]);
    result
}

// ============================================================================
// Project-local rules
// ============================================================================

/// Load project-local rules from .mu/rules/ directory.
fn load_project_rules(rules_dir: &Path) -> Vec<ProjectRule> {
    if !rules_dir.exists() {
        return Vec::new();
    }

    let mut rules = Vec::new();

    let entries = match std::fs::read_dir(rules_dir) {
        Ok(e) => e,
        Err(_) => return Vec::new(),
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("toml") {
            continue;
        }
        // Skip config.toml — that's for overrides, not rules
        if path.file_name().and_then(|n| n.to_str()) == Some("config.toml") {
            continue;
        }

        if let Ok(content) = std::fs::read_to_string(&path) {
            match toml::from_str::<RulesFile>(&content) {
                Ok(rf) => rules.extend(rf.rule),
                Err(e) => {
                    tracing::warn!("Failed to parse {}: {}", path.display(), e);
                }
            }
        }
    }

    rules
}

/// Load audit config overrides from .mu/rules/config.toml
fn load_audit_config(rules_dir: &Path) -> AuditConfig {
    let config_path = rules_dir.join("config.toml");
    if !config_path.exists() {
        return AuditConfig::default();
    }

    match std::fs::read_to_string(&config_path) {
        Ok(content) => match toml::from_str::<ConfigFile>(&content) {
            Ok(cf) => cf.audit,
            Err(e) => {
                tracing::warn!("Failed to parse {}: {}", config_path.display(), e);
                AuditConfig::default()
            }
        },
        Err(_) => AuditConfig::default(),
    }
}

/// Run project-local pattern rules against the codebase.
fn run_project_rules(
    mubase: &crate::engine::storage::MUbase,
    rules: &[ProjectRule],
    scope_files: &Option<HashSet<String>>,
) -> Vec<Violation> {
    if rules.is_empty() {
        return Vec::new();
    }

    let sql = r#"
        SELECT n.name, n.type, n.file_path, n.line_start, n.source_text
        FROM nodes n
        WHERE n.source_text IS NOT NULL
        ORDER BY n.file_path, n.line_start
    "#;

    let result = match mubase.query(sql) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    let mut violations = Vec::new();

    // Compile all rule patterns
    let compiled_rules: Vec<(&ProjectRule, Regex)> = rules
        .iter()
        .filter_map(|r| Regex::new(&r.pattern).ok().map(|re| (r, re)))
        .collect();

    for row in &result.rows {
        let name = match row.first().and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let node_type = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
        let file_path = row.get(2).and_then(|v| v.as_str()).map(|s| s.to_string());
        let line = row.get(3).and_then(|v| v.as_u64()).map(|l| l as u32);
        let source_text = row.get(4).and_then(|v| v.as_str()).unwrap_or("");

        if let Some(ref scope) = scope_files {
            if let Some(ref fp) = file_path {
                if !scope.contains(fp) {
                    continue;
                }
            }
        }

        for (rule, regex) in &compiled_rules {
            // Check node type filter
            if !rule.node_types.is_empty() && !rule.node_types.iter().any(|t| t == node_type) {
                continue;
            }

            if regex.is_match(source_text) {
                violations.push(Violation {
                    rule_id: rule.id.clone(),
                    severity: rule.severity,
                    node_name: name.clone(),
                    file_path: file_path.clone(),
                    line,
                    message: rule.description.clone(),
                });
            }
        }
    }

    violations
}

// ============================================================================
// Diff scoping
// ============================================================================

/// Get changed files between a git ref and HEAD.
fn get_diff_files(diff_base: &str) -> anyhow::Result<HashSet<String>> {
    let output = Command::new("git")
        .args(["diff", "--name-only", &format!("{}...HEAD", diff_base)])
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("git diff failed: {}", stderr);
    }

    let files: HashSet<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|l| !l.is_empty())
        .map(|s| s.to_string())
        .collect();

    Ok(files)
}

// ============================================================================
// Helpers
// ============================================================================

/// Run a SQL query and convert results to violations. The query must return
/// (name, file_path, line_start) as the first three columns.
fn query_to_violations(
    mubase: &crate::engine::storage::MUbase,
    sql: &str,
    scope_files: &Option<HashSet<String>>,
    rule_id: &str,
    severity: Severity,
    message_fn: impl Fn(&str, &Option<String>) -> String,
) -> Vec<Violation> {
    let result = match mubase.query(sql) {
        Ok(r) => r,
        Err(_) => return Vec::new(),
    };

    result
        .rows
        .iter()
        .filter_map(|row| {
            let name = row.first()?.as_str()?.to_string();
            let file_path = row.get(1).and_then(|v| v.as_str()).map(|s| s.to_string());
            let line = row.get(2).and_then(|v| v.as_u64()).map(|l| l as u32);

            if let Some(ref scope) = scope_files {
                if let Some(ref fp) = file_path {
                    if !scope.contains(fp) {
                        return None;
                    }
                }
            }

            Some(Violation {
                rule_id: rule_id.to_string(),
                severity,
                message: message_fn(&name, &file_path),
                node_name: name,
                file_path,
                line,
            })
        })
        .collect()
}

/// Count total nodes for stats.
fn count_nodes(mubase: &crate::engine::storage::MUbase) -> usize {
    mubase
        .query("SELECT COUNT(*) FROM nodes WHERE type IN ('function', 'class', 'module')")
        .ok()
        .and_then(|r| r.rows.first()?.first()?.as_u64())
        .map(|n| n as usize)
        .unwrap_or(0)
}

// ============================================================================
// CLI entry point
// ============================================================================

/// Run the audit command.
pub async fn run(
    min_complexity: Option<u32>,
    max_params: Option<usize>,
    diff: Option<&str>,
    rules_dir: Option<&str>,
    format: OutputFormat,
) -> anyhow::Result<()> {
    let start = Instant::now();

    // Find mubase
    let mubase_path = mubase::find_mubase_optional(".")
        .ok_or_else(|| anyhow::anyhow!("No .mu/mubase found. Run 'mu bootstrap' first."))?;

    let cwd = std::env::current_dir()?;
    let project_root = mubase::find_project_root(&cwd)
        .ok_or_else(|| anyhow::anyhow!("Could not determine project root."))?;

    let mubase = crate::engine::storage::MUbase::open_read_only(&mubase_path)?;

    // Load project-local config + rules
    let rules_path = match rules_dir {
        Some(d) => std::path::PathBuf::from(d),
        None => project_root.join(".mu").join("rules"),
    };
    let config = load_audit_config(&rules_path);
    let project_rules = load_project_rules(&rules_path);

    // Resolve thresholds (CLI > project config > defaults)
    let complexity_threshold = min_complexity
        .or(config.complexity_threshold)
        .unwrap_or(30);
    let param_limit = max_params.or(config.max_params).unwrap_or(6);

    // Resolve diff scope
    let scope_files = match diff {
        Some(base) => Some(get_diff_files(base)?),
        None => None,
    };

    let disabled: HashSet<&str> = config.disable.iter().map(|s| s.as_str()).collect();

    // Run all built-in rules
    let mut violations = Vec::new();
    let mut rules_run = 0;

    if !disabled.contains("R1-orphan") {
        violations.extend(rule_orphaned_fns(&mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R3-complexity") {
        violations.extend(rule_high_complexity(&mubase, complexity_threshold, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R5-docs") {
        violations.extend(rule_missing_docstrings(&mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R9-secrets") {
        violations.extend(rule_secrets(&mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R10-todo") {
        violations.extend(rule_todo_fixme(&mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R12-unwrap") {
        violations.extend(rule_unwrap_abuse(&mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R14-params") {
        violations.extend(rule_long_params(&mubase, param_limit, &scope_files));
        rules_run += 1;
    }

    // Run project-local rules
    let project_violations = run_project_rules(&mubase, &project_rules, &scope_files);
    rules_run += project_rules.len();
    violations.extend(project_violations);

    // Sort: errors first, then warnings, then info
    violations.sort_by(|a, b| a.severity.cmp(&b.severity));

    let nodes_checked = count_nodes(&mubase);
    let error_count = violations.iter().filter(|v| v.severity == Severity::Error).count();
    let warning_count = violations.iter().filter(|v| v.severity == Severity::Warning).count();
    let info_count = violations.iter().filter(|v| v.severity == Severity::Info).count();

    let duration_ms = start.elapsed().as_millis() as u64;

    let result = AuditResult {
        violations,
        rules_run,
        nodes_checked,
        error_count,
        warning_count,
        info_count,
        duration_ms,
        diff_scope: diff.map(|d| d.to_string()),
    };

    Output::new(result, format).render()
}

/// Run audit and return structured results (for MCP tool).
pub fn run_audit_for_mcp(
    mubase: &crate::engine::storage::MUbase,
    project_root: &Path,
    min_complexity: Option<u32>,
    diff_base: Option<&str>,
) -> Result<AuditResult, String> {
    let start = Instant::now();

    let rules_path = project_root.join(".mu").join("rules");
    let config = load_audit_config(&rules_path);
    let project_rules = load_project_rules(&rules_path);

    let complexity_threshold = min_complexity
        .or(config.complexity_threshold)
        .unwrap_or(30);
    let param_limit = config.max_params.unwrap_or(6);

    let scope_files = match diff_base {
        Some(base) => get_diff_files(base).ok(),
        None => None,
    };

    let disabled: HashSet<&str> = config.disable.iter().map(|s| s.as_str()).collect();

    let mut violations = Vec::new();
    let mut rules_run = 0;

    if !disabled.contains("R1-orphan") {
        violations.extend(rule_orphaned_fns(mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R3-complexity") {
        violations.extend(rule_high_complexity(mubase, complexity_threshold, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R5-docs") {
        violations.extend(rule_missing_docstrings(mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R9-secrets") {
        violations.extend(rule_secrets(mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R10-todo") {
        violations.extend(rule_todo_fixme(mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R12-unwrap") {
        violations.extend(rule_unwrap_abuse(mubase, &scope_files));
        rules_run += 1;
    }
    if !disabled.contains("R14-params") {
        violations.extend(rule_long_params(mubase, param_limit, &scope_files));
        rules_run += 1;
    }

    let project_violations = run_project_rules(mubase, &project_rules, &scope_files);
    rules_run += project_rules.len();
    violations.extend(project_violations);

    violations.sort_by(|a, b| a.severity.cmp(&b.severity));

    let nodes_checked = count_nodes(mubase);
    let error_count = violations.iter().filter(|v| v.severity == Severity::Error).count();
    let warning_count = violations.iter().filter(|v| v.severity == Severity::Warning).count();
    let info_count = violations.iter().filter(|v| v.severity == Severity::Info).count();

    Ok(AuditResult {
        violations,
        rules_run,
        nodes_checked,
        error_count,
        warning_count,
        info_count,
        duration_ms: start.elapsed().as_millis() as u64,
        diff_scope: diff_base.map(|d| d.to_string()),
    })
}

/// Format audit results as markdown (for MCP output).
pub fn format_as_markdown(result: &AuditResult) -> String {
    let mut md = String::new();

    md.push_str(&format!(
        "# Audit: {} errors, {} warnings, {} info\n",
        result.error_count, result.warning_count, result.info_count
    ));
    md.push_str(&format!(
        "Checked {} nodes with {} rules",
        result.nodes_checked, result.rules_run
    ));
    if let Some(ref scope) = result.diff_scope {
        md.push_str(&format!(" (scoped to {})", scope));
    }
    md.push_str(&format!(" in {}ms\n\n", result.duration_ms));

    if result.violations.is_empty() {
        md.push_str("No violations found.\n");
        return md;
    }

    // Group by severity
    for (severity, label) in [
        (Severity::Error, "Errors"),
        (Severity::Warning, "Warnings"),
        (Severity::Info, "Info"),
    ] {
        let group: Vec<&Violation> = result
            .violations
            .iter()
            .filter(|v| v.severity == severity)
            .collect();

        if group.is_empty() {
            continue;
        }

        md.push_str(&format!("## {} ({})\n\n", label, group.len()));

        for v in &group {
            let location = match (&v.file_path, v.line) {
                (Some(fp), Some(line)) => format!(" — {}:{}", fp, line),
                (Some(fp), None) => format!(" — {}", fp),
                _ => String::new(),
            };

            md.push_str(&format!(
                "- **[{}]** `{}`: {}{}\n",
                v.rule_id, v.node_name, v.message, location
            ));
        }
        md.push('\n');
    }

    md
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_count_params_simple() {
        assert_eq!(count_params("fn foo(a: i32, b: String)"), 2);
    }

    #[test]
    fn test_count_params_with_generics() {
        assert_eq!(
            count_params("fn foo(map: HashMap<K, V>, b: String)"),
            2
        );
    }

    #[test]
    fn test_count_params_empty() {
        assert_eq!(count_params("fn foo()"), 0);
    }

    #[test]
    fn test_count_params_self() {
        assert_eq!(count_params("fn foo(&self, a: i32, b: i32)"), 2);
        assert_eq!(count_params("fn foo(&mut self, a: i32)"), 1);
        assert_eq!(count_params("def foo(self, a, b)"), 2);
        assert_eq!(count_params("def foo(cls, a)"), 1);
    }

    #[test]
    fn test_count_params_no_parens() {
        assert_eq!(count_params("some random text"), 0);
    }

    #[test]
    fn test_count_params_many() {
        assert_eq!(
            count_params("fn foo(a: i32, b: i32, c: i32, d: i32, e: i32, f: i32, g: i32)"),
            7
        );
    }

    #[test]
    fn test_severity_ordering() {
        assert!(Severity::Error < Severity::Warning);
        assert!(Severity::Warning < Severity::Info);
    }

    #[test]
    fn test_audit_result_serialization() {
        let result = AuditResult {
            violations: vec![Violation {
                rule_id: "R3-complexity".to_string(),
                severity: Severity::Warning,
                node_name: "big_function".to_string(),
                file_path: Some("src/main.rs".to_string()),
                line: Some(42),
                message: "complexity 35 exceeds threshold 30".to_string(),
            }],
            rules_run: 7,
            nodes_checked: 100,
            error_count: 0,
            warning_count: 1,
            info_count: 0,
            duration_ms: 50,
            diff_scope: None,
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("big_function"));
        assert!(json.contains("R3-complexity"));
    }

    #[test]
    fn test_format_as_markdown() {
        let result = AuditResult {
            violations: vec![
                Violation {
                    rule_id: "R9-secrets".to_string(),
                    severity: Severity::Error,
                    node_name: "connect".to_string(),
                    file_path: Some("src/db.rs".to_string()),
                    line: Some(10),
                    message: "possible hardcoded password/secret detected".to_string(),
                },
                Violation {
                    rule_id: "R3-complexity".to_string(),
                    severity: Severity::Warning,
                    node_name: "process".to_string(),
                    file_path: Some("src/main.rs".to_string()),
                    line: Some(50),
                    message: "complexity 40 exceeds threshold 30".to_string(),
                },
            ],
            rules_run: 7,
            nodes_checked: 200,
            error_count: 1,
            warning_count: 1,
            info_count: 0,
            duration_ms: 100,
            diff_scope: None,
        };

        let md = format_as_markdown(&result);
        assert!(md.contains("# Audit: 1 errors"));
        assert!(md.contains("## Errors (1)"));
        assert!(md.contains("R9-secrets"));
        assert!(md.contains("## Warnings (1)"));
        assert!(md.contains("R3-complexity"));
    }

    #[test]
    fn test_project_rule_deserialization() {
        let toml_str = r#"
            [[rule]]
            id = "no-println"
            description = "Avoid println! in production code"
            pattern = 'println!\s*\('
            severity = "warning"
            node_types = ["function"]
        "#;

        let rf: RulesFile = toml::from_str(toml_str).unwrap();
        assert_eq!(rf.rule.len(), 1);
        assert_eq!(rf.rule[0].id, "no-println");
        assert_eq!(rf.rule[0].severity, Severity::Warning);
    }

    #[test]
    fn test_audit_config_deserialization() {
        let toml_str = r#"
            [audit]
            complexity_threshold = 20
            max_params = 5
            disable = ["R1-orphan", "R10-todo"]
        "#;

        let cf: ConfigFile = toml::from_str(toml_str).unwrap();
        assert_eq!(cf.audit.complexity_threshold, Some(20));
        assert_eq!(cf.audit.max_params, Some(5));
        assert_eq!(cf.audit.disable.len(), 2);
    }
}
