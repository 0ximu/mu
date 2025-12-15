//! Query command - Execute MUQL queries against the MU database.
//!
//! Opens the database directly in read-only mode.
//! Supports SQL and terse SELECT syntax (fn, cls, mod with filters).
//!
//! Results are formatted in various output formats (table, json, csv).
//!
//! Examples:
//!   mu q "SELECT * FROM functions LIMIT 5"
//!   mu q "SELECT name, complexity FROM functions ORDER BY complexity DESC"
//!   mu q "SHOW TABLES"
//!   mu q --format json "SELECT * FROM classes"
//!   mu q --limit 20 "SELECT * FROM functions"
//!   mu q "fn c>50"                              # Terse syntax
//!   mu q "cls n%Service"                        # Classes matching pattern

use crate::output::{OutputFormat, TableDisplay};
use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::Connection;
use serde::Serialize;
use std::path::PathBuf;
use std::time::Instant;
use tabled::{builder::Builder, settings::Style};

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

/// Result of terse syntax parsing
enum TerseParseResult {
    /// Successfully converted to SQL
    Sql(String),
    /// Not terse syntax - use as-is (probably raw SQL)
    NotTerse,
    /// Terse graph operation - requires daemon
    RequiresDaemon(String),
}

/// Try to convert terse MUQL syntax to SQL.
///
/// Terse syntax patterns:
/// - `fn` -> SELECT * FROM functions
/// - `fn c>50` -> SELECT * FROM functions WHERE complexity > 50
/// - `fn c<10` -> SELECT * FROM functions WHERE complexity < 10
/// - `fn n%auth` -> SELECT * FROM functions WHERE name LIKE '%auth%'
/// - `fn f%src/api` -> SELECT * FROM functions WHERE file_path LIKE '%src/api%'
/// - `cls` -> SELECT * FROM classes
/// - `mod` -> SELECT * FROM modules
/// - `meth` -> SELECT * FROM methods (same as functions)
///
/// Graph operations that require daemon:
/// - `deps TARGET [dN]` -> SHOW dependencies
/// - `impact TARGET` -> SHOW impact
fn try_convert_terse_to_sql(input: &str) -> TerseParseResult {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return TerseParseResult::NotTerse;
    }

    // Check if it starts with SQL keywords - not terse
    let sql_keywords = [
        "select", "show", "find", "path", "analyze", "describe", "insert", "update", "delete",
        "with", "explain",
    ];
    let lower = trimmed.to_lowercase();
    for kw in sql_keywords {
        if lower.starts_with(kw) {
            return TerseParseResult::NotTerse;
        }
    }

    // Split into tokens
    let tokens: Vec<&str> = trimmed.split_whitespace().collect();
    if tokens.is_empty() {
        return TerseParseResult::NotTerse;
    }

    let first = tokens[0].to_lowercase();

    // Graph operations that require daemon
    match first.as_str() {
        "deps" | "dependents" | "impact" | "ancestors" | "callers" | "callees" | "path" => {
            let suggestion = match first.as_str() {
                "deps" => {
                    if tokens.len() > 1 {
                        let target = tokens[1];
                        let depth = tokens
                            .get(2)
                            .and_then(|d| d.strip_prefix('d'))
                            .unwrap_or("1");
                        format!("SHOW dependencies OF {} DEPTH {}", target, depth)
                    } else {
                        "SHOW dependencies OF <target> DEPTH <n>".to_string()
                    }
                }
                "impact" => {
                    if tokens.len() > 1 {
                        format!("SHOW impact OF {}", tokens[1])
                    } else {
                        "SHOW impact OF <target>".to_string()
                    }
                }
                "ancestors" => {
                    if tokens.len() > 1 {
                        format!("SHOW ancestors OF {}", tokens[1])
                    } else {
                        "SHOW ancestors OF <target>".to_string()
                    }
                }
                _ => format!("Use MUQL: SHOW {} OF <target>", first),
            };
            return TerseParseResult::RequiresDaemon(suggestion);
        }
        _ => {}
    }

    // SELECT-convertible terse patterns
    let sql_type = match first.as_str() {
        "fn" | "func" | "functions" => "function",
        "cls" | "class" | "classes" => "class",
        "mod" | "module" | "modules" => "module",
        "meth" | "method" | "methods" => "function", // methods are functions
        _ => return TerseParseResult::NotTerse,
    };

    // Base query
    let base_columns = "id, type, name, file_path, line_start, line_end, complexity";
    let mut conditions: Vec<String> = vec![format!("type = '{}'", sql_type)];
    let mut limit = 100;
    let mut order_by: Option<String> = None;

    // Parse remaining tokens as filters
    for token in tokens.iter().skip(1) {
        let token_lower = token.to_lowercase();

        // Limit: l10 or limit10
        if let Some(n) = token_lower.strip_prefix('l') {
            if let Ok(num) = n.parse::<usize>() {
                limit = num;
                continue;
            }
        }

        // Complexity filters: c>50, c<10, c>=20, c=5
        if token_lower.starts_with("c>")
            || token_lower.starts_with("c<")
            || token_lower.starts_with("c=")
        {
            let op_char = token.chars().nth(1).unwrap();
            let rest = &token[2..];

            // Handle >= and <=
            let (op, value) = if let Some(stripped) = rest.strip_prefix('=') {
                (format!("{}=", op_char), stripped)
            } else {
                (op_char.to_string(), rest)
            };

            if let Ok(num) = value.parse::<i64>() {
                conditions.push(format!("complexity {} {}", op, num));
                continue;
            }
        }

        // Name pattern: n%pattern or name%pattern
        if let Some(pattern) = token_lower
            .strip_prefix("n%")
            .or_else(|| token_lower.strip_prefix("name%"))
        {
            let escaped = pattern.replace('\'', "''");
            conditions.push(format!("name LIKE '%{}%'", escaped));
            continue;
        }

        // File path pattern: f%pattern or file%pattern or path%pattern
        if let Some(pattern) = token_lower
            .strip_prefix("f%")
            .or_else(|| token_lower.strip_prefix("file%"))
            .or_else(|| token_lower.strip_prefix("path%"))
        {
            let escaped = pattern.replace('\'', "''");
            conditions.push(format!("file_path LIKE '%{}%'", escaped));
            continue;
        }

        // Order: o:complexity, o:-complexity (descending), o:name
        if let Some(field) = token_lower.strip_prefix("o:") {
            let (field_name, desc) = if let Some(f) = field.strip_prefix('-') {
                (f, true)
            } else {
                (field, false)
            };
            // Validate field name (basic alphanumeric check)
            if field_name.chars().all(|c| c.is_alphanumeric() || c == '_') {
                order_by = Some(if desc {
                    format!("{} DESC", field_name)
                } else {
                    format!("{} ASC", field_name)
                });
            }
            continue;
        }

        // If token looks like a bare pattern (no special prefix), treat as name filter
        if !token.contains(':')
            && !token.contains('>')
            && !token.contains('<')
            && !token.contains('=')
        {
            let escaped = token.replace('\'', "''");
            conditions.push(format!("name LIKE '%{}%'", escaped));
        }
    }

    // Build final SQL
    let mut sql = format!("SELECT {} FROM nodes", base_columns);

    if !conditions.is_empty() {
        sql.push_str(" WHERE ");
        sql.push_str(&conditions.join(" AND "));
    }

    if let Some(ob) = order_by {
        sql.push_str(&format!(" ORDER BY {}", ob));
    }

    sql.push_str(&format!(" LIMIT {}", limit));

    TerseParseResult::Sql(sql)
}

