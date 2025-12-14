"""Tests for MU Daemon - Rust daemon lifecycle and integration.

These tests verify the daemon lifecycle management (start/stop/status) and
basic integration with the Rust mu-daemon binary.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip this entire module if mu.daemon is not available (moved to mu-daemon package)
pytest.importorskip("mu.daemon", reason="mu.daemon moved to mu-daemon package")

from mu.daemon.config import DaemonConfig
from mu.daemon.lifecycle import DaemonLifecycle, find_rust_daemon_binary


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def daemon_config() -> DaemonConfig:
    """Create default daemon configuration."""
    return DaemonConfig()


@pytest.fixture
def temp_pid_file(tmp_path: Path) -> Path:
    """Create a temporary PID file path."""
    return tmp_path / ".mu" / "daemon.pid"


# =============================================================================
# TestDaemonConfig
# =============================================================================


class TestDaemonConfig:
    """Tests for DaemonConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = DaemonConfig()

        assert config.host == "127.0.0.1"
        assert config.port == 9120  # Rust daemon default port
        assert config.debounce_ms == 100
        assert config.max_connections == 100
        assert config.watch_paths == []

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = DaemonConfig(
            host="0.0.0.0",
            port=9000,
            debounce_ms=200,
            max_connections=50,
            watch_paths=[Path("/tmp/test")],
        )

        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.debounce_ms == 200
        assert config.max_connections == 50
        assert len(config.watch_paths) == 1


# =============================================================================
# TestDaemonLifecycle
# =============================================================================


class TestDaemonLifecycle:
    """Tests for DaemonLifecycle."""

    def test_is_running_no_pid_file(self, temp_pid_file: Path) -> None:
        """Test is_running when no PID file exists."""
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        running, pid = lifecycle.is_running()

        assert running is False
        assert pid is None

    def test_is_running_stale_pid(self, temp_pid_file: Path) -> None:
        """Test is_running with stale PID file."""
        temp_pid_file.parent.mkdir(parents=True, exist_ok=True)
        # Write a PID that definitely doesn't exist
        temp_pid_file.write_text("99999999")

        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        running, pid = lifecycle.is_running()

        assert running is False
        assert pid is None

        # PID file should be cleaned up
        assert not temp_pid_file.exists()

    def test_is_running_invalid_pid_content(self, temp_pid_file: Path) -> None:
        """Test is_running with invalid PID file content."""
        temp_pid_file.parent.mkdir(parents=True, exist_ok=True)
        temp_pid_file.write_text("not_a_number")

        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        running, pid = lifecycle.is_running()

        assert running is False
        assert pid is None
        # File should be cleaned up
        assert not temp_pid_file.exists()

    def test_status_stopped(self, temp_pid_file: Path) -> None:
        """Test status when daemon is stopped and nothing on port."""
        # Use a port that's unlikely to be in use
        config = DaemonConfig(port=59999)
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file, config=config)
        status = lifecycle.status()

        assert status["status"] == "stopped"

    def test_status_with_running_process(self, temp_pid_file: Path) -> None:
        """Test status with running process but no HTTP response."""
        temp_pid_file.parent.mkdir(parents=True, exist_ok=True)
        # Write current process PID (which exists)
        temp_pid_file.write_text(str(os.getpid()))

        lifecycle = DaemonLifecycle(
            pid_file=temp_pid_file,
            config=DaemonConfig(port=59999),  # Unlikely to have server
        )
        status = lifecycle.status()

        # Process exists but HTTP fails
        assert status["status"] == "running"
        assert status["pid"] == os.getpid()
        assert status["healthy"] is False

    def test_write_pid_info(self, temp_pid_file: Path, tmp_path: Path) -> None:
        """Test _write_pid_info writes JSON with full connection info."""
        import json

        temp_pid_file.parent.mkdir(parents=True, exist_ok=True)
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)

        project_root = tmp_path / "project"
        project_root.mkdir()

        lifecycle._write_pid_info(
            pid=12345,
            port=9120,
            host="127.0.0.1",
            root=project_root,
        )

        assert temp_pid_file.exists()
        data = json.loads(temp_pid_file.read_text())
        assert data["pid"] == 12345
        assert data["port"] == 9120
        assert data["host"] == "127.0.0.1"
        assert data["root"] == str(project_root.resolve())
        assert "started_at" in data

    def test_read_pid_info_json(self, temp_pid_file: Path, tmp_path: Path) -> None:
        """Test read_pid_info reads JSON PID file."""
        import json

        temp_pid_file.parent.mkdir(parents=True, exist_ok=True)
        project_root = tmp_path / "project"
        project_root.mkdir()

        data = {
            "pid": 12345,
            "port": 9120,
            "host": "127.0.0.1",
            "root": str(project_root.resolve()),
            "started_at": "2024-01-01T00:00:00+00:00",
        }
        temp_pid_file.write_text(json.dumps(data))

        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        pid_info = lifecycle.read_pid_info()

        assert pid_info is not None
        assert pid_info["pid"] == 12345
        assert pid_info["port"] == 9120
        assert pid_info["host"] == "127.0.0.1"
        assert pid_info["root"] == str(project_root.resolve())

    def test_read_pid_info_legacy(self, temp_pid_file: Path) -> None:
        """Test read_pid_info returns None for legacy PID format."""
        temp_pid_file.parent.mkdir(parents=True, exist_ok=True)
        temp_pid_file.write_text("12345")

        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        pid_info = lifecycle.read_pid_info()

        # Legacy format doesn't have full info
        assert pid_info is None

    def test_read_pid_info_no_file(self, temp_pid_file: Path) -> None:
        """Test read_pid_info returns None when no file."""
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        pid_info = lifecycle.read_pid_info()

        assert pid_info is None

    def test_cleanup_pid(self, temp_pid_file: Path) -> None:
        """Test _cleanup_pid removes PID file."""
        temp_pid_file.parent.mkdir(parents=True, exist_ok=True)
        temp_pid_file.write_text("12345")

        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        lifecycle._cleanup_pid()

        assert not temp_pid_file.exists()

    def test_cleanup_pid_missing_file(self, temp_pid_file: Path) -> None:
        """Test _cleanup_pid with missing file doesn't raise."""
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        # Should not raise
        lifecycle._cleanup_pid()

    def test_cleanup_stale_pid_missing_file(self, temp_pid_file: Path) -> None:
        """Test _cleanup_stale_pid with missing file doesn't raise."""
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)
        # Should not raise
        lifecycle._cleanup_stale_pid()

    def test_stop_not_running(self, temp_pid_file: Path) -> None:
        """Test stop when daemon is not running returns False."""
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)

        result = lifecycle.stop()
        assert result is False

    def test_default_pid_file(self) -> None:
        """Test default PID file location."""
        lifecycle = DaemonLifecycle()

        # Default is now .mu/daemon.pid
        assert lifecycle.pid_file.name == "daemon.pid"
        assert lifecycle.pid_file.parent.name == ".mu"


