"""MU Daemon Commands - DEPRECATED, use 'mu serve' instead."""

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


@click.group(cls=LazyGroup, lazy_subcommands=LAZY_DAEMON_COMMANDS, hidden=True)
def daemon() -> None:
    """[DEPRECATED] Use 'mu serve' instead.

    \b
    Migration:
        mu daemon start  ->  mu serve
        mu daemon stop   ->  mu serve --stop
        mu daemon status ->  mu serve --status
        mu daemon run    ->  mu serve -f
    """
    pass


__all__ = ["daemon"]