/// Normalize type values in SQL queries to lowercase.
/// Database stores types as: 'function', 'class', 'module', 'external'
fn normalize_type_in_sql(sql: &str) -> String {
    // Match patterns like: type = 'Class' or type='CLASS' or type = "Function"
    let re = regex::Regex::new(r#"(?i)\btype\s*=\s*['"]([^'"]+)['"]"#).unwrap();
    re.replace_all(sql, |caps: &regex::Captures| {
        let type_value = caps.get(1).map(|m| m.as_str()).unwrap_or("");
        format!("type = '{}'", type_value.to_lowercase())
    })
    .to_string()
}

/// Rewrite virtual table names to nodes table with type filter.
///
/// Transforms:
/// - `FROM functions` -> `FROM nodes WHERE type = 'function'`
/// - `FROM classes` -> `FROM nodes WHERE type = 'class'`
/// - `FROM modules` -> `FROM nodes WHERE type = 'module'`
///
/// Handles WHERE clause merging:
/// - `SELECT * FROM functions WHERE complexity > 10`
///   -> `SELECT * FROM nodes WHERE type = 'function' AND complexity > 10`
fn rewrite_virtual_tables(sql: &str) -> String {
    // Virtual table mappings (case-insensitive)
    let virtual_tables = [
        ("functions", "function"),
        ("classes", "class"),
        ("modules", "module"),
    ];

    let mut result = sql.to_string();

    for (virtual_table, type_value) in virtual_tables {
        // Pattern: FROM <virtual_table> (case-insensitive, word boundary)
        // Captures optional whitespace and handles WHERE clause presence
        let pattern = format!(r"(?i)\bFROM\s+{}\b", regex::escape(virtual_table));
        let re = regex::Regex::new(&pattern).unwrap();

        if re.is_match(&result) {
            // Check if there's already a WHERE clause after the table name
            // Pattern to find WHERE after the table name
            let where_pattern = format!(r"(?i)\bFROM\s+{}\s+WHERE\b", regex::escape(virtual_table));
            let where_re = regex::Regex::new(&where_pattern).unwrap();

            if where_re.is_match(&result) {
                // Has WHERE clause - merge conditions with AND
                let replace_pattern =
                    format!(r"(?i)\bFROM\s+{}\s+WHERE\b", regex::escape(virtual_table));
                let replace_re = regex::Regex::new(&replace_pattern).unwrap();
                result = replace_re
                    .replace(
                        &result,
                        format!("FROM nodes WHERE type = '{}' AND", type_value),
                    )
                    .to_string();
            } else {
                // No WHERE clause - add type filter
                result = re
                    .replace(&result, format!("FROM nodes WHERE type = '{}'", type_value))
                    .to_string();
            }
        }
    }

    result
}

/// Execute a SQL query directly against the database (standalone mode).
///
/// Opens the database in read-only mode and executes raw SQL.
/// Supports both raw SQL and terse SELECT syntax (fn, cls, mod).
fn execute_query_direct(query_str: &str) -> Result<QueryResult> {
    let start = Instant::now();

    // Try to convert terse syntax to SQL
    let final_query = match try_convert_terse_to_sql(query_str) {
        TerseParseResult::Sql(sql) => sql,
        TerseParseResult::NotTerse => {
            // Not terse syntax - rewrite virtual tables (functions, classes, modules)
            // to nodes table with type filter for standalone mode
            rewrite_virtual_tables(query_str)
        }
        TerseParseResult::RequiresDaemon(suggestion) => {
            return Err(anyhow::anyhow!(
                "Graph operations require the daemon.\n\nStart daemon: mu serve\nOr use SQL: {}",
                suggestion
            ));
        }
    };

    // Normalize type values in WHERE clauses (case-insensitive)
    let final_query = normalize_type_in_sql(&final_query);

    // Find the database
    let db_path = find_mubase(".")?;

    // Open in read-only mode
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    // Execute the query directly and collect all results
    // Note: DuckDB requires query execution before accessing column metadata
    let mut stmt = conn.prepare(&final_query).map_err(|e| {
        let msg = e.to_string();
        // Provide friendlier error messages for common issues
        if msg.contains("syntax error") {
            anyhow::anyhow!(
                "Invalid query syntax.\n\n\
                 Hint: Run 'mu query --examples' for valid query examples.\n\n\
                 Details: {}",
                msg
            )
        } else if msg.contains("does not exist") {
            anyhow::anyhow!(
                "Table or column not found.\n\n\
                 Hint: Run 'mu query \"SHOW TABLES\"' to see available tables,\n\
                       or 'mu query --schema' for column reference.\n\n\
                 Details: {}",
                msg
            )
        } else {
            anyhow::anyhow!("Query failed: {}", msg)
        }
    })?;

    let mut rows = stmt.query([])?;

    // Get column info from the result set after execution
    let column_count = rows.as_ref().map(|r| r.column_count()).unwrap_or(0);
    let columns: Vec<String> = if column_count > 0 {
        (0..column_count)
            .map(|i| {
                rows.as_ref()
                    .and_then(|r| r.column_name(i).ok())
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| format!("col_{}", i))
            })
            .collect()
    } else {
        vec![]
    };

    // Collect rows
    let mut rows_data: Vec<Vec<String>> = Vec::new();

    while let Some(row) = rows.next()? {
        let mut row_values: Vec<String> = Vec::new();
        for i in 0..column_count {
            // Try to extract value as different types
            let value = if let Ok(v) = row.get::<_, String>(i) {
                v
            } else if let Ok(v) = row.get::<_, i64>(i) {
                v.to_string()
            } else if let Ok(v) = row.get::<_, f64>(i) {
                v.to_string()
            } else if let Ok(v) = row.get::<_, bool>(i) {
                v.to_string()
            } else {
                // Try to get as Value for NULL handling
                match row.get_ref(i) {
                    Ok(value_ref) => {
                        use duckdb::types::ValueRef;
                        match value_ref {
                            ValueRef::Null => "NULL".to_string(),
                            ValueRef::Text(s) => String::from_utf8_lossy(s).to_string(),
                            ValueRef::Blob(b) => format!("<blob:{} bytes>", b.len()),
                            _ => "?".to_string(),
                        }
                    }
                    Err(_) => "NULL".to_string(),
                }
            };
            row_values.push(value);
        }
        rows_data.push(row_values);
    }

    let duration_ms = start.elapsed().as_millis() as u64;

    Ok(QueryResult {
        columns,
        row_count: rows_data.len(),
        rows: rows_data,
        execution_time_ms: duration_ms,
        error: None,
    })
}

