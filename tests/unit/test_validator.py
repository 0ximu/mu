"""Tests for the ChangeValidator - pre-commit pattern validation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mu.intelligence.models import Pattern, PatternCategory
from mu.intelligence.validator import (
    ChangeValidator,
    ChangedFile,
    ValidationResult,
    Violation,
    ViolationSeverity,
)


class TestViolation:
    """Tests for Violation dataclass."""

    def test_to_dict(self):
        """Test violation serialization."""
        violation = Violation(
            file_path="src/service.py",
            line_start=10,
            line_end=10,
            severity=ViolationSeverity.WARNING,
            rule="snake_case_functions",
            message="Function uses camelCase",
            suggestion="Rename to snake_case",
            pattern_category="naming",
        )
        result = violation.to_dict()

        assert result["file_path"] == "src/service.py"
        assert result["line_start"] == 10
        assert result["severity"] == "warning"
        assert result["rule"] == "snake_case_functions"
        assert result["message"] == "Function uses camelCase"
        assert result["suggestion"] == "Rename to snake_case"

    def test_severity_levels(self):
        """Test all severity levels."""
        assert ViolationSeverity.ERROR.value == "error"
        assert ViolationSeverity.WARNING.value == "warning"
        assert ViolationSeverity.INFO.value == "info"


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_empty_result_is_valid(self):
        """Test that empty result is valid."""
        result = ValidationResult(valid=True)
        assert result.valid
        assert result.violations == []
        assert result.error_count == 0

    def test_result_with_violations(self):
        """Test result with violations."""
        violations = [
            Violation(
                file_path="test.py",
                line_start=1,
                line_end=1,
                severity=ViolationSeverity.ERROR,
                rule="test",
                message="Error",
            ),
            Violation(
                file_path="test.py",
                line_start=2,
                line_end=2,
                severity=ViolationSeverity.WARNING,
                rule="test",
                message="Warning",
            ),
        ]
        result = ValidationResult(
            valid=False,
            violations=violations,
            error_count=1,
            warning_count=1,
        )

        assert not result.valid
        assert len(result.violations) == 2
        assert result.error_count == 1
        assert result.warning_count == 1

    def test_to_dict(self):
        """Test result serialization."""
        result = ValidationResult(
            valid=True,
            patterns_checked=["snake_case_functions"],
            files_checked=["test.py"],
            validation_time_ms=10.5,
        )
        data = result.to_dict()

        assert data["valid"] is True
        assert data["patterns_checked"] == ["snake_case_functions"]
        assert data["files_checked"] == ["test.py"]
        assert data["validation_time_ms"] == 10.5


class TestChangedFile:
    """Tests for ChangedFile dataclass."""

    def test_basic_creation(self):
        """Test creating a changed file."""
        cf = ChangedFile(
            path="src/test.py",
            status="M",
            content="def test(): pass",
            added_lines=[(1, "def test(): pass")],
        )
        assert cf.path == "src/test.py"
        assert cf.status == "M"
        assert len(cf.added_lines) == 1


class TestChangeValidator:
    """Tests for ChangeValidator class."""

    @pytest.fixture
    def mock_mubase(self):
        """Create a mock MUbase."""
        mubase = MagicMock()
        mubase.stats.return_value = {"root_path": "/tmp/test_project"}
        mubase.has_patterns.return_value = True
        mubase.get_patterns.return_value = [
            Pattern(
                name="snake_case_functions",
                category=PatternCategory.NAMING,
                description="Functions use snake_case",
                frequency=100,
                confidence=0.9,
            ),
            Pattern(
                name="service_layer",
                category=PatternCategory.ARCHITECTURE,
                description="Service layer pattern",
                frequency=10,
                confidence=0.9,
            ),
            Pattern(
                name="repository_pattern",
                category=PatternCategory.ARCHITECTURE,
                description="Repository pattern",
                frequency=5,
                confidence=0.9,
            ),
            Pattern(
                name="test_function_naming",
                category=PatternCategory.TESTING,
                description="Test functions use test_ prefix",
                frequency=50,
                confidence=0.9,
            ),
        ]
        return mubase

    def test_validate_empty_changes(self, mock_mubase):
        """Test validation with no changes."""
        validator = ChangeValidator(mock_mubase)

        with patch.object(validator, "_get_all_changes", return_value=[]):
            result = validator.validate()

        assert result.valid
        assert len(result.violations) == 0
        assert len(result.patterns_checked) > 0

    def test_validate_specific_files(self, mock_mubase, tmp_path):
        """Test validation of specific files."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def myFunction():\n    pass")

        mock_mubase.stats.return_value = {"root_path": str(tmp_path)}
        validator = ChangeValidator(mock_mubase)

        result = validator.validate(files=["test.py"])

        assert len(result.files_checked) == 1
        # Should have a snake_case violation
        naming_violations = [v for v in result.violations if v.rule == "snake_case_functions"]
        assert len(naming_violations) == 1
        assert "myFunction" in naming_violations[0].message

    def test_snake_case_validation(self, mock_mubase):
        """Test snake_case function naming validation."""
        validator = ChangeValidator(mock_mubase)
        validator._root_path = Path("/tmp")
        validator._patterns = mock_mubase.get_patterns()

        # Create a changed file with camelCase function
        changed_file = ChangedFile(
            path="service.py",
            status="M",
            content="def getUserById(id):\n    pass",
            added_lines=[(1, "def getUserById(id):")],
        )

        violations = validator._check_naming_patterns(changed_file)

        assert len(violations) == 1
        assert violations[0].severity == ViolationSeverity.WARNING
        assert violations[0].rule == "snake_case_functions"
        assert "getUserById" in violations[0].message
        assert "get_user_by_id" in violations[0].suggestion

    def test_snake_case_ignores_dunder_methods(self, mock_mubase):
        """Test that dunder methods are not flagged."""
        validator = ChangeValidator(mock_mubase)
        validator._root_path = Path("/tmp")
        validator._patterns = mock_mubase.get_patterns()

        changed_file = ChangedFile(
            path="model.py",
            status="M",
            content="def __init__(self):\n    pass",
            added_lines=[(1, "def __init__(self):")],
        )

        violations = validator._check_naming_patterns(changed_file)
        assert len(violations) == 0

    def test_architecture_validation_service_db_access(self, mock_mubase):
        """Test that services using direct DB access get flagged."""
        validator = ChangeValidator(mock_mubase)
        validator._root_path = Path("/tmp")
        validator._patterns = mock_mubase.get_patterns()

        changed_file = ChangedFile(
            path="user_service.py",
            status="M",
            content="session = Session()\nresult = session.execute(query)",
            added_lines=[
                (1, "session = Session()"),
                (2, "result = session.execute(query)"),
            ],
        )

        violations = validator._check_architecture_patterns(changed_file)

        # Should flag both Session() and .execute()
        assert len(violations) >= 1
        assert any("Service" in v.message or "execute" in v.message for v in violations)

    def test_test_function_naming_validation(self, mock_mubase):
        """Test that test functions without test_ prefix are flagged."""
        validator = ChangeValidator(mock_mubase)
        validator._root_path = Path("/tmp")
        validator._patterns = mock_mubase.get_patterns()

        changed_file = ChangedFile(
            path="test_user.py",
            status="M",
            content="def verify_user_creation():\n    pass",
            added_lines=[(1, "def verify_user_creation():")],
        )

        violations = validator._check_testing_patterns(changed_file)

        assert len(violations) == 1
        assert violations[0].rule == "test_function_naming"
        assert "verify_user_creation" in violations[0].message

    def test_test_function_allows_helpers(self, mock_mubase):
        """Test that helper/fixture functions are not flagged."""
        validator = ChangeValidator(mock_mubase)
        validator._root_path = Path("/tmp")
        validator._patterns = mock_mubase.get_patterns()

        changed_file = ChangedFile(
            path="test_user.py",
            status="M",
            content="def setup_test_data():\n    pass",
            added_lines=[(1, "def setup_test_data():")],
        )

        violations = validator._check_testing_patterns(changed_file)
        assert len(violations) == 0

    def test_import_star_validation(self, mock_mubase):
        """Test that star imports are flagged."""
        mock_mubase.get_patterns.return_value = [
            Pattern(
                name="modular_imports",
                category=PatternCategory.IMPORTS,
                description="Modular imports",
                frequency=100,
                confidence=0.8,
            ),
        ]

        validator = ChangeValidator(mock_mubase)
        validator._root_path = Path("/tmp")
        validator._patterns = mock_mubase.get_patterns()

        changed_file = ChangedFile(
            path="module.py",
            status="M",
            content="from utils import *",
            added_lines=[(1, "from utils import *")],
        )

        violations = validator._check_import_patterns(changed_file)

        assert len(violations) == 1
        assert violations[0].rule == "no_star_imports"
        assert "Star imports" in violations[0].message

    def test_to_snake_case_conversion(self, mock_mubase):
        """Test camelCase to snake_case conversion."""
        validator = ChangeValidator(mock_mubase)

        assert validator._to_snake_case("getUserById") == "get_user_by_id"
        assert validator._to_snake_case("HTTPResponse") == "http_response"
        assert validator._to_snake_case("simpleTest") == "simple_test"
        assert validator._to_snake_case("ABC") == "abc"

    def test_category_filter(self, mock_mubase):
        """Test that category filter works."""
        # Update mock to return only naming patterns when category is specified
        mock_mubase.get_patterns.side_effect = lambda cat=None: [
            Pattern(
                name="snake_case_functions",
                category=PatternCategory.NAMING,
                description="Functions use snake_case",
                frequency=100,
                confidence=0.9,
            ),
        ] if cat == "naming" else mock_mubase.get_patterns.return_value

        validator = ChangeValidator(mock_mubase)

        with patch.object(validator, "_get_all_changes", return_value=[]):
            result = validator.validate(category=PatternCategory.NAMING)

        # Validation should complete successfully
        assert result.valid
        assert len(result.files_checked) == 0


