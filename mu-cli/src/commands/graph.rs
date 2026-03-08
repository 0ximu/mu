//! Graph command - Graph analysis operations
//!
//! Provides graph-based analysis commands:
//! - `mu impact <node>` - Find downstream impact (what might break if this changes)

use crate::mubase;
use crate::output::{Output, OutputFormat, TableDisplay};
use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::{params, Connection};
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::visit::EdgeRef;
use petgraph::Direction;
use serde::Serialize;
use std::collections::{HashMap, HashSet, VecDeque};

/// Open database connection in read-only mode.
pub fn open_db() -> Result<Connection> {
    let db_path = mubase::find_mubase(".")?;
    Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))
}

/// In-memory graph structure for fast traversal
pub struct GraphData {
    graph: DiGraph<String, String>,
    node_map: HashMap<String, NodeIndex>,
    reverse_map: HashMap<NodeIndex, String>,
    node_info: HashMap<String, NodeInfo>,
}

#[derive(Debug, Clone)]
pub struct NodeInfo {
    pub name: String,
    pub node_type: String,
    pub file_path: Option<String>,
}

impl GraphData {
    /// Load graph from database
    pub fn from_db(conn: &Connection) -> Result<Self> {
        let mut graph = DiGraph::new();
        let mut node_map = HashMap::new();
        let mut reverse_map = HashMap::new();
        let mut node_info = HashMap::new();

        // Load all nodes
        let mut stmt = conn.prepare("SELECT id, name, type, file_path FROM nodes")?;
        let mut rows = stmt.query([])?;

        while let Some(row) = rows.next()? {
            let id: String = row.get(0)?;
            let name: String = row.get(1)?;
            let node_type: String = row.get(2)?;
            let file_path: Option<String> = row.get(3)?;

            let idx = graph.add_node(id.clone());
            node_map.insert(id.clone(), idx);
            reverse_map.insert(idx, id.clone());
            node_info.insert(
                id,
                NodeInfo {
                    name,
                    node_type,
                    file_path,
                },
            );
        }

        // Load all edges
        let mut stmt = conn.prepare("SELECT source_id, target_id, type FROM edges")?;
        let mut rows = stmt.query([])?;

        while let Some(row) = rows.next()? {
            let source: String = row.get(0)?;
            let target: String = row.get(1)?;
            let edge_type: String = row.get(2)?;

            if let (Some(&s), Some(&t)) = (node_map.get(&source), node_map.get(&target)) {
                graph.add_edge(s, t, edge_type);
            }
        }

        Ok(Self {
            graph,
            node_map,
            reverse_map,
            node_info,
        })
    }

    /// Find impact (downstream reachable nodes)
    pub fn impact(
        &self,
        node_id: &str,
        edge_types: Option<&[String]>,
        max_depth: Option<u8>,
    ) -> Vec<String> {
        self.traverse_bfs(node_id, Direction::Outgoing, edge_types, max_depth)
    }

    /// BFS traversal in a given direction with optional depth limit
    fn traverse_bfs(
        &self,
        node_id: &str,
        direction: Direction,
        edge_types: Option<&[String]>,
        max_depth: Option<u8>,
    ) -> Vec<String> {
        let start = match self.node_map.get(node_id) {
            Some(&idx) => idx,
            None => return vec![],
        };

        let allowed: Option<HashSet<&String>> = edge_types.map(|t| t.iter().collect());

        let mut visited: HashSet<NodeIndex> = HashSet::new();
        let mut result = Vec::new();
        let mut queue: VecDeque<(NodeIndex, u8)> = VecDeque::new();

        visited.insert(start);
        queue.push_back((start, 0));

        while let Some((current, depth)) = queue.pop_front() {
            // Skip if we've exceeded max depth
            if let Some(max) = max_depth {
                if depth >= max {
                    continue;
                }
            }

            for edge in self.graph.edges_directed(current, direction) {
                if let Some(ref allowed_types) = allowed {
                    if !allowed_types.contains(edge.weight()) {
                        continue;
                    }
                }

                let neighbor = if direction == Direction::Outgoing {
                    edge.target()
                } else {
                    edge.source()
                };

                if !visited.contains(&neighbor) {
                    visited.insert(neighbor);
                    result.push(self.reverse_map[&neighbor].clone());
                    queue.push_back((neighbor, depth + 1));
                }
            }
        }

        result
    }

    /// Get node info for a given ID
    pub fn get_info(&self, node_id: &str) -> Option<&NodeInfo> {
        self.node_info.get(node_id)
    }

    /// Check if node exists
    pub fn has_node(&self, node_id: &str) -> bool {
        self.node_map.contains_key(node_id)
    }

    /// Get node count
    #[allow(dead_code)]
    pub fn node_count(&self) -> usize {
        self.graph.node_count()
    }

    /// Get edge count
    #[allow(dead_code)]
    pub fn edge_count(&self) -> usize {
        self.graph.edge_count()
    }
}

// ============== Output Types ==============

/// Impact analysis result
#[derive(Debug, Serialize)]
pub struct ImpactResult {
    pub node_id: String,
    pub node_name: String,
    pub direction: String,
    pub affected_nodes: Vec<AffectedNode>,
    pub total_count: usize,
}

