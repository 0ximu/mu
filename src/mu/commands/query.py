"""MU query commands - MUQL query execution."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import find_mubase_path, get_mubase_path

MUQL_EXAMPLES = """
MUQL Query Examples
===================

Basic SELECT queries:
  SELECT * FROM functions                    # All functions
  SELECT * FROM functions LIMIT 10           # First 10 functions
  SELECT name, complexity FROM functions     # Specific columns
  SELECT * FROM classes WHERE complexity > 20

Filtering:
  SELECT * FROM functions WHERE name LIKE '%auth%'
  SELECT * FROM functions WHERE name = 'parse_file'
  SELECT * FROM classes WHERE file_path LIKE 'src/api/%'

Aggregation:
  SELECT COUNT(*) FROM functions
  SELECT type, COUNT(*) FROM nodes GROUP BY type
  SELECT AVG(complexity) FROM functions

SHOW relationships:
  SHOW dependencies OF MyClass               # What does MyClass depend on?
  SHOW dependents OF MyClass                 # What depends on MyClass?
  SHOW dependencies OF MyClass DEPTH 3       # Transitive dependencies
  SHOW children OF MyModule                  # Contents of a module/class

FIND pattern search:
  FIND functions MATCHING 'test_%'           # Functions starting with test_
  FIND classes CALLING parse_file            # Classes that call parse_file
  FIND functions WITH DECORATOR '@cache'     # Functions with decorator

PATH queries:
  PATH FROM cli TO parser                    # Any path between nodes
  PATH FROM cli TO parser MAX DEPTH 5        # Limited depth
  PATH FROM api TO database VIA imports      # Only import edges

ANALYZE:
  ANALYZE complexity                         # Complexity analysis
  ANALYZE hotspots                           # High-change areas
  ANALYZE circular                           # Circular dependencies
  FIND CYCLES                                # Detect cycles in graph

DESCRIBE (schema):
  DESCRIBE tables                            # List available tables
  DESCRIBE functions                         # Schema for functions table

For more details: https://github.com/dominaite/mu#muql
"""

MUQL_SCHEMA = """
MUQL Schema Reference
=====================

Tables (node types):
  nodes      - All nodes (modules, classes, functions)
  modules    - File/module level entities
  classes    - Class/struct/interface definitions
  functions  - Function/method definitions

Columns (all tables share these):
  id            VARCHAR   Node identifier (e.g., "cls:src/auth.py:AuthService")
  type          VARCHAR   Node type: module, class, function
  name          VARCHAR   Simple name (e.g., "AuthService")
  qualified_name VARCHAR  Full qualified name
  file_path     VARCHAR   Source file path
  line_start    INTEGER   Start line number
  line_end      INTEGER   End line number
  complexity    INTEGER   Cyclomatic complexity score

Edge types (for SHOW/PATH queries):
  contains   - Module→Class, Class→Function (structural)
  imports    - Module→Module (import dependencies)
  inherits   - Class→Class (inheritance)
  calls      - Function→Function (call graph)
  uses       - Class→Class (type references)

Common filters:
  WHERE complexity > 20        # High complexity
  WHERE name LIKE 'test_%'     # Name pattern
  WHERE file_path LIKE 'src/%' # Path pattern
  WHERE type = 'function'      # Node type

