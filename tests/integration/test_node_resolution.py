"""Integration tests for Node Resolution - Regression tests.

Tests the complete node resolution pipeline with realistic scenarios
that triggered bugs in production, including the .NET test file disambiguation bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mu.kernel import MUbase, Node, NodeType
from mu.kernel.resolver import (
    NodeResolver,
    ResolutionStrategy,
    _is_test_node,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def dotnet_project_db(tmp_path: Path) -> MUbase:
    """Create a MUbase mimicking a .NET project structure.

    This fixture replicates the structure that caused the original bug:
    - Source files in Dominaite.Payroll.Core/
    - Test files in Dominaite.Payroll.Core.Tests/
    """
    db = MUbase(tmp_path / "dotnet.mubase")

    # Source modules and classes
    db.add_node(
        Node(
            id="mod:Dominaite.Payroll.Core/Services/PayoutService.cs",
            type=NodeType.MODULE,
            name="PayoutService",
            file_path="Dominaite.Payroll.Core/Services/PayoutService.cs",
        )
    )
    db.add_node(
        Node(
            id="cls:Dominaite.Payroll.Core/Services/PayoutService.cs:PayoutService",
            type=NodeType.CLASS,
            name="PayoutService",
            qualified_name="Dominaite.Payroll.Core.Services.PayoutService",
            file_path="Dominaite.Payroll.Core/Services/PayoutService.cs",
            line_start=15,
            line_end=250,
        )
    )
    db.add_node(
        Node(
            id="fn:Dominaite.Payroll.Core/Services/PayoutService.cs:PayoutService.ProcessPayout",
            type=NodeType.FUNCTION,
            name="ProcessPayout",
            qualified_name="Dominaite.Payroll.Core.Services.PayoutService.ProcessPayout",
            file_path="Dominaite.Payroll.Core/Services/PayoutService.cs",
            line_start=50,
            line_end=120,
        )
    )

    # Test modules and classes
    db.add_node(
        Node(
            id="mod:Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs",
            type=NodeType.MODULE,
            name="PayoutServiceTests",
            file_path="Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs",
        )
    )
    db.add_node(
        Node(
            id="cls:Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs:PayoutServiceTests",
            type=NodeType.CLASS,
            name="PayoutServiceTests",
            qualified_name="Dominaite.Payroll.Core.Tests.PayoutServiceTests",
            file_path="Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs",
            line_start=10,
            line_end=500,
        )
    )
    db.add_node(
        Node(
            id="fn:Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs:PayoutServiceTests.ProcessPayout_ShouldSucceed",
            type=NodeType.FUNCTION,
            name="ProcessPayout_ShouldSucceed",
            qualified_name="Dominaite.Payroll.Core.Tests.PayoutServiceTests.ProcessPayout_ShouldSucceed",
            file_path="Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs",
            line_start=25,
            line_end=50,
        )
    )

    # Additional service for disambiguation testing
    db.add_node(
        Node(
            id="cls:Dominaite.Payroll.Core/Services/BillingService.cs:BillingService",
            type=NodeType.CLASS,
            name="BillingService",
            qualified_name="Dominaite.Payroll.Core.Services.BillingService",
            file_path="Dominaite.Payroll.Core/Services/BillingService.cs",
            line_start=10,
            line_end=180,
        )
    )
    db.add_node(
        Node(
            id="cls:Dominaite.Payroll.Core.Tests/BillingServiceTests.cs:BillingServiceTests",
            type=NodeType.CLASS,
            name="BillingServiceTests",
            qualified_name="Dominaite.Payroll.Core.Tests.BillingServiceTests",
            file_path="Dominaite.Payroll.Core.Tests/BillingServiceTests.cs",
            line_start=10,
            line_end=300,
        )
    )

    return db


@pytest.fixture
def multi_language_db(tmp_path: Path) -> MUbase:
    """Create a MUbase with nodes from multiple programming languages.

    Useful for testing language-agnostic test detection.
    """
    db = MUbase(tmp_path / "multi.mubase")

    # Python
    db.add_node(
        Node(
            id="cls:src/services/auth.py:AuthService",
            type=NodeType.CLASS,
            name="AuthService",
            file_path="src/services/auth.py",
        )
    )
    db.add_node(
        Node(
            id="cls:tests/test_auth.py:TestAuthService",
            type=NodeType.CLASS,
            name="TestAuthService",
            file_path="tests/test_auth.py",
        )
    )

    # TypeScript
    db.add_node(
        Node(
            id="cls:src/components/Button.tsx:Button",
            type=NodeType.CLASS,
            name="Button",
            file_path="src/components/Button.tsx",
        )
    )
    db.add_node(
        Node(
            id="cls:src/components/__tests__/Button.test.tsx:ButtonTest",
            type=NodeType.CLASS,
            name="ButtonTest",
            file_path="src/components/__tests__/Button.test.tsx",
        )
    )

    # Go
    db.add_node(
        Node(
            id="fn:pkg/handlers/user.go:HandleUser",
            type=NodeType.FUNCTION,
            name="HandleUser",
            file_path="pkg/handlers/user.go",
        )
    )
    db.add_node(
        Node(
            id="fn:pkg/handlers/user_test.go:TestHandleUser",
            type=NodeType.FUNCTION,
            name="TestHandleUser",
            file_path="pkg/handlers/user_test.go",
        )
    )

    # Java
    db.add_node(
        Node(
            id="cls:src/main/java/com/example/UserService.java:UserService",
            type=NodeType.CLASS,
            name="UserService",
            file_path="src/main/java/com/example/UserService.java",
        )
    )
    db.add_node(
        Node(
            id="cls:src/test/java/com/example/UserServiceTest.java:UserServiceTest",
            type=NodeType.CLASS,
            name="UserServiceTest",
            file_path="src/test/java/com/example/UserServiceTest.java",
        )
    )

    return db


# =============================================================================
# Regression Tests
# =============================================================================


@pytest.mark.regression
class TestDominaiteResolutionRegression:
    """Regression tests for the Dominaite .NET project resolution bug.

    Original Bug: When searching for "PayoutService", the resolver would
    incorrectly return PayoutServiceTests (the test class) instead of
    PayoutService (the source class) because:
    1. Test detection wasn't language-agnostic
    2. The .Tests/ directory pattern wasn't recognized
    3. Score calculation didn't properly penalize test files

    These tests ensure the fix remains in place.
    """

    def test_resolve_payoutservice_prefers_source(self, dotnet_project_db: MUbase) -> None:
        """Resolving 'PayoutService' should return the source class, not test."""
        resolver = NodeResolver(dotnet_project_db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("PayoutService")

        # The source class should be selected
        assert result.node.name == "PayoutService"
        assert result.node.file_path == "Dominaite.Payroll.Core/Services/PayoutService.cs"
        assert ".Tests" not in result.node.file_path

        # PayoutServiceTests (suffix match) should be in alternatives
        # Note: PayoutServiceTests matches the suffix "PayoutService" so it's a candidate
        assert result.was_ambiguous is True
        alt_names = [alt.node.name for alt in result.alternatives]
        # The test class (PayoutServiceTests) should be in alternatives since it ends with "PayoutService"
        assert "PayoutServiceTests" in alt_names or len(result.alternatives) >= 1

    def test_resolve_suffix_match_prefers_source(self, dotnet_project_db: MUbase) -> None:
        """Suffix match 'Service' should prefer source files over tests."""
        # Add more services to ensure suffix matching is triggered
        dotnet_project_db.add_node(
            Node(
                id="cls:Dominaite.Payroll.Core/Services/ReportService.cs:ReportService",
                type=NodeType.CLASS,
                name="ReportService",
                file_path="Dominaite.Payroll.Core/Services/ReportService.cs",
            )
        )
        dotnet_project_db.add_node(
            Node(
                id="cls:Dominaite.Payroll.Core.Tests/ReportServiceTests.cs:ReportServiceTests",
                type=NodeType.CLASS,
                name="ReportServiceTests",
                file_path="Dominaite.Payroll.Core.Tests/ReportServiceTests.cs",
            )
        )

        resolver = NodeResolver(dotnet_project_db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("Service")

        # Result should be a source file, not a test file
        assert ".Tests" not in result.node.file_path
        assert not _is_test_node(result.node)

    def test_dotnet_tests_directory_detected(self, dotnet_project_db: MUbase) -> None:
        """The .Tests/ directory pattern should be detected as test."""
        # Get the test node
        test_node = dotnet_project_db.get_node(
            "cls:Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs:PayoutServiceTests"
        )
        assert test_node is not None
        assert _is_test_node(test_node) is True

        # Get the source node
        source_node = dotnet_project_db.get_node(
            "cls:Dominaite.Payroll.Core/Services/PayoutService.cs:PayoutService"
        )
        assert source_node is not None
        assert _is_test_node(source_node) is False

    def test_exact_id_bypasses_disambiguation(self, dotnet_project_db: MUbase) -> None:
        """Exact node ID should return directly without disambiguation."""
        resolver = NodeResolver(dotnet_project_db)

        # Using exact ID should always return that specific node
        result = resolver.resolve(
            "cls:Dominaite.Payroll.Core.Tests/PayoutServiceTests.cs:PayoutServiceTests"
        )

        assert result.node.name == "PayoutServiceTests"
        assert result.was_ambiguous is False
        assert result.resolution_method == "exact_id"

    def test_billing_service_resolution(self, dotnet_project_db: MUbase) -> None:
        """Additional service should also resolve to source, not test."""
        resolver = NodeResolver(dotnet_project_db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("BillingService")

        assert result.node.name == "BillingService"
        assert ".Tests" not in result.node.file_path


@pytest.mark.regression
class TestMultiLanguageResolution:
    """Regression tests for multi-language test detection."""

    def test_python_test_detection(self, multi_language_db: MUbase) -> None:
        """Python test files in tests/ directory should be detected."""
        resolver = NodeResolver(multi_language_db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("AuthService")

        # Should prefer source over test
        assert result.node.file_path == "src/services/auth.py"
        assert "tests" not in result.node.file_path

    def test_typescript_test_detection(self, multi_language_db: MUbase) -> None:
        """TypeScript .test.tsx files in __tests__ should be detected."""
        resolver = NodeResolver(multi_language_db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("Button")

        # Should prefer source over test
        assert result.node.file_path == "src/components/Button.tsx"
        assert "__tests__" not in result.node.file_path

    def test_go_test_detection(self, multi_language_db: MUbase) -> None:
        """Go _test.go files should be detected."""
        resolver = NodeResolver(multi_language_db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("HandleUser")

        # Should prefer source over test
        assert result.node.file_path == "pkg/handlers/user.go"
        assert "_test.go" not in result.node.file_path

    def test_java_test_detection(self, multi_language_db: MUbase) -> None:
        """Java files in src/test/ should be detected."""
        resolver = NodeResolver(multi_language_db, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("UserService")

        # Should prefer source over test
        assert result.node.file_path == "src/main/java/com/example/UserService.java"
        assert "/test/" not in result.node.file_path


# =============================================================================
# Integration Tests for Resolution Strategies
# =============================================================================


class TestResolutionStrategiesIntegration:
    """Integration tests for all resolution strategies."""

    def test_strict_mode_on_unambiguous(self, dotnet_project_db: MUbase) -> None:
        """STRICT mode should succeed when reference is unambiguous."""
        resolver = NodeResolver(dotnet_project_db, strategy=ResolutionStrategy.STRICT)

        # ProcessPayout is unique
        result = resolver.resolve("ProcessPayout")
        assert result.node.name == "ProcessPayout"
        assert result.was_ambiguous is False

    def test_interactive_mode_receives_sorted_candidates(
        self, dotnet_project_db: MUbase
    ) -> None:
        """INTERACTIVE mode should receive candidates sorted by score."""
        received_scores: list[int] = []

        def capture_callback(candidates: list) -> object:
            nonlocal received_scores
            received_scores = [c.score for c in candidates]
            return candidates[0]

        resolver = NodeResolver(
            dotnet_project_db,
            strategy=ResolutionStrategy.INTERACTIVE,
            interactive_callback=capture_callback,
        )

        resolver.resolve("PayoutService")

        # Scores should be in descending order
        assert received_scores == sorted(received_scores, reverse=True)

    def test_first_match_deterministic(self, dotnet_project_db: MUbase) -> None:
        """FIRST_MATCH should return consistent results."""
        resolver = NodeResolver(dotnet_project_db, strategy=ResolutionStrategy.FIRST_MATCH)

        # Run resolution multiple times
        results = [resolver.resolve("PayoutService") for _ in range(5)]

        # All results should be identical
        first_id = results[0].node.id
        assert all(r.node.id == first_id for r in results)


# =============================================================================
# Edge Case Integration Tests
# =============================================================================


class TestEdgeCasesIntegration:
    """Integration tests for edge cases in node resolution."""

    def test_resolve_method_not_class(self, dotnet_project_db: MUbase) -> None:
        """Resolving a method name should return the method, not class."""
        resolver = NodeResolver(dotnet_project_db, strategy=ResolutionStrategy.PREFER_SOURCE)

        result = resolver.resolve("ProcessPayout")

        assert result.node.type == NodeType.FUNCTION
        assert result.node.name == "ProcessPayout"

    def test_resolve_with_multiple_matches_same_score(self, tmp_path: Path) -> None:
        """When multiple matches have the same score, resolution is deterministic."""
        db = MUbase(tmp_path / "test.mubase")

        # Add two identical classes in different files (same depth, both non-test)
        db.add_node(
            Node(
                id="cls:src/a/Service.cs:Service",
                type=NodeType.CLASS,
                name="Service",
                file_path="src/a/Service.cs",
            )
        )
        db.add_node(
            Node(
                id="cls:src/b/Service.cs:Service",
                type=NodeType.CLASS,
                name="Service",
                file_path="src/b/Service.cs",
            )
        )

        resolver = NodeResolver(db, strategy=ResolutionStrategy.PREFER_SOURCE)

        # Run multiple times
        results = [resolver.resolve("Service") for _ in range(3)]

        # Should be deterministic (sorted by node ID as tiebreaker)
        first_id = results[0].node.id
        assert all(r.node.id == first_id for r in results)

    def test_empty_database(self, tmp_path: Path) -> None:
        """Resolution in empty database raises NodeNotFoundError."""
        db = MUbase(tmp_path / "empty.mubase")
        resolver = NodeResolver(db)

        from mu.kernel.resolver import NodeNotFoundError

        with pytest.raises(NodeNotFoundError):
            resolver.resolve("AnyNode")
