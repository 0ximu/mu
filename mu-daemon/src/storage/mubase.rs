//! MUbase - DuckDB-based storage for the code graph.

use anyhow::{Context, Result};
use duckdb::{params, Connection};
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex};

use super::edges::Edge;
use super::nodes::Node;
use super::schema::{NodeType, SCHEMA_SQL, SCHEMA_VERSION};

/// Graph engine wrapper around petgraph for in-memory graph operations.
pub struct GraphEngine {
    nodes: Vec<String>,
    edges: Vec<(String, String, String)>,
    node_map: HashMap<String, usize>,
}

impl GraphEngine {
    /// Create a new empty graph engine.
    pub fn new() -> Self {
        Self {
            nodes: Vec::new(),
            edges: Vec::new(),
            node_map: HashMap::new(),
        }
    }

    /// Create from nodes and edges.
    pub fn from_data(nodes: Vec<String>, edges: Vec<(String, String, String)>) -> Self {
        let mut node_map = HashMap::new();
        for (i, node) in nodes.iter().enumerate() {
            node_map.insert(node.clone(), i);
        }
        Self {
            nodes,
            edges,
            node_map,
        }
    }

    /// Get the number of nodes.
    pub fn node_count(&self) -> usize {
        self.nodes.len()
    }

    /// Get the number of edges.
    pub fn edge_count(&self) -> usize {
        self.edges.len()
    }

    /// Check if a node exists.
    pub fn has_node(&self, node_id: &str) -> bool {
        self.node_map.contains_key(node_id)
    }

    /// Get all nodes.
    pub fn get_nodes(&self) -> &[String] {
        &self.nodes
    }

    /// Get all edges as (source, target, type) tuples.
    pub fn get_edges(&self) -> &[(String, String, String)] {
        &self.edges
    }
}

impl Default for GraphEngine {
    fn default() -> Self {
        Self::new()
    }
}

/// MUbase - DuckDB-based storage for code graphs.
pub struct MUbase {
    conn: Arc<Mutex<Connection>>,
    path: std::path::PathBuf,
}

impl MUbase {
    /// Open or create a MUbase database.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let conn = Connection::open(path)
            .with_context(|| format!("Failed to open database: {:?}", path))?;

        let mubase = Self {
            conn: Arc::new(Mutex::new(conn)),
            path: path.to_path_buf(),
        };

