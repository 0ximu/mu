//! Patterns command - Detect code patterns in the codebase
//!
//! Analyzes the code graph to detect common patterns across different categories:
//! naming conventions, architectural patterns, testing patterns, etc.

use crate::output::{Output, OutputFormat, TableDisplay};
use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::Connection;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;

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

/// Pattern category
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PatternCategory {
    Naming,
    Architecture,
    Testing,
    Imports,
    ErrorHandling,
    Api,
    Async,
    Logging,
}

impl PatternCategory {
    fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "naming" => Some(Self::Naming),
            "architecture" => Some(Self::Architecture),
            "testing" => Some(Self::Testing),
            "imports" => Some(Self::Imports),
            "error_handling" | "error-handling" => Some(Self::ErrorHandling),
            "api" => Some(Self::Api),
            "async" => Some(Self::Async),
            "logging" => Some(Self::Logging),
            _ => None,
        }
    }

    fn as_str(&self) -> &'static str {
        match self {
            Self::Naming => "naming",
            Self::Architecture => "architecture",
            Self::Testing => "testing",
            Self::Imports => "imports",
            Self::ErrorHandling => "error_handling",
            Self::Api => "api",
            Self::Async => "async",
            Self::Logging => "logging",
        }
    }

    fn all() -> Vec<Self> {
        vec![
            Self::Naming,
            Self::Architecture,
            Self::Testing,
            Self::Imports,
            Self::ErrorHandling,
            Self::Api,
            Self::Async,
            Self::Logging,
        ]
    }
}

/// A detected pattern
#[derive(Debug, Clone, Serialize)]
pub struct DetectedPattern {
    /// Pattern name
    pub name: String,
    /// Category
    pub category: String,
    /// Description
    pub description: String,
    /// Confidence score (0.0 - 1.0)
    pub confidence: f32,
    /// Number of occurrences
    pub occurrences: usize,
    /// Example entities matching this pattern
    pub examples: Vec<String>,
}

/// Pattern analysis result
#[derive(Debug, Serialize)]
pub struct PatternAnalysis {
    /// Detected patterns
    pub patterns: Vec<DetectedPattern>,
    /// Total nodes analyzed
    pub nodes_analyzed: usize,
    /// Categories analyzed
    pub categories_analyzed: Vec<String>,
}

impl TableDisplay for PatternAnalysis {
    fn to_table(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!(
            "{} (analyzed {} nodes)\n",
            "PATTERNS:".cyan().bold(),
            self.nodes_analyzed
        ));
        output.push_str(&format!("{}\n", "-".repeat(70)));

        if self.patterns.is_empty() {
            output.push_str(&"  No patterns detected.\n".dimmed().to_string());
            return output;
        }

        // Group by category
        let mut by_category: HashMap<String, Vec<&DetectedPattern>> = HashMap::new();
        for pattern in &self.patterns {
            by_category
                .entry(pattern.category.clone())
                .or_default()
                .push(pattern);
        }

        for category in &self.categories_analyzed {
            if let Some(patterns) = by_category.get(category) {
                output.push_str(&format!(
                    "\n{} {}:\n",
                    "▸".cyan(),
                    category.to_uppercase().bold()
                ));

                for pattern in patterns {
                    let confidence_bar = make_confidence_bar(pattern.confidence);
                    let confidence_pct = format!("{:.0}%", pattern.confidence * 100.0);

                    output.push_str(&format!(
                        "  {} {} {} ({}x)\n",
                        confidence_bar,
                        pattern.name.yellow(),
                        confidence_pct.dimmed(),
                        pattern.occurrences
                    ));
                    output.push_str(&format!("    {}\n", pattern.description.dimmed()));

                    if !pattern.examples.is_empty() {
                        let examples: String = pattern
                            .examples
                            .iter()
                            .take(3)
                            .cloned()
                            .collect::<Vec<_>>()
                            .join(", ");
                        output.push_str(&format!(
                            "    {}: {}\n",
                            "Examples".dimmed(),
                            examples.dimmed()
                        ));
                    }
                }
            }
        }

        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!(":: patterns nodes={}\n", self.nodes_analyzed));

        for pattern in &self.patterns {
            output.push_str(&format!(
                "@ {} [{}] confidence={:.2} count={}\n",
                pattern.name, pattern.category, pattern.confidence, pattern.occurrences
            ));
            output.push_str(&format!("  | {}\n", pattern.description));
            if !pattern.examples.is_empty() {
                output.push_str(&format!("  # examples: {}\n", pattern.examples.join(", ")));
            }
        }

        output
    }
}

