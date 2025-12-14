//! Vibe command - Pattern conformance checking
//!
//! Checks if code matches established codebase patterns.
//! Useful for ensuring consistency and can be used in CI.
//!
//! Categories:
//! - naming: Naming conventions (language-aware)
//! - architecture: Architectural patterns
//! - testing: Test patterns
//! - imports: Import organization
//! - api: API patterns
//! - async: Async patterns

use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::Connection;
use std::collections::{HashMap, HashSet};
use std::path::PathBuf;

use super::conventions::{
    check_convention, convention_for, detect_language, is_csharp_test_method, is_dunder,
    NamingConvention,
};
use crate::output::OutputFormat;

/// A pattern issue found during vibe check
#[derive(Debug, Clone, serde::Serialize)]
pub struct VibeIssue {
    pub file: String,
    pub category: String,
    pub message: String,
    pub suggestion: Option<String>,
}

/// Result of a vibe check
#[derive(Debug, serde::Serialize)]
pub struct VibeResult {
    pub path: String,
    pub files_checked: usize,
    pub patterns_detected: usize,
    pub issues: Vec<VibeIssue>,
}

impl VibeResult {
    fn is_immaculate(&self) -> bool {
        self.issues.is_empty()
    }
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

/// Node data loaded from database
#[derive(Debug, Clone)]
struct NodeData {
    id: String,
    node_type: String,
    name: String,
    file_path: Option<String>,
}

/// Check naming conventions (language-aware)
fn check_naming_conventions(
    nodes: &[NodeData],
    convention_override: Option<NamingConvention>,
) -> Vec<VibeIssue> {
    let mut issues = Vec::new();

    for node in nodes {
        // Skip empty names (parser artifacts)
        if node.name.is_empty() {
            continue;
        }

        // Skip dunder methods in Python
        if is_dunder(&node.name) {
            continue;
        }

        // Skip EF Core migrations (they use timestamp_Name convention intentionally)
        if let Some(ref path) = node.file_path {
            if path.contains("/Migrations/") || path.contains("\\Migrations\\") {
                continue;
            }
        }

        // Determine the language from file path
        let language = node
            .file_path
            .as_ref()
            .map(|p| detect_language(p))
            .unwrap_or("unknown");

        // Map node type to entity type string
        let entity_type = match node.node_type.as_str() {
            "function" => "function",
            "method" => "method",
            "class" => "class",
            "struct" => "struct",
            "interface" => "interface",
            "trait" => "interface",
            "enum" => "enum",
            "constant" => "constant",
            "variable" => "variable",
            "module" => "module",
            "property" => "property",
            "field" => "property",
            _ => continue, // Skip unknown types
        };

        // Skip C# test methods that use Method_Scenario_Expected naming pattern
        // This is the standard convention for xUnit/NUnit/MSTest test methods
        if language == "csharp"
            && (entity_type == "function" || entity_type == "method")
            && is_csharp_test_method(&node.name, node.file_path.as_deref())
        {
            continue;
        }

        // Get expected convention (override or language-specific)
        let expected_convention =
            convention_override.unwrap_or_else(|| convention_for(language, entity_type));

        // Check if the name follows the expected convention
        if let Some(suggestion) = check_convention(&node.name, expected_convention) {
            issues.push(VibeIssue {
                file: node.file_path.clone().unwrap_or_else(|| node.id.clone()),
                category: "naming".to_string(),
                message: format!(
                    "{} '{}' should use {} ({})",
                    capitalize_first(entity_type),
                    node.name,
                    expected_convention,
                    language
                ),
                suggestion: Some(format!("Rename to '{}'", suggestion)),
            });
        }
    }

    issues
}

/// Capitalize the first letter of a string
fn capitalize_first(s: &str) -> String {
    let mut chars = s.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
        None => String::new(),
    }
}

