//! Database migrations for MU schema evolution.
//!
//! This module handles migrating databases between schema versions.
//! Databases older than v1.1.0 must be rebuilt with `mu bootstrap`.

use anyhow::{Context, Result};
use duckdb::Connection;
use std::cmp::Ordering;

/// Compare two dotted version strings numerically, component by component.
///
/// String comparison gets this wrong: "1.10.0" < "1.2.0" lexicographically.
/// Missing or non-numeric components are treated as 0.
pub fn compare_semver(a: &str, b: &str) -> Ordering {
    let parse = |v: &str| -> Vec<u64> {
        v.split('.')
            .map(|c| c.trim().parse::<u64>().unwrap_or(0))
            .collect()
    };
    let (av, bv) = (parse(a), parse(b));
    let len = av.len().max(bv.len());
    for i in 0..len {
        let x = av.get(i).copied().unwrap_or(0);
        let y = bv.get(i).copied().unwrap_or(0);
        match x.cmp(&y) {
            Ordering::Equal => continue,
            other => return other,
        }
    }
    Ordering::Equal
}

/// Check if migration is needed from current version to target.
#[cfg(test)]
pub fn needs_migration(current: &str, target: &str) -> bool {
    compare_semver(current, target) == Ordering::Less
}

/// Migrate v1.1.0 → v1.2.0: Add source_text column to nodes table.
///
/// This migration adds a TEXT column for storing searchable source text
/// (docstrings, signatures, body previews) alongside each node.
pub fn migrate_add_source_text(conn: &Connection) -> Result<()> {
    tracing::info!("Starting migration: v1.1.0 → v1.2.0 (add source_text column)");

    // Verify we're at the expected version
    let version: String = conn
        .query_row(
            "SELECT value FROM metadata WHERE key = 'schema_version'",
            [],
            |row| row.get(0),
        )
        .unwrap_or_else(|_| "unknown".to_string());

    if version != "1.1.0" {
        anyhow::bail!(
            "Cannot migrate: expected schema version 1.1.0, found {}",
            version
        );
    }

    // Add the column
    conn.execute("ALTER TABLE nodes ADD COLUMN source_text TEXT", [])
        .context("Failed to add source_text column")?;

    // Update schema version
    conn.execute(
        "UPDATE metadata SET value = '1.2.0' WHERE key = 'schema_version'",
        [],
    )
    .context("Failed to update schema version")?;

    tracing::info!("Migration complete: v1.1.0 → v1.2.0");
    Ok(())
}

