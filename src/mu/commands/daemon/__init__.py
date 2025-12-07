"""MU Daemon Commands - Real-time file watching and HTTP/WebSocket API."""

from __future__ import annotations

import click

from mu.commands.lazy import LazyGroup

# Define lazy subcommands for daemon group
LAZY_DAEMON_COMMANDS: dict[str, tuple[str, str]] = {
    "start": ("mu.commands.daemon.start", "daemon_start"),
    "stop": ("mu.commands.daemon.stop", "daemon_stop"),
    "status": ("mu.commands.daemon.status", "daemon_status"),
    "run": ("mu.commands.daemon.run", "daemon_run"),
}


@click.group(cls=LazyGroup, lazy_subcommands=LAZY_DAEMON_COMMANDS)
def daemon() -> None:
    """MU daemon commands (real-time updates).

    Run a long-running daemon that watches for file changes
    and serves HTTP/WebSocket API for queries.

    \b
    Examples:
        mu daemon start .         # Start daemon in background
        mu daemon status          # Check daemon status
        mu daemon stop            # Stop running daemon
        mu daemon run .           # Run in foreground (for debugging)
    """
    pass


__all__ = ["daemon"]
