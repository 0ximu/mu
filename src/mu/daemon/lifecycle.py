"""Daemon lifecycle management.

Handles starting, stopping, and checking status of the MU daemon process.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from mu.daemon.config import DaemonConfig

logger = logging.getLogger(__name__)

# Default timeout for HTTP status checks
STATUS_TIMEOUT = 2.0

# Maximum time to wait for daemon startup
STARTUP_TIMEOUT = 10.0

# Maximum time to wait for daemon shutdown
SHUTDOWN_TIMEOUT = 5.0


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
            pid_file: Path to PID file (default: .mu.pid in cwd)
            config: Optional daemon configuration
        """
        self.pid_file = pid_file or Path.cwd() / ".mu.pid"
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
        """Run daemon in foreground (for debugging).

        Args:
            mubase_path: Path to .mubase file
            config: Optional daemon configuration override
        """
        import uvicorn

        from mu.daemon.server import create_app

        cfg = config or self.config

        # Write PID file
        self._write_pid()

        try:
            app = create_app(mubase_path, cfg)
            uvicorn.run(
                app,
                host=cfg.host,
                port=cfg.port,
                log_level="info",
            )
        finally:
            self._cleanup_pid()

    def start_background(
        self,
        mubase_path: Path,
        config: DaemonConfig | None = None,
    ) -> int:
        """Start daemon in background.

        Uses subprocess to spawn a new Python process running the daemon.

        Args:
            mubase_path: Path to .mubase file
            config: Optional daemon configuration override

        Returns:
            PID of the background process

        Raises:
            RuntimeError: If daemon fails to start
        """
        cfg = config or self.config

        # Check if already running
        running, pid = self.is_running()
        if running:
            raise RuntimeError(f"Daemon already running (PID {pid})")

        # Build command to run daemon
        # We use a subprocess that imports and runs the daemon
        python_path = sys.executable
        mubase_path_str = str(mubase_path.resolve())

        daemon_script = f"""
import sys
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

# Add parent to path if needed
sys.path.insert(0, "{Path(__file__).parent.parent.parent.parent}")

from pathlib import Path
from mu.daemon.config import DaemonConfig
from mu.daemon.server import create_app
import uvicorn

mubase_path = Path("{mubase_path_str}")
config = DaemonConfig(
    host="{cfg.host}",
    port={cfg.port},
    debounce_ms={cfg.debounce_ms},
    max_connections={cfg.max_connections},
)

# Write PID
pid_file = Path("{str(self.pid_file.resolve())}")
pid_file.write_text(str(os.getpid()))

try:
    app = create_app(mubase_path, config)
    uvicorn.run(app, host=config.host, port=config.port, log_level="warning")
finally:
    try:
        pid_file.unlink()
    except:
        pass
"""

        # Start subprocess
        process = subprocess.Popen(
            [python_path, "-c", daemon_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent
        )

        # Wait for daemon to start
        start_time = time.time()
        while time.time() - start_time < STARTUP_TIMEOUT:
            time.sleep(0.2)

            # Check if PID file was created
            if self.pid_file.exists():
                try:
                    pid = int(self.pid_file.read_text().strip())
                    # Verify process is running
                    os.kill(pid, 0)

                    # Try to connect to status endpoint
                    try:
                        response = httpx.get(
                            f"http://{cfg.host}:{cfg.port}/status",
                            timeout=STATUS_TIMEOUT,
                        )
                        if response.status_code == 200:
                            logger.info(f"Daemon started successfully (PID {pid})")
                            return pid
                    except httpx.RequestError:
                        # Server not ready yet
                        pass
                except (ValueError, OSError):
                    pass

            # Check if process died
            if process.poll() is not None:
                raise RuntimeError("Daemon process exited unexpectedly")

        raise RuntimeError(f"Daemon failed to start within {STARTUP_TIMEOUT}s")

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
]
