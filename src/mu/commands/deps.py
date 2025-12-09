"""mu deps - Show dependencies for a node (promoted from kernel deps)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import get_mubase_path

if TYPE_CHECKING:
    from mu.output import OutputConfig


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


@click.command("deps")
@click.argument("node", type=str)
@click.option(
    "--depth",
    "-d",
    type=int,
    default=1,
    help="Traversal depth",
)
@click.option(
    "--reverse",
    "-r",
    is_flag=True,
    help="Show dependents instead of dependencies",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option(
    "--json", "as_json", is_flag=True, help="Output as JSON (deprecated, use --format json)"
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--no-truncate", is_flag=True, help="Show full values without truncation")
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=".",
    help="Path to codebase",
)
@click.pass_context
def deps(
    ctx: click.Context,
    node: str,
    depth: int,
    reverse: bool,
    output_format: str,
    as_json: bool,
    no_color: bool,
    no_truncate: bool,
    path: Path,
) -> None:
    """Show what NODE depends on (or what depends on it with --reverse).

    NODE can be a function, class, or module name.

    \b
    Examples:
        mu deps AuthService           # What does AuthService depend on?
        mu deps cli.py --depth 2      # Dependencies 2 levels deep
        mu deps GraphBuilder -r       # What depends on GraphBuilder?
        mu deps MUbase --format json  # Output as JSON
        mu deps MUbase --no-truncate  # Show full values
    """
    from typing import Any

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import print_error, print_info
    from mu.output import Column, format_output

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu bootstrap' first.")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Handle deprecated --json flag
    effective_format = output_format
    if as_json:
        effective_format = "json"

    # Build output config
    config = _get_output_config(ctx, effective_format, no_color, no_truncate)

    relation_type = "Dependents" if reverse else "Dependencies"

    # Try daemon first to avoid database locking
    client = DaemonClient()
    if client.is_running():
        try:
            direction = "incoming" if reverse else "outgoing"
            result = client.deps(node, depth=depth, direction=direction, cwd=str(path))

            deps_list = result.get("dependencies", [])

            # Convert to standard data format
            data: list[dict[str, Any]] = []
            for dep in deps_list:
                if isinstance(dep, dict):
                    data.append(
                        {
                            "name": dep.get("qualified_name") or dep.get("name", str(dep)),
                            "type": dep.get("type", "unknown"),
                            "file_path": dep.get("file_path", ""),
                        }
                    )
                else:
                    data.append({"name": str(dep), "type": "unknown", "file_path": ""})

            title = f"{relation_type} of {node} (depth={depth}, {len(data)} nodes)"
            columns = [
                Column("Name", "name"),
                Column("Type", "type"),
                Column("File", "file_path"),
            ]

            output = format_output(data, columns, config, title=title)
            click.echo(output)
            return
        except DaemonError:
            # Fall through to local database access
            pass
        finally:
            client.close()

    # Fallback to direct database access
    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked by the daemon. The daemon should be routing queries, but isn't responding."
        )
        print_info("Try: mu serve --stop && mu serve")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Find the node by name
    matching_nodes = db.find_by_name(f"%{node}%")

    if not matching_nodes:
        print_error(f"No node found matching '{node}'")
        db.close()
        sys.exit(ExitCode.CONFIG_ERROR)

    # Use the first match
    target_node = matching_nodes[0]
    if len(matching_nodes) > 1:
        print_info(
            f"Multiple matches found, using: {target_node.qualified_name or target_node.name}"
        )

    # Get dependencies or dependents
    if reverse:
        related = db.get_dependents(target_node.id, depth=depth)
    else:
        related = db.get_dependencies(target_node.id, depth=depth)

    db.close()

    # Convert to standard data format
    data = []
    for n in related:
        data.append(
            {
                "name": n.qualified_name or n.name,
                "type": n.type.value,
                "file_path": n.file_path or "",
            }
        )

    title = f"{relation_type} of {target_node.qualified_name or target_node.name} (depth={depth}, {len(data)} nodes)"
    columns = [
        Column("Name", "name"),
        Column("Type", "type"),
        Column("File", "file_path"),
    ]

    output = format_output(data, columns, config, title=title)
    click.echo(output)


__all__ = ["deps"]
