"""MU daemon stop command - Stop running MU daemon."""

from __future__ import annotations

from pathlib import Path

import click


@click.command("stop")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
def daemon_stop(path: Path) -> None:
    """Stop running MU daemon.

    \b
    Example:
        mu daemon stop
    """
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.logging import print_info, print_success

    pid_file = path.resolve() / ".mu.pid"
    lifecycle = DaemonLifecycle(pid_file=pid_file)

    if lifecycle.stop():
        print_success("MU daemon stopped")
    else:
        print_info("Daemon not running")


__all__ = ["daemon_stop"]