        mubase.init_schema()?;
        Ok(mubase)
    }

    /// Acquire the database connection lock, handling PoisonError gracefully.
    /// If the mutex is poisoned (previous holder panicked), we still acquire
    /// the lock and continue - the database connection itself is likely fine.
    fn acquire_conn(
        &self,
    ) -> Result<std::sync::MutexGuard<'_, Connection>> {
        self.conn
            .lock()
            .map_err(|e| anyhow::anyhow!("Database lock poisoned: {}", e))
    }

    /// Initialize the database schema.
    fn init_schema(&self) -> Result<()> {
        let conn = self.acquire_conn()?;

        // Execute schema creation
        conn.execute_batch(SCHEMA_SQL)
            .context("Failed to initialize schema")?;

        // Set schema version
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
            params![SCHEMA_VERSION],
        )?;

        Ok(())
    }

    /// Clear all data from the database.
    pub fn clear(&self) -> Result<()> {
        let conn = self.acquire_conn()?;
        conn.execute("DELETE FROM edges", [])?;
        conn.execute("DELETE FROM nodes", [])?;
        Ok(())
    }

    /// Insert a node into the database.
    pub fn insert_node(&self, node: &Node) -> Result<()> {
        let conn = self.acquire_conn()?;
        let properties_json = node
            .properties
            .as_ref()
            .map(|p| serde_json::to_string(p).unwrap_or_default());

        conn.execute(
            r#"INSERT OR REPLACE INTO nodes
               (id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"#,
            params![
                node.id,
                node.node_type.as_str(),
                node.name,
                node.qualified_name,
                node.file_path,
                node.line_start,
                node.line_end,
                properties_json,
                node.complexity,
            ],
        )?;
        Ok(())
    }

    /// Insert multiple nodes in a batch.
    pub fn insert_nodes(&self, nodes: &[Node]) -> Result<()> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(
            r#"INSERT OR REPLACE INTO nodes
               (id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"#,
        )?;

        for node in nodes {
            let properties_json = node
                .properties
                .as_ref()
                .map(|p| serde_json::to_string(p).unwrap_or_default());

            stmt.execute(params![
                node.id,
                node.node_type.as_str(),
                node.name,
                node.qualified_name,
                node.file_path,
                node.line_start,
                node.line_end,
                properties_json,
                node.complexity,
            ])?;
        }
        Ok(())
    }

    /// Insert an edge into the database.
    pub fn insert_edge(&self, edge: &Edge) -> Result<()> {
        let conn = self.acquire_conn()?;
        let properties_json = edge
            .properties
            .as_ref()
            .map(|p| serde_json::to_string(p).unwrap_or_default());

        conn.execute(
            r#"INSERT OR REPLACE INTO edges
               (id, source_id, target_id, type, properties)
               VALUES (?, ?, ?, ?, ?)"#,
            params![
                edge.id,
                edge.source_id,
                edge.target_id,
                edge.edge_type.as_str(),
                properties_json,
            ],
        )?;
        Ok(())
    }

    /// Insert multiple edges in a batch.
    pub fn insert_edges(&self, edges: &[Edge]) -> Result<()> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(
            r#"INSERT OR REPLACE INTO edges
               (id, source_id, target_id, type, properties)
               VALUES (?, ?, ?, ?, ?)"#,
        )?;

        for edge in edges {
            let properties_json = edge
                .properties
                .as_ref()
                .map(|p| serde_json::to_string(p).unwrap_or_default());

            stmt.execute(params![
                edge.id,
                edge.source_id,
                edge.target_id,
                edge.edge_type.as_str(),
                properties_json,
            ])?;
        }
        Ok(())
    }

    /// Get a node by ID.
    pub fn get_node(&self, id: &str) -> Result<Option<Node>> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity
             FROM nodes WHERE id = ?",
        )?;

        let mut rows = stmt.query(params![id])?;

        if let Some(row) = rows.next()? {
            let node_type_str: String = row.get(1)?;
            let properties_str: Option<String> = row.get(7)?;

            Ok(Some(Node {
                id: row.get(0)?,
                node_type: NodeType::from_str(&node_type_str).unwrap_or(NodeType::Module),
                name: row.get(2)?,
                qualified_name: row.get(3)?,
                file_path: row.get(4)?,
                line_start: row.get(5)?,
                line_end: row.get(6)?,
                properties: properties_str.and_then(|s| serde_json::from_str(&s).ok()),
                complexity: row.get(8)?,
            }))
        } else {
            Ok(None)
        }
    }

    /// Get all nodes of a specific type.
    pub fn get_nodes_by_type(&self, node_type: NodeType) -> Result<Vec<Node>> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity
             FROM nodes WHERE type = ?",
        )?;

        let mut rows = stmt.query(params![node_type.as_str()])?;
        let mut nodes = Vec::new();

        while let Some(row) = rows.next()? {
            let node_type_str: String = row.get(1)?;
            let properties_str: Option<String> = row.get(7)?;

            nodes.push(Node {
                id: row.get(0)?,
                node_type: NodeType::from_str(&node_type_str).unwrap_or(NodeType::Module),
                name: row.get(2)?,
                qualified_name: row.get(3)?,
                file_path: row.get(4)?,
                line_start: row.get(5)?,
                line_end: row.get(6)?,
                properties: properties_str.and_then(|s| serde_json::from_str(&s).ok()),
                complexity: row.get(8)?,
            });
        }

        Ok(nodes)
    }

    /// Delete nodes for a specific file (for incremental updates).
    pub fn delete_nodes_for_file(&self, file_path: &str) -> Result<usize> {
        let conn = self.acquire_conn()?;

        // First delete edges referencing these nodes
        conn.execute(
            "DELETE FROM edges WHERE source_id IN (SELECT id FROM nodes WHERE file_path = ?)
             OR target_id IN (SELECT id FROM nodes WHERE file_path = ?)",
            params![file_path, file_path],
        )?;

        // Then delete the nodes
        let deleted = conn.execute("DELETE FROM nodes WHERE file_path = ?", params![file_path])?;

        Ok(deleted)
    }

    /// Execute a raw SQL query and return results.
    pub fn query(&self, sql: &str) -> Result<QueryResult> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(sql)?;

        // Execute the query
        let mut rows = stmt.query([])?;

        // Collect rows and extract column information
        let mut rows_data: Vec<Vec<serde_json::Value>> = Vec::new();
        let mut columns: Vec<String> = Vec::new();
        let mut column_count = 0;

        while let Some(row) = rows.next()? {
            // Extract column information from the first row
            // In duckdb-rs, we can get column names from row.as_ref().column_names()
            if columns.is_empty() {
                let stmt_ref = row.as_ref();
                columns = stmt_ref.column_names().iter().map(|s| s.to_string()).collect();
                column_count = columns.len();
            }

            let mut row_data = Vec::new();
            for i in 0..column_count {
                // Try to get value as different types
                let value = if let Ok(v) = row.get::<_, String>(i) {
                    serde_json::Value::String(v)
                } else if let Ok(v) = row.get::<_, i64>(i) {
                    serde_json::Value::Number(v.into())
                } else if let Ok(v) = row.get::<_, f64>(i) {
                    serde_json::json!(v)
                } else if let Ok(v) = row.get::<_, bool>(i) {
                    serde_json::Value::Bool(v)
                } else {
                    serde_json::Value::Null
                };
                row_data.push(value);
            }
            rows_data.push(row_data);
        }

        // For empty result sets, columns will be empty which is acceptable
        // The caller can use DESCRIBE or other methods to get schema info if needed

        Ok(QueryResult {
            columns,
            rows: rows_data,
        })
    }

    /// Get graph statistics.
    pub fn stats(&self) -> Result<GraphStats> {
        let conn = self.acquire_conn()?;

        let node_count: usize = conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))?;
        let edge_count: usize = conn.query_row("SELECT COUNT(*) FROM edges", [], |row| row.get(0))?;

        // Get counts by type
        let mut type_counts = HashMap::new();
        let mut stmt = conn.prepare("SELECT type, COUNT(*) FROM nodes GROUP BY type")?;
        let mut rows = stmt.query([])?;
        while let Some(row) = rows.next()? {
            let type_name: String = row.get(0)?;
            let count: usize = row.get(1)?;
            type_counts.insert(type_name, count);
        }

        Ok(GraphStats {
            node_count,
            edge_count,
            type_counts,
        })
    }

    /// Load the graph into memory for fast traversal.
    pub fn load_graph(&self) -> Result<GraphEngine> {
        let conn = self.acquire_conn()?;

        // Load all node IDs
        let mut stmt = conn.prepare("SELECT id FROM nodes")?;
        let mut rows = stmt.query([])?;
        let mut nodes = Vec::new();
        while let Some(row) = rows.next()? {
            let id: String = row.get(0)?;
            nodes.push(id);
        }

        // Load all edges
        let mut stmt = conn.prepare("SELECT source_id, target_id, type FROM edges")?;
        let mut rows = stmt.query([])?;
        let mut edges = Vec::new();
        while let Some(row) = rows.next()? {
            let source: String = row.get(0)?;
            let target: String = row.get(1)?;
            let edge_type: String = row.get(2)?;
            edges.push((source, target, edge_type));
        }

        Ok(GraphEngine::from_data(nodes, edges))
    }
}

