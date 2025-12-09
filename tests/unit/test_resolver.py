"""Tests for MU Node Resolver - disambiguation and resolution strategies."""

from __future__ import annotations

from pathlib import Path

import pytest

from mu.kernel import MUbase, Node, NodeType
from mu.kernel.resolver import (
    AmbiguousNodeError,
    MatchType,
    NodeCandidate,
    NodeNotFoundError,
    NodeResolver,
    ResolvedNode,
    ResolutionStrategy,
    _is_test_node,
)


class TestResolutionStrategy:
    """Tests for ResolutionStrategy enum."""

    def test_strategy_values_exist(self) -> None:
        """All expected strategy values are defined."""
        assert ResolutionStrategy.INTERACTIVE.value == "interactive"
        assert ResolutionStrategy.PREFER_SOURCE.value == "prefer_source"
        assert ResolutionStrategy.FIRST_MATCH.value == "first_match"
        assert ResolutionStrategy.STRICT.value == "strict"

    def test_strategy_enum_members(self) -> None:
        """All expected strategies exist as enum members."""
        strategies = list(ResolutionStrategy)
        assert len(strategies) == 4
        assert ResolutionStrategy.INTERACTIVE in strategies
        assert ResolutionStrategy.PREFER_SOURCE in strategies
        assert ResolutionStrategy.FIRST_MATCH in strategies
        assert ResolutionStrategy.STRICT in strategies


class TestMatchType:
    """Tests for MatchType enum."""

    def test_match_type_values_exist(self) -> None:
        """All expected match type values are defined."""
        assert MatchType.EXACT_ID.value == "exact_id"
        assert MatchType.EXACT_NAME.value == "exact_name"
        assert MatchType.SUFFIX_MATCH.value == "suffix_match"
        assert MatchType.FUZZY_MATCH.value == "fuzzy_match"


class TestNodeCandidate:
    """Tests for NodeCandidate dataclass."""

    @pytest.fixture
    def sample_node(self) -> Node:
        """Create a sample node for testing."""
        return Node(
            id="cls:src/services/user.py:UserService",
            type=NodeType.CLASS,
            name="UserService",
            qualified_name="services.user.UserService",
            file_path="src/services/user.py",
            line_start=10,
            line_end=100,
        )

    def test_node_candidate_creation(self, sample_node: Node) -> None:
        """NodeCandidate can be created with required fields."""
        candidate = NodeCandidate(
            node=sample_node,
            score=80,
            is_test=False,
            is_exact_match=True,
            match_type=MatchType.EXACT_NAME,
        )
        assert candidate.node == sample_node
        assert candidate.score == 80
        assert candidate.is_test is False
        assert candidate.is_exact_match is True
        assert candidate.match_type == MatchType.EXACT_NAME

    def test_node_candidate_to_dict(self, sample_node: Node) -> None:
        """NodeCandidate.to_dict() returns correct dictionary."""
        candidate = NodeCandidate(
            node=sample_node,
            score=90,
            is_test=False,
            is_exact_match=True,
            match_type=MatchType.EXACT_ID,
        )
        d = candidate.to_dict()

        assert d["node_id"] == "cls:src/services/user.py:UserService"
        assert d["node_name"] == "UserService"
        assert d["score"] == 90
        assert d["is_test"] is False
        assert d["is_exact_match"] is True
        assert d["match_type"] == "exact_id"
        assert d["file_path"] == "src/services/user.py"
        assert d["line_start"] == 10
        assert d["line_end"] == 100

    def test_node_candidate_to_dict_test_file(self) -> None:
        """NodeCandidate.to_dict() reflects is_test correctly for test nodes."""
        test_node = Node(
            id="cls:tests/test_user.py:TestUserService",
            type=NodeType.CLASS,
            name="TestUserService",
            file_path="tests/test_user.py",
        )
        candidate = NodeCandidate(
            node=test_node,
            score=70,
            is_test=True,
            is_exact_match=False,
            match_type=MatchType.SUFFIX_MATCH,
        )
        d = candidate.to_dict()

        assert d["is_test"] is True
        assert d["match_type"] == "suffix_match"


