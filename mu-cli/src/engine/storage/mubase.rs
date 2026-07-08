//! MUbase - DuckDB-based storage for the code graph.

use anyhow::{Context, Result};
use duckdb::{params, Config, Connection};
use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use super::edges::Edge;
use super::nodes::Node;
use super::schema::{NodeType, SCHEMA_SQL, SCHEMA_VERSION};

/// MUbase - DuckDB-based storage for code graphs.
pub struct MUbase {
    conn: Arc<Mutex<Connection>>,
    /// Path to the database file (stored for potential future use in queries/debugging).
    #[allow(dead_code)]
    path: std::path::PathBuf,
    /// Whether FTS extension is loaded and index exists.
    fts_available: AtomicBool,
}

impl Clone for MUbase {
    fn clone(&self) -> Self {
        Self {
            conn: Arc::clone(&self.conn),
            path: self.path.clone(),
            fts_available: AtomicBool::new(self.fts_available.load(Ordering::Relaxed)),
        }
    }
}

impl MUbase {
    /// Open or create a MUbase database in read-write mode.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let conn = Connection::open(path)
            .with_context(|| format!("Failed to open database: {:?}", path))?;

        let mubase = Self {
            conn: Arc::new(Mutex::new(conn)),
            path: path.to_path_buf(),
            fts_available: AtomicBool::new(false),
        };

        mubase.init_schema()?;
        mubase.detect_fts_availability();

