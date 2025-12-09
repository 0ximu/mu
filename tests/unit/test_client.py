"""Tests for the daemon client module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from mu.client import (
    DEFAULT_DAEMON_URL,
    DaemonClient,
    DaemonError,
    forward_query,
    is_daemon_running,
)


class TestDaemonClient:
    """Tests for DaemonClient class."""

    def test_init_default_values(self) -> None:
        """Test client initializes with defaults."""
        client = DaemonClient()
        assert client.base_url == DEFAULT_DAEMON_URL
        assert client.timeout == 2.0  # Increased from 0.5 for reliability
        client.close()

    def test_init_custom_values(self) -> None:
        """Test client with custom configuration."""
        client = DaemonClient(base_url="http://custom:9000", timeout=1.0)
        assert client.base_url == "http://custom:9000"
        assert client.timeout == 1.0
        client.close()

    def test_context_manager(self) -> None:
        """Test client works as context manager."""
        with DaemonClient() as client:
            assert client.base_url == DEFAULT_DAEMON_URL

    @patch.object(httpx.Client, "get")
    def test_is_running_true(self, mock_get: MagicMock) -> None:
        """Test is_running returns True when daemon responds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        with DaemonClient() as client:
            assert client.is_running() is True

    @patch.object(httpx.Client, "get")
    def test_is_running_false_connect_error(self, mock_get: MagicMock) -> None:
        """Test is_running returns False on connection error."""
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        with DaemonClient() as client:
            assert client.is_running() is False

    @patch.object(httpx.Client, "get")
    def test_is_running_false_timeout(self, mock_get: MagicMock) -> None:
        """Test is_running returns False on timeout."""
        mock_get.side_effect = httpx.TimeoutException("Timeout")

        with DaemonClient() as client:
            assert client.is_running() is False

    @patch.object(httpx.Client, "post")
    def test_query_success(self, mock_post: MagicMock) -> None:
        """Test successful query execution."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "result": {
                "columns": ["name", "complexity"],
                "rows": [["test_func", 10]],
                "row_count": 1,
            },
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with DaemonClient() as client:
            result = client.query("SELECT * FROM functions LIMIT 1")
            assert result["columns"] == ["name", "complexity"]
            assert result["row_count"] == 1

    @patch.object(httpx.Client, "post")
    def test_query_failure(self, mock_post: MagicMock) -> None:
        """Test query failure returns error."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error": "Invalid query syntax",
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with DaemonClient() as client:
            with pytest.raises(DaemonError, match="Invalid query syntax"):
                client.query("INVALID QUERY")

    @patch.object(httpx.Client, "post")
    def test_query_connect_error(self, mock_post: MagicMock) -> None:
        """Test query raises DaemonError on connection failure."""
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        with DaemonClient() as client:
            with pytest.raises(DaemonError, match="Daemon not available"):
                client.query("SELECT * FROM functions")

    @patch.object(httpx.Client, "get")
    def test_status_success(self, mock_get: MagicMock) -> None:
        """Test successful status request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "running",
            "uptime_seconds": 3600.0,
            "connections": 2,
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with DaemonClient() as client:
            status = client.status()
            assert status["status"] == "running"
            assert status["uptime_seconds"] == 3600.0

    @patch.object(httpx.Client, "get")
    def test_status_connect_error(self, mock_get: MagicMock) -> None:
        """Test status raises DaemonError on connection failure."""
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        with DaemonClient() as client:
            with pytest.raises(DaemonError, match="Daemon not available"):
                client.status()

    @patch.object(httpx.Client, "post")
    def test_context_success(self, mock_post: MagicMock) -> None:
        """Test successful context extraction."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "mu_text": "!module Test",
            "token_count": 100,
            "nodes": [],
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        with DaemonClient() as client:
            result = client.context("How does auth work?")
            assert result["mu_text"] == "!module Test"
            assert result["token_count"] == 100


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    @patch("mu.client.httpx.get")
    def test_is_daemon_running_true(self, mock_get: MagicMock) -> None:
        """Test is_daemon_running returns True when daemon responds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        assert is_daemon_running() is True
        mock_get.assert_called_once()

    @patch("mu.client.httpx.get")
    def test_is_daemon_running_false(self, mock_get: MagicMock) -> None:
        """Test is_daemon_running returns False on error."""
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        assert is_daemon_running() is False

    @patch("mu.client.DaemonClient")
    def test_forward_query(self, mock_client_class: MagicMock) -> None:
        """Test forward_query convenience function."""
        mock_client = MagicMock()
        mock_client.query.return_value = {"columns": [], "rows": [], "row_count": 0}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = forward_query("SELECT * FROM functions")
        assert result["row_count"] == 0
        mock_client.query.assert_called_once_with("SELECT * FROM functions")
