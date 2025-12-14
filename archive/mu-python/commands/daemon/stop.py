"""MU daemon stop command - Stop running MU daemon.

DEPRECATED: Use 'mu serve --stop' instead.
"""

from __future__ import annotations

from pathlib import Path

import click

from mu.paths import get_daemon_pid_path


def _show_deprecation_warning() -> None:
    """Show deprecation warning for daemon commands."""
    click.secho(
        "⚠️  'mu daemon stop' is deprecated. Use 'mu serve --stop' instead.",
        fg="yellow",
        err=True,
    )


@click.command("stop")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
def daemon_stop(path: Path) -> None:
    """[DEPRECATED] Stop running MU daemon.

    Use 'mu serve --stop' instead.
    """
    _show_deprecation_warning()
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.logging import print_info, print_success

    pid_file = get_daemon_pid_path(path)
    lifecycle = DaemonLifecycle(pid_file=pid_file)

    if lifecycle.stop():
        print_success("MU daemon stopped")
    else:
        print_info("Daemon not running")


__all__ = ["daemon_stop"]