/// Check for circular imports
fn check_circular_imports(conn: &Connection, path: &str) -> Result<Vec<VibeIssue>> {
    let mut issues = Vec::new();

    let path_filter = path_filter_clause(path, "n.file_path");
    let query = format!(
        r#"
        WITH RECURSIVE import_path(source, target, path, depth, source_file) AS (
            SELECT e.source_id, e.target_id, ARRAY[e.source_id, e.target_id], 1, n.file_path
            FROM edges e
            JOIN nodes n ON e.source_id = n.id
            WHERE e.type = 'imports'
              AND n.file_path IS NOT NULL
              {}

            UNION ALL

            SELECT ip.source, e.target_id, list_append(ip.path, e.target_id), ip.depth + 1, ip.source_file
            FROM import_path ip
            JOIN edges e ON ip.target = e.source_id
            WHERE e.type = 'imports'
              AND ip.depth < 10
              AND NOT list_contains(ip.path, e.target_id)
        )
        SELECT DISTINCT source, target, path
        FROM import_path
        WHERE source = target AND depth > 1
        LIMIT 50
    "#,
        path_filter
    );

    let mut stmt = conn.prepare(&query)?;
    let mut rows = stmt.query([])?;

    let mut seen_cycles = HashSet::new();
    while let Some(row) = rows.next()? {
        let source: String = row.get(0)?;
        let path_str: String = row.get(2)?;

        let cycle_key = format!("{}:{}", source, path_str);
        if seen_cycles.contains(&cycle_key) {
            continue;
        }
        seen_cycles.insert(cycle_key);

        let file_info = get_file_from_node_id(&source);
        issues.push(VibeIssue {
            file: file_info.unwrap_or_else(|| source.clone()),
            category: "architecture".to_string(),
            message: format!("Circular import detected involving {}", source),
            suggestion: Some("Consider refactoring to break the circular dependency".to_string()),
        });
    }

    Ok(issues)
}

/// Check for test coverage
fn check_test_coverage(conn: &Connection, path: &str) -> Result<Vec<VibeIssue>> {
    let mut issues = Vec::new();

    let path_filter = path_filter_clause(path, "file_path");
    let source_funcs_query = format!(
        r#"
        SELECT DISTINCT file_path, name
        FROM nodes
        WHERE type = 'function'
          AND file_path IS NOT NULL
          AND file_path NOT LIKE '%test%'
          AND file_path NOT LIKE '%__pycache__%'
          AND name NOT LIKE '__%'
          {}
        ORDER BY file_path
        LIMIT 100
    "#,
        path_filter
    );

    let test_funcs_query = format!(
        r#"
        SELECT DISTINCT name
        FROM nodes
        WHERE type = 'function'
          AND file_path IS NOT NULL
          AND file_path LIKE '%test%'
          {}
    "#,
        path_filter
    );

    let mut test_func_names = HashSet::new();
    let mut stmt = conn.prepare(&test_funcs_query)?;
    let mut rows = stmt.query([])?;
    while let Some(row) = rows.next()? {
        let name: String = row.get(0)?;
        test_func_names.insert(name);
    }

    let mut stmt = conn.prepare(&source_funcs_query)?;
    let mut rows = stmt.query([])?;

    let mut file_issues: HashMap<String, Vec<String>> = HashMap::new();
    while let Some(row) = rows.next()? {
        let file_path: String = row.get(0)?;
        let func_name: String = row.get(1)?;

        let has_test = test_func_names.iter().any(|test_name| {
            test_name.contains(&func_name) || test_name.ends_with(&format!("_{}", func_name))
        });

        if !has_test {
            file_issues
                .entry(file_path.clone())
                .or_default()
                .push(func_name);
        }
    }

    for (file_path, funcs) in file_issues.iter().take(20) {
        let test_path = infer_test_path(file_path);
        issues.push(VibeIssue {
            file: file_path.clone(),
            category: "testing".to_string(),
            message: format!("{} function(s) without corresponding tests", funcs.len()),
            suggestion: Some(format!("Create test file: {}", test_path)),
        });
    }

    Ok(issues)
}

