//! MU CLI - Command-line interface for Machine Understanding
//!
//! A semantic compression tool that translates codebases into token-efficient
//! representations optimized for LLM comprehension.

use clap::{CommandFactory, Parser, Subcommand};
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

mod cache;
mod commands;
mod config;
mod engine;
mod mubase;
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
  mu deps MyClass   Show dependencies of MyClass

Examples:
  mu impact Parser  What breaks if I change Parser?")]
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

        /// Detail level: low, medium, high, auto
        #[arg(short, long, default_value = "auto")]
        detail: String,
    },

    /// Show project status and recommended next steps
    #[command(visible_alias = "st")]
    Status {
        /// Path to check (defaults to current directory)
        #[arg(default_value = ".")]
        path: String,
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

        /// Include structural 'contains' edges (classes/functions within modules)
        #[arg(long, default_value_t = true)]
        include_contains: bool,
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

        /// Include cross-service edges (publishes, subscribes, calls_http, uses_contract)
        #[arg(long)]
        cross_service: bool,
    },

    /// Review changes: semantic diff + impact analysis + audit findings + risk score
    #[command(visible_alias = "rv")]
    Review {
        /// Base git ref to compare against (defaults to main/develop)
        #[arg(long)]
        base: Option<String>,
    },

    /// Audit codebase for code smells, complexity, missing docs, and custom rules
    #[command(visible_alias = "lint")]
    Audit {
        /// Minimum complexity threshold to flag (default: 30)
        #[arg(long, default_value = None)]
        min_complexity: Option<u32>,

        /// Maximum parameter count before flagging (default: 6)
        #[arg(long, default_value = None)]
        max_params: Option<usize>,

        /// Scope audit to files changed since this git ref (e.g., "main", "HEAD~5")
        #[arg(long)]
        diff: Option<String>,

        /// Path to project rules directory (default: .mu/rules/)
        #[arg(long)]
        rules_dir: Option<String>,

        /// Show only the top N violations by severity (default: 20, 0 = unlimited)
        #[arg(long, default_value_t = 20)]
        top: usize,
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
        "debug"
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
    println!("  {:<14} {}", "engine:".cyan(), cli_version);
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
        Commands::Bootstrap { path, force } => {
            bootstrap::run(&path, force, format).await
        }
        Commands::Compress {
            path,
            output,
            detail,
        } => compress::run(&path, output.as_deref(), &detail, format).await,
        Commands::Status { path } => status::run(&path, format).await,
        Commands::Deps {
            node,
            reverse,
            depth,
            include_contains,
        } => deps::run(&node, reverse, depth, include_contains, format).await,
        Commands::Diff { base_ref, head_ref } => diff::run(&base_ref, &head_ref, format).await,
        Commands::Impact {
            node,
            depth,
            edge_types,
            cross_service,
        } => graph::run_impact(&node, edge_types, depth, cross_service, format).await,

        Commands::Review { base } => review::run(base.as_deref(), format).await,
        Commands::Audit {
            min_complexity,
            max_params,
            diff,
            rules_dir,
            top,
        } => audit::run(min_complexity, max_params, diff.as_deref(), rules_dir.as_deref(), top, format).await,

        Commands::Mcp { path } => mcp::run(&path).await,

        Commands::Doctor { path } => doctor::run(&path, format).await,
        Commands::Completions {
            shell,
            instructions,
        } => {
            if instructions {
                completions::run(shell, true, format)
            } else {
                let mut cmd = Cli::command();
                completions::generate_completions_with_cmd(shell, &mut cmd);
                Ok(())
            }
        }
    }
}