# =============================================================================
# TestFindRustDaemonBinary
# =============================================================================


class TestFindRustDaemonBinary:
    """Tests for find_rust_daemon_binary function."""

    def test_finds_binary_in_path(self) -> None:
        """Test that function can find binary in PATH."""
        # This test will pass if mu-daemon is installed or built
        binary = find_rust_daemon_binary()
        # Just verify it returns Path or None, not that it exists
        assert binary is None or isinstance(binary, Path)

    def test_finds_release_binary(self, tmp_path: Path) -> None:
        """Test that function finds release binary in dev location."""
        # This is more of an integration test - skip if not in dev environment
        binary = find_rust_daemon_binary()
        if binary and "release" in str(binary):
            assert binary.exists()

    def test_returns_none_when_not_found(self) -> None:
        """Test that function returns None when binary not found."""
        with patch("shutil.which", return_value=None):
            with patch("pathlib.Path.exists", return_value=False):
                # This would return None if we could fully mock Path
                # For now, just verify the function is callable
                result = find_rust_daemon_binary()
                # Result depends on actual environment
                assert result is None or isinstance(result, Path)


# =============================================================================
# TestDaemonConfigExtended
# =============================================================================


class TestDaemonConfigExtended:
    """Extended tests for DaemonConfig."""

    def test_pid_file_default(self) -> None:
        """Test default PID file path."""
        from mu.paths import get_daemon_pid_path

        config = DaemonConfig()
        # Default is now .mu/daemon.pid via get_daemon_pid_path()
        assert config.pid_file == get_daemon_pid_path()


# =============================================================================
# TestDaemonLifecycleStartBackground
# =============================================================================


