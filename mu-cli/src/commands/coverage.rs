//! Coverage command - Dead code detection
//!
//! Analyzes the codebase to find potentially dead or orphaned code:
//! - `--orphans`: Functions with no callers (excluding entry points)
//! - `--untested`: Public functions not directly called by any test function
//!
//! Results are grouped by directory and sorted by staleness (oldest first).

use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::Connection;
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;
use std::process::Command;

use crate::output::{Output, OutputFormat, TableDisplay};

/// Entry point patterns to exclude from orphan detection
const ENTRY_POINT_PATTERNS: &[&str] = &[
    "main",
    "run",
    "start",
    "__main__",
    "__init__",
    "__new__",
    "setup",
    "teardown",
    "setUp",
    "tearDown",
];

/// Test function patterns
const TEST_PATTERNS: &[&str] = &["test_", "_test", "Test", "test"];

/// .NET serialization/ORM attributes that indicate reflection-based access
/// Functions with these attributes are accessed by frameworks, not direct calls
const DOTNET_SERIALIZATION_ATTRS: &[&str] = &[
    "JsonProperty",
    "JsonPropertyName",
    "JsonIgnore",
    "Column",
    "Required",
    "Key",
    "ForeignKey",
    "NotMapped",
    "DataMember",
    "DataContract",
    "XmlElement",
    "XmlAttribute",
    "ProtoMember",
    "BsonElement",
    "MaxLength",
    "MinLength",
    "Range",
    "EmailAddress",
    "Phone",
    "Url",
    "RegularExpression",
    "Compare",
    "Display",
    "DisplayName",
    "Description",
    "DefaultValue",
];

/// A potentially dead function
#[derive(Debug, Clone, Serialize)]
pub struct DeadFunction {
    pub id: String,
    pub name: String,
    pub file_path: String,
    pub line_start: Option<i64>,
    pub reason: String,
    pub last_modified: Option<String>,
}

/// A group of dead functions by directory
#[derive(Debug, Clone, Serialize)]
pub struct DirectoryGroup {
    pub directory: String,
    pub functions: Vec<DeadFunction>,
}

/// Result of coverage analysis
#[derive(Debug, Serialize)]
pub struct CoverageResult {
    pub total_functions: usize,
    pub orphan_count: usize,
    pub untested_count: usize,
    pub groups: Vec<DirectoryGroup>,
    pub mode: String,
}

impl TableDisplay for CoverageResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!(
            "\n{} {}\n",
            "Dead Code Analysis".cyan().bold(),
            format!("({})", self.mode).dimmed()
        ));
        output.push_str(&format!("{}\n\n", "-".repeat(60)));

        let total_dead = if self.mode == "orphans" {
            self.orphan_count
        } else if self.mode == "untested" {
            self.untested_count
        } else {
            self.orphan_count + self.untested_count
        };

        if total_dead == 0 {
            output.push_str(&format!(
                "  {} No dead code detected!\n\n",
                "OK".green().bold()
            ));
            output.push_str(&format!(
                "  {} functions analyzed.\n",
                self.total_functions.to_string().cyan()
            ));
            return output;
        }

        // Group header
        for group in &self.groups {
            if group.functions.is_empty() {
                continue;
            }

            output.push_str(&format!(
                "{} {}\n",
                "Directory:".bold(),
                group.directory.yellow()
            ));

            for func in &group.functions {
                let staleness = func
                    .last_modified
                    .as_ref()
                    .map(|d| format!(" ({})", d).dimmed().to_string())
                    .unwrap_or_default();

                let location = func
                    .line_start
                    .map(|l| format!(":L{}", l))
                    .unwrap_or_default();

                output.push_str(&format!(
                    "  {} {}{}{}\n",
                    "[fn]".green(),
                    func.name.bold(),
                    location.dimmed(),
                    staleness
                ));
                output.push_str(&format!("      {} {}\n", "->".dimmed(), func.reason.dimmed()));
            }
            output.push('\n');
        }

        // Summary
        output.push_str(&format!("{}\n", "-".repeat(60)));
        output.push_str(&format!(
            "{}: {} functions analyzed\n",
            "Total".bold(),
            self.total_functions
        ));

        if self.orphan_count > 0 {
            output.push_str(&format!(
                "{}: {} functions with no callers\n",
                "Orphans".red().bold(),
                self.orphan_count
            ));
        }
        if self.untested_count > 0 {
            output.push_str(&format!(
                "{}: {} public functions without test coverage\n",
                "Untested".yellow().bold(),
                self.untested_count
            ));
        }

        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();
        output.push_str(&format!(":: coverage --{}\n", self.mode));
        output.push_str(&format!("# total_functions: {}\n", self.total_functions));
        output.push_str(&format!("# orphan_count: {}\n", self.orphan_count));
        output.push_str(&format!("# untested_count: {}\n", self.untested_count));

        for group in &self.groups {
            if group.functions.is_empty() {
                continue;
            }
            output.push_str(&format!("\n# {}\n", group.directory));
            for func in &group.functions {
                output.push_str(&format!("${} | {}\n", func.name, func.reason));
            }
        }

        output
    }
}

