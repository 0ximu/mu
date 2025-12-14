"""MU describe command - Output CLI interface description."""

from __future__ import annotations

import sys

import click


@click.command("describe")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["mu", "json", "markdown"]),
    default="mu",
    help="Output format (default: mu)",
)
def describe(output_format: str) -> None:
    """Output MU representation of CLI interface.

    Generates a machine-readable description of all MU CLI commands,
    arguments, and options. Useful for AI agents to understand the interface.

    \b
    Examples:
        mu describe                # MU format (optimized for LLMs)
        mu describe --format json  # JSON Schema format
        mu describe --format markdown  # Human-readable Markdown
    """
    from mu.describe import describe_cli, format_json, format_markdown, format_mu
    from mu.errors import ExitCode
    from mu.logging import console, print_error

    result = describe_cli()

    if result.error:
        print_error(result.error)
        sys.exit(ExitCode.FATAL_ERROR)

    if output_format == "mu":
        output = format_mu(result)
    elif output_format == "json":
        output = format_json(result)
    else:
        output = format_markdown(result)

    console.print(output)


__all__ = ["describe"]