class TestGitIntegration:
    """Tests for git-related functionality."""

    def test_parse_diff_for_added_lines(self):
        """Test parsing unified diff format."""
        mubase = MagicMock()
        mubase.stats.return_value = {}
        mubase.has_patterns.return_value = False

        validator = ChangeValidator(mubase)

        diff_output = """--- a/test.py
+++ b/test.py
@@ -1,3 +1,5 @@
 def existing():
     pass
+
+def new_function():
+    return True"""

        added_lines = validator._parse_diff_for_added_lines(diff_output)

        # Should have 3 added lines: empty line and 2 for new function
        assert len(added_lines) == 3
        # Line numbers: the hunk starts at +1, after 2 context lines (lines 1,2)
        # the added lines are at positions 3, 4, 5
        assert added_lines[0][0] == 3  # Empty line
        assert added_lines[1][0] == 4  # def new_function():
        assert added_lines[2][0] == 5  # return True

    def test_parse_porcelain_status(self):
        """Test parsing git status --porcelain output."""
        mubase = MagicMock()
        mubase.stats.return_value = {}
        mubase.has_patterns.return_value = False

        validator = ChangeValidator(mubase)
        validator._root_path = Path("/tmp")

        status_output = """M  src/modified.py
A  src/added.py
D  src/deleted.py
?? src/untracked.py
R  old.py -> new.py"""

        with patch.object(validator, "_create_changed_file") as mock_create:
            mock_create.return_value = ChangedFile(path="test", status="M")
            files = validator._parse_porcelain_status(status_output)

        # Should not include deleted file
        assert mock_create.call_count == 4
        # Check that deleted file was skipped
        call_paths = [call[0][0] for call in mock_create.call_args_list]
        assert "src/deleted.py" not in call_paths


class TestMCPIntegration:
    """Tests for MCP tool integration."""

    def test_mu_validate_import(self):
        """Test that mu_validate is properly exported."""
        from mu.mcp.server import mu_validate, ValidateOutput, ViolationInfo

        assert callable(mu_validate)
        assert ValidateOutput is not None
        assert ViolationInfo is not None

    def test_intelligence_module_exports(self):
        """Test that validator classes are exported from intelligence module."""
        from mu.intelligence import (
            ChangeValidator,
            ChangedFile,
            ValidationResult,
            Violation,
            ViolationSeverity,
        )

        assert ChangeValidator is not None
        assert ChangedFile is not None
        assert ValidationResult is not None
        assert Violation is not None
        assert ViolationSeverity is not None
