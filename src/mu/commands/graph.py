"""MU graph reasoning commands - Impact analysis, ancestors, and cycle detection.

These commands expose the Rust-based petgraph algorithms for graph reasoning:
- mu impact: Find downstream impact ("If I change X, what breaks?")
- mu ancestors: Find upstream dependencies ("What does X depend on?")
- mu cycles: Detect circular dependencies

Thin Client Architecture (ADR-002):
- If daemon is running, forward requests via MCP tools (no DB lock)
- If daemon is not running, fall back to local MUbase access
"""

from __future__ import annotations

import sys
from pathlib import Path

import click


def _get_mubase_path(path: Path) -> Path:
    """Resolve and validate .mu/mubase path."""
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info
    from mu.paths import get_mubase_path

    mubase_path = get_mubase_path(path)
    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu kernel init' and 'mu kernel build' first")
        sys.exit(ExitCode.CONFIG_ERROR)
    return mubase_path


def _format_node_list(
    nodes: list[str],
    title: str,
    output_format: str,
    no_color: bool,
) -> str:
    """Format a list of node IDs for output."""
    import json

    from rich.table import Table

    if output_format == "json":
        return json.dumps({"title": title, "nodes": nodes, "count": len(nodes)}, indent=2)

    if output_format == "csv":
        lines = ["node_id"]
        lines.extend(nodes)
        return "\n".join(lines)

    # Default: table format
    table = Table(title=title, show_header=True)
    table.add_column("Node ID", style="cyan" if not no_color else None)

    for node in nodes:
        table.add_row(node)

    # Convert table to string using Rich console
    from io import StringIO

    from rich.console import Console

    string_io = StringIO()
    console = Console(file=string_io, force_terminal=not no_color)
    console.print(table)
    return string_io.getvalue()


def _format_cycles(
    cycles: list[list[str]],
    output_format: str,
    no_color: bool,
) -> str:
    """Format cycle detection results."""
    import json

    from rich.table import Table

    if output_format == "json":
        return json.dumps(
            {
                "cycles": cycles,
                "cycle_count": len(cycles),
                "total_nodes": sum(len(c) for c in cycles),
            },
            indent=2,
        )

    if output_format == "csv":
        lines = ["cycle_id,node_id"]
        for i, cycle in enumerate(cycles):
            for node in cycle:
                lines.append(f"{i},{node}")
        return "\n".join(lines)

    # Default: table format
    if not cycles:
        return "No cycles detected."

    table = Table(title=f"Circular Dependencies ({len(cycles)} cycles)", show_header=True)
    table.add_column("Cycle", style="yellow" if not no_color else None)
    table.add_column("Nodes", style="cyan" if not no_color else None)

    for i, cycle in enumerate(cycles):
        # Show cycle as: A -> B -> C -> A
        cycle_str = " -> ".join(cycle)
        if cycle:
            cycle_str += f" -> {cycle[0]}"  # Complete the cycle visually
        table.add_row(str(i + 1), cycle_str)

    from io import StringIO

    from rich.console import Console

    string_io = StringIO()
    console = Console(file=string_io, force_terminal=not no_color)
    console.print(table)
    return string_io.getvalue()


