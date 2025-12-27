//! MU CLI - Command-line interface for Machine Understanding
//!
//! A semantic compression tool that translates codebases into token-efficient
//! representations optimized for LLM comprehension.

use clap::{CommandFactory, Parser, Subcommand};
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

/// Parse and validate threshold value (must be between 0.0 and 1.0)
fn parse_threshold(s: &str) -> Result<f32, String> {
    let value: f32 = s
        .parse()
        .map_err(|_| format!("'{}' is not a valid number", s))?;
    if !(0.0..=1.0).contains(&value) {
        return Err(format!(
            "threshold must be between 0.0 and 1.0, got {}",
            value
        ));
    }
    Ok(value)
}

mod cache;
mod commands;
mod config;
mod output;
mod tsconfig;

use commands::*;
use config::MuConfig;
use output::OutputFormat;

/// Semantic code intelligence for AI-native development.
///
/// MU parses your codebase into a semantic graph with fast queries,
/// semantic search, and intelligent context extraction. Feed your
/// entire codebase to an AI in seconds, not hours.
#[derive(Parser)]
#[command(name = "mu")]
#[command(author, version)]
#[command(about = "Semantic code intelligence for AI-native development")]
#[command(
    long_about = "MU parses your codebase into a semantic graph with fast queries,\nsemantic search, and intelligent context extraction.\n\n92-98% compression while preserving semantic signal."
)]
#[command(propagate_version = true)]
#[command(next_help_heading = "Options")]
#[command(after_help = "Quick Start:
  mu bootstrap      Initialize code graph (run this first)
  mu status         Check project status
  mu search \"auth\"  Find auth-related code
  mu deps MyClass   Show dependencies of MyClass

Examples:
  mu q \"fn c>50\"    Query functions with complexity > 50
  mu impact Parser  What breaks if I change Parser?
  mu grok \"auth\"    Semantic search with context")]
pub struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,

    /// Enable verbose output (debug logging)
    #[arg(short, long, global = true)]
    verbose: bool,

    /// Suppress all output except errors
    #[arg(short, long, global = true)]
    quiet: bool,

    /// Output format (overrides config default)
    #[arg(long, global = true, value_enum)]
    format: Option<OutputFormat>,

    /// Show detailed version information
    #[arg(long = "version-verbose")]
    version_verbose: bool,
}

#[derive(Subcommand)]
enum Commands {
    // ==================== Getting Started ====================
    /// Initialize and build MU database in one step
    #[command(visible_alias = "bs", visible_alias = "init")]
    Bootstrap {
        /// Path to analyze (defaults to current directory)
        #[arg(default_value = ".")]
        path: String,

        /// Force rebuild even if database exists
        #[arg(short, long)]
        force: bool,

        /// Generate embeddings for semantic search (enables mu search)
        #[arg(short, long)]
        embed: bool,

        /// Skip embedding generation without prompting
        #[arg(long, conflicts_with = "embed")]
        no_embed: bool,

        /// Fail on .murc.toml errors instead of silently using defaults
        #[arg(long)]
        strict: bool,
    },

    /// Compress codebase into hierarchical MU sigil format
    #[command(visible_alias = "c")]
    Compress {
        /// Path to compress (file or directory)
        #[arg(default_value = ".")]
        path: String,

        /// Output file (default: stdout)
        #[arg(short, long)]
        output: Option<String>,

        /// Detail level: low, medium, high
        #[arg(short, long, default_value = "medium")]
        detail: String,
    },

    /// Show project status and recommended next steps
    #[command(visible_alias = "st")]
    Status {
        /// Path to check (defaults to current directory)
        #[arg(default_value = ".")]
        path: String,
    },

    /// Generate or update embeddings (incremental by default)
    Embed {
        /// Path to analyze (defaults to current directory)
        #[arg(default_value = ".")]
        path: String,

        /// Force regenerate all embeddings (not incremental)
        #[arg(short, long)]
        force: bool,

        /// Show embedding status without updating
        #[arg(long)]
        status: bool,
    },

    /// Semantic search across the codebase
    Search {
        /// Search query
        query: String,

        /// Maximum results to return
        #[arg(short = 'n', long = "limit", default_value = "10")]
        limit: usize,

        /// Minimum similarity threshold (0.0-1.0)
        #[arg(short, long, default_value = "0.1", value_parser = parse_threshold)]
        threshold: f32,
    },

