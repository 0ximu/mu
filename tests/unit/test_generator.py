"""Tests for the code generator."""

from __future__ import annotations

import pytest

from mu.intelligence import (
    CodeGenerator,
    GeneratedFile,
    GenerateResult,
    TemplateType,
)
from mu.intelligence.models import Pattern, PatternCategory


class TestTemplateType:
    """Tests for TemplateType enum."""

    def test_all_types_defined(self) -> None:
        """Verify all expected template types exist."""
        expected = [
            "hook",
            "component",
            "service",
            "repository",
            "api_route",
            "test",
            "model",
            "controller",
        ]
        actual = [t.value for t in TemplateType]
        assert sorted(actual) == sorted(expected)

    def test_from_string(self) -> None:
        """Test creating TemplateType from string."""
        assert TemplateType("hook") == TemplateType.HOOK
        assert TemplateType("service") == TemplateType.SERVICE
        assert TemplateType("api_route") == TemplateType.API_ROUTE

    def test_invalid_type_raises(self) -> None:
        """Test that invalid type raises ValueError."""
        with pytest.raises(ValueError):
            TemplateType("invalid")


class TestGeneratedFile:
    """Tests for GeneratedFile dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        file = GeneratedFile(
            path="src/hooks/useAuth.ts",
            content="export function useAuth() {}",
            description="Auth hook",
            is_primary=True,
        )
        result = file.to_dict()

        assert result["path"] == "src/hooks/useAuth.ts"
        assert result["content"] == "export function useAuth() {}"
        assert result["description"] == "Auth hook"
        assert result["is_primary"] is True

    def test_default_is_primary(self) -> None:
        """Test default value for is_primary."""
        file = GeneratedFile(
            path="test.py",
            content="",
            description="Test",
        )
        assert file.is_primary is True


class TestGenerateResult:
    """Tests for GenerateResult dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        result = GenerateResult(
            template_type=TemplateType.HOOK,
            name="useAuth",
            files=[
                GeneratedFile(
                    path="src/hooks/useAuth.ts",
                    content="// hook",
                    description="Hook file",
                    is_primary=True,
                )
            ],
            patterns_used=["hooks_pattern"],
            suggestions=["Add to index.ts"],
        )
        data = result.to_dict()

        assert data["template_type"] == "hook"
        assert data["name"] == "useAuth"
        assert len(data["files"]) == 1
        assert data["patterns_used"] == ["hooks_pattern"]
        assert data["suggestions"] == ["Add to index.ts"]

    def test_primary_file(self) -> None:
        """Test primary_file property."""
        primary = GeneratedFile(
            path="main.ts",
            content="",
            description="Main",
            is_primary=True,
        )
        secondary = GeneratedFile(
            path="test.ts",
            content="",
            description="Test",
            is_primary=False,
        )

        result = GenerateResult(
            template_type=TemplateType.HOOK,
            name="test",
            files=[secondary, primary],
        )
        assert result.primary_file == primary

    def test_primary_file_fallback(self) -> None:
        """Test primary_file falls back to first file."""
        file = GeneratedFile(
            path="test.ts",
            content="",
            description="Test",
            is_primary=False,
        )
        result = GenerateResult(
            template_type=TemplateType.HOOK,
            name="test",
            files=[file],
        )
        assert result.primary_file == file

    def test_primary_file_empty(self) -> None:
        """Test primary_file returns None when no files."""
        result = GenerateResult(
            template_type=TemplateType.HOOK,
            name="test",
            files=[],
        )
        assert result.primary_file is None


class TestCodeGeneratorHelpers:
    """Tests for CodeGenerator helper methods (without MUbase)."""

    def test_to_snake_case(self) -> None:
        """Test snake_case conversion."""
        # Create minimal mock
        class MockDB:
            def stats(self):
                return {}

            def get_nodes(self, _):
                return []

        db = MockDB()
        gen = CodeGenerator(db)  # type: ignore

        assert gen._to_snake_case("UserService") == "user_service"
        assert gen._to_snake_case("HTTPClient") == "http_client"
        assert gen._to_snake_case("useAuth") == "use_auth"
        assert gen._to_snake_case("already_snake") == "already_snake"

    def test_to_pascal_case(self) -> None:
        """Test PascalCase conversion."""

        class MockDB:
            def stats(self):
                return {}

            def get_nodes(self, _):
                return []

        db = MockDB()
        gen = CodeGenerator(db)  # type: ignore

        assert gen._to_pascal_case("user_service") == "UserService"
        assert gen._to_pascal_case("http_client") == "HttpClient"
        assert gen._to_pascal_case("UserService") == "UserService"

    def test_to_camel_case(self) -> None:
        """Test camelCase conversion."""

        class MockDB:
            def stats(self):
                return {}

            def get_nodes(self, _):
                return []

        db = MockDB()
        gen = CodeGenerator(db)  # type: ignore

        assert gen._to_camel_case("UserService") == "userService"
        assert gen._to_camel_case("user_profile") == "userProfile"