/// Migrate v1.2.0 -> v2.0.0: Add V3 search columns (summary, importance, search_text).
pub fn migrate_v1_2_to_v2(conn: &Connection) -> Result<()> {
    tracing::info!("Starting migration: v1.2.0 → v2.0.0 (V3 search)");

    let cols = [
        ("summary_text", "ALTER TABLE nodes ADD COLUMN summary_text TEXT"),
        ("summary_source", "ALTER TABLE nodes ADD COLUMN summary_source VARCHAR DEFAULT 'heuristic'"),
        ("summary_code_hash", "ALTER TABLE nodes ADD COLUMN summary_code_hash VARCHAR"),
        ("importance_score", "ALTER TABLE nodes ADD COLUMN importance_score FLOAT DEFAULT 0.0"),
        ("search_text", "ALTER TABLE nodes ADD COLUMN search_text TEXT"),
        ("summary_updated_at", "ALTER TABLE nodes ADD COLUMN summary_updated_at TIMESTAMP"),
    ];

    for (col_name, ddl) in &cols {
        // Check if column already exists (idempotent)
        let exists: bool = conn.query_row(
            &format!(
                "SELECT COUNT(*) > 0 FROM information_schema.columns WHERE table_name='nodes' AND column_name='{}'",
                col_name
            ),
            [],
            |row| row.get(0),
        ).unwrap_or(false);

        if !exists {
            conn.execute(ddl, [])?;
            tracing::info!("Added column: {}", col_name);
        }
    }

    conn.execute_batch("
        CREATE INDEX IF NOT EXISTS idx_nodes_importance ON nodes(importance_score DESC);
        CREATE INDEX IF NOT EXISTS idx_nodes_summary_source ON nodes(summary_source);
    ")?;

    conn.execute(
        "UPDATE metadata SET value = '2.0.0' WHERE key = 'schema_version'",
        [],
    )?;

    tracing::info!("Migration v1.2.0 → v2.0.0 complete");
    Ok(())
}

/// Migrate v2.0.0 → v2.1.0: Add node_category column for classify-once-at-bootstrap.
pub fn migrate_v2_to_v2_1(conn: &Connection) -> Result<()> {
    tracing::info!("Starting migration: v2.0.0 → v2.1.0 (add node_category)");
    conn.execute_batch("ALTER TABLE nodes ADD COLUMN node_category VARCHAR DEFAULT 'production'")?;
    conn.execute_batch("CREATE INDEX IF NOT EXISTS idx_nodes_category ON nodes(node_category)")?;
    conn.execute("UPDATE metadata SET value = '2.1.0' WHERE key = 'schema_version'", [])?;
    tracing::info!("Migration v2.0.0 → v2.1.0 complete");
    Ok(())
}

/// Migrate v2.1.0 → v2.2.0: Drop the embeddings table.
///
/// Vector search was removed from the product (search is BM25 + importance);
/// the table was only ever populated by a long-gone v1 pipeline.
pub fn migrate_v2_1_to_v2_2(conn: &Connection) -> Result<()> {
    tracing::info!("Starting migration: v2.1.0 → v2.2.0 (drop embeddings table)");
    conn.execute_batch("DROP INDEX IF EXISTS idx_embeddings_model")?;
    conn.execute_batch("DROP TABLE IF EXISTS embeddings")?;
    conn.execute("UPDATE metadata SET value = '2.2.0' WHERE key = 'schema_version'", [])?;
    tracing::info!("Migration v2.1.0 → v2.2.0 complete");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_needs_migration() {
        assert!(needs_migration("1.0.0", "1.2.0"));
        assert!(needs_migration("1.1.0", "1.2.0"));
        assert!(!needs_migration("1.2.0", "1.2.0"));
        // Numeric compare: 1.10.0 is newer than 1.2.0, no migration needed
        assert!(!needs_migration("1.10.0", "1.2.0"));
        assert!(needs_migration("1.2.0", "1.10.0"));
    }

    #[test]
    fn test_compare_semver_numeric_not_lexicographic() {
        // The lexicographic trap: "1.10.0" < "1.2.0" as strings.
        assert_eq!(compare_semver("1.10.0", "1.2.0"), Ordering::Greater);
        assert_eq!(compare_semver("1.2.0", "1.10.0"), Ordering::Less);
    }

    #[test]
    fn test_compare_semver_equal() {
        assert_eq!(compare_semver("2.1.0", "2.1.0"), Ordering::Equal);
        // Missing components count as zero
        assert_eq!(compare_semver("2.1", "2.1.0"), Ordering::Equal);
    }

    #[test]
    fn test_compare_semver_ordering() {
        assert_eq!(compare_semver("1.0.0", "2.0.0"), Ordering::Less);
        assert_eq!(compare_semver("2.1.0", "2.0.0"), Ordering::Greater);
        assert_eq!(compare_semver("0.9.0", "1.0.0"), Ordering::Less);
    }

    #[test]
    fn test_migrate_v2_1_to_v2_2_drops_embeddings() {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            r#"
            CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR);
            INSERT INTO metadata VALUES ('schema_version', '2.1.0');
            CREATE TABLE embeddings (
                node_id VARCHAR PRIMARY KEY,
                embedding FLOAT[384] NOT NULL,
                model VARCHAR NOT NULL,
                created_at TIMESTAMP
            );
            "#,
        )
        .unwrap();

        migrate_v2_1_to_v2_2(&conn).unwrap();

        let version: String = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(version, "2.2.0");
        assert!(conn.query_row("SELECT 1 FROM embeddings", [], |_| Ok(())).is_err());

        // Idempotent: running again on a DB without the table succeeds
        migrate_v2_1_to_v2_2(&conn).unwrap();
    }

    #[test]
    fn test_migrate_add_source_text() {
        let conn = Connection::open_in_memory().unwrap();

        // Create v1.1.0 schema (nodes table without source_text)
        conn.execute_batch(
            r#"
            CREATE TABLE nodes (
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
            CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR);
            INSERT INTO metadata VALUES ('schema_version', '1.1.0');
            INSERT INTO nodes VALUES ('fn:test.py:main', 'function', 'main', 'test.py:main', 'test.py', 1, 10, NULL, 3);
            "#,
        )
        .unwrap();

        // Run migration
        migrate_add_source_text(&conn).unwrap();

        // Verify version updated
        let version: String = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(version, "1.2.0");

        // Verify source_text column exists and is NULL for existing rows
        let source_text: Option<String> = conn
            .query_row(
                "SELECT source_text FROM nodes WHERE id = 'fn:test.py:main'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(source_text, None);

        // Verify we can write to the new column
        conn.execute(
            "UPDATE nodes SET source_text = 'fn main() -> Result<()>' WHERE id = 'fn:test.py:main'",
            [],
        )
        .unwrap();

        let source_text: Option<String> = conn
            .query_row(
                "SELECT source_text FROM nodes WHERE id = 'fn:test.py:main'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(source_text, Some("fn main() -> Result<()>".to_string()));
    }

    #[test]
    fn test_migrate_add_source_text_wrong_version() {
        let conn = Connection::open_in_memory().unwrap();

        conn.execute_batch(
            r#"
            CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR);
            INSERT INTO metadata VALUES ('schema_version', '1.0.0');
            "#,
        )
        .unwrap();

        // Should fail because version is 1.0.0, not 1.1.0
        let result = migrate_add_source_text(&conn);
        assert!(result.is_err());
    }
}