@click.command("impact")
@click.argument("node")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=".",
    help="Path to codebase (default: current directory)",
)
@click.option(
    "--edge-types",
    "-e",
    multiple=True,
    help="Filter by edge type (imports, calls, inherits, contains). Can specify multiple.",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--no-interactive", "-n", is_flag=True, help="Disable interactive disambiguation")
@click.option("--quiet", "-q", is_flag=True, help="Suppress resolution info messages")
def impact(
    node: str,
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
    no_interactive: bool,
    quiet: bool,
) -> None:
    """Find downstream impact of changing a node.

    "If I change X, what might break?"

    Uses BFS traversal via petgraph: O(V + E)

    \b
    Examples:
        mu impact "mod:src/auth.py"
        mu impact AuthService
        mu impact "mod:src/kernel/mubase.py" --edge-types imports
        mu impact MUbase -f json
    """
    from mu.client import DaemonClient, DaemonError
    from mu.logging import console, print_warning

    # Try daemon HTTP client first (no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            # Resolve node to full ID if it's a short name
            resolved_node = node
            if not node.startswith(("mod:", "cls:", "fn:")):
                found = client.find_node(node, cwd=str(path.resolve()))
                if found:
                    resolved_node = found.get("id", node)

            edge_type_list = list(edge_types) if edge_types else None
            result = client.impact(
                resolved_node, edge_types=edge_type_list, cwd=str(path.resolve())
            )

            # Handle daemon response format - client.impact normalizes to dict
            # with 'impacted_nodes' key (see client.py)
            impacted = result.get("impacted_nodes", [])
            if not impacted:
                # Also check for raw list response or 'data' key
                data = result.get("data", result)
                if isinstance(data, list):
                    impacted = data

            title = f"Impact of {resolved_node} ({len(impacted)} nodes)"
            output = _format_node_list(impacted, title, output_format, no_color)
            console.print(output)
            return
        except DaemonError as e:
            print_warning(f"Daemon request failed, falling back to local: {e}")
        except Exception as e:
            print_warning(f"Daemon query failed, falling back to local: {e}")

    # Fallback: Local mode (requires lock)
    _impact_local(node, path, edge_types, output_format, no_color, no_interactive, quiet)


def _impact_local(
    node: str,
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
    no_interactive: bool = False,
    quiet: bool = False,
) -> None:
    """Execute impact analysis in local mode (direct MUbase access)."""
    import sys

    from mu.commands.utils import resolve_node_for_command
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.graph import GraphManager
    from mu.logging import console, print_error, print_info

    mubase_path = _get_mubase_path(path)

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)
    try:
        gm = GraphManager(db.conn)
        stats = gm.load()

        # Resolve node using NodeResolver with disambiguation
        resolved, resolution = resolve_node_for_command(
            db, node, no_interactive=no_interactive, quiet=quiet
        )
        resolved_node = resolved.id

        # Check node exists in graph
        if not gm.has_node(resolved_node):
            print_error(f"Node not in graph: {resolved_node}")
            print_info(
                f"Graph has {stats.node_count} nodes. Available edge types: {stats.edge_types}"
            )
            sys.exit(1)

        # Run impact analysis
        edge_type_list = list(edge_types) if edge_types else None
        impacted = gm.impact(resolved_node, edge_type_list)

        # Format and output
        title = f"Impact of {resolved_node} ({len(impacted)} nodes)"
        output = _format_node_list(impacted, title, output_format, no_color)
        console.print(output)

    finally:
        db.close()


@click.command("ancestors")
@click.argument("node")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=".",
    help="Path to codebase (default: current directory)",
)
@click.option(
    "--edge-types",
    "-e",
    multiple=True,
    help="Filter by edge type (imports, calls, inherits, contains). Can specify multiple.",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--no-interactive", "-n", is_flag=True, help="Disable interactive disambiguation")
@click.option("--quiet", "-q", is_flag=True, help="Suppress resolution info messages")
def ancestors(
    node: str,
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
    no_interactive: bool,
    quiet: bool,
) -> None:
    """Find upstream dependencies of a node.

    "What does X depend on?"

    Uses BFS traversal via petgraph: O(V + E)

    \b
    Examples:
        mu ancestors "mod:src/cli.py"
        mu ancestors UserService
        mu ancestors "fn:src/auth.py:login" --edge-types calls
        mu ancestors MUbase -f json
    """
    from mu.client import DaemonClient, DaemonError
    from mu.logging import console, print_warning

    # Try daemon HTTP client first (no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            # Resolve node to full ID if it's a short name
            resolved_node = node
            if not node.startswith(("mod:", "cls:", "fn:")):
                found = client.find_node(node, cwd=str(path.resolve()))
                if found:
                    resolved_node = found.get("id", node)

            edge_type_list = list(edge_types) if edge_types else None
            result = client.ancestors(
                resolved_node, edge_types=edge_type_list, cwd=str(path.resolve())
            )

            # Handle daemon response format - client.ancestors normalizes to dict
            # with 'ancestor_nodes' key (see client.py)
            ancestor_nodes = result.get("ancestor_nodes", [])
            if not ancestor_nodes:
                # Also check for raw list response or 'data' key
                data = result.get("data", result)
                if isinstance(data, list):
                    ancestor_nodes = data

            title = f"Ancestors of {resolved_node} ({len(ancestor_nodes)} nodes)"
            output = _format_node_list(ancestor_nodes, title, output_format, no_color)
            console.print(output)
            return
        except DaemonError as e:
            print_warning(f"Daemon request failed, falling back to local: {e}")
        except Exception as e:
            print_warning(f"Daemon query failed, falling back to local: {e}")

    # Fallback: Local mode (requires lock)
    _ancestors_local(node, path, edge_types, output_format, no_color, no_interactive, quiet)


def _ancestors_local(
    node: str,
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
    no_interactive: bool = False,
    quiet: bool = False,
) -> None:
    """Execute ancestors analysis in local mode (direct MUbase access)."""
    from mu.commands.utils import resolve_node_for_command
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.graph import GraphManager
    from mu.logging import console, print_error, print_info

    mubase_path = _get_mubase_path(path)

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)
    try:
        gm = GraphManager(db.conn)
        stats = gm.load()

        # Resolve node using NodeResolver with disambiguation
        resolved, resolution = resolve_node_for_command(
            db, node, no_interactive=no_interactive, quiet=quiet
        )
        resolved_node = resolved.id

        # Check node exists in graph
        if not gm.has_node(resolved_node):
            print_error(f"Node not in graph: {resolved_node}")
            print_info(
                f"Graph has {stats.node_count} nodes. Available edge types: {stats.edge_types}"
            )
            sys.exit(1)

        # Run ancestors analysis
        edge_type_list = list(edge_types) if edge_types else None
        ancestor_nodes = gm.ancestors(resolved_node, edge_type_list)

        # Format and output
        title = f"Ancestors of {resolved_node} ({len(ancestor_nodes)} nodes)"
        output = _format_node_list(ancestor_nodes, title, output_format, no_color)
        console.print(output)

    finally:
        db.close()