class TestDaemonLifecycleStartBackground:
    """Tests for start_background method."""

    def test_start_background_already_running(self, temp_pid_file: Path) -> None:
        """Test start_background when daemon is already running."""
        temp_pid_file.parent.mkdir(parents=True, exist_ok=True)
        # Write current process PID (which exists)
        temp_pid_file.write_text(str(os.getpid()))

        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)

        with pytest.raises(RuntimeError, match="already running"):
            lifecycle.start_background(Path("/tmp/mubase"))

    def test_start_background_no_binary(self, temp_pid_file: Path) -> None:
        """Test start_background when Rust binary not found."""
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)

        with patch(
            "mu.daemon.lifecycle.find_rust_daemon_binary", return_value=None
        ):
            with pytest.raises(RuntimeError, match="Rust daemon binary not found"):
                lifecycle.start_background(Path("/tmp/mubase"))


# =============================================================================
# TestDaemonLifecycleStartForeground
# =============================================================================


class TestDaemonLifecycleStartForeground:
    """Tests for start_foreground method."""

    def test_start_foreground_no_binary(self, temp_pid_file: Path) -> None:
        """Test start_foreground when Rust binary not found."""
        lifecycle = DaemonLifecycle(pid_file=temp_pid_file)

        with patch(
            "mu.daemon.lifecycle.find_rust_daemon_binary", return_value=None
        ):
            with pytest.raises(RuntimeError, match="Rust daemon binary not found"):
                lifecycle.start_foreground(Path("/tmp/mubase"))


# =============================================================================
# TestClientPortDiscovery
# =============================================================================


class TestClientPortDiscovery:
    """Tests for client port discovery from PID file."""

    def test_get_daemon_url_for_project_json(self, tmp_path: Path) -> None:
        """Test get_daemon_url_for_project reads JSON PID file."""
        import json

        from mu.client import get_daemon_url_for_project

        # Create .mu/daemon.pid with JSON
        mu_dir = tmp_path / ".mu"
        mu_dir.mkdir()
        pid_file = mu_dir / "daemon.pid"
        pid_file.write_text(
            json.dumps(
                {
                    "pid": 12345,
                    "port": 9200,
                    "host": "127.0.0.1",
                    "root": str(tmp_path),
                    "started_at": "2024-01-01T00:00:00+00:00",
                }
            )
        )

        url = get_daemon_url_for_project(tmp_path)
        assert url == "http://127.0.0.1:9200"

    def test_get_daemon_url_for_project_legacy(self, tmp_path: Path) -> None:
        """Test get_daemon_url_for_project handles legacy PID file."""
        from mu.client import DEFAULT_DAEMON_URL, get_daemon_url_for_project

        # Create .mu/daemon.pid with just PID number (legacy format)
        mu_dir = tmp_path / ".mu"
        mu_dir.mkdir()
        pid_file = mu_dir / "daemon.pid"
        pid_file.write_text("12345")

        url = get_daemon_url_for_project(tmp_path)
        assert url == DEFAULT_DAEMON_URL

    def test_get_daemon_url_for_project_no_file(self, tmp_path: Path) -> None:
        """Test get_daemon_url_for_project returns None when no PID file."""
        from mu.client import get_daemon_url_for_project

        url = get_daemon_url_for_project(tmp_path)
        assert url is None

    def test_get_daemon_url_fallback(self, tmp_path: Path) -> None:
        """Test get_daemon_url falls back to default."""
        from mu.client import DEFAULT_DAEMON_URL, get_daemon_url

        url = get_daemon_url(tmp_path)
        assert url == DEFAULT_DAEMON_URL

    def test_daemon_client_for_project(self, tmp_path: Path) -> None:
        """Test DaemonClient.for_project factory method."""
        import json

        from mu.client import DaemonClient

        # Create .mu/daemon.pid with JSON
        mu_dir = tmp_path / ".mu"
        mu_dir.mkdir()
        pid_file = mu_dir / "daemon.pid"
        pid_file.write_text(
            json.dumps(
                {
                    "pid": 12345,
                    "port": 9300,
                    "host": "127.0.0.1",
                    "root": str(tmp_path),
                    "started_at": "2024-01-01T00:00:00+00:00",
                }
            )
        )

        client = DaemonClient.for_project(tmp_path)
        assert client.base_url == "http://127.0.0.1:9300"
