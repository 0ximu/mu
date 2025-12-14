"""MU kernel diff command - Show semantic diff between snapshots."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import get_mubase_path


@click.command("diff")
@click.argument("from_commit", type=str)
@click.argument("to_commit", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_diff(from_commit: str, to_commit: str, path: Path, as_json: bool) -> None:
    """Show semantic diff between two snapshots.

    \b
    Examples:
        mu kernel diff abc123 def456 .
        mu kernel diff HEAD~5 HEAD . --json
    """
    import json as json_module

    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.kernel.temporal import SnapshotManager, TemporalDiffer
    from mu.logging import console, print_error, print_info, print_success, print_warning

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
        manager = SnapshotManager(db, path.resolve())
        differ = TemporalDiffer(manager)

        try:
            diff = differ.diff(from_commit, to_commit)
        except ValueError as e:
            print_error(str(e))
            return

        if as_json:
            console.print(json_module.dumps(diff.to_dict(), indent=2, default=str))
        else:
            print_info(
                f"Changes from {diff.from_snapshot.short_hash} to {diff.to_snapshot.short_hash}"
            )
            print_info("")

            stats = diff.stats
            print_info(
                f"Summary: +{stats['nodes_added']} added, -{stats['nodes_removed']} removed, ~{stats['nodes_modified']} modified"
            )
            print_info("")

            if diff.nodes_added:
                print_success(f"Added Nodes ({len(diff.nodes_added)}):")
                for node_diff in diff.nodes_added[:10]:
                    print_info(f"  + [{node_diff.node_type}] {node_diff.name}")
                if len(diff.nodes_added) > 10:
                    print_info(f"  ... and {len(diff.nodes_added) - 10} more")

            if diff.nodes_removed:
                print_warning(f"Removed Nodes ({len(diff.nodes_removed)}):")
                for node_diff in diff.nodes_removed[:10]:
                    print_info(f"  - [{node_diff.node_type}] {node_diff.name}")
                if len(diff.nodes_removed) > 10:
                    print_info(f"  ... and {len(diff.nodes_removed) - 10} more")

            if diff.nodes_modified:
                print_info(f"Modified Nodes ({len(diff.nodes_modified)}):")
                for node_diff in diff.nodes_modified[:10]:
                    print_info(f"  ~ [{node_diff.node_type}] {node_diff.name}")
                if len(diff.nodes_modified) > 10:
                    print_info(f"  ... and {len(diff.nodes_modified) - 10} more")
    finally:
        db.close()


__all__ = ["kernel_diff"]