        Ok(mubase)
    }

    /// Open a MUbase database in read-only mode (for concurrent queries).
    pub fn open_read_only(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let config = Config::default()
            .access_mode(duckdb::AccessMode::ReadOnly)
            .map_err(|e| anyhow::anyhow!("Failed to set read-only mode: {}", e))?;
        let conn = Connection::open_with_flags(path, config)
            .with_context(|| format!("Failed to open database in read-only mode: {:?}", path))?;

        let mubase = Self {
            conn: Arc::new(Mutex::new(conn)),
            path: path.to_path_buf(),
            fts_available: AtomicBool::new(false),
        };

        mubase.detect_fts_availability();

        Ok(mubase)
    }

    /// Acquire the database connection lock, handling PoisonError gracefully.
    /// If the mutex is poisoned (previous holder panicked), we still acquire
    /// the lock and continue - the database connection itself is likely fine.
    fn acquire_conn(&self) -> Result<std::sync::MutexGuard<'_, Connection>> {
        match self.conn.lock() {
            Ok(guard) => Ok(guard),
            Err(poisoned) => {
                tracing::warn!("Recovering from poisoned database mutex");
                Ok(poisoned.into_inner())
            }
        }
    }

    /// Run a closure with a borrowed reference to the underlying connection.
    pub fn with_connection<F, T>(&self, f: F) -> Result<T>
    where
        F: FnOnce(&Connection) -> Result<T>,
    {
        let conn = self.acquire_conn()?;
        f(&conn)
    }

    /// Initialize the database schema.
    fn init_schema(&self) -> Result<()> {
        let conn = self.acquire_conn()?;

        // Note: DuckDB has different concurrency model than SQLite:
        // - Single writer, multiple readers by default
        // - Use open_read_only() for read-only connections
        // - No WAL mode pragma needed (DuckDB manages this internally)

        // Check for v1 schema incompatibility (has model_name column instead of model)
        // DuckDB doesn't have information_schema.columns, so we try a query that would fail
        let has_old_schema = conn
            .query_row(
                "SELECT 1 FROM embeddings WHERE model_name IS NOT NULL LIMIT 1",
                [],
                |_| Ok(true),
            )
            .is_ok();

        if has_old_schema {
            anyhow::bail!(
                "Database was created with MU v1 and is incompatible with v2.\n\
                 Please delete and rebuild:\n\n\
                   rm -rf .mu && mu bootstrap\n"
            );
        }

        // v1.0.0 predates everything the current engine stores; its only
        // migration path (JSON embeddings) was removed along with vector search.
        let is_v1_0 = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version' AND value = '1.0.0'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if is_v1_0 {
            anyhow::bail!(
                "Database schema v1.0.0 is too old to migrate.\n\
                 Please delete and rebuild:\n\n\
                   rm -rf .mu && mu bootstrap\n"
            );
        }

        // Check if migration from v1.1.0 → v1.2.0 is needed (add source_text column)
        let needs_source_text_migrate = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version' AND value = '1.1.0'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if needs_source_text_migrate {
            tracing::info!("Adding source_text column to nodes table");
            super::migrations::migrate_add_source_text(&conn)?;
        }

        // Check if migration from v1.2.0 → v2.0.0 is needed (V3 search columns)
        let needs_v2_migrate = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version' AND value = '1.2.0'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if needs_v2_migrate {
            tracing::info!("Adding V3 search columns to nodes table");
            super::migrations::migrate_v1_2_to_v2(&conn)?;
        }

        // Check if migration from v2.0.0 → v2.1.0 is needed (add node_category)
        let needs_v2_1_migrate = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version' AND value = '2.0.0'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if needs_v2_1_migrate {
            tracing::info!("Adding node_category column to nodes table");
            super::migrations::migrate_v2_to_v2_1(&conn)?;
        }

        // Check if migration from v2.1.0 → v2.2.0 is needed (drop embeddings table)
        let needs_v2_2_migrate = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version' AND value = '2.1.0'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if needs_v2_2_migrate {
            tracing::info!("Dropping unused embeddings table");
            super::migrations::migrate_v2_1_to_v2_2(&conn)?;
        }

        // Execute schema creation (CREATE TABLE IF NOT EXISTS is safe for existing tables)
        conn.execute_batch(SCHEMA_SQL)
            .context("Failed to initialize schema")?;

        // Set schema version
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
            params![SCHEMA_VERSION],
        )
        .context("Failed to set schema version")?;

        Ok(())
    }

    /// Detect if FTS extension is loaded and index exists.
    fn detect_fts_availability(&self) {
        let Ok(conn) = self.acquire_conn() else {
            return;
        };

        // Try to load FTS extension
        let _ = conn.execute("INSTALL fts", []);
        let _ = conn.execute("LOAD fts", []);

        // Check if FTS index exists on nodes table
        // DuckDB FTS creates a schema called fts_main_<table>
        let has_fts = conn
            .query_row(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'fts_main_nodes'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if has_fts {
            self.fts_available.store(true, Ordering::Relaxed);
            tracing::debug!("FTS extension loaded, BM25 index available");
        }
    }

    /// Update summary fields for a node.
    pub fn update_summary(
        &self,
        node_id: &str,
        summary_text: &str,
        summary_source: &str,
        code_hash: &str,
    ) -> Result<()> {
        let conn = self.acquire_conn()?;
        conn.execute(
            "UPDATE nodes SET summary_text = ?, summary_source = ?, summary_code_hash = ?, summary_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params![summary_text, summary_source, code_hash, node_id],
        )?;
        Ok(())
    }

    /// Batch update importance scores.
    pub fn update_importance_batch(&self, scores: &[(String, f32)]) -> Result<()> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare("UPDATE nodes SET importance_score = ? WHERE id = ?")?;
        for (node_id, score) in scores {
            stmt.execute(params![score, node_id])?;
        }
        Ok(())
    }

    /// Update search_text for a node.
    pub fn update_search_text(&self, node_id: &str, search_text: &str) -> Result<()> {
        let conn = self.acquire_conn()?;
        conn.execute(
            "UPDATE nodes SET search_text = ? WHERE id = ?",
            params![search_text, node_id],
        )?;
        Ok(())
    }

    /// Batch update search_text.
    pub fn update_search_text_batch(&self, texts: &[(String, String)]) -> Result<()> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare("UPDATE nodes SET search_text = ? WHERE id = ?")?;
        for (node_id, text) in texts {
            stmt.execute(params![text, node_id])?;
        }
        Ok(())
    }

    /// Get nodes needing enrichment (summary_source = 'heuristic', ordered by importance).
    pub fn get_unsummarized_nodes(&self, limit: usize) -> Result<Vec<Node>> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity, source_text,
                    summary_text, summary_source, summary_code_hash, importance_score, search_text, summary_updated_at, node_category
             FROM nodes
             WHERE (summary_source IS NULL OR summary_source = 'heuristic')
               AND (node_category = 'production' OR node_category IS NULL)
             ORDER BY importance_score DESC
             LIMIT ?",
        )?;

        let mut rows = stmt.query(params![limit as i64])?;
        let mut nodes = Vec::new();

        while let Some(row) = rows.next()? {
            let node_type_str: String = row.get(1)?;
            let properties_str: Option<String> = row.get(7)?;

            nodes.push(Node {
                id: row.get(0)?,
                node_type: NodeType::parse(&node_type_str).unwrap_or(NodeType::Module),
                name: row.get(2)?,
                qualified_name: row.get(3)?,
                file_path: row.get(4)?,
                line_start: row.get(5)?,
                line_end: row.get(6)?,
                properties: properties_str.and_then(|s| serde_json::from_str(&s).ok()),
                complexity: row.get(8)?,
                source_text: row.get(9)?,
                summary_text: row.get(10)?,
                summary_source: row.get(11)?,
                summary_code_hash: row.get(12)?,
                importance_score: row.get::<_, Option<f32>>(13)?.unwrap_or(0.0),
                search_text: row.get(14)?,
                summary_updated_at: row.get::<_, Option<String>>(15).unwrap_or(None),
                node_category: row.get(16)?,
            });
        }

        Ok(nodes)
    }

    /// Rebuild FTS index on search_text only.
    ///
    /// Drops existing FTS index and recreates it targeting search_text
    /// (plus name, qualified_name, file_path as before).
    pub fn rebuild_fts_on_search_text(&self) -> Result<bool> {
        let conn = self.acquire_conn()?;

        // Ensure FTS extension is loaded
        let _ = conn.execute("INSTALL fts", []);
        let _ = conn.execute("LOAD fts", []);

        // Drop existing FTS index if present
        let _ = conn.execute("PRAGMA drop_fts_index('nodes')", []);

        // Check if we have nodes to index
        let count: usize = conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))?;
        if count == 0 {
            return Ok(false);
        }

        // Recreate FTS index including search_text
        conn.execute(
            "PRAGMA create_fts_index('nodes', 'id', 'name', 'qualified_name', 'file_path', 'search_text', overwrite=1)",
            [],
        )
        .context("Failed to create FTS index on search_text")?;

        self.fts_available.store(true, Ordering::Relaxed);
        tracing::info!("FTS index rebuilt on search_text ({} nodes)", count);

        Ok(true)
    }

    /// Run V3 three-phase search (exact -> BM25 -> importance tiebreak).
    ///
    /// Wraps `search::search_nodes` with the internal connection.
    pub fn search_v3(
        &self,
        query: &str,
        limit: usize,
    ) -> Result<Vec<crate::engine::search::SearchResult>> {
        let conn = self.acquire_conn()?;
        crate::engine::search::search_nodes(&conn, query, limit)
    }

    /// Full-config search: test + auxiliary dampening.
    pub fn search_v3_with_config(
        &self,
        query: &str,
        limit: usize,
        categories: &[&str],
    ) -> Result<Vec<crate::engine::search::SearchResult>> {
        let conn = self.acquire_conn()?;
        crate::engine::search::search_nodes_with_categories(&conn, query, limit, categories)
    }

    /// Clear all data from the database (no-op since insert functions handle this).
    pub fn clear(&self) -> Result<()> {
        // Clearing is now handled by insert_nodes and insert_edges
        Ok(())
    }

    /// Insert multiple nodes in a batch using an appender for better performance.
    pub fn insert_nodes(&self, nodes: &[Node]) -> Result<()> {
        // Drop unnamed nodes: parsers occasionally emit them for anonymous
        // lambdas/closures/arrow fns, and they appear in query output as
        // `[fn]  (path)` with a blank name — pure noise. Keep-list check here
        // rather than at every query site.
        let mut dropped_unnamed = 0usize;

        // Deduplicate by ID (keep last occurrence)
        let mut unique_nodes: std::collections::HashMap<&str, &Node> =
            std::collections::HashMap::new();
        for node in nodes {
            if node.name.trim().is_empty() {
                dropped_unnamed += 1;
                continue;
            }
            unique_nodes.insert(&node.id, node);
        }

        let dedup_nodes: Vec<&Node> = unique_nodes.into_values().collect();
        tracing::info!(
            "insert_nodes: {} unique nodes (from {} total, {} unnamed dropped)",
            dedup_nodes.len(),
            nodes.len(),
            dropped_unnamed,
        );

        let conn = self.acquire_conn()?;

        // First clear the table
        conn.execute("DELETE FROM nodes", [])?;

        // Use appender for bulk insert
        {
            let mut appender = conn
                .appender("nodes")
                .context("Failed to create node appender")?;
            for node in &dedup_nodes {
                let properties_json = node
                    .properties
                    .as_ref()
                    .map(serde_json::to_string)
                    .transpose()
                    .context("Failed to serialize node properties")?;

                appender.append_row(params![
                    node.id,
                    node.node_type.as_str(),
                    node.name,
                    node.qualified_name,
                    node.file_path,
                    node.line_start,
                    node.line_end,
                    properties_json,
                    node.complexity,
                    node.source_text,
                    node.summary_text,
                    node.summary_source,
                    node.summary_code_hash,
                    node.importance_score,
                    node.search_text,
                    node.summary_updated_at,
                    node.node_category,
                ])?;
            }
            appender.flush()?;
        }

        // Verify insertion
        let count: usize = conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))?;
        tracing::info!("insert_nodes: after insert, DB has {} nodes", count);
        Ok(())
    }

    /// Insert multiple edges in a batch using an appender for better performance.
    pub fn insert_edges(&self, edges: &[Edge]) -> Result<()> {
        // Count by type before dedup
        let mut type_counts: std::collections::HashMap<&str, usize> =
            std::collections::HashMap::new();
        for edge in edges {
            *type_counts.entry(edge.edge_type.as_str()).or_insert(0) += 1;
        }
        tracing::info!("insert_edges: before dedup - {:?}", type_counts);

        // Deduplicate by ID (keep last occurrence)
        let mut unique_edges: std::collections::HashMap<&str, &Edge> =
            std::collections::HashMap::new();
        for edge in edges {
            unique_edges.insert(&edge.id, edge);
        }

        let dedup_edges: Vec<&Edge> = unique_edges.into_values().collect();

        // Count by type after dedup
        let mut type_counts_after: std::collections::HashMap<&str, usize> =
            std::collections::HashMap::new();
        for edge in &dedup_edges {
            *type_counts_after
                .entry(edge.edge_type.as_str())
                .or_insert(0) += 1;
        }
        tracing::info!("insert_edges: after dedup - {:?}", type_counts_after);
        tracing::info!(
            "insert_edges: {} unique edges (from {} total)",
            dedup_edges.len(),
            edges.len()
        );

        let conn = self.acquire_conn()?;

        // First clear the table
        conn.execute("DELETE FROM edges", [])?;

        // Use appender for bulk insert
        {
            let mut appender = conn
                .appender("edges")
                .context("Failed to create edge appender")?;
            for edge in &dedup_edges {
                let properties_json = edge
                    .properties
                    .as_ref()
                    .map(serde_json::to_string)
                    .transpose()
                    .context("Failed to serialize edge properties")?;

                appender.append_row(params![
                    edge.id,
                    edge.source_id,
                    edge.target_id,
                    edge.edge_type.as_str(),
                    properties_json,
                ])?;
            }
            appender.flush()?;
        }

        // Verify insertion
        let count: usize = conn.query_row("SELECT COUNT(*) FROM edges", [], |row| row.get(0))?;
        tracing::info!("insert_edges: after insert, DB has {} edges", count);
        Ok(())
    }

    /// Get all nodes from the database.
    pub fn all_nodes(&self) -> Result<Vec<Node>> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity, source_text,
                    summary_text, summary_source, summary_code_hash, importance_score, search_text, summary_updated_at, node_category
             FROM nodes",
        )?;

        let mut rows = stmt.query([])?;
        let mut nodes = Vec::new();

        while let Some(row) = rows.next()? {
            let node_type_str: String = row.get(1)?;
            let properties_str: Option<String> = row.get(7)?;

            nodes.push(Node {
                id: row.get(0)?,
                node_type: NodeType::parse(&node_type_str).unwrap_or(NodeType::Module),
                name: row.get(2)?,
                qualified_name: row.get(3)?,
                file_path: row.get(4)?,
                line_start: row.get(5)?,
                line_end: row.get(6)?,
                properties: properties_str.and_then(|s| serde_json::from_str(&s).ok()),
                complexity: row.get(8)?,
                source_text: row.get(9)?,
                summary_text: row.get(10)?,
                summary_source: row.get(11)?,
                summary_code_hash: row.get(12)?,
                importance_score: row.get::<_, Option<f32>>(13)?.unwrap_or(0.0),
                search_text: row.get(14)?,
                summary_updated_at: row.get::<_, Option<String>>(15).unwrap_or(None),
                node_category: row.get(16)?,
            });
        }

        Ok(nodes)
    }

    /// Execute a raw SQL query and return results.
    pub fn query(&self, sql: &str) -> Result<QueryResult> {
        self.query_params(sql, &[])
    }

    /// Execute a parameterized SQL query and return results.
    pub fn query_params(&self, sql: &str, params: &[&dyn duckdb::ToSql]) -> Result<QueryResult> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn
            .prepare(sql)
            .with_context(|| format!("Failed to prepare query: {}", sql))?;

        let mut rows = stmt.query(params).context("Failed to execute query")?;

        Self::collect_rows(&mut rows)
    }

    /// Collect rows from a query result into a QueryResult.
    fn collect_rows(rows: &mut duckdb::Rows<'_>) -> Result<QueryResult> {
        let mut rows_data: Vec<Vec<serde_json::Value>> = Vec::new();
        let mut columns: Vec<String> = Vec::new();
        let mut column_count = 0;

        while let Some(row) = rows.next()? {
            if columns.is_empty() {
                let stmt_ref = row.as_ref();
                columns = stmt_ref
                    .column_names()
                    .iter()
                    .map(|s| s.to_string())
                    .collect();
                column_count = columns.len();
            }

            let mut row_data = Vec::new();
            for i in 0..column_count {
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

        Ok(QueryResult {
            columns,
            rows: rows_data,
        })
    }

    /// Get graph statistics.
    pub fn stats(&self) -> Result<GraphStats> {
        let conn = self.acquire_conn()?;

        let node_count: usize =
            conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))?;
        let edge_count: usize =
            conn.query_row("SELECT COUNT(*) FROM edges", [], |row| row.get(0))?;

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
}

