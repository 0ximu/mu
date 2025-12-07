"""MU MCP test command - Test MCP tools without starting server."""

from __future__ import annotations

import sys

import click


@click.command("test")
def mcp_test() -> None:
    """Test MCP tools without starting server.

    Runs each MCP tool with a simple test case and reports
    PASS/FAIL status for each. Useful for verifying setup.

    \b
    Examples:
        mu mcp test           # Test all tools
    """
    from mu.logging import console, print_success, print_warning
    from mu.mcp.server import test_tools

    results = test_tools()
    all_ok = all(r.get("ok") for r in results.values())

    for tool_name, result in results.items():
        ok = result.get("ok", False)
        status = "PASS" if ok else "FAIL"
        color = "green" if ok else "red"
        click.secho(f"  {status}: {tool_name}", fg=color)
        if not ok:
            error = result.get("error", "Unknown error")
            click.echo(f"        {error}")

    console.print()
    if all_ok:
        print_success("All MCP tools passed")
    else:
        print_warning("Some MCP tools failed. Run 'mu daemon start .' to enable all features.")
        sys.exit(1)


__all__ = ["mcp_test"]