@click.command("cycles")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=".",
    help="Path to codebase (default: current directory)",
)
@click.option(
    "--edge-types",
    "-e",
    multiple=True,
    help="Filter by edge type (imports, calls, inherits, contains). Can specify multiple.",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
def cycles(
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
) -> None:
    """Detect circular dependencies in the codebase.

    Uses Kosaraju's strongly connected components algorithm via petgraph: O(V + E)

    \b
    Examples:
        mu cycles                           # All cycles
        mu cycles --edge-types imports      # Only import cycles
        mu cycles -e imports -e calls       # Import and call cycles
        mu cycles -f json                   # JSON output
    """
    from mu.client import DaemonClient, DaemonError
    from mu.logging import console, print_info, print_warning

    # Try daemon HTTP client first (no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            edge_type_list = list(edge_types) if edge_types else None
            result = client.cycles(edge_types=edge_type_list, cwd=str(path.resolve()))

            # Handle daemon response format
            data = result.get("data", result)
            if isinstance(data, list):
                detected_cycles = data
                total_nodes = sum(len(c) for c in detected_cycles)
            else:
                detected_cycles = []
                total_nodes = 0

            print_info(f"Analyzed graph: {total_nodes} nodes in cycles")

            output = _format_cycles(detected_cycles, output_format, no_color)
            console.print(output)
            return
        except DaemonError as e:
            print_warning(f"Daemon request failed, falling back to local: {e}")
        except Exception as e:
            print_warning(f"MCP tool failed, falling back to local: {e}")

    # Fallback: Local mode (requires lock)
    _cycles_local(path, edge_types, output_format, no_color)


def _cycles_local(
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
) -> None:
    """Execute cycle detection in local mode (direct MUbase access)."""
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.graph import GraphManager
    from mu.logging import console, print_error, print_info

    mubase_path = _get_mubase_path(path)

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)
    try:
        gm = GraphManager(db.conn)
        stats = gm.load()

        print_info(f"Analyzing graph: {stats.node_count} nodes, {stats.edge_count} edges")
        print_info(f"Edge types: {', '.join(stats.edge_types)}")

        # Run cycle detection
        edge_type_list = list(edge_types) if edge_types else None
        detected_cycles = gm.find_cycles(edge_type_list)

        # Format and output
        output = _format_cycles(detected_cycles, output_format, no_color)
        console.print(output)

    finally:
        db.close()


__all__ = ["impact", "ancestors", "cycles"]