/// MUQL query examples shown with --examples flag
pub const MUQL_EXAMPLES: &str = r#"
MUQL Query Examples
===================

Basic SELECT queries:
  SELECT * FROM functions                    # All functions
  SELECT * FROM functions LIMIT 10           # First 10 functions
  SELECT name, complexity FROM functions     # Specific columns
  SELECT * FROM classes WHERE complexity > 20

Filtering:
  SELECT * FROM functions WHERE name LIKE '%auth%'
  SELECT * FROM functions WHERE name = 'parse_file'
  SELECT * FROM classes WHERE file_path LIKE 'src/api/%'

Aggregation:
  SELECT COUNT(*) FROM functions
  SELECT type, COUNT(*) FROM nodes GROUP BY type
  SELECT AVG(complexity) FROM functions

Terse syntax (shortcuts):
  fn                                         # All functions
  fn c>50                                    # Functions with complexity > 50
  fn n%auth                                  # Functions matching 'auth'
  fn f%src/api                               # Functions in src/api path
  cls                                        # All classes
  mod                                        # All modules
  fn c>10 l5 o:-complexity                   # Combined: filter, limit, order

Schema info:
  SHOW TABLES                                # List available tables
  DESCRIBE nodes                             # Schema for nodes table

Graph operations (use dedicated commands):
  mu deps MyClass                            # Dependencies of MyClass
  mu deps MyClass -r                         # What depends on MyClass
  mu impact Parser                           # What breaks if Parser changes
  mu ancestors Parser                        # What Parser depends on
  mu cycles                                  # Find circular dependencies
  mu path cli parser                         # Path between nodes

