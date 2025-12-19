//! Deps command - Show dependencies of a node
//!
//! Analyzes the dependency graph to show what a node depends on (ancestors)
//! or what depends on it (dependents/reverse).

use crate::output::{Output, OutputFormat, TableDisplay};
use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::{params, Connection};
use serde::Serialize;
use std::collections::{HashSet, VecDeque};
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

/// Dependency information for a node
#[derive(Debug, Serialize)]
pub struct DependencyInfo {
    /// The node being analyzed
    pub node_id: String,
    /// Node name (human readable)
    pub node_name: String,
    /// Direction of analysis
    pub direction: String,
    /// Depth of traversal
    pub depth: u8,
    /// Dependencies found
    pub dependencies: Vec<DependencyNode>,
    /// Total count
    pub total_count: usize,
}

/// A single dependency node
#[derive(Debug, Serialize, Clone)]
pub struct DependencyNode {
    /// Node ID
    pub id: String,
    /// Node name
    pub name: String,
    /// Node type (module, class, function)
    pub node_type: String,
    /// Edge type that created this dependency
    pub edge_type: String,
    /// Depth at which this was found
    pub depth: u8,
    /// File path if available
    pub file_path: Option<String>,
}

impl TableDisplay for DependencyInfo {
    fn to_table(&self) -> String {
        let mut output = String::new();

        // Header
        let direction_label = if self.direction == "outgoing" {
            "Dependencies of"
        } else {
            "Dependents of"
        };
        output.push_str(&format!(
            "{} {} (depth: {})\n",
            direction_label.bold(),
            self.node_name.cyan(),
            self.depth
        ));
        output.push_str(&format!("{}\n", "-".repeat(60)));

        if self.dependencies.is_empty() {
            output.push_str(&"  No dependencies found.\n".dimmed().to_string());
        } else {
            // Group by depth
            let max_depth = self.dependencies.iter().map(|d| d.depth).max().unwrap_or(0);

            for d in 1..=max_depth {
                let at_depth: Vec<_> = self
                    .dependencies
                    .iter()
                    .filter(|dep| dep.depth == d)
                    .collect();
                if !at_depth.is_empty() {
                    output.push_str(&format!("\n  {} Depth {}:\n", "->".dimmed(), d));
                    for dep in at_depth {
                        let type_badge = match dep.node_type.as_str() {
                            "module" => "[mod]".blue(),
                            "class" => "[cls]".yellow(),
                            "function" => "[fn]".green(),
                            _ => format!("[{}]", dep.node_type).normal(),
                        };
                        let edge_info = format!("({})", dep.edge_type).dimmed();
                        output.push_str(&format!(
                            "     {} {} {} {}\n",
                            type_badge,
                            dep.name,
                            edge_info,
                            dep.file_path.as_deref().unwrap_or("").dimmed()
                        ));
                    }
                }
            }
        }

        output.push_str(&format!("\n{}: {}\n", "Total".bold(), self.total_count));
        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();
        let sigil = if self.direction == "outgoing" {
            "deps"
        } else {
            "dependents"
        };
        output.push_str(&format!(
            ":: {} {} depth={}\n",
            sigil, self.node_id, self.depth
        ));

        for dep in &self.dependencies {
            let prefix = "  ".repeat(dep.depth as usize);
            output.push_str(&format!(
                "{}- {} [{}] via:{}\n",
                prefix, dep.id, dep.node_type, dep.edge_type
            ));
        }

        output.push_str(&format!("# total: {}\n", self.total_count));
        output
    }
}

/// Find the parent module for a class or function node.
/// Classes and functions don't have direct `imports` edges - those are on the module.
/// Returns the module ID if found.
fn find_parent_module(conn: &Connection, node_id: &str) -> Option<String> {
    // Only look for parent module for class (cls:) or function (fn:) nodes
    if !node_id.starts_with("cls:") && !node_id.starts_with("fn:") {
        return None;
    }

    // Extract the file path from the node ID
    // Format: cls:src/path/file.cs:ClassName or fn:src/path/file.rs:func_name
    let parts: Vec<&str> = node_id.splitn(2, ':').collect();
    if parts.len() < 2 {
        return None;
    }

    let rest = parts[1];
    // Split by ':' again to get file path (before the class/function name)
    let file_path = if let Some(idx) = rest.rfind(':') {
        &rest[..idx]
    } else {
        rest
    };

    // Look for the module node with this file path
    let module_id = format!("mod:{}", file_path);

    // Verify the module exists
    let query = "SELECT id FROM nodes WHERE id = ? LIMIT 1";
    let mut stmt = conn.prepare(query).ok()?;
    let mut rows = stmt.query(params![&module_id]).ok()?;

    if rows.next().ok()?.is_some() {
        Some(module_id)
    } else {
        None
    }
}

