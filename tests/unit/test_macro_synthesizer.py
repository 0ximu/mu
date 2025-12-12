"""Tests for MacroSynthesizer - OMEGA macro synthesis from patterns."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mu.extras.intelligence.models import (
    MacroDefinition,
    MacroTier,
    Pattern,
    PatternCategory,
    PatternsResult,
    SynthesisResult,
)
from mu.extras.intelligence.synthesizer import (
    PATTERN_TO_MACRO_MAP,
    MacroSynthesizer,
)
from mu.kernel import MUbase, Node, NodeType

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create temporary database path."""
    return tmp_path / "test.mubase"


@pytest.fixture
def db(db_path: Path) -> MUbase:
    """Create database instance with context manager."""
    database = MUbase(db_path)
    yield database
    database.close()


@pytest.fixture
def synthesizer(db: MUbase) -> MacroSynthesizer:
    """Create MacroSynthesizer instance."""
    return MacroSynthesizer(db)


# =============================================================================
# MacroDefinition Tests
# =============================================================================


class TestMacroDefinition:
    """Tests for MacroDefinition dataclass."""

    def test_to_lisp_def_simple(self) -> None:
        """to_lisp_def generates valid defmacro form."""
        macro = MacroDefinition(
            name="api",
            tier=MacroTier.STANDARD,
            signature=["method", "path", "name", "params"],
            description="REST API endpoint handler",
            pattern_source="http_method_handlers",
            frequency=42,
            expansion_template="(defn {name} [{params}] -> Response)",
        )

        result = macro.to_lisp_def()

        assert "(defmacro api [method path name params]" in result
        assert '"REST API endpoint handler"' in result

    def test_to_lisp_def_single_param(self) -> None:
        """to_lisp_def works with single parameter."""
        macro = MacroDefinition(
            name="test",
            tier=MacroTier.STANDARD,
            signature=["name"],
            description="Test function",
            pattern_source="test_prefix",
            frequency=10,
            expansion_template="(defn test_{name} [])",
        )

        result = macro.to_lisp_def()

        assert "(defmacro test [name]" in result

    def test_apply_simple(self) -> None:
        """apply produces correct macro invocation for simple values."""
        macro = MacroDefinition(
            name="api",
            tier=MacroTier.STANDARD,
            signature=["method", "path", "name"],
            description="REST API endpoint",
            pattern_source="http_method_handlers",
            frequency=10,
            expansion_template="...",
        )

        result = macro.apply({"method": "GET", "path": "/users", "name": "get_users"})

        assert result == "(api GET /users get_users)"

    def test_apply_with_spaces_quotes_value(self) -> None:
        """apply quotes values containing spaces."""
        macro = MacroDefinition(
            name="api",
            tier=MacroTier.STANDARD,
            signature=["method", "path", "name"],
            description="REST API endpoint",
            pattern_source="http_method_handlers",
            frequency=10,
            expansion_template="...",
        )

        result = macro.apply({"method": "GET", "path": "/users/{id}", "name": "get user"})

        assert '(api GET /users/{id} "get user")' == result

    def test_apply_with_list(self) -> None:
        """apply formats list parameters correctly."""
        macro = MacroDefinition(
            name="model",
            tier=MacroTier.STANDARD,
            signature=["name", "fields"],
            description="Data model",
            pattern_source="model_layer",
            frequency=10,
            expansion_template="(data {name} [{fields}])",
        )

        result = macro.apply({"name": "User", "fields": ["id", "name", "email"]})

        assert result == "(model User [id name email])"

    def test_apply_with_empty_list(self) -> None:
        """apply handles empty lists."""
        macro = MacroDefinition(
            name="hook",
            tier=MacroTier.STANDARD,
            signature=["name", "deps"],
            description="React hook",
            pattern_source="hooks_pattern",
            frequency=10,
            expansion_template="...",
        )

        result = macro.apply({"name": "useAuth", "deps": []})

        assert result == "(hook useAuth [])"

    def test_apply_with_missing_param(self) -> None:
        """apply uses '_' for missing parameters."""
        macro = MacroDefinition(
            name="api",
            tier=MacroTier.STANDARD,
            signature=["method", "path", "name"],
            description="REST API endpoint",
            pattern_source="http_method_handlers",
            frequency=10,
            expansion_template="...",
        )

        result = macro.apply({"method": "GET"})

        assert result == "(api GET _ _)"

    def test_to_dict(self) -> None:
        """to_dict serializes all fields correctly."""
        macro = MacroDefinition(
            name="service",
            tier=MacroTier.STANDARD,
            signature=["name", "deps"],
            description="Service class",
            pattern_source="service_layer",
            frequency=25,
            expansion_template="(class {name}Service ...)",
            token_savings=150,
        )

        d = macro.to_dict()

        assert d["name"] == "service"
        assert d["tier"] == "standard"
        assert d["signature"] == ["name", "deps"]
        assert d["description"] == "Service class"
        assert d["pattern_source"] == "service_layer"
        assert d["frequency"] == 25
        assert d["token_savings"] == 150

    def test_from_dict(self) -> None:
        """from_dict deserializes correctly."""
        data = {
            "name": "hook",
            "tier": "synthesized",
            "signature": ["name", "deps"],
            "description": "Custom hook",
            "pattern_source": "hooks_pattern",
            "frequency": 15,
            "expansion_template": "(defn use{name} ...)",
            "token_savings": 75,
        }

        macro = MacroDefinition.from_dict(data)

        assert macro.name == "hook"
        assert macro.tier == MacroTier.SYNTHESIZED
        assert macro.signature == ["name", "deps"]
        assert macro.frequency == 15
        assert macro.token_savings == 75


