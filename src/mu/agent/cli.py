"""CLI commands for MU Agent."""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from mu.agent.core import MUAgent
from mu.agent.formats import format_for_terminal
from mu.agent.models import AgentConfig


@click.group()
def agent() -> None:
    """MU Agent - Code structure specialist.

    Ask questions about your codebase structure, dependencies,
    and architecture using natural language.

    The agent uses a cheap model (gpt-5-nano by default) to minimize costs
    while querying the .mubase graph database for structural information.
    """
    pass


@agent.command()
@click.argument("question")
@click.option(
    "--model",
    "-m",
    default="gpt-5-nano-2025-08-07",
    help="Model to use (default: gpt-5-nano-2025-08-07)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON",
)
@click.option(
    "--max-tokens",
    "-t",
    default=4096,
    type=int,
    help="Maximum response tokens (default: 4096)",
)
def ask(question: str, model: str, as_json: bool, max_tokens: int) -> None:
    """Ask a question about the codebase.

    Uses the MU Agent to answer questions about code structure,
    dependencies, and architecture by querying the .mubase graph.

    \b
    Examples:
        mu agent ask "How does authentication work?"
        mu agent ask "What depends on UserService?"
        mu agent ask "Are there any circular dependencies?"
        mu agent ask --json "Show me the most complex functions"
    """
    config = AgentConfig(model=model, max_tokens=max_tokens)

    with MUAgent(config) as mu_agent:
        response = mu_agent.ask(question)

        if as_json:
            click.echo(json.dumps(response.to_dict(), indent=2))
        else:
            if response.error:
                click.echo(f"Error: {response.error}", err=True)
                sys.exit(1)
            else:
                output = format_for_terminal(response.content)
                click.echo(output)

                # Show stats in verbose mode
                if response.tool_calls_made > 0:
                    click.echo(
                        f"\n[{response.tool_calls_made} tool calls, "
                        f"~{response.tokens_used} tokens]",
                        err=True,
                    )


@agent.command()
@click.option(
    "--model",
    "-m",
    default="gpt-5-nano-2025-08-07",
    help="Model to use (default: gpt-5-nano-2025-08-07)",
)
@click.option(
    "--max-tokens",
    "-t",
    default=4096,
    type=int,
    help="Maximum response tokens (default: 4096)",
)
def interactive(model: str, max_tokens: int) -> None:
    """Start interactive session with MU Agent.

    Opens a REPL-like interface where you can ask multiple questions
    while maintaining conversation context.

    \b
    Commands:
        exit, quit, q   - Exit the session
        reset, clear    - Clear conversation history
        help, ?         - Show help

    \b
    Examples:
        mu agent interactive
        mu agent interactive --model claude-3-5-sonnet-latest
    """
    config = AgentConfig(model=model, max_tokens=max_tokens)

    click.echo("MU Agent - Code Structure Specialist")
    click.echo(f"Model: {model}")
    click.echo("Type 'exit' to quit, 'reset' to clear conversation, 'help' for help\n")

    with MUAgent(config) as mu_agent:
        while True:
            try:
                question = click.prompt("You", prompt_suffix=": ")
            except (EOFError, KeyboardInterrupt):
                click.echo("\nGoodbye!")
                break

            # Handle commands
            cmd = question.lower().strip()
            if cmd in ("exit", "quit", "q"):
                click.echo("Goodbye!")
                break
            elif cmd in ("reset", "clear"):
                mu_agent.reset()
                click.echo("Conversation cleared.\n")
                continue
            elif cmd in ("help", "?"):
                _show_interactive_help()
                continue
            elif not question.strip():
                continue

            # Process question
            response = mu_agent.ask(question)

            if response.error:
                click.echo(f"\nError: {response.error}\n", err=True)
            else:
                output = format_for_terminal(response.content)
                click.echo(f"\nMU: {output}\n")

                # Show stats
                if response.tool_calls_made > 0:
                    click.echo(
                        f"[{response.tool_calls_made} tool calls, "
                        f"~{response.tokens_used} tokens]\n",
                        err=True,
                    )


@agent.command()
@click.argument("muql")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON",
)
def query(muql: str, as_json: bool) -> None:
    """Execute MUQL query directly (bypass LLM).

    Runs the query directly against the .mubase without using the LLM.
    Useful for quick lookups when you know the exact query.

    \b
    Examples:
        mu agent query "SELECT * FROM functions WHERE complexity > 50"
        mu agent query "SHOW dependencies OF UserService"
        mu agent query --json "SELECT name FROM classes LIMIT 10"
    """
    with MUAgent() as mu_agent:
        result = mu_agent.query(muql)

        if as_json:
            click.echo(json.dumps(result, indent=2, default=str))
        else:
            if "error" in result:
                click.echo(f"Error: {result['error']}", err=True)
                sys.exit(1)
            else:
                _print_query_result(result)