/// Run the coverage command
pub async fn run(
    orphans_only: bool,
    untested_only: bool,
    format: OutputFormat,
) -> Result<()> {
    let db_path = find_mubase(".")?;
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    let mode = if orphans_only {
        "orphans"
    } else if untested_only {
        "untested"
    } else {
        "all"
    };

    let mut all_dead: Vec<DeadFunction> = Vec::new();
    let mut orphan_count = 0;
    let mut untested_count = 0;

    // Get total function count
    let total_functions = count_functions(&conn)?;

    // Find orphans if requested
    if !untested_only {
        let orphans = find_orphans(&conn)?;
        orphan_count = orphans.len();
        all_dead.extend(orphans);
    }

    // Find untested if requested
    if !orphans_only {
        let untested = find_untested(&conn)?;
        untested_count = untested.len();

        // Avoid duplicates - only add untested functions not already in orphans
        let existing_ids: HashSet<_> = all_dead.iter().map(|f| f.id.clone()).collect();
        for func in untested {
            if !existing_ids.contains(&func.id) {
                all_dead.push(func);
            }
        }
    }

    // Add staleness info via git
    add_staleness_info(&mut all_dead)?;

    // Group by directory and sort by staleness
    let groups = group_by_directory(all_dead);

    let result = CoverageResult {
        total_functions,
        orphan_count,
        untested_count,
        groups,
        mode: mode.to_string(),
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

/// Count total functions in the database
fn count_functions(conn: &Connection) -> Result<usize> {
    let mut stmt = conn.prepare(
        "SELECT COUNT(*) FROM nodes
         WHERE type = 'function'
         AND file_path IS NOT NULL
         AND file_path NOT LIKE '%test%'
         AND file_path NOT LIKE '%spec%'",
    )?;
    let mut rows = stmt.query([])?;

    if let Some(row) = rows.next()? {
        let count: i64 = row.get(0)?;
        Ok(count as usize)
    } else {
        Ok(0)
    }
}

/// Find orphan functions (no callers, not entry points)
fn find_orphans(conn: &Connection) -> Result<Vec<DeadFunction>> {
    // Build the NOT LIKE clauses for entry points
    let entry_point_clauses: Vec<String> = ENTRY_POINT_PATTERNS
        .iter()
        .map(|p| format!("AND LOWER(n.name) NOT LIKE '%{}%'", p.to_lowercase()))
        .collect();

    // Include properties in query for filtering
    let sql = format!(
        "SELECT n.id, n.name, n.file_path, n.line_start, n.properties
         FROM nodes n
         WHERE n.type = 'function'
         AND n.file_path IS NOT NULL
         AND n.file_path NOT LIKE '%test%'
         AND n.file_path NOT LIKE '%spec%'
         AND n.file_path NOT LIKE '%mock%'
         AND n.id NOT IN (
             SELECT DISTINCT target_id FROM edges WHERE type = 'calls'
         )
         {}
         ORDER BY n.file_path, n.name
         LIMIT 500",
        entry_point_clauses.join("\n         ")
    );

    let mut stmt = conn.prepare(&sql)?;
    let mut rows = stmt.query([])?;

    let mut orphans = Vec::new();
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        let name: String = row.get(1)?;
        let file_path: String = row.get(2)?;
        let line_start: Option<i64> = row.get(3)?;
        let properties: Option<String> = row.get(4)?;

        // Additional filter: skip private functions (start with _)
        if name.starts_with('_') && !name.starts_with("__") {
            continue;
        }

        // Filter out .NET false positives using properties
        if let Some(ref props_str) = properties {
            if let Ok(props) = serde_json::from_str::<serde_json::Value>(props_str) {
                // Skip properties on DTO classes (accessed via reflection/serialization)
                if props.get("parent_is_dto").and_then(|v| v.as_bool()).unwrap_or(false) {
                    continue;
                }

                // Skip ALL orphan properties - if a property has no callers, it's accessed
                // via reflection (config binding, serialization, ORM, etc.)
                // Properties WITH callers are already excluded from the orphan set
                if props.get("is_property").and_then(|v| v.as_bool()).unwrap_or(false) {
                    continue;
                }

                // Skip functions with serialization/validation attributes
                if let Some(decorators) = props.get("decorators").and_then(|v| v.as_array()) {
                    let has_framework_attr = decorators.iter().any(|d| {
                        if let Some(decorator_str) = d.as_str() {
                            DOTNET_SERIALIZATION_ATTRS
                                .iter()
                                .any(|attr| decorator_str.contains(attr))
                        } else {
                            false
                        }
                    });
                    if has_framework_attr {
                        continue;
                    }
                }
            }
        }

        orphans.push(DeadFunction {
            id,
            name,
            file_path,
            line_start,
            reason: "No callers found".to_string(),
            last_modified: None,
        });
    }

    Ok(orphans)
}

/// Find untested public functions (not called by any test function)
fn find_untested(conn: &Connection) -> Result<Vec<DeadFunction>> {
    // Build test pattern matching for source functions
    let test_patterns: Vec<String> = TEST_PATTERNS
        .iter()
        .map(|p| format!("source.name LIKE '%{}%'", p))
        .collect();
    let test_condition = test_patterns.join(" OR ");

    // Find all test function IDs first
    let test_sql = format!(
        "SELECT DISTINCT e.target_id
         FROM edges e
         JOIN nodes source ON source.id = e.source_id
         WHERE e.type = 'calls'
         AND ({})
         OR source.file_path LIKE '%test%'
         OR source.file_path LIKE '%spec%'",
        test_condition
    );

    // Find public functions not in the tested set (include properties for filtering)
    let sql = format!(
        "SELECT n.id, n.name, n.file_path, n.line_start, n.properties
         FROM nodes n
         WHERE n.type = 'function'
         AND n.file_path IS NOT NULL
         AND n.file_path NOT LIKE '%test%'
         AND n.file_path NOT LIKE '%spec%'
         AND n.file_path NOT LIKE '%mock%'
         AND n.id NOT IN ({})
         ORDER BY n.file_path, n.name
         LIMIT 500",
        test_sql
    );

    let mut stmt = conn.prepare(&sql)?;
    let mut rows = stmt.query([])?;

    let mut untested = Vec::new();
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        let name: String = row.get(1)?;
        let file_path: String = row.get(2)?;
        let line_start: Option<i64> = row.get(3)?;
        let properties: Option<String> = row.get(4)?;

        // Skip private functions (start with single _)
        if name.starts_with('_') && !name.starts_with("__") {
            continue;
        }

        // Skip entry points for untested too
        let name_lower = name.to_lowercase();
        if ENTRY_POINT_PATTERNS
            .iter()
            .any(|p| name_lower.contains(&p.to_lowercase()))
        {
            continue;
        }

        // Filter out .NET false positives using properties
        if let Some(ref props_str) = properties {
            if let Ok(props) = serde_json::from_str::<serde_json::Value>(props_str) {
                // Skip properties on DTO classes (accessed via reflection/serialization)
                if props.get("parent_is_dto").and_then(|v| v.as_bool()).unwrap_or(false) {
                    continue;
                }

                // Skip ALL properties - they're tested indirectly through the classes that use them
                if props.get("is_property").and_then(|v| v.as_bool()).unwrap_or(false) {
                    continue;
                }
            }
        }

        untested.push(DeadFunction {
            id,
            name,
            file_path,
            line_start,
            reason: "No test coverage (not called by test functions)".to_string(),
            last_modified: None,
        });
    }

    Ok(untested)
}