class TestResolvedNode:
    """Tests for ResolvedNode dataclass."""

    @pytest.fixture
    def sample_node(self) -> Node:
        """Create a sample node for testing."""
        return Node(
            id="fn:src/auth.py:login",
            type=NodeType.FUNCTION,
            name="login",
            file_path="src/auth.py",
        )

    def test_resolved_node_creation(self, sample_node: Node) -> None:
        """ResolvedNode can be created with required fields."""
        resolved = ResolvedNode(node=sample_node)

        assert resolved.node == sample_node
        assert resolved.alternatives == []
        assert resolved.resolution_method == "exact"
        assert resolved.was_ambiguous is False

    def test_resolved_node_with_alternatives(self, sample_node: Node) -> None:
        """ResolvedNode can have alternatives populated."""
        alt_node = Node(
            id="fn:tests/test_auth.py:login",
            type=NodeType.FUNCTION,
            name="login",
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
            node=sample_node,
            alternatives=[alt_candidate],
            resolution_method="prefer_source",
            was_ambiguous=True,
        )

        assert len(resolved.alternatives) == 1
        assert resolved.alternatives[0].node.id == "fn:tests/test_auth.py:login"
        assert resolved.was_ambiguous is True

    def test_resolved_node_to_dict(self, sample_node: Node) -> None:
        """ResolvedNode.to_dict() returns correct dictionary."""
        resolved = ResolvedNode(
            node=sample_node,
            alternatives=[],
            resolution_method="exact_id",
            was_ambiguous=False,
        )
        d = resolved.to_dict()

        assert d["node_id"] == "fn:src/auth.py:login"
        assert d["node_name"] == "login"
        assert d["resolution_method"] == "exact_id"
        assert d["was_ambiguous"] is False
        assert d["alternative_count"] == 0
        assert d["alternatives"] == []

    def test_resolved_node_to_dict_with_alternatives(self, sample_node: Node) -> None:
        """ResolvedNode.to_dict() includes serialized alternatives."""
        alt_node = Node(
            id="fn:tests/test_auth.py:login",
            type=NodeType.FUNCTION,
            name="login",
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
            node=sample_node,
            alternatives=[alt_candidate],
            resolution_method="prefer_source",
            was_ambiguous=True,
        )
        d = resolved.to_dict()

        assert d["alternative_count"] == 1
        assert len(d["alternatives"]) == 1
        assert d["alternatives"][0]["node_id"] == "fn:tests/test_auth.py:login"
        assert d["alternatives"][0]["is_test"] is True