/// Load nodes and edges from the database and perform BFS traversal
fn find_dependencies(
    conn: &Connection,
    node_id: &str,
    reverse: bool,
    max_depth: u8,
    include_contains: bool,
) -> Result<Vec<DependencyNode>> {
    let mut visited: HashSet<String> = HashSet::new();
    let mut result: Vec<DependencyNode> = Vec::new();
    let mut queue: VecDeque<(String, u8)> = VecDeque::new();

    // Start with the given node
    visited.insert(node_id.to_string());
    queue.push_back((node_id.to_string(), 0));

    // For class/function nodes (outgoing direction), also include parent module's imports
    // since classes don't have direct import edges - those are on the module
    if !reverse {
        if let Some(module_id) = find_parent_module(conn, node_id) {
            if !visited.contains(&module_id) {
                // Don't add the module itself, but queue it for edge traversal
                // This allows finding module-level imports
                queue.push_back((module_id.clone(), 0));
                visited.insert(module_id);
            }
        }
    }

    // By default, exclude 'contains' edges which represent structural containment
    // (e.g., module contains class, class contains function) rather than actual dependencies.
    // Use --include-contains to see these edges.
    let contains_filter = if include_contains {
        ""
    } else {
        " AND e.type != 'contains'"
    };

    // Prepare query based on direction
    // reverse=false: what does this node depend on (follow outgoing edges: source -> target)
    // reverse=true: what depends on this node (follow incoming edges: target <- source)
    let edge_query = if reverse {
        // Find nodes that point TO this node (dependents)
        format!(
            "SELECT e.source_id, e.type, n.name, n.type as node_type, n.file_path
             FROM edges e
             JOIN nodes n ON n.id = e.source_id
             WHERE e.target_id = ?{}",
            contains_filter
        )
    } else {
        // Find nodes that this node points TO (dependencies)
        format!(
            "SELECT e.target_id, e.type, n.name, n.type as node_type, n.file_path
             FROM edges e
             JOIN nodes n ON n.id = e.target_id
             WHERE e.source_id = ?{}",
            contains_filter
        )
    };

    while let Some((current_id, current_depth)) = queue.pop_front() {
        if current_depth >= max_depth {
            continue;
        }

        let mut stmt = conn.prepare(&edge_query)?;
        let mut rows = stmt.query(params![current_id])?;

        while let Some(row) = rows.next()? {
            let neighbor_id: String = row.get(0)?;
            let edge_type: String = row.get(1)?;
            let name: String = row.get(2)?;
            let node_type: String = row.get(3)?;
            let file_path: Option<String> = row.get(4)?;

            if !visited.contains(&neighbor_id) {
                visited.insert(neighbor_id.clone());

                let dep = DependencyNode {
                    id: neighbor_id.clone(),
                    name,
                    node_type,
                    edge_type,
                    depth: current_depth + 1,
                    file_path,
                };
                result.push(dep);

                queue.push_back((neighbor_id, current_depth + 1));
            }
        }
    }

    // Sort by depth, then by name
    result.sort_by(|a, b| a.depth.cmp(&b.depth).then(a.name.cmp(&b.name)));

    Ok(result)
}

/// Run the deps command
pub async fn run(
    node: &str,
    reverse: bool,
    depth: u8,
    include_contains: bool,
    format: OutputFormat,
) -> Result<()> {
    // Validate node name is not empty or whitespace-only
    if node.trim().is_empty() {
        return Err(anyhow::anyhow!("Node name cannot be empty"));
    }

    run_direct(node, reverse, depth, include_contains, format).await
}

/// Run deps command with direct database access
async fn run_direct(
    node: &str,
    reverse: bool,
    depth: u8,
    include_contains: bool,
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

    // Try to resolve the node ID if it's a partial match
    let node_id = resolve_node_id(&conn, node)?;

    // Get node info for display
    let node_info = get_node_info(&conn, &node_id)?;

    // Find dependencies
    let dependencies = find_dependencies(&conn, &node_id, reverse, depth, include_contains)?;

    let info = DependencyInfo {
        node_id: node_id.clone(),
        node_name: node_info.0,
        direction: if reverse { "incoming" } else { "outgoing" }.to_string(),
        depth,
        total_count: dependencies.len(),
        dependencies,
    };

    Output::new(info, format).render()
}

