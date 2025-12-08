//! MU Daemon - High-performance code intelligence server.
//!
//! A single Rust binary that provides:
//! - HTTP API for code queries (MUQL, context, dependencies)
//! - File watching with incremental graph updates
//! - WebSocket for live updates
//! - MCP protocol support (stdio mode)

use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
use std::sync::atomic::AtomicUsize;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::{broadcast, RwLock};
use tracing::{info, Level};
use tracing_subscriber::FmtSubscriber;

mod build;
mod context;
mod muql;
mod server;
mod storage;
mod watcher;

use build::BuildPipeline;
use server::{create_router, AppState, ProjectManager};
use storage::MUbase;

/// MU code intelligence daemon
#[derive(Parser, Debug)]
#[command(name = "mu-daemon")]
#[command(about = "High-performance MU code intelligence daemon")]
#[command(version)]
struct Cli {
    /// Root directory to analyze and watch
    #[arg(default_value = ".")]
    root: PathBuf,

    /// HTTP port to listen on
    #[arg(short, long, default_value = "9120")]
    port: u16,

    /// Enable MCP mode (stdio protocol instead of HTTP)
    #[arg(long)]
    mcp: bool,

    /// Path to .mubase database file
    #[arg(long)]
    mubase: Option<PathBuf>,

    /// Build graph on startup
    #[arg(long)]
    build: bool,

    /// Enable verbose logging
    #[arg(short, long)]
    verbose: bool,

    /// Disable file watching
    #[arg(long)]
    no_watch: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();

    // Initialize logging
    let level = if cli.verbose { Level::DEBUG } else { Level::INFO };
    let subscriber = FmtSubscriber::builder()
        .with_max_level(level)
        .with_target(false)
        .compact()
        .init();

    // Resolve paths
    let root = cli.root.canonicalize().unwrap_or(cli.root.clone());
    let mubase_path = cli.mubase.unwrap_or_else(|| root.join(".mubase"));

    info!("Starting MU daemon for {:?}", root);
    info!("Database: {:?}", mubase_path);

    // Open or create mubase database
    info!("Opening database...");
    let mubase = MUbase::open(&mubase_path)?;
    info!("Database opened successfully");

    // Load graph from mubase
    let graph = mubase.load_graph()?;
    info!(
        "Graph loaded: {} nodes, {} edges",
        graph.node_count(),
        graph.edge_count()
    );

    // Create shared state
    let (event_tx, _) = broadcast::channel(1000);
    let mubase = Arc::new(RwLock::new(mubase));
    let graph = Arc::new(RwLock::new(graph));

    // Create project manager for multi-project support
    let projects = Arc::new(ProjectManager::new(
        mubase.clone(),
        graph.clone(),
        mubase_path.clone(),
        root.clone(),
    ));

    let state = AppState {
        mubase,
        graph,
        watcher_tx: event_tx.clone(),
        root: root.clone(),
        projects,
        start_time: Instant::now(),
        ws_connections: Arc::new(AtomicUsize::new(0)),
    };

    // Build graph if requested
    if cli.build {
        info!("Building graph from codebase...");
        let pipeline = BuildPipeline::new(state.clone());
        let result = pipeline.build(&root).await?;
        info!(
            "Build complete: {} nodes, {} edges in {:?}",
            result.node_count, result.edge_count, result.duration
        );
    }

    // Start file watcher (unless disabled)
    if !cli.no_watch && !cli.mcp {
        info!("Starting file watcher...");
        let watcher_state = state.clone();
        tokio::spawn(async move {
            if let Err(e) = watcher::watch_directory(root.clone(), watcher_state).await {
                tracing::error!("File watcher error: {}", e);
            }
        });
    }

    if cli.mcp {
        // MCP mode: communicate via stdio
        info!("Starting in MCP mode (stdio)");
        server::mcp::run_stdio(state).await
    } else {
        // HTTP mode
        let router = create_router(state);
        let addr = format!("0.0.0.0:{}", cli.port);
        let listener = tokio::net::TcpListener::bind(&addr).await?;
        info!("MU daemon listening on http://{}", addr);

        axum::serve(listener, router).await?;
        Ok(())
    }
}