class TestIsTestNode:
    """Tests for _is_test_node function - language-agnostic test detection."""

    @pytest.mark.parametrize(
        "file_path,name,expected",
        [
            # Python test patterns
            ("tests/unit/test_service.py", "test_service", True),
            ("tests/test_auth.py", "TestAuth", True),
            ("src/app/service.py", "Service", False),
            ("test_utils.py", "test_utils", True),
            # conftest.py in a nested tests directory (pattern requires /tests/ not tests/)
            ("src/tests/conftest.py", "conftest", True),
            ("src/service_test.py", "service_test", True),
            ("src/service_tests.py", "service_tests", True),
            # TypeScript/JavaScript test patterns
            ("src/app/__tests__/service.test.ts", "ServiceTest", True),
            ("src/app/service.spec.ts", "ServiceSpec", True),
            ("src/app/__test__/util.ts", "util", True),
            ("src/components/Button.test.tsx", "Button", True),
            ("src/components/Button.spec.tsx", "Button", True),
            ("src/components/Button.tsx", "Button", False),
            # __mocks__ needs to be within a path (not at root)
            ("src/__mocks__/api.ts", "api", True),
            # Go test patterns
            ("src/app/service_test.go", "TestService", True),
            ("src/app/service.go", "Service", False),
            # Java test patterns
            ("src/test/java/ServiceTest.java", "ServiceTest", True),
            ("src/main/java/Service.java", "Service", False),
            # Rust test patterns
            ("src/lib_test.rs", "test_lib", True),
            # tests directory must match pattern /tests/
            ("src/tests/integration.rs", "integration", True),
            ("src/lib.rs", "lib", False),
            # C# / .NET test patterns
            ("src/Services.Tests/PayoutServiceTests.cs", "PayoutServiceTests", True),
            ("src/Services/PayoutService.cs", "PayoutService", False),
            ("src/MyApp.Test/ServiceTest.cs", "ServiceTest", True),
            ("src/MyApp/Service.cs", "Service", False),
            ("Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs", "PayoutServiceTests", True),
            ("Dominaite.Payroll.Core/PayoutService.cs", "PayoutService", False),
            ("tests/UnitTests/AuthTest.cs", "AuthTest", True),
            ("src/IntegrationTests/ApiTests.cs", "ApiTests", True),
            ("src/FunctionalTests/E2ETest.cs", "E2ETest", True),
            # Edge cases - should NOT be detected as tests
            ("src/contest.py", "Contest", False),
            ("src/attestation.py", "Attestation", False),
            ("src/test_manager.py", "TestManager", True),  # Starts with test_
            ("src/prototype.py", "Prototype", False),
            # Name-based patterns (class/function names)
            ("src/utils.py", "TestHelper", True),  # Name starts with Test
            ("src/mock_client.py", "MockClient", True),  # Name starts with Mock
            ("src/fixtures.py", "Fixtures", True),  # Name equals fixture pattern
            ("src/stub_service.py", "StubService", True),  # Name starts with Stub
        ],
    )
    def test_is_test_node_detection(self, file_path: str, name: str, expected: bool) -> None:
        """Test detection for various language test file patterns."""
        node = Node(
            id=f"cls:{file_path}:{name}",
            type=NodeType.CLASS,
            name=name,
            file_path=file_path,
        )
        result = _is_test_node(node)
        assert result == expected, f"Expected {expected} for {file_path}:{name}, got {result}"

    def test_is_test_node_no_file_path(self) -> None:
        """Test detection when file_path is None."""
        node = Node(
            id="cls:unknown:TestService",
            type=NodeType.CLASS,
            name="TestService",
            file_path=None,
        )
        # Should still detect based on name pattern
        assert _is_test_node(node) is True

    def test_is_test_node_empty_file_path(self) -> None:
        """Test detection when file_path is empty string."""
        node = Node(
            id="cls:unknown:Service",
            type=NodeType.CLASS,
            name="Service",
            file_path="",
        )
        assert _is_test_node(node) is False


