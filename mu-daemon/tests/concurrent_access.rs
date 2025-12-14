//! Concurrent database access integration tests.
//!
//! Tests that DuckDB's single-writer, multiple-reader concurrency model works:
//! - Daemon holds write lock (read-write mode)
//! - CLI can still perform read queries (read-only mode)
//! - No lock errors occur

use mu_daemon::storage::{AccessMode, Edge, MUbase, Node};
use std::sync::{Arc, Barrier};
use std::thread;
use std::time::Duration;
use tempfile::tempdir;

/// Test that multiple readers can access the database concurrently in read-only mode.
#[test]
fn test_concurrent_readers() {
    let dir = tempdir().expect("Failed to create temp dir");
    let db_path = dir.path().join("test.mubase");

    // Create database and insert some data (write mode)
    {
        let db = MUbase::open(&db_path).expect("Failed to open database");
        let node = Node::module("src/main.rs");
        db.insert_node(&node).expect("Failed to insert node");
    }

    // Open multiple read-only connections concurrently
    let db_path = Arc::new(db_path);
    let barrier = Arc::new(Barrier::new(3));

    let handles: Vec<_> = (0..3)
        .map(|i| {
            let path = Arc::clone(&db_path);
            let barrier = Arc::clone(&barrier);

            thread::spawn(move || {
                // Wait for all threads to be ready
                barrier.wait();

                // Open database in read-only mode and perform read query
                let db = MUbase::open_read_only(&*path)
                    .expect(&format!("Reader {} failed to open DB", i));
                let result = db.query("SELECT COUNT(*) as cnt FROM nodes");

                match result {
                    Ok(r) => {
                        assert!(!r.rows.is_empty(), "Reader {} should get results", i);
                        true
                    }
                    Err(e) => {
                        panic!("Reader {} got error: {}", i, e);
                    }
                }
            })
        })
        .collect();

    // All readers should succeed
    for (i, handle) in handles.into_iter().enumerate() {
        let result = handle
            .join()
            .expect(&format!("Reader thread {} panicked", i));
        assert!(result, "Reader {} should succeed", i);
    }
}

/// Test that a writer (daemon) and readers (CLI) can access the database concurrently.
/// Writer uses read-write mode, readers use read-only mode.
#[test]
fn test_daemon_write_cli_read_concurrent() {
    let dir = tempdir().expect("Failed to create temp dir");
    let db_path = dir.path().join("test.mubase");

    // Create database with initial data
    {
        let db = MUbase::open(&db_path).expect("Failed to open database");
        let node = Node::module("src/initial.rs");
        db.insert_node(&node)
            .expect("Failed to insert initial node");
    }

    let db_path = Arc::new(db_path);
    let barrier = Arc::new(Barrier::new(4)); // 1 writer + 3 readers

    // Spawn writer thread (simulates daemon holding write lock)
    let writer_path = Arc::clone(&db_path);
    let writer_barrier = Arc::clone(&barrier);
    let writer_handle = thread::spawn(move || {
        // Open in read-write mode (daemon mode)
        let db = MUbase::open(&*writer_path).expect("Writer (daemon) failed to open DB");

        // Wait for all threads to be ready
        writer_barrier.wait();

        // Perform writes while readers are active
        for i in 0..5 {
            let node = Node::module(&format!("src/module_{}.rs", i));
            match db.insert_node(&node) {
                Ok(_) => {}
                Err(e) => {
                    panic!("Writer failed on iteration {}: {}", i, e);
                }
            }
            thread::sleep(Duration::from_millis(10));
        }
        true
    });

    // Spawn reader threads (simulate CLI queries using read-only mode)
    let reader_handles: Vec<_> = (0..3)
        .map(|i| {
            let path = Arc::clone(&db_path);
            let barrier = Arc::clone(&barrier);

            thread::spawn(move || {
                // Wait for all threads to be ready
                barrier.wait();

                // Open in read-only mode (CLI mode)
                let db = MUbase::open_read_only(&*path)
                    .expect(&format!("Reader {} (CLI) failed to open DB", i));

                // Perform multiple reads while writer is active
                for j in 0..5 {
                    match db.query("SELECT * FROM nodes") {
                        Ok(_) => {}
                        Err(e) => {
                            // Check if this is a lock error
                            let err_str = e.to_string().to_lowercase();
                            if err_str.contains("lock") || err_str.contains("busy") {
                                panic!("Reader {} got lock error on iteration {}: {}", i, j, e);
                            }
                            // Other errors might be acceptable during concurrent access
                        }
                    }
                    thread::sleep(Duration::from_millis(5));
                }
                true
            })
        })
        .collect();

    // Wait for writer to complete
    let writer_result = writer_handle.join().expect("Writer thread panicked");
    assert!(writer_result, "Writer should succeed");

    // Wait for all readers to complete
    for (i, handle) in reader_handles.into_iter().enumerate() {
        let result = handle
            .join()
            .expect(&format!("Reader thread {} panicked", i));
        assert!(result, "Reader {} should succeed", i);
    }
}

