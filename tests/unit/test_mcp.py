"""Tests for the MCP server module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mu.client import DaemonError
from mu.mcp.server import (
    ContextResult,
    DepsResult,
    NodeInfo,
    QueryResult,
    create_server,
    mu_context,
    mu_deps,
    mu_node,
    mu_query,
    mu_search,
    mu_status,
)


class TestDataModels:
    """Tests for MCP data models."""

    def test_node_info_creation(self) -> None:
        """Test NodeInfo dataclass creation."""
        node = NodeInfo(
            id="func:test",
            type="function",
            name="test",
            qualified_name="module.test",
            file_path="src/test.py",
            line_start=10,
            line_end=20,
            complexity=5,
        )
        assert node.id == "func:test"
        assert node.type == "function"
        assert node.name == "test"
        assert node.complexity == 5

    def test_node_info_defaults(self) -> None:
        """Test NodeInfo with default values."""
        node = NodeInfo(id="test", type="function", name="test")
        assert node.qualified_name is None
        assert node.file_path is None
        assert node.line_start is None
        assert node.complexity == 0

    def test_query_result_creation(self) -> None:
        """Test QueryResult dataclass creation."""
        result = QueryResult(
            columns=["name", "complexity"],
            rows=[["test", 10]],
            row_count=1,
            execution_time_ms=5.0,
        )
        assert result.columns == ["name", "complexity"]
        assert result.row_count == 1
        assert result.execution_time_ms == 5.0

    def test_context_result_creation(self) -> None:
        """Test ContextResult dataclass creation."""
        result = ContextResult(
            mu_text="!module Test",
            token_count=100,
            node_count=5,
        )
        assert result.mu_text == "!module Test"
        assert result.token_count == 100
        assert result.node_count == 5

    def test_deps_result_creation(self) -> None:
        """Test DepsResult dataclass creation."""
        deps = [
            NodeInfo(id="dep1", type="module", name="dep1"),
            NodeInfo(id="dep2", type="class", name="dep2"),
        ]
        result = DepsResult(
            node_id="test",
            direction="outgoing",
            dependencies=deps,
        )
        assert result.node_id == "test"
        assert result.direction == "outgoing"
        assert len(result.dependencies) == 2


class TestMuQuery:
    """Tests for mu_query tool."""

    @patch("mu.mcp.server._get_client")
    def test_query_via_daemon(self, mock_get_client: MagicMock) -> None:
        """Test query execution via daemon client."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "columns": ["name", "complexity"],
            "rows": [["test_func", 10]],
            "row_count": 1,
            "execution_time_ms": 5.0,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        result = mu_query("SELECT * FROM functions LIMIT 1")

        assert result.columns == ["name", "complexity"]
        assert result.row_count == 1
        # Note: cwd is now passed for multi-project routing
        mock_client.query.assert_called_once()
        call_args = mock_client.query.call_args
        assert call_args[0][0] == "SELECT * FROM functions LIMIT 1"
        assert "cwd" in call_args[1]

    @patch("mu.mcp.server._find_mubase")
    @patch("mu.mcp.server._get_client")
    def test_query_fallback_to_direct(
        self, mock_get_client: MagicMock, mock_find_mubase: MagicMock
    ) -> None:
        """Test query falls back to direct MUbase when daemon not running."""
        mock_get_client.side_effect = DaemonError("Daemon not running")
        mock_find_mubase.return_value = None

        with pytest.raises(DaemonError, match="No .mubase found"):
            mu_query("SELECT * FROM functions")


