"""Tests for the proactive warnings module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mu.intelligence.models import (
    ProactiveWarning,
    WarningCategory,
    WarningsResult,
)
from mu.intelligence.warnings import (
    ProactiveWarningGenerator,
    WarningConfig,
)


class TestWarningCategory:
    """Tests for WarningCategory enum."""

    def test_all_categories_exist(self) -> None:
        """Test all expected categories exist."""
        categories = [
            WarningCategory.HIGH_IMPACT,
            WarningCategory.STALE,
            WarningCategory.SECURITY,
            WarningCategory.NO_TESTS,
            WarningCategory.DEPRECATED,
            WarningCategory.COMPLEXITY,
            WarningCategory.DIFFERENT_OWNER,
        ]
        assert len(categories) == 7

    def test_category_values(self) -> None:
        """Test category string values."""
        assert WarningCategory.HIGH_IMPACT.value == "high_impact"
        assert WarningCategory.SECURITY.value == "security"
        assert WarningCategory.NO_TESTS.value == "no_tests"


class TestProactiveWarning:
    """Tests for ProactiveWarning dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dict."""
        warning = ProactiveWarning(
            category=WarningCategory.HIGH_IMPACT,
            level="warn",
            message="Many dependents",
            details={"count": 42},
        )
        d = warning.to_dict()

        assert d["category"] == "high_impact"
        assert d["level"] == "warn"
        assert d["message"] == "Many dependents"
        assert d["details"] == {"count": 42}

    def test_default_details(self) -> None:
        """Test default empty details."""
        warning = ProactiveWarning(
            category=WarningCategory.STALE,
            level="info",
            message="Old code",
        )
        assert warning.details == {}


class TestWarningsResult:
    """Tests for WarningsResult dataclass."""

    def test_has_warnings(self) -> None:
        """Test has_warnings property."""
        result = WarningsResult(target="test.py", target_type="file")
        assert not result.has_warnings

        result.warnings.append(
            ProactiveWarning(
                category=WarningCategory.STALE,
                level="info",
                message="test",
            )
        )
        assert result.has_warnings

    def test_warning_counts(self) -> None:
        """Test error/warn/info count properties."""
        result = WarningsResult(
            target="test.py",
            target_type="file",
            warnings=[
                ProactiveWarning(
                    category=WarningCategory.HIGH_IMPACT,
                    level="error",
                    message="error1",
                ),
                ProactiveWarning(
                    category=WarningCategory.HIGH_IMPACT,
                    level="error",
                    message="error2",
                ),
                ProactiveWarning(
                    category=WarningCategory.STALE,
                    level="warn",
                    message="warn1",
                ),
                ProactiveWarning(
                    category=WarningCategory.NO_TESTS,
                    level="info",
                    message="info1",
                ),
            ],
        )

        assert result.error_count == 2
        assert result.warn_count == 1
        assert result.info_count == 1

    def test_to_dict(self) -> None:
        """Test serialization."""
        result = WarningsResult(
            target="src/auth.py",
            target_type="file",
            summary="1 warning",
            risk_score=0.15,
            analysis_time_ms=42.5,
        )
        d = result.to_dict()

        assert d["target"] == "src/auth.py"
        assert d["target_type"] == "file"
        assert d["summary"] == "1 warning"
        assert d["risk_score"] == 0.15
        assert d["analysis_time_ms"] == 42.5
        assert d["warnings"] == []


class TestWarningConfig:
    """Tests for WarningConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = WarningConfig()

        assert config.high_impact_threshold == 10
        assert config.stale_warn_days == 180
        assert config.stale_error_days == 365
        assert config.complexity_warn == 20
        assert config.complexity_error == 50

    def test_feature_flags(self) -> None:
        """Test feature flags default to True."""
        config = WarningConfig()

        assert config.check_impact is True
        assert config.check_staleness is True
        assert config.check_security is True
        assert config.check_tests is True
        assert config.check_complexity is True
        assert config.check_deprecated is True

    def test_custom_thresholds(self) -> None:
        """Test custom threshold values."""
        config = WarningConfig(
            high_impact_threshold=5,
            complexity_warn=10,
        )

        assert config.high_impact_threshold == 5
        assert config.complexity_warn == 10


