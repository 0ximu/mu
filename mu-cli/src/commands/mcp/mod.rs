//! MCP command - Model Context Protocol server for AI assistant integration
//!
//! Exposes MU capabilities as MCP tools that AI assistants like Claude can use
//! to understand and query codebases.

mod server;

use rmcp::{transport::stdio, ServiceExt};
use std::path::Path;

pub use server::MuMcpServer;

/// Find the mubase path starting from the given directory
fn find_mubase_path(start_dir: &Path) -> Option<std::path::PathBuf> {
    let mut current = start_dir.to_path_buf();
    loop {
        let mubase_path = current.join(".mu").join("mubase");
        if mubase_path.exists() {
            return Some(mubase_path);
        }
        if !current.pop() {
            return None;
        }
    }
}

/// Find the project root (directory containing .mu)
fn find_project_root(start_dir: &Path) -> Option<std::path::PathBuf> {
    let mut current = start_dir.to_path_buf();
    loop {
        let mu_dir = current.join(".mu");
        if mu_dir.exists() {
            return Some(current);
        }
        if !current.pop() {
            return None;
        }
    }
}

/// Run the MCP server
pub async fn run(path: &str) -> anyhow::Result<()> {
    let start_dir = if path == "." {
        std::env::current_dir()?
    } else {
        std::fs::canonicalize(path)?
    };

    // Find project root and mubase
    let project_root = find_project_root(&start_dir)
        .ok_or_else(|| anyhow::anyhow!("No .mu directory found. Run 'mu bootstrap' first."))?;

    let mubase_path = find_mubase_path(&start_dir)
        .ok_or_else(|| anyhow::anyhow!("No .mu/mubase found. Run 'mu bootstrap' first."))?;

    // Open database in read-only mode
    let mubase = mu_daemon::storage::MUbase::open_read_only(&mubase_path)?;

    // Create and run MCP server
    let server = MuMcpServer::new(mubase, project_root);

    // Serve over stdio
    let running_server = server.serve(stdio()).await?;

    // Wait for client to disconnect
    running_server.waiting().await?;

    Ok(())
}