/// Result of a SQL query.
#[derive(Debug, Clone, serde::Serialize)]
pub struct QueryResult {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<serde_json::Value>>,
}

impl QueryResult {
    /// Get the number of rows.
    pub fn row_count(&self) -> usize {
        self.rows.len()
    }

    /// Convert to a list of dictionaries.
    pub fn as_dicts(&self) -> Vec<HashMap<String, serde_json::Value>> {
        self.rows
            .iter()
            .map(|row| {
                self.columns
                    .iter()
                    .zip(row.iter())
                    .map(|(col, val)| (col.clone(), val.clone()))
                    .collect()
            })
            .collect()
    }
}

/// Statistics about the graph.
#[derive(Debug, Clone, serde::Serialize)]
pub struct GraphStats {
    pub node_count: usize,
    pub edge_count: usize,
    pub type_counts: HashMap<String, usize>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn create_test_db() -> MUbase {
        // DuckDB needs a path that doesn't exist yet (or is a valid DB)
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("test.mubase");
        // Keep the dir alive by leaking it (ok for tests)
        std::mem::forget(dir);
        MUbase::open(&db_path).unwrap()
    }

    #[test]
    fn test_open_and_init() {
        let db = create_test_db();
        let stats = db.stats().unwrap();
        assert_eq!(stats.node_count, 0);
        assert_eq!(stats.edge_count, 0);
    }