    /// Find relevant code context for a question (semantic search)
    Grok {
        /// Question or topic to find context for
        question: String,

        /// Number of context chunks to retrieve (1-3)
        #[arg(short, long, default_value = "2")]
        depth: u8,
    },

    /// Execute a MUQL query
    #[command(visible_alias = "q")]
    Query {
        /// MUQL query string (optional if using --interactive, --examples, or --schema)
        query: Option<String>,

        /// Interactive REPL mode
        #[arg(short, long)]
        interactive: bool,

        /// Limit number of results (overrides LIMIT in query)
        #[arg(short, long)]
        limit: Option<usize>,

        /// Show MUQL query examples
        #[arg(long)]
        examples: bool,

        /// Show MUQL schema reference (tables, columns, edge types)
        #[arg(long)]
        schema: bool,
    },

    /// Show dependencies of a node (what this node depends on)
    Deps {
        /// Node to analyze
        node: String,

        /// Show reverse dependencies (what depends on this)
        #[arg(short, long)]
        reverse: bool,

        /// Maximum depth to traverse
        #[arg(short, long, default_value = "1")]
        depth: u8,

        /// Include 'contains' edges (classes/functions within modules)
        #[arg(long)]
        include_contains: bool,
    },

    /// Show what depends on a node (reverse dependencies)
    #[command(visible_alias = "rdeps")]
    Usedby {
        /// Node to analyze
        node: String,

        /// Maximum depth to traverse
        #[arg(short, long, default_value = "1")]
        depth: u8,

        /// Include 'contains' edges (classes/functions within modules)
        #[arg(long)]
        include_contains: bool,
    },

    /// Read and display a file with MU context
    Read {
        /// File path to read
        path: String,

        /// Show line numbers
        #[arg(short = 'n', long)]
        line_numbers: bool,
    },

    /// Semantic diff between git refs
    Diff {
        /// Base git ref (branch, commit, tag)
        base_ref: String,

        /// Head git ref (branch, commit, tag) - defaults to HEAD
        #[arg(default_value = "HEAD")]
        head_ref: String,
    },

    /// Find downstream impact (what might break if this node changes)
    Impact {
        /// Node to analyze
        node: String,

        /// Maximum depth to traverse (default: unlimited)
        #[arg(short, long)]
        depth: Option<u8>,

        /// Filter by edge types (e.g., imports,calls)
        #[arg(short, long, value_delimiter = ',')]
        edge_types: Option<Vec<String>>,
    },

    /// Find upstream ancestors (what this node depends on)
    Ancestors {
        /// Node to analyze
        node: String,

        /// Maximum depth to traverse (default: unlimited)
        #[arg(short, long)]
        depth: Option<u8>,

        /// Filter by edge types (e.g., imports,calls)
        #[arg(short, long, value_delimiter = ',')]
        edge_types: Option<Vec<String>>,
    },

    /// Detect circular dependencies in the codebase
    Cycles {
        /// Filter by edge types (e.g., imports,calls)
        #[arg(short, long, value_delimiter = ',')]
        edge_types: Option<Vec<String>>,
    },

    /// Find shortest path between two nodes
    Path {
        /// Source node
        from: String,

        /// Target node
        to: String,

        /// Filter by edge types (e.g., imports,calls)
        #[arg(short, long, value_delimiter = ',')]
        edge_types: Option<Vec<String>>,
    },

    // ==================== Vibes ====================
    /// Impact analysis with flair - what breaks if this changes?
    Yolo {
        /// Path to fix
        #[arg(default_value = ".")]
        path: String,
    },

    /// Find sus code - security risks, complexity, missing tests
    Sus {
        /// File to analyze, or "." to scan entire codebase
        #[arg(default_value = ".")]
        path: String,

        /// Minimum warning level to show (1=info, 2=warn, 3=error)
        #[arg(short, long, default_value = "1")]
        threshold: u8,
    },

    /// Git archaeology - why does this code exist?
    Wtf {
        /// File path to analyze (shows origin, evolution, and files that change together)
        target: Option<String>,
    },

