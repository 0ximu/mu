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
    ReviewDiffOutput,
    SemanticDiffOutput,
    create_server,
    mu_context,
    mu_deps,
    mu_query,
    mu_review_diff,
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

    @patch("mu.mcp.tools.graph.get_client")
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

    @patch("mu.mcp.tools.graph.find_mubase")
    @patch("mu.mcp.tools.graph.get_client")
    def test_query_fallback_to_direct(
        self, mock_get_client: MagicMock, mock_find_mubase: MagicMock
    ) -> None:
        """Test query falls back to direct MUbase when daemon not running."""
        mock_get_client.side_effect = DaemonError("Daemon not running")
        mock_find_mubase.return_value = None

        with pytest.raises(DaemonError, match=r"No \.mu/mubase found"):
            mu_query("SELECT * FROM functions")


class TestMuContext:
    """Tests for mu_context tool."""

    @patch("mu.mcp.tools.context.get_client")
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

    @patch("mu.mcp.tools.context.find_mubase")
    @patch("mu.mcp.tools.context.get_client")
    def test_context_fallback_no_mubase(
        self, mock_get_client: MagicMock, mock_find_mubase: MagicMock
    ) -> None:
        """Test context raises error when no mubase and daemon not running."""
        mock_get_client.side_effect = DaemonError("Daemon not running")
        mock_find_mubase.return_value = None

        with pytest.raises(DaemonError, match=r"No \.mu/mubase found"):
            mu_context("How does auth work?")


class TestMuDeps:
    """Tests for mu_deps tool."""

    @patch("mu.mcp.tools.analysis.get_client")
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

    @patch("mu.mcp.tools.analysis.get_client")
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


class TestMuStatus:
    """Tests for mu_status tool."""

    @patch("mu.mcp.tools.setup.get_client")
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

    @patch("mu.mcp.tools.setup.find_mubase")
    @patch("mu.mcp.tools.setup.get_client")
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


class TestReviewDiffOutput:
    """Tests for ReviewDiffOutput dataclass."""

    def test_review_diff_output_creation(self) -> None:
        """Test ReviewDiffOutput dataclass creation with all fields."""
        output = ReviewDiffOutput(
            base_ref="main",
            head_ref="HEAD",
            changes=[{"entity_name": "test", "change_type": "added"}],
            breaking_changes=[],
            has_breaking_changes=False,
            total_changes=1,
            violations=[],
            patterns_checked=["snake_case_functions"],
            files_checked=["src/test.py"],
            error_count=0,
            warning_count=0,
            info_count=0,
            patterns_valid=True,
            review_summary="# Code Review: main -> HEAD\n\nLooks good!",
            review_time_ms=100.0,
        )
        assert output.base_ref == "main"
        assert output.head_ref == "HEAD"
        assert output.total_changes == 1
        assert output.patterns_valid is True
        assert output.has_breaking_changes is False

    def test_review_diff_output_empty_violations(self) -> None:
        """Test ReviewDiffOutput with empty violations (pattern validation removed)."""
        output = ReviewDiffOutput(
            base_ref="develop",
            head_ref="feature-branch",
            changes=[],
            breaking_changes=[],
            has_breaking_changes=False,
            total_changes=0,
            violations=[],
            patterns_checked=[],
            files_checked=[],
            error_count=0,
            warning_count=0,
            info_count=0,
            patterns_valid=True,
            review_summary="Review summary",
            review_time_ms=50.0,
        )
        assert len(output.violations) == 0
        assert output.warning_count == 0
        assert output.patterns_valid is True