/// Test that database stats can be read (read-only) while modifications are happening.
/// This is a common CLI operation pattern.
#[test]
fn test_stats_during_writes() {
    let dir = tempdir().expect("Failed to create temp dir");
    let db_path = dir.path().join("test.mubase");

    // Create database with initial data
    {
        let db = MUbase::open(&db_path).expect("Failed to open database");
        let node = Node::module("src/main.rs");
        db.insert_node(&node).expect("Failed to insert node");
    }

    let db_path = Arc::new(db_path);
    let barrier = Arc::new(Barrier::new(2));

    // Writer thread (daemon mode)
    let writer_path = Arc::clone(&db_path);
    let writer_barrier = Arc::clone(&barrier);
    let writer_handle = thread::spawn(move || {
        let db = MUbase::open(&*writer_path).expect("Writer failed to open DB");
        writer_barrier.wait();

        for i in 0..10 {
            let node = Node::module(&format!("src/file_{}.rs", i));
            db.insert_node(&node).expect("Failed to insert node");
            thread::sleep(Duration::from_millis(5));
        }
    });

    // Stats reader thread (CLI mode)
    let reader_path = Arc::clone(&db_path);
    let reader_barrier = Arc::clone(&barrier);
    let reader_handle = thread::spawn(move || {
        let db = MUbase::open_read_only(&*reader_path).expect("Reader failed to open DB");
        reader_barrier.wait();

        for _ in 0..10 {
            match db.stats() {
                Ok(stats) => {
                    // Stats should show some nodes (at least the initial one)
                    assert!(
                        stats.node_count >= 1,
                        "Should have at least 1 node, got {}",
                        stats.node_count
                    );
                }
                Err(e) => {
                    let err_str = e.to_string().to_lowercase();
                    if err_str.contains("lock") || err_str.contains("busy") {
                        panic!("Stats reader got lock error: {}", e);
                    }
                }
            }
            thread::sleep(Duration::from_millis(5));
        }
    });

    writer_handle.join().expect("Writer thread panicked");
    reader_handle.join().expect("Reader thread panicked");
}

/// Test that MUQL queries work in read-only mode during active writes.
/// This simulates `mu query` while daemon is indexing.
#[test]
fn test_query_during_indexing() {
    let dir = tempdir().expect("Failed to create temp dir");
    let db_path = dir.path().join("test.mubase");

    // Create database with initial data
    {
        let db = MUbase::open(&db_path).expect("Failed to open database");
        let node = Node::module("src/main.rs");
        db.insert_node(&node).expect("Failed to insert node");
    }

    let db_path = Arc::new(db_path);
    let barrier = Arc::new(Barrier::new(2));

    // Indexer thread (simulates daemon building graph)
    let indexer_path = Arc::clone(&db_path);
    let indexer_barrier = Arc::clone(&barrier);
    let indexer_handle = thread::spawn(move || {
        let db = MUbase::open(&*indexer_path).expect("Indexer failed to open DB");
        indexer_barrier.wait();

        // Simulate indexing: batch insert nodes
        let nodes: Vec<Node> = (0..20)
            .map(|i| Node::module(&format!("src/indexed_{}.rs", i)))
            .collect();

        for chunk in nodes.chunks(5) {
            db.insert_nodes(chunk)
                .expect("Failed to batch insert nodes");
            thread::sleep(Duration::from_millis(10));
        }
    });

    // Query thread (simulates CLI user running queries in read-only mode)
    let query_path = Arc::clone(&db_path);
    let query_barrier = Arc::clone(&barrier);
    let query_handle = thread::spawn(move || {
        let db = MUbase::open_read_only(&*query_path).expect("Query reader failed to open DB");
        query_barrier.wait();

        // Run various MUQL-style queries
        let queries = [
            "SELECT * FROM nodes WHERE type = 'module'",
            "SELECT COUNT(*) FROM nodes",
            "SELECT name, file_path FROM nodes LIMIT 5",
            "SELECT * FROM nodes ORDER BY name",
        ];

        for _ in 0..5 {
            for query in &queries {
                match db.query(query) {
                    Ok(_) => {}
                    Err(e) => {
                        let err_str = e.to_string().to_lowercase();
                        if err_str.contains("lock") || err_str.contains("busy") {
                            panic!("Query got lock error for '{}': {}", query, e);
                        }
                        // Syntax errors or empty results are ok
                    }
                }
            }
            thread::sleep(Duration::from_millis(5));
        }
    });

    indexer_handle.join().expect("Indexer thread panicked");
    query_handle.join().expect("Query thread panicked");
}