/// Check import organization
fn check_imports(conn: &Connection, path: &str) -> Result<Vec<VibeIssue>> {
    let mut issues = Vec::new();

    let path_filter = path_filter_clause(path, "n.file_path");
    let query = format!(
        r#"
        SELECT e.source_id, n.file_path, e.target_id
        FROM edges e
        JOIN nodes n ON e.source_id = n.id
        WHERE e.type = 'imports'
          AND n.file_path IS NOT NULL
          AND e.target_id LIKE 'ext:%'
          {}
        ORDER BY n.file_path
    "#,
        path_filter
    );

    let mut stmt = conn.prepare(&query)?;
    let mut rows = stmt.query([])?;

    let mut file_imports: HashMap<String, Vec<String>> = HashMap::new();
    while let Some(row) = rows.next()? {
        let _source_id: String = row.get(0)?;
        let file_path: String = row.get(1)?;
        let target_id: String = row.get(2)?;

        file_imports
            .entry(file_path.clone())
            .or_default()
            .push(target_id.clone());
    }

    for (file_path, imports) in file_imports.iter() {
        if imports.len() > 50 {
            issues.push(VibeIssue {
                file: file_path.clone(),
                category: "imports".to_string(),
                message: format!("Excessive imports: {} external dependencies", imports.len()),
                suggestion: Some("Consider breaking this module into smaller pieces".to_string()),
            });
        }
    }

    Ok(issues)
}

/// Check API patterns
fn check_api_patterns(conn: &Connection, path: &str) -> Result<Vec<VibeIssue>> {
    let mut issues = Vec::new();

    let path_filter = path_filter_clause(path, "n.file_path");
    let query = format!(
        r#"
        SELECT n.name, n.file_path
        FROM nodes n
        WHERE n.type = 'function'
          AND (n.name LIKE '%api%' OR n.name LIKE '%endpoint%' OR n.name LIKE '%route%')
          AND n.file_path IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM nodes doc
              WHERE doc.file_path = n.file_path
                AND doc.properties::TEXT LIKE '%docstring%'
          )
          {}
        LIMIT 50
    "#,
        path_filter
    );

    let mut stmt = conn.prepare(&query)?;
    let mut rows = stmt.query([])?;

    while let Some(row) = rows.next()? {
        let func_name: String = row.get(0)?;
        let file_path: String = row.get(1)?;

        issues.push(VibeIssue {
            file: file_path,
            category: "api".to_string(),
            message: format!("API function '{}' lacks documentation", func_name),
            suggestion: Some("Add docstring with parameters and return type".to_string()),
        });
    }

    Ok(issues)
}

/// Check async/await patterns
fn check_async_patterns(conn: &Connection, path: &str) -> Result<Vec<VibeIssue>> {
    let mut issues = Vec::new();

    let path_filter = path_filter_clause(path, "n.file_path");
    let query = format!(
        r#"
        SELECT n.name, n.file_path
        FROM nodes n
        WHERE n.type = 'function'
          AND n.file_path IS NOT NULL
          AND (n.name LIKE '%async%' OR n.properties::TEXT LIKE '%async%')
          AND n.file_path NOT LIKE '%test%'
          {}
        LIMIT 50
    "#,
        path_filter
    );

    let mut stmt = conn.prepare(&query)?;
    let mut rows = stmt.query([])?;

    while let Some(row) = rows.next()? {
        let func_name: String = row.get(0)?;
        let file_path: String = row.get(1)?;

        if func_name.contains("async")
            && !func_name.starts_with("async_")
            && !func_name.ends_with("_async")
        {
            issues.push(VibeIssue {
                file: file_path,
                category: "async".to_string(),
                message: format!(
                    "Async function '{}' should follow async naming convention",
                    func_name
                ),
                suggestion: Some("Prefix with 'async_' or suffix with '_async'".to_string()),
            });
        }
    }

    Ok(issues)
}

