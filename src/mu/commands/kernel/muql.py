"""MU kernel muql command - Execute MUQL queries.

DEPRECATED: Use 'mu query' or 'mu q' instead.
"""

from __future__ import annotations

from pathlib import Path

import click


def _show_deprecation_warning() -> None:
    """Show deprecation warning for kernel muql."""
    click.secho(
        "⚠️  'mu kernel muql' is deprecated. Use 'mu query' or 'mu q' instead.",
        fg="yellow",
        err=True,
    )


@click.command("muql")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.argument("query", required=False)
@click.option("--interactive", "-i", is_flag=True, help="Start interactive REPL")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv", "tree"]),
    default="table",
    help="Output format",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--explain", is_flag=True, help="Show execution plan without running")
def kernel_muql(
    path: Path,
    query: str | None,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
) -> None:
    """[DEPRECATED] Execute MUQL queries.

    Use 'mu query' or 'mu q' instead.

    \b
    Examples:
        mu query "SELECT * FROM functions"
        mu q "SELECT * FROM classes LIMIT 10"
        mu query -i  # Interactive mode
    """
    _show_deprecation_warning()
    from mu.commands.query import _execute_muql

    _execute_muql(path, query, interactive, output_format, no_color, explain)


__all__ = ["kernel_muql"]
