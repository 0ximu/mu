"""Tests for MU CLI command utilities."""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mu.kernel import MUbase, Node, NodeType
from mu.kernel.resolver import (
    MatchType,
    NodeCandidate,
    NodeNotFoundError,
    ResolvedNode,
    ResolutionStrategy,
)
from mu.commands.utils import (
    format_candidate_display,
    format_resolution_for_json,
    is_interactive,
    shorten_path,
)


class TestIsInteractive:
    """Tests for is_interactive() function."""

    def test_is_interactive_true_when_both_tty(self) -> None:
        """Returns True when both stdin and stdout are TTY."""
        with patch.object(sys.stdin, "isatty", return_value=True):
            with patch.object(sys.stdout, "isatty", return_value=True):
                assert is_interactive() is True

    def test_is_interactive_false_when_stdin_not_tty(self) -> None:
        """Returns False when stdin is not a TTY."""
        with patch.object(sys.stdin, "isatty", return_value=False):
            with patch.object(sys.stdout, "isatty", return_value=True):
                assert is_interactive() is False

    def test_is_interactive_false_when_stdout_not_tty(self) -> None:
        """Returns False when stdout is not a TTY."""
        with patch.object(sys.stdin, "isatty", return_value=True):
            with patch.object(sys.stdout, "isatty", return_value=False):
                assert is_interactive() is False

    def test_is_interactive_false_when_both_not_tty(self) -> None:
        """Returns False when neither stdin nor stdout are TTY."""
        with patch.object(sys.stdin, "isatty", return_value=False):
            with patch.object(sys.stdout, "isatty", return_value=False):
                assert is_interactive() is False


class TestShortenPath:
    """Tests for shorten_path() function."""

    def test_short_path_unchanged(self) -> None:
        """Short paths are returned unchanged."""
        path = "src/auth.py"
        assert shorten_path(path, max_length=50) == path

    def test_exact_length_unchanged(self) -> None:
        """Paths at exact max_length are returned unchanged."""
        path = "x" * 50
        assert shorten_path(path, max_length=50) == path

    def test_long_path_truncated(self) -> None:
        """Long paths are truncated with ellipsis."""
        path = "src/very/long/nested/directory/structure/file.py"
        result = shorten_path(path, max_length=30)

        assert len(result) <= 30
        assert "..." in result
        # Should preserve beginning and end
        assert result.startswith("src/")
        assert result.endswith(".py")

    def test_truncation_preserves_beginning_and_end(self) -> None:
        """Truncation preserves both beginning and end of path."""
        path = "beginning/middle/section/of/path/ending"
        result = shorten_path(path, max_length=25)

        # Should have ellipsis in middle
        assert "..." in result
        parts = result.split("...")
        assert len(parts) == 2
        # Beginning preserved
        assert path.startswith(parts[0])
        # Ending preserved
        assert path.endswith(parts[1])

    def test_very_short_max_length(self) -> None:
        """Very short max_length still works."""
        path = "src/services/authentication/handler.py"
        result = shorten_path(path, max_length=15)

        assert len(result) <= 15
        assert "..." in result

    def test_default_max_length(self) -> None:
        """Default max_length is 50."""
        short_path = "a" * 49
        long_path = "a" * 60

        assert shorten_path(short_path) == short_path
        assert "..." in shorten_path(long_path)


