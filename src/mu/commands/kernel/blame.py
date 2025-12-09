"""MU kernel blame command - Show who last modified a node."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import get_mubase_path


@click.command("blame")
@click.argument("node_name", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_blame(node_name: str, path: Path, as_json: bool) -> None:
    """Show who last modified each aspect of a node.

    Similar to git blame, shows attribution for node properties.

    \b
    Examples:
        mu kernel blame MUbase .
        mu kernel blame "cli.py" . --json
    """
    import json as json_module

    from rich.table import Table

    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.kernel.temporal import HistoryTracker
    from mu.logging import console, print_error, print_info

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        sys.exit(ExitCode.CONFIG_ERROR)

    from mu.kernel import MUbaseLockError

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)

    try:
        # Find the node
        nodes = db.find_by_name(node_name)
        if not nodes:
            nodes = db.find_by_name(f"%{node_name}%")
        if not nodes:
            print_error(f"Node not found: {node_name}")
            return

        node = nodes[0]
        tracker = HistoryTracker(db)
        blame_info = tracker.blame(node.id)

        if not blame_info:
            print_info(f"No blame info found for {node.name}")
            return

        if as_json:
            output = {prop: change.to_dict() for prop, change in blame_info.items()}
            console.print(json_module.dumps(output, indent=2, default=str))
        else:
            table = Table(title=f"Blame for {node.name}")
            table.add_column("Property", style="cyan")
            table.add_column("Commit", style="yellow", width=10)
            table.add_column("Author", style="green")
            table.add_column("Date", style="dim")

            for prop_name, change in blame_info.items():
                date_str = change.commit_date.strftime("%Y-%m-%d") if change.commit_date else ""

                table.add_row(
                    prop_name,
                    (change.commit_hash or "")[:8],
                    change.commit_author or "",
                    date_str,
                )

            console.print(table)
    finally:
        db.close()


__all__ = ["kernel_blame"]
