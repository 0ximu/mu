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
    from mu.mcp.server import mcp

    table = Table(title="MU MCP Tools")
    table.add_column("Tool", style="cyan")
    table.add_column("Description")

    # Get tools dynamically from the MCP server
    tools = []
    for tool in mcp._tool_manager._tools.values():
        name = tool.name
        # Extract first line of docstring as description
        desc = (tool.description or "").split("\n")[0].strip()
        tools.append((name, desc))

    # Sort alphabetically
    tools.sort(key=lambda x: x[0])

    for name, desc in tools:
        table.add_row(name, desc)

    console.print(table)
    console.print()
    print_info(f"Total: {len(tools)} tools available")
    console.print()
    print_info("To use with Claude Code, add to ~/.claude/mcp_servers.json:")
    console.print('  {"mu": {"command": "mu", "args": ["mcp", "serve"]}}')


__all__ = ["mcp_tools"]