class TestFormatCandidateDisplay:
    """Tests for format_candidate_display() function."""

    @pytest.fixture
    def source_candidate(self) -> NodeCandidate:
        """Create a source file candidate."""
        node = Node(
            id="cls:src/services/auth.py:AuthService",
            type=NodeType.CLASS,
            name="AuthService",
            file_path="src/services/auth.py",
            line_start=10,
            line_end=100,
        )
        return NodeCandidate(
            node=node,
            score=90,
            is_test=False,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )

    @pytest.fixture
    def test_candidate(self) -> NodeCandidate:
        """Create a test file candidate."""
        node = Node(
            id="cls:tests/test_auth.py:TestAuthService",
            type=NodeType.CLASS,
            name="TestAuthService",
            file_path="tests/test_auth.py",
            line_start=5,
            line_end=200,
        )
        return NodeCandidate(
            node=node,
            score=70,
            is_test=True,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )

    def test_format_shows_index_and_name(self, source_candidate: NodeCandidate) -> None:
        """Format includes index and node name."""
        result = format_candidate_display(source_candidate, 1)

        assert "[1]" in result
        assert "AuthService" in result

    def test_format_shows_type(self, source_candidate: NodeCandidate) -> None:
        """Format includes node type."""
        result = format_candidate_display(source_candidate, 1)

        assert "(class)" in result

    def test_format_shows_test_marker_for_tests(self, test_candidate: NodeCandidate) -> None:
        """Format includes [TEST] marker for test files."""
        result = format_candidate_display(test_candidate, 2)

        assert "[TEST]" in result

    def test_format_no_test_marker_for_source(self, source_candidate: NodeCandidate) -> None:
        """Format does not include [TEST] for source files."""
        result = format_candidate_display(source_candidate, 1)

        assert "[TEST]" not in result

    def test_format_shows_line_numbers(self, source_candidate: NodeCandidate) -> None:
        """Format includes line range."""
        result = format_candidate_display(source_candidate, 1)

        assert "L10-100" in result

    def test_format_shows_file_path(self, source_candidate: NodeCandidate) -> None:
        """Format includes file path on second line."""
        result = format_candidate_display(source_candidate, 1)

        # Should be multi-line with path indented
        assert "src/services/auth.py" in result
        assert "\n" in result

    def test_format_function_type(self) -> None:
        """Format shows function type correctly."""
        node = Node(
            id="fn:src/utils.py:helper",
            type=NodeType.FUNCTION,
            name="helper",
            file_path="src/utils.py",
            line_start=1,
            line_end=10,
        )
        candidate = NodeCandidate(
            node=node,
            score=80,
            is_test=False,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )

        result = format_candidate_display(candidate, 1)
        assert "(function)" in result

    def test_format_module_type(self) -> None:
        """Format shows module type correctly."""
        node = Node(
            id="mod:src/utils.py",
            type=NodeType.MODULE,
            name="utils",
            file_path="src/utils.py",
        )
        candidate = NodeCandidate(
            node=node,
            score=80,
            is_test=False,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )

        result = format_candidate_display(candidate, 3)
        assert "(module)" in result
        assert "[3]" in result

    def test_format_without_line_numbers(self) -> None:
        """Format handles nodes without line numbers."""
        node = Node(
            id="mod:src/utils.py",
            type=NodeType.MODULE,
            name="utils",
            file_path="src/utils.py",
            line_start=None,
            line_end=None,
        )
        candidate = NodeCandidate(
            node=node,
            score=80,
            is_test=False,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )

        result = format_candidate_display(candidate, 1)
        # Should not contain line info
        assert "L" not in result or "L1" not in result

    def test_format_without_file_path(self) -> None:
        """Format handles nodes without file path."""
        node = Node(
            id="ext:os",
            type=NodeType.EXTERNAL,
            name="os",
            file_path=None,
        )
        candidate = NodeCandidate(
            node=node,
            score=50,
            is_test=False,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )

        result = format_candidate_display(candidate, 1)
        # Should not have second line with path
        assert result.count("\n") == 0 or "None" not in result

    def test_format_long_path_shortened(self) -> None:
        """Format shortens very long file paths."""
        # Create a path that exceeds the 60 character limit used by format_candidate_display
        long_path = "src/" + "/".join(["subdir"] * 10) + "/very_long_deeply_nested_service_file.py"
        node = Node(
            id=f"cls:{long_path}:Service",
            type=NodeType.CLASS,
            name="Service",
            file_path=long_path,
            line_start=1,
            line_end=100,
        )
        candidate = NodeCandidate(
            node=node,
            score=80,
            is_test=False,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )

        result = format_candidate_display(candidate, 1)
        # Path should be shortened (contains ...)
        assert "..." in result


