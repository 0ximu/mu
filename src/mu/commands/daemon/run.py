"""MU daemon run command - Run daemon in foreground."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command("run")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--port", "-p", type=int, default=8765, help="Server port")
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
def daemon_run(
    path: Path,
    port: int,
    host: str,
    watch: tuple[Path, ...],
    debounce: int,
) -> None:
    """Run daemon in foreground (for debugging).

    Press Ctrl+C to stop.

    \b
    Examples:
        mu daemon run .
        mu daemon run . --port 9000
    """
    from mu.daemon.config import DaemonConfig
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info, print_warning

    mubase_path = path.resolve() / ".mubase"
    if not mubase_path.exists():
        print_error("No .mubase found. Run 'mu kernel build' first.")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Build watch paths
    watch_paths = list(watch) if watch else [path.resolve()]

    config = DaemonConfig(
        host=host,
        port=port,
        watch_paths=watch_paths,
        debounce_ms=debounce,
        pid_file=path.resolve() / ".mu.pid",
    )

    lifecycle = DaemonLifecycle(pid_file=config.pid_file, config=config)

    running, pid = lifecycle.is_running()
    if running:
        print_warning(f"Daemon already running (PID {pid})")
        print_info("Stop it first with 'mu daemon stop'")
        sys.exit(ExitCode.CONFIG_ERROR)

    print_info(f"Starting MU daemon on http://{host}:{port}")
    print_info("Press Ctrl+C to stop")

    try:
        lifecycle.start_foreground(mubase_path, config)
    except KeyboardInterrupt:
        print_info("\nShutting down...")


__all__ = ["daemon_run"]