#[derive(Debug, Serialize)]
pub struct AffectedNode {
    pub id: String,
    pub name: String,
    pub node_type: String,
    pub file_path: Option<String>,
}

impl TableDisplay for ImpactResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        let label = if self.direction == "downstream" {
            format!("{} {}", "Impact of changing".bold(), self.node_name.cyan())
        } else {
            format!("{} {}", "Ancestors of".bold(), self.node_name.cyan())
        };
        output.push_str(&format!("{}\n", label));
        output.push_str(&format!("{}\n", "-".repeat(60)));

        if self.affected_nodes.is_empty() {
            output.push_str(&"  No affected nodes found.\n".dimmed().to_string());
        } else {
            for node in &self.affected_nodes {
                let type_badge = match node.node_type.as_str() {
                    "module" => "[mod]".blue(),
                    "class" => "[cls]".yellow(),
                    "function" => "[fn]".green(),
                    "external" => "[ext]".magenta(),
                    _ => format!("[{}]", node.node_type).normal(),
                };
                let path_info = node
                    .file_path
                    .as_deref()
                    .map(|p| format!(" ({})", p).dimmed().to_string())
                    .unwrap_or_default();
                output.push_str(&format!("  {} {}{}\n", type_badge, node.name, path_info));
            }
        }

        output.push_str(&format!(
            "\n{}: {} nodes\n",
            "Total affected".bold(),
            self.total_count
        ));
        output
    }

}

// ============== Command Runners ==============

/// Run the impact command
pub async fn run_impact(
    node: &str,
    edge_types: Option<Vec<String>>,
    depth: Option<u8>,
    format: OutputFormat,
) -> Result<()> {
    let conn = open_db()?;
    let graph = GraphData::from_db(&conn)?;

    // Resolve node ID
    let node_id = resolve_node_id(&conn, node)?;

    if !graph.has_node(&node_id) {
        return Err(anyhow::anyhow!("Node not found: {}", node));
    }

    let affected_ids = graph.impact(&node_id, edge_types.as_deref(), depth);

    let affected_nodes: Vec<AffectedNode> = affected_ids
        .iter()
        .filter_map(|id| {
            graph.get_info(id).map(|info| AffectedNode {
                id: id.clone(),
                name: info.name.clone(),
                node_type: info.node_type.clone(),
                file_path: info.file_path.clone(),
            })
        })
        .collect();

    let node_info = graph.get_info(&node_id);
    let result = ImpactResult {
        node_id: node_id.clone(),
        node_name: node_info.map(|i| i.name.clone()).unwrap_or(node_id),
        direction: "downstream".to_string(),
        total_count: affected_nodes.len(),
        affected_nodes,
    };

    Output::new(result, format).render()
}

/// Try to resolve a partial node ID to a full node ID using fuzzy matching
pub fn resolve_node_id(conn: &Connection, query: &str) -> Result<String> {
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

            // Multiple matches - return error with sorted suggestions
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

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn create_test_db() -> Connection {
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("test.mubase");
        let conn = Connection::open(&db_path).unwrap();

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

        // Create a cycle: a -> b -> c -> a
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params!["mod:a", "module", "a", "a.py"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params!["mod:b", "module", "b", "b.py"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params!["mod:c", "module", "c", "c.py"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_path) VALUES (?, ?, ?, ?)",
            params!["mod:d", "module", "d", "d.py"],
        )
        .unwrap();

        // Cycle: a -> b -> c -> a
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            params!["e1", "mod:a", "mod:b", "imports"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            params!["e2", "mod:b", "mod:c", "imports"],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            params!["e3", "mod:c", "mod:a", "imports"],
        )
        .unwrap();

        // d is outside the cycle, b -> d
        conn.execute(
            "INSERT INTO edges (id, source_id, target_id, type) VALUES (?, ?, ?, ?)",
            params!["e4", "mod:b", "mod:d", "calls"],
        )
        .unwrap();

        std::mem::forget(dir);
        conn
    }

    #[test]
    fn test_impact() {
        let conn = create_test_db();
        let graph = GraphData::from_db(&conn).unwrap();

        let impact = graph.impact("mod:a", None, None);

        // a -> b, b -> c, c -> a (cycle), b -> d
        // So from a, we can reach b, c, d
        assert!(impact.contains(&"mod:b".to_string()));
        assert!(impact.contains(&"mod:c".to_string()));
        assert!(impact.contains(&"mod:d".to_string()));
    }

    #[test]
    fn test_edge_type_filtering() {
        let conn = create_test_db();
        let graph = GraphData::from_db(&conn).unwrap();

        // With only "imports", we shouldn't reach d (connected via "calls")
        let imports_only = vec!["imports".to_string()];
        let impact = graph.impact("mod:a", Some(&imports_only), None);

        assert!(impact.contains(&"mod:b".to_string()));
        assert!(impact.contains(&"mod:c".to_string()));
        assert!(!impact.contains(&"mod:d".to_string()));
    }
}
