"""MU kernel snapshot command - Create temporal snapshots."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command("snapshot")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--commit", "-c", type=str, help="Git commit to snapshot (default: HEAD)")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing snapshot")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_snapshot(path: Path, commit: str | None, force: bool, as_json: bool) -> None:
    """Create a temporal snapshot of the current graph state.

    Links the current state of the code graph to a git commit,
    enabling time-travel queries and history tracking.

    \b
    Examples:
        mu kernel snapshot .                 # Snapshot at HEAD
        mu kernel snapshot . --commit abc123 # Snapshot at specific commit
        mu kernel snapshot . --force         # Overwrite existing
    """
    import json as json_module

    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.kernel.temporal import SnapshotManager
    from mu.logging import console, print_error, print_info, print_success

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)

    try:
        manager = SnapshotManager(db, path.resolve())
        snapshot = manager.create_snapshot(commit, force=force)

        if as_json:
            console.print(json_module.dumps(snapshot.to_dict(), indent=2, default=str))
        else:
            print_success(f"Created snapshot: {snapshot.short_hash}")
            print_info(f"  Commit: {snapshot.commit_hash}")
            if snapshot.commit_message:
                print_info(f"  Message: {snapshot.commit_message[:60]}...")
            print_info(f"  Nodes: {snapshot.node_count}")
            print_info(f"  Edges: {snapshot.edge_count}")
            if snapshot.parent_id:
                print_info(
                    f"  Changes: +{snapshot.nodes_added} -{snapshot.nodes_removed} ~{snapshot.nodes_modified}"
                )
    except ValueError as e:
        print_error(str(e))
        sys.exit(ExitCode.CONFIG_ERROR)
    finally:
        db.close()


@click.command("snapshots")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--limit", "-l", type=int, default=20, help="Maximum snapshots to show")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_snapshots(path: Path, limit: int, as_json: bool) -> None:
    """List all temporal snapshots.

    \b
    Examples:
        mu kernel snapshots .
        mu kernel snapshots . --limit 50
    """
    import json as json_module

    from rich.table import Table

    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.kernel.temporal import SnapshotManager
    from mu.logging import console, print_error, print_info

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)

    try:
        manager = SnapshotManager(db, path.resolve())
        snapshots = manager.list_snapshots(limit)

        if not snapshots:
            print_info("No snapshots found. Run 'mu kernel snapshot' to create one.")
            return

        if as_json:
            console.print(
                json_module.dumps([s.to_dict() for s in snapshots], indent=2, default=str)
            )
        else:
            table = Table(title=f"Temporal Snapshots ({len(snapshots)})")
            table.add_column("Commit", style="cyan", width=10)
            table.add_column("Date", style="dim")
            table.add_column("Message", style="green")
            table.add_column("Nodes", justify="right")
            table.add_column("Changes", style="yellow")

            for snap in snapshots:
                date_str = snap.commit_date.strftime("%Y-%m-%d %H:%M") if snap.commit_date else ""
                message = (snap.commit_message or "")[:40]
                changes = f"+{snap.nodes_added} -{snap.nodes_removed} ~{snap.nodes_modified}"

                table.add_row(
                    snap.short_hash,
                    date_str,
                    message,
                    str(snap.node_count),
                    changes,
                )

            console.print(table)
    finally:
        db.close()


__all__ = ["kernel_snapshot", "kernel_snapshots"]
