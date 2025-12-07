"""MU MCP tools command - List available MCP tools."""

from __future__ import annotations

import click


@click.command("tools")
def mcp_tools() -> None:
    """List available MCP tools.

    Shows all tools exposed by the MU MCP server.
    """
    from rich.table import Table

    from mu.logging import console, print_info

    table = Table(title="MU MCP Tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Description")

    # Get tools from the server
    tools = [
        ("mu_query", "Execute MUQL queries against the code graph"),
        ("mu_context", "Extract smart context for natural language questions"),
        ("mu_deps", "Show dependencies of a code node"),
        ("mu_node", "Look up a specific code node by ID"),
        ("mu_search", "Search for code nodes by name pattern"),
        ("mu_status", "Get MU daemon status and codebase statistics"),
    ]

    for name, desc in tools:
        table.add_row(name, desc)

    console.print(table)
    console.print()
    print_info("To use with Claude Code, add to ~/.claude/mcp_servers.json:")
    console.print('  {"mu": {"command": "mu", "args": ["mcp", "serve"]}}')


__all__ = ["mcp_tools"]
