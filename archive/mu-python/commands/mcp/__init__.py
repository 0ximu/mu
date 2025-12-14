"""MU MCP Commands - Model Context Protocol server for AI assistants."""

from __future__ import annotations

import click

from mu.commands.lazy import LazyGroup

# Define lazy subcommands for mcp group
LAZY_MCP_COMMANDS: dict[str, tuple[str, str]] = {
    "serve": ("mu.commands.mcp.serve", "mcp_serve"),
    "tools": ("mu.commands.mcp.tools", "mcp_tools"),
    "test": ("mu.commands.mcp.test", "mcp_test"),
}


@click.group(cls=LazyGroup, lazy_subcommands=LAZY_MCP_COMMANDS)
def mcp() -> None:
    """MCP server for AI assistants (Claude Code, etc).

    Expose MU's code analysis as MCP tools for AI assistants.

    \b
    Examples:
        mu mcp serve              # Run MCP server (stdio transport)
        mu mcp serve --http       # Run with HTTP transport
        mu mcp tools              # List available tools
    """
    pass


__all__ = ["mcp"]