class TestMuReviewDiff:
    """Tests for mu_review_diff tool."""

    @patch("mu.mcp.tools.analysis.mu_semantic_diff")
    def test_review_diff_basic(self, mock_semantic_diff: MagicMock) -> None:
        """Test basic review diff without pattern validation."""
        # Mock semantic diff result
        mock_semantic_diff.return_value = SemanticDiffOutput(
            base_ref="main",
            head_ref="HEAD",
            changes=[
                {"entity_name": "new_func", "change_type": "added", "is_breaking": False}
            ],
            breaking_changes=[],
            summary_text="1 change",
            has_breaking_changes=False,
            total_changes=1,
        )

        result = mu_review_diff("main", "HEAD", validate_patterns=False)

        assert result.base_ref == "main"
        assert result.head_ref == "HEAD"
        assert result.total_changes == 1
        assert result.has_breaking_changes is False
        # No validation run
        assert result.patterns_valid is True
        assert len(result.violations) == 0
        assert "Looks good" in result.review_summary

    @patch("mu.mcp.tools.analysis.mu_semantic_diff")
    def test_review_diff_with_breaking_changes(
        self, mock_semantic_diff: MagicMock
    ) -> None:
        """Test review diff detects breaking changes."""
        mock_semantic_diff.return_value = SemanticDiffOutput(
            base_ref="main",
            head_ref="HEAD",
            changes=[
                {
                    "entity_name": "removed_func",
                    "change_type": "removed",
                    "is_breaking": True,
                }
            ],
            breaking_changes=[
                {
                    "entity_name": "removed_func",
                    "change_type": "removed",
                    "is_breaking": True,
                }
            ],
            summary_text="1 breaking change",
            has_breaking_changes=True,
            total_changes=1,
        )

        result = mu_review_diff("main", "HEAD", validate_patterns=False)

        assert result.has_breaking_changes is True
        assert len(result.breaking_changes) == 1
        assert "Breaking Changes" in result.review_summary
        assert "Review breaking changes" in result.review_summary

    @patch("subprocess.run")
    @patch("mu.mcp.tools.analysis.find_mubase")
    @patch("mu.mcp.tools.analysis.mu_semantic_diff")
    def test_review_diff_with_pattern_validation(
        self,
        mock_semantic_diff: MagicMock,
        mock_find_mubase: MagicMock,
        mock_subprocess: MagicMock,
    ) -> None:
        """Test review diff with pattern validation enabled."""
        # Mock semantic diff
        mock_semantic_diff.return_value = SemanticDiffOutput(
            base_ref="main",
            head_ref="HEAD",
            changes=[],
            breaking_changes=[],
            summary_text="No changes",
            has_breaking_changes=False,
            total_changes=0,
        )

        # Mock no mubase found (skip validation)
        mock_find_mubase.return_value = None

        result = mu_review_diff("main", "HEAD", validate_patterns=True)

        # Should still succeed but with no files validated
        assert result.patterns_valid is True
        assert len(result.files_checked) == 0

    @patch("mu.mcp.tools.analysis.mu_semantic_diff")
    def test_review_diff_summary_generation(
        self, mock_semantic_diff: MagicMock
    ) -> None:
        """Test review summary is properly generated."""
        mock_semantic_diff.return_value = SemanticDiffOutput(
            base_ref="develop",
            head_ref="feature-x",
            changes=[
                {"entity_name": "add1", "change_type": "added"},
                {"entity_name": "add2", "change_type": "added"},
                {"entity_name": "mod1", "change_type": "modified"},
            ],
            breaking_changes=[],
            summary_text="3 changes",
            has_breaking_changes=False,
            total_changes=3,
        )

        result = mu_review_diff("develop", "feature-x", validate_patterns=False)

        # Check summary contains expected sections
        assert "Code Review: develop -> feature-x" in result.review_summary
        assert "Semantic Changes" in result.review_summary
        assert "Total changes: 3" in result.review_summary
        assert "Added: 2" in result.review_summary
        assert "Recommendation" in result.review_summary

    @patch("mu.mcp.tools.analysis.mu_semantic_diff")
    def test_review_diff_with_category_ignored(
        self, mock_semantic_diff: MagicMock
    ) -> None:
        """Test review diff ignores pattern_category (validation removed)."""
        mock_semantic_diff.return_value = SemanticDiffOutput(
            base_ref="main",
            head_ref="HEAD",
            changes=[],
            breaking_changes=[],
            summary_text="",
            has_breaking_changes=False,
            total_changes=0,
        )

        # Category is now ignored (no validation)
        result = mu_review_diff("main", "HEAD", pattern_category="any_category")
        assert result.base_ref == "main"
        assert result.patterns_valid is True