class TestSynthesisResult:
    """Tests for SynthesisResult dataclass."""

    def test_get_header_empty(self) -> None:
        """get_header handles empty macro list."""
        result = SynthesisResult()

        header = result.get_header()

        assert header == ";; MU-Lisp Macro Definitions"

    def test_get_header_with_macros(self) -> None:
        """get_header groups macros by tier."""
        macros = [
            MacroDefinition(
                name="api",
                tier=MacroTier.STANDARD,
                signature=["method", "path"],
                description="REST endpoint",
                pattern_source="api",
                frequency=10,
                expansion_template="...",
            ),
            MacroDefinition(
                name="custom",
                tier=MacroTier.SYNTHESIZED,
                signature=["name"],
                description="Custom pattern",
                pattern_source="custom",
                frequency=20,
                expansion_template="...",
            ),
        ]
        result = SynthesisResult(macros=macros)

        header = result.get_header()

        assert ";; Standard (cross-codebase)" in header
        assert "(defmacro api" in header
        assert ";; Synthesized (this codebase)" in header
        assert "(defmacro custom" in header

    def test_get_header_ordering(self) -> None:
        """get_header orders macros: CORE -> STANDARD -> SYNTHESIZED."""
        macros = [
            MacroDefinition(
                name="synthesized_one",
                tier=MacroTier.SYNTHESIZED,
                signature=["x"],
                description="Synth",
                pattern_source="p",
                frequency=1,
                expansion_template="...",
            ),
            MacroDefinition(
                name="standard_one",
                tier=MacroTier.STANDARD,
                signature=["x"],
                description="Std",
                pattern_source="p",
                frequency=1,
                expansion_template="...",
            ),
            MacroDefinition(
                name="core_one",
                tier=MacroTier.CORE,
                signature=["x"],
                description="Core",
                pattern_source="p",
                frequency=1,
                expansion_template="...",
            ),
        ]
        result = SynthesisResult(macros=macros)

        header = result.get_header()

        # Core should come before Standard
        core_pos = header.find("core_one")
        standard_pos = header.find("standard_one")
        synth_pos = header.find("synthesized_one")

        assert core_pos < standard_pos < synth_pos

    def test_to_dict(self) -> None:
        """to_dict serializes result correctly."""
        result = SynthesisResult(
            macros=[],
            total_patterns_analyzed=50,
            patterns_converted=5,
            estimated_compression=0.35,
            synthesis_time_ms=125.5,
        )

        d = result.to_dict()

        assert d["total_patterns_analyzed"] == 50
        assert d["patterns_converted"] == 5
        assert d["estimated_compression"] == 0.35
        assert d["synthesis_time_ms"] == 125.5

    def test_from_dict(self) -> None:
        """from_dict deserializes correctly."""
        data = {
            "macros": [],
            "total_patterns_analyzed": 30,
            "patterns_converted": 3,
            "estimated_compression": 0.25,
            "synthesis_time_ms": 50.0,
        }

        result = SynthesisResult.from_dict(data)

        assert result.total_patterns_analyzed == 30
        assert result.patterns_converted == 3
        assert result.estimated_compression == 0.25

    def test_macro_count_properties(self) -> None:
        """Count properties return correct values."""
        macros = [
            MacroDefinition(
                name="a",
                tier=MacroTier.CORE,
                signature=[],
                description="",
                pattern_source="",
                frequency=0,
                expansion_template="",
            ),
            MacroDefinition(
                name="b",
                tier=MacroTier.STANDARD,
                signature=[],
                description="",
                pattern_source="",
                frequency=0,
                expansion_template="",
            ),
            MacroDefinition(
                name="c",
                tier=MacroTier.STANDARD,
                signature=[],
                description="",
                pattern_source="",
                frequency=0,
                expansion_template="",
            ),
            MacroDefinition(
                name="d",
                tier=MacroTier.SYNTHESIZED,
                signature=[],
                description="",
                pattern_source="",
                frequency=0,
                expansion_template="",
            ),
        ]
        result = SynthesisResult(macros=macros)

        assert result.macro_count == 4
        assert result.core_count == 1
        assert result.standard_count == 2
        assert result.synthesized_count == 1