    #[test]
    fn test_insert_and_get_node() {
        let db = create_test_db();
        let node = Node::module("src/cli.py");

        db.insert_node(&node).unwrap();

        let retrieved = db.get_node("mod:src/cli.py").unwrap();
        assert!(retrieved.is_some());
        let retrieved = retrieved.unwrap();
        assert_eq!(retrieved.name, "cli");
    }

    #[test]
    fn test_insert_edge() {
        let db = create_test_db();

        let node1 = Node::module("src/a.py");
        let node2 = Node::module("src/b.py");
        db.insert_node(&node1).unwrap();
        db.insert_node(&node2).unwrap();

        let edge = Edge::imports("mod:src/a.py", "mod:src/b.py");
        db.insert_edge(&edge).unwrap();

        let stats = db.stats().unwrap();
        assert_eq!(stats.node_count, 2);
        assert_eq!(stats.edge_count, 1);
    }

    #[test]
    fn test_load_graph() {
        let db = create_test_db();

        let node1 = Node::module("src/a.py");
        let node2 = Node::module("src/b.py");
        db.insert_node(&node1).unwrap();
        db.insert_node(&node2).unwrap();

        let edge = Edge::imports("mod:src/a.py", "mod:src/b.py");
        db.insert_edge(&edge).unwrap();

        let graph = db.load_graph().unwrap();
        assert_eq!(graph.node_count(), 2);
        assert_eq!(graph.edge_count(), 1);
    }

    #[test]
    fn test_query_returns_proper_column_names() {
        let db = create_test_db();

        // Insert a test node
        let node = Node::module("src/test.py");
        db.insert_node(&node).unwrap();

        // Query with SELECT *
        let result = db.query("SELECT * FROM nodes").unwrap();

        // Verify column names are actual column names, not col_0, col_1, etc.
        assert!(!result.columns.is_empty());
        assert!(
            result.columns.contains(&"id".to_string()),
            "Expected 'id' column, got: {:?}",
            result.columns
        );
        assert!(
            result.columns.contains(&"name".to_string()),
            "Expected 'name' column, got: {:?}",
            result.columns
        );
        assert!(
            result.columns.contains(&"type".to_string()),
            "Expected 'type' column, got: {:?}",
            result.columns
        );
        assert!(
            result.columns.contains(&"file_path".to_string()),
            "Expected 'file_path' column, got: {:?}",
            result.columns
        );

        // Ensure we don't have col_0, col_1 style names
        for col in &result.columns {
            assert!(
                !col.starts_with("col_"),
                "Column name should not be '{}', expected actual column names",
                col
            );
        }
    }

    #[test]
    fn test_query_returns_proper_column_names_with_aliases() {
        let db = create_test_db();

        // Insert test data
        let node = Node::module("src/test.py");
        db.insert_node(&node).unwrap();

        // Query with aliases
        let result = db
            .query("SELECT id AS node_id, name AS node_name FROM nodes")
            .unwrap();

        assert_eq!(result.columns.len(), 2);
        assert!(
            result.columns.contains(&"node_id".to_string()),
            "Expected 'node_id' alias, got: {:?}",
            result.columns
        );
        assert!(
            result.columns.contains(&"node_name".to_string()),
            "Expected 'node_name' alias, got: {:?}",
            result.columns
        );
    }
}