fn make_confidence_bar(confidence: f32) -> String {
    let filled = (confidence * 5.0).round() as usize;
    let empty = 5 - filled;
    format!(
        "[{}{}]",
        "█".repeat(filled).green(),
        "░".repeat(empty).dimmed()
    )
}

/// Detect naming patterns
fn detect_naming_patterns(
    conn: &Connection,
    include_examples: bool,
) -> Result<Vec<DetectedPattern>> {
    let mut patterns = Vec::new();

    // Snake case functions (Python style)
    let snake_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'function' AND name LIKE '%_%' AND name = LOWER(name)",
        [],
        |row| row.get(0),
    )?;

    let total_functions: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'function'",
        [],
        |row| row.get(0),
    )?;

    if total_functions > 0 && snake_count > 0 {
        let confidence = snake_count as f32 / total_functions as f32;
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE type = 'function' AND name LIKE '%_%' AND name = LOWER(name) LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "snake_case_functions".to_string(),
            category: "naming".to_string(),
            description: "Functions use snake_case naming convention".to_string(),
            confidence,
            occurrences: snake_count,
            examples,
        });
    }

    // PascalCase classes
    let pascal_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'class' AND name GLOB '[A-Z]*'",
        [],
        |row| row.get(0),
    )?;

    let total_classes: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'class'",
        [],
        |row| row.get(0),
    )?;

    if total_classes > 0 && pascal_count > 0 {
        let confidence = pascal_count as f32 / total_classes as f32;
        let examples = if include_examples {
            get_examples(
                conn,
                "SELECT name FROM nodes WHERE type = 'class' AND name GLOB '[A-Z]*' LIMIT 5",
            )?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "PascalCase_classes".to_string(),
            category: "naming".to_string(),
            description: "Classes use PascalCase naming convention".to_string(),
            confidence,
            occurrences: pascal_count,
            examples,
        });
    }

    // Service suffix pattern
    let service_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'class' AND name LIKE '%Service'",
        [],
        |row| row.get(0),
    )?;

    if service_count >= 2 {
        let examples = if include_examples {
            get_examples(
                conn,
                "SELECT name FROM nodes WHERE type = 'class' AND name LIKE '%Service' LIMIT 5",
            )?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "service_suffix".to_string(),
            category: "naming".to_string(),
            description: "Service classes use 'Service' suffix".to_string(),
            confidence: 0.8,
            occurrences: service_count,
            examples,
        });
    }

    Ok(patterns)
}