/// Run the vibe command - pattern conformance with personality
///
/// # Arguments
/// * `path` - Path to check
/// * `format` - Output format (table, json, etc.)
/// * `convention_override` - Optional convention to use for all entities (overrides language detection)
pub async fn run(
    path: &str,
    format: OutputFormat,
    convention_override: Option<&str>,
) -> anyhow::Result<()> {
    // Parse convention override if provided
    let convention = convention_override
        .map(|s| {
            s.parse::<NamingConvention>()
                .map_err(|e| anyhow::anyhow!(e))
        })
        .transpose()?;

    let db_path = match find_mubase(path) {
        Ok(p) => p,
        Err(_) => {
            let result = VibeResult {
                path: path.to_string(),
                files_checked: 0,
                patterns_detected: 0,
                issues: vec![],
            };

            match format {
                OutputFormat::Json => {
                    println!("{}", serde_json::to_string_pretty(&result)?);
                }
                _ => {
                    print_vibe_output(&result, convention);
                }
            }
            return Ok(());
        }
    };

    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    let mut all_issues = Vec::new();
    let mut patterns_checked = 0;

    let nodes = load_nodes_from_path(&conn, path)?;
    let files_checked = count_unique_files(&nodes);

    patterns_checked += 1;
    let naming_issues = check_naming_conventions(&nodes, convention);
    all_issues.extend(naming_issues);

    patterns_checked += 1;
    let circular_issues = check_circular_imports(&conn, path)?;
    all_issues.extend(circular_issues);

    patterns_checked += 1;
    let test_issues = check_test_coverage(&conn, path)?;
    all_issues.extend(test_issues);

    patterns_checked += 1;
    let import_issues = check_imports(&conn, path)?;
    all_issues.extend(import_issues);

    patterns_checked += 1;
    let api_issues = check_api_patterns(&conn, path)?;
    all_issues.extend(api_issues);

    patterns_checked += 1;
    let async_issues = check_async_patterns(&conn, path)?;
    all_issues.extend(async_issues);

    let result = VibeResult {
        path: path.to_string(),
        files_checked,
        patterns_detected: patterns_checked,
        issues: all_issues,
    };

    match format {
        OutputFormat::Json => {
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
        _ => {
            print_vibe_output(&result, convention);
        }
    }

    Ok(())
}

/// Load nodes from database based on path filter
fn load_nodes_from_path(conn: &Connection, path: &str) -> Result<Vec<NodeData>> {
    let mut nodes = Vec::new();

    let query = if path == "." {
        "SELECT id, type, name, file_path FROM nodes WHERE file_path IS NOT NULL".to_string()
    } else {
        format!(
            "SELECT id, type, name, file_path FROM nodes WHERE file_path IS NOT NULL AND file_path LIKE '%{}%'",
            path.replace("'", "''")
        )
    };

    let mut stmt = conn.prepare(&query)?;
    let mut rows = stmt.query([])?;

    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        let node_type: String = row.get(1)?;
        let name: String = row.get(2)?;
        let file_path: Option<String> = row.get(3)?;

        nodes.push(NodeData {
            id,
            node_type,
            name,
            file_path,
        });
    }

    Ok(nodes)
}

/// Count unique files in node list
fn count_unique_files(nodes: &[NodeData]) -> usize {
    let mut files = HashSet::new();
    for node in nodes {
        if let Some(file_path) = &node.file_path {
            files.insert(file_path.clone());
        }
    }
    files.len()
}

/// Extract file path from node ID
fn get_file_from_node_id(node_id: &str) -> Option<String> {
    if let Some(colon_pos) = node_id.find(':') {
        let file_part = &node_id[colon_pos + 1..];
        if let Some(second_colon) = file_part.find(':') {
            return Some(file_part[..second_colon].to_string());
        }
        return Some(file_part.to_string());
    }
    None
}

/// Generate SQL path filter clause for a given path and column
fn path_filter_clause(path: &str, column: &str) -> String {
    if path == "." {
        String::new()
    } else {
        format!(" AND {} LIKE '%{}%'", column, path.replace("'", "''"))
    }
}

// Note: is_snake_case, is_pascal_case, is_dunder, to_snake_case, to_pascal_case
// are now imported from super::conventions module for language-aware naming checks.

