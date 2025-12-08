"""Tests for pattern detection (Intelligence Layer)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mu.intelligence import (
    Pattern,
    PatternCategory,
    PatternDetector,
    PatternExample,
    PatternsResult,
)
from mu.kernel import MUbase, Node, NodeType


class TestPatternModels:
    """Tests for pattern data models."""

    def test_pattern_category_values(self) -> None:
        """All expected pattern categories exist."""
        assert PatternCategory.ERROR_HANDLING.value == "error_handling"
        assert PatternCategory.NAMING.value == "naming"
        assert PatternCategory.TESTING.value == "testing"
        assert PatternCategory.ARCHITECTURE.value == "architecture"
        assert PatternCategory.API.value == "api"
        assert PatternCategory.IMPORTS.value == "imports"

    def test_pattern_example_to_dict(self) -> None:
        """PatternExample converts to dict correctly."""
        example = PatternExample(
            file_path="src/services/auth.py",
            line_start=10,
            line_end=25,
            code_snippet="class AuthService:\n    pass",
            annotation="Service class example",
        )
        d = example.to_dict()
        assert d["file_path"] == "src/services/auth.py"
        assert d["line_start"] == 10
        assert d["line_end"] == 25
        assert "AuthService" in d["code_snippet"]
        assert d["annotation"] == "Service class example"

    def test_pattern_to_dict(self) -> None:
        """Pattern converts to dict correctly."""
        pattern = Pattern(
            name="service_layer",
            category=PatternCategory.ARCHITECTURE,
            description="Service layer pattern (5 Service classes)",
            frequency=5,
            confidence=0.9,
            examples=[
                PatternExample(
                    file_path="src/auth.py",
                    line_start=1,
                    line_end=10,
                    code_snippet="class AuthService: ...",
                    annotation="Auth service",
                )
            ],
            anti_patterns=["Business logic in controllers"],
            related_patterns=["repository_pattern"],
        )
        d = pattern.to_dict()
        assert d["name"] == "service_layer"
        assert d["category"] == "architecture"
        assert d["frequency"] == 5
        assert d["confidence"] == 0.9
        assert len(d["examples"]) == 1
        assert d["anti_patterns"] == ["Business logic in controllers"]

    def test_patterns_result_get_by_category(self) -> None:
        """PatternsResult filters by category."""
        patterns = [
            Pattern(
                name="test1",
                category=PatternCategory.NAMING,
                description="Test 1",
                frequency=10,
                confidence=0.9,
            ),
            Pattern(
                name="test2",
                category=PatternCategory.ARCHITECTURE,
                description="Test 2",
                frequency=5,
                confidence=0.8,
            ),
            Pattern(
                name="test3",
                category=PatternCategory.NAMING,
                description="Test 3",
                frequency=3,
                confidence=0.7,
            ),
        ]
        result = PatternsResult(patterns=patterns, total_patterns=3)

        naming_patterns = result.get_by_category(PatternCategory.NAMING)
        assert len(naming_patterns) == 2
        assert all(p.category == PatternCategory.NAMING for p in naming_patterns)

    def test_patterns_result_get_top_patterns(self) -> None:
        """PatternsResult returns top patterns by frequency."""
        patterns = [
            Pattern(
                name="low",
                category=PatternCategory.NAMING,
                description="Low freq",
                frequency=2,
                confidence=0.9,
            ),
            Pattern(
                name="high",
                category=PatternCategory.NAMING,
                description="High freq",
                frequency=100,
                confidence=0.9,
            ),
            Pattern(
                name="medium",
                category=PatternCategory.NAMING,
                description="Medium freq",
                frequency=50,
                confidence=0.9,
            ),
        ]
        result = PatternsResult(patterns=patterns, total_patterns=3)

        top = result.get_top_patterns(2)
        assert len(top) == 2
        assert top[0].name == "high"
        assert top[1].name == "medium"


class TestPatternDetector:
    """Tests for pattern detection."""

    @pytest.fixture
    def temp_mubase(self, tmp_path: Path) -> MUbase:
        """Create a temporary MUbase with sample data."""
        db = MUbase(tmp_path / ".mubase")

        # Add sample nodes representing a codebase
        nodes = [
            # Service pattern
            Node(
                id="cls:src/services/auth.py:AuthService",
                type=NodeType.CLASS,
                name="AuthService",
                file_path="src/services/auth.py",
                line_start=10,
                line_end=50,
            ),
            Node(
                id="cls:src/services/user.py:UserService",
                type=NodeType.CLASS,
                name="UserService",
                file_path="src/services/user.py",
                line_start=5,
                line_end=40,
            ),
            Node(
                id="cls:src/services/payment.py:PaymentService",
                type=NodeType.CLASS,
                name="PaymentService",
                file_path="src/services/payment.py",
                line_start=1,
                line_end=100,
            ),
            # Repository pattern
            Node(
                id="cls:src/repos/user.py:UserRepository",
                type=NodeType.CLASS,
                name="UserRepository",
                file_path="src/repos/user.py",
                line_start=1,
                line_end=30,
            ),
            Node(
                id="cls:src/repos/order.py:OrderRepository",
                type=NodeType.CLASS,
                name="OrderRepository",
                file_path="src/repos/order.py",
                line_start=1,
                line_end=40,
            ),
            Node(
                id="cls:src/repos/product.py:ProductRepository",
                type=NodeType.CLASS,
                name="ProductRepository",
                file_path="src/repos/product.py",
                line_start=1,
                line_end=35,
            ),
            # Error classes
            Node(
                id="cls:src/errors.py:AuthError",
                type=NodeType.CLASS,
                name="AuthError",
                file_path="src/errors.py",
                line_start=5,
                line_end=15,
            ),
            Node(
                id="cls:src/errors.py:ValidationError",
                type=NodeType.CLASS,
                name="ValidationError",
                file_path="src/errors.py",
                line_start=20,
                line_end=30,
            ),
            Node(
                id="cls:src/errors.py:NotFoundError",
                type=NodeType.CLASS,
                name="NotFoundError",
                file_path="src/errors.py",
                line_start=35,
                line_end=45,
            ),
            # Functions with naming patterns
            Node(
                id="fn:src/utils.py:get_user",
                type=NodeType.FUNCTION,
                name="get_user",
                file_path="src/utils.py",
                line_start=1,
                line_end=5,
            ),
            Node(
                id="fn:src/utils.py:get_order",
                type=NodeType.FUNCTION,
                name="get_order",
                file_path="src/utils.py",
                line_start=10,
                line_end=15,
            ),
            Node(
                id="fn:src/utils.py:get_product",
                type=NodeType.FUNCTION,
                name="get_product",
                file_path="src/utils.py",
                line_start=20,
                line_end=25,
            ),
            # Test files
            Node(
                id="mod:tests/test_auth.py",
                type=NodeType.MODULE,
                name="test_auth",
                file_path="tests/test_auth.py",
                line_start=1,
                line_end=100,
            ),
            Node(
                id="mod:tests/test_user.py",
                type=NodeType.MODULE,
                name="test_user",
                file_path="tests/test_user.py",
                line_start=1,
                line_end=80,
            ),
            Node(
                id="mod:tests/test_payment.py",
                type=NodeType.MODULE,
                name="test_payment",
                file_path="tests/test_payment.py",
                line_start=1,
                line_end=120,
            ),
            # Index/barrel files
            Node(
                id="mod:src/__init__.py",
                type=NodeType.MODULE,
                name="__init__",
                file_path="src/__init__.py",
                line_start=1,
                line_end=10,
            ),
            Node(
                id="mod:src/services/__init__.py",
                type=NodeType.MODULE,
                name="__init__",
                file_path="src/services/__init__.py",
                line_start=1,
                line_end=5,
            ),
            Node(
                id="mod:src/repos/__init__.py",
                type=NodeType.MODULE,
                name="__init__",
                file_path="src/repos/__init__.py",
                line_start=1,
                line_end=5,
            ),
        ]

        for node in nodes:
            db.add_node(node)

        # Set root path metadata
        db.conn.execute(
            "INSERT OR REPLACE INTO metadata VALUES ('root_path', ?)",
            [str(tmp_path)],
        )

        return db

    def test_detect_all_patterns(self, temp_mubase: MUbase) -> None:
        """Pattern detector finds patterns across all categories."""
        detector = PatternDetector(temp_mubase)
        result = detector.detect()

        assert result.total_patterns > 0
        assert len(result.categories_found) > 0
        assert result.detection_time_ms >= 0

    def test_detect_architecture_patterns(self, temp_mubase: MUbase) -> None:
        """Pattern detector finds architectural patterns (services, repos)."""
        detector = PatternDetector(temp_mubase)
        result = detector.detect(category=PatternCategory.ARCHITECTURE)

        # Should find service and repository patterns
        pattern_names = [p.name for p in result.patterns]

        # Check for service layer pattern
        service_patterns = [p for p in result.patterns if "service" in p.name.lower()]
        assert len(service_patterns) > 0, "Should detect service layer pattern"

        # Check for repository pattern
        repo_patterns = [
            p for p in result.patterns if "repository" in p.name.lower()
        ]
        assert len(repo_patterns) > 0, "Should detect repository pattern"

    def test_detect_error_handling_patterns(self, temp_mubase: MUbase) -> None:
        """Pattern detector finds error handling patterns."""
        detector = PatternDetector(temp_mubase)
        result = detector.detect(category=PatternCategory.ERROR_HANDLING)

        # Should find custom error classes
        assert any(
            "error" in p.name.lower() for p in result.patterns
        ), "Should detect error class pattern"

    def test_detect_naming_patterns(self, temp_mubase: MUbase) -> None:
        """Pattern detector finds naming patterns."""
        detector = PatternDetector(temp_mubase)
        result = detector.detect(category=PatternCategory.NAMING)

        # Should find function prefix pattern (get_*)
        prefix_patterns = [
            p for p in result.patterns if "prefix" in p.name.lower()
        ]
        assert len(prefix_patterns) > 0, "Should detect function prefix patterns"

    def test_detect_testing_patterns(self, temp_mubase: MUbase) -> None:
        """Pattern detector finds testing patterns."""
        detector = PatternDetector(temp_mubase)
        result = detector.detect(category=PatternCategory.TESTING)

        # Should find test file organization pattern
        assert any(
            "test" in p.name.lower() for p in result.patterns
        ), "Should detect test patterns"

    def test_detect_import_patterns(self, temp_mubase: MUbase) -> None:
        """Pattern detector finds import/barrel patterns."""
        detector = PatternDetector(temp_mubase)
        result = detector.detect(category=PatternCategory.IMPORTS)

        # Should find barrel file pattern (__init__.py)
        barrel_patterns = [
            p for p in result.patterns if "barrel" in p.name.lower()
        ]
        assert len(barrel_patterns) > 0, "Should detect barrel file pattern"


class TestPatternStorage:
    """Tests for pattern storage in MUbase."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> MUbase:
        """Create a temporary MUbase."""
        return MUbase(tmp_path / ".mubase")

    def test_save_and_retrieve_patterns(self, temp_db: MUbase) -> None:
        """Patterns can be saved and retrieved."""
        patterns = [
            Pattern(
                name="test_pattern",
                category=PatternCategory.NAMING,
                description="Test pattern",
                frequency=10,
                confidence=0.9,
                examples=[
                    PatternExample(
                        file_path="test.py",
                        line_start=1,
                        line_end=5,
                        code_snippet="def test(): pass",
                        annotation="Test example",
                    )
                ],
                anti_patterns=["Don't do this"],
            ),
        ]

        temp_db.save_patterns(patterns)
        assert temp_db.has_patterns()

        retrieved = temp_db.get_patterns()
        assert len(retrieved) == 1
        assert retrieved[0].name == "test_pattern"
        assert retrieved[0].category == PatternCategory.NAMING
        assert retrieved[0].frequency == 10
        assert len(retrieved[0].examples) == 1
        assert retrieved[0].anti_patterns == ["Don't do this"]

    def test_filter_patterns_by_category(self, temp_db: MUbase) -> None:
        """Patterns can be filtered by category."""
        patterns = [
            Pattern(
                name="naming_pattern",
                category=PatternCategory.NAMING,
                description="Naming",
                frequency=5,
                confidence=0.8,
            ),
            Pattern(
                name="arch_pattern",
                category=PatternCategory.ARCHITECTURE,
                description="Architecture",
                frequency=3,
                confidence=0.7,
            ),
        ]

        temp_db.save_patterns(patterns)

        naming = temp_db.get_patterns("naming")
        assert len(naming) == 1
        assert naming[0].name == "naming_pattern"

        arch = temp_db.get_patterns("architecture")
        assert len(arch) == 1
        assert arch[0].name == "arch_pattern"

    def test_patterns_stats(self, temp_db: MUbase) -> None:
        """Pattern stats are calculated correctly."""
        patterns = [
            Pattern(
                name="p1",
                category=PatternCategory.NAMING,
                description="",
                frequency=1,
                confidence=0.9,
            ),
            Pattern(
                name="p2",
                category=PatternCategory.NAMING,
                description="",
                frequency=2,
                confidence=0.8,
            ),
            Pattern(
                name="p3",
                category=PatternCategory.ARCHITECTURE,
                description="",
                frequency=3,
                confidence=0.7,
            ),
        ]

        temp_db.save_patterns(patterns)
        stats = temp_db.patterns_stats()

        assert stats["total_patterns"] == 3
        assert stats["patterns_by_category"]["naming"] == 2
        assert stats["patterns_by_category"]["architecture"] == 1

    def test_has_patterns_empty(self, temp_db: MUbase) -> None:
        """has_patterns returns False for empty database."""
        assert not temp_db.has_patterns()
