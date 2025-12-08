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
    "impact": ("mu.commands.graph", "impact"),
    "ancestors": ("mu.commands.graph", "ancestors"),
    "cycles": ("mu.commands.graph", "cycles"),
    # Intelligence Layer commands
    "patterns": ("mu.commands.patterns", "patterns"),
    "generate": ("mu.commands.generate", "generate"),
    "warn": ("mu.commands.warn", "warn"),
    "related": ("mu.commands.core", "related"),
    # Output commands
    "compress": ("mu.commands.compress", "compress"),
    "diff": ("mu.commands.diff", "diff"),
    # Service groups
    "daemon": ("mu.commands.daemon", "daemon"),
    "mcp": ("mu.commands.mcp", "mcp"),
    "agent": ("mu.agent.cli", "agent"),
    # Advanced/power-user commands
    "kernel": ("mu.commands.kernel", "kernel"),
    "cache": ("mu.commands.cache", "cache"),
    "contracts": ("mu.commands.contracts", "contracts"),
    # Legacy commands (kept for compatibility)
    "init": ("mu.commands.init_cmd", "init"),
    "scan": ("mu.commands.scan", "scan"),
    "view": ("mu.commands.view", "view"),
    "describe": ("mu.commands.describe", "describe"),
    "man": ("mu.commands.man", "man_command"),
    "llm": ("mu.commands.llm_spec", "llm_command"),
}


@click.group(cls=LazyGroup, lazy_subcommands=LAZY_COMMANDS)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
@click.option("-q", "--quiet", is_flag=True, help="Suppress non-error output")
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.version_option(version=__version__, prog_name="mu")
@pass_context
def cli(ctx: MUContext, verbose: bool, quiet: bool, config: Path | None) -> None:
    """MU - Machine Understanding: Semantic compression for AI-native development.

    Translate codebases into token-efficient representations optimized for LLM comprehension.
    """
    # Lazy import for faster startup
    from mu.config import MUConfig
    from mu.logging import print_error, setup_logging

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


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
