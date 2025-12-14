"""Macro Synthesizer for OMEGA format compression.

Synthesizes Lisp macros from detected patterns to achieve maximum
token compression while preserving semantic information.

The synthesizer bridges PatternDetector output to LispExporter input:
1. Mining: Query PatternDetector for high-frequency patterns
2. Analysis: Identify variable vs static parts of each pattern
3. Synthesis: Generate MacroDefinition with signature and template
4. Filtering: Keep only macros that provide significant compression

Usage:
    from mu.extras.intelligence import MacroSynthesizer
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    synthesizer = MacroSynthesizer(db)

    # Synthesize macros from codebase patterns
    result = synthesizer.synthesize()

    # Get macro header for context injection
    print(result.get_header())

    # Check if a node can be compressed with a macro
    macro = synthesizer.get_applicable_macros(node, result.macros)
    if macro:
        print(macro.apply(node_data))
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from mu.extras.intelligence.models import (
    MacroDefinition,
    MacroTier,
    PatternCategory,
    SynthesisResult,
)

if TYPE_CHECKING:
    from mu.extras.intelligence.models import Pattern
    from mu.extras.intelligence.patterns import PatternDetector
    from mu.kernel.models import Node
    from mu.kernel.mubase import MUbase


# Mapping from pattern names/categories to standard macros
PATTERN_TO_MACRO_MAP: dict[str, str] = {
    # API patterns
    "http_method_handlers": "api",
    "api_route_handler": "api",
    "rest_endpoint": "api",
    # Component patterns
    "component_classes": "component",
    "react_component": "component",
    "functional_component": "component",
    # Hook patterns
    "hooks_pattern": "hook",
    "use_prefix": "hook",
    "react_hook": "hook",
    # Test patterns
    "test_function_naming": "test",
    "test_prefix": "test",
    "test_classes": "test",
    # Model patterns
    "model_layer": "model",
    "dataclass_pattern": "model",
    "entity_classes": "model",
    # Service patterns
    "service_layer": "service",
    "class_suffix_service": "service",
    # Repository patterns
    "repository_pattern": "repo",
    "class_suffix_repository": "repo",
}


class MacroSynthesizer:
    """Synthesize Lisp macros from detected patterns.

    The synthesizer bridges PatternDetector output to LispExporter input:

    1. Mining: Query PatternDetector for high-frequency patterns
    2. Analysis: Identify variable vs static parts of each pattern
    3. Synthesis: Generate MacroDefinition with signature and template
    4. Filtering: Keep only macros that provide significant compression

    Configuration constants control synthesis behavior:
    - MAX_SYNTHESIZED_MACROS: Limit dynamic macros to prevent header bloat
    - MIN_PATTERN_FREQUENCY: Minimum instances to justify macro overhead
    - MIN_TOKEN_SAVINGS_PER_INSTANCE: Per-use savings threshold
    - MIN_NET_SAVINGS: Break-even threshold for macro adoption

    Example:
        >>> synthesizer = MacroSynthesizer(mubase)
        >>> result = synthesizer.synthesize()
        >>> print(f"Generated {result.macro_count} macros")
        >>> print(f"Estimated compression: {result.estimated_compression:.1%}")
    """

    # Limits to ensure stability and cache efficiency
    MAX_SYNTHESIZED_MACROS: int = 5
    """Maximum number of synthesized macros to generate."""

    MIN_PATTERN_FREQUENCY: int = 10
    """Minimum pattern instances to justify macro creation."""

    MIN_TOKEN_SAVINGS_PER_INSTANCE: int = 5
    """Minimum tokens saved per macro invocation."""

    MIN_NET_SAVINGS: int = 50
    """Break-even threshold: macro must save more than it costs to define."""

    # Standard macros (hardcoded, Tier.STANDARD)
    # These are common cross-codebase patterns that don't need synthesis
    STANDARD_MACROS: dict[str, MacroDefinition] = {
        "api": MacroDefinition(
            name="api",
            tier=MacroTier.STANDARD,
            signature=["method", "path", "name", "params"],
            description="REST API endpoint handler",
            pattern_source="http_method_handlers",
            frequency=0,
            expansion_template=(
                '(defn {name} [{params}] -> Response :decorators [app.{method}("{path}")])'
            ),
        ),
        "component": MacroDefinition(
            name="component",
            tier=MacroTier.STANDARD,
            signature=["name", "props"],
            description="UI component (React/Vue/etc)",
            pattern_source="component_classes",
            frequency=0,
            expansion_template="(defn {name} [{props}] -> JSX)",
        ),
        "hook": MacroDefinition(
            name="hook",
            tier=MacroTier.STANDARD,
            signature=["name", "deps", "returns"],
            description="React hook (use* pattern)",
            pattern_source="hooks_pattern",
            frequency=0,
            expansion_template="(defn use{name} [{deps}] -> {returns})",
        ),
        "test": MacroDefinition(
            name="test",
            tier=MacroTier.STANDARD,
            signature=["name", "target"],
            description="Test function",
            pattern_source="test_function_naming",
            frequency=0,
            expansion_template="(defn test_{name} [] :tests {target})",
        ),
        "model": MacroDefinition(
            name="model",
            tier=MacroTier.STANDARD,
            signature=["name", "fields"],
            description="Data model/entity",
            pattern_source="model_layer",
            frequency=0,
            expansion_template="(data {name} [{fields}])",
        ),
        "service": MacroDefinition(
            name="service",
            tier=MacroTier.STANDARD,
            signature=["name", "deps", "methods"],
            description="Service class for business logic",
            pattern_source="service_layer",
            frequency=0,
            expansion_template="(class {name}Service :deps [{deps}] {methods})",
        ),
        "repo": MacroDefinition(
            name="repo",
            tier=MacroTier.STANDARD,
            signature=["name", "entity"],
            description="Repository for data access",
            pattern_source="repository_pattern",
            frequency=0,
            expansion_template="(class {name}Repository :entity {entity})",
        ),
    }

    def __init__(self, mubase: MUbase) -> None:
        """Initialize the macro synthesizer.

        Args:
            mubase: The MUbase database for pattern access.
        """
        self.db = mubase
        self._pattern_detector: PatternDetector | None = None

    @property
    def pattern_detector(self) -> PatternDetector:
        """Lazy-load pattern detector."""
        if self._pattern_detector is None:
            from mu.extras.intelligence.patterns import PatternDetector

            self._pattern_detector = PatternDetector(self.db)
        return self._pattern_detector

    def synthesize(
        self,
        include_standard: bool = True,
        max_synthesized: int | None = None,
    ) -> SynthesisResult:
        """Synthesize macros from codebase patterns.

        This method does two things:
        1. Creates MacroDefinition objects for detected patterns
        2. Builds a node→macro map for O(1) lookup during compression

        Args:
            include_standard: Include standard macros that match patterns.
            max_synthesized: Override MAX_SYNTHESIZED_MACROS limit.

        Returns:
            SynthesisResult with macro definitions and node_macro_map.
        """
        start_time = time.time()
        max_synth = max_synthesized or self.MAX_SYNTHESIZED_MACROS

        # Get patterns from detector
        patterns_result = self.pattern_detector.detect()
        total_patterns = len(patterns_result.patterns)

        macros: list[MacroDefinition] = []
        standard_matched: set[str] = set()
        synthesized_count = 0

        # Process patterns and match to standard macros or synthesize new ones
        for pattern in patterns_result.patterns:
            # Skip low-frequency patterns
            if pattern.frequency < self.MIN_PATTERN_FREQUENCY:
                continue

            # Check if pattern maps to a standard macro
            macro_name = PATTERN_TO_MACRO_MAP.get(pattern.name)
            if macro_name and macro_name in self.STANDARD_MACROS:
                if include_standard and macro_name not in standard_matched:
                    # Clone standard macro with updated frequency
                    std_macro = self.STANDARD_MACROS[macro_name]
                    macro = MacroDefinition(
                        name=std_macro.name,
                        tier=std_macro.tier,
                        signature=std_macro.signature,
                        description=std_macro.description,
                        pattern_source=pattern.name,
                        frequency=pattern.frequency,
                        expansion_template=std_macro.expansion_template,
                        token_savings=self._calculate_token_savings_for_macro(
                            std_macro, pattern.frequency
                        ),
                    )
                    macros.append(macro)
                    standard_matched.add(macro_name)
            elif synthesized_count < max_synth:
                # Try to synthesize a new macro
                synthesized = self._analyze_pattern(pattern)
                if synthesized:
                    # Calculate and check token savings
                    savings = self._calculate_token_savings(synthesized)
                    if savings >= self.MIN_NET_SAVINGS:
                        synthesized.token_savings = savings
                        macros.append(synthesized)
                        synthesized_count += 1

        # Build node→macro map for O(1) lookup during compression
        node_macro_map = self._build_node_macro_map(macros)

        # Calculate estimated compression
        total_savings = sum(m.token_savings for m in macros)
        # Rough estimate: assume average context is ~10000 tokens
        estimated_compression = total_savings / 10000 if total_savings > 0 else 0.0

        elapsed_ms = (time.time() - start_time) * 1000

        return SynthesisResult(
            macros=macros,
            node_macro_map=node_macro_map,
            total_patterns_analyzed=total_patterns,
            patterns_converted=len(macros),
            estimated_compression=min(estimated_compression, 0.9),  # Cap at 90%
            synthesis_time_ms=elapsed_ms,
            nodes_mapped=len(node_macro_map),
        )

    def _build_node_macro_map(
        self, macros: list[MacroDefinition]
    ) -> dict[str, MacroDefinition]:
        """Build a mapping from node IDs to applicable macros.

        This is the key optimization: instead of O(N*M) matching during export,
        we pre-compute which macro applies to each node during synthesis.

        Args:
            macros: Available macro definitions.

        Returns:
            Dict mapping node_id -> MacroDefinition.
        """
        from mu.kernel.schema import NodeType

        node_macro_map: dict[str, MacroDefinition] = {}

        # Build macro lookup by name for fast access
        macro_lookup = {m.name: m for m in macros}

        # Query nodes from database and match to macros
        # We check each macro type against the appropriate node type

        # Test functions
        if "test" in macro_lookup:
            test_macro = macro_lookup["test"]
            functions = self.db.get_nodes(NodeType.FUNCTION)
            for node in functions:
                node_name = (node.name or "").lower()
                file_path = (node.file_path or "").lower()
                if node_name.startswith("test") or "/test" in file_path:
                    node_macro_map[node.id] = test_macro

        # Service classes
        if "service" in macro_lookup:
            service_macro = macro_lookup["service"]
            classes = self.db.get_nodes(NodeType.CLASS)
            for node in classes:
                if (node.name or "").lower().endswith("service"):
                    node_macro_map[node.id] = service_macro

        # Repository classes
        if "repo" in macro_lookup:
            repo_macro = macro_lookup["repo"]
            classes = self.db.get_nodes(NodeType.CLASS)
            for node in classes:
                node_name = (node.name or "").lower()
                if "repository" in node_name or "repo" in node_name:
                    node_macro_map[node.id] = repo_macro

        # Model classes (dataclasses)
        if "model" in macro_lookup:
            model_macro = macro_lookup["model"]
            classes = self.db.get_nodes(NodeType.CLASS)
            for node in classes:
                props = node.properties or {}
                decorators = str(props.get("decorators", [])).lower()
                if "dataclass" in decorators or (node.name or "").lower().endswith(
                    "model"
                ):
                    if node.id not in node_macro_map:  # Don't override service/repo
                        node_macro_map[node.id] = model_macro

        # Hook functions (React-style use*)
        if "hook" in macro_lookup:
            hook_macro = macro_lookup["hook"]
            functions = self.db.get_nodes(NodeType.FUNCTION)
            for node in functions:
                if (node.name or "").lower().startswith("use"):
                    if node.id not in node_macro_map:  # Don't override test
                        node_macro_map[node.id] = hook_macro

        # API endpoints (functions with HTTP decorators)
        if "api" in macro_lookup:
            api_macro = macro_lookup["api"]
            functions = self.db.get_nodes(NodeType.FUNCTION)
            for node in functions:
                props = node.properties or {}
                decorators = str(props.get("decorators", [])).lower()
                if any(
                    m in decorators
                    for m in ["get", "post", "put", "delete", "patch", "route"]
                ):
                    if node.id not in node_macro_map:
                        node_macro_map[node.id] = api_macro

        return node_macro_map

    def _analyze_pattern(self, pattern: Pattern) -> MacroDefinition | None:
        """Analyze a pattern and generate a macro if beneficial.

        Args:
            pattern: The detected pattern to analyze.

        Returns:
            MacroDefinition if pattern is macro-worthy, None otherwise.
        """
        # Extract variable parts for the signature
        signature = self._extract_variable_parts(pattern)
        if not signature:
            return None

        # Generate macro name from pattern
        name = self._pattern_to_macro_name(pattern.name)
        if not name:
            return None

        # Build expansion template from pattern description
        template = self._build_expansion_template(pattern, signature)

        return MacroDefinition(
            name=name,
            tier=MacroTier.SYNTHESIZED,
            signature=signature,
            description=pattern.description,
            pattern_source=pattern.name,
            frequency=pattern.frequency,
            expansion_template=template,
            token_savings=0,  # Calculated later
        )

    def _extract_variable_parts(self, pattern: Pattern) -> list[str]:
        """Identify the variable parts of a pattern for macro signature.

        Args:
            pattern: The pattern to analyze.

        Returns:
            List of variable parameter names.
        """
        # Default signatures based on pattern category
        category_signatures: dict[PatternCategory, list[str]] = {
            PatternCategory.API: ["method", "path", "name"],
            PatternCategory.COMPONENTS: ["name", "props"],
            PatternCategory.STATE_MANAGEMENT: ["name", "initial_state"],
            PatternCategory.TESTING: ["name", "target"],
            PatternCategory.ARCHITECTURE: ["name", "deps"],
            PatternCategory.NAMING: ["name"],
            PatternCategory.ERROR_HANDLING: ["name", "message"],
            PatternCategory.IMPORTS: ["module"],
            PatternCategory.ASYNC: ["name", "returns"],
            PatternCategory.LOGGING: ["level", "message"],
        }

        # Use category-based signature or default
        return category_signatures.get(pattern.category, ["name"])

    def _calculate_token_savings(self, macro: MacroDefinition) -> int:
        """Calculate estimated token savings from using a macro.

        Uses the break-even formula:
            Net Savings = (Instances × (OriginalTokens - MacroCallTokens))
                          - MacroDefinitionTokens

        A macro is only worth synthesizing if:
            Net Savings > MIN_NET_SAVINGS (default: 50)

        Args:
            macro: The macro definition.

        Returns:
            Net tokens saved (negative means macro costs more than it saves).
        """
        return self._calculate_token_savings_for_macro(macro, macro.frequency)

    def _calculate_token_savings_for_macro(self, macro: MacroDefinition, frequency: int) -> int:
        """Calculate token savings for a macro with given frequency.

        Args:
            macro: The macro definition.
            frequency: Number of instances the macro would compress.

        Returns:
            Net tokens saved.
        """
        # Estimate tokens in expanded form based on template length
        # Rough heuristic: 1 token per ~4 characters
        expanded_tokens = len(macro.expansion_template) // 4 + len(macro.signature) * 2

        # Estimate tokens in macro call: (name param1 param2 ...)
        macro_call_tokens = 1 + len(macro.signature)  # name + params

        # Estimate tokens in macro definition
        # (defmacro name [params] "description")
        macro_def_tokens = 4 + len(macro.signature) + len(macro.description) // 10

        # Calculate savings per instance
        savings_per_instance = expanded_tokens - macro_call_tokens

        # Only count if savings exceed minimum threshold
        if savings_per_instance < self.MIN_TOKEN_SAVINGS_PER_INSTANCE:
            return 0

        # Net savings = (instances × per-instance savings) - definition cost
        net_savings = (frequency * savings_per_instance) - macro_def_tokens

        return max(0, net_savings)

    def get_applicable_macros(
        self,
        node: Node,
        available_macros: list[MacroDefinition],
    ) -> MacroDefinition | None:
        """Find the best macro to apply to a node.

        Args:
            node: The node to potentially compress.
            available_macros: Available macro definitions.

        Returns:
            Best matching macro or None.
        """
        from mu.kernel.schema import NodeType

        # Match node type to macro patterns
        node_type_to_macros: dict[NodeType, list[str]] = {
            NodeType.FUNCTION: ["api", "hook", "test"],
            NodeType.CLASS: ["service", "repo", "model", "component"],
            NodeType.MODULE: [],
            NodeType.EXTERNAL: [],
        }

        applicable_names = node_type_to_macros.get(node.type, [])
        if not applicable_names:
            return None

        # Check node properties and name for pattern matches
        node_name = node.name.lower() if node.name else ""
        node_props = node.properties or {}

        best_macro: MacroDefinition | None = None
        best_score = 0

        for macro in available_macros:
            if macro.name not in applicable_names:
                continue

            score = self._score_macro_match(node, node_name, node_props, macro)
            if score > best_score:
                best_score = score
                best_macro = macro

        return best_macro if best_score > 0 else None

    def _score_macro_match(
        self,
        node: Node,
        node_name: str,
        node_props: dict[str, Any],
        macro: MacroDefinition,
    ) -> int:
        """Score how well a macro matches a node.

        Args:
            node: The node to score.
            node_name: Lowercase node name.
            node_props: Node properties dict.
            macro: The macro to check.

        Returns:
            Match score (0 = no match, higher = better match).
        """
        score = 0

        # Check for pattern-specific indicators
        if macro.name == "api":
            # Look for HTTP method decorators
            decorators = node_props.get("decorators", [])
            if any(d in str(decorators).lower() for d in ["get", "post", "put", "delete", "route"]):
                score += 10
        elif macro.name == "hook":
            # React hooks start with "use"
            if node_name.startswith("use"):
                score += 10
        elif macro.name == "test":
            # Test functions start with "test_" or are in test files
            if node_name.startswith("test") or "test" in (node.file_path or "").lower():
                score += 10
        elif macro.name == "service":
            if node_name.endswith("service"):
                score += 10
        elif macro.name == "repo":
            if "repository" in node_name or "repo" in node_name:
                score += 10
        elif macro.name == "model":
            # Check for dataclass decorator or model indicators
            decorators = node_props.get("decorators", [])
            if "dataclass" in str(decorators).lower() or node_name.endswith("model"):
                score += 10
        elif macro.name == "component":
            # Check for JSX return or component indicators
            if node_name[0].isupper() and not node_name.endswith("service"):
                score += 5

        return score

    def _pattern_to_macro_name(self, pattern_name: str) -> str | None:
        """Convert a pattern name to a valid macro name.

        Args:
            pattern_name: The pattern name to convert.

        Returns:
            Valid macro name or None if not convertible.
        """
        # Clean up pattern name
        name = pattern_name.lower()

        # Remove common suffixes
        for suffix in ["_pattern", "_patterns", "_classes", "_functions"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]

        # Remove common prefixes
        for prefix in ["class_suffix_", "function_prefix_", "file_"]:
            if name.startswith(prefix):
                name = name[len(prefix) :]

        # Validate: must be valid identifier
        if not name or not name[0].isalpha():
            return None

        # Replace underscores with hyphens for Lisp style
        return name.replace("_", "-")

    def _build_expansion_template(self, pattern: Pattern, signature: list[str]) -> str:
        """Build an expansion template for a synthesized macro.

        Args:
            pattern: The source pattern.
            signature: The macro signature (parameter names).

        Returns:
            Expansion template string.
        """
        # Build a generic template based on pattern category
        params_str = " ".join(f"{{{p}}}" for p in signature)

        category_templates: dict[PatternCategory, str] = {
            PatternCategory.API: "(defn {name} [{params}] -> Response)",
            PatternCategory.COMPONENTS: "(defn {name} [{props}] -> JSX)",
            PatternCategory.STATE_MANAGEMENT: "(def {name} (atom {initial_state}))",
            PatternCategory.TESTING: "(defn test_{name} [] :tests {target})",
            PatternCategory.ARCHITECTURE: "(class {name} :deps [{deps}])",
            PatternCategory.NAMING: "(def {name})",
            PatternCategory.ERROR_HANDLING: "(class {name}Error [{message}])",
            PatternCategory.IMPORTS: "(import {module})",
            PatternCategory.ASYNC: "(defn-async {name} [] -> {returns})",
            PatternCategory.LOGGING: "(log {level} {message})",
        }

        return category_templates.get(pattern.category, f"({pattern.name} {params_str})")


__all__ = [
    "MacroSynthesizer",
]
