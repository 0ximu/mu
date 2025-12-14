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
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.output import OutputConfig


def _get_mubase_path(path: Path) -> tuple[Path, Path]:
    """Resolve and validate .mu/mubase path, returning (mubase_path, root_path).

    Uses find_mubase_path() to walk up directories, making commands workspace-aware.
    """
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info
    from mu.paths import find_mubase_path, get_mubase_path

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
    return mubase_path, root_path


def _get_output_config(
    ctx: click.Context | None,
    output_format: str,
    no_color: bool,
    no_truncate: bool = False,
) -> OutputConfig:
    """Build OutputConfig from command options and context."""
    from mu.commands.utils import is_interactive
    from mu.output import OutputConfig

    # Check if global options should override command options
    obj = getattr(ctx, "obj", None) if ctx else None

    # Global format overrides command format
    fmt = output_format
    if obj and obj.output_format:
        fmt = obj.output_format

    # TTY auto-detection
    is_tty = is_interactive()

    # Combine flags: command flags OR global flags OR auto-detection
    final_no_truncate = no_truncate or (obj and obj.no_truncate) or not is_tty
    final_no_color = no_color or (obj and obj.no_color) or not is_tty
    width = (obj.width if obj else None) or None

    return OutputConfig(
        format=fmt,
        no_truncate=final_no_truncate,
        no_color=final_no_color,
        width=width,
    )


def _format_node_list(
    nodes: list[str],
    title: str,
    config: OutputConfig,
) -> str:
    """Format a list of node IDs for output using unified output module."""
    from mu.output import format_node_list

    return format_node_list(nodes, title, config)