/// Try to resolve a partial node ID to a full node ID using fuzzy matching
fn resolve_node_id(conn: &Connection, query: &str) -> Result<String> {
    // 1. Try exact match on id or name first
    let mut stmt = conn.prepare("SELECT id FROM nodes WHERE id = ?1 OR name = ?1")?;
    let mut rows = stmt.query(params![query])?;
    if let Some(row) = rows.next()? {
        return Ok(row.get(0)?);
    }

    // 2. Try fuzzy match on both name and id (case-insensitive)
    let pattern = format!("%{}%", query.to_lowercase());
    let mut stmt = conn.prepare(
        "SELECT id, name, type FROM nodes WHERE LOWER(name) LIKE ?1 OR LOWER(id) LIKE ?1 LIMIT 10",
    )?;
    let mut rows = stmt.query(params![pattern])?;

    let mut matches: Vec<(String, String, String)> = Vec::new();
    while let Some(row) = rows.next()? {
        let id: String = row.get(0)?;
        let name: String = row.get(1)?;
        let node_type: String = row.get(2)?;
        matches.push((id, name, node_type));
    }

    match matches.len() {
        0 => Err(anyhow::anyhow!("Node not found: {}", query)),
        // Safe: len() == 1 guarantees next() returns Some
        1 => Ok(matches.into_iter().next().expect("len is 1").0),
        _ => {
            // Sort matches by type priority (class > module > function) then by name
            let mut matches = matches;
            matches.sort_by(|a, b| {
                let type_priority = |t: &str| match t {
                    "class" => 0,
                    "module" => 1,
                    "function" => 2,
                    _ => 3,
                };
                type_priority(&a.2)
                    .cmp(&type_priority(&b.2))
                    .then_with(|| a.1.cmp(&b.1))
            });

            // Multiple matches - show sorted suggestions
            let suggestions: Vec<String> = matches
                .iter()
                .map(|(id, name, typ)| format!("  {} [{}] {}", name, typ, id))
                .collect();
            Err(anyhow::anyhow!(
                "Multiple nodes match '{}'. Be more specific:\n{}",
                query,
                suggestions.join("\n")
            ))
        }
    }
}

