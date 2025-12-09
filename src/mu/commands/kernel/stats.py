"""MU kernel stats command - Show graph database statistics.

DEPRECATED: Use 'mu status' instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import get_mubase_path


def _show_deprecation_warning() -> None:
    """Show deprecation warning for kernel stats."""
    click.secho(
        "⚠️  'mu kernel stats' is deprecated. Use 'mu status' instead.",
        fg="yellow",
        err=True,
    )


@click.command("stats")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_stats(path: Path, as_json: bool) -> None:
    """[DEPRECATED] Show graph database statistics.

    Use 'mu status' instead.
    """
    _show_deprecation_warning()
    import json as json_module

    from rich.table import Table

    from mu.client import DaemonClient
    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.logging import console, print_error, print_info

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu kernel init' and 'mu kernel build' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Try daemon first to avoid DuckDB lock conflicts
    client = DaemonClient()
    stats = None
    if client.is_running():
        try:
            status_resp = client.status(cwd=str(path.resolve()))
            # Rust daemon returns flat response with node_count/edge_count
            # Normalize to expected stats format
            stats = status_resp.get("stats", {})
            if not stats:
                # Rust daemon format - normalize keys
                stats = {
                    "nodes": status_resp.get("node_count", 0),
                    "edges": status_resp.get("edge_count", 0),
                    "nodes_by_type": {},  # Not available from daemon status
                    "edges_by_type": {},  # Not available from daemon status
                    "file_size_kb": 0,
                    "version": status_resp.get("schema_version", "unknown"),
                    "built_at": None,
                }
        except Exception:
            pass  # Fall through to local mode
        finally:
            client.close()
    else:
        client.close()

    # Fallback to local mode if daemon not available
    if stats is None:
        from mu.kernel import MUbaseLockError

        try:
            db = MUbase(mubase_path, read_only=True)
            stats = db.stats()
            db.close()
        except MUbaseLockError:
            print_error(
                "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
            )
            sys.exit(ExitCode.CONFIG_ERROR)

    if as_json:
        console.print(json_module.dumps(stats, indent=2, default=str))
        return

    table = Table(title="MU Kernel Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Nodes", str(stats["nodes"]))
    table.add_row("Total Edges", str(stats["edges"]))
    table.add_row("", "")

    # Nodes by type
    for node_type, count in stats.get("nodes_by_type", {}).items():
        table.add_row(f"  {node_type.title()}", str(count))

    table.add_row("", "")

    # Edges by type
    for edge_type, count in stats.get("edges_by_type", {}).items():
        table.add_row(f"  {edge_type.title()} edges", str(count))

    table.add_row("", "")
    table.add_row("File Size", f"{stats.get('file_size_kb', 0):.1f} KB")
    table.add_row("Version", stats.get("version", "unknown"))

    if stats.get("built_at"):
        table.add_row("Built At", str(stats["built_at"]))

    console.print(table)


__all__ = ["kernel_stats"]
