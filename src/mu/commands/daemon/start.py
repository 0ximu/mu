"""MU daemon start command - Start MU daemon in background."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import get_daemon_pid_path, get_mubase_path


@click.command("start")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--port", "-p", type=int, default=9120, help="Server port")
@click.option("--host", type=str, default="127.0.0.1", help="Server host")
@click.option(
    "--watch",
    "-w",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="Additional paths to watch",
)
@click.option(
    "--debounce",
    type=int,
    default=100,
    help="Debounce delay in milliseconds",
)
def daemon_start(
    path: Path,
    port: int,
    host: str,
    watch: tuple[Path, ...],
    debounce: int,
) -> None:
    """Start MU daemon in background.

    The daemon watches for file changes and provides an HTTP/WebSocket
    API for querying the code graph.

    \b
    Examples:
        mu daemon start .
        mu daemon start . --port 9000
        mu daemon start . --watch ./lib --watch ./tests
    """
    from mu.daemon.config import DaemonConfig
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info, print_success, print_warning

    mubase_path = get_mubase_path(path)
    if not mubase_path.exists():
        print_error("No .mu/mubase found. Run 'mu kernel build' first.")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Build watch paths
    watch_paths = list(watch) if watch else [path.resolve()]

    config = DaemonConfig(
        host=host,
        port=port,
        watch_paths=watch_paths,
        debounce_ms=debounce,
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


__all__ = ["daemon_start"]
