"""Tests for OmegaContextExtractor - OMEGA semantic compression.

Tests the OMEGA context extraction pipeline including:
- Basic extraction and S-expression output
- Seed/body separation
- Compression ratio vs sigils
- Token budget enforcement
- Manifest generation
- Cache optimization ordering
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mu.intelligence.models import MacroDefinition, MacroTier, SynthesisResult
from mu.kernel import MUbase, Node, NodeType
from mu.kernel.context.omega import (
    OmegaConfig,
    OmegaContextExtractor,
    OmegaManifest,
    OmegaResult,
)


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
def config() -> OmegaConfig:
    """Create default OMEGA config."""
    return OmegaConfig(
        max_tokens=8000,
        include_synthesized=True,
        max_synthesized_macros=5,
    )


@pytest.fixture
def extractor(db: MUbase, config: OmegaConfig) -> OmegaContextExtractor:
    """Create OmegaContextExtractor instance."""
    return OmegaContextExtractor(db, config)


# =============================================================================
# OmegaConfig Tests
# =============================================================================


class TestOmegaConfig:
    """Tests for OmegaConfig dataclass."""

    def test_default_values(self) -> None:
        """Default config has sensible values."""
        config = OmegaConfig()

        assert config.max_tokens == 8000
        assert config.header_budget_ratio == 0.15
        assert config.include_synthesized is True
        assert config.max_synthesized_macros == 5
        assert config.enable_prompt_cache_optimization is True
        assert config.fallback_to_sigils is False

    def test_to_dict(self) -> None:
        """to_dict serializes all fields correctly."""
        config = OmegaConfig(
            max_tokens=4000,
            header_budget_ratio=0.2,
            include_synthesized=False,
            max_synthesized_macros=3,
        )

        d = config.to_dict()

        assert d["max_tokens"] == 4000
        assert d["header_budget_ratio"] == 0.2
        assert d["include_synthesized"] is False
        assert d["max_synthesized_macros"] == 3

    def test_from_dict(self) -> None:
        """from_dict deserializes correctly."""
        data = {
            "max_tokens": 10000,
            "header_budget_ratio": 0.1,
            "include_synthesized": True,
            "max_synthesized_macros": 10,
            "enable_prompt_cache_optimization": False,
            "fallback_to_sigils": True,
        }

        config = OmegaConfig.from_dict(data)

        assert config.max_tokens == 10000
        assert config.header_budget_ratio == 0.1
        assert config.include_synthesized is True
        assert config.max_synthesized_macros == 10
        assert config.enable_prompt_cache_optimization is False
        assert config.fallback_to_sigils is True

    def test_from_dict_with_defaults(self) -> None:
        """from_dict uses defaults for missing fields."""
        data = {"max_tokens": 5000}

        config = OmegaConfig.from_dict(data)

        assert config.max_tokens == 5000
        assert config.header_budget_ratio == 0.15  # default
        assert config.include_synthesized is True  # default


# =============================================================================
# OmegaManifest Tests
# =============================================================================


class TestOmegaManifest:
    """Tests for OmegaManifest dataclass."""

    def test_to_sexpr_minimal(self) -> None:
        """to_sexpr works with minimal manifest."""
        manifest = OmegaManifest(version="1.0")

        result = manifest.to_sexpr()

        assert '(mu-lisp :version "1.0")' in result

    def test_to_sexpr_with_codebase_info(self) -> None:
        """to_sexpr includes codebase and commit info."""
        manifest = OmegaManifest(
            version="1.0",
            codebase="mu",
            commit="abc1234567890",
        )

        result = manifest.to_sexpr()

        assert ':codebase "mu"' in result
        assert ':commit "abc1234"' in result  # Truncated to 7 chars

    def test_to_sexpr_with_macros(self) -> None:
        """to_sexpr includes macro lists."""
        manifest = OmegaManifest(
            version="1.0",
            core_macros=["module", "class", "defn"],
            standard_macros=["api", "service"],
            synthesized_macros=["mcp-tool"],
        )

        result = manifest.to_sexpr()

        assert ":core [module class defn]" in result
        assert ":standard [api service]" in result
        assert ":synthesized [mcp-tool]" in result

    def test_all_macros_property(self) -> None:
        """all_macros returns combined list in order."""
        manifest = OmegaManifest(
            core_macros=["a", "b"],
            standard_macros=["c"],
            synthesized_macros=["d", "e"],
        )

        result = manifest.all_macros

        assert result == ["a", "b", "c", "d", "e"]

    def test_macro_count_property(self) -> None:
        """macro_count returns total count."""
        manifest = OmegaManifest(
            core_macros=["a", "b"],
            standard_macros=["c"],
            synthesized_macros=["d"],
        )

        assert manifest.macro_count == 4

    def test_to_dict(self) -> None:
        """to_dict serializes all fields."""
        manifest = OmegaManifest(
            version="1.0",
            codebase="mu",
            commit="abc123",
            core_macros=["module"],
            standard_macros=["api"],
            synthesized_macros=["custom"],
        )

        d = manifest.to_dict()

        assert d["version"] == "1.0"
        assert d["codebase"] == "mu"
        assert d["commit"] == "abc123"
        assert d["core_macros"] == ["module"]
        assert d["standard_macros"] == ["api"]
        assert d["synthesized_macros"] == ["custom"]

    def test_from_dict(self) -> None:
        """from_dict deserializes correctly."""
        data = {
            "version": "1.0",
            "codebase": "test",
            "commit": "xyz789",
            "core_macros": ["module", "class"],
            "standard_macros": [],
            "synthesized_macros": ["custom"],
        }

        manifest = OmegaManifest.from_dict(data)

        assert manifest.version == "1.0"
        assert manifest.codebase == "test"
        assert manifest.commit == "xyz789"
        assert manifest.core_macros == ["module", "class"]
        assert manifest.synthesized_macros == ["custom"]


# =============================================================================
# OmegaResult Tests
# =============================================================================


class TestOmegaResult:
    """Tests for OmegaResult dataclass."""

    def test_full_output_with_seed_and_body(self) -> None:
        """full_output combines seed and body correctly."""
        result = OmegaResult(
            seed=";; MU-Lisp Macro Definitions\n(defmacro api [...])",
            body="(module auth ...)",
            manifest=OmegaManifest(),
        )

        output = result.full_output

        assert ";; MU-Lisp Macro Definitions" in output
        assert "(defmacro api" in output
        assert ";; Codebase Context" in output
        assert "(module auth" in output

    def test_full_output_body_only(self) -> None:
        """full_output works with empty seed."""
        result = OmegaResult(
            seed="",
            body="(module auth ...)",
            manifest=OmegaManifest(),
        )

        output = result.full_output

        assert ";; Codebase Context" in output
        assert "(module auth" in output

    def test_full_output_seed_only(self) -> None:
        """full_output works with empty body."""
        result = OmegaResult(
            seed=";; Definitions",
            body="",
            manifest=OmegaManifest(),
        )

        output = result.full_output

        assert output == ";; Definitions"

    def test_is_compressed_property(self) -> None:
        """is_compressed reflects compression ratio."""
        compressed = OmegaResult(
            seed="",
            body="",
            manifest=OmegaManifest(),
            compression_ratio=2.5,
        )
        not_compressed = OmegaResult(
            seed="",
            body="",
            manifest=OmegaManifest(),
            compression_ratio=0.8,
        )

        assert compressed.is_compressed is True
        assert not_compressed.is_compressed is False

    def test_tokens_saved_property(self) -> None:
        """tokens_saved calculates correctly."""
        result = OmegaResult(
            seed="",
            body="",
            manifest=OmegaManifest(),
            original_tokens=1000,
            total_tokens=300,
        )

        assert result.tokens_saved == 700

    def test_tokens_saved_no_savings(self) -> None:
        """tokens_saved returns 0 when no savings."""
        result = OmegaResult(
            seed="",
            body="",
            manifest=OmegaManifest(),
            original_tokens=100,
            total_tokens=150,
        )

        assert result.tokens_saved == 0

    def test_savings_percent_property(self) -> None:
        """savings_percent calculates correctly."""
        result = OmegaResult(
            seed="",
            body="",
            manifest=OmegaManifest(),
            original_tokens=1000,
            total_tokens=250,
        )

        assert result.savings_percent == 75.0

    def test_savings_percent_zero_original(self) -> None:
        """savings_percent handles zero original tokens."""
        result = OmegaResult(
            seed="",
            body="",
            manifest=OmegaManifest(),
            original_tokens=0,
            total_tokens=100,
        )

        assert result.savings_percent == 0.0

    def test_to_dict(self) -> None:
        """to_dict serializes all fields."""
        result = OmegaResult(
            seed="seed",
            body="body",
            manifest=OmegaManifest(version="1.0"),
            macros_used=["api"],
            seed_tokens=50,
            body_tokens=200,
            total_tokens=250,
            original_tokens=750,
            compression_ratio=3.0,
            nodes_included=5,
            extraction_stats={"key": "value"},
        )

        d = result.to_dict()

        assert d["seed"] == "seed"
        assert d["body"] == "body"
        assert d["manifest"]["version"] == "1.0"
        assert d["macros_used"] == ["api"]
        assert d["seed_tokens"] == 50
        assert d["body_tokens"] == 200
        assert d["total_tokens"] == 250
        assert d["original_tokens"] == 750
        assert d["compression_ratio"] == 3.0
        assert d["nodes_included"] == 5
        assert d["extraction_stats"]["key"] == "value"

    def test_from_dict(self) -> None:
        """from_dict deserializes correctly."""
        data = {
            "seed": "definitions",
            "body": "content",
            "manifest": {"version": "1.0"},
            "macros_used": ["api", "service"],
            "seed_tokens": 100,
            "body_tokens": 400,
            "total_tokens": 500,
            "original_tokens": 1500,
            "compression_ratio": 3.0,
            "nodes_included": 10,
            "extraction_stats": {},
        }

        result = OmegaResult.from_dict(data)

        assert result.seed == "definitions"
        assert result.body == "content"
        assert result.manifest.version == "1.0"
        assert result.macros_used == ["api", "service"]
        assert result.compression_ratio == 3.0


# =============================================================================
# OmegaContextExtractor Tests
# =============================================================================


class TestOmegaContextExtractor:
    """Tests for OmegaContextExtractor class."""

    def test_init(self, db: MUbase) -> None:
        """OmegaContextExtractor initializes correctly."""
        config = OmegaConfig(max_tokens=4000)
        extractor = OmegaContextExtractor(db, config)

        assert extractor.mubase is db
        assert extractor.config.max_tokens == 4000
        assert extractor._synthesizer is None
        assert extractor._lisp_exporter is None

    def test_init_default_config(self, db: MUbase) -> None:
        """OmegaContextExtractor uses default config if not provided."""
        extractor = OmegaContextExtractor(db)

        assert extractor.config.max_tokens == 8000
        assert extractor.config.include_synthesized is True

    def test_lazy_synthesizer(self, db: MUbase) -> None:
        """synthesizer property is lazy-loaded."""
        extractor = OmegaContextExtractor(db)

        assert extractor._synthesizer is None

        # Access the property
        synthesizer = extractor.synthesizer

        assert synthesizer is not None
        assert extractor._synthesizer is synthesizer

    def test_lazy_lisp_exporter(self, db: MUbase) -> None:
        """lisp_exporter property is lazy-loaded."""
        extractor = OmegaContextExtractor(db)

        assert extractor._lisp_exporter is None

        # Access the property
        exporter = extractor.lisp_exporter

        assert exporter is not None
        assert extractor._lisp_exporter is exporter

    def test_extract_no_results(self, db: MUbase) -> None:
        """extract handles empty context gracefully."""
        config = OmegaConfig(max_tokens=1000)
        extractor = OmegaContextExtractor(db, config)

        # Mock the smart extractor to return no nodes
        with patch.object(extractor, "smart_extractor") as mock_smart:
            mock_result = MagicMock()
            mock_result.nodes = []
            mock_smart.extract.return_value = mock_result

            result = extractor.extract("How does auth work?")

        assert result.nodes_included == 0
        assert "No relevant context found" in result.body

    def test_extract_with_nodes(self, db: MUbase) -> None:
        """extract processes nodes correctly."""
        config = OmegaConfig(max_tokens=4000, include_synthesized=False)
        extractor = OmegaContextExtractor(db, config)

        # Create mock nodes
        mock_node = Node(
            id="cls:auth.py:AuthService",
            type=NodeType.CLASS,
            name="AuthService",
            file_path="auth.py",
            properties={"bases": []},
        )

        # Mock smart extractor
        with patch.object(extractor, "smart_extractor") as mock_smart:
            mock_context = MagicMock()
            mock_context.nodes = [mock_node]
            mock_context.token_count = 500
            mock_smart.extract.return_value = mock_context

            # Create mock synthesizer
            mock_synth = MagicMock()
            mock_synth.synthesize.return_value = SynthesisResult(macros=[])
            mock_synth.get_applicable_macros.return_value = None
            extractor._synthesizer = mock_synth

            # Create mock lisp exporter
            mock_lisp = MagicMock()
            mock_export = MagicMock()
            mock_export.success = True
            mock_export.output = "(module auth.py (class AuthService))"
            mock_lisp.export.return_value = mock_export
            extractor._lisp_exporter = mock_lisp

            result = extractor.extract("How does auth work?")

        assert result.nodes_included == 1
        assert "auth" in result.body.lower()

    def test_token_counting(self, db: MUbase) -> None:
        """_count_tokens uses tiktoken correctly."""
        extractor = OmegaContextExtractor(db)

        # Count tokens for known text
        text = "Hello world this is a test"
        token_count = extractor._count_tokens(text)

        # tiktoken's cl100k_base should give ~6 tokens for this
        assert token_count > 0
        assert token_count < 20  # Sanity check

    def test_token_counting_empty(self, db: MUbase) -> None:
        """_count_tokens handles empty strings."""
        extractor = OmegaContextExtractor(db)

        assert extractor._count_tokens("") == 0


class TestOmegaContextExtractorMacroSelection:
    """Tests for macro selection in OmegaContextExtractor."""

    def test_select_macros_empty_nodes(self, db: MUbase) -> None:
        """_select_macros_for_context handles empty nodes."""
        extractor = OmegaContextExtractor(db)
        # Create empty SynthesisResult
        synthesis_result = SynthesisResult(macros=[], node_macro_map={})

        result = extractor._select_macros_for_context([], synthesis_result)

        assert result == []

    def test_select_macros_no_applicable(self, db: MUbase) -> None:
        """_select_macros_for_context returns empty for non-matching nodes."""
        extractor = OmegaContextExtractor(db)

        node = Node(
            id="fn:utils.py:calculate",
            type=NodeType.FUNCTION,
            name="calculate",
            file_path="utils.py",
        )
        macros = [
            MacroDefinition(
                name="api",
                tier=MacroTier.STANDARD,
                signature=["method", "path"],
                description="API endpoint",
                pattern_source="http_method_handlers",
                frequency=10,
                expansion_template="...",
            )
        ]

        # No node→macro mappings (node not in the map)
        synthesis_result = SynthesisResult(
            macros=macros,
            node_macro_map={},  # Empty - node not mapped to any macro
        )

        result = extractor._select_macros_for_context([node], synthesis_result)

        assert result == []

    def test_select_macros_cache_optimization_ordering(self, db: MUbase) -> None:
        """_select_macros_for_context orders by tier when optimization enabled."""
        config = OmegaConfig(enable_prompt_cache_optimization=True)
        extractor = OmegaContextExtractor(db, config)

        # Create macros of different tiers
        synth_macro = MacroDefinition(
            name="custom",
            tier=MacroTier.SYNTHESIZED,
            signature=["x"],
            description="Custom",
            pattern_source="p",
            frequency=1,
            expansion_template="...",
        )
        std_macro = MacroDefinition(
            name="api",
            tier=MacroTier.STANDARD,
            signature=["x"],
            description="API",
            pattern_source="p",
            frequency=1,
            expansion_template="...",
        )
        core_macro = MacroDefinition(
            name="defn",
            tier=MacroTier.CORE,
            signature=["x"],
            description="Function",
            pattern_source="p",
            frequency=1,
            expansion_template="...",
        )

        nodes = [
            Node(id="n1", type=NodeType.FUNCTION, name="a", file_path="a.py"),
            Node(id="n2", type=NodeType.FUNCTION, name="b", file_path="b.py"),
            Node(id="n3", type=NodeType.FUNCTION, name="c", file_path="c.py"),
        ]

        # Build node_macro_map with different macros for each node
        # This tests O(1) lookup and tier ordering
        node_macro_map = {
            "n1": synth_macro,  # First node gets SYNTHESIZED
            "n2": std_macro,    # Second node gets STANDARD
            "n3": core_macro,   # Third node gets CORE
        }

        synthesis_result = SynthesisResult(
            macros=[synth_macro, std_macro, core_macro],
            node_macro_map=node_macro_map,
        )

        result = extractor._select_macros_for_context(nodes, synthesis_result)

        # Should be ordered: CORE -> STANDARD -> SYNTHESIZED (for cache optimization)
        assert len(result) == 3
        assert result[0].tier == MacroTier.CORE
        assert result[1].tier == MacroTier.STANDARD
        assert result[2].tier == MacroTier.SYNTHESIZED


class TestOmegaContextExtractorSeedGeneration:
    """Tests for seed (schema header) generation.

    Schema v2.0 uses a fixed OMG_SCHEMA_HEADER for strict positional typing,
    replacing the dynamic defmacro approach.
    """

    def test_generate_seed_returns_schema_header(self, db: MUbase) -> None:
        """_generate_seed returns OMG SCHEMA v2.0 header."""
        extractor = OmegaContextExtractor(db)

        # Even with empty macros, Schema v2.0 returns the fixed header
        result = extractor._generate_seed([])

        assert ";; OMG SCHEMA v2.0 - STRICT POSITIONAL TYPING" in result
        assert "(defschema module [Name FilePath]" in result
        assert "(defschema service [Name Dependencies Methods]" in result
        assert "(defschema method [Name Args ReturnType Complexity]" in result

    def test_generate_seed_with_macros(self, db: MUbase) -> None:
        """_generate_seed produces OMG SCHEMA v2.0 (macros param ignored)."""
        extractor = OmegaContextExtractor(db)

        # Macros are not used in Schema v2.0 - we have a fixed schema
        macros = [
            MacroDefinition(
                name="api",
                tier=MacroTier.STANDARD,
                signature=["method", "path", "name"],
                description="REST API endpoint",
                pattern_source="http_method_handlers",
                frequency=10,
                expansion_template="...",
            ),
            MacroDefinition(
                name="test",
                tier=MacroTier.STANDARD,
                signature=["name"],
                description="Test function",
                pattern_source="test_prefix",
                frequency=5,
                expansion_template="...",
            ),
        ]

        result = extractor._generate_seed(macros)

        # Schema v2.0 uses defschema instead of defmacro
        assert ";; OMG SCHEMA v2.0 - STRICT POSITIONAL TYPING" in result
        assert "(defschema api [HttpVerb Path Handler Args]" in result
        assert "(defschema function [Name Args ReturnType Complexity]" in result


class TestOmegaContextExtractorManifest:
    """Tests for manifest generation."""

    def test_build_manifest_empty_macros(self, db: MUbase) -> None:
        """_build_manifest works with no macros."""
        extractor = OmegaContextExtractor(db)

        manifest = extractor._build_manifest([])

        assert manifest.version == "1.0"
        assert manifest.core_macros == []
        assert manifest.standard_macros == []
        assert manifest.synthesized_macros == []

    def test_build_manifest_categorizes_macros(self, db: MUbase) -> None:
        """_build_manifest categorizes macros by tier."""
        extractor = OmegaContextExtractor(db)

        macros = [
            MacroDefinition(
                name="defn",
                tier=MacroTier.CORE,
                signature=["name"],
                description="Core",
                pattern_source="p",
                frequency=1,
                expansion_template="...",
            ),
            MacroDefinition(
                name="api",
                tier=MacroTier.STANDARD,
                signature=["method"],
                description="Standard",
                pattern_source="p",
                frequency=1,
                expansion_template="...",
            ),
            MacroDefinition(
                name="custom",
                tier=MacroTier.SYNTHESIZED,
                signature=["x"],
                description="Synthesized",
                pattern_source="p",
                frequency=1,
                expansion_template="...",
            ),
        ]

        manifest = extractor._build_manifest(macros)

        assert manifest.core_macros == ["defn"]
        assert manifest.standard_macros == ["api"]
        assert manifest.synthesized_macros == ["custom"]


# =============================================================================
# Integration Tests
# =============================================================================


class TestOmegaIntegration:
    """Integration tests for the full OMEGA pipeline."""

    def test_extraction_stats_populated(self, db: MUbase) -> None:
        """extraction_stats contains timing and count info."""
        extractor = OmegaContextExtractor(db)

        with patch.object(extractor, "smart_extractor") as mock_smart:
            mock_result = MagicMock()
            mock_result.nodes = []
            mock_smart.extract.return_value = mock_result

            result = extractor.extract("test question")

        assert "question" in result.extraction_stats
        assert result.extraction_stats["question"] == "test question"

    def test_compression_ratio_calculation(self, db: MUbase) -> None:
        """Compression ratio is calculated from original vs OMEGA tokens."""
        extractor = OmegaContextExtractor(db)

        mock_node = Node(
            id="cls:test.py:Test",
            type=NodeType.CLASS,
            name="Test",
            file_path="test.py",
        )

        with patch.object(extractor, "smart_extractor") as mock_smart:
            mock_result = MagicMock()
            mock_result.nodes = [mock_node]
            mock_result.token_count = 1000  # Original tokens
            mock_smart.extract.return_value = mock_result

            # Mock synthesizer by setting private attribute
            mock_synth = MagicMock()
            mock_synth.synthesize.return_value = SynthesisResult(macros=[])
            mock_synth.get_applicable_macros.return_value = None
            extractor._synthesizer = mock_synth

            # Mock lisp exporter by setting private attribute
            mock_lisp = MagicMock()
            mock_export = MagicMock()
            mock_export.success = True
            mock_export.output = "(module test)"  # Short output
            mock_lisp.export.return_value = mock_export
            extractor._lisp_exporter = mock_lisp

            result = extractor.extract("test")

        # Compression ratio should be original/OMEGA
        assert result.original_tokens == 1000
        assert result.compression_ratio > 0