    /// OMEGA compressed overview - feed your whole codebase to an LLM
    Omg {
        /// Maximum tokens for output
        #[arg(short = 't', long, default_value = "8000")]
        max_tokens: usize,

        /// Exclude relationship edges from output
        #[arg(long)]
        no_edges: bool,
    },

    /// Naming convention check - does the code pass the vibe check?
    Vibe {
        /// Path to vibe check
        #[arg(default_value = ".")]
        path: String,

        /// Force a specific naming convention (overrides language detection)
        /// Valid options: snake, pascal, camel, screaming
        #[arg(long)]
        convention: Option<String>,
    },

    /// Achieve enlightenment - clear caches and temp files
    Zen {
        /// Path to clean
        #[arg(default_value = ".")]
        path: String,

        /// Skip confirmation prompt
        #[arg(short, long)]
        yes: bool,

        /// Full reset: remove ALL MU files (.mu/, .murc.toml, .mubase)
        #[arg(short, long)]
        reset: bool,
    },

    // ==================== Analysis & Export ====================
    /// Detect code patterns in the codebase
    Patterns {
        /// Filter by pattern category
        #[arg(short, long, value_parser = ["naming", "architecture", "testing", "imports", "error_handling", "api", "async", "logging"])]
        category: Option<String>,

        /// Force re-analysis (ignore cache)
        #[arg(long)]
        refresh: bool,

        /// Include code examples in output
        #[arg(long)]
        examples: bool,
    },

    /// Export the code graph to various formats
    Export {
        /// Export format (mu, json, mermaid, d2, cytoscape)
        #[arg(short = 'F', long = "export-format", default_value = "mu", value_parser = ["mu", "json", "mermaid", "d2", "cytoscape"])]
        export_format: String,

        /// Output file path (default: stdout)
        #[arg(short, long)]
        output: Option<String>,

        /// Filter to subgraph containing this node
        #[arg(short, long)]
        node: Option<String>,

        /// Maximum number of nodes to export
        #[arg(short = 'l', long = "limit")]
        limit: Option<usize>,
    },

    /// Show change history for a node
    History {
        /// Node to show history for (ID or name)
        node: String,

        /// Maximum number of commits to show
        #[arg(short = 'n', long, default_value = "10")]
        limit: usize,
    },

    // ==================== Integration ====================
    /// Start MCP server for AI assistant integration (Claude, etc.)
    Mcp {
        /// Working directory (defaults to current)
        #[arg(default_value = ".")]
        path: String,
    },

    // ==================== Utilities ====================
    /// Run health checks on MU installation
    Doctor {
        /// Path to check (defaults to current directory)
        #[arg(default_value = ".")]
        path: String,
    },

    /// Generate shell completion scripts
    Completions {
        /// Shell to generate completions for
        #[arg(value_enum)]
        shell: completions::Shell,

        /// Show installation instructions instead of generating completions
        #[arg(long)]
        instructions: bool,
    },
}

fn setup_logging(verbose: bool, quiet: bool) {
    let filter = if quiet {
        "error"
    } else if verbose {
        "debug,mu_embeddings=info"
    } else {
        "warn"
    };

    tracing_subscriber::registry()
        .with(fmt::layer().with_writer(std::io::stderr))
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(filter)))
        .init();
}