For more details: https://github.com/0ximu/mu#muql
"#;

/// MUQL schema reference shown with --schema flag
pub const MUQL_SCHEMA: &str = r#"
MUQL Schema Reference
=====================

Tables:
  nodes       - All nodes (modules, classes, functions)
  edges       - Relationships between nodes
  embeddings  - Vector embeddings for semantic search
  metadata    - Database metadata

Virtual tables (auto-rewritten to nodes with type filter):
  functions   -> nodes WHERE type = 'function'
  classes     -> nodes WHERE type = 'class'
  modules     -> nodes WHERE type = 'module'

Node columns:
  id            VARCHAR   Node identifier (e.g., "cls:src/auth.py:AuthService")
  type          VARCHAR   Node type: module, class, function
  name          VARCHAR   Simple name (e.g., "AuthService")
  qualified_name VARCHAR  Full qualified name
  file_path     VARCHAR   Source file path
  line_start    INTEGER   Start line number
  line_end      INTEGER   End line number
  complexity    INTEGER   Cyclomatic complexity score
  properties    JSON      Additional metadata

Edge columns:
  source_id     VARCHAR   Source node ID
  target_id     VARCHAR   Target node ID
  type          VARCHAR   Edge type (see below)

Edge types:
  contains   - Module->Class, Class->Function (structural)
  imports    - Module->Module (import dependencies)
  inherits   - Class->Class (inheritance)
  calls      - Function->Function (call graph)

Common filters:
  WHERE complexity > 20        # High complexity
  WHERE name LIKE 'test_%'     # Name pattern
  WHERE file_path LIKE 'src/%' # Path pattern
  WHERE type = 'function'      # Node type

