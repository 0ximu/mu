"""MU daemon status command - Check daemon status."""

from __future__ import annotations

from pathlib import Path

import click

from mu.paths import get_daemon_pid_path


@click.command("status")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def daemon_status(path: Path, as_json: bool) -> None:
    """Check daemon status.

    \b
    Example:
        mu daemon status
        mu daemon status --json
    """
    import json as json_module

    from rich.table import Table

    from mu.daemon.config import DaemonConfig
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.logging import console, print_info

    pid_file = get_daemon_pid_path(path)
    config = DaemonConfig(pid_file=pid_file)
    lifecycle = DaemonLifecycle(pid_file=pid_file, config=config)

    status = lifecycle.status()

    if as_json:
        console.print(json_module.dumps(status, indent=2))
        return

    if status.get("status") == "stopped":
        print_info("Daemon is not running")
        return

    # Build status table
    table = Table(title="MU Daemon Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Status", status.get("status", "unknown"))
    if "pid" in status:
        table.add_row("PID", str(status["pid"]))
    if "healthy" in status:
        table.add_row("Healthy", "Yes" if status["healthy"] else "No")
    if "mubase_path" in status:
        table.add_row("Database", status["mubase_path"])
    if "uptime_seconds" in status:
        uptime = status["uptime_seconds"]
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        if hours > 0:
            table.add_row("Uptime", f"{hours}h {minutes}m {seconds}s")
        elif minutes > 0:
            table.add_row("Uptime", f"{minutes}m {seconds}s")
        else:
            table.add_row("Uptime", f"{seconds}s")
    if "connections" in status:
        table.add_row("WebSocket Connections", str(status["connections"]))
    if "stats" in status:
        stats = status["stats"]
        if "nodes" in stats:
            table.add_row("Nodes", str(stats["nodes"]))
        if "edges" in stats:
            table.add_row("Edges", str(stats["edges"]))

    console.print(table)


__all__ = ["daemon_status"]
