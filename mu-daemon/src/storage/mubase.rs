//! MUbase - DuckDB-based storage for the code graph.

use anyhow::{Context, Result};
use duckdb::{params, Config, Connection};
use std::collections::HashMap;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

/// Database access mode for concurrent access control.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum AccessMode {
    /// Read-write mode (exclusive lock, for modifications)
    #[default]
    ReadWrite,
    /// Read-only mode (shared access, for queries)
    ReadOnly,
}

use super::edges::Edge;
use super::embeddings::{EmbeddingStats, VectorSearchResult};
use super::graph_engine::GraphEngine;
use super::nodes::Node;
use super::schema::{NodeType, SCHEMA_SQL, SCHEMA_VERSION};

/// MUbase - DuckDB-based storage for code graphs.
pub struct MUbase {
    conn: Arc<Mutex<Connection>>,
    /// Path to the database file (stored for potential future use in queries/debugging).
    #[allow(dead_code)]
    path: std::path::PathBuf,
    /// Whether VSS extension is loaded and HNSW index exists.
    vss_available: AtomicBool,
    /// Whether we've already warned about VSS unavailability (warn once).
    vss_warned: AtomicBool,
    /// Whether FTS extension is loaded and index exists.
    fts_available: AtomicBool,
}

impl MUbase {
    /// Open or create a MUbase database in read-write mode.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        Self::open_with_mode(path, AccessMode::ReadWrite)
    }

    /// Open a MUbase database in read-only mode (for concurrent queries).
    ///
    /// Use this for operations that don't modify the database, such as:
    /// - Running MUQL queries
    /// - Vector search
    /// - Graph traversal
    ///
    /// Multiple read-only connections can coexist without blocking.
    pub fn open_read_only(path: impl AsRef<Path>) -> Result<Self> {
        Self::open_with_mode(path, AccessMode::ReadOnly)
    }

    /// Open a MUbase database with the specified access mode.
    pub fn open_with_mode(path: impl AsRef<Path>, mode: AccessMode) -> Result<Self> {
        let path = path.as_ref();

        let conn = match mode {
            AccessMode::ReadWrite => Connection::open(path)
                .with_context(|| format!("Failed to open database: {:?}", path))?,
            AccessMode::ReadOnly => {
                let config = Config::default()
                    .access_mode(duckdb::AccessMode::ReadOnly)
                    .map_err(|e| anyhow::anyhow!("Failed to set read-only mode: {}", e))?;
                Connection::open_with_flags(path, config).with_context(|| {
                    format!("Failed to open database in read-only mode: {:?}", path)
                })?
            }
        };

        let mubase = Self {
            conn: Arc::new(Mutex::new(conn)),
            path: path.to_path_buf(),
            vss_available: AtomicBool::new(false),
            vss_warned: AtomicBool::new(false),
            fts_available: AtomicBool::new(false),
        };

        // Only initialize schema in read-write mode
        if mode == AccessMode::ReadWrite {
            mubase.init_schema()?;
        }

        // Check if VSS extension and HNSW index are available
        mubase.detect_vss_availability();

        // Check if FTS extension and index are available
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

        // Check if migration is needed (v1.0.0 JSON embeddings → v1.1.0 native arrays)
        // We detect this by checking the schema version in metadata table
        let needs_migrate = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version' AND value = '1.0.0'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if needs_migrate {
            tracing::info!("Migrating embeddings from JSON to native FLOAT[384]");
            super::migrations::migrate_embeddings_to_native(&conn)?;
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

    /// Get the current schema version from the database.
    ///
    /// Returns "1.0.0" if no version is stored (legacy database).
    pub fn get_schema_version(&self) -> Result<String> {
        let conn = self.acquire_conn()?;
        let version: String = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .unwrap_or_else(|_| "1.0.0".to_string());
        Ok(version)
    }

    /// Update the schema version in the database.
    fn set_schema_version(&self, version: &str) -> Result<()> {
        let conn = self.acquire_conn()?;
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
            params![version],
        )?;
        Ok(())
    }

    /// Run any pending schema migrations.
    ///
    /// Currently migrates v1.0.0 (JSON embeddings) to v1.1.0 (native FLOAT[384]).
    pub fn run_migrations(&self) -> Result<()> {
        let current_version = self.get_schema_version()?;
        if super::migrations::needs_migration(&current_version, super::migrations::TARGET_VERSION) {
            tracing::info!(
                "Migrating schema from {} to {}",
                current_version,
                super::migrations::TARGET_VERSION
            );
            let conn = self.acquire_conn()?;
            super::migrations::migrate_embeddings_to_native(&conn)?;
        }
        Ok(())
    }

    // ========================================================================
    // VSS Extension & HNSW Index Support
    // ========================================================================

    /// Detect if VSS extension is loaded and HNSW index exists.
    ///
    /// Called during database open to enable optimized vector search paths.
    fn detect_vss_availability(&self) {
        let Ok(conn) = self.acquire_conn() else {
            return;
        };

        // Try to load VSS extension (may already be loaded)
        let _ = conn.execute("LOAD vss", []);

        // Check if HNSW index exists on embeddings table
        let has_hnsw = conn
            .query_row(
                "SELECT 1 FROM duckdb_indexes() WHERE index_name = 'idx_embeddings_hnsw'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if has_hnsw {
            self.vss_available.store(true, Ordering::Relaxed);
            tracing::debug!("VSS extension loaded, HNSW index available");
        }
    }

    /// Try to load the VSS extension. Returns true if successful.
    ///
    /// This installs and loads the DuckDB VSS extension for vector similarity search.
    /// The extension provides HNSW indexing for O(log n) approximate nearest neighbor search.
    fn try_load_vss(&self) -> Result<bool> {
        let conn = self.acquire_conn()?;

        // Try to install VSS (may already be installed)
        if let Err(e) = conn.execute("INSTALL vss", []) {
            tracing::debug!("VSS install skipped (may already be installed): {}", e);
        }

        // Try to load VSS
        match conn.execute("LOAD vss", []) {
            Ok(_) => {
                tracing::info!("VSS extension loaded successfully");
                Ok(true)
            }
            Err(e) => {
                tracing::warn!("Failed to load VSS extension: {}", e);
                Ok(false)
            }
        }
    }

    /// Create HNSW index on the embeddings table for fast vector search.
    ///
    /// Prerequisites:
    /// - VSS extension must be installed and loaded
    /// - Embeddings table must have data (index built from existing vectors)
    ///
    /// The index uses cosine distance metric matching our similarity search.
    /// After creation, vector_search will automatically use the index.
    pub fn create_hnsw_index(&self) -> Result<bool> {
        // First ensure VSS is loaded
        if !self.try_load_vss()? {
            anyhow::bail!(
                "Cannot create HNSW index: VSS extension failed to load.\n\
                 This may be due to network issues or platform limitations."
            );
        }

        let conn = self.acquire_conn()?;

        // Check if index already exists
        let exists = conn
            .query_row(
                "SELECT 1 FROM duckdb_indexes() WHERE index_name = 'idx_embeddings_hnsw'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if exists {
            tracing::info!("HNSW index already exists");
            self.vss_available.store(true, Ordering::Relaxed);
            return Ok(false); // Index already existed
        }

        // Check if we have embeddings to index
        let count: usize = conn.query_row("SELECT COUNT(*) FROM embeddings", [], |row| row.get(0))?;

        if count == 0 {
            anyhow::bail!("Cannot create HNSW index: no embeddings in database");
        }

        tracing::info!("Creating HNSW index on {} embeddings...", count);

        // Enable experimental persistence for HNSW (required for non-memory databases)
        conn.execute("SET hnsw_enable_experimental_persistence = true", [])
            .context("Failed to enable HNSW persistence")?;

        // Create HNSW index with cosine metric
        // Note: DuckDB VSS uses 'cosine' metric which computes cosine distance (1 - similarity)
        conn.execute(
            "CREATE INDEX idx_embeddings_hnsw ON embeddings USING HNSW (embedding) WITH (metric = 'cosine')",
            [],
        )
        .context("Failed to create HNSW index")?;

        self.vss_available.store(true, Ordering::Relaxed);
        tracing::info!("HNSW index created successfully");

        Ok(true) // Index was created
    }

    /// Drop the HNSW index if it exists.
    pub fn drop_hnsw_index(&self) -> Result<()> {
        let conn = self.acquire_conn()?;
        conn.execute("DROP INDEX IF EXISTS idx_embeddings_hnsw", [])?;
        self.vss_available.store(false, Ordering::Relaxed);
        Ok(())
    }

    /// Check if HNSW index is available for vector search.
    pub fn has_hnsw_index(&self) -> bool {
        self.vss_available.load(Ordering::Relaxed)
    }

    // ========================================================================
    // FTS Extension & BM25 Search Support
    // ========================================================================

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

    /// Create FTS index on the nodes table for BM25 keyword search.
    ///
    /// Indexes: name, qualified_name, file_path
    /// This enables fast keyword-based search that complements semantic search.
    pub fn create_fts_index(&self) -> Result<bool> {
        let conn = self.acquire_conn()?;

        // Install and load FTS extension
        conn.execute("INSTALL fts", [])
            .context("Failed to install FTS extension")?;
        conn.execute("LOAD fts", [])
            .context("Failed to load FTS extension")?;

        // Check if index already exists
        let exists = conn
            .query_row(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'fts_main_nodes'",
                [],
                |_| Ok(true),
            )
            .unwrap_or(false);

        if exists {
            tracing::info!("FTS index already exists");
            self.fts_available.store(true, Ordering::Relaxed);
            return Ok(false);
        }

        // Check if we have nodes to index
        let count: usize = conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))?;
        if count == 0 {
            anyhow::bail!("Cannot create FTS index: no nodes in database");
        }

        tracing::info!("Creating FTS index on {} nodes...", count);

        // Create FTS index on name, qualified_name, and file_path
        // This allows searching for symbol names and file locations
        conn.execute(
            "PRAGMA create_fts_index('nodes', 'id', 'name', 'qualified_name', 'file_path', overwrite=1)",
            [],
        )
        .context("Failed to create FTS index")?;

        self.fts_available.store(true, Ordering::Relaxed);
        tracing::info!("FTS index created successfully");

        Ok(true)
    }

    /// Drop the FTS index if it exists.
    pub fn drop_fts_index(&self) -> Result<()> {
        let conn = self.acquire_conn()?;
        let _ = conn.execute("PRAGMA drop_fts_index('nodes')", []);
        self.fts_available.store(false, Ordering::Relaxed);
        Ok(())
    }

    /// Check if FTS index is available for BM25 search.
    pub fn has_fts_index(&self) -> bool {
        self.fts_available.load(Ordering::Relaxed)
    }

    /// Perform BM25 keyword search on nodes.
    ///
    /// Returns nodes matching the query ranked by BM25 score.
    /// This finds exact keyword matches that semantic search might miss.
    pub fn bm25_search(&self, query: &str, limit: usize) -> Result<Vec<VectorSearchResult>> {
        let conn = self.acquire_conn()?;

        // Ensure FTS is loaded
        let _ = conn.execute("LOAD fts", []);

        if !self.has_fts_index() {
            // Fall back to LIKE-based search if no FTS index
            return self.fallback_keyword_search(&conn, query, limit);
        }

        // BM25 search using DuckDB FTS
        // The fts_main_nodes.match_bm25 function returns a score for matching documents
        let sql = format!(
            r#"
            SELECT
                n.id,
                n.name,
                n.type,
                n.file_path,
                n.qualified_name,
                fts_main_nodes.match_bm25(n.id, ?) AS score
            FROM nodes n
            WHERE score IS NOT NULL
            ORDER BY score DESC
            LIMIT ?
            "#
        );

        let mut stmt = conn.prepare(&sql)?;
        let mut rows = stmt.query(params![query, limit as i64])?;
        let mut results = Vec::new();

        while let Some(row) = rows.next()? {
            let node_id: String = row.get(0)?;
            let name: String = row.get(1)?;
            let node_type: String = row.get(2)?;
            let file_path: Option<String> = row.get(3)?;
            let qualified_name: Option<String> = row.get(4)?;
            let score: f64 = row.get(5)?;

            // Normalize BM25 score to 0-1 range (BM25 scores are typically 0-25+)
            // Using sigmoid-like normalization
            let similarity = (score / (score + 10.0)) as f32;

            results.push(VectorSearchResult {
                node_id,
                name,
                node_type,
                file_path,
                qualified_name,
                similarity,
            });
        }

        Ok(results)
    }

    /// Fallback keyword search using LIKE when FTS index is not available.
    fn fallback_keyword_search(
        &self,
        conn: &Connection,
        query: &str,
        limit: usize,
    ) -> Result<Vec<VectorSearchResult>> {
        // Split query into keywords and search for any match
        let keywords: Vec<&str> = query.split_whitespace().collect();
        if keywords.is_empty() {
            return Ok(Vec::new());
        }

        // Build OR conditions for each keyword
        let conditions: Vec<String> = keywords
            .iter()
            .map(|kw| {
                let escaped = kw.replace('\'', "''").to_lowercase();
                format!(
                    "(LOWER(name) LIKE '%{}%' OR LOWER(qualified_name) LIKE '%{}%' OR LOWER(file_path) LIKE '%{}%')",
                    escaped, escaped, escaped
                )
            })
            .collect();

        let sql = format!(
            r#"
            SELECT id, name, type, file_path, qualified_name
            FROM nodes
            WHERE {}
            LIMIT ?
            "#,
            conditions.join(" OR ")
        );

        let mut stmt = conn.prepare(&sql)?;
        let mut rows = stmt.query(params![limit as i64])?;
        let mut results = Vec::new();

        while let Some(row) = rows.next()? {
            results.push(VectorSearchResult {
                node_id: row.get(0)?,
                name: row.get(1)?,
                node_type: row.get(2)?,
                file_path: row.get(3)?,
                qualified_name: row.get(4)?,
                similarity: 0.5, // Fixed score for LIKE matches
            });
        }

        Ok(results)
    }

    /// Clear all data from the database (no-op since insert functions handle this).
    pub fn clear(&self) -> Result<()> {
        // Clearing is now handled by insert_nodes and insert_edges
        Ok(())
    }

    /// Insert a node into the database.
    pub fn insert_node(&self, node: &Node) -> Result<()> {
        let conn = self.acquire_conn()?;
        let properties_json = node
            .properties
            .as_ref()
            .map(serde_json::to_string)
            .transpose()
            .context("Failed to serialize node properties")?;

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
        )
        .with_context(|| format!("Failed to insert node: {}", node.id))?;
        Ok(())
    }

    /// Insert multiple nodes in a batch using an appender for better performance.
    pub fn insert_nodes(&self, nodes: &[Node]) -> Result<()> {
        // Deduplicate by ID (keep last occurrence)
        let mut unique_nodes: std::collections::HashMap<&str, &Node> =
            std::collections::HashMap::new();
        for node in nodes {
            unique_nodes.insert(&node.id, node);
        }

        let dedup_nodes: Vec<&Node> = unique_nodes.into_values().collect();
        tracing::info!(
            "insert_nodes: {} unique nodes (from {} total)",
            dedup_nodes.len(),
            nodes.len()
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
                ])?;
            }
            appender.flush()?;
        }

        // Verify insertion
        let count: usize = conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))?;
        tracing::info!("insert_nodes: after insert, DB has {} nodes", count);
        Ok(())
    }

    /// Insert an edge into the database.
    pub fn insert_edge(&self, edge: &Edge) -> Result<()> {
        let conn = self.acquire_conn()?;
        let properties_json = edge
            .properties
            .as_ref()
            .map(serde_json::to_string)
            .transpose()
            .context("Failed to serialize edge properties")?;

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
        )
        .with_context(|| format!("Failed to insert edge: {}", edge.id))?;
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
                node_type: NodeType::parse(&node_type_str).unwrap_or(NodeType::Module),
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

    /// Get all nodes from the database.
    pub fn all_nodes(&self) -> Result<Vec<Node>> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity
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
            });
        }

        Ok(nodes)
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
                node_type: NodeType::parse(&node_type_str).unwrap_or(NodeType::Module),
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
        )
        .with_context(|| format!("Failed to delete edges for file: {}", file_path))?;

        // Then delete the nodes
        let deleted = conn
            .execute("DELETE FROM nodes WHERE file_path = ?", params![file_path])
            .with_context(|| format!("Failed to delete nodes for file: {}", file_path))?;

        Ok(deleted)
    }

    /// Execute a raw SQL query and return results.
    pub fn query(&self, sql: &str) -> Result<QueryResult> {
        self.query_with_params(sql, &[])
    }

    /// Execute a SQL query with parameters and return results.
    ///
    /// Parameters use `?` placeholders in the SQL string.
    /// This prevents SQL injection by properly escaping values.
    pub fn query_with_params(
        &self,
        sql: &str,
        params: &[&dyn duckdb::ToSql],
    ) -> Result<QueryResult> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn
            .prepare(sql)
            .with_context(|| format!("Failed to prepare query: {}", sql))?;

        // Execute the query with parameters
        let mut rows = stmt.query(params).context("Failed to execute query")?;

        // Collect rows and extract column information
        let mut rows_data: Vec<Vec<serde_json::Value>> = Vec::new();
        let mut columns: Vec<String> = Vec::new();
        let mut column_count = 0;

        while let Some(row) = rows.next()? {
            // Extract column information from the first row
            // In duckdb-rs, we can get column names from row.as_ref().column_names()
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

    // ========================================================================
    // Embedding Methods
    // ========================================================================

    /// Check if the embeddings table has any data.
    pub fn has_embeddings(&self) -> Result<bool> {
        let conn = self.acquire_conn()?;
        let count: usize =
            conn.query_row("SELECT COUNT(*) FROM embeddings", [], |row| row.get(0))?;
        Ok(count > 0)
    }

    /// Clear all embeddings from the database.
    pub fn clear_embeddings(&self) -> Result<()> {
        let conn = self.acquire_conn()?;
        conn.execute("DELETE FROM embeddings", [])?;
        Ok(())
    }

    /// Insert a batch of (node_id, embedding, optional_text) tuples.
    ///
    /// Embeddings are stored as native FLOAT[384] arrays for efficient
    /// similarity search using `array_cosine_similarity()`.
    ///
    /// # Arguments
    /// * `batch` - Slice of (node_id, embedding_vector, optional_text) tuples
    /// * `model` - Optional model name (defaults to 'mu-sigma-v2')
    pub fn insert_embeddings_batch(
        &self,
        batch: &[(String, Vec<f32>, Option<String>)],
        model: Option<&str>,
    ) -> Result<()> {
        let conn = self.acquire_conn()?;
        let model_name = model.unwrap_or("mu-sigma-v2");

        for (node_id, embedding, _text) in batch {
            // Format embedding as DuckDB array literal: [0.1, 0.2, ...]::FLOAT[384]
            // Note: We use string formatting because duckdb-rs doesn't support
            // native array parameters well. The node_id is still parameterized
            // to prevent SQL injection.
            let array_literal = format!(
                "[{}]::FLOAT[384]",
                embedding
                    .iter()
                    .map(|f| f.to_string())
                    .collect::<Vec<_>>()
                    .join(",")
            );

            let sql = format!(
                "INSERT OR REPLACE INTO embeddings (node_id, embedding, model, created_at) \
                 VALUES (?, {}, ?, CURRENT_TIMESTAMP)",
                array_literal
            );

            conn.execute(&sql, params![node_id, model_name])?;
        }

        Ok(())
    }

    /// Get files that have changed compared to stored hashes.
    ///
    /// # Arguments
    /// * `current_hashes` - Map of file_path -> content_hash for current files
    ///
    /// # Returns
    /// List of file paths that are new or have changed content
    pub fn get_stale_files(&self, current_hashes: &HashMap<String, String>) -> Result<Vec<String>> {
        let stored_hashes = self.get_all_file_hashes()?;
        let mut stale_files = Vec::new();

        for (file_path, current_hash) in current_hashes {
            match stored_hashes.get(file_path) {
                Some(stored_hash) if stored_hash == current_hash => {
                    // File unchanged, skip
                }
                _ => {
                    // File is new or hash changed
                    stale_files.push(file_path.clone());
                }
            }
        }

        Ok(stale_files)
    }

    /// Search for similar embeddings using cosine similarity.
    ///
    /// Uses DuckDB's native vector functions for efficient in-database search.
    /// When HNSW index is available (via VSS extension), uses O(log n) approximate
    /// nearest neighbor search. Otherwise falls back to O(n) linear scan.
    ///
    /// # Arguments
    /// * `query_embedding` - The query vector to search for (384 dimensions)
    /// * `limit` - Maximum number of results to return
    /// * `threshold` - Optional minimum similarity threshold (0.0 to 1.0)
    ///
    /// # Returns
    /// Vector of search results sorted by similarity (highest first)
    pub fn vector_search(
        &self,
        query_embedding: &[f32],
        limit: usize,
        threshold: Option<f32>,
    ) -> Result<Vec<VectorSearchResult>> {
        let conn = self.acquire_conn()?;

        // Build query array literal for SQL
        let query_array = format!(
            "[{}]::FLOAT[384]",
            query_embedding
                .iter()
                .map(|f| f.to_string())
                .collect::<Vec<_>>()
                .join(",")
        );

        let min_similarity = threshold.unwrap_or(0.0);

        // Check if HNSW index is available for faster search
        let use_hnsw = self.vss_available.load(Ordering::Relaxed);

        // Warn once if HNSW is not available (user may want to enable it)
        if !use_hnsw && !self.vss_warned.swap(true, Ordering::Relaxed) {
            let count: usize = conn
                .query_row("SELECT COUNT(*) FROM embeddings", [], |row| row.get(0))
                .unwrap_or(0);
            if count > 1000 {
                tracing::warn!(
                    "Linear scan over {} embeddings. Run `mu bootstrap --hnsw` for faster search.",
                    count
                );
            }
        }

        let sql = if use_hnsw {
            // HNSW path: Use distance-based ordering for index utilization
            // HNSW requires ORDER BY distance pattern to use the index effectively
            // We fetch more results to account for threshold filtering, then filter
            format!(
                r#"
                SELECT
                    e.node_id,
                    n.name,
                    n.type as node_type,
                    n.file_path,
                    n.qualified_name,
                    array_cosine_distance(e.embedding, {query_array}) as distance
                FROM embeddings e
                JOIN nodes n ON e.node_id = n.id
                ORDER BY distance
                LIMIT {limit}
                "#,
                query_array = query_array,
                limit = limit * 2 // Fetch extra for threshold filtering
            )
        } else {
            // Linear scan path: Use similarity with WHERE filtering
            format!(
                r#"
                SELECT
                    e.node_id,
                    n.name,
                    n.type as node_type,
                    n.file_path,
                    n.qualified_name,
                    array_cosine_similarity(e.embedding, {query_array}) as similarity
                FROM embeddings e
                JOIN nodes n ON e.node_id = n.id
                WHERE array_cosine_similarity(e.embedding, {query_array}) >= {min_similarity}
                ORDER BY similarity DESC
                LIMIT {limit}
                "#,
                query_array = query_array,
                min_similarity = min_similarity,
                limit = limit
            )
        };

        let mut stmt = conn.prepare(&sql)?;
        let mut rows = stmt.query([])?;
        let mut results: Vec<VectorSearchResult> = Vec::new();

        while let Some(row) = rows.next()? {
            let node_id: String = row.get(0)?;
            let name: String = row.get(1)?;
            let node_type: String = row.get(2)?;
            let file_path: Option<String> = row.get(3)?;
            let qualified_name: Option<String> = row.get(4)?;

            // Handle distance vs similarity based on query type
            let similarity = if use_hnsw {
                let distance: f64 = row.get(5)?;
                // Convert distance to similarity: similarity = 1 - distance
                let sim = 1.0 - distance;
                // Apply threshold filter (HNSW can't filter in ORDER BY)
                if sim < min_similarity as f64 {
                    continue;
                }
                sim as f32
            } else {
                let sim: f64 = row.get(5)?;
                sim as f32
            };

            results.push(VectorSearchResult {
                node_id,
                similarity,
                name,
                node_type,
                file_path,
                qualified_name,
            });

            // Stop if we have enough results (HNSW fetches extra)
            if results.len() >= limit {
                break;
            }
        }

        Ok(results)
    }

    /// Get embedding statistics.
    pub fn embedding_stats(&self) -> Result<EmbeddingStats> {
        let conn = self.acquire_conn()?;

        let total_nodes: usize =
            conn.query_row("SELECT COUNT(*) FROM nodes", [], |row| row.get(0))?;
        let nodes_with_embeddings: usize =
            conn.query_row("SELECT COUNT(*) FROM embeddings", [], |row| row.get(0))?;

        // Get the model used (most common one if multiple)
        let model: Option<String> = conn
            .query_row(
                "SELECT model FROM embeddings GROUP BY model ORDER BY COUNT(*) DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .ok();

        let coverage_percent = if total_nodes > 0 {
            (nodes_with_embeddings as f32 / total_nodes as f32) * 100.0
        } else {
            0.0
        };

        Ok(EmbeddingStats {
            total_nodes,
            nodes_with_embeddings,
            model,
            coverage_percent,
        })
    }

    /// Get all stored file hashes.
    pub fn get_all_file_hashes(&self) -> Result<HashMap<String, String>> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare("SELECT file_path, content_hash FROM file_hashes")?;
        let mut rows = stmt.query([])?;
        let mut hashes = HashMap::new();

        while let Some(row) = rows.next()? {
            let file_path: String = row.get(0)?;
            let content_hash: String = row.get(1)?;
            hashes.insert(file_path, content_hash);
        }

        Ok(hashes)
    }

    /// Update multiple file hashes in batch.
    ///
    /// # Arguments
    /// * `updates` - Slice of (file_path, content_hash) pairs to insert/update
    pub fn set_file_hashes_batch(&self, updates: &[(String, String)]) -> Result<()> {
        let conn = self.acquire_conn()?;
        let mut stmt = conn.prepare(
            r#"INSERT OR REPLACE INTO file_hashes (file_path, content_hash, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)"#,
        )?;

        for (file_path, content_hash) in updates {
            stmt.execute(params![file_path, content_hash])?;
        }

        Ok(())
    }

    /// Delete embeddings for nodes that no longer exist.
    /// Useful for cleanup after incremental updates.
    pub fn cleanup_orphaned_embeddings(&self) -> Result<usize> {
        let conn = self.acquire_conn()?;
        let deleted = conn.execute(
            "DELETE FROM embeddings WHERE node_id NOT IN (SELECT id FROM nodes)",
            [],
        )?;
        Ok(deleted)
    }

    /// Delete file hashes for files that no longer exist in the current set.
    ///
    /// # Arguments
    /// * `current_files` - Set of file paths that currently exist
    pub fn cleanup_stale_file_hashes(
        &self,
        current_files: &std::collections::HashSet<String>,
    ) -> Result<usize> {
        let conn = self.acquire_conn()?;

        // Get all stored file paths
        let stored_hashes = self.get_all_file_hashes()?;
        let mut deleted_count = 0;

        for file_path in stored_hashes.keys() {
            if !current_files.contains(file_path) {
                conn.execute(
                    "DELETE FROM file_hashes WHERE file_path = ?",
                    params![file_path],
                )?;
                deleted_count += 1;
            }
        }

        Ok(deleted_count)
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

    /// Create a 384-dimensional test embedding by padding short vectors with zeros.
    /// This is needed because the schema uses FLOAT[384] fixed-size arrays.
    fn test_embedding(values: &[f32]) -> Vec<f32> {
        let mut embedding = vec![0.0f32; 384];
        for (i, &v) in values.iter().enumerate() {
            if i < 384 {
                embedding[i] = v;
            }
        }
        embedding
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

    // ========================================================================
    // Embedding Tests
    // ========================================================================

    #[test]
    fn test_has_embeddings_empty() {
        let db = create_test_db();
        assert!(!db.has_embeddings().unwrap());
    }

    #[test]
    fn test_insert_and_has_embeddings() {
        let db = create_test_db();

        // Insert a node first (embeddings reference nodes)
        let node = Node::module("src/test.py");
        db.insert_node(&node).unwrap();

        // Insert an embedding (padded to 384 dimensions)
        let batch = vec![(
            "mod:src/test.py".to_string(),
            test_embedding(&[0.1, 0.2, 0.3]),
            None,
        )];
        db.insert_embeddings_batch(&batch, None).unwrap();

        assert!(db.has_embeddings().unwrap());
    }

    #[test]
    fn test_embedding_stats() {
        let db = create_test_db();

        // Insert nodes
        let node1 = Node::module("src/a.py");
        let node2 = Node::module("src/b.py");
        db.insert_node(&node1).unwrap();
        db.insert_node(&node2).unwrap();

        // Insert embedding for one node (padded to 384 dimensions)
        let batch = vec![(
            "mod:src/a.py".to_string(),
            test_embedding(&[0.1, 0.2, 0.3]),
            None,
        )];
        db.insert_embeddings_batch(&batch, Some("test-model"))
            .unwrap();

        let stats = db.embedding_stats().unwrap();
        assert_eq!(stats.total_nodes, 2);
        assert_eq!(stats.nodes_with_embeddings, 1);
        assert_eq!(stats.model, Some("test-model".to_string()));
        assert!((stats.coverage_percent - 50.0).abs() < 0.01);
    }

    #[test]
    fn test_vector_search() {
        let db = create_test_db();

        // Insert nodes
        let node1 = Node::module("src/similar.py");
        let node2 = Node::module("src/different.py");
        db.insert_node(&node1).unwrap();
        db.insert_node(&node2).unwrap();

        // Insert embeddings - one similar to query, one different (padded to 384 dims)
        let batch = vec![
            (
                "mod:src/similar.py".to_string(),
                test_embedding(&[1.0, 0.0, 0.0]),
                None,
            ),
            (
                "mod:src/different.py".to_string(),
                test_embedding(&[0.0, 1.0, 0.0]),
                None,
            ),
        ];
        db.insert_embeddings_batch(&batch, None).unwrap();

        // Search for vector similar to first embedding (padded to 384 dims)
        let query = test_embedding(&[0.9, 0.1, 0.0]);
        let results = db.vector_search(&query, 10, None).unwrap();

        assert_eq!(results.len(), 2);
        // First result should be the similar one
        assert_eq!(results[0].node_id, "mod:src/similar.py");
        assert!(results[0].similarity > results[1].similarity);
    }

    #[test]
    fn test_vector_search_with_threshold() {
        let db = create_test_db();

        // Insert nodes
        let node1 = Node::module("src/similar.py");
        let node2 = Node::module("src/different.py");
        db.insert_node(&node1).unwrap();
        db.insert_node(&node2).unwrap();

        // Insert embeddings (padded to 384 dims)
        let batch = vec![
            (
                "mod:src/similar.py".to_string(),
                test_embedding(&[1.0, 0.0, 0.0]),
                None,
            ),
            (
                "mod:src/different.py".to_string(),
                test_embedding(&[0.0, 1.0, 0.0]),
                None,
            ),
        ];
        db.insert_embeddings_batch(&batch, None).unwrap();

        // Search with high threshold - should only return similar (padded to 384 dims)
        let query = test_embedding(&[1.0, 0.0, 0.0]);
        let results = db.vector_search(&query, 10, Some(0.9)).unwrap();

        assert_eq!(results.len(), 1);
        assert_eq!(results[0].node_id, "mod:src/similar.py");
    }

    #[test]
    fn test_file_hashes() {
        let db = create_test_db();

        // Set file hashes
        let hashes = vec![
            ("src/a.py".to_string(), "hash_a".to_string()),
            ("src/b.py".to_string(), "hash_b".to_string()),
        ];
        db.set_file_hashes_batch(&hashes).unwrap();

        // Retrieve and verify
        let retrieved = db.get_all_file_hashes().unwrap();
        assert_eq!(retrieved.len(), 2);
        assert_eq!(retrieved.get("src/a.py"), Some(&"hash_a".to_string()));
        assert_eq!(retrieved.get("src/b.py"), Some(&"hash_b".to_string()));
    }

    #[test]
    fn test_get_stale_files() {
        let db = create_test_db();

        // Set initial file hashes
        let initial_hashes = vec![
            ("src/a.py".to_string(), "hash_a".to_string()),
            ("src/b.py".to_string(), "hash_b".to_string()),
        ];
        db.set_file_hashes_batch(&initial_hashes).unwrap();

        // Current hashes - a.py unchanged, b.py changed, c.py new
        let mut current_hashes = HashMap::new();
        current_hashes.insert("src/a.py".to_string(), "hash_a".to_string()); // Same
        current_hashes.insert("src/b.py".to_string(), "hash_b_new".to_string()); // Changed
        current_hashes.insert("src/c.py".to_string(), "hash_c".to_string()); // New

        let stale = db.get_stale_files(&current_hashes).unwrap();
        assert_eq!(stale.len(), 2);
        assert!(stale.contains(&"src/b.py".to_string()));
        assert!(stale.contains(&"src/c.py".to_string()));
    }

    #[test]
    fn test_cleanup_orphaned_embeddings() {
        let db = create_test_db();

        // Insert a node and its embedding (padded to 384 dims)
        let node = Node::module("src/test.py");
        db.insert_node(&node).unwrap();
        let batch = vec![(
            "mod:src/test.py".to_string(),
            test_embedding(&[0.1, 0.2, 0.3]),
            None,
        )];
        db.insert_embeddings_batch(&batch, None).unwrap();

        // Also insert an orphan embedding (no corresponding node)
        let orphan_batch = vec![(
            "mod:src/nonexistent.py".to_string(),
            test_embedding(&[0.4, 0.5, 0.6]),
            None,
        )];
        db.insert_embeddings_batch(&orphan_batch, None).unwrap();

        // Verify we have 2 embeddings
        let stats_before = db.embedding_stats().unwrap();
        assert_eq!(stats_before.nodes_with_embeddings, 2);

        // Cleanup orphans
        let deleted = db.cleanup_orphaned_embeddings().unwrap();
        assert_eq!(deleted, 1);

        // Verify we now have 1 embedding
        let stats_after = db.embedding_stats().unwrap();
        assert_eq!(stats_after.nodes_with_embeddings, 1);
    }

    // Note: cosine_similarity tests removed - now tested via DuckDB's array_cosine_similarity()
    // See migrations.rs tests for vector similarity validation

    // ========================================================================
    // HNSW Index Tests
    // ========================================================================

    #[test]
    fn test_hnsw_availability_detection_no_index() {
        // Fresh database should not have HNSW available
        let db = create_test_db();
        assert!(!db.has_hnsw_index());
    }

    #[test]
    fn test_hnsw_create_requires_embeddings() {
        // Cannot create HNSW on empty embeddings table
        let db = create_test_db();

        let result = db.create_hnsw_index();
        // Should fail because there are no embeddings
        assert!(result.is_err() || matches!(result, Ok(false)));
    }

    #[test]
    #[ignore = "Requires VSS extension to be installed"]
    fn test_hnsw_create_with_embeddings() {
        let db = create_test_db();

        // Create nodes
        let node1 = Node::module("src/a.py");
        let node2 = Node::module("src/b.py");
        db.insert_nodes(&[node1, node2]).unwrap();

        // Insert embeddings
        let batch = vec![
            ("mod:src/a.py".to_string(), test_embedding(&[1.0, 0.0, 0.0]), None),
            ("mod:src/b.py".to_string(), test_embedding(&[0.0, 1.0, 0.0]), None),
        ];
        db.insert_embeddings_batch(&batch, None).unwrap();

        // Create HNSW index
        let result = db.create_hnsw_index();
        if let Err(e) = &result {
            // VSS may not be available
            if e.to_string().contains("VSS") {
                return; // Skip test if VSS not available
            }
        }

        assert!(result.unwrap());
        assert!(db.has_hnsw_index());
    }

    #[test]
    #[ignore = "Requires VSS extension to be installed"]
    fn test_hnsw_vector_search_uses_index() {
        let db = create_test_db();

        // Create nodes
        let node1 = Node::module("src/a.py");
        let node2 = Node::module("src/b.py");
        db.insert_nodes(&[node1, node2]).unwrap();

        // Insert embeddings
        let batch = vec![
            ("mod:src/a.py".to_string(), test_embedding(&[1.0, 0.0, 0.0]), None),
            ("mod:src/b.py".to_string(), test_embedding(&[0.0, 1.0, 0.0]), None),
        ];
        db.insert_embeddings_batch(&batch, None).unwrap();

        // Create HNSW index
        let result = db.create_hnsw_index();
        if result.is_err() {
            return; // VSS not available
        }

        // Search should work with HNSW
        let query = test_embedding(&[0.9, 0.1, 0.0]);
        let results = db.vector_search(&query, 5, None).unwrap();

        // Should find node_a as closest match
        assert!(!results.is_empty());
        assert_eq!(results[0].node_id, "mod:src/a.py");
    }

    #[test]
    fn test_vector_search_fallback_without_hnsw() {
        // Vector search should work without HNSW (linear scan)
        let db = create_test_db();

        // Verify HNSW is not available
        assert!(!db.has_hnsw_index());

        // Create nodes and embeddings
        let node1 = Node::module("src/a.py");
        let node2 = Node::module("src/b.py");
        db.insert_nodes(&[node1, node2]).unwrap();

        let batch = vec![
            ("mod:src/a.py".to_string(), test_embedding(&[1.0, 0.0, 0.0]), None),
            ("mod:src/b.py".to_string(), test_embedding(&[0.0, 1.0, 0.0]), None),
        ];
        db.insert_embeddings_batch(&batch, None).unwrap();

        // Search should still work via linear scan
        let query = test_embedding(&[0.9, 0.1, 0.0]);
        let results = db.vector_search(&query, 5, None).unwrap();

        // Should find node_a as closest match
        assert!(!results.is_empty());
        assert_eq!(results[0].node_id, "mod:src/a.py");
    }

    #[test]
    fn test_drop_hnsw_index() {
        let db = create_test_db();

        // Drop should succeed even if index doesn't exist
        db.drop_hnsw_index().unwrap();
        assert!(!db.has_hnsw_index());
    }
}