# =============================================================================
# MacroSynthesizer Tests
# =============================================================================


class TestMacroSynthesizer:
    """Tests for MacroSynthesizer class."""

    def test_init(self, db: MUbase) -> None:
        """MacroSynthesizer initializes correctly."""
        synthesizer = MacroSynthesizer(db)

        assert synthesizer.db is db
        assert synthesizer._pattern_detector is None

    def test_standard_macros_defined(self) -> None:
        """Standard macros are pre-defined."""
        assert "api" in MacroSynthesizer.STANDARD_MACROS
        assert "component" in MacroSynthesizer.STANDARD_MACROS
        assert "hook" in MacroSynthesizer.STANDARD_MACROS
        assert "test" in MacroSynthesizer.STANDARD_MACROS
        assert "model" in MacroSynthesizer.STANDARD_MACROS
        assert "service" in MacroSynthesizer.STANDARD_MACROS
        assert "repo" in MacroSynthesizer.STANDARD_MACROS

    def test_pattern_to_macro_map_exists(self) -> None:
        """Pattern-to-macro mapping is defined."""
        assert "http_method_handlers" in PATTERN_TO_MACRO_MAP
        assert "hooks_pattern" in PATTERN_TO_MACRO_MAP
        assert "test_function_naming" in PATTERN_TO_MACRO_MAP

    def test_synthesize_empty_patterns(self, synthesizer: MacroSynthesizer) -> None:
        """synthesize handles empty pattern results."""
        mock_detector = MagicMock()
        mock_detector.detect.return_value = PatternsResult(
            patterns=[],
            total_patterns=0,
        )
        synthesizer._pattern_detector = mock_detector

        result = synthesizer.synthesize()

        assert result.macro_count == 0
        assert result.total_patterns_analyzed == 0
        assert result.patterns_converted == 0

    def test_synthesize_matches_api_pattern(self, synthesizer: MacroSynthesizer) -> None:
        """synthesize matches API patterns to standard macro."""
        api_pattern = Pattern(
            name="http_method_handlers",
            category=PatternCategory.API,
            description="HTTP method handlers",
            frequency=20,  # Above MIN_PATTERN_FREQUENCY
            confidence=0.9,
        )

        mock_detector = MagicMock()
        mock_detector.detect.return_value = PatternsResult(
            patterns=[api_pattern],
            total_patterns=1,
        )
        synthesizer._pattern_detector = mock_detector

        result = synthesizer.synthesize()

        # Should match to standard "api" macro
        api_macros = [m for m in result.macros if m.name == "api"]
        assert len(api_macros) == 1
        assert api_macros[0].tier == MacroTier.STANDARD
        assert api_macros[0].frequency == 20

    def test_synthesize_matches_component_pattern(self, synthesizer: MacroSynthesizer) -> None:
        """synthesize matches component patterns to standard macro."""
        component_pattern = Pattern(
            name="component_classes",
            category=PatternCategory.COMPONENTS,
            description="React components",
            frequency=15,
            confidence=0.85,
        )

        mock_detector = MagicMock()
        mock_detector.detect.return_value = PatternsResult(
            patterns=[component_pattern],
            total_patterns=1,
        )
        synthesizer._pattern_detector = mock_detector

        result = synthesizer.synthesize()

        component_macros = [m for m in result.macros if m.name == "component"]
        assert len(component_macros) == 1

    def test_synthesize_respects_max_limit(self, synthesizer: MacroSynthesizer) -> None:
        """synthesize respects MAX_SYNTHESIZED_MACROS limit."""
        # Create many patterns that don't map to standard macros
        patterns = [
            Pattern(
                name=f"custom_pattern_{i}",
                category=PatternCategory.ARCHITECTURE,
                description=f"Custom pattern {i}",
                frequency=50,  # High frequency
                confidence=0.9,
            )
            for i in range(10)
        ]

        mock_detector = MagicMock()
        mock_detector.detect.return_value = PatternsResult(
            patterns=patterns,
            total_patterns=10,
        )
        synthesizer._pattern_detector = mock_detector

        result = synthesizer.synthesize(max_synthesized=3)

        # Should respect limit for synthesized macros
        synthesized = [m for m in result.macros if m.tier == MacroTier.SYNTHESIZED]
        assert len(synthesized) <= 3

    def test_synthesize_filters_low_frequency(self, synthesizer: MacroSynthesizer) -> None:
        """synthesize filters patterns below MIN_PATTERN_FREQUENCY."""
        low_freq_pattern = Pattern(
            name="http_method_handlers",
            category=PatternCategory.API,
            description="Low frequency API",
            frequency=3,  # Below MIN_PATTERN_FREQUENCY (10)
            confidence=0.9,
        )

        mock_detector = MagicMock()
        mock_detector.detect.return_value = PatternsResult(
            patterns=[low_freq_pattern],
            total_patterns=1,
        )
        synthesizer._pattern_detector = mock_detector

        result = synthesizer.synthesize()

        # Should not create macro for low frequency pattern
        assert result.macro_count == 0

    def test_synthesize_exclude_standard(self, synthesizer: MacroSynthesizer) -> None:
        """synthesize can exclude standard macros."""
        api_pattern = Pattern(
            name="http_method_handlers",
            category=PatternCategory.API,
            description="HTTP method handlers",
            frequency=20,
            confidence=0.9,
        )

        mock_detector = MagicMock()
        mock_detector.detect.return_value = PatternsResult(
            patterns=[api_pattern],
            total_patterns=1,
        )
        synthesizer._pattern_detector = mock_detector

        result = synthesizer.synthesize(include_standard=False)

        # Should not include standard macros
        standard_macros = [m for m in result.macros if m.tier == MacroTier.STANDARD]
        assert len(standard_macros) == 0

    def test_calculate_token_savings(self, synthesizer: MacroSynthesizer) -> None:
        """Token savings calculation is correct."""
        # Create a macro with known properties
        macro = MacroDefinition(
            name="api",
            tier=MacroTier.STANDARD,
            signature=["method", "path", "name", "params"],  # 4 params
            description="REST API endpoint handler",  # ~30 chars
            pattern_source="http_method_handlers",
            frequency=40,
            expansion_template='(defn {name} [{params}] -> Response :decorators [app.{method}("{path}")])',  # ~70 chars
        )

        savings = synthesizer._calculate_token_savings(macro)

        # Should have positive savings for high-frequency macro
        assert savings > 0

    def test_calculate_token_savings_break_even(self, synthesizer: MacroSynthesizer) -> None:
        """Token savings rejects macros that don't meet threshold."""
        # Create a macro with low frequency that won't pay off
        macro = MacroDefinition(
            name="rarely_used",
            tier=MacroTier.SYNTHESIZED,
            signature=["a", "b", "c"],  # 3 params
            description="A rarely used macro that costs more than it saves",
            pattern_source="rare_pattern",
            frequency=2,  # Very low frequency
            expansion_template="(defn {a} [{b}] -> {c})",  # Short template
        )

        savings = synthesizer._calculate_token_savings(macro)

        # Should be 0 or very low - macro doesn't pay for itself
        assert savings < synthesizer.MIN_NET_SAVINGS


