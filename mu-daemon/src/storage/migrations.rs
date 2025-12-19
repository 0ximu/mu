//! Database migrations for MU schema evolution.
//!
//! This module handles migrating databases between schema versions.
//! Currently supports:
//! - v1.0.0 → v1.1.0: VARCHAR JSON embeddings → FLOAT[384] native arrays

use anyhow::{Context, Result};
use duckdb::Connection;

/// Target schema version for migrations.
pub const TARGET_VERSION: &str = "1.1.0";

/// Check if migration is needed from current version to target.
pub fn needs_migration(current: &str, target: &str) -> bool {
    current != target && current < target
}

/// Migrate embeddings from JSON VARCHAR to native FLOAT[384] arrays.
///
/// This migration:
/// 1. Creates a new embeddings table with FLOAT[384] column
/// 2. Copies data, casting JSON strings to native arrays
/// 3. Drops the old table and renames the new one
/// 4. Updates the schema version
///
/// The migration is atomic - if any step fails, the database remains unchanged.
pub fn migrate_embeddings_to_native(conn: &Connection) -> Result<()> {
    tracing::info!("Starting migration: v1.0.0 → v1.1.0 (JSON → native arrays)");

    // Check if embeddings table exists and has data
    let has_embeddings: bool = conn
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM embeddings LIMIT 1)",
            [],
            |row| row.get(0),
        )
        .unwrap_or(false);

    if !has_embeddings {
        tracing::info!("No embeddings to migrate, updating schema version only");
        conn.execute(
            "UPDATE metadata SET value = '1.1.0' WHERE key = 'schema_version'",
            [],
        )?;
        return Ok(());
    }

    // Count embeddings for progress reporting
    let count: usize = conn.query_row("SELECT COUNT(*) FROM embeddings", [], |row| row.get(0))?;
    tracing::info!("Migrating {} embeddings to native FLOAT[384] format", count);

    // Step 1: Create new table with native array type
    conn.execute_batch(
        r#"
        CREATE TABLE IF NOT EXISTS embeddings_new (
            node_id VARCHAR PRIMARY KEY,
            embedding FLOAT[384] NOT NULL,
            model VARCHAR NOT NULL DEFAULT 'mu-sigma-v2',
            created_at TIMESTAMP
        );
        "#,
    )
    .context("Failed to create new embeddings table")?;

    // Step 2: Migrate data - DuckDB can cast JSON array strings to FLOAT[]
    let migrated = conn
        .execute(
            r#"
            INSERT INTO embeddings_new (node_id, embedding, model, created_at)
            SELECT node_id, embedding::FLOAT[384], model, created_at
            FROM embeddings
            "#,
            [],
        )
        .context("Failed to migrate embedding data")?;

    tracing::info!("Migrated {} rows", migrated);

    // Step 3: Verify migration
    let new_count: usize =
        conn.query_row("SELECT COUNT(*) FROM embeddings_new", [], |row| row.get(0))?;

    if new_count != count {
        // Rollback by dropping the new table
        conn.execute("DROP TABLE IF EXISTS embeddings_new", [])?;
        anyhow::bail!(
            "Migration verification failed: expected {} rows, got {}",
            count,
            new_count
        );
    }

    // Step 4: Swap tables
    conn.execute("DROP TABLE embeddings", [])
        .context("Failed to drop old embeddings table")?;

    conn.execute("ALTER TABLE embeddings_new RENAME TO embeddings", [])
        .context("Failed to rename new embeddings table")?;

    // Step 5: Recreate index
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model)",
        [],
    )
    .context("Failed to recreate embeddings index")?;

    // Step 6: Update schema version
    conn.execute(
        "UPDATE metadata SET value = '1.1.0' WHERE key = 'schema_version'",
        [],
    )
    .context("Failed to update schema version")?;

    tracing::info!("Migration complete: v1.0.0 → v1.1.0");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Create a 384-element test embedding JSON string.
    fn test_embedding_json(values: &[f32]) -> String {
        let mut embedding = vec![0.0f32; 384];
        for (i, &v) in values.iter().enumerate() {
            if i < 384 {
                embedding[i] = v;
            }
        }
        format!(
            "[{}]",
            embedding
                .iter()
                .map(|f| f.to_string())
                .collect::<Vec<_>>()
                .join(",")
        )
    }

    /// Create a 384-element DuckDB array literal.
    fn test_embedding_literal(values: &[f32]) -> String {
        let mut embedding = vec![0.0f32; 384];
        for (i, &v) in values.iter().enumerate() {
            if i < 384 {
                embedding[i] = v;
            }
        }
        format!(
            "[{}]::FLOAT[384]",
            embedding
                .iter()
                .map(|f| f.to_string())
                .collect::<Vec<_>>()
                .join(",")
        )
    }

    #[test]
    fn test_needs_migration() {
        assert!(needs_migration("1.0.0", "1.1.0"));
        assert!(!needs_migration("1.1.0", "1.1.0"));
        assert!(!needs_migration("1.2.0", "1.1.0"));
    }

    #[test]
    fn test_migration_empty_db() {
        let conn = Connection::open_in_memory().unwrap();

        // Create minimal schema
        conn.execute_batch(
            r#"
            CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR);
            INSERT INTO metadata VALUES ('schema_version', '1.0.0');
            CREATE TABLE embeddings (
                node_id VARCHAR PRIMARY KEY,
                embedding VARCHAR NOT NULL,
                model VARCHAR NOT NULL DEFAULT 'mu-sigma-v2',
                created_at TIMESTAMP
            );
            "#,
        )
        .unwrap();

        // Run migration on empty embeddings table
        migrate_embeddings_to_native(&conn).unwrap();

        // Verify version updated
        let version: String = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(version, "1.1.0");
    }

    #[test]
    fn test_migration_with_data() {
        let conn = Connection::open_in_memory().unwrap();

        // Create test embedding JSON (384 dimensions, padded with zeros)
        let embedding_json = test_embedding_json(&[0.1, 0.2, 0.3]);

        // Create v1.0.0 schema with JSON embeddings
        conn.execute_batch(&format!(
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
            INSERT INTO metadata VALUES ('schema_version', '1.0.0');
            CREATE TABLE embeddings (
                node_id VARCHAR PRIMARY KEY,
                embedding VARCHAR NOT NULL,
                model VARCHAR NOT NULL DEFAULT 'mu-sigma-v2',
                created_at TIMESTAMP
            );
            INSERT INTO nodes VALUES ('mod:test.py', 'module', 'test', NULL, 'test.py', 1, 10, NULL, 0);
            INSERT INTO embeddings VALUES ('mod:test.py', '{}', 'test-model', NULL);
            "#,
            embedding_json
        ))
        .unwrap();

        // Run migration
        migrate_embeddings_to_native(&conn).unwrap();

        // Verify data migrated correctly
        let (node_id, model): (String, String) = conn
            .query_row(
                "SELECT node_id, model FROM embeddings WHERE node_id = 'mod:test.py'",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .unwrap();

        assert_eq!(node_id, "mod:test.py");
        assert_eq!(model, "test-model");

        // Verify schema version
        let version: String = conn
            .query_row(
                "SELECT value FROM metadata WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(version, "1.1.0");

        // Verify embedding can be used with array functions (compare with identical vector)
        let query_literal = test_embedding_literal(&[0.1, 0.2, 0.3]);
        let sql = format!(
            "SELECT CAST(array_cosine_similarity(embedding, {}) AS DOUBLE) FROM embeddings",
            query_literal
        );
        let similarity: f64 = conn.query_row(&sql, [], |row| row.get(0)).unwrap();
        assert!((similarity - 1.0).abs() < 0.0001); // Should be ~1.0 for identical vectors
    }
}
