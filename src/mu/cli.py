"""MU CLI - Machine Understanding command-line interface."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dotenv import load_dotenv

# Load .env file before any other imports that might use env vars
load_dotenv()

import click  # noqa: E402

from mu import __version__  # noqa: E402
from mu.commands.lazy import LazyGroup  # noqa: E402

if TYPE_CHECKING:
    from mu.config import MUConfig

VerbosityLevel = Literal["quiet", "normal", "verbose"]


class MUContext:
    """Shared context for CLI commands."""

    def __init__(self) -> None:
        self.config: MUConfig | None = None
        self.verbosity: VerbosityLevel = "normal"
        self.debug: bool = False
        # Output configuration
        self.output_format: str | None = None  # None = use command default
        self.no_truncate: bool = False
        self.no_color: bool = False
        self.width: int | None = None


pass_context = click.make_pass_decorator(MUContext, ensure=True)


# Define lazy subcommands: name -> (module_path, attribute_name)
LAZY_COMMANDS: dict[str, tuple[str, str]] = {
    # Core commands (most common workflows)
    "bootstrap": ("mu.commands.core", "bootstrap"),
    "status": ("mu.commands.core", "status"),
    "compress": ("mu.commands.compress", "compress"),
    # Query & Navigation
    "q": ("mu.commands.query", "q"),
    "read": ("mu.commands.core", "read"),
    "search": ("mu.commands.core", "search"),
    # Graph Reasoning (petgraph-backed)
    "deps": ("mu.commands.deps", "deps"),
    "impact": ("mu.commands.graph", "impact"),
    "ancestors": ("mu.commands.graph", "ancestors"),
    "cycles": ("mu.commands.graph", "cycles"),
    "related": ("mu.commands.core", "related"),
    # Intelligence Layer
    "patterns": ("mu.commands.patterns", "patterns"),
    "diff": ("mu.commands.diff", "diff"),
    # History (promoted from kernel)
    "snapshot": ("mu.commands.kernel.snapshot", "kernel_snapshot"),
    "snapshots": ("mu.commands.kernel.snapshot", "kernel_snapshots"),
    "history": ("mu.commands.kernel.history", "kernel_history"),
    "blame": ("mu.commands.kernel.blame", "kernel_blame"),
    # Export (promoted from kernel)
    "export": ("mu.commands.kernel.export", "kernel_export"),
    "embed": ("mu.commands.kernel.embed", "kernel_embed"),
    # Services
    "serve": ("mu.commands.serve", "serve"),
    "mcp": ("mu.commands.mcp", "mcp"),
}

# Hidden commands (still work, not in Commands list - featured in docstring instead)
HIDDEN_COMMANDS: dict[str, tuple[str, str]] = {
    # Quick Commands - featured prominently in docstring, hidden from Commands list
    "grok": ("mu.commands.vibes", "grok"),  # Understand code - extract relevant context
    "omg": ("mu.commands.vibes", "omg"),  # Ship mode - OMEGA compressed context
    "yolo": ("mu.commands.vibes", "yolo"),  # Impact check - what breaks if I change this?
    "sus": ("mu.commands.vibes", "sus"),  # Smell check - warnings before touching code
    "vibe": ("mu.commands.vibes", "vibe"),  # Pattern check - does this code fit?
    "wtf": ("mu.commands.vibes", "wtf"),  # Git archaeology - why does this code exist?
    "zen": ("mu.commands.vibes", "zen"),  # Clean up - clear caches
    # Utility commands (not in main help)
    "migrate": ("mu.commands.migrate", "migrate"),
    "view": ("mu.commands.view", "view"),
    "describe": ("mu.commands.describe", "describe"),
    "man": ("mu.commands.man", "man_command"),
    "llm": ("mu.commands.llm_spec", "llm_command"),
    "cache": ("mu.commands.cache", "cache"),
    # Deprecated aliases - still work, not in help
    "query": ("mu.commands.query", "query"),  # Use 'q' instead
    "context": ("mu.commands.core", "context"),  # Use 'grok' instead
    "warn": ("mu.commands.warn", "warn"),  # Use 'sus' instead
    "daemon": ("mu.commands.daemon", "daemon"),  # Use 'serve' instead
    # Power-user commands (hidden)
    "kernel": ("mu.commands.kernel", "kernel"),  # Advanced graph ops
    "sigma": ("mu.sigma.cli", "sigma"),  # Training data pipeline (easter egg)
}


@click.group(cls=LazyGroup, lazy_subcommands=LAZY_COMMANDS, hidden_subcommands=HIDDEN_COMMANDS)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
@click.option("-q", "--quiet", is_flag=True, help="Suppress non-error output")
@click.option("--debug", is_flag=True, help="Show full tracebacks on errors")
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.option(
    "--output-format",
    "-F",
    type=click.Choice(["table", "json", "csv", "tree"]),
    default=None,
    help="Output format (overrides command-specific defaults)",
)
@click.option(
    "--no-truncate",
    is_flag=True,
    help="Show full values without truncation",
)
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable colored output",
)
@click.option(
    "--width",
    type=int,
    default=None,
    help="Table width (default: auto-detect terminal)",
)
@click.version_option(version=__version__, prog_name="mu")
@pass_context
def cli(
    ctx: MUContext,
    verbose: bool,
    quiet: bool,
    debug: bool,
    config: Path | None,
    output_format: str | None,
    no_truncate: bool,
    no_color: bool,
    width: int | None,
) -> None:
    """MU - Machine Understanding for Codebases.

    \b
    Quick Commands:
      grok         Understand code - extract relevant context
      omg          Ship mode - OMEGA compressed context
      yolo         Impact check - what breaks if I change this?
      sus          Smell check - warnings before touching code
      vibe         Pattern check - does this code fit?
      wtf          Git archaeology - why does this code exist?
      zen          Clean up - clear caches

    \b
    Core:
      bootstrap    Initialize MU for a codebase
      status       Show MU status and guidance
      compress     Compress code to MU format

    \b
    Query:
      q            Execute MUQL queries
      read         Read source code for a node
      search       Search for code entities

    \b
    Graph:
      deps         Show dependencies
      impact       What breaks if I change this?
      ancestors    What depends on this?
      cycles       Find circular dependencies
      related      Find related files

    \b
    Intelligence:
      patterns     Detect codebase patterns
      diff         Semantic diff between refs

    \b
    History:
      snapshot     Create a temporal snapshot
      snapshots    List all snapshots
      history      Show change history for a node
      blame        Show who last modified a node

    \b
    Export:
      export       Export graph in various formats
      embed        Generate embeddings for semantic search

    \b
    Services:
      serve        Start MU daemon (HTTP/WebSocket API)
      mcp          MCP server tools

    Use 'mu <command> --help' for details.
    Use --debug to show full tracebacks on errors.
    """
    import sys

    # Lazy import for faster startup
    from mu.config import MUConfig
    from mu.logging import print_error, setup_logging

    # Store debug flag
    ctx.debug = debug

    # Determine verbosity
    if quiet:
        ctx.verbosity = "quiet"
    elif verbose:
        ctx.verbosity = "verbose"
    else:
        ctx.verbosity = "normal"

    setup_logging(ctx.verbosity)

    # Auto-detect TTY for output settings
    is_tty = sys.stdout.isatty()

    # Store output configuration with TTY auto-detection
    ctx.output_format = output_format
    ctx.no_truncate = no_truncate or not is_tty  # Auto-disable truncation when piped
    ctx.no_color = no_color or not is_tty  # Auto-disable color when piped
    ctx.width = width

    # Load configuration
    try:
        ctx.config = MUConfig.load(config)
    except Exception as e:
        if not quiet:
            print_error(f"Failed to load configuration: {e}")
        # Don't fail here - some commands (like init) don't need config


def install_completion(shell: str | None = None) -> None:
    """Install shell completion for mu CLI.

    Args:
        shell: Shell type (bash, zsh, fish). Auto-detected if not specified.
    """
    import os
    import subprocess

    # Detect shell if not specified
    if shell is None:
        shell_env = os.environ.get("SHELL", "")
        if "zsh" in shell_env:
            shell = "zsh"
        elif "fish" in shell_env:
            shell = "fish"
        else:
            shell = "bash"

    click.echo(f"Installing {shell} completion for mu...")

    if shell == "zsh":
        # For zsh, add to .zshrc
        completion_script = "_MU_COMPLETE=zsh_source mu"
        rc_file = os.path.expanduser("~/.zshrc")
        marker = "# mu shell completion"

        with open(rc_file, "a+") as f:
            f.seek(0)
            content = f.read()
            if marker not in content:
                f.write(f"\n{marker}\n")
                f.write(f'eval "$({completion_script})"\n')
                click.echo(f"Added completion to {rc_file}")
                click.echo("Restart your shell or run: source ~/.zshrc")
            else:
                click.echo("Completion already installed")

    elif shell == "bash":
        # For bash, add to .bashrc
        completion_script = "_MU_COMPLETE=bash_source mu"
        rc_file = os.path.expanduser("~/.bashrc")
        marker = "# mu shell completion"

        with open(rc_file, "a+") as f:
            f.seek(0)
            content = f.read()
            if marker not in content:
                f.write(f"\n{marker}\n")
                f.write(f'eval "$({completion_script})"\n')
                click.echo(f"Added completion to {rc_file}")
                click.echo("Restart your shell or run: source ~/.bashrc")
            else:
                click.echo("Completion already installed")

    elif shell == "fish":
        # For fish, write to completions directory
        completion_dir = os.path.expanduser("~/.config/fish/completions")
        os.makedirs(completion_dir, exist_ok=True)
        completion_file = os.path.join(completion_dir, "mu.fish")

        result = subprocess.run(
            ["mu"],
            env={**os.environ, "_MU_COMPLETE": "fish_source"},
            capture_output=True,
            text=True,
        )
        with open(completion_file, "w") as f:
            f.write(result.stdout)
        click.echo(f"Wrote completion to {completion_file}")

    else:
        click.echo(f"Unsupported shell: {shell}")
        click.echo("Supported shells: bash, zsh, fish")


def main() -> None:
    """Entry point for the CLI."""
    import sys

    # Handle --install-completion flag early
    if "--install-completion" in sys.argv:
        shell = None
        idx = sys.argv.index("--install-completion")
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("-"):
            shell = sys.argv[idx + 1]
        install_completion(shell)
        return

    # Check if --debug flag is present anywhere in args
    debug_mode = "--debug" in sys.argv

    try:
        cli()
    except click.ClickException:
        # Let Click handle its own exceptions
        raise
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C
        sys.exit(130)
    except Exception as e:
        from mu.logging import print_error, print_info

        # Provide user-friendly error messages for common errors
        error_str = str(e).lower()

        if "lock" in error_str:
            print_error("Database is locked by another process.")
            print_info("")
            print_info("The daemon may be running. Try one of these:")
            print_info("  1. Start daemon: mu daemon start")
            print_info("  2. Stop daemon:  mu daemon stop")
        elif "no .mu/mubase" in error_str or "mubase not found" in error_str:
            print_error("No .mu/mubase found.")
            print_info("")
            print_info("Run 'mu bootstrap' to initialize MU for this directory.")
        elif "corrupt" in error_str or "wal" in error_str:
            print_error("Database appears corrupted.")
            print_info("")
            print_info("Try removing and rebuilding:")
            print_info("  rm -rf .mu/")
            print_info("  mu bootstrap")
        elif "api" in error_str and "key" in error_str:
            print_error("API key not configured.")
            print_info("")
            print_info("Set your API key in environment or .env file:")
            print_info("  export ANTHROPIC_API_KEY=your-key")
            print_info("  # or")
            print_info("  export OPENAI_API_KEY=your-key")
        else:
            # Generic error
            print_error(f"Error: {e}")

        if debug_mode:
            print_info("")
            print_info("Full traceback (--debug mode):")
            import traceback

            traceback.print_exc()
        else:
            print_info("")
            print_info("Run with --debug for full traceback.")

        sys.exit(1)


if __name__ == "__main__":
    main()