@agent.command()
@click.argument("node")
@click.option(
    "--direction",
    "-d",
    type=click.Choice(["outgoing", "incoming", "both"]),
    default="outgoing",
    help="Direction to traverse (default: outgoing)",
)
@click.option(
    "--depth",
    type=int,
    default=2,
    help="Traversal depth (default: 2)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON",
)
def deps(node: str, direction: str, depth: int, as_json: bool) -> None:
    """Show dependencies of a code node.

    Find what a node depends on (outgoing) or what depends on it (incoming).

    \b
    Examples:
        mu agent deps UserService
        mu agent deps AuthService --direction incoming
        mu agent deps --json PaymentService
    """
    with MUAgent() as mu_agent:
        result = mu_agent.deps(node, direction=direction, depth=depth)

        if as_json:
            click.echo(json.dumps(result, indent=2, default=str))
        else:
            if "error" in result:
                click.echo(f"Error: {result['error']}", err=True)
                sys.exit(1)
            else:
                _print_query_result(result)


@agent.command()
@click.argument("node")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON",
)
def impact(node: str, as_json: bool) -> None:
    """Show impact of changing a node.

    Find all code that would be affected if this node changes.

    \b
    Examples:
        mu agent impact User
        mu agent impact --json PaymentService
    """
    with MUAgent() as mu_agent:
        result = mu_agent.impact(node)

        if as_json:
            click.echo(json.dumps(result, indent=2, default=str))
        else:
            if "error" in result:
                click.echo(f"Error: {result['error']}", err=True)
                sys.exit(1)
            else:
                impacted = result.get("impacted_nodes", [])
                click.echo(f"Impact of changing {node}:")
                click.echo(f"  Total affected: {len(impacted)} nodes")
                for n in impacted[:20]:
                    click.echo(f"  - {n}")
                if len(impacted) > 20:
                    click.echo(f"  ... and {len(impacted) - 20} more")


@agent.command()
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON",
)
def cycles(as_json: bool) -> None:
    """Detect circular dependencies in the codebase.

    \b
    Examples:
        mu agent cycles
        mu agent cycles --json
    """
    with MUAgent() as mu_agent:
        result = mu_agent.cycles()

        if as_json:
            click.echo(json.dumps(result, indent=2, default=str))
        else:
            if "error" in result:
                click.echo(f"Error: {result['error']}", err=True)
                sys.exit(1)
            else:
                cycle_list = result.get("cycles", [])
                if not cycle_list:
                    click.echo("No circular dependencies detected.")
                else:
                    click.echo(f"Found {len(cycle_list)} circular dependency cycles:")
                    for i, cycle in enumerate(cycle_list[:10], 1):
                        cycle_str = " -> ".join(cycle)
                        click.echo(f"  {i}. {cycle_str}")
                    if len(cycle_list) > 10:
                        click.echo(f"  ... and {len(cycle_list) - 10} more")


def _show_interactive_help() -> None:
    """Show help for interactive mode."""
    click.echo(
        """
MU Agent Interactive Mode Help
==============================

Commands:
  exit, quit, q   - Exit the session
  reset, clear    - Clear conversation history
  help, ?         - Show this help

Example Questions:
  "How does authentication work?"
  "What depends on UserService?"
  "Show me the most complex functions"
  "Are there any circular dependencies?"
  "What is the architecture of this codebase?"
  "What would break if I change the User model?"

Tips:
  - The agent maintains conversation context, so you can ask follow-up questions
  - Use 'reset' to start a fresh conversation
  - For direct queries without LLM, use 'mu agent query "MUQL"'
"""
    )


def _print_query_result(result: dict[str, Any]) -> None:
    """Print a query result in table format."""
    columns = result.get("columns", [])
    rows = result.get("rows", [])

    if not rows:
        click.echo("No results found.")
        return

    click.echo(f"Found {len(rows)} results:")
    click.echo()

    # Calculate column widths
    widths = [len(col) for col in columns]
    for row in rows[:50]:
        for i, val in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(val) if val else ""))

    # Print header
    header = "  ".join(col.ljust(widths[i]) for i, col in enumerate(columns))
    click.echo(header)
    click.echo("-" * len(header))

    # Print rows
    for row in rows[:50]:
        row_str = "  ".join(
            str(val if val is not None else "").ljust(widths[i]) for i, val in enumerate(row)
        )
        click.echo(row_str)

    if len(rows) > 50:
        click.echo(f"... and {len(rows) - 50} more rows")


__all__ = ["agent"]