class TestNodeResolver:
    """Tests for NodeResolver class."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> MUbase:
        """Create an in-memory MUbase with test data."""
        db = MUbase(":memory:")

        # Add source file node
        db.add_node(
            Node(
                id="cls:src/services/payout.py:PayoutService",
                type=NodeType.CLASS,
                name="PayoutService",
                qualified_name="services.payout.PayoutService",
                file_path="src/services/payout.py",
                line_start=10,
                line_end=100,
            )
        )

        # Add test file node with similar name
        db.add_node(
            Node(
                id="cls:tests/test_payout.py:PayoutServiceTests",
                type=NodeType.CLASS,
                name="PayoutServiceTests",
                qualified_name="tests.test_payout.PayoutServiceTests",
                file_path="tests/test_payout.py",
                line_start=5,
                line_end=200,
            )
        )

        # Add another source node for ambiguity testing
        db.add_node(
            Node(
                id="fn:src/services/payout.py:PayoutService.process",
                type=NodeType.FUNCTION,
                name="process",
                qualified_name="services.payout.PayoutService.process",
                file_path="src/services/payout.py",
                line_start=50,
                line_end=75,
            )
        )

        # Add module node
        db.add_node(
            Node(
                id="mod:src/services/payout.py",
                type=NodeType.MODULE,
                name="payout",
                file_path="src/services/payout.py",
            )
        )

        # Add a function with same name in different locations
        db.add_node(
            Node(
                id="fn:src/utils.py:login",
                type=NodeType.FUNCTION,
                name="login",
                file_path="src/utils.py",
            )
        )
        db.add_node(
            Node(
                id="fn:src/auth/handlers.py:login",
                type=NodeType.FUNCTION,
                name="login",
                file_path="src/auth/handlers.py",
            )
        )
        db.add_node(
            Node(
                id="fn:tests/test_auth.py:test_login",
                type=NodeType.FUNCTION,
                name="test_login",
                file_path="tests/test_auth.py",
            )
        )

        return db

    def test_exact_id_match(self, db: MUbase) -> None:
        """Test exact ID match returns immediately without ambiguity."""
        resolver = NodeResolver(db)
        result = resolver.resolve("cls:src/services/payout.py:PayoutService")

        assert result.node.id == "cls:src/services/payout.py:PayoutService"
        assert result.node.name == "PayoutService"
        assert result.was_ambiguous is False
        assert result.resolution_method == "exact_id"
        assert len(result.alternatives) == 0

    def test_exact_name_match_single(self, db: MUbase) -> None:
        """Test exact name match when only one node has that name."""
        resolver = NodeResolver(db)
        result = resolver.resolve("process")

        assert result.node.name == "process"
        assert result.was_ambiguous is False
        assert result.resolution_method == "exact_name"

    def test_exact_name_match_multiple(self, db: MUbase) -> None:
        """Test exact name match with multiple candidates."""
        resolver = NodeResolver(db)
        result = resolver.resolve("login")

        # Should resolve to one of the login functions
        assert result.node.name == "login"
        # Multiple matches exist
        assert result.was_ambiguous is True
        assert len(result.alternatives) > 0

    def test_suffix_match(self, db: MUbase) -> None:
        """Test suffix matching falls back correctly."""
        # Add a node that can only be found by suffix
        db.add_node(
            Node(
                id="cls:src/services/user_service.py:UserService",
                type=NodeType.CLASS,
                name="UserService",
                file_path="src/services/user_service.py",
            )
        )

        resolver = NodeResolver(db)
        result = resolver.resolve("Service")

        # Should find nodes ending with "Service"
        assert "Service" in result.node.name
        # Multiple services exist
        assert result.was_ambiguous is True

    def test_fuzzy_match(self, db: MUbase) -> None:
        """Test fuzzy matching finds partial matches."""
        resolver = NodeResolver(db)
        result = resolver.resolve("Payout")

        # Should find PayoutService via fuzzy match
        assert "Payout" in result.node.name
        assert result.was_ambiguous is True

    def test_prefer_source_over_test(self, db: MUbase) -> None:
        """Test PREFER_SOURCE strategy selects source file over test file."""
        # Add nodes where both source and test match the same search
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

        resolver = NodeResolver(db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("AuthService")

        # Should prefer the source file
        assert result.node.file_path == "src/auth.py"
        assert result.was_ambiguous is True
        assert result.resolution_method == "prefer_source"

        # The test file should be in alternatives
        alt_paths = [alt.node.file_path for alt in result.alternatives]
        assert "tests/test_auth.py" in alt_paths

    def test_strict_raises_on_ambiguity(self, db: MUbase) -> None:
        """Test STRICT strategy raises AmbiguousNodeError on multiple matches."""
        resolver = NodeResolver(db, strategy=ResolutionStrategy.STRICT)

        with pytest.raises(AmbiguousNodeError) as excinfo:
            resolver.resolve("login")

        assert excinfo.value.reference == "login"
        assert len(excinfo.value.candidates) >= 2
        assert "login" in str(excinfo.value)

    def test_interactive_calls_callback(self, db: MUbase) -> None:
        """Test INTERACTIVE strategy calls the callback with candidates."""
        callback_called = False
        received_candidates: list[NodeCandidate] = []

        def mock_callback(candidates: list[NodeCandidate]) -> NodeCandidate:
            nonlocal callback_called, received_candidates
            callback_called = True
            received_candidates = candidates
            # Choose the first candidate
            return candidates[0]

        resolver = NodeResolver(
            db,
            strategy=ResolutionStrategy.INTERACTIVE,
            interactive_callback=mock_callback,
        )
        result = resolver.resolve("login")

        assert callback_called is True
        assert len(received_candidates) >= 2
        assert result.resolution_method == "interactive"
        assert result.was_ambiguous is True

    def test_interactive_falls_back_without_callback(self, db: MUbase) -> None:
        """Test INTERACTIVE without callback falls back to PREFER_SOURCE."""
        resolver = NodeResolver(
            db,
            strategy=ResolutionStrategy.INTERACTIVE,
            interactive_callback=None,  # No callback provided
        )
        result = resolver.resolve("login")

        # Should fall back to prefer_source behavior
        assert result.was_ambiguous is True
        # Should prefer non-test file
        assert "test" not in result.node.file_path.lower()

    def test_first_match_behavior(self, db: MUbase) -> None:
        """Test FIRST_MATCH returns first match alphabetically."""
        resolver = NodeResolver(db, strategy=ResolutionStrategy.FIRST_MATCH)
        result = resolver.resolve("login")

        assert result.was_ambiguous is True
        assert result.resolution_method == "first_match"
        # First match is the one with highest score (already sorted)
        assert result.node.name == "login"

    def test_not_found_raises_error(self, db: MUbase) -> None:
        """Test NodeNotFoundError raised when no matches."""
        resolver = NodeResolver(db)

        with pytest.raises(NodeNotFoundError) as excinfo:
            resolver.resolve("NonExistentNode123")

        assert excinfo.value.reference == "NonExistentNode123"
        assert "NonExistentNode123" in str(excinfo.value)

    def test_not_found_empty_reference(self, db: MUbase) -> None:
        """Test NodeNotFoundError raised for empty reference."""
        resolver = NodeResolver(db)

        with pytest.raises(NodeNotFoundError) as excinfo:
            resolver.resolve("")

        assert "Empty" in str(excinfo.value)

    def test_not_found_whitespace_reference(self, db: MUbase) -> None:
        """Test reference is stripped before processing."""
        resolver = NodeResolver(db)

        with pytest.raises(NodeNotFoundError):
            resolver.resolve("   ")

    def test_scoring_system_prefers_exact_over_fuzzy(self, db: MUbase) -> None:
        """Test higher scores win - exact matches beat fuzzy matches."""
        # Add a node that matches exactly
        db.add_node(
            Node(
                id="fn:src/exact.py:TargetFunction",
                type=NodeType.FUNCTION,
                name="TargetFunction",
                file_path="src/exact.py",
            )
        )
        # Add a node that only matches via fuzzy (contains TargetFunction)
        db.add_node(
            Node(
                id="fn:src/fuzzy.py:MyTargetFunctionWrapper",
                type=NodeType.FUNCTION,
                name="MyTargetFunctionWrapper",
                file_path="src/fuzzy.py",
            )
        )

        resolver = NodeResolver(db)
        result = resolver.resolve("TargetFunction")

        # Exact match should win
        assert result.node.name == "TargetFunction"
        assert result.node.id == "fn:src/exact.py:TargetFunction"

    def test_scoring_system_shorter_path_bonus(self, db: MUbase) -> None:
        """Test shorter paths get bonus points."""
        # Add nodes at different path depths
        db.add_node(
            Node(
                id="cls:src/svc.py:DeepService",
                type=NodeType.CLASS,
                name="DeepService",
                file_path="src/svc.py",
            )
        )
        db.add_node(
            Node(
                id="cls:src/a/b/c/d/deep/svc.py:DeepService",
                type=NodeType.CLASS,
                name="DeepService",
                file_path="src/a/b/c/d/deep/svc.py",
            )
        )

        resolver = NodeResolver(db, strategy=ResolutionStrategy.FIRST_MATCH)
        result = resolver.resolve("DeepService")

        # Shorter path should have higher score and come first
        assert result.node.file_path == "src/svc.py"

    def test_scoring_non_test_bonus(self, db: MUbase) -> None:
        """Test non-test files get bonus points."""
        db.add_node(
            Node(
                id="cls:src/scorer.py:Scorer",
                type=NodeType.CLASS,
                name="Scorer",
                file_path="src/scorer.py",
            )
        )
        db.add_node(
            Node(
                id="cls:tests/test_scorer.py:Scorer",
                type=NodeType.CLASS,
                name="Scorer",
                file_path="tests/test_scorer.py",
            )
        )

        resolver = NodeResolver(db, strategy=ResolutionStrategy.FIRST_MATCH)
        result = resolver.resolve("Scorer")

        # Source file should have higher score due to non-test bonus
        assert result.node.file_path == "src/scorer.py"

    def test_default_strategy_is_prefer_source(self, db: MUbase) -> None:
        """Test default strategy is PREFER_SOURCE."""
        resolver = NodeResolver(db)
        assert resolver.strategy == ResolutionStrategy.PREFER_SOURCE


class TestNodeResolverEdgeCases:
    """Edge case tests for NodeResolver."""

    @pytest.fixture
    def db(self) -> MUbase:
        """Create an in-memory MUbase."""
        return MUbase(":memory:")

    def test_resolve_with_special_characters_in_name(self, db: MUbase) -> None:
        """Test resolving nodes with special characters."""
        db.add_node(
            Node(
                id="fn:src/utils.py:__init__",
                type=NodeType.FUNCTION,
                name="__init__",
                file_path="src/utils.py",
            )
        )

        resolver = NodeResolver(db)
        result = resolver.resolve("__init__")

        assert result.node.name == "__init__"

    def test_resolve_module_by_file_path(self, db: MUbase) -> None:
        """Test resolving a module using its file path reference."""
        db.add_node(
            Node(
                id="mod:src/services/api.py",
                type=NodeType.MODULE,
                name="api",
                file_path="src/services/api.py",
            )
        )

        resolver = NodeResolver(db)
        result = resolver.resolve("mod:src/services/api.py")

        assert result.node.id == "mod:src/services/api.py"
        assert result.was_ambiguous is False

    def test_all_test_files_returns_first_test(self, db: MUbase) -> None:
        """Test when all candidates are test files, returns highest scored."""
        db.add_node(
            Node(
                id="cls:tests/a/test_svc.py:TestService",
                type=NodeType.CLASS,
                name="TestService",
                file_path="tests/a/test_svc.py",
            )
        )
        db.add_node(
            Node(
                id="cls:tests/b/c/test_svc.py:TestService",
                type=NodeType.CLASS,
                name="TestService",
                file_path="tests/b/c/test_svc.py",
            )
        )

        resolver = NodeResolver(db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("TestService")

        # Should return one of the test files (shorter path wins)
        assert result.node.name == "TestService"
        # All are tests, so was_ambiguous but resolved
        assert result.was_ambiguous is True
        # Shorter path should win
        assert result.node.file_path == "tests/a/test_svc.py"


class TestNodeNotFoundError:
    """Tests for NodeNotFoundError exception."""

    def test_error_with_default_message(self) -> None:
        """Test error with default message."""
        error = NodeNotFoundError("MyNode")
        assert error.reference == "MyNode"
        assert "MyNode" in str(error)
        assert "not found" in str(error).lower()

    def test_error_with_custom_message(self) -> None:
        """Test error with custom message."""
        error = NodeNotFoundError("MyNode", "Custom error message")
        assert error.reference == "MyNode"
        assert str(error) == "Custom error message"


class TestAmbiguousNodeError:
    """Tests for AmbiguousNodeError exception."""

    def test_error_contains_candidates(self) -> None:
        """Test error contains candidate information."""
        candidates = [
            NodeCandidate(
                node=Node(id="cls:a.py:Foo", type=NodeType.CLASS, name="Foo"),
                score=80,
                is_test=False,
                is_exact_match=True,
                match_type=MatchType.EXACT_NAME,
            ),
            NodeCandidate(
                node=Node(id="cls:b.py:Foo", type=NodeType.CLASS, name="Foo"),
                score=75,
                is_test=False,
                is_exact_match=True,
                match_type=MatchType.EXACT_NAME,
            ),
        ]

        error = AmbiguousNodeError("Foo", candidates)

        assert error.reference == "Foo"
        assert len(error.candidates) == 2
        assert "cls:a.py:Foo" in str(error)
        assert "cls:b.py:Foo" in str(error)

    def test_error_truncates_many_candidates(self) -> None:
        """Test error message truncates when many candidates."""
        candidates = [
            NodeCandidate(
                node=Node(id=f"cls:{i}.py:Foo", type=NodeType.CLASS, name="Foo"),
                score=80 - i,
                is_test=False,
                is_exact_match=True,
                match_type=MatchType.EXACT_NAME,
            )
            for i in range(10)
        ]

        error = AmbiguousNodeError("Foo", candidates)

        # Should show first 5 and indicate more
        assert "... and 5 more" in str(error)
        # Should contain first 5
        for i in range(5):
            assert f"cls:{i}.py:Foo" in str(error)