/// Detect architectural patterns
fn detect_architecture_patterns(
    conn: &Connection,
    include_examples: bool,
) -> Result<Vec<DetectedPattern>> {
    let mut patterns = Vec::new();

    // Repository pattern
    let repo_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'class' AND (name LIKE '%Repository' OR name LIKE '%Repo')",
        [],
        |row| row.get(0),
    )?;

    if repo_count >= 1 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE type = 'class' AND (name LIKE '%Repository' OR name LIKE '%Repo') LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "repository_pattern".to_string(),
            category: "architecture".to_string(),
            description: "Uses Repository pattern for data access".to_string(),
            confidence: 0.9,
            occurrences: repo_count,
            examples,
        });
    }

    // Factory pattern
    let factory_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE (type = 'class' OR type = 'function') AND name LIKE '%Factory%'",
        [],
        |row| row.get(0),
    )?;

    if factory_count >= 1 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE (type = 'class' OR type = 'function') AND name LIKE '%Factory%' LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "factory_pattern".to_string(),
            category: "architecture".to_string(),
            description: "Uses Factory pattern for object creation".to_string(),
            confidence: 0.85,
            occurrences: factory_count,
            examples,
        });
    }

    // Handler pattern (common in web frameworks)
    let handler_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE (type = 'class' OR type = 'function') AND name LIKE '%Handler%'",
        [],
        |row| row.get(0),
    )?;

    if handler_count >= 2 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE (type = 'class' OR type = 'function') AND name LIKE '%Handler%' LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "handler_pattern".to_string(),
            category: "architecture".to_string(),
            description: "Uses Handler pattern for request/event processing".to_string(),
            confidence: 0.8,
            occurrences: handler_count,
            examples,
        });
    }

    // Modular structure (multiple modules)
    let module_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'module'",
        [],
        |row| row.get(0),
    )?;

    if module_count >= 5 {
        patterns.push(DetectedPattern {
            name: "modular_architecture".to_string(),
            category: "architecture".to_string(),
            description: "Codebase follows modular architecture".to_string(),
            confidence: (module_count as f32 / 20.0).min(1.0),
            occurrences: module_count,
            examples: vec![],
        });
    }

    Ok(patterns)
}

/// Detect testing patterns
fn detect_testing_patterns(
    conn: &Connection,
    include_examples: bool,
) -> Result<Vec<DetectedPattern>> {
    let mut patterns = Vec::new();

    // Test files
    let test_files: usize = conn.query_row(
        "SELECT COUNT(DISTINCT file_path) FROM nodes WHERE file_path LIKE '%test%' OR file_path LIKE '%spec%'",
        [],
        |row| row.get(0),
    )?;

    if test_files >= 1 {
        let examples = if include_examples {
            get_examples(conn, "SELECT DISTINCT file_path FROM nodes WHERE file_path LIKE '%test%' OR file_path LIKE '%spec%' LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "test_directory".to_string(),
            category: "testing".to_string(),
            description: "Tests organized in test/spec directories".to_string(),
            confidence: 0.9,
            occurrences: test_files,
            examples,
        });
    }

    // Test functions
    let test_functions: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'function' AND (name LIKE 'test_%' OR name LIKE '%_test')",
        [],
        |row| row.get(0),
    )?;

    if test_functions >= 3 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE type = 'function' AND (name LIKE 'test_%' OR name LIKE '%_test') LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "test_functions".to_string(),
            category: "testing".to_string(),
            description: "Test functions follow test_ naming convention".to_string(),
            confidence: 0.95,
            occurrences: test_functions,
            examples,
        });
    }

    Ok(patterns)
}

/// Detect import patterns
fn detect_import_patterns(
    conn: &Connection,
    _include_examples: bool,
) -> Result<Vec<DetectedPattern>> {
    let mut patterns = Vec::new();

    // Check edge types for imports
    let import_edges: usize = conn.query_row(
        "SELECT COUNT(*) FROM edges WHERE type = 'imports'",
        [],
        |row| row.get(0),
    )?;

    let module_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'module'",
        [],
        |row| row.get(0),
    )?;

    if module_count > 0 && import_edges > 0 {
        let avg_imports = import_edges as f32 / module_count as f32;

        if avg_imports < 5.0 {
            patterns.push(DetectedPattern {
                name: "minimal_imports".to_string(),
                category: "imports".to_string(),
                description: "Modules have minimal import dependencies".to_string(),
                confidence: 1.0 - (avg_imports / 10.0).min(1.0),
                occurrences: import_edges,
                examples: vec![format!("{:.1} imports/module avg", avg_imports)],
            });
        } else if avg_imports > 15.0 {
            patterns.push(DetectedPattern {
                name: "heavy_imports".to_string(),
                category: "imports".to_string(),
                description: "Modules have many import dependencies".to_string(),
                confidence: (avg_imports / 30.0).min(1.0),
                occurrences: import_edges,
                examples: vec![format!("{:.1} imports/module avg", avg_imports)],
            });
        }
    }

    Ok(patterns)
}

