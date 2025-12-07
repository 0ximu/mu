"""MU kernel stats command - Show graph database statistics."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command("stats")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def kernel_stats(path: Path, as_json: bool) -> None:
    """Show graph database statistics."""
    import json as json_module

    from rich.table import Table

    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.logging import console, print_error, print_info

    mubase_path = path.resolve() / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel init' and 'mu kernel build' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)
    stats = db.stats()
    db.close()

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