Tip: Use DESCRIBE tables or DESCRIBE <table> for live schema info.
"""


def _execute_muql(
    path: Path,
    query_str: str | None,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
    no_truncate: bool = False,
    offline: bool = False,
) -> None:
    """Shared MUQL execution logic for query commands.

    Used by `mu query`, `mu q`, and `mu kernel muql` commands.

    Thin Client Architecture (ADR-002):
    - If daemon is running, forward query via HTTP (no DB lock)
    - If daemon is not running, fall back to local MUbase access
    - If offline=True, skip daemon entirely and use local access
    """
    import os

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.kernel.muql.executor import QueryResult
    from mu.kernel.muql.formatter import format_result
    from mu.logging import console, print_error, print_info, print_warning

    # Check for MU_OFFLINE environment variable
    if os.environ.get("MU_OFFLINE", "").lower() in ("1", "true", "yes"):
        offline = True

    # First try to find mubase by walking up directories (workspace-aware)
    mubase_path = find_mubase_path(path)
    if not mubase_path:
        # Fallback to direct path construction for better error message
        mubase_path = get_mubase_path(path)
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu bootstrap' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Derive root_path from mubase_path (.mu/mubase -> parent.parent)
    root_path = mubase_path.parent.parent

    # For non-query operations (interactive, explain), always use local mode
    if interactive or explain:
        _execute_muql_local(
            mubase_path, query_str, interactive, output_format, no_color, explain, no_truncate
        )
        return

    if not query_str:
        print_error("Either provide a query or use --interactive/-i flag")
        print_info('Example: mu query "SELECT * FROM functions LIMIT 10"')
        print_info("         mu query -i")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Offline mode: skip daemon entirely
    if offline:
        _execute_muql_local(
            mubase_path, query_str, interactive, output_format, no_color, explain, no_truncate
        )
        return

    # Try daemon first (Thin Client path - no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            # Pass cwd for multi-project routing (use resolved root_path)
            result_dict = client.query(query_str, cwd=str(root_path))
            # Convert daemon response to QueryResult for formatting
            rows = [tuple(row) for row in result_dict.get("rows", [])]
            result = QueryResult(
                columns=result_dict.get("columns", []),
                rows=rows,
                row_count=result_dict.get("row_count", len(rows)),
                error=result_dict.get("error"),
                execution_time_ms=result_dict.get("execution_time_ms", 0.0),
            )
            output = format_result(result, output_format, no_color, no_truncate)
            console.print(output)
            return
        except DaemonError as e:
            # Log and fall back to local mode
            print_warning(f"Daemon query failed, falling back to local mode: {e}")

    # Fallback: Local mode (requires lock)
    _execute_muql_local(
        mubase_path, query_str, interactive, output_format, no_color, explain, no_truncate
    )


def _execute_muql_local(
    mubase_path: Path,
    query_str: str | None,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
    no_truncate: bool = False,
) -> None:
    """Execute MUQL query in local mode (direct MUbase access).

    Opens database in read-only mode for queries to avoid lock conflicts.
    Only interactive mode requires write access.
    """
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.muql import MUQLEngine
    from mu.kernel.muql.repl import run_repl
    from mu.logging import console, print_error, print_info

    # Use read-only mode for non-interactive queries to avoid lock issues
    read_only = not interactive

    try:
        db = MUbase(mubase_path, read_only=read_only)
    except MUbaseLockError:
        print_error("Database is locked by another process.")
        print_info("")
        print_info("The daemon may be running. Try one of these:")
        print_info("  1. Start daemon: mu daemon start")
        print_info("     Then queries route through daemon automatically")
        print_info("  2. Stop daemon:  mu daemon stop")
        print_info("     Then run your query again")
        sys.exit(ExitCode.CONFIG_ERROR)

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
                output = engine.query(query_str, output_format, no_color, no_truncate)
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
@click.option("--no-truncate", is_flag=True, help="Show full values without truncation")
@click.option("--full-paths", is_flag=True, help="Show full file paths (alias for --no-truncate)")
@click.option("--examples", is_flag=True, help="Show MUQL query examples")
@click.option("--schema", is_flag=True, help="Show MUQL schema reference (tables, columns, edge types)")
@click.option(
    "--offline", is_flag=True, help="Skip daemon, use local DB directly (also: MU_OFFLINE=1)"
)
@click.pass_context
def query(
    ctx: click.Context,
    muql: str | None,
    path: Path,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
    no_truncate: bool,
    full_paths: bool,
    examples: bool,
    schema: bool,
    offline: bool,
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
        mu query --no-truncate "SELECT * FROM modules"
        mu query --examples                 # Show query examples
        mu query --schema                   # Show schema reference
        mu query --offline "SELECT ..."     # Skip daemon, use local DB
    """
    if examples:
        click.echo(MUQL_EXAMPLES)
        return

    if schema:
        click.echo(MUQL_SCHEMA)
        return

    # Combine no_truncate and full_paths (either one disables truncation)
    effective_no_truncate = no_truncate or full_paths

    # Check global context for output settings
    obj = getattr(ctx, "obj", None) if ctx else None
    if obj:
        # Global format overrides command format
        if obj.output_format:
            output_format = obj.output_format
        # Global no_truncate overrides
        if obj.no_truncate:
            effective_no_truncate = True
        # Global no_color overrides
        if obj.no_color:
            no_color = True

    _execute_muql(
        path, muql, interactive, output_format, no_color, explain, effective_no_truncate, offline
    )


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
@click.option("--no-truncate", is_flag=True, help="Show full values without truncation")
@click.option("--full-paths", is_flag=True, help="Show full file paths (alias for --no-truncate)")
@click.option("--examples", is_flag=True, help="Show MUQL query examples")
@click.option("--schema", is_flag=True, help="Show MUQL schema reference (tables, columns, edge types)")
@click.option(
    "--offline", is_flag=True, help="Skip daemon, use local DB directly (also: MU_OFFLINE=1)"
)
@click.pass_context
def q(
    ctx: click.Context,
    muql: str | None,
    path: Path,
    interactive: bool,
    output_format: str,
    no_color: bool,
    explain: bool,
    no_truncate: bool,
    full_paths: bool,
    examples: bool,
    schema: bool,
    offline: bool,
) -> None:
    """Execute MUQL query (short alias for 'mu query').

    \b
    Examples:
        mu q "SELECT * FROM functions LIMIT 10"
        mu q -i
        mu q --examples
        mu q --schema
        mu q --offline "SELECT ..."
    """
    if examples:
        click.echo(MUQL_EXAMPLES)
        return

    if schema:
        click.echo(MUQL_SCHEMA)
        return

    # Combine no_truncate and full_paths (either one disables truncation)
    effective_no_truncate = no_truncate or full_paths

    # Check global context for output settings
    obj = getattr(ctx, "obj", None) if ctx else None
    if obj:
        # Global format overrides command format
        if obj.output_format:
            output_format = obj.output_format
        # Global no_truncate overrides
        if obj.no_truncate:
            effective_no_truncate = True
        # Global no_color overrides
        if obj.no_color:
            no_color = True

    _execute_muql(
        path, muql, interactive, output_format, no_color, explain, effective_no_truncate, offline
    )


__all__ = ["query", "q", "_execute_muql", "_execute_muql_local"]