/// Infer test file path from source file path (language-aware)
fn infer_test_path(file_path: &str) -> String {
    use super::conventions::detect_language;

    let language = detect_language(file_path);
    let file_name = file_path.split('/').next_back().unwrap_or(file_path);

    match language {
        // C#: tests/{Project}.Tests/{ClassName}Tests.cs
        "csharp" => {
            // Extract project name from path like src/ProjectName/Services/Foo.cs
            let parts: Vec<&str> = file_path.split('/').collect();
            let project_name = parts
                .iter()
                .find(|p| !p.is_empty() && **p != "src" && !p.contains('.'))
                .unwrap_or(&"Project");
            let test_file = file_name.replace(".cs", "Tests.cs");
            format!("tests/{}.Tests/{}", project_name, test_file)
        }

        // TypeScript/JavaScript: __tests__/filename.test.ts or filename.spec.ts
        "typescript" | "javascript" => {
            let ext = if language == "typescript" { "ts" } else { "js" };
            let base_name = file_name
                .strip_suffix(".ts")
                .or_else(|| file_name.strip_suffix(".tsx"))
                .or_else(|| file_name.strip_suffix(".js"))
                .or_else(|| file_name.strip_suffix(".jsx"))
                .unwrap_or(file_name);
            format!("__tests__/{}.test.{}", base_name, ext)
        }

        // Go: same directory, _test.go suffix
        "go" => {
            let base_name = file_name.strip_suffix(".go").unwrap_or(file_name);
            let dir = file_path.rsplit_once('/').map(|(d, _)| d).unwrap_or(".");
            format!("{}/{}_test.go", dir, base_name)
        }

        // Rust: tests/ directory or #[test] in same file
        "rust" => {
            let base_name = file_name.strip_suffix(".rs").unwrap_or(file_name);
            format!("tests/{}_test.rs", base_name)
        }

        // Java: src/test/java/... mirror structure
        "java" => {
            if file_path.contains("src/main/java/") {
                let test_path = file_path.replace("src/main/java/", "src/test/java/");
                test_path.replace(".java", "Test.java")
            } else {
                let base_name = file_name.strip_suffix(".java").unwrap_or(file_name);
                format!("src/test/java/{}Test.java", base_name)
            }
        }

        // Python (and default): tests/test_filename.py
        _ => {
            if file_path.contains("src/") {
                file_path.replace("src/", "tests/test_")
            } else {
                format!("tests/test_{}", file_name)
            }
        }
    }
}