/// Get node name and type for display
fn get_node_info(conn: &Connection, node_id: &str) -> Result<(String, String)> {
    let mut stmt = conn.prepare("SELECT name, type FROM nodes WHERE id = ?")?;
    let mut rows = stmt.query(params![node_id])?;

    if let Some(row) = rows.next()? {
        let name: String = row.get(0)?;
        let node_type: String = row.get(1)?;
        Ok((name, node_type))
    } else {
        Ok((node_id.to_string(), "unknown".to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn create_test_db() -> (Connection, PathBuf) {
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("test.mubase");
        let conn = Connection::open(&db_path).unwrap();

        // Create schema
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS nodes (
                id VARCHAR PRIMARY KEY,
                type VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                qualified_name VARCHAR,
                file_path VARCHAR,
                line_start INTEGER,
                line_end INTEGER,
                properties JSON,
                complexity INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS edges (
                id VARCHAR PRIMARY KEY,
                source_id VARCHAR NOT NULL,
                target_id VARCHAR NOT NULL,
                type VARCHAR NOT NULL,
                properties JSON
            );
            "#,
        )
        .unwrap();

        // Insert test data
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params!["mod:src/a.py", "module", "a", "src/a.py"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params!["mod:src/b.py", "module", "b", "src/b.py"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params!["mod:src/c.py", "module", "c", "src/c.py"],
        )
        .unwrap();

        // a imports b, b imports c
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            params!["e1", "mod:src/a.py", "mod:src/b.py", "imports"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            params!["e2", "mod:src/b.py", "mod:src/c.py", "imports"],
        )
        .unwrap();

        std::mem::forget(dir); // Keep dir alive
        (conn, db_path)
    }

    #[test]
    fn test_find_dependencies_outgoing() {
        let (conn, _) = create_test_db();

        // include_contains=false by default (excludes 'contains' edges)
        let deps = find_dependencies(&conn, "mod:src/a.py", false, 2, false).unwrap();

        assert_eq!(deps.len(), 2);
        assert!(deps.iter().any(|d| d.id == "mod:src/b.py" && d.depth == 1));
        assert!(deps.iter().any(|d| d.id == "mod:src/c.py" && d.depth == 2));
    }

    #[test]
    fn test_find_dependencies_reverse() {
        let (conn, _) = create_test_db();

        // include_contains=false by default (excludes 'contains' edges)
        let deps = find_dependencies(&conn, "mod:src/c.py", true, 2, false).unwrap();

        assert_eq!(deps.len(), 2);
        assert!(deps.iter().any(|d| d.id == "mod:src/b.py" && d.depth == 1));
        assert!(deps.iter().any(|d| d.id == "mod:src/a.py" && d.depth == 2));
    }

    #[test]
    fn test_depth_limiting() {
        let (conn, _) = create_test_db();

        // include_contains=false by default (excludes 'contains' edges)
        let deps = find_dependencies(&conn, "mod:src/a.py", false, 1, false).unwrap();

        assert_eq!(deps.len(), 1);
        assert!(deps.iter().any(|d| d.id == "mod:src/b.py"));
    }

    #[test]
    fn test_contains_edges_excluded_by_default() {
        let (conn, _) = create_test_db();

        // Add a contains edge: module a contains class Foo
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params!["cls:src/a.py::Foo", "class", "Foo", "src/a.py"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            params!["e3", "mod:src/a.py", "cls:src/a.py::Foo", "contains"],
        )
        .unwrap();

        // With include_contains=false, should NOT include the contains edge
        let deps = find_dependencies(&conn, "mod:src/a.py", false, 2, false).unwrap();
        assert!(!deps.iter().any(|d| d.id == "cls:src/a.py::Foo"));
        assert_eq!(deps.len(), 2); // Only b and c via imports

        // With include_contains=true, SHOULD include the contains edge
        let deps = find_dependencies(&conn, "mod:src/a.py", false, 2, true).unwrap();
        assert!(deps.iter().any(|d| d.id == "cls:src/a.py::Foo"));
        assert_eq!(deps.len(), 3); // b, c via imports, Foo via contains
    }

    #[tokio::test]
    async fn test_empty_node_name_rejected() {
        use crate::output::OutputFormat;

        // Empty string should fail
        let result = super::run("", false, 1, false, OutputFormat::Table).await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Node name cannot be empty"));

        // Whitespace-only should fail
        let result = super::run("   ", false, 1, false, OutputFormat::Table).await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Node name cannot be empty"));
    }

    #[test]
    fn test_resolve_node_id_exact_match_by_id() {
        let (conn, _) = create_test_db();

        // Exact match by id should work
        let result = resolve_node_id(&conn, "mod:src/a.py").unwrap();
        assert_eq!(result, "mod:src/a.py");
    }

    #[test]
    fn test_resolve_node_id_exact_match_by_name() {
        let (conn, _) = create_test_db();

        // Exact match by name should work
        let result = resolve_node_id(&conn, "a").unwrap();
        assert_eq!(result, "mod:src/a.py");
    }

    #[test]
    fn test_resolve_node_id_fuzzy_match_single() {
        let (conn, _) = create_test_db();

        // Add a node with a unique name
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params![
                "cls:src/services/UserService.ts",
                "class",
                "UserService",
                "src/services/UserService.ts"
            ],
        )
        .unwrap();

        // Fuzzy match should find the single result
        let result = resolve_node_id(&conn, "UserServ").unwrap();
        assert_eq!(result, "cls:src/services/UserService.ts");
    }

    #[test]
    fn test_resolve_node_id_fuzzy_match_case_insensitive() {
        let (conn, _) = create_test_db();

        // Add a node with a unique name
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params![
                "cls:src/auth/AuthManager.ts",
                "class",
                "AuthManager",
                "src/auth/AuthManager.ts"
            ],
        )
        .unwrap();

        // Case-insensitive fuzzy match should work
        let result = resolve_node_id(&conn, "authman").unwrap();
        assert_eq!(result, "cls:src/auth/AuthManager.ts");
    }

    #[test]
    fn test_resolve_node_id_multiple_matches_error() {
        let (conn, _) = create_test_db();

        // Add nodes with similar names
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params![
                "cls:src/UserService.ts",
                "class",
                "UserService",
                "src/UserService.ts"
            ],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params![
                "cls:src/UserController.ts",
                "class",
                "UserController",
                "src/UserController.ts"
            ],
        )
        .unwrap();

        // Multiple matches should return an error with suggestions
        let result = resolve_node_id(&conn, "User");
        assert!(result.is_err());
        let err_msg = result.unwrap_err().to_string();
        assert!(err_msg.contains("Multiple nodes match"));
        assert!(err_msg.contains("UserService"));
        assert!(err_msg.contains("UserController"));
    }

    #[test]
    fn test_resolve_node_id_no_match() {
        let (conn, _) = create_test_db();

        // No match should return an error
        let result = resolve_node_id(&conn, "NonExistent");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Node not found"));
    }
}