class TestFormatResolutionForJson:
    """Tests for format_resolution_for_json() function."""

    @pytest.fixture
    def resolved_node(self) -> ResolvedNode:
        """Create a resolved node for testing."""
        node = Node(
            id="cls:src/auth.py:AuthService",
            type=NodeType.CLASS,
            name="AuthService",
            file_path="src/auth.py",
        )
        return ResolvedNode(
            node=node,
            alternatives=[],
            resolution_method="exact_name",
            was_ambiguous=False,
        )

    def test_format_includes_reference(self, resolved_node: ResolvedNode) -> None:
        """JSON format includes original reference."""
        result = format_resolution_for_json(resolved_node, "AuthService")

        assert result["reference"] == "AuthService"

    def test_format_includes_resolved_id(self, resolved_node: ResolvedNode) -> None:
        """JSON format includes resolved node ID."""
        result = format_resolution_for_json(resolved_node, "AuthService")

        assert result["resolved_id"] == "cls:src/auth.py:AuthService"

    def test_format_includes_resolved_name(self, resolved_node: ResolvedNode) -> None:
        """JSON format includes resolved node name."""
        result = format_resolution_for_json(resolved_node, "AuthService")

        assert result["resolved_name"] == "AuthService"

    def test_format_includes_resolution_method(self, resolved_node: ResolvedNode) -> None:
        """JSON format includes resolution method."""
        result = format_resolution_for_json(resolved_node, "AuthService")

        assert result["resolution_method"] == "exact_name"

    def test_format_includes_ambiguity_flag(self, resolved_node: ResolvedNode) -> None:
        """JSON format includes was_ambiguous flag."""
        result = format_resolution_for_json(resolved_node, "AuthService")

        assert result["was_ambiguous"] is False

    def test_format_includes_alternative_count(self, resolved_node: ResolvedNode) -> None:
        """JSON format includes alternative count."""
        result = format_resolution_for_json(resolved_node, "AuthService")

        assert result["alternative_count"] == 0

    def test_format_includes_alternatives_list(self) -> None:
        """JSON format includes serialized alternatives."""
        main_node = Node(
            id="cls:src/auth.py:AuthService",
            type=NodeType.CLASS,
            name="AuthService",
            file_path="src/auth.py",
        )
        alt_node = Node(
            id="cls:tests/test_auth.py:AuthService",
            type=NodeType.CLASS,
            name="AuthService",
            file_path="tests/test_auth.py",
        )
        alt_candidate = NodeCandidate(
            node=alt_node,
            score=70,
            is_test=True,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )

        resolved = ResolvedNode(
            node=main_node,
            alternatives=[alt_candidate],
            resolution_method="prefer_source",
            was_ambiguous=True,
        )

        result = format_resolution_for_json(resolved, "AuthService")

        assert result["alternative_count"] == 1
        assert len(result["alternatives"]) == 1
        assert result["alternatives"][0]["node_id"] == "cls:tests/test_auth.py:AuthService"
        assert result["alternatives"][0]["name"] == "AuthService"
        assert result["alternatives"][0]["is_test"] is True

    def test_format_limits_alternatives_to_10(self) -> None:
        """JSON format limits alternatives to first 10."""
        main_node = Node(
            id="cls:src/svc.py:Service",
            type=NodeType.CLASS,
            name="Service",
            file_path="src/svc.py",
        )

        # Create 15 alternatives
        alternatives = []
        for i in range(15):
            alt_node = Node(
                id=f"cls:src/svc{i}.py:Service",
                type=NodeType.CLASS,
                name="Service",
                file_path=f"src/svc{i}.py",
            )
            alternatives.append(
                NodeCandidate(
                    node=alt_node,
                    score=80 - i,
                    is_test=False,
                    is_exact_match=True,
                    match_type=MatchType.EXACT_NAME,
                )
            )

        resolved = ResolvedNode(
            node=main_node,
            alternatives=alternatives,
            resolution_method="prefer_source",
            was_ambiguous=True,
        )

        result = format_resolution_for_json(resolved, "Service")

        # Should report full count but only include first 10
        assert result["alternative_count"] == 15
        assert len(result["alternatives"]) == 10