class TestMuContext:
    """Tests for mu_context tool."""

    @patch("mu.mcp.server._get_client")
    def test_context_via_daemon(self, mock_get_client: MagicMock) -> None:
        """Test context extraction via daemon client."""
        mock_client = MagicMock()
        mock_client.context.return_value = {
            "mu_text": "!module Auth",
            "token_count": 500,
            "nodes": [{}, {}, {}],  # 3 nodes
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        result = mu_context("How does authentication work?", max_tokens=4000)

        assert result.mu_text == "!module Auth"
        assert result.token_count == 500
        assert result.node_count == 3
        # Note: cwd is now passed for multi-project routing
        mock_client.context.assert_called_once()
        call_args = mock_client.context.call_args
        assert call_args[0][0] == "How does authentication work?"
        assert call_args[1]["max_tokens"] == 4000
        assert "cwd" in call_args[1]

    @patch("mu.mcp.server._find_mubase")
    @patch("mu.mcp.server._get_client")
    def test_context_fallback_no_mubase(
        self, mock_get_client: MagicMock, mock_find_mubase: MagicMock
    ) -> None:
        """Test context raises error when no mubase and daemon not running."""
        mock_get_client.side_effect = DaemonError("Daemon not running")
        mock_find_mubase.return_value = None

        with pytest.raises(DaemonError, match="No .mubase found"):
            mu_context("How does auth work?")


class TestMuDeps:
    """Tests for mu_deps tool."""

    @patch("mu.mcp.server._get_client")
    def test_deps_outgoing(self, mock_get_client: MagicMock) -> None:
        """Test dependency lookup for outgoing dependencies."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "columns": ["id", "type", "name", "file_path"],
            "rows": [
                ["mod:utils", "module", "utils", "src/utils.py"],
                ["class:Helper", "class", "Helper", "src/helper.py"],
            ],
            "row_count": 2,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        result = mu_deps("AuthService", depth=2, direction="outgoing")

        assert result.node_id == "AuthService"
        assert result.direction == "outgoing"
        assert len(result.dependencies) == 2
        assert result.dependencies[0].name == "utils"

    @patch("mu.mcp.server._get_client")
    def test_deps_incoming(self, mock_get_client: MagicMock) -> None:
        """Test dependency lookup for incoming dependencies (dependents)."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "columns": ["id", "type", "name"],
            "rows": [["func:login", "function", "login"]],
            "row_count": 1,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        result = mu_deps("AuthService", direction="incoming")

        assert result.direction == "incoming"
        # Should use SHOW dependents query
        call_args = mock_client.query.call_args[0][0]
        assert "dependents" in call_args.lower()


class TestMuNode:
    """Tests for mu_node tool."""

    @patch("mu.mcp.server._get_client")
    def test_node_found(self, mock_get_client: MagicMock) -> None:
        """Test node lookup when node exists."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "columns": ["id", "type", "name", "file_path", "line_start", "complexity"],
            "rows": [["func:test", "function", "test", "src/test.py", 10, 5]],
            "row_count": 1,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        result = mu_node("func:test")

        assert result.id == "func:test"
        assert result.type == "function"
        assert result.name == "test"
        assert result.file_path == "src/test.py"

    @patch("mu.mcp.server._get_client")
    def test_node_not_found(self, mock_get_client: MagicMock) -> None:
        """Test node lookup raises error when node not found."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "columns": ["id", "type", "name"],
            "rows": [],
            "row_count": 0,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        with pytest.raises(ValueError, match="Node not found"):
            mu_node("nonexistent")


class TestMuSearch:
    """Tests for mu_search tool."""

    @patch("mu.mcp.server._get_client")
    def test_search_by_pattern(self, mock_get_client: MagicMock) -> None:
        """Test search with name pattern."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "columns": ["id", "type", "name", "file_path", "line_start", "complexity"],
            "rows": [
                ["func:test_auth", "function", "test_auth", "tests/test_auth.py", 1, 10],
                ["func:test_login", "function", "test_login", "tests/test_auth.py", 20, 5],
            ],
            "row_count": 2,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        result = mu_search("%test%", limit=10)

        assert result.row_count == 2
        assert len(result.rows) == 2

    @patch("mu.mcp.server._get_client")
    def test_search_with_type_filter(self, mock_get_client: MagicMock) -> None:
        """Test search with node type filter."""
        mock_client = MagicMock()
        mock_client.query.return_value = {
            "columns": ["id", "type", "name"],
            "rows": [["class:UserService", "class", "UserService"]],
            "row_count": 1,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        result = mu_search("%Service%", node_type="class")

        # Verify query includes type filter
        call_args = mock_client.query.call_args[0][0]
        assert "type = 'class'" in call_args


class TestMuStatus:
    """Tests for mu_status tool."""

    @patch("mu.mcp.server._get_client")
    def test_status_daemon_running(self, mock_get_client: MagicMock) -> None:
        """Test status when daemon is running."""
        mock_client = MagicMock()
        mock_client.status.return_value = {
            "mubase_path": "/path/to/.mubase",
            "stats": {"nodes": 100, "edges": 200},
            "connections": 2,
            "uptime_seconds": 3600.0,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = mock_client

        result = mu_status()

        assert result["daemon_running"] is True
        assert result["stats"]["nodes"] == 100
        assert result["connections"] == 2

    @patch("mu.mcp.server._find_mubase")
    @patch("mu.mcp.server._get_client")
    def test_status_daemon_not_running_no_mubase(
        self, mock_get_client: MagicMock, mock_find_mubase: MagicMock
    ) -> None:
        """Test status when daemon not running and no mubase."""
        mock_get_client.side_effect = DaemonError("Daemon not running")
        mock_find_mubase.return_value = None

        result = mu_status()

        assert result["daemon_running"] is False
        assert result["mubase_path"] is None
        assert "message" in result


class TestServerCreation:
    """Tests for server factory functions."""

    def test_create_server(self) -> None:
        """Test create_server returns FastMCP instance."""
        server = create_server()
        assert server is not None
        # Verify it's the same singleton
        from mu.mcp.server import mcp

        assert server is mcp