class TestCodeGeneratorTemplates:
    """Tests for template generation (with mock patterns)."""

    def setup_method(self) -> None:
        """Set up mock database for tests."""

        class MockDB:
            def stats(self):
                return {"root_path": "/test"}

            def get_nodes(self, node_type):
                return []

            def has_patterns(self):
                return True

            def get_patterns(self, category=None):
                return []

        self.mock_db = MockDB()

    def test_hook_name_normalization(self) -> None:
        """Test that hook names are normalized to start with 'use'."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []  # Skip pattern detection
        gen._language = "typescript"

        result = gen.generate(TemplateType.HOOK, "Auth", {})

        assert result.name == "useAuth"

    def test_hook_with_use_prefix_unchanged(self) -> None:
        """Test that hook names already starting with 'use' are unchanged."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "typescript"

        result = gen.generate(TemplateType.HOOK, "useCustomHook", {})

        assert result.name == "useCustomHook"

    def test_service_name_normalization(self) -> None:
        """Test that service names get 'Service' suffix."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        result = gen.generate(TemplateType.SERVICE, "User", {})

        assert result.name == "UserService"

    def test_service_with_suffix_unchanged(self) -> None:
        """Test that service names already ending with 'Service' are unchanged."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        result = gen.generate(TemplateType.SERVICE, "PaymentService", {})

        assert result.name == "PaymentService"

    def test_repository_name_normalization(self) -> None:
        """Test that repository names get 'Repository' suffix."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        result = gen.generate(TemplateType.REPOSITORY, "User", {})

        assert result.name == "UserRepository"

    def test_controller_name_normalization(self) -> None:
        """Test that controller names get 'Controller' suffix."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        result = gen.generate(TemplateType.CONTROLLER, "User", {})

        assert result.name == "UserController"

    def test_generates_primary_file(self) -> None:
        """Test that generation produces at least one primary file."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        result = gen.generate(TemplateType.SERVICE, "Test", {})

        assert len(result.files) >= 1
        assert any(f.is_primary for f in result.files)

    def test_typescript_hook_content(self) -> None:
        """Test TypeScript hook content structure."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "typescript"

        result = gen.generate(TemplateType.HOOK, "useAuth", {})
        primary = result.primary_file

        assert primary is not None
        assert "import {" in primary.content
        assert "useState" in primary.content
        assert "useCallback" in primary.content
        assert "export function useAuth" in primary.content

    def test_python_service_content(self) -> None:
        """Test Python service content structure."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        result = gen.generate(TemplateType.SERVICE, "User", {})
        primary = result.primary_file

        assert primary is not None
        assert "@dataclass" in primary.content
        assert "class UserService:" in primary.content
        assert "def get(" in primary.content
        assert "def create(" in primary.content

    def test_model_with_fields(self) -> None:
        """Test model generation with custom fields."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        fields = [
            {"name": "email", "type": "str"},
            {"name": "age", "type": "int"},
        ]
        result = gen.generate(TemplateType.MODEL, "User", {"fields": fields})
        primary = result.primary_file

        assert primary is not None
        assert "email: str" in primary.content
        assert "age: int" in primary.content

    def test_api_route_python(self) -> None:
        """Test Python API route generation."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        result = gen.generate(TemplateType.API_ROUTE, "users", {})
        primary = result.primary_file

        assert primary is not None
        assert "router = APIRouter" in primary.content
        assert "@router.get" in primary.content
        assert "@router.post" in primary.content

    def test_api_route_typescript(self) -> None:
        """Test TypeScript API route generation (Next.js style)."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "typescript"

        result = gen.generate(TemplateType.API_ROUTE, "users", {})
        primary = result.primary_file

        assert primary is not None
        assert "NextRequest" in primary.content
        assert "NextResponse" in primary.content
        assert "export async function GET" in primary.content
        assert "export async function POST" in primary.content

    def test_test_file_python(self) -> None:
        """Test Python test file generation."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        result = gen.generate(TemplateType.TEST, "auth", {})

        assert "test_" in result.name
        primary = result.primary_file
        assert primary is not None
        assert "import pytest" in primary.content or "class Test" in primary.content

    def test_test_file_typescript(self) -> None:
        """Test TypeScript test file generation."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "typescript"

        result = gen.generate(TemplateType.TEST, "auth", {})
        primary = result.primary_file

        assert primary is not None
        assert "describe(" in primary.content
        assert "it(" in primary.content

    def test_invalid_template_type_raises(self) -> None:
        """Test that invalid template type raises ValueError."""
        gen = CodeGenerator(self.mock_db)  # type: ignore
        gen._patterns = []
        gen._language = "python"

        with pytest.raises(ValueError):
            gen.generate("invalid_type", "Test", {})


class TestLanguageDetection:
    """Tests for language detection."""

    def test_detects_python_from_patterns(self) -> None:
        """Test Python detection from file extension pattern."""

        class MockDB:
            def stats(self):
                return {}

            def get_nodes(self, _):
                return []

        gen = CodeGenerator(MockDB())  # type: ignore
        gen._patterns = [
            Pattern(
                name="file_extension_py",
                category=PatternCategory.NAMING,
                description="Python files",
                frequency=100,
                confidence=0.9,
            )
        ]

        assert gen._detect_language() == "python"

    def test_detects_typescript_from_patterns(self) -> None:
        """Test TypeScript detection from file extension pattern."""

        class MockDB:
            def stats(self):
                return {}

            def get_nodes(self, _):
                return []

        gen = CodeGenerator(MockDB())  # type: ignore
        gen._patterns = [
            Pattern(
                name="file_extension_ts",
                category=PatternCategory.NAMING,
                description="TypeScript files",
                frequency=100,
                confidence=0.9,
            )
        ]

        assert gen._detect_language() == "typescript"

    def test_default_to_python(self) -> None:
        """Test default language is Python when no patterns detected."""

        class MockDB:
            def stats(self):
                return {}

            def get_nodes(self, _):
                return []

        gen = CodeGenerator(MockDB())  # type: ignore
        gen._patterns = []

        assert gen._detect_language() == "python"