Tip: Use SHOW TABLES or DESCRIBE nodes for live schema info.
"#;

/// Query result for display
#[derive(Debug, Serialize)]
pub struct QueryResult {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<String>>,
    pub row_count: usize,
    pub execution_time_ms: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl TableDisplay for QueryResult {
    fn to_table(&self) -> String {
        if let Some(ref error) = self.error {
            return format!("{} {}", "ERROR:".red().bold(), error);
        }

        if self.rows.is_empty() {
            return format!("{}", "No results found.".dimmed());
        }

        // Build table using tabled
        let mut builder = Builder::default();

        // Add header row
        builder.push_record(&self.columns);

        // Add data rows
        for row in &self.rows {
            builder.push_record(row);
        }

        let mut table = builder.build();
        table.with(Style::rounded());

        // Add footer with stats
        let footer = format!(
            "\n{} {} row(s) in {}ms",
            "Returned".dimmed(),
            self.row_count.to_string().cyan(),
            self.execution_time_ms.to_string().yellow()
        );

        format!("{}{}", table, footer)
    }

    fn to_mu(&self) -> String {
        if let Some(ref error) = self.error {
            return format!(":: error\n{}", error);
        }

        let mut output = String::new();
        output.push_str(":: query-result\n");

        // Header
        output.push_str(&format!("; columns: {}\n", self.columns.join(", ")));

        // Rows as S-expressions
        for row in &self.rows {
            let values: Vec<String> = row
                .iter()
                .enumerate()
                .map(|(i, v)| {
                    let col = self.columns.get(i).map(|s| s.as_str()).unwrap_or("?");
                    format!(":{} {}", col, v)
                })
                .collect();
            output.push_str(&format!("(row {})\n", values.join(" ")));
        }

        output.push_str(&format!(
            "; {} rows, {}ms\n",
            self.row_count, self.execution_time_ms
        ));
        output
    }
}

/// Format QueryResult as CSV
fn format_csv(result: &QueryResult) -> String {
    if result.error.is_some() || result.rows.is_empty() {
        return String::new();
    }

    let mut output = String::new();

    // Header
    output.push_str(&result.columns.join(","));
    output.push('\n');

    // Rows
    for row in &result.rows {
        let escaped: Vec<String> = row
            .iter()
            .map(|v| {
                // Escape quotes and wrap in quotes if contains comma or quote
                if v.contains(',') || v.contains('"') || v.contains('\n') {
                    format!("\"{}\"", v.replace('"', "\"\""))
                } else {
                    v.clone()
                }
            })
            .collect();
        output.push_str(&escaped.join(","));
        output.push('\n');
    }

    output
}

/// Run the query command
#[allow(dead_code)]
pub async fn run(query_str: &str, interactive: bool, format: OutputFormat) -> Result<()> {
    if interactive {
        // Interactive mode not available without daemon
        eprintln!(
            "{} Interactive REPL mode is not available.",
            "ERROR:".red().bold()
        );
        eprintln!();
        eprintln!("Run queries directly instead:");
        eprintln!(
            "  {}",
            "mu query \"SELECT * FROM functions LIMIT 10\"".cyan()
        );
        eprintln!("  {}", "mu query \"fn c>50\"".cyan());
        std::process::exit(1);
    }

    let result = execute_query_direct(query_str)?;
    print_result(&result, format)?;

    if result.error.is_some() {
        std::process::exit(1);
    }

    Ok(())
}

/// Print query result in the specified format
fn print_result(result: &QueryResult, format: OutputFormat) -> Result<()> {
    match format {
        OutputFormat::Table => {
            println!("{}", result.to_table());
        }
        OutputFormat::Json => {
            println!("{}", serde_json::to_string_pretty(result)?);
        }
        OutputFormat::Mu => {
            println!("{}", result.to_mu());
        }
        OutputFormat::Csv => {
            print!("{}", format_csv(result));
        }
        OutputFormat::Tree => {
            // Tree format: show as hierarchical if applicable, otherwise table
            println!("{}", result.to_table());
        }
    }
    Ok(())
}

/// Run the query command with extended options
pub async fn run_extended(
    query_str: Option<&str>,
    interactive: bool,
    format: OutputFormat,
    limit: Option<usize>,
    examples: bool,
    schema: bool,
) -> Result<()> {
    // Handle --examples flag
    if examples {
        println!("{}", MUQL_EXAMPLES);
        return Ok(());
    }

    // Handle --schema flag
    if schema {
        println!("{}", MUQL_SCHEMA);
        return Ok(());
    }

    if interactive || query_str.is_none() {
        // Interactive mode not available
        eprintln!(
            "{} Interactive REPL mode is not available.",
            "ERROR:".red().bold()
        );
        eprintln!();
        eprintln!("Run queries directly instead:");
        eprintln!(
            "  {}",
            "mu query \"SELECT * FROM functions LIMIT 10\"".cyan()
        );
        eprintln!("  {}", "mu query \"fn c>50\"".cyan());
        std::process::exit(1);
    }

    let query_str = query_str.unwrap();

    // Apply limit override if specified
    let final_query = if let Some(limit) = limit {
        // Check if query already has LIMIT
        if query_str.to_uppercase().contains(" LIMIT ") {
            query_str.to_string()
        } else {
            format!("{} LIMIT {}", query_str, limit)
        }
    } else {
        query_str.to_string()
    };

    let result = execute_query_direct(&final_query)?;
    print_result(&result, format)?;

    // Exit with error code if query failed
    if result.error.is_some() {
        std::process::exit(1);
    }

    Ok(())
}

/// Format result as CSV string
#[allow(dead_code)]
pub fn to_csv(result: &QueryResult) -> String {
    format_csv(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_csv_formatting() {
        let result = QueryResult {
            columns: vec!["name".to_string(), "value".to_string()],
            rows: vec![
                vec!["foo".to_string(), "bar".to_string()],
                vec!["with,comma".to_string(), "normal".to_string()],
                vec!["with\"quote".to_string(), "ok".to_string()],
            ],
            row_count: 3,
            execution_time_ms: 10,
            error: None,
        };

        let csv = format_csv(&result);
        assert!(csv.contains("name,value"));
        assert!(csv.contains("foo,bar"));
        assert!(csv.contains("\"with,comma\"")); // Comma should be quoted
        assert!(csv.contains("\"with\"\"quote\"")); // Quote should be escaped
    }

    #[test]
    fn test_table_display_empty() {
        let result = QueryResult {
            columns: vec![],
            rows: vec![],
            row_count: 0,
            execution_time_ms: 5,
            error: None,
        };

        let table = result.to_table();
        assert!(table.contains("No results"));
    }

    #[test]
    fn test_table_display_error() {
        let result = QueryResult {
            columns: vec![],
            rows: vec![],
            row_count: 0,
            execution_time_ms: 0,
            error: Some("Syntax error".to_string()),
        };

        let table = result.to_table();
        assert!(table.contains("Syntax error"));
    }

    #[test]
    fn test_find_mubase_not_found() {
        // Create a temp directory without a mubase
        let dir = tempfile::tempdir().unwrap();
        let result = find_mubase(dir.path().to_str().unwrap());
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("No MUbase found"));
    }

    #[test]
    fn test_find_mubase_new_path() {
        // Create a temp directory with .mu/mubase
        let dir = tempfile::tempdir().unwrap();
        let mu_dir = dir.path().join(".mu");
        std::fs::create_dir(&mu_dir).unwrap();
        let mubase_path = mu_dir.join("mubase");
        std::fs::write(&mubase_path, "").unwrap();

        let result = find_mubase(dir.path().to_str().unwrap());
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), mubase_path.canonicalize().unwrap());
    }

    #[test]
    fn test_find_mubase_legacy_path() {
        // Create a temp directory with .mubase (legacy)
        let dir = tempfile::tempdir().unwrap();
        let mubase_path = dir.path().join(".mubase");
        std::fs::write(&mubase_path, "").unwrap();

        let result = find_mubase(dir.path().to_str().unwrap());
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), mubase_path.canonicalize().unwrap());
    }

    // Terse syntax conversion tests
    #[test]
    fn test_terse_fn_basic() {
        match try_convert_terse_to_sql("fn") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("FROM nodes"));
                assert!(sql.contains("type = 'function'"));
                assert!(sql.contains("LIMIT 100"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    #[test]
    fn test_terse_fn_complexity_filter() {
        match try_convert_terse_to_sql("fn c>50") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("type = 'function'"));
                assert!(sql.contains("complexity > 50"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    #[test]
    fn test_terse_fn_name_pattern() {
        match try_convert_terse_to_sql("fn n%auth") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("type = 'function'"));
                assert!(sql.contains("name LIKE '%auth%'"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    #[test]
    fn test_terse_cls_basic() {
        match try_convert_terse_to_sql("cls") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("type = 'class'"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    #[test]
    fn test_terse_mod_basic() {
        match try_convert_terse_to_sql("mod") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("type = 'module'"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    #[test]
    fn test_terse_with_limit() {
        match try_convert_terse_to_sql("fn l20") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("LIMIT 20"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    #[test]
    fn test_terse_with_order() {
        match try_convert_terse_to_sql("fn o:-complexity") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("ORDER BY complexity DESC"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    #[test]
    fn test_terse_deps_requires_daemon() {
        match try_convert_terse_to_sql("deps Auth d2") {
            TerseParseResult::RequiresDaemon(suggestion) => {
                assert!(suggestion.contains("SHOW dependencies OF Auth DEPTH 2"));
            }
            _ => panic!("Expected RequiresDaemon result"),
        }
    }

    #[test]
    fn test_sql_not_terse() {
        match try_convert_terse_to_sql("SELECT * FROM functions") {
            TerseParseResult::NotTerse => {}
            _ => panic!("Expected NotTerse result"),
        }
    }

    #[test]
    fn test_terse_file_pattern() {
        match try_convert_terse_to_sql("fn f%src/api") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("file_path LIKE '%src/api%'"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    #[test]
    fn test_terse_combined_filters() {
        match try_convert_terse_to_sql("fn c>10 n%parse l5 o:-complexity") {
            TerseParseResult::Sql(sql) => {
                assert!(sql.contains("complexity > 10"));
                assert!(sql.contains("name LIKE '%parse%'"));
                assert!(sql.contains("LIMIT 5"));
                assert!(sql.contains("ORDER BY complexity DESC"));
            }
            _ => panic!("Expected Sql result"),
        }
    }

    // Virtual table rewrite tests
    #[test]
    fn test_virtual_table_rewrite_functions() {
        let result = rewrite_virtual_tables("SELECT * FROM functions");
        assert_eq!(result, "SELECT * FROM nodes WHERE type = 'function'");
    }

    #[test]
    fn test_virtual_table_rewrite_with_where() {
        let result = rewrite_virtual_tables("SELECT * FROM functions WHERE complexity > 10");
        assert_eq!(
            result,
            "SELECT * FROM nodes WHERE type = 'function' AND complexity > 10"
        );
    }

    #[test]
    fn test_virtual_table_rewrite_classes() {
        let result = rewrite_virtual_tables("SELECT name FROM classes");
        assert_eq!(result, "SELECT name FROM nodes WHERE type = 'class'");
    }

    #[test]
    fn test_virtual_table_rewrite_modules() {
        let result = rewrite_virtual_tables("SELECT * FROM modules WHERE name LIKE '%api%'");
        assert_eq!(
            result,
            "SELECT * FROM nodes WHERE type = 'module' AND name LIKE '%api%'"
        );
    }

    #[test]
    fn test_virtual_table_preserves_case() {
        // Should handle case-insensitive FROM FUNCTIONS
        let result = rewrite_virtual_tables("SELECT * FROM FUNCTIONS");
        assert!(result.contains("FROM nodes WHERE type = 'function'"));

        // Should handle mixed case
        let result2 = rewrite_virtual_tables("SELECT * FROM Functions WHERE complexity > 5");
        assert!(result2.contains("FROM nodes WHERE type = 'function' AND complexity > 5"));
    }

    #[test]
    fn test_virtual_table_preserves_other_clauses() {
        let result = rewrite_virtual_tables(
            "SELECT name, complexity FROM functions WHERE complexity > 10 ORDER BY complexity DESC LIMIT 20",
        );
        assert!(result.contains("FROM nodes WHERE type = 'function' AND complexity > 10"));
        assert!(result.contains("ORDER BY complexity DESC"));
        assert!(result.contains("LIMIT 20"));
    }

    #[test]
    fn test_virtual_table_no_rewrite_nodes() {
        // Should not modify queries that already use 'nodes' table
        let query = "SELECT * FROM nodes WHERE type = 'function'";
        let result = rewrite_virtual_tables(query);
        assert_eq!(result, query);
    }

    #[test]
    fn test_virtual_table_no_rewrite_edges() {
        // Should not modify queries on other tables
        let query = "SELECT * FROM edges";
        let result = rewrite_virtual_tables(query);
        assert_eq!(result, query);
    }
}