/// Add staleness info via git log (file-level)
fn add_staleness_info(functions: &mut [DeadFunction]) -> Result<()> {
    // Cache file modification dates
    let mut date_cache: HashMap<String, Option<String>> = HashMap::new();

    for func in functions.iter_mut() {
        let file_path = &func.file_path;

        if !date_cache.contains_key(file_path) {
            let date = get_file_last_modified(file_path);
            date_cache.insert(file_path.clone(), date);
        }

        func.last_modified = date_cache.get(file_path).cloned().flatten();
    }

    Ok(())
}

/// Get last modified date for a file via git
fn get_file_last_modified(file_path: &str) -> Option<String> {
    let output = Command::new("git")
        .args([
            "log",
            "-1",
            "--format=%ad",
            "--date=short",
            "--",
            file_path,
        ])
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let date = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if date.is_empty() {
        None
    } else {
        Some(date)
    }
}

/// Group functions by directory and sort by staleness
fn group_by_directory(mut functions: Vec<DeadFunction>) -> Vec<DirectoryGroup> {
    // Sort by last_modified (oldest first, None at the end)
    functions.sort_by(|a, b| {
        match (&a.last_modified, &b.last_modified) {
            (Some(a_date), Some(b_date)) => a_date.cmp(b_date), // Oldest first
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => std::cmp::Ordering::Equal,
        }
    });

    // Group by directory
    let mut groups: HashMap<String, Vec<DeadFunction>> = HashMap::new();

    for func in functions {
        let dir = std::path::Path::new(&func.file_path)
            .parent()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| ".".to_string());

        groups.entry(dir).or_default().push(func);
    }

    // Convert to sorted vec
    let mut result: Vec<DirectoryGroup> = groups
        .into_iter()
        .map(|(directory, functions)| DirectoryGroup {
            directory,
            functions,
        })
        .collect();

    // Sort directories by their oldest function
    result.sort_by(|a, b| {
        let a_oldest = a
            .functions
            .first()
            .and_then(|f| f.last_modified.as_ref());
        let b_oldest = b
            .functions
            .first()
            .and_then(|f| f.last_modified.as_ref());

        match (a_oldest, b_oldest) {
            (Some(a_date), Some(b_date)) => a_date.cmp(b_date),
            (Some(_), None) => std::cmp::Ordering::Less,
            (None, Some(_)) => std::cmp::Ordering::Greater,
            (None, None) => a.directory.cmp(&b.directory),
        }
    });

    result
}
