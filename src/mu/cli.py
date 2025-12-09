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


pass_context = click.make_pass_decorator(MUContext, ensure=True)


# Define lazy subcommands: name -> (module_path, attribute_name)
LAZY_COMMANDS: dict[str, tuple[str, str]] = {
    # Core commands (most common workflows)
    "bootstrap": ("mu.commands.core", "bootstrap"),
    "status": ("mu.commands.core", "status"),
    "read": ("mu.commands.core", "read"),
    "context": ("mu.commands.core", "context"),
    "search": ("mu.commands.core", "search"),
    # Query commands
    "query": ("mu.commands.query", "query"),
    "q": ("mu.commands.query", "q"),
    # Graph reasoning commands (petgraph-backed)
    "deps": ("mu.commands.deps", "deps"),  # Promoted from kernel deps
    "impact": ("mu.commands.graph", "impact"),
    "ancestors": ("mu.commands.graph", "ancestors"),
    "cycles": ("mu.commands.graph", "cycles"),
    # Intelligence Layer commands
    "patterns": ("mu.commands.patterns", "patterns"),
    "warn": ("mu.commands.warn", "warn"),
    "related": ("mu.commands.core", "related"),
    # Output commands
    "compress": ("mu.commands.compress", "compress"),
    "diff": ("mu.commands.diff", "diff"),
    # Services - consolidated
    "serve": ("mu.commands.serve", "serve"),  # Unified server command
    "mcp": ("mu.commands.mcp", "mcp"),
    # Advanced/power-user commands
    "kernel": ("mu.commands.kernel", "kernel"),
    # Vibes commands - developer-friendly CLI with personality
    "omg": ("mu.commands.vibes", "omg"),  # OMEGA context
    "grok": ("mu.commands.vibes", "grok"),  # Smart context
    "wtf": ("mu.commands.vibes", "wtf"),  # Git archaeology
    "yolo": ("mu.commands.vibes", "yolo"),  # Impact analysis
    "sus": ("mu.commands.vibes", "sus"),  # Proactive warnings
    "vibe": ("mu.commands.vibes", "vibe"),  # Pattern validation
    "zen": ("mu.commands.vibes", "zen"),  # Cache cleanup
}

# Hidden commands (power-user, deprecated, or for compatibility)
HIDDEN_COMMANDS: dict[str, tuple[str, str]] = {
    "migrate": ("mu.commands.migrate", "migrate"),
    "view": ("mu.commands.view", "view"),
    "describe": ("mu.commands.describe", "describe"),
    "man": ("mu.commands.man", "man_command"),
    "llm": ("mu.commands.llm_spec", "llm_command"),
    # Deprecated - use 'mu serve' instead
    "daemon": ("mu.commands.daemon", "daemon"),
    # Hidden - accessible but not in main help
    "cache": ("mu.commands.cache", "cache"),
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
@click.version_option(version=__version__, prog_name="mu")
@pass_context
def cli(ctx: MUContext, verbose: bool, quiet: bool, debug: bool, config: Path | None) -> None:
    """MU - Machine Understanding for Codebases.

    \b
    Core Commands:
      bootstrap    Initialize MU for a codebase
      status       Show MU status and guidance
      compress     Compress code to MU format

    \b
    Query & Navigation:
      query, q     Execute MUQL queries
      context      Smart context extraction
      read         Read source code for a node
      search       Search for code entities

    \b
    Graph Reasoning:
      deps         Show dependencies
      impact       What breaks if I change this?
      ancestors    What depends on this?
      cycles       Find circular dependencies
      related      Find related files

    \b
    Intelligence:
      patterns     Detect codebase patterns
      warn         Proactive code warnings
      diff         Semantic diff between refs

    \b
    Services:
      serve        Start MU daemon (HTTP/WebSocket API)
      mcp          MCP server tools

    \b
    Vibes (fun aliases):
      omg, grok, wtf, yolo, sus, vibe, zen

    \b
    Advanced:
      kernel       Advanced graph operations (power users)

    Use 'mu <command> --help' for details.
    Use --debug to show full tracebacks on errors.
    """
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
