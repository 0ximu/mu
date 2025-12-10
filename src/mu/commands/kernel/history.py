"""MU kernel history command - Show change history for a node."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import get_mubase_path


@click.command("history")
@click.argument("node_ref", type=str, metavar="NODE")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--limit", "-l", type=int, default=20, help="Maximum changes to show")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--no-interactive", is_flag=True, help="Skip interactive prompts")
def kernel_history(node_ref: str, path: Path, limit: int, as_json: bool, no_interactive: bool) -> None:
    """Show change history for a node.

    NODE can be a name, file path, or full node ID:
      - AuthService (class/function name)
      - src/auth.py (file path)
      - cls:src/auth.py:AuthService (full node ID)

    \b
    Examples:
        mu history AuthService
        mu history src/auth.py --limit 50
        mu history cls:src/auth.py:AuthService --json
    """
    import json as json_module

    from rich.table import Table

    from mu.commands.utils import resolve_node_for_command
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
        # Resolve the node using intelligent resolution
        node, _resolution = resolve_node_for_command(
            db, node_ref, no_interactive=no_interactive, quiet=as_json
        )
        tracker = HistoryTracker(db)
        changes = tracker.history(node.id, limit=limit)

        if not changes:
            print_info(f"No history found for {node.name}")
            print_info("Create snapshots with 'mu kernel snapshot' to track history")
            return

        if as_json:
            console.print(json_module.dumps([c.to_dict() for c in changes], indent=2, default=str))
        else:
            table = Table(title=f"History of {node.name}")
            table.add_column("Commit", style="cyan", width=10)
            table.add_column("Change", style="yellow", width=10)
            table.add_column("Author", style="dim")
            table.add_column("Date")
            table.add_column("Message", style="green")

            for change in changes:
                date_str = change.commit_date.strftime("%Y-%m-%d") if change.commit_date else ""
                message = (change.commit_message or "")[:30]

                table.add_row(
                    (change.commit_hash or "")[:8],
                    change.change_type.value,
                    change.commit_author or "",
                    date_str,
                    message,
                )

            console.print(table)
    finally:
        db.close()


__all__ = ["kernel_history"]