/// Result of a SQL query.
#[derive(Debug, Clone, serde::Serialize)]
pub struct QueryResult {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<serde_json::Value>>,
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
        let dir = tempdir().unwrap();
        let db_path = dir.path().join("test.mubase");
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
    fn test_insert_and_query_nodes() {
        let db = create_test_db();
        let node = Node::module("src/cli.py");
        db.insert_nodes(&[node]).unwrap();

        let result = db
            .query("SELECT id, name FROM nodes WHERE id = 'mod:src/cli.py'")
            .unwrap();
        assert_eq!(result.rows.len(), 1);
    }

    #[test]
    fn test_insert_nodes_and_edges() {
        let db = create_test_db();

        let node1 = Node::module("src/a.py");
        let node2 = Node::module("src/b.py");
        db.insert_nodes(&[node1, node2]).unwrap();

        let edge = Edge::imports("mod:src/a.py", "mod:src/b.py");
        db.insert_edges(&[edge]).unwrap();

        let stats = db.stats().unwrap();
        assert_eq!(stats.node_count, 2);
        assert_eq!(stats.edge_count, 1);
    }

    #[test]
    fn test_query_returns_proper_column_names() {
        let db = create_test_db();
        let node = Node::module("src/test.py");
        db.insert_nodes(&[node]).unwrap();

        let result = db.query("SELECT * FROM nodes").unwrap();

        assert!(!result.columns.is_empty());
        assert!(result.columns.contains(&"id".to_string()));
        assert!(result.columns.contains(&"name".to_string()));
        assert!(result.columns.contains(&"type".to_string()));
        assert!(result.columns.contains(&"file_path".to_string()));

        for col in &result.columns {
            assert!(!col.starts_with("col_"));
        }
    }

    #[test]
    fn test_query_returns_proper_column_names_with_aliases() {
        let db = create_test_db();
        let node = Node::module("src/test.py");
        db.insert_nodes(&[node]).unwrap();

        let result = db
            .query("SELECT id AS node_id, name AS node_name FROM nodes")
            .unwrap();

        assert_eq!(result.columns.len(), 2);
        assert!(result.columns.contains(&"node_id".to_string()));
        assert!(result.columns.contains(&"node_name".to_string()));
    }
}