/// Detect error handling patterns
fn detect_error_handling_patterns(
    conn: &Connection,
    include_examples: bool,
) -> Result<Vec<DetectedPattern>> {
    let mut patterns = Vec::new();

    // Error/Exception classes
    let error_classes: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'class' AND (name LIKE '%Error' OR name LIKE '%Exception')",
        [],
        |row| row.get(0),
    )?;

    if error_classes >= 2 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE type = 'class' AND (name LIKE '%Error' OR name LIKE '%Exception') LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "custom_exceptions".to_string(),
            category: "error_handling".to_string(),
            description: "Defines custom error/exception classes".to_string(),
            confidence: 0.9,
            occurrences: error_classes,
            examples,
        });
    }

    Ok(patterns)
}

/// Detect API patterns
fn detect_api_patterns(conn: &Connection, include_examples: bool) -> Result<Vec<DetectedPattern>> {
    let mut patterns = Vec::new();

    // REST-like function names
    let rest_functions: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'function' AND (name LIKE 'get_%' OR name LIKE 'post_%' OR name LIKE 'put_%' OR name LIKE 'delete_%' OR name LIKE 'create_%' OR name LIKE 'update_%')",
        [],
        |row| row.get(0),
    )?;

    if rest_functions >= 3 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE type = 'function' AND (name LIKE 'get_%' OR name LIKE 'post_%' OR name LIKE 'create_%' OR name LIKE 'update_%' OR name LIKE 'delete_%') LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "rest_naming".to_string(),
            category: "api".to_string(),
            description: "API functions follow REST-like naming (get_, create_, update_, delete_)"
                .to_string(),
            confidence: 0.85,
            occurrences: rest_functions,
            examples,
        });
    }

    // Route/endpoint pattern
    let route_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'function' AND (name LIKE '%_route' OR name LIKE '%_endpoint' OR name LIKE '%_view')",
        [],
        |row| row.get(0),
    )?;

    if route_count >= 2 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE type = 'function' AND (name LIKE '%_route' OR name LIKE '%_endpoint' OR name LIKE '%_view') LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "route_handlers".to_string(),
            category: "api".to_string(),
            description: "Uses route/endpoint/view naming for API handlers".to_string(),
            confidence: 0.9,
            occurrences: route_count,
            examples,
        });
    }

    Ok(patterns)
}

/// Detect async patterns
fn detect_async_patterns(
    conn: &Connection,
    include_examples: bool,
) -> Result<Vec<DetectedPattern>> {
    let mut patterns = Vec::new();

    // Async function names
    let async_functions: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE type = 'function' AND (name LIKE 'async_%' OR name LIKE '%_async')",
        [],
        |row| row.get(0),
    )?;

    if async_functions >= 2 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE type = 'function' AND (name LIKE 'async_%' OR name LIKE '%_async') LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "async_naming".to_string(),
            category: "async".to_string(),
            description: "Async functions use async_ prefix/suffix".to_string(),
            confidence: 0.8,
            occurrences: async_functions,
            examples,
        });
    }

    Ok(patterns)
}

/// Detect logging patterns
fn detect_logging_patterns(
    conn: &Connection,
    include_examples: bool,
) -> Result<Vec<DetectedPattern>> {
    let mut patterns = Vec::new();

    // Logger classes/functions
    let logger_count: usize = conn.query_row(
        "SELECT COUNT(*) FROM nodes WHERE name LIKE '%logger%' OR name LIKE '%Logger%' OR name LIKE '%logging%'",
        [],
        |row| row.get(0),
    )?;

    if logger_count >= 1 {
        let examples = if include_examples {
            get_examples(conn, "SELECT name FROM nodes WHERE name LIKE '%logger%' OR name LIKE '%Logger%' OR name LIKE '%logging%' LIMIT 5")?
        } else {
            vec![]
        };

        patterns.push(DetectedPattern {
            name: "centralized_logging".to_string(),
            category: "logging".to_string(),
            description: "Uses centralized logging infrastructure".to_string(),
            confidence: 0.85,
            occurrences: logger_count,
            examples,
        });
    }

    Ok(patterns)
}

