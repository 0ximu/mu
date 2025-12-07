"""MU kernel muql command - Execute MUQL queries."""

from __future__ import annotations

from pathlib import Path

import click


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
    """Execute MUQL queries against the graph database.

    MUQL provides an SQL-like query interface for exploring your codebase.
    Also available as 'mu query' or 'mu q' (shorter aliases).

    \b
    Examples:
        # Single query
        mu kernel muql . "SELECT * FROM functions WHERE complexity > 20"

        # Interactive mode
        mu kernel muql . -i

        # Show execution plan
        mu kernel muql . --explain "SELECT * FROM classes LIMIT 10"

        # Output as JSON
        mu kernel muql . -f json "SELECT name, complexity FROM functions"

    \b
    Query Types:
        SELECT - SQL-like queries on nodes
        SHOW   - Dependency and relationship queries
        FIND   - Pattern matching queries
        PATH   - Path finding between nodes
        ANALYZE - Built-in analysis queries

    \b
    In interactive mode, use these commands:
        .help    - Show help
        .format  - Change output format
        .explain - Explain query
        .exit    - Exit REPL
    """
    from mu.commands.query import _execute_muql

    _execute_muql(path, query, interactive, output_format, no_color, explain)


__all__ = ["kernel_muql"]
