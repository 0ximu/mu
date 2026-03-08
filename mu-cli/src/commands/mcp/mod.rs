//! MCP command - Model Context Protocol server for AI assistant integration
//!
//! Exposes MU capabilities as MCP tools that AI assistants like Claude can use
//! to understand and query codebases.

mod server;

use rmcp::{transport::stdio, ServiceExt};

pub use server::MuMcpServer;

/// Run the MCP server
///
/// The server now supports dynamic project detection via MCP client roots.
/// If the client provides roots during initialization, the server will use
/// the first root as the project directory instead of relying on its CWD.
///
/// This means you can start the server from anywhere - as long as the client
/// (e.g., Claude Code) tells it where to look, MU will find the right project.
pub async fn run(path: &str) -> anyhow::Result<()> {
    // Use provided path or CWD as fallback
    // Note: The actual project may be overridden by client roots during MCP init
    let fallback_dir = if path == "." {
        std::env::current_dir()?
    } else {
        std::fs::canonicalize(path)?
    };

    // Create server with lazy initialization
    // The mubase won't be opened until the first tool call, and will use
    // client-provided roots if available
    let server = MuMcpServer::new(fallback_dir);

    // Serve over stdio
    let running_server = server.serve(stdio()).await?;

    // Wait for client to disconnect
    running_server.waiting().await?;

    Ok(())
}
