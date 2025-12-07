"""MU MCP serve command - Start MCP server for AI assistants."""

from __future__ import annotations

import click


@click.command("serve")
@click.option(
    "--http",
    "use_http",
    is_flag=True,
    help="Use HTTP transport instead of stdio",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=8000,
    help="Port for HTTP transport (default: 8000)",
)
def mcp_serve(use_http: bool, port: int) -> None:
    """Start MCP server for AI assistants.

    By default uses stdio transport (for Claude Code integration).
    Use --http for HTTP transport.

    \b
    Examples:
        mu mcp serve          # stdio (for Claude Code)
        mu mcp serve --http   # HTTP on port 8000
    """
    from mu.logging import print_info
    from mu.mcp import run_server
    from mu.mcp.server import TransportType

    transport: TransportType = "streamable-http" if use_http else "stdio"

    if use_http:
        print_info(f"Starting MCP server on http://localhost:{port}/mcp")
    else:
        print_info("Starting MCP server (stdio transport)")

    run_server(transport=transport)


__all__ = ["mcp_serve"]
