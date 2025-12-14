"""MU MCP test command - Test MCP tools without starting server."""

from __future__ import annotations

import json
import sys

import click


@click.command("test")
@click.argument("tool_name", required=False)
@click.option(
    "--input", "-i", "input_json", help='JSON input for the tool (e.g., \'{"question": "..."}\'\')'
)
@click.option("--list", "-l", "list_tools", is_flag=True, help="List available MCP tools")
def mcp_test(tool_name: str | None, input_json: str | None, list_tools: bool) -> None:
    """Test MCP tools without starting server.

    Runs each MCP tool with a simple test case and reports
    PASS/FAIL status for each. Useful for verifying setup.

    \b
    Examples:
        mu mcp test                              # Test all tools
        mu mcp test --list                       # List available tools
        mu mcp test mu_status                    # Test specific tool
        mu mcp test mu_context -i '{"question": "How does auth work?"}'
    """
    from mu.logging import console, print_error, print_info, print_success, print_warning
    from mu.mcp.server import TOOL_REGISTRY, test_tool, test_tools

    if list_tools:
        print_info("Available MCP tools:\n")
        for name, tool_info in TOOL_REGISTRY.items():
            desc = tool_info.get("description", "No description")
            # Truncate long descriptions
            if len(desc) > 60:
                desc = desc[:57] + "..."
            click.echo(f"  {name}")
            click.echo(click.style(f"    {desc}", dim=True))
        return

    if tool_name:
        # Test specific tool
        if tool_name not in TOOL_REGISTRY:
            print_error(f"Unknown tool: {tool_name}")
            print_info("\nAvailable tools:")
            for name in TOOL_REGISTRY:
                click.echo(f"  {name}")
            sys.exit(1)

        # Parse input JSON if provided
        tool_input = None
        if input_json:
            try:
                tool_input = json.loads(input_json)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON input: {e}")
                sys.exit(1)

        print_info(f"Testing tool: {tool_name}")
        if tool_input:
            print_info(f"Input: {json.dumps(tool_input, indent=2)}")
        print_info("")

        result = test_tool(tool_name, tool_input)

        if result.get("ok"):
            print_success(f"PASS: {tool_name}")
            if "result" in result:
                print_info("\nResult:")
                # Pretty print result
                output = result["result"]
                if isinstance(output, dict):
                    click.echo(json.dumps(output, indent=2))
                else:
                    click.echo(str(output)[:1000])  # Limit output length
        else:
            print_error(f"FAIL: {tool_name}")
            error = result.get("error", "Unknown error")
            print_info(f"Error: {error}")
            sys.exit(1)
        return

    # Test all tools
    results = test_tools()
    all_ok = all(r.get("ok") for r in results.values())

    for name, result in results.items():
        ok = result.get("ok", False)
        status = "PASS" if ok else "FAIL"
        color = "green" if ok else "red"
        click.secho(f"  {status}: {name}", fg=color)
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