class TestMacroSynthesizerPatternMatching:
    """Tests for pattern matching in MacroSynthesizer."""

    def test_get_applicable_macros_api(self, db: MUbase) -> None:
        """get_applicable_macros identifies API functions."""
        synthesizer = MacroSynthesizer(db)

        # Create a function node with API decorator
        node = Node(
            id="fn:test.py:get_users",
            type=NodeType.FUNCTION,
            name="get_users",
            file_path="test.py",
            properties={"decorators": ["app.get('/users')"]},
        )

        api_macro = MacroSynthesizer.STANDARD_MACROS["api"]
        macros = [api_macro]

        result = synthesizer.get_applicable_macros(node, macros)

        assert result is not None
        assert result.name == "api"

    def test_get_applicable_macros_hook(self, db: MUbase) -> None:
        """get_applicable_macros identifies React hooks."""
        synthesizer = MacroSynthesizer(db)

        node = Node(
            id="fn:hooks.ts:useAuth",
            type=NodeType.FUNCTION,
            name="useAuth",
            file_path="hooks.ts",
            properties={},
        )

        hook_macro = MacroSynthesizer.STANDARD_MACROS["hook"]
        macros = [hook_macro]

        result = synthesizer.get_applicable_macros(node, macros)

        assert result is not None
        assert result.name == "hook"

    def test_get_applicable_macros_test(self, db: MUbase) -> None:
        """get_applicable_macros identifies test functions."""
        synthesizer = MacroSynthesizer(db)

        node = Node(
            id="fn:test_auth.py:test_login",
            type=NodeType.FUNCTION,
            name="test_login",
            file_path="test_auth.py",
            properties={},
        )

        test_macro = MacroSynthesizer.STANDARD_MACROS["test"]
        macros = [test_macro]

        result = synthesizer.get_applicable_macros(node, macros)

        assert result is not None
        assert result.name == "test"

    def test_get_applicable_macros_service(self, db: MUbase) -> None:
        """get_applicable_macros identifies service classes."""
        synthesizer = MacroSynthesizer(db)

        node = Node(
            id="cls:auth.py:AuthService",
            type=NodeType.CLASS,
            name="AuthService",
            file_path="auth.py",
            properties={},
        )

        service_macro = MacroSynthesizer.STANDARD_MACROS["service"]
        macros = [service_macro]

        result = synthesizer.get_applicable_macros(node, macros)

        assert result is not None
        assert result.name == "service"

    def test_get_applicable_macros_model_dataclass(self, db: MUbase) -> None:
        """get_applicable_macros identifies dataclass models."""
        synthesizer = MacroSynthesizer(db)

        node = Node(
            id="cls:models.py:User",
            type=NodeType.CLASS,
            name="User",
            file_path="models.py",
            properties={"decorators": ["dataclass"]},
        )

        model_macro = MacroSynthesizer.STANDARD_MACROS["model"]
        macros = [model_macro]

        result = synthesizer.get_applicable_macros(node, macros)

        assert result is not None
        assert result.name == "model"

    def test_get_applicable_macros_no_match(self, db: MUbase) -> None:
        """get_applicable_macros returns None for non-matching nodes."""
        synthesizer = MacroSynthesizer(db)

        # A generic function that doesn't match any pattern
        node = Node(
            id="fn:utils.py:calculate",
            type=NodeType.FUNCTION,
            name="calculate",
            file_path="utils.py",
            properties={},
        )

        api_macro = MacroSynthesizer.STANDARD_MACROS["api"]
        macros = [api_macro]

        result = synthesizer.get_applicable_macros(node, macros)

        assert result is None

    def test_get_applicable_macros_module_type(self, db: MUbase) -> None:
        """get_applicable_macros returns None for module nodes."""
        synthesizer = MacroSynthesizer(db)

        node = Node(
            id="mod:test.py",
            type=NodeType.MODULE,
            name="test",
            file_path="test.py",
        )

        macros = list(MacroSynthesizer.STANDARD_MACROS.values())

        result = synthesizer.get_applicable_macros(node, macros)

        assert result is None


