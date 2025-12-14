"""MU yolo command - Impact analysis for code changes.

This command shows downstream impact of modifying a file or node,
using BFS traversal to find all dependents.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import find_mubase_path

from ._utils import prompt_for_input

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command(name="yolo", short_help="Impact check - what breaks if I change this?")
@click.argument("target", required=False)
@click.option("--depth", "-d", default=2, help="Traversal depth")
@click.option(
    "--type",
    "-t",
    "edge_types",
    multiple=True,
    help="Edge types: imports, calls, inherits, contains",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def yolo(
    ctx: MUContext,
    target: str | None,
    depth: int,
    edge_types: tuple[str, ...],
    as_json: bool,
) -> None:
    """Impact check - what breaks if I change this?

    Shows downstream impact of modifying a file or node.
    Uses BFS traversal to find all dependents.

    \b
    Examples:
        mu yolo src/mu/kernel/mubase.py
        mu yolo MUbase
        mu yolo AuthService -d 3
        mu yolo  # Interactive mode
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import print_error

    # Interactive mode
    if not target:
        target = prompt_for_input("What file or symbol do you want to check?", "yolo")

    # Find mubase
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    if not mubase_path:
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(1)

    # Try daemon first
    client = DaemonClient()
    if client.is_running():
        try:
            # Resolve node to full ID if it's a short name
            resolved_node = target
            if not target.startswith(("mod:", "cls:", "fn:")):
                found = client.find_node(target, cwd=str(cwd))
                if found:
                    resolved_node = found.get("id", target)

            edge_type_list = list(edge_types) if edge_types else None
            result = client.impact(resolved_node, edge_types=edge_type_list, cwd=str(cwd))

            # Handle daemon response format
            impacted = result.get("impacted_nodes", result.get("data", []))
            if isinstance(impacted, dict):
                impacted = []

            if as_json:
                click.echo(
                    json.dumps(
                        {
                            "target": target,
                            "node_id": resolved_node,
                            "impacted_count": len(impacted),
                            "impacted": impacted,
                        },
                        indent=2,
                    )
                )
                return

            click.echo()
            click.echo(
                click.style("YOLO: ", fg="magenta", bold=True) + click.style(target, bold=True)
            )
            click.echo()
            click.echo(click.style(f"{len(impacted)} nodes affected", fg="yellow", bold=True))

            if impacted:
                click.echo()
                click.echo(click.style(f"Impacted nodes ({len(impacted)})", fg="cyan"))
                for node_id in impacted[:15]:
                    click.echo(click.style("  * ", dim=True) + str(node_id))
                if len(impacted) > 15:
                    click.echo(click.style(f"  ... and {len(impacted) - 15} more", dim=True))

            click.echo()
            if len(impacted) > 10:
                click.echo(
                    click.style(
                        f"!!  High impact - changes affect {len(impacted)} downstream nodes",
                        fg="yellow",
                    )
                )
            else:
                click.echo(click.style("Low impact. Go ahead, YOLO!", dim=True))
            return
        except DaemonError:
            pass  # Fall through to local mode

    # Local mode
    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)

    try:
        from mu.commands.utils import resolve_node_for_command
        from mu.kernel.graph import GraphManager

        # Resolve target using NodeResolver (same as mu impact)
        try:
            resolved_node, resolution = resolve_node_for_command(
                db, target, no_interactive=True, quiet=True
            )
        except SystemExit:
            print_error(f"Could not find node: {target}")
            sys.exit(1)

        # Use GraphManager for impact analysis (same as mu impact)
        gm = GraphManager(db.conn)
        gm.load()

        # Check node exists in graph
        if not gm.has_node(resolved_node.id):
            print_error(f"Node not in graph: {resolved_node.id}")
            sys.exit(1)

        # Run impact analysis using petgraph (same as mu impact)
        edge_type_list = list(edge_types) if edge_types else None
        impacted = gm.impact(resolved_node.id, edge_type_list)

        if as_json:
            click.echo(
                json.dumps(
                    {
                        "target": target,
                        "node_id": resolved_node.id,
                        "impacted_count": len(impacted),
                        "impacted": impacted,
                    },
                    indent=2,
                )
            )
            return

        click.echo()
        click.echo(click.style("YOLO: ", fg="magenta", bold=True) + click.style(target, bold=True))
        if resolution.was_ambiguous:
            click.echo(
                click.style("  Resolved to: ", dim=True) + click.style(resolved_node.id, fg="cyan")
            )
        click.echo()
        click.echo(click.style(f"{len(impacted)} nodes affected", fg="yellow", bold=True))

        if impacted:
            click.echo()
            click.echo(click.style(f"Impacted nodes ({len(impacted)})", fg="cyan"))
            for node_id in impacted[:15]:
                click.echo(click.style("  * ", dim=True) + str(node_id))
            if len(impacted) > 15:
                click.echo(click.style(f"  ... and {len(impacted) - 15} more", dim=True))

        click.echo()
        if len(impacted) > 10:
            click.echo(
                click.style(
                    f"!!  High impact - changes affect {len(impacted)} downstream nodes",
                    fg="yellow",
                )
            )
        else:
            click.echo(click.style("Low impact. Go ahead, YOLO!", dim=True))

    finally:
        db.close()


__all__ = ["yolo"]
