"""mu serve - Unified service management."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import get_daemon_pid_path, get_mubase_path


@click.command("serve")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--port", "-p", type=int, default=9120, help="HTTP port (default: 9120)")
@click.option("--host", type=str, default="127.0.0.1", help="Bind address")
@click.option("--foreground", "-f", is_flag=True, help="Run in foreground (don't daemonize)")
@click.option("--stop", is_flag=True, help="Stop running server")
@click.option("--status", is_flag=True, help="Check server status")
@click.option("--mcp", is_flag=True, help="Start MCP server instead of HTTP daemon")
def serve(
    path: Path,
    port: int,
    host: str,
    foreground: bool,
    stop: bool,
    status: bool,
    mcp: bool,
) -> None:
    """Start MU server (daemon + optional MCP).

    The server watches for file changes and provides an HTTP/WebSocket
    API for querying the code graph.

    \b
    Examples:
        mu serve              # Start daemon in background
        mu serve -f           # Run in foreground (Ctrl+C to stop)
        mu serve --stop       # Stop running daemon
        mu serve --status     # Check if daemon is running
        mu serve --mcp        # Start MCP server (for Claude Code)
    """
    if stop:
        _serve_stop(path)
    elif status:
        _serve_status(path)
    elif mcp:
        _serve_mcp()
    elif foreground:
        _serve_foreground(path, port, host)
    else:
        _serve_background(path, port, host)


def _serve_stop(path: Path) -> None:
    """Stop running daemon."""
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.logging import print_info, print_success

    pid_file = get_daemon_pid_path(path)
    lifecycle = DaemonLifecycle(pid_file=pid_file)

    if lifecycle.stop():
        print_success("MU daemon stopped")
    else:
        print_info("Daemon not running")


def _serve_status(path: Path) -> None:
    """Check daemon status."""
    from rich.table import Table

    from mu.daemon.config import DaemonConfig
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.logging import console, print_info

    pid_file = get_daemon_pid_path(path)
    config = DaemonConfig(pid_file=pid_file)
    lifecycle = DaemonLifecycle(pid_file=pid_file, config=config)

    status_data = lifecycle.status()

    if status_data.get("status") == "stopped":
        print_info("Daemon is not running")
        return

    # Build status table
    table = Table(title="MU Daemon Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Status", status_data.get("status", "unknown"))
    if "pid" in status_data:
        table.add_row("PID", str(status_data["pid"]))
    if "healthy" in status_data:
        table.add_row("Healthy", "Yes" if status_data["healthy"] else "No")
    if "mubase_path" in status_data:
        table.add_row("Database", status_data["mubase_path"])
    if "uptime_seconds" in status_data:
        uptime = status_data["uptime_seconds"]
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        if hours > 0:
            table.add_row("Uptime", f"{hours}h {minutes}m {seconds}s")
        elif minutes > 0:
            table.add_row("Uptime", f"{minutes}m {seconds}s")
        else:
            table.add_row("Uptime", f"{seconds}s")
    if "connections" in status_data:
        table.add_row("WebSocket Connections", str(status_data["connections"]))
    # Check for stats in nested format or at top level (daemon uses node_count/edge_count)
    if "stats" in status_data:
        stats = status_data["stats"]
        if "nodes" in stats:
            table.add_row("Nodes", str(stats["nodes"]))
        if "edges" in stats:
            table.add_row("Edges", str(stats["edges"]))
    elif "node_count" in status_data:
        # Daemon returns counts at top level
        table.add_row("Nodes", str(status_data["node_count"]))
        if "edge_count" in status_data:
            table.add_row("Edges", str(status_data["edge_count"]))

    console.print(table)


def _serve_mcp() -> None:
    """Start MCP server (stdio transport for Claude Code)."""
    from mu.logging import print_info
    from mu.mcp import run_server

    print_info("Starting MCP server (stdio transport)")
    run_server(transport="stdio")


def _serve_foreground(path: Path, port: int, host: str) -> None:
    """Run daemon in foreground (for debugging)."""
    from mu.daemon.config import DaemonConfig
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info, print_warning

    mubase_path = get_mubase_path(path)
    if not mubase_path.exists():
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(ExitCode.CONFIG_ERROR)

    config = DaemonConfig(
        host=host,
        port=port,
        watch_paths=[path.resolve()],
        debounce_ms=100,
        pid_file=get_daemon_pid_path(path),
    )

    lifecycle = DaemonLifecycle(pid_file=config.pid_file, config=config)

    running, pid = lifecycle.is_running()
    if running:
        print_warning(f"Daemon already running (PID {pid})")
        print_info("Stop it first with 'mu serve --stop'")
        sys.exit(ExitCode.CONFIG_ERROR)

    print_info(f"Starting MU daemon on http://{host}:{port}")
    print_info("Press Ctrl+C to stop")

    try:
        lifecycle.start_foreground(mubase_path, config)
    except KeyboardInterrupt:
        print_info("\nShutting down...")


def _serve_background(path: Path, port: int, host: str) -> None:
    """Start daemon in background."""
    from mu.daemon.config import DaemonConfig
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info, print_success, print_warning

    mubase_path = get_mubase_path(path)
    if not mubase_path.exists():
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(ExitCode.CONFIG_ERROR)

    config = DaemonConfig(
        host=host,
        port=port,
        watch_paths=[path.resolve()],
        debounce_ms=100,
        pid_file=get_daemon_pid_path(path),
    )

    lifecycle = DaemonLifecycle(pid_file=config.pid_file, config=config)

    running, pid = lifecycle.is_running()
    if running:
        print_warning(f"Daemon already running (PID {pid})")
        return

    try:
        pid = lifecycle.start_background(mubase_path, config)
        print_success(f"MU daemon started on http://{host}:{port}")
        print_info(f"PID: {pid}")
        print_info(f"PID file: {config.pid_file}")
    except RuntimeError as e:
        print_error(str(e))
        sys.exit(ExitCode.FATAL_ERROR)


__all__ = ["serve"]
