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

    /// Load graph from a MUbase instance (acquires lock briefly).
    pub fn from_mubase(mubase: &crate::engine::storage::MUbase) -> Result<Self> {
        mubase.with_connection(Self::from_db)
    }

    /// Find reachable nodes via outgoing edges (transitive outgoing closure).
    /// Kept for API parity with `dependents`; not currently wired to the CLI,
    /// which uses `dependents` for true blast-radius semantics.
    #[allow(dead_code)]
    pub fn impact(
        &self,
        node_id: &str,
        edge_types: Option<&[String]>,
        max_depth: Option<u8>,
    ) -> Vec<String> {
        self.traverse_bfs(&[node_id], Direction::Outgoing, edge_types, max_depth)
    }

    /// Find dependents (upstream — who calls/uses this node, transitively)
    pub fn dependents(
        &self,
        node_id: &str,
        edge_types: Option<&[String]>,
        max_depth: Option<u8>,
    ) -> Vec<String> {
        self.traverse_bfs(&[node_id], Direction::Incoming, edge_types, max_depth)
    }

    /// Find dependents starting from multiple seed nodes (single shared BFS,
    /// so seeds and anything already visited are never reported as dependents).
    /// Used for class targets: a class's blast radius must include callers of
    /// its methods, which the graph attaches to the method nodes, not the class.
    pub fn dependents_many(
        &self,
        node_ids: &[&str],
        edge_types: Option<&[String]>,
        max_depth: Option<u8>,
    ) -> Vec<String> {
        self.traverse_bfs(node_ids, Direction::Incoming, edge_types, max_depth)
    }

    /// Direct children of a node via `contains` edges (e.g. a class's methods).
    pub fn contained_members(&self, node_id: &str) -> Vec<String> {
        let Some(&idx) = self.node_map.get(node_id) else {
            return vec![];
        };
        self.graph
            .edges_directed(idx, Direction::Outgoing)
            .filter(|e| e.weight() == "contains")
            .map(|e| self.reverse_map[&e.target()].clone())
            .collect()
    }

    /// BFS traversal in a given direction with optional depth limit
    fn traverse_bfs(
        &self,
        node_ids: &[&str],
        direction: Direction,
        edge_types: Option<&[String]>,
        max_depth: Option<u8>,
    ) -> Vec<String> {
        let allowed: Option<HashSet<&String>> = edge_types.map(|t| t.iter().collect());

        let mut visited: HashSet<NodeIndex> = HashSet::new();
        let mut result = Vec::new();
        let mut queue: VecDeque<(NodeIndex, u8)> = VecDeque::new();

        for node_id in node_ids {
            if let Some(&idx) = self.node_map.get(*node_id) {
                if visited.insert(idx) {
                    queue.push_back((idx, 0));
                }
            }
        }
        if queue.is_empty() {
            return vec![];
        }

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
                    "message" => "[msg]".cyan(),
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
    cross_service: bool,
    format: OutputFormat,
) -> Result<()> {
    let conn = open_db()?;
    let graph = GraphData::from_db(&conn)?;

    // Resolve node ID
    let node_id = resolve_node_id(&conn, node)?;

    if !graph.has_node(&node_id) {
        return Err(anyhow::anyhow!("Node not found: {}", node));
    }

    // If --cross-service is set and no explicit edge_types given, include cross-service types
    let effective_edge_types = if cross_service && edge_types.is_none() {
        None // traverse all edges including cross-service
    } else if let Some(mut types) = edge_types {
        if cross_service {
            for cs_type in crate::engine::storage::CROSS_SERVICE_EDGE_TYPES {
                let s = cs_type.to_string();
                if !types.contains(&s) {
                    types.push(s);
                }
            }
        }
        Some(types)
    } else {
        None
    };

    // Use `dependents` (Incoming BFS) — matches the help text "what breaks if this
    // node changes" and aligns with the MCP mu_impact tool. The prior outgoing
    // traversal was a transitive-deps listing mislabelled as impact.
    let affected_ids = graph.dependents(&node_id, effective_edge_types.as_deref(), depth);

    // Fetch importance scores so the list is ranked by PageRank-derived weight
    // (high-importance dependents first = the ones most likely to matter).
    let importance: HashMap<String, f32> = if affected_ids.is_empty() {
        HashMap::new()
    } else {
        let mut stmt = conn.prepare("SELECT id, importance_score FROM nodes WHERE id = ?1")?;
        let mut map = HashMap::new();
        for id in &affected_ids {
            let mut rows = stmt.query(params![id])?;
            if let Some(row) = rows.next()? {
                map.insert(id.clone(), row.get::<_, Option<f32>>(1)?.unwrap_or(0.0));
            }
        }
        map
    };

    let mut affected_nodes: Vec<AffectedNode> = affected_ids
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

    affected_nodes.sort_by(|a, b| {
        let ia = importance.get(&a.id).copied().unwrap_or(0.0);
        let ib = importance.get(&b.id).copied().unwrap_or(0.0);
        ib.partial_cmp(&ia).unwrap_or(std::cmp::Ordering::Equal)
    });

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
    // 1. Try exact match on id or name first. When multiple nodes share a name
    //    (common in C# where `Foo` is both a module file and the class inside it),
    //    prefer class > module > function — callers usually mean the class.
    let mut stmt = conn.prepare(
        "SELECT id FROM nodes WHERE id = ?1 OR name = ?1
         ORDER BY CASE type
             WHEN 'class' THEN 0
             WHEN 'module' THEN 1
             WHEN 'function' THEN 2
             ELSE 3
         END
         LIMIT 1",
    )?;
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

    /// Build a DB shaped like the DI case that broke impact analysis: a class
    /// whose methods are called by another class. Callers point at the method
    /// node, so a BFS from the class node alone cannot see them.
    fn create_class_method_db() -> Connection {
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("test.mubase");
        let conn = Connection::open(&db_path).unwrap();
        conn.execute_batch(
            r#"
            CREATE TABLE nodes (
                id VARCHAR PRIMARY KEY, type VARCHAR NOT NULL, name VARCHAR NOT NULL,
                qualified_name VARCHAR, file_path VARCHAR,
                line_start INTEGER, line_end INTEGER, properties JSON, complexity INTEGER DEFAULT 0
            );
            CREATE TABLE edges (
                id VARCHAR PRIMARY KEY, source_id VARCHAR NOT NULL,
                target_id VARCHAR NOT NULL, type VARCHAR NOT NULL, properties JSON
            );
            INSERT INTO nodes (id, type, name, file_path) VALUES
                ('cls:svc.cs:Svc', 'class', 'Svc', 'svc.cs'),
                ('fn:svc.cs:Svc.Send', 'function', 'Send', 'svc.cs'),
                ('cls:caller.cs:Caller', 'class', 'Caller', 'caller.cs'),
                ('fn:caller.cs:Caller.Run', 'function', 'Run', 'caller.cs');
            INSERT INTO edges (id, source_id, target_id, type) VALUES
                ('e1', 'cls:svc.cs:Svc', 'fn:svc.cs:Svc.Send', 'contains'),
                ('e2', 'cls:caller.cs:Caller', 'fn:caller.cs:Caller.Run', 'contains'),
                ('e3', 'fn:caller.cs:Caller.Run', 'fn:svc.cs:Svc.Send', 'calls');
            "#,
        )
        .unwrap();
        std::mem::forget(dir);
        conn
    }

    #[test]
    fn test_contained_members() {
        let conn = create_class_method_db();
        let graph = GraphData::from_db(&conn).unwrap();
        let members = graph.contained_members("cls:svc.cs:Svc");
        assert_eq!(members, vec!["fn:svc.cs:Svc.Send".to_string()]);
    }

    #[test]
    fn test_class_blast_radius_includes_method_callers() {
        let conn = create_class_method_db();
        let graph = GraphData::from_db(&conn).unwrap();

        // From the class node alone, the caller is invisible.
        let class_only = graph.dependents("cls:svc.cs:Svc", None, None);
        assert!(!class_only.contains(&"fn:caller.cs:Caller.Run".to_string()));

        // Seeding class + members finds the caller (and its containing class),
        // without reporting the seeds themselves.
        let members = graph.contained_members("cls:svc.cs:Svc");
        let mut seeds: Vec<&str> = vec!["cls:svc.cs:Svc"];
        seeds.extend(members.iter().map(|s| s.as_str()));
        let full = graph.dependents_many(&seeds, None, None);
        assert!(full.contains(&"fn:caller.cs:Caller.Run".to_string()));
        assert!(full.contains(&"cls:caller.cs:Caller".to_string()));
        assert!(!full.contains(&"cls:svc.cs:Svc".to_string()));
        assert!(!full.contains(&"fn:svc.cs:Svc.Send".to_string()));
    }
}