/// Get example names from a query
fn get_examples(conn: &Connection, sql: &str) -> Result<Vec<String>> {
    let mut stmt = conn.prepare(sql)?;
    let mut rows = stmt.query([])?;
    let mut examples = Vec::new();

    while let Some(row) = rows.next()? {
        let name: String = row.get(0)?;
        examples.push(name);
    }

    Ok(examples)
}

/// Run the patterns command
pub async fn run(
    category: Option<&str>,
    refresh: bool,
    include_examples: bool,
    format: OutputFormat,
) -> Result<()> {
    run_direct(category, refresh, include_examples, format).await
}

/// Run patterns command with direct database access
async fn run_direct(
    category: Option<&str>,
    _refresh: bool,
    include_examples: bool,
    format: OutputFormat,
) -> Result<()> {
    // Find the MUbase database
    let db_path = find_mubase(".")?;

    // Open the database in read-only mode
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    // Get total nodes for analysis
    let nodes_analyzed: usize =
        conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))?;

    // Determine which categories to analyze
    let categories: Vec<PatternCategory> = match category {
        Some(cat) => {
            let parsed = PatternCategory::from_str(cat)
                .ok_or_else(|| anyhow::anyhow!("Unknown category: {}", cat))?;
            vec![parsed]
        }
        None => PatternCategory::all(),
    };

    let mut all_patterns = Vec::new();
    let mut categories_analyzed = Vec::new();

    for cat in &categories {
        categories_analyzed.push(cat.as_str().to_string());

        let patterns = match cat {
            PatternCategory::Naming => detect_naming_patterns(&conn, include_examples)?,
            PatternCategory::Architecture => detect_architecture_patterns(&conn, include_examples)?,
            PatternCategory::Testing => detect_testing_patterns(&conn, include_examples)?,
            PatternCategory::Imports => detect_import_patterns(&conn, include_examples)?,
            PatternCategory::ErrorHandling => {
                detect_error_handling_patterns(&conn, include_examples)?
            }
            PatternCategory::Api => detect_api_patterns(&conn, include_examples)?,
            PatternCategory::Async => detect_async_patterns(&conn, include_examples)?,
            PatternCategory::Logging => detect_logging_patterns(&conn, include_examples)?,
        };

        all_patterns.extend(patterns);
    }

    // Sort by confidence (descending)
    // Use unwrap_or to handle NaN values safely
    all_patterns.sort_by(|a, b| {
        b.confidence
            .partial_cmp(&a.confidence)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let result = PatternAnalysis {
        patterns: all_patterns,
        nodes_analyzed,
        categories_analyzed,
    };

    Output::new(result, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pattern_category_from_str() {
        assert_eq!(
            PatternCategory::from_str("naming"),
            Some(PatternCategory::Naming)
        );
        assert_eq!(
            PatternCategory::from_str("ARCHITECTURE"),
            Some(PatternCategory::Architecture)
        );
        assert_eq!(
            PatternCategory::from_str("error_handling"),
            Some(PatternCategory::ErrorHandling)
        );
        assert_eq!(
            PatternCategory::from_str("error-handling"),
            Some(PatternCategory::ErrorHandling)
        );
        assert_eq!(PatternCategory::from_str("unknown"), None);
    }

    #[test]
    fn test_make_confidence_bar() {
        let bar = make_confidence_bar(1.0);
        assert!(bar.contains("█████"));

        let bar = make_confidence_bar(0.0);
        assert!(bar.contains("░░░░░"));

        let bar = make_confidence_bar(0.5);
        // Should have roughly half filled
        assert!(bar.contains("█") && bar.contains("░"));
    }
}