/// Test that graph loading works in read-only mode during writes.
/// This tests the load_graph() method used for graph traversal.
#[test]
fn test_graph_load_during_writes() {
    let dir = tempdir().expect("Failed to create temp dir");
    let db_path = dir.path().join("test.mubase");

    // Create database with initial data
    {
        let db = MUbase::open(&db_path).expect("Failed to open database");
        let node1 = Node::module("src/a.rs");
        let node2 = Node::module("src/b.rs");
        db.insert_node(&node1).expect("Failed to insert node1");
        db.insert_node(&node2).expect("Failed to insert node2");

        let edge = Edge::imports("mod:src/a.rs", "mod:src/b.rs");
        db.insert_edge(&edge).expect("Failed to insert edge");
    }

    let db_path = Arc::new(db_path);
    let barrier = Arc::new(Barrier::new(2));

    // Writer thread
    let writer_path = Arc::clone(&db_path);
    let writer_barrier = Arc::clone(&barrier);
    let writer_handle = thread::spawn(move || {
        let db = MUbase::open(&*writer_path).expect("Writer failed to open DB");
        writer_barrier.wait();

        for i in 0..10 {
            let node = Node::module(&format!("src/new_{}.rs", i));
            db.insert_node(&node).expect("Failed to insert node");

            let edge = Edge::imports(&format!("mod:src/new_{}.rs", i), "mod:src/a.rs");
            db.insert_edge(&edge).expect("Failed to insert edge");

            thread::sleep(Duration::from_millis(5));
        }
    });

    // Graph loader thread (read-only mode)
    let loader_path = Arc::clone(&db_path);
    let loader_barrier = Arc::clone(&barrier);
    let loader_handle = thread::spawn(move || {
        let db = MUbase::open_read_only(&*loader_path).expect("Loader failed to open DB");
        loader_barrier.wait();

        for _ in 0..10 {
            match db.load_graph() {
                Ok(graph) => {
                    // Graph should have at least the initial nodes
                    assert!(
                        graph.node_count() >= 2,
                        "Should have at least 2 nodes, got {}",
                        graph.node_count()
                    );
                }
                Err(e) => {
                    let err_str = e.to_string().to_lowercase();
                    if err_str.contains("lock") || err_str.contains("busy") {
                        panic!("Graph loader got lock error: {}", e);
                    }
                }
            }
            thread::sleep(Duration::from_millis(5));
        }
    });

    writer_handle.join().expect("Writer thread panicked");
    loader_handle.join().expect("Loader thread panicked");
}

/// Test that AccessMode enum works correctly.
#[test]
fn test_access_mode_enum() {
    assert_eq!(AccessMode::default(), AccessMode::ReadWrite);

    let dir = tempdir().expect("Failed to create temp dir");
    let db_path = dir.path().join("test.mubase");

    // Create with explicit mode
    {
        let db = MUbase::open_with_mode(&db_path, AccessMode::ReadWrite)
            .expect("Failed to open with ReadWrite mode");
        let node = Node::module("src/test.rs");
        db.insert_node(&node).expect("Failed to insert node");
    }

    // Open with read-only mode
    {
        let db = MUbase::open_with_mode(&db_path, AccessMode::ReadOnly)
            .expect("Failed to open with ReadOnly mode");
        let stats = db.stats().expect("Failed to get stats");
        assert_eq!(stats.node_count, 1);
    }
}

/// Test that write operations fail in read-only mode.
#[test]
fn test_read_only_prevents_writes() {
    let dir = tempdir().expect("Failed to create temp dir");
    let db_path = dir.path().join("test.mubase");

    // Create database first
    {
        let db = MUbase::open(&db_path).expect("Failed to create database");
        let node = Node::module("src/initial.rs");
        db.insert_node(&node).expect("Failed to insert node");
    }

    // Try to write in read-only mode - should fail
    {
        let db = MUbase::open_read_only(&db_path).expect("Failed to open read-only");
        let node = Node::module("src/new.rs");
        let result = db.insert_node(&node);

        assert!(result.is_err(), "Insert should fail in read-only mode");

        let err_str = result.unwrap_err().to_string().to_lowercase();
        assert!(
            err_str.contains("read")
                || err_str.contains("permission")
                || err_str.contains("cannot"),
            "Error should mention read-only restriction: {}",
            err_str
        );
    }
}