class TestMacroSynthesizerHelpers:
    """Tests for MacroSynthesizer helper methods."""

    def test_pattern_to_macro_name_valid(self, synthesizer: MacroSynthesizer) -> None:
        """_pattern_to_macro_name converts valid patterns."""
        # "custom_pattern_classes" -> strips "_classes" -> "custom_pattern" -> "custom-pattern"
        # Note: only one suffix is stripped per call (first match wins)
        result = synthesizer._pattern_to_macro_name("custom_pattern_classes")
        assert result == "custom-pattern"

        # "file_handler_functions" -> strips "_functions" -> "file_handler"
        # -> strips "file_" prefix -> "handler"
        result = synthesizer._pattern_to_macro_name("file_handler_functions")
        assert result == "handler"

    def test_pattern_to_macro_name_removes_suffixes(self, synthesizer: MacroSynthesizer) -> None:
        """_pattern_to_macro_name removes common suffixes."""
        result = synthesizer._pattern_to_macro_name("api_pattern")
        assert result == "api"

        result = synthesizer._pattern_to_macro_name("service_patterns")
        assert result == "service"

    def test_pattern_to_macro_name_replaces_underscores(
        self, synthesizer: MacroSynthesizer
    ) -> None:
        """_pattern_to_macro_name converts underscores to hyphens."""
        result = synthesizer._pattern_to_macro_name("my_custom_thing")
        assert result == "my-custom-thing"

    def test_pattern_to_macro_name_invalid(self, synthesizer: MacroSynthesizer) -> None:
        """_pattern_to_macro_name returns None for invalid names."""
        result = synthesizer._pattern_to_macro_name("123_invalid")
        assert result is None

        result = synthesizer._pattern_to_macro_name("")
        assert result is None

    def test_extract_variable_parts_by_category(self, synthesizer: MacroSynthesizer) -> None:
        """_extract_variable_parts returns category-appropriate signatures."""
        api_pattern = Pattern(
            name="test",
            category=PatternCategory.API,
            description="",
            frequency=10,
            confidence=0.9,
        )
        result = synthesizer._extract_variable_parts(api_pattern)
        assert "method" in result
        assert "path" in result

        test_pattern = Pattern(
            name="test",
            category=PatternCategory.TESTING,
            description="",
            frequency=10,
            confidence=0.9,
        )
        result = synthesizer._extract_variable_parts(test_pattern)
        assert "name" in result
        assert "target" in result

    def test_build_expansion_template(self, synthesizer: MacroSynthesizer) -> None:
        """_build_expansion_template creates category-appropriate templates."""
        api_pattern = Pattern(
            name="test",
            category=PatternCategory.API,
            description="API endpoint",
            frequency=10,
            confidence=0.9,
        )
        signature = ["method", "path", "name"]

        result = synthesizer._build_expansion_template(api_pattern, signature)

        assert "defn" in result
        assert "Response" in result

    def test_lazy_pattern_detector(self, db: MUbase) -> None:
        """pattern_detector is lazily loaded."""
        synthesizer = MacroSynthesizer(db)

        assert synthesizer._pattern_detector is None

        # Access the property to trigger lazy load
        detector = synthesizer.pattern_detector

        assert detector is not None
        assert synthesizer._pattern_detector is detector


class TestMacroTier:
    """Tests for MacroTier enum."""

    def test_tier_values(self) -> None:
        """MacroTier has expected values."""
        assert MacroTier.CORE.value == "core"
        assert MacroTier.STANDARD.value == "standard"
        assert MacroTier.SYNTHESIZED.value == "synthesized"

    def test_tier_from_string(self) -> None:
        """MacroTier can be created from string."""
        assert MacroTier("core") == MacroTier.CORE
        assert MacroTier("standard") == MacroTier.STANDARD
        assert MacroTier("synthesized") == MacroTier.SYNTHESIZED