class TestResolveNodeFunctions:
    """Tests for resolve_node_* wrapper functions."""

    @pytest.fixture
    def db_with_nodes(self, tmp_path: Path) -> MUbase:
        """Create a MUbase with test nodes."""
        db = MUbase(tmp_path / "test.mubase")

        db.add_node(
            Node(
                id="cls:src/auth.py:AuthService",
                type=NodeType.CLASS,
                name="AuthService",
                file_path="src/auth.py",
            )
        )
        db.add_node(
            Node(
                id="cls:tests/test_auth.py:AuthService",
                type=NodeType.CLASS,
                name="AuthService",
                file_path="tests/test_auth.py",
            )
        )

        return db

    def test_resolve_node_auto_prefer_source(self, db_with_nodes: MUbase) -> None:
        """resolve_node_auto with prefer_source=True prefers source files."""
        from mu.commands.utils import resolve_node_auto

        result = resolve_node_auto(db_with_nodes, "AuthService", prefer_source=True)

        assert result.node.file_path == "src/auth.py"
        assert result.was_ambiguous is True

    def test_resolve_node_auto_first_match(self, db_with_nodes: MUbase) -> None:
        """resolve_node_auto with prefer_source=False uses first match."""
        from mu.commands.utils import resolve_node_auto

        result = resolve_node_auto(db_with_nodes, "AuthService", prefer_source=False)

        assert result.node.name == "AuthService"
        # First match behavior (sorted by score, then ID)
        assert result.was_ambiguous is True

    def test_resolve_node_strict_raises_on_ambiguity(self, db_with_nodes: MUbase) -> None:
        """resolve_node_strict raises AmbiguousNodeError on multiple matches."""
        from mu.commands.utils import resolve_node_strict
        from mu.kernel.resolver import AmbiguousNodeError

        with pytest.raises(AmbiguousNodeError):
            resolve_node_strict(db_with_nodes, "AuthService")

    def test_resolve_node_strict_succeeds_unambiguous(self, db_with_nodes: MUbase) -> None:
        """resolve_node_strict succeeds when reference is unambiguous."""
        from mu.commands.utils import resolve_node_strict

        # Add a unique node
        db_with_nodes.add_node(
            Node(
                id="fn:src/utils.py:unique_helper",
                type=NodeType.FUNCTION,
                name="unique_helper",
                file_path="src/utils.py",
            )
        )

        result = resolve_node_strict(db_with_nodes, "unique_helper")

        assert result.node.name == "unique_helper"
        assert result.was_ambiguous is False


class TestInteractiveChoose:
    """Tests for interactive_choose() function."""

    @pytest.fixture
    def candidates(self) -> list[NodeCandidate]:
        """Create a list of candidates for testing."""
        return [
            NodeCandidate(
                node=Node(
                    id="cls:src/auth.py:AuthService",
                    type=NodeType.CLASS,
                    name="AuthService",
                    file_path="src/auth.py",
                    line_start=10,
                    line_end=100,
                ),
                score=90,
                is_test=False,
                is_exact_match=True,
                match_type=MatchType.EXACT_NAME,
            ),
            NodeCandidate(
                node=Node(
                    id="cls:tests/test_auth.py:AuthService",
                    type=NodeType.CLASS,
                    name="AuthService",
                    file_path="tests/test_auth.py",
                    line_start=5,
                    line_end=200,
                ),
                score=70,
                is_test=True,
                is_exact_match=True,
                match_type=MatchType.EXACT_NAME,
            ),
        ]

    def test_interactive_choose_with_mocked_prompt(
        self, candidates: list[NodeCandidate]
    ) -> None:
        """Test interactive_choose with mocked click.prompt."""
        from mu.commands.utils import interactive_choose

        # Mock click.prompt to return "1" (first option)
        with patch("mu.commands.utils.click.prompt", return_value=1):
            with patch("mu.commands.utils.click.echo"):
                chosen = interactive_choose(candidates)

        assert chosen.node.id == "cls:src/auth.py:AuthService"
        assert chosen.score == 90

    def test_interactive_choose_selects_second_option(
        self, candidates: list[NodeCandidate]
    ) -> None:
        """Test interactive_choose selecting the second option."""
        from mu.commands.utils import interactive_choose

        # Mock click.prompt to return "2" (second option)
        with patch("mu.commands.utils.click.prompt", return_value=2):
            with patch("mu.commands.utils.click.echo"):
                chosen = interactive_choose(candidates)

        assert chosen.node.id == "cls:tests/test_auth.py:AuthService"
        assert chosen.is_test is True

    def test_format_candidate_display_output(
        self, candidates: list[NodeCandidate]
    ) -> None:
        """Test that format_candidate_display produces expected output."""
        result = format_candidate_display(candidates[0], 1)

        assert "AuthService" in result
        assert "[1]" in result
        assert "(class)" in result
        assert "src/auth.py" in result