def _format_cycles_output(
    cycles: list[list[str]],
    config: OutputConfig,
) -> str:
    """Format cycle detection results using unified output module."""
    from mu.output import format_cycles

    return format_cycles(cycles, config)


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
@click.option("--no-truncate", is_flag=True, help="Show full node IDs without truncation")
@click.option("--no-interactive", "-n", is_flag=True, help="Disable interactive disambiguation")
@click.option("--quiet", "-q", is_flag=True, help="Suppress resolution info messages")
@click.pass_context
def impact(
    ctx: click.Context,
    node: str,
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
    no_truncate: bool,
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
        mu impact MUbase --no-truncate   # Show full node IDs
    """
    from mu.client import DaemonClient, DaemonError
    from mu.logging import print_warning

    # Build output config from context and options
    config = _get_output_config(ctx, output_format, no_color, no_truncate)

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
            output = _format_node_list(impacted, title, config)
            click.echo(output)
            return
        except DaemonError as e:
            print_warning(f"Daemon request failed, falling back to local: {e}")
        except Exception as e:
            print_warning(f"Daemon query failed, falling back to local: {e}")

    # Fallback: Local mode (requires lock)
    _impact_local(
        ctx, node, path, edge_types, output_format, no_color, no_truncate, no_interactive, quiet
    )


def _impact_local(
    ctx: click.Context,
    node: str,
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
    no_truncate: bool = False,
    no_interactive: bool = False,
    quiet: bool = False,
) -> None:
    """Execute impact analysis in local mode (direct MUbase access)."""
    import sys

    from mu.commands.utils import resolve_node_for_command
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.graph import GraphManager
    from mu.logging import print_error, print_info

    mubase_path, _root_path = _get_mubase_path(path)

    # Build output config
    config = _get_output_config(ctx, output_format, no_color, no_truncate)

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
        output = _format_node_list(impacted, title, config)
        click.echo(output)

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
@click.option("--no-truncate", is_flag=True, help="Show full node IDs without truncation")
@click.option("--no-interactive", "-n", is_flag=True, help="Disable interactive disambiguation")
@click.option("--quiet", "-q", is_flag=True, help="Suppress resolution info messages")
@click.pass_context
def ancestors(
    ctx: click.Context,
    node: str,
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
    no_truncate: bool,
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
        mu ancestors MUbase --no-truncate  # Show full node IDs
    """
    from mu.client import DaemonClient, DaemonError
    from mu.logging import print_warning

    # Build output config from context and options
    config = _get_output_config(ctx, output_format, no_color, no_truncate)

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
            output = _format_node_list(ancestor_nodes, title, config)
            click.echo(output)
            return
        except DaemonError as e:
            print_warning(f"Daemon request failed, falling back to local: {e}")
        except Exception as e:
            print_warning(f"Daemon query failed, falling back to local: {e}")

    # Fallback: Local mode (requires lock)
    _ancestors_local(
        ctx, node, path, edge_types, output_format, no_color, no_truncate, no_interactive, quiet
    )


def _ancestors_local(
    ctx: click.Context,
    node: str,
    path: Path,
    edge_types: tuple[str, ...],
    output_format: str,
    no_color: bool,
    no_truncate: bool = False,
    no_interactive: bool = False,
    quiet: bool = False,
) -> None:
    """Execute ancestors analysis in local mode (direct MUbase access)."""
    from mu.commands.utils import resolve_node_for_command
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.graph import GraphManager
    from mu.logging import print_error, print_info

    mubase_path, _root_path = _get_mubase_path(path)

    # Build output config
    config = _get_output_config(ctx, output_format, no_color, no_truncate)

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
        output = _format_node_list(ancestor_nodes, title, config)
        click.echo(output)

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
    default=("imports", "inherits"),
    help="Filter by edge type (imports, calls, inherits, contains). Defaults to imports,inherits (architectural cycles).",
)
@click.option(
    "--all-edges",
    is_flag=True,
    help="Include all edge types (imports, calls, inherits, contains). Shows recursive patterns too.",
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
@click.option("--no-truncate", is_flag=True, help="Show full node IDs without truncation")
@click.pass_context
def cycles(
    ctx: click.Context,
    path: Path,
    edge_types: tuple[str, ...],
    all_edges: bool,
    output_format: str,
    no_color: bool,
    no_truncate: bool,
) -> None:
    """Detect circular dependencies in the codebase.

    Uses Kosaraju's strongly connected components algorithm via petgraph: O(V + E)

    By default, only checks imports and inherits edges (architectural cycles).
    Use --all-edges to include call cycles (recursive functions).

    \b
    Examples:
        mu cycles                           # Architectural cycles (imports, inherits)
        mu cycles --all-edges               # All cycles including recursive calls
        mu cycles -e calls                  # Only call cycles
        mu cycles -e imports -e calls       # Import and call cycles
        mu cycles -f json                   # JSON output
        mu cycles --no-truncate             # Show full node IDs
    """
    from mu.client import DaemonClient, DaemonError
    from mu.logging import print_info, print_warning

    # Build output config from context and options
    config = _get_output_config(ctx, output_format, no_color, no_truncate)

    # Determine effective edge types
    # --all-edges overrides --edge-types to None (all edges)
    # Otherwise use the provided/default edge_types
    effective_edge_types: list[str] | None = None if all_edges else list(edge_types)

    # Try daemon HTTP client first (no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            result = client.cycles(edge_types=effective_edge_types, cwd=str(path.resolve()))

            # Handle daemon response format
            data = result.get("data", result)
            if isinstance(data, list):
                detected_cycles = data
                total_nodes = sum(len(c) for c in detected_cycles)
            else:
                detected_cycles = []
                total_nodes = 0

            print_info(f"Analyzed graph: {total_nodes} nodes in cycles")

            output = _format_cycles_output(detected_cycles, config)
            click.echo(output)
            return
        except DaemonError as e:
            print_warning(f"Daemon request failed, falling back to local: {e}")
        except Exception as e:
            print_warning(f"MCP tool failed, falling back to local: {e}")

    # Fallback: Local mode (requires lock)
    _cycles_local(ctx, path, effective_edge_types, output_format, no_color, no_truncate)


def _cycles_local(
    ctx: click.Context,
    path: Path,
    edge_types: list[str] | None,
    output_format: str,
    no_color: bool,
    no_truncate: bool = False,
) -> None:
    """Execute cycle detection in local mode (direct MUbase access)."""
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.graph import GraphManager
    from mu.logging import print_error, print_info

    mubase_path, _root_path = _get_mubase_path(path)

    # Build output config
    config = _get_output_config(ctx, output_format, no_color, no_truncate)

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
        edge_type_desc = ", ".join(edge_types) if edge_types else "all"
        print_info(f"Edge types: {edge_type_desc}")

        # Run cycle detection
        detected_cycles = gm.find_cycles(edge_types)

        # Format and output
        output = _format_cycles_output(detected_cycles, config)
        click.echo(output)

    finally:
        db.close()


__all__ = ["impact", "ancestors", "cycles"]
