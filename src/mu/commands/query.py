"""MU query commands - MUQL query execution."""

from __future__ import annotations

import sys
from pathlib import Path

import click


def _execute_muql(
    path: Path,
    query_str: str | None,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
    full_paths: bool = False,
) -> None:
    """Shared MUQL execution logic for query commands.

    Used by `mu query`, `mu q`, and `mu kernel muql` commands.

    Thin Client Architecture (ADR-002):
    - If daemon is running, forward query via HTTP (no DB lock)
    - If daemon is not running, fall back to local MUbase access
    """
    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.kernel.muql.executor import QueryResult
    from mu.kernel.muql.formatter import format_result
    from mu.logging import console, print_error, print_info, print_warning

    mubase_path = path.resolve() / ".mubase"
    truncate_paths = not full_paths

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel init' and 'mu kernel build' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    # For non-query operations (interactive, explain), always use local mode
    if interactive or explain:
        _execute_muql_local(
            mubase_path, query_str, interactive, output_format, no_color, explain, truncate_paths
        )
        return

    if not query_str:
        print_error("Either provide a query or use --interactive/-i flag")
        print_info('Example: mu query "SELECT * FROM functions LIMIT 10"')
        print_info("         mu query -i")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Try daemon first (Thin Client path - no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            result_dict = client.query(query_str)
            # Convert daemon response to QueryResult for formatting
            result = QueryResult(
                columns=result_dict.get("columns", []),
                rows=[tuple(row) for row in result_dict.get("rows", [])],
                row_count=result_dict.get("row_count", 0),
                error=result_dict.get("error"),
                execution_time_ms=result_dict.get("execution_time_ms", 0.0),
            )
            output = format_result(result, output_format, no_color, truncate_paths)
            console.print(output)
            return
        except DaemonError as e:
            # Log and fall back to local mode
            print_warning(f"Daemon query failed, falling back to local mode: {e}")

    # Fallback: Local mode (requires lock)
    _execute_muql_local(
        mubase_path, query_str, interactive, output_format, no_color, explain, truncate_paths
    )


def _execute_muql_local(
    mubase_path: Path,
    query_str: str | None,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
    truncate_paths: bool = True,
) -> None:
    """Execute MUQL query in local mode (direct MUbase access).

    This path requires exclusive lock on the database.
    """
    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.kernel.muql import MUQLEngine
    from mu.kernel.muql.repl import run_repl
    from mu.logging import console, print_error, print_info

    db = MUbase(mubase_path)

    try:
        if interactive:
            # Start REPL
            run_repl(db, no_color)
        elif query_str:
            # Execute single query
            engine = MUQLEngine(db)

            if explain:
                # Show execution plan
                explanation = engine.explain(query_str)
                console.print(explanation)
            else:
                # Execute and format
                output = engine.query(query_str, output_format, no_color, truncate_paths)
                console.print(output)
        else:
            # No query provided and not interactive mode
            print_error("Either provide a query or use --interactive/-i flag")
            print_info('Example: mu query "SELECT * FROM functions LIMIT 10"')
            print_info("         mu query -i")
            sys.exit(ExitCode.CONFIG_ERROR)
    finally:
        db.close()


@click.command("query")
@click.argument("muql", required=False)
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=".",
    help="Path to codebase (default: current directory)",
)
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
@click.option("--full-paths", is_flag=True, help="Show full file paths without truncation")
def query(
    muql: str | None,
    path: Path,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
    full_paths: bool,
) -> None:
    """Execute MUQL query against the codebase graph.

    MUQL provides an SQL-like query interface for exploring your codebase.
    Alias for 'mu kernel muql'.

    \b
    Examples:
        mu query "SELECT * FROM functions WHERE complexity > 20"
        mu query "SHOW dependencies OF MUbase"
        mu query -i                         # Interactive mode
        mu query -f json "SELECT * FROM classes"
        mu query --full-paths "SELECT * FROM modules"
    """
    _execute_muql(path, muql, interactive, output_format, no_color, explain, full_paths)


@click.command("q")
@click.argument("muql", required=False)
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=".",
    help="Path to codebase (default: current directory)",
)
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
@click.option("--full-paths", is_flag=True, help="Show full file paths without truncation")
def q(
    muql: str | None,
    path: Path,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
    full_paths: bool,
) -> None:
    """Execute MUQL query (short alias for 'mu query').

    \b
    Examples:
        mu q "SELECT * FROM functions LIMIT 10"
        mu q -i
    """
    _execute_muql(path, muql, interactive, output_format, no_color, explain, full_paths)


__all__ = ["query", "q", "_execute_muql", "_execute_muql_local"]