fn print_vibe_output(result: &VibeResult, convention_override: Option<NamingConvention>) {
    println!();
    println!("{} {}", "Vibe Check:".magenta().bold(), result.path.bold());

    // Show convention override if specified
    if let Some(conv) = convention_override {
        println!("{}", format!("Convention override: {}", conv).cyan());
    }

    println!();

    if result.files_checked == 0 {
        println!(
            "{}",
            "No MU database found. Run 'mu bootstrap' first.".yellow()
        );
        println!();
        println!(
            "{}",
            "Once indexed, I'll check if your code matches the codebase vibe.".dimmed()
        );
        println!();
        println!("{}", "Pattern Categories:".cyan());
        println!(
            "  {} naming       - Naming conventions (language-aware)",
            "*".dimmed()
        );
        println!("  {} architecture - Architectural patterns", "*".dimmed());
        println!("  {} testing      - Test patterns", "*".dimmed());
        println!("  {} imports      - Import organization", "*".dimmed());
        println!("  {} api          - API patterns", "*".dimmed());
        println!("  {} async        - Async patterns", "*".dimmed());
        println!();
        println!("{}", "Usage:".cyan());
        println!(
            "  {} mu vibe                       # Check uncommitted changes",
            "$".dimmed()
        );
        println!(
            "  {} mu vibe --staged              # Check staged changes",
            "$".dimmed()
        );
        println!(
            "  {} mu vibe src/new.py            # Check specific file",
            "$".dimmed()
        );
        println!(
            "  {} mu vibe --convention snake    # Force snake_case convention",
            "$".dimmed()
        );
        println!(
            "  {} mu vibe --convention pascal   # Force PascalCase convention",
            "$".dimmed()
        );
        println!(
            "  {} mu vibe -c naming             # Only check naming",
            "$".dimmed()
        );
        println!(
            "  {} mu vibe --strict              # Exit 1 on issues (CI)",
            "$".dimmed()
        );
        println!();
        println!("{}", "Supported Conventions:".cyan());
        println!(
            "  {} snake        - snake_case (Python, Rust functions)",
            "*".dimmed()
        );
        println!(
            "  {} pascal       - PascalCase (C# methods, most classes)",
            "*".dimmed()
        );
        println!(
            "  {} camel        - camelCase (JavaScript, Java methods)",
            "*".dimmed()
        );
        println!(
            "  {} screaming    - SCREAMING_SNAKE_CASE (constants)",
            "*".dimmed()
        );
    } else if result.is_immaculate() {
        println!(
            "{}",
            "[OK] All good. The vibe is immaculate.".green().bold()
        );
        println!();
        println!(
            "{}",
            format!(
                "Checked {} files against {} patterns",
                result.files_checked, result.patterns_detected
            )
            .dimmed()
        );
    } else {
        println!(
            "{}",
            format!("{} issues found", result.issues.len()).red().bold()
        );
        println!();

        for issue in &result.issues {
            println!(
                "{} {} {}",
                "X".red(),
                format!("[{}]", issue.category).cyan(),
                issue.message
            );
            println!("  {}", issue.file.dimmed());
            if let Some(suggestion) = &issue.suggestion {
                println!("  {} {}", "->".green(), suggestion);
            }
            println!();
        }

        println!("{}", "The vibe is... off.".dimmed());
    }

    println!();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_path_filter_clause_root() {
        // "." should return empty string (no filter)
        let result = path_filter_clause(".", "file_path");
        assert_eq!(result, "");
    }

    #[test]
    fn test_path_filter_clause_specific() {
        // Specific path should return LIKE clause
        let result = path_filter_clause("src/hooks/useAuth.ts", "file_path");
        assert_eq!(result, " AND file_path LIKE '%src/hooks/useAuth.ts%'");

        // Test with different column name
        let result = path_filter_clause("src/hooks", "n.file_path");
        assert_eq!(result, " AND n.file_path LIKE '%src/hooks%'");
    }

    #[test]
    fn test_path_filter_escapes_quotes() {
        // Single quotes should be escaped to prevent SQL injection
        let result = path_filter_clause("path'with'quotes", "file_path");
        assert_eq!(result, " AND file_path LIKE '%path''with''quotes%'");

        // Test with single quote at end
        let result = path_filter_clause("test'", "col");
        assert_eq!(result, " AND col LIKE '%test''%'");
    }

    // ========================================================================
    // Language-Aware Test Path Inference Tests
    // ========================================================================

    #[test]
    fn test_infer_test_path_csharp() {
        // C# should use {Project}.Tests directory structure
        assert_eq!(
            infer_test_path("src/dominaite-gateway-api/Services/TransactionService.cs"),
            "tests/dominaite-gateway-api.Tests/TransactionServiceTests.cs"
        );
        assert_eq!(
            infer_test_path("src/MyProject/Controllers/UserController.cs"),
            "tests/MyProject.Tests/UserControllerTests.cs"
        );
    }

    #[test]
    fn test_infer_test_path_typescript() {
        // TypeScript should use __tests__/filename.test.ts
        assert_eq!(
            infer_test_path("src/hooks/useAuth.ts"),
            "__tests__/useAuth.test.ts"
        );
        assert_eq!(
            infer_test_path("src/components/Button.tsx"),
            "__tests__/Button.test.ts"
        );
    }

    #[test]
    fn test_infer_test_path_javascript() {
        // JavaScript should use __tests__/filename.test.js
        assert_eq!(
            infer_test_path("src/utils/helpers.js"),
            "__tests__/helpers.test.js"
        );
    }

    #[test]
    fn test_infer_test_path_go() {
        // Go should use same directory with _test.go suffix
        assert_eq!(
            infer_test_path("pkg/handlers/user.go"),
            "pkg/handlers/user_test.go"
        );
        assert_eq!(
            infer_test_path("internal/service/auth.go"),
            "internal/service/auth_test.go"
        );
    }

    #[test]
    fn test_infer_test_path_rust() {
        // Rust should use tests/ directory
        assert_eq!(infer_test_path("src/lib.rs"), "tests/lib_test.rs");
        assert_eq!(
            infer_test_path("src/parser/lexer.rs"),
            "tests/lexer_test.rs"
        );
    }

    #[test]
    fn test_infer_test_path_java() {
        // Java should mirror src/main/java to src/test/java
        assert_eq!(
            infer_test_path("src/main/java/com/example/UserService.java"),
            "src/test/java/com/example/UserServiceTest.java"
        );
        // Fallback for non-standard structure
        assert_eq!(
            infer_test_path("src/UserService.java"),
            "src/test/java/UserServiceTest.java"
        );
    }

    #[test]
    fn test_infer_test_path_python() {
        // Python should use tests/test_filename.py
        assert_eq!(
            infer_test_path("src/services/user_service.py"),
            "tests/test_services/user_service.py"
        );
        assert_eq!(
            infer_test_path("utils/helpers.py"),
            "tests/test_helpers.py"
        );
    }
}