class TestProactiveWarningGenerator:
    """Tests for ProactiveWarningGenerator."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock MUbase."""
        db = MagicMock()
        db.conn = MagicMock()
        db.get_node = MagicMock(return_value=None)
        db.find_by_name = MagicMock(return_value=[])
        db.get_children = MagicMock(return_value=[])
        return db

    @pytest.fixture
    def generator(self, mock_db: MagicMock, tmp_path: Path) -> ProactiveWarningGenerator:
        """Create a generator with mock DB."""
        return ProactiveWarningGenerator(mock_db, root_path=tmp_path)

    def test_analyze_unknown_target(
        self, generator: ProactiveWarningGenerator
    ) -> None:
        """Test analyzing an unknown target raises ValueError."""
        with pytest.raises(ValueError, match="Target not found"):
            generator.analyze("nonexistent_file.py")

    def test_analyze_file_target(
        self, generator: ProactiveWarningGenerator, tmp_path: Path
    ) -> None:
        """Test analyzing a file target."""
        # Create a test file
        test_file = tmp_path / "test_code.py"
        test_file.write_text("# Test file\ndef foo(): pass")

        # Update generator root path
        generator.root_path = tmp_path

        result = generator.analyze("test_code.py")

        assert result.target == "test_code.py"
        assert result.target_type == "file"

    def test_security_check_by_name(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test security check triggers on security-related names."""
        # Create mock node with security-related name
        mock_node = MagicMock()
        mock_node.id = "cls:auth.py:AuthService"
        mock_node.name = "AuthService"
        mock_node.type = "class"
        mock_node.file_path = None
        mock_node.complexity = 5

        mock_db.find_by_name = MagicMock(return_value=[mock_node])

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        result = generator.analyze("AuthService")

        # Should have security warning due to "auth" in name
        security_warnings = [w for w in result.warnings if w.category == WarningCategory.SECURITY]
        assert len(security_warnings) > 0

    def test_security_check_by_imports(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test security check triggers on security imports."""
        # Create a file with security imports
        test_file = tmp_path / "crypto_utils.py"
        test_file.write_text("""
import hashlib
import secrets
from cryptography.fernet import Fernet

def encrypt(data):
    pass
""")

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        result = generator.analyze("crypto_utils.py")

        security_warnings = [w for w in result.warnings if w.category == WarningCategory.SECURITY]
        assert len(security_warnings) > 0

    def test_complexity_check(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test complexity warning triggers on high complexity."""
        # Create mock node with high complexity
        mock_node = MagicMock()
        mock_node.id = "fn:code.py:complex_func"
        mock_node.name = "complex_func"
        mock_node.type = "function"
        mock_node.file_path = "code.py"
        mock_node.complexity = 55  # Above error threshold

        mock_db.find_by_name = MagicMock(return_value=[mock_node])

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        result = generator.analyze("complex_func")

        complexity_warnings = [
            w for w in result.warnings if w.category == WarningCategory.COMPLEXITY
        ]
        assert len(complexity_warnings) > 0
        assert complexity_warnings[0].level == "error"

    def test_complexity_warning_level(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test complexity warning (not error) for moderate complexity."""
        mock_node = MagicMock()
        mock_node.id = "fn:code.py:moderate_func"
        mock_node.name = "moderate_func"
        mock_node.type = "function"
        mock_node.file_path = "code.py"
        mock_node.complexity = 25  # Above warn but below error

        mock_db.find_by_name = MagicMock(return_value=[mock_node])

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        result = generator.analyze("moderate_func")

        complexity_warnings = [
            w for w in result.warnings if w.category == WarningCategory.COMPLEXITY
        ]
        assert len(complexity_warnings) > 0
        assert complexity_warnings[0].level == "warn"

    def test_deprecated_check(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test deprecated warning triggers on deprecated marker."""
        # Create a file with deprecation marker
        test_file = tmp_path / "old_code.py"
        test_file.write_text("""
# This module is DEPRECATED - use new_code.py instead

@deprecated
def old_function():
    pass
""")

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        result = generator.analyze("old_code.py")

        deprecated_warnings = [
            w for w in result.warnings if w.category == WarningCategory.DEPRECATED
        ]
        assert len(deprecated_warnings) > 0

    def test_no_tests_check(self, tmp_path: Path) -> None:
        """Test no_tests warning when no test file exists."""
        # Create fresh mock for this test
        mock_db = MagicMock()
        mock_db.conn = MagicMock()
        mock_db.query = MagicMock(return_value={"rows": []})

        # Create source file without test
        src_file = tmp_path / "source_module.py"
        src_file.write_text("def foo(): pass")

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)

        # Directly test _check_tests method since analyze needs full path resolution
        no_test_warnings = generator._check_tests(src_file, [])

        assert len(no_test_warnings) > 0
        assert no_test_warnings[0].category == WarningCategory.NO_TESTS

    def test_no_tests_skip_test_files(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test that test files don't get no_tests warning."""
        # Create a test file
        test_file = tmp_path / "test_module.py"
        test_file.write_text("def test_foo(): pass")

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        result = generator.analyze("test_module.py")

        no_test_warnings = [w for w in result.warnings if w.category == WarningCategory.NO_TESTS]
        assert len(no_test_warnings) == 0

    def test_risk_score_calculation(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test risk score increases with warnings."""
        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)

        # No warnings = 0 score
        result_empty = WarningsResult(target="test", target_type="file")
        assert generator._calculate_risk_score(result_empty.warnings) == 0.0

        # Error warning = higher score
        warnings_with_error = [
            ProactiveWarning(
                category=WarningCategory.HIGH_IMPACT,
                level="error",
                message="test",
            )
        ]
        score = generator._calculate_risk_score(warnings_with_error)
        assert score > 0.3  # Error + high_impact category

    def test_disabled_checks(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test that disabled checks don't produce warnings."""
        config = WarningConfig(
            check_security=False,
            check_tests=False,
        )

        # Create file with security indicators
        test_file = tmp_path / "auth.py"
        test_file.write_text("import hashlib")

        generator = ProactiveWarningGenerator(mock_db, config, tmp_path)
        result = generator.analyze("auth.py")

        # Should have no security or no_tests warnings
        security_warnings = [w for w in result.warnings if w.category == WarningCategory.SECURITY]
        no_tests_warnings = [w for w in result.warnings if w.category == WarningCategory.NO_TESTS]

        assert len(security_warnings) == 0
        assert len(no_tests_warnings) == 0

    def test_summary_generation(self, generator: ProactiveWarningGenerator) -> None:
        """Test summary message generation."""
        # No warnings
        summary = generator._generate_summary([], "test.py")
        assert "no warnings" in summary.lower()

        # Multiple warnings
        warnings = [
            ProactiveWarning(
                category=WarningCategory.HIGH_IMPACT,
                level="error",
                message="impact",
            ),
            ProactiveWarning(
                category=WarningCategory.SECURITY,
                level="warn",
                message="security",
            ),
        ]
        summary = generator._generate_summary(warnings, "test.py")
        assert "error" in summary.lower()
        assert "warning" in summary.lower()


class TestStalenessCheck:
    """Tests for staleness checking with git."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock MUbase."""
        db = MagicMock()
        db.conn = MagicMock()
        db.get_node = MagicMock(return_value=None)
        db.find_by_name = MagicMock(return_value=[])
        db.get_children = MagicMock(return_value=[])
        return db

    def test_staleness_disabled_without_git(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test staleness check gracefully handles missing git."""
        config = WarningConfig(use_git_history=False)

        test_file = tmp_path / "old.py"
        test_file.write_text("# old code")

        generator = ProactiveWarningGenerator(mock_db, config, tmp_path)
        warnings = generator._check_staleness(test_file)

        assert len(warnings) == 0


class TestImpactCheck:
    """Tests for impact checking."""

    def test_impact_with_graph_manager(self) -> None:
        """Test impact check uses GraphManager."""
        mock_db = MagicMock()
        mock_db.conn = MagicMock()

        # Create mock node
        mock_node = MagicMock()
        mock_node.id = "cls:core.py:CoreClass"
        mock_node.name = "CoreClass"

        # Mock GraphManager at the kernel level where it's imported from
        with patch("mu.kernel.graph.GraphManager") as MockGM:
            mock_gm = MockGM.return_value
            mock_gm.has_node.return_value = True
            mock_gm.impact.return_value = [f"dep_{i}" for i in range(15)]

            generator = ProactiveWarningGenerator(mock_db)
            warnings = generator._check_impact([mock_node])

            assert len(warnings) > 0
            assert warnings[0].category == WarningCategory.HIGH_IMPACT


class TestJavaScriptTestDetection:
    """Tests for JavaScript/TypeScript test file detection."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock MUbase."""
        db = MagicMock()
        db.conn = MagicMock()
        db.get_node = MagicMock(return_value=None)
        db.find_by_name = MagicMock(return_value=[])
        db.get_children = MagicMock(return_value=[])
        return db

    def test_typescript_finds_test_file(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test finds *.test.ts file pattern."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)

        source_file = src_dir / "utils.ts"
        test_file = src_dir / "utils.test.ts"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_typescript_finds_spec_file(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test finds *.spec.ts file pattern."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)

        source_file = src_dir / "component.tsx"
        test_file = src_dir / "component.spec.tsx"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_typescript_finds_tests_in_dunder_tests(
        self, mock_db: MagicMock, tmp_path: Path
    ) -> None:
        """Test finds tests in __tests__ directory."""
        src_dir = tmp_path / "src"
        test_dir = src_dir / "__tests__"
        src_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)

        source_file = src_dir / "api.ts"
        test_file = test_dir / "api.ts"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_javascript_warns_when_no_tests(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Verify warning when no JS/TS test file exists."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)

        source_file = src_dir / "module.js"
        source_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 1
        assert warnings[0].category == WarningCategory.NO_TESTS

    def test_typescript_skips_test_files_themselves(
        self, mock_db: MagicMock, tmp_path: Path
    ) -> None:
        """Test files (ending with .test.ts) should not trigger no_tests warning."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)

        test_file = src_dir / "component.test.ts"
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(test_file, [])

        assert len(warnings) == 0


class TestGoTestDetection:
    """Tests for Go test file detection."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock MUbase."""
        db = MagicMock()
        db.conn = MagicMock()
        db.get_node = MagicMock(return_value=None)
        db.find_by_name = MagicMock(return_value=[])
        db.get_children = MagicMock(return_value=[])
        return db

    def test_go_finds_test_file(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test finds *_test.go file pattern."""
        pkg_dir = tmp_path / "pkg" / "handlers"
        pkg_dir.mkdir(parents=True)

        source_file = pkg_dir / "user.go"
        test_file = pkg_dir / "user_test.go"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_go_warns_when_no_tests(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Verify warning when no Go test file exists."""
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir(parents=True)

        source_file = pkg_dir / "main.go"
        source_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 1
        assert warnings[0].category == WarningCategory.NO_TESTS

    def test_go_skips_test_files_themselves(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test files (ending with _test.go) should not trigger no_tests warning."""
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir(parents=True)

        test_file = pkg_dir / "handler_test.go"
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(test_file, [])

        assert len(warnings) == 0


class TestGenericTestDetection:
    """Tests for generic/unknown language test file detection."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock MUbase."""
        db = MagicMock()
        db.conn = MagicMock()
        db.get_node = MagicMock(return_value=None)
        db.find_by_name = MagicMock(return_value=[])
        db.get_children = MagicMock(return_value=[])
        return db

    def test_unknown_language_uses_generic_patterns(
        self, mock_db: MagicMock, tmp_path: Path
    ) -> None:
        """Unknown file extensions should use generic test patterns."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)

        # .rb is Ruby, not in the explicit handlers
        source_file = src_dir / "module.rb"
        test_file = src_dir / "test_module.rb"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_unknown_language_finds_tests_pattern(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Unknown language finds Tests suffix pattern."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)

        source_file = src_dir / "Service.vb"
        test_file = src_dir / "ServiceTests.vb"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_unknown_language_warns_when_no_tests(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Unknown language warns when no test file found."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)

        source_file = src_dir / "script.pl"
        source_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 1
        assert warnings[0].category == WarningCategory.NO_TESTS


class TestCSharpTestDetection:
    """Tests for C#/.NET test file detection - Dominaite regression tests."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create a mock MUbase."""
        db = MagicMock()
        db.conn = MagicMock()
        db.get_node = MagicMock(return_value=None)
        db.find_by_name = MagicMock(return_value=[])
        db.get_children = MagicMock(return_value=[])
        return db

    def test_csharp_finds_tests_in_sibling_test_project(
        self, mock_db: MagicMock, tmp_path: Path
    ) -> None:
        """Dominaite regression: PayoutServiceTests.cs in *.Tests/ project."""
        # Setup: src/Dominaite.Services/PayoutService.cs
        #        src/Dominaite.Services.Tests/PayoutServiceTests.cs
        src_dir = tmp_path / "src" / "Dominaite.Services"
        test_dir = tmp_path / "src" / "Dominaite.Services.Tests"
        src_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)

        source_file = src_dir / "PayoutService.cs"
        test_file = test_dir / "PayoutServiceTests.cs"
        source_file.touch()
        test_file.touch()

        # Test _check_tests directly
        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_csharp_finds_tests_in_nested_directory(
        self, mock_db: MagicMock, tmp_path: Path
    ) -> None:
        """Test file in subdirectory of .Tests project with mirrored structure."""
        # Setup: src/Project/Services/UserService.cs
        #        src/Project.Tests/Services/UserServiceTests.cs
        src_dir = tmp_path / "src" / "Project" / "Services"
        test_dir = tmp_path / "src" / "Project.Tests" / "Services"
        src_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)

        source_file = src_dir / "UserService.cs"
        test_file = test_dir / "UserServiceTests.cs"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_csharp_finds_tests_recursive_search(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test rglob finds tests in non-mirrored directory structure."""
        # Setup: src/Project/PayoutService.cs
        #        src/Project.Tests/Unit/Services/PayoutServiceTests.cs (different structure)
        src_dir = tmp_path / "src" / "Project"
        test_dir = tmp_path / "src" / "Project.Tests" / "Unit" / "Services"
        src_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)

        source_file = src_dir / "PayoutService.cs"
        test_file = test_dir / "PayoutServiceTests.cs"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file via rglob at {test_file}"

    def test_csharp_warns_when_no_tests_exist(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Verify warning when no test file exists."""
        # Setup: src/Project/Service.cs (no .Tests directory)
        src_dir = tmp_path / "src" / "Project"
        src_dir.mkdir(parents=True)

        source_file = src_dir / "Service.cs"
        source_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 1
        assert warnings[0].category == WarningCategory.NO_TESTS

    def test_csharp_skips_test_files_themselves(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Test files (ending with Tests.cs) should not trigger no_tests warning."""
        # Setup: src/Project.Tests/PayoutServiceTests.cs
        test_dir = tmp_path / "src" / "Project.Tests"
        test_dir.mkdir(parents=True)

        test_file = test_dir / "PayoutServiceTests.cs"
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(test_file, [])

        # Should return empty - test files don't need tests
        assert len(warnings) == 0

    def test_csharp_handles_singular_test_suffix(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Handle FooTest.cs (singular) in addition to FooTests.cs (plural)."""
        # Setup: src/Project/Foo.cs
        #        src/Project.Tests/FooTest.cs (singular)
        src_dir = tmp_path / "src" / "Project"
        test_dir = tmp_path / "src" / "Project.Tests"
        src_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)

        source_file = src_dir / "Foo.cs"
        test_file = test_dir / "FooTest.cs"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"

    def test_csharp_deep_nested_project_structure(self, mock_db: MagicMock, tmp_path: Path) -> None:
        """Handle deeply nested project structures."""
        # Setup: src/Solution/Dominaite.Services/Handlers/Payments/PayoutService.cs
        #        src/Solution/Dominaite.Services.Tests/Handlers/Payments/PayoutServiceTests.cs
        src_dir = tmp_path / "src" / "Solution" / "Dominaite.Services" / "Handlers" / "Payments"
        test_dir = (
            tmp_path / "src" / "Solution" / "Dominaite.Services.Tests" / "Handlers" / "Payments"
        )
        src_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)

        source_file = src_dir / "PayoutService.cs"
        test_file = test_dir / "PayoutServiceTests.cs"
        source_file.touch()
        test_file.touch()

        generator = ProactiveWarningGenerator(mock_db, root_path=tmp_path)
        warnings = generator._check_tests(source_file, [])

        assert len(warnings) == 0, f"Should find test file at {test_file}"
