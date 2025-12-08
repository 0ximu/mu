"""Daemon lifecycle management.

Handles starting, stopping, and checking status of the MU daemon process.
Uses the Rust mu-daemon binary exclusively.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from mu.daemon.config import DaemonConfig

logger = logging.getLogger(__name__)

# Default timeout for HTTP status checks
STATUS_TIMEOUT = 2.0

# Maximum time to wait for daemon startup
# Rust daemon needs more time for large codebases with --build
STARTUP_TIMEOUT = 30.0

# Maximum time to wait for daemon shutdown
SHUTDOWN_TIMEOUT = 5.0


def find_rust_daemon_binary() -> Path | None:
    """Find the mu-daemon Rust binary.

    Search order:
    1. mu-daemon in PATH (installed via cargo install)
    2. Development build: mu-daemon/target/release/mu-daemon
    3. Development build: mu-daemon/target/debug/mu-daemon

    Returns:
        Path to binary if found, None otherwise.
    """
    # Check PATH first (cargo install puts it in ~/.cargo/bin)
    path_binary = shutil.which("mu-daemon")
    if path_binary:
        return Path(path_binary)

    # Check development builds relative to this file
    # Structure: src/mu/daemon/lifecycle.py -> mu-daemon/target/
    project_root = Path(__file__).parent.parent.parent.parent
    release_binary = project_root / "mu-daemon" / "target" / "release" / "mu-daemon"
    if release_binary.exists():
        return release_binary

    debug_binary = project_root / "mu-daemon" / "target" / "debug" / "mu-daemon"
    if debug_binary.exists():
        return debug_binary

    return None


class DaemonLifecycle:
    """Manage daemon start/stop/status with PID file and process control.

    Attributes:
        pid_file: Path to the PID file
        config: Optional daemon configuration
    """

    def __init__(
        self,
        pid_file: Path | None = None,
        config: DaemonConfig | None = None,
    ) -> None:
        """Initialize the lifecycle manager.

        Args:
            pid_file: Path to PID file (default: .mu/daemon.pid in cwd)
            config: Optional daemon configuration
        """
        from mu.paths import get_daemon_pid_path

        self.pid_file = pid_file or get_daemon_pid_path()
        self.config = config or DaemonConfig()

    def is_running(self) -> tuple[bool, int | None]:
        """Check if daemon is running.

        Returns:
            Tuple of (is_running, pid or None)
        """
        if not self.pid_file.exists():
            return False, None

        try:
            pid = int(self.pid_file.read_text().strip())
        except (ValueError, OSError):
            # Invalid or unreadable PID file
            self._cleanup_stale_pid()
            return False, None

        # Check if process exists
        try:
            os.kill(pid, 0)  # Signal 0 just checks existence
            return True, pid
        except OSError:
            # Process doesn't exist, clean up stale PID file
            self._cleanup_stale_pid()
            return False, None

    def _cleanup_stale_pid(self) -> None:
        """Remove stale PID file."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
                logger.debug(f"Cleaned up stale PID file: {self.pid_file}")
        except OSError:
            pass

    def start_foreground(
        self,
        mubase_path: Path,
        config: DaemonConfig | None = None,
    ) -> None:
        """Run Rust daemon in foreground (for debugging).

        Args:
            mubase_path: Path to .mubase file (used to find project root)
            config: Optional daemon configuration override

        Raises:
            RuntimeError: If Rust daemon binary not found
        """
        cfg = config or self.config

        rust_binary = find_rust_daemon_binary()
        if not rust_binary:
            raise RuntimeError(
                "Rust daemon binary not found. Build it with: cd mu-daemon && cargo build --release"
            )

        # Rust daemon takes the project root, not the mubase path directly
        project_root = (
            mubase_path.parent.parent
            if mubase_path.name == "mubase"
            else mubase_path.parent
        )

        # Build command arguments
        cmd = [
            str(rust_binary),
            str(project_root),
            "--port",
            str(cfg.port),
            "--build",  # Build graph on startup
        ]

        if cfg.host != "127.0.0.1":
            cmd.extend(["--host", cfg.host])

        logger.info(f"Starting Rust daemon: {' '.join(cmd)}")

        # Write PID file
        self._write_pid()

        try:
            # Run in foreground (blocking)
            subprocess.run(cmd, check=True)
        finally:
            self._cleanup_pid()

    def start_background(
        self,
        mubase_path: Path,
        config: DaemonConfig | None = None,
    ) -> int:
        """Start Rust daemon in background.

        Args:
            mubase_path: Path to .mubase file (used to find project root)
            config: Optional daemon configuration override

        Returns:
            PID of the background process

        Raises:
            RuntimeError: If daemon fails to start or Rust binary not found
        """
        cfg = config or self.config

        # Check if already running
        running, pid = self.is_running()
        if running:
            raise RuntimeError(f"Daemon already running (PID {pid})")

        # Find Rust daemon binary
        rust_binary = find_rust_daemon_binary()
        if not rust_binary:
            raise RuntimeError(
                "Rust daemon binary not found. Build it with: cd mu-daemon && cargo build --release"
            )

        return self._start_rust_daemon(mubase_path, cfg, rust_binary)

    def _start_rust_daemon(
        self,
        mubase_path: Path,
        cfg: DaemonConfig,
        binary_path: Path,
    ) -> int:
        """Start the Rust mu-daemon binary.

        Args:
            mubase_path: Path to .mubase file (used to find project root)
            cfg: Daemon configuration
            binary_path: Path to the mu-daemon binary

        Returns:
            PID of the daemon process
        """
        # Rust daemon takes the project root, not the mubase path directly
        # It will find/create .mu/mubase itself
        project_root = mubase_path.parent.parent if mubase_path.name == "mubase" else mubase_path.parent

        # Build command arguments
        cmd = [
            str(binary_path),
            str(project_root),
            "--port", str(cfg.port),
            "--build",  # Build graph on startup
        ]

        if cfg.host != "127.0.0.1":
            cmd.extend(["--host", cfg.host])

        logger.debug(f"Starting Rust daemon: {' '.join(cmd)}")

        # Start subprocess
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent
        )

        # Write PID file ourselves since Rust daemon doesn't manage it
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self.pid_file.write_text(str(process.pid))

        # Wait for daemon to start
        start_time = time.time()
        while time.time() - start_time < STARTUP_TIMEOUT:
            time.sleep(0.2)

            # Check if process is still running
            if process.poll() is not None:
                self._cleanup_stale_pid()
                raise RuntimeError("Rust daemon process exited unexpectedly")

            # Try to connect to status endpoint
            try:
                response = httpx.get(
                    f"http://{cfg.host}:{cfg.port}/status",
                    timeout=STATUS_TIMEOUT,
                )
                if response.status_code == 200:
                    logger.info(f"Rust daemon started successfully (PID {process.pid})")
                    return process.pid
            except httpx.RequestError:
                # Server not ready yet
                pass

        raise RuntimeError(f"Rust daemon failed to start within {STARTUP_TIMEOUT}s")

    def stop(self) -> bool:
        """Stop running daemon.

        Returns:
            True if daemon was stopped, False if not running
        """
        running, pid = self.is_running()
        if not running or pid is None:
            return False

        logger.info(f"Stopping daemon (PID {pid})")

        # Send SIGTERM for graceful shutdown
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            logger.error(f"Failed to send SIGTERM: {e}")
            return False

        # Wait for process to exit
        start_time = time.time()
        while time.time() - start_time < SHUTDOWN_TIMEOUT:
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                # Process has exited
                self._cleanup_stale_pid()
                logger.info("Daemon stopped")
                return True

        # Process didn't exit, try SIGKILL
        logger.warning("Daemon didn't respond to SIGTERM, sending SIGKILL")
        try:
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except OSError:
            pass

        self._cleanup_stale_pid()
        return True

    def status(self) -> dict[str, Any]:
        """Get daemon status.

        Checks both PID file and HTTP availability to detect running daemon,
        even if started outside of lifecycle management.

        Returns:
            Status dictionary with daemon info
        """
        running, pid = self.is_running()

        # Always check HTTP availability - daemon might be running without PID file
        http_available = False
        http_data: dict[str, Any] = {}
        try:
            response = httpx.get(
                f"http://{self.config.host}:{self.config.port}/status",
                timeout=STATUS_TIMEOUT,
            )
            if response.status_code == 200:
                http_available = True
                http_data = response.json()
        except httpx.RequestError:
            pass

        if running and http_available:
            # Best case: PID file exists and HTTP responds
            http_data["pid"] = pid
            http_data["healthy"] = True
            return http_data

        if running and not http_available:
            # PID file exists but HTTP not responding
            return {
                "status": "running",
                "pid": pid,
                "healthy": False,
                "message": "Daemon process exists but not responding to HTTP",
            }

        if not running and http_available:
            # No PID file but something is serving on the port
            http_data["status"] = "running"
            http_data["healthy"] = True
            http_data["message"] = "Daemon running (no PID file - may have been started externally)"
            return http_data

        # Neither PID file nor HTTP available
        return {"status": "stopped"}

    def _write_pid(self) -> None:
        """Write current PID to file with secure permissions."""
        pid = os.getpid()
        self.pid_file.write_text(str(pid))
        # Set permissions to owner-only read/write (0600)
        try:
            os.chmod(self.pid_file, 0o600)
        except OSError:
            pass
        logger.debug(f"Wrote PID {pid} to {self.pid_file}")

    def _cleanup_pid(self) -> None:
        """Remove PID file."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
                logger.debug(f"Removed PID file: {self.pid_file}")
        except OSError as e:
            logger.warning(f"Failed to remove PID file: {e}")


__all__ = [
    "DaemonLifecycle",
    "find_rust_daemon_binary",
]