/// Print verbose version information
fn print_verbose_version() {
    use colored::Colorize;

    let cli_version = env!("CARGO_PKG_VERSION");
    let platform = format!("{}-{}", std::env::consts::ARCH, std::env::consts::OS);

    println!("mu {}", cli_version);
    println!("  {:<14} {}", "mu-cli:".cyan(), cli_version);
    println!("  {:<14} {}", "mu-core:".cyan(), cli_version);
    println!("  {:<14} {}", "mu-daemon:".cyan(), cli_version);
    println!("  {:<14} {}", "mu-embeddings:".cyan(), cli_version);
    println!("  {:<14} {}", "Platform:".cyan(), platform);
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    // Handle verbose version flag
    if cli.version_verbose {
        print_verbose_version();
        return Ok(());
    }

    setup_logging(cli.verbose, cli.quiet);

    // Load configuration from .murc.toml
    let config = MuConfig::load(std::path::Path::new("."));

    // Resolve output format: CLI flag > config default > Table
    let format = cli.format.unwrap_or_else(|| {
        config
            .default_format()
            .and_then(|f| f.parse().ok())
            .unwrap_or(OutputFormat::Table)
    });

    // Apply color override from config if set
    if let Some(use_color) = config.use_color() {
        colored::control::set_override(use_color);
    }

    // Handle case where no command is provided
    let command = match cli.command {
        Some(cmd) => cmd,
        None => {
            // Print help if no command provided
            let _ = Cli::command().print_help();
            println!();
            return Ok(());
        }
    };

    match command {
        // Core commands
        Commands::Bootstrap {
            path,
            force,
            embed,
            no_embed,
            strict,
        } => bootstrap::run(&path, force, embed, no_embed, strict, format).await,
        Commands::Compress {
            path,
            output,
            detail,
        } => compress::run(&path, output.as_deref(), &detail, format).await,
        Commands::Status { path } => status::run(&path, format).await,
        Commands::Embed {
            path,
            force,
            status,
        } => {
            if status {
                embed::run_status(&path, format).await
            } else {
                embed::run_incremental(&path, force, format).await
            }
        }
        Commands::Search {
            query,
            limit,
            threshold,
        } => search::run(&query, limit, threshold, format).await,
        Commands::Grok { question, depth } => grok::run(&question, depth, format).await,
        Commands::Query {
            query,
            interactive,
            limit,
            examples,
            schema,
        } => {
            query::run_extended(
                query.as_deref(),
                interactive,
                format,
                limit,
                examples,
                schema,
            )
            .await
        }
        Commands::Deps {
            node,
            reverse,
            depth,
            include_contains,
        } => deps::run(&node, reverse, depth, include_contains, format).await,
        Commands::Usedby {
            node,
            depth,
            include_contains,
        } => deps::run(&node, true, depth, include_contains, format).await,
        Commands::Read { path, line_numbers } => read::run(&path, line_numbers, format).await,
        Commands::Diff { base_ref, head_ref } => diff::run(&base_ref, &head_ref, format).await,

        // Graph analysis commands
        Commands::Impact {
            node,
            depth,
            edge_types,
        } => graph::run_impact(&node, edge_types, depth, format).await,
        Commands::Ancestors {
            node,
            depth,
            edge_types,
        } => graph::run_ancestors(&node, edge_types, depth, format).await,
        Commands::Cycles { edge_types } => graph::run_cycles(edge_types, format).await,
        Commands::Path {
            from,
            to,
            edge_types,
        } => graph::run_path(&from, &to, edge_types, format).await,

        // Vibe commands
        Commands::Yolo { path } => vibes::yolo::run(&path, format).await,
        Commands::Sus { path, threshold } => vibes::sus::run(&path, threshold, format).await,
        Commands::Wtf { target } => vibes::wtf::run(target.as_deref(), format).await,
        Commands::Omg {
            max_tokens,
            no_edges,
        } => vibes::omg::run(max_tokens, !no_edges, format).await,
        Commands::Vibe { path, convention } => {
            vibes::vibe::run(&path, format, convention.as_deref()).await
        }
        Commands::Zen { path, yes, reset } => vibes::zen::run(&path, yes, reset, format).await,

        // Analysis commands
        Commands::Patterns {
            category,
            refresh,
            examples,
        } => patterns::run(category.as_deref(), refresh, examples, format).await,

        Commands::Export {
            export_format,
            output,
            node,
            limit,
        } => {
            export::run(
                &export_format,
                output.as_deref(),
                node.as_deref(),
                limit,
                format,
            )
            .await
        }

        Commands::History { node, limit } => history::run(&node, limit, format).await,

        // Integration commands
        Commands::Mcp { path } => mcp::run(&path).await,

        // Utility commands
        Commands::Doctor { path } => doctor::run(&path, format).await,
        Commands::Completions {
            shell,
            instructions,
        } => {
            if instructions {
                completions::run(shell, true, format)
            } else {
                // Generate completions using the CLI Command
                let mut cmd = Cli::command();
                completions::generate_completions_with_cmd(shell, &mut cmd);
                Ok(())
            }
        }
    }
}
