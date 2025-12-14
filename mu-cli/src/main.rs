//! MU CLI - Command-line interface for Machine Understanding
//!
//! A semantic compression tool that translates codebases into token-efficient
//! representations optimized for LLM comprehension.

use clap::{CommandFactory, Parser, Subcommand};
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

mod commands;
mod config;
mod output;
mod tsconfig;

use commands::*;
use output::OutputFormat;

/// MU (Machine Understanding) - Semantic compression for LLMs
///
/// Translates codebases into token-efficient representations optimized for
/// LLM comprehension. Achieves 92-98% compression while preserving semantic signal.
#[derive(Parser)]
#[command(name = "mu")]
#[command(author, version, about, long_about = None)]
#[command(propagate_version = true)]
pub struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,

    /// Enable verbose output (debug logging)
    #[arg(short, long, global = true)]
    verbose: bool,

    /// Suppress all output except errors
    #[arg(short, long, global = true)]
    quiet: bool,

    /// Output format
    #[arg(long, global = true, default_value = "table")]
    format: OutputFormat,

    /// Show detailed version information
    #[arg(long = "version-verbose")]
    version_verbose: bool,
}

/// Graph analysis subcommands
#[derive(Subcommand)]
enum GraphCommands {
    /// Find downstream impact (what might break if this node changes)
    Impact {
        /// Node to analyze
        node: String,

        /// Filter by edge types (e.g., imports,calls)
        #[arg(short, long, value_delimiter = ',')]
        edge_types: Option<Vec<String>>,
    },

    /// Find upstream ancestors (what this node depends on)
    Ancestors {
        /// Node to analyze
        node: String,

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
}

#[derive(Subcommand)]
enum Commands {
    // ==================== Core Commands ====================
    /// Initialize and build MU database in one step
    #[command(visible_alias = "bs")]
    Bootstrap {
        /// Path to analyze (defaults to current directory)
        #[arg(default_value = ".")]
        path: String,

        /// Force rebuild even if database exists
        #[arg(short, long)]
        force: bool,

        /// Generate embeddings for semantic search
        #[arg(short, long)]
        embed: bool,
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
        #[arg(short = 'n', long = "top", default_value = "10")]
        limit: usize,

        /// Minimum similarity threshold (0.0-1.0)
        #[arg(short, long, default_value = "0.1")]
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

    /// Show what depends on a node (reverse dependencies) [aliases: rdeps]
    #[command(alias = "rdeps")]
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

        /// Filter by edge types (e.g., imports,calls)
        #[arg(short, long, value_delimiter = ',')]
        edge_types: Option<Vec<String>>,
    },

    /// Find upstream ancestors (what this node depends on)
    Ancestors {
        /// Node to analyze
        node: String,

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

    // ==================== Graph Commands ====================
    /// Graph analysis subcommands
    #[command(subcommand)]
    Graph(GraphCommands),

    // ==================== Vibe Commands ====================
    /// Just make it work (auto-fix common issues)
    Yolo {
        /// Path to fix
        #[arg(default_value = ".")]
        path: String,
    },

    /// Scan codebase for risky code (security, complexity, no tests)
    Sus {
        /// File to analyze, or "." to scan entire codebase
        #[arg(default_value = ".")]
        path: String,

        /// Minimum warning level to show (1=info, 2=warn, 3=error)
        #[arg(short, long, default_value = "1")]
        threshold: u8,
    },

    /// Show file history, ownership, and co-change patterns
    Wtf {
        /// File path to analyze (shows origin, evolution, and files that change together)
        target: Option<String>,
    },

    /// Generate OMEGA-compressed codebase overview for LLMs
    Omg {
        /// Maximum tokens for output
        #[arg(short = 't', long, default_value = "8000")]
        max_tokens: usize,

        /// Exclude relationship edges from output
        #[arg(long)]
        no_edges: bool,
    },

    /// Get the vibe check on a file or codebase
    Vibe {
        /// Path to vibe check
        #[arg(default_value = ".")]
        path: String,

        /// Force a specific naming convention (overrides language detection)
        /// Valid options: snake, pascal, camel, screaming
        #[arg(long)]
        convention: Option<String>,
    },

    /// Achieve codebase enlightenment (cache cleanup)
    Zen {
        /// Path to clean
        #[arg(default_value = ".")]
        path: String,

        /// Skip confirmation prompt
        #[arg(short, long)]
        yes: bool,
    },

    // ==================== Analysis Commands ====================
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
        #[arg(short = 'l', long)]
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

    // ==================== Utility Commands ====================
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
        "debug"
    } else {
        "info"
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

    let format = cli.format;

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
        Commands::Bootstrap { path, force, embed } => {
            bootstrap::run(&path, force, embed, format).await
        }
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

        // Top-level graph aliases
        Commands::Impact { node, edge_types } => graph::run_impact(&node, edge_types, format).await,
        Commands::Ancestors { node, edge_types } => {
            graph::run_ancestors(&node, edge_types, format).await
        }
        Commands::Cycles { edge_types } => graph::run_cycles(edge_types, format).await,

        // Graph commands
        Commands::Graph(graph_cmd) => match graph_cmd {
            GraphCommands::Impact { node, edge_types } => {
                graph::run_impact(&node, edge_types, format).await
            }
            GraphCommands::Ancestors { node, edge_types } => {
                graph::run_ancestors(&node, edge_types, format).await
            }
            GraphCommands::Cycles { edge_types } => graph::run_cycles(edge_types, format).await,
            GraphCommands::Path {
                from,
                to,
                edge_types,
            } => graph::run_path(&from, &to, edge_types, format).await,
        },

        // Vibe commands
        Commands::Yolo { path } => vibes::yolo::run(&path, format).await,
        Commands::Sus { path, threshold } => vibes::sus::run(&path, threshold, format).await,
        Commands::Wtf { target } => vibes::wtf::run(target.as_deref(), format).await,
        Commands::Omg { max_tokens, no_edges } => vibes::omg::run(max_tokens, !no_edges, format).await,
        Commands::Vibe { path, convention } => {
            vibes::vibe::run(&path, format, convention.as_deref()).await
        }
        Commands::Zen { path, yes } => vibes::zen::run(&path, yes, format).await,

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
