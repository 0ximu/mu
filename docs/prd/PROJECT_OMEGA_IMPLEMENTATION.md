# Project OMEGA: Implementation PRD

## The Lisp Singularity - S-Expression Semantic Compression

**Status:** APPROVED
**Version:** 1.0
**Authors:** Human Architect + Claude Opus 4.5 (Audit)
**Target Branch:** `feature/omega`

---

## 1. Executive Summary

Project OMEGA transforms MU from a **code describer** into a **pure intent transmitter**. By converting codebase representations to Lisp S-expressions with dynamic macro compression, we achieve:

- **3-5x token reduction** (conservative estimate, 10x aspirational)
- **Unified data representation** across storage, query, and output
- **Prompt cache optimization** through stable macro headers
- **LLM-native parsing** (S-expressions are pre-trained vocabulary)

### The Core Insight

```
Current: Graph → SQL → Sigils → LLM parses sigils
OMEGA:   Graph → S-expr → S-expr → LLM parses native lists
```

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      PROJECT OMEGA                              │
└─────────────────────────────────────────────────────────────────┘
                              │
    ┌─────────────────────────┼─────────────────────────────┐
    │                         │                             │
    ▼                         ▼                             ▼
┌───────────────┐    ┌───────────────────┐    ┌─────────────────┐
│ LispExporter  │    │ MacroSynthesizer  │    │  OmegaContext   │
│ (Translator)  │◄──►│   (Compressor)    │◄──►│    (Payload)    │
└───────────────┘    └───────────────────┘    └─────────────────┘
        │                     │                        │
        │                     │                        │
        └──────────┬──────────┴────────────┬──────────┘
                   │                       │
                   ▼                       ▼
          ┌───────────────┐       ┌───────────────┐
          │PatternDetector│       │SmartContext   │
          │(existing)     │       │Extractor      │
          └───────────────┘       │(existing)     │
                   │              └───────────────┘
                   ▼
          ┌───────────────┐
          │    MUbase     │
          │ (existing)    │
          └───────────────┘
```

---

## 3. Component Specifications

### 3.1 Component A: LispExporter

**File:** `src/mu/kernel/export/lisp.py`

The LispExporter converts MUbase graph data into strict S-expressions, replacing the sigil-based `MUTextExporter`.

#### Interface

```python
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mu.kernel.export.base import ExportOptions, ExportResult, Exporter
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


@dataclass
class LispExportOptions(ExportOptions):
    """Extended options for Lisp export."""

    include_header: bool = True
    """Include MU-Lisp standard library header."""

    macros: list[str] = field(default_factory=list)
    """Names of macros to enable (empty = core only)."""

    pretty_print: bool = True
    """Format with indentation for readability."""

    max_depth: int = 10
    """Maximum nesting depth before truncation."""


class LispExporter:
    """Export graph as Lisp S-expressions.

    Produces a token-efficient representation using nested lists
    that LLMs can parse natively without custom syntax.

    Example output:
        (mu-lisp :version "1.0"
          (module auth
            :deps [fastapi pydantic]
            (class AuthService
              :bases [BaseService]
              (defn authenticate [username:str password:str] -> User))
            (defn hash_password [raw:str] -> str)))
    """

    # Format metadata
    format_name: str = "lisp"
    file_extension: str = ".mulisp"
    description: str = "Lisp S-expression format (OMEGA compression)"

    # Core forms (always available)
    CORE_FORMS = {
        "module": "(module name :deps [deps...] body...)",
        "class": "(class name :bases [bases...] :attrs [attrs...] methods...)",
        "defn": "(defn name [params...] -> return-type :decorators [...])",
        "data": "(data name [fields...])",
        "const": "(const name value)",
    }

    def __init__(self) -> None:
        """Initialize the Lisp exporter."""
        self._indent_size = 2

    def export(
        self,
        mubase: MUbase,
        options: LispExportOptions | ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to Lisp S-expression format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.

        Returns:
            ExportResult with Lisp format output.
        """
        ...

    def _emit_header(self, version: str = "1.0") -> str:
        """Emit the MU-Lisp header with version and core forms."""
        ...

    def _module_to_sexpr(self, module_path: str, nodes: list[Node]) -> str:
        """Convert a module and its contents to S-expression."""
        ...

    def _class_to_sexpr(self, cls: Node, methods: list[Node]) -> str:
        """Convert a class to S-expression."""
        ...

    def _function_to_sexpr(self, func: Node) -> str:
        """Convert a function/method to S-expression."""
        ...

    def _escape_string(self, s: str) -> str:
        """Escape special characters in strings."""
        ...

    def _format_sexpr(self, sexpr: str, indent: int = 0) -> str:
        """Pretty-print an S-expression with proper indentation."""
        ...
```

#### Output Format Specification

```lisp
;; MU-Lisp v1.0 - Machine Understanding Semantic Format
;; Core forms: module, class, defn, data, const

(mu-lisp :version "1.0" :codebase "mu" :commit "abc123"

  (module mu.kernel.mubase
    :deps [duckdb pathlib typing]
    :file "src/mu/kernel/mubase.py"

    (class MUbase
      :bases [object]
      :attrs [db_path conn root_path]
      :complexity 45

      (defn __init__ [self db_path:Path] -> None)
      (defn build [self modules:list root_path:Path] -> None)
      (defn get_node [self node_id:str] -> Node|None)
      (defn get_nodes [self node_type:NodeType] -> list[Node])
      (defn get_dependencies [self node_id:str depth:int] -> list[Node])
      (defn close [self] -> None))

    (defn get_default_path [] -> Path))

  (module mu.intelligence.patterns
    :deps [re time collections]
    :file "src/mu/intelligence/patterns.py"

    (class PatternDetector
      :attrs [db MIN_FREQUENCY MIN_CONFIDENCE]

      (defn detect [self category:PatternCategory|None] -> PatternsResult)
      (defn _detect_api_patterns [self] -> list[Pattern]))))
```

#### Syntax Rules

| Element | S-Expression Form | Notes |
|---------|-------------------|-------|
| Module | `(module name :deps [...] body...)` | `:file` optional |
| Class | `(class name :bases [...] :attrs [...] methods...)` | All kwargs optional |
| Function | `(defn name [params...] -> return :decorators [...])` | Params as `name:type` |
| Dataclass | `(data name [field1:type field2:type])` | Shorthand for simple classes |
| Constant | `(const NAME value)` | Module-level constants |
| Async | `(defn-async name [...] -> type)` | Async variant |
| Static | `(defn-static name [...] -> type)` | Static method variant |

---

### 3.2 Component B: MacroSynthesizer

**File:** `src/mu/intelligence/synthesizer.py`

The MacroSynthesizer analyzes patterns and generates custom macros for repeated structures.

#### Interface

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mu.intelligence.models import Pattern, PatternsResult
    from mu.kernel.mubase import MUbase


class MacroTier(Enum):
    """Tiers of macro stability."""

    CORE = "core"
    """Built-in macros, always available (module, class, defn, data)."""

    STANDARD = "standard"
    """Common cross-codebase macros (api, component, test, hook)."""

    SYNTHESIZED = "synthesized"
    """Dynamically generated per-codebase macros."""


@dataclass
class MacroDefinition:
    """A macro definition for pattern compression.

    This is the CRITICAL interface for pattern-to-lisp translation.
    """

    name: str
    """Macro name (e.g., 'api', 'component', 'hook')."""

    tier: MacroTier
    """Stability tier of this macro."""

    signature: list[str]
    """Parameter names in order (e.g., ['method', 'path', 'name', 'params'])."""

    description: str
    """Human-readable description of what this macro represents."""

    pattern_source: str
    """Name of the pattern that generated this macro."""

    frequency: int
    """How many nodes this macro compresses."""

    expansion_template: str
    """Template showing what this macro expands to.

    Example for 'api' macro:
        (defn {name} [{params}] -> Response
          :decorators [app.{method}(\"{path}\")])
    """

    token_savings: int = 0
    """Estimated tokens saved by using this macro."""

    def to_lisp_def(self) -> str:
        """Generate the Lisp defmacro form.

        Returns:
            S-expression defining this macro.

        Example:
            (defmacro api [method path name params]
              \"REST API endpoint handler\"
              :expands-to \"(defn {name} [{params}] -> Response :decorators [...])\")
        """
        params = " ".join(self.signature)
        return f'(defmacro {self.name} [{params}]\n  "{self.description}")'

    def apply(self, node_data: dict) -> str:
        """Apply this macro to a node, producing compressed S-expr.

        Args:
            node_data: Dictionary with keys matching signature params.

        Returns:
            Macro invocation S-expression.

        Example:
            Input: {"method": "GET", "path": "/users", "name": "get_users", "params": []}
            Output: (api GET "/users" get_users [])
        """
        args = []
        for param in self.signature:
            value = node_data.get(param, "_")
            if isinstance(value, str) and " " in value:
                args.append(f'"{value}"')
            elif isinstance(value, list):
                args.append(f"[{' '.join(str(v) for v in value)}]")
            else:
                args.append(str(value))
        return f"({self.name} {' '.join(args)})"

    def to_dict(self) -> dict:
        """Serialize for JSON/storage."""
        return {
            "name": self.name,
            "tier": self.tier.value,
            "signature": self.signature,
            "description": self.description,
            "pattern_source": self.pattern_source,
            "frequency": self.frequency,
            "expansion_template": self.expansion_template,
            "token_savings": self.token_savings,
        }


@dataclass
class SynthesisResult:
    """Result of macro synthesis."""

    macros: list[MacroDefinition] = field(default_factory=list)
    """Generated macro definitions."""

    total_patterns_analyzed: int = 0
    """Number of patterns considered."""

    patterns_converted: int = 0
    """Number of patterns that became macros."""

    estimated_compression: float = 0.0
    """Estimated compression ratio (0.0 - 1.0)."""

    synthesis_time_ms: float = 0.0
    """Time taken for synthesis."""

    def get_header(self) -> str:
        """Generate the macro header for context injection.

        Returns stable core macros first, then synthesized macros.
        This ordering optimizes for prompt caching.
        """
        lines = [";; MU-Lisp Macro Definitions"]

        # Group by tier
        core = [m for m in self.macros if m.tier == MacroTier.CORE]
        standard = [m for m in self.macros if m.tier == MacroTier.STANDARD]
        synthesized = [m for m in self.macros if m.tier == MacroTier.SYNTHESIZED]

        if core:
            lines.append(";; Core (built-in)")
            for m in core:
                lines.append(m.to_lisp_def())

        if standard:
            lines.append("\n;; Standard (cross-codebase)")
            for m in standard:
                lines.append(m.to_lisp_def())

        if synthesized:
            lines.append("\n;; Synthesized (this codebase)")
            for m in synthesized:
                lines.append(m.to_lisp_def())

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize for JSON/storage."""
        return {
            "macros": [m.to_dict() for m in self.macros],
            "total_patterns_analyzed": self.total_patterns_analyzed,
            "patterns_converted": self.patterns_converted,
            "estimated_compression": round(self.estimated_compression, 3),
            "synthesis_time_ms": round(self.synthesis_time_ms, 2),
        }


class MacroSynthesizer:
    """Synthesize Lisp macros from detected patterns.

    The synthesizer bridges PatternDetector output to LispExporter input:

    1. Mining: Query PatternDetector for high-frequency patterns
    2. Analysis: Identify variable vs static parts of each pattern
    3. Synthesis: Generate MacroDefinition with signature and template
    4. Filtering: Keep only macros that provide significant compression

    Configuration:
        - MAX_SYNTHESIZED_MACROS: Limit dynamic macros (default: 5)
        - MIN_PATTERN_FREQUENCY: Minimum instances to justify macro (default: 10)
        - MIN_TOKEN_SAVINGS: Minimum tokens saved per instance (default: 5)
    """

    # Limits to ensure stability and cache efficiency
    MAX_SYNTHESIZED_MACROS = 5
    MIN_PATTERN_FREQUENCY = 10
    MIN_TOKEN_SAVINGS_PER_INSTANCE = 5
    MIN_NET_SAVINGS = 50  # Break-even threshold: macro must save more than it costs

    # Standard macros (hardcoded, Tier.STANDARD)
    STANDARD_MACROS = {
        "api": MacroDefinition(
            name="api",
            tier=MacroTier.STANDARD,
            signature=["method", "path", "name", "params"],
            description="REST API endpoint handler",
            pattern_source="http_method_handlers",
            frequency=0,
            expansion_template='(defn {name} [{params}] -> Response :decorators [app.{method}("{path}")])',
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
            from mu.intelligence.patterns import PatternDetector
            self._pattern_detector = PatternDetector(self.db)
        return self._pattern_detector

    def synthesize(
        self,
        include_standard: bool = True,
        max_synthesized: int | None = None,
    ) -> SynthesisResult:
        """Synthesize macros from codebase patterns.

        Args:
            include_standard: Include standard macros that match patterns.
            max_synthesized: Override MAX_SYNTHESIZED_MACROS limit.

        Returns:
            SynthesisResult with macro definitions.
        """
        ...

    def _analyze_pattern(self, pattern: Pattern) -> MacroDefinition | None:
        """Analyze a pattern and generate a macro if beneficial.

        Args:
            pattern: The detected pattern to analyze.

        Returns:
            MacroDefinition if pattern is macro-worthy, None otherwise.
        """
        ...

    def _extract_variable_parts(self, pattern: Pattern) -> list[str]:
        """Identify the variable parts of a pattern for macro signature.

        Args:
            pattern: The pattern to analyze.

        Returns:
            List of variable parameter names.
        """
        ...

    def _calculate_token_savings(self, macro: MacroDefinition) -> int:
        """Calculate estimated token savings from using a macro.

        Uses the break-even formula:
            Net Savings = (Instances × (OriginalTokens - MacroCallTokens)) - MacroDefinitionTokens

        A macro is only worth synthesizing if Net Savings > MIN_NET_SAVINGS (default: 50).

        Example:
            - API endpoint expanded: ~25 tokens
            - API macro call: ~8 tokens
            - Macro definition: ~15 tokens
            - 40 instances

            Net = (40 × (25 - 8)) - 15 = 680 - 15 = 665 tokens saved ✓

        Args:
            macro: The macro definition.

        Returns:
            Net tokens saved (negative means macro costs more than it saves).
        """
        ...

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
        ...
```

#### Pattern-to-Macro Mapping Rules

| Pattern Category | Standard Macro | Signature |
|------------------|----------------|-----------|
| `api` / `http_method_handlers` | `api` | `[method path name params]` |
| `components` | `component` | `[name props]` |
| `state_management` / hooks | `hook` | `[name deps returns]` |
| `testing` | `test` | `[name target]` |
| `architecture` / model | `model` | `[name fields]` |
| `architecture` / service | `service` | `[name deps methods]` |
| `architecture` / repository | `repo` | `[name entity]` |

---

### 3.3 Component C: OmegaContext

**File:** `src/mu/kernel/context/omega.py`

OmegaContext integrates LispExporter and MacroSynthesizer into the context extraction pipeline.

#### Interface

```python
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mu.intelligence.synthesizer import MacroDefinition, SynthesisResult
    from mu.kernel.context.models import ContextResult
    from mu.kernel.mubase import MUbase


@dataclass
class OmegaConfig:
    """Configuration for OMEGA context generation."""

    max_tokens: int = 8000
    """Maximum tokens for the complete output (header + body)."""

    header_budget_ratio: float = 0.15
    """Maximum ratio of budget for macro header (default: 15%)."""

    include_synthesized: bool = True
    """Include dynamically synthesized macros."""

    max_synthesized_macros: int = 5
    """Maximum synthesized macros to include."""

    enable_prompt_cache_optimization: bool = True
    """Order macros for prompt cache efficiency."""

    fallback_to_sigils: bool = False
    """Fall back to sigil format if OMEGA fails."""


@dataclass
class OmegaManifest:
    """Manifest describing the OMEGA payload.

    Included at the start of every OMEGA output for LLM comprehension.
    """

    version: str = "1.0"
    """MU-Lisp version."""

    codebase: str = ""
    """Codebase identifier."""

    commit: str = ""
    """Git commit hash (if available)."""

    core_macros: list[str] = field(default_factory=list)
    """Names of core macros used."""

    standard_macros: list[str] = field(default_factory=list)
    """Names of standard macros used."""

    synthesized_macros: list[str] = field(default_factory=list)
    """Names of synthesized macros used."""

    def to_sexpr(self) -> str:
        """Generate manifest as S-expression.

        Example:
            (mu-lisp :version "1.0" :codebase "mu" :commit "abc123"
              :core [module class defn data]
              :standard [api service]
              :synthesized [mcp-tool])
        """
        parts = [
            f'(mu-lisp :version "{self.version}"',
        ]
        if self.codebase:
            parts.append(f' :codebase "{self.codebase}"')
        if self.commit:
            parts.append(f' :commit "{self.commit[:7]}"')
        if self.core_macros:
            parts.append(f'\n  :core [{" ".join(self.core_macros)}]')
        if self.standard_macros:
            parts.append(f'\n  :standard [{" ".join(self.standard_macros)}]')
        if self.synthesized_macros:
            parts.append(f'\n  :synthesized [{" ".join(self.synthesized_macros)}]')
        parts.append(")")
        return "".join(parts)


@dataclass
class OmegaResult:
    """Result of OMEGA context extraction.

    Structured as Seed (header) + Body (payload) for optimal
    prompt cache utilization.
    """

    # The two-part payload
    seed: str
    """Macro definitions header (stable, cacheable)."""

    body: str
    """Compressed S-expression payload."""

    # Metadata
    manifest: OmegaManifest
    """Manifest describing the payload."""

    macros_used: list[MacroDefinition] = field(default_factory=list)
    """Macros applied in this context."""

    # Token accounting
    seed_tokens: int = 0
    """Tokens in the seed (header)."""

    body_tokens: int = 0
    """Tokens in the body (payload)."""

    total_tokens: int = 0
    """Total tokens (seed + body)."""

    # Compression stats
    original_tokens: int = 0
    """Tokens if exported as sigils."""

    compression_ratio: float = 0.0
    """Compression achieved (original / omega)."""

    # Standard context info
    nodes_included: int = 0
    """Number of nodes in the context."""

    extraction_stats: dict[str, Any] = field(default_factory=dict)
    """Debug/metrics info."""

    @property
    def full_output(self) -> str:
        """Get the complete OMEGA output (seed + body).

        Format:
            ;; MU-Lisp Macro Definitions
            (defmacro api [...] ...)
            ...

            ;; Codebase Context
            (mu-lisp :version "1.0" ...)
        """
        return f"{self.seed}\n\n;; Codebase Context\n{self.body}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "seed": self.seed,
            "body": self.body,
            "manifest": {
                "version": self.manifest.version,
                "codebase": self.manifest.codebase,
                "core_macros": self.manifest.core_macros,
                "standard_macros": self.manifest.standard_macros,
                "synthesized_macros": self.manifest.synthesized_macros,
            },
            "seed_tokens": self.seed_tokens,
            "body_tokens": self.body_tokens,
            "total_tokens": self.total_tokens,
            "compression_ratio": round(self.compression_ratio, 2),
            "nodes_included": self.nodes_included,
        }


class OmegaContextExtractor:
    """OMEGA-enhanced context extraction.

    Wraps SmartContextExtractor to produce OMEGA format output
    with macro compression for maximum token density.

    Usage:
        from mu.kernel.context.omega import OmegaContextExtractor, OmegaConfig

        extractor = OmegaContextExtractor(mubase, OmegaConfig(max_tokens=8000))
        result = extractor.extract("How does authentication work?")

        print(result.full_output)  # Complete OMEGA context
        print(f"Compression: {result.compression_ratio:.1f}x")
    """

    def __init__(
        self,
        mubase: MUbase,
        config: OmegaConfig | None = None,
    ) -> None:
        """Initialize the OMEGA context extractor.

        Args:
            mubase: The MUbase database.
            config: OMEGA configuration.
        """
        self.mubase = mubase
        self.config = config or OmegaConfig()

        # Lazy-loaded components
        self._synthesizer: MacroSynthesizer | None = None
        self._lisp_exporter: LispExporter | None = None
        self._smart_extractor: SmartContextExtractor | None = None

    def extract(self, question: str) -> OmegaResult:
        """Extract OMEGA-compressed context for a question.

        Args:
            question: Natural language question about the code.

        Returns:
            OmegaResult with seed (header) and body (payload).
        """
        ...

    def extract_for_task(self, task: str) -> OmegaResult:
        """Extract OMEGA context for a development task.

        Args:
            task: Task description (e.g., "Add rate limiting to API").

        Returns:
            OmegaResult optimized for the task.
        """
        ...

    def _synthesize_macros(self) -> SynthesisResult:
        """Run macro synthesis for the codebase."""
        ...

    def _select_macros_for_context(
        self,
        nodes: list[Node],
        available_macros: list[MacroDefinition],
    ) -> list[MacroDefinition]:
        """Select which macros to include based on context nodes.

        Only includes macros that will actually be used in the body.
        """
        ...

    def _generate_seed(
        self,
        macros: list[MacroDefinition],
        manifest: OmegaManifest,
    ) -> str:
        """Generate the seed (header) with macro definitions."""
        ...

    def _generate_body(
        self,
        nodes: list[Node],
        macros: list[MacroDefinition],
    ) -> str:
        """Generate the body with macro-compressed S-expressions."""
        ...

    def _count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken."""
        ...
```

---

## 4. Integration Points

### 4.1 MCP Server Updates

**File:** `src/mu/mcp/server.py` (update)

Add OMEGA-specific tools:

```python
@mcp.tool()
def mu_context_omega(
    question: str,
    max_tokens: int = 8000,
    include_synthesized: bool = True,
) -> dict:
    """Extract OMEGA-compressed context for a question.

    Returns S-expression format with macro compression for
    maximum token efficiency.

    Args:
        question: Question about the codebase
        max_tokens: Token budget (default 8000)
        include_synthesized: Include dynamic macros

    Returns:
        OmegaResult with seed, body, and compression stats
    """
    ...


@mcp.tool()
def mu_export_lisp(
    node_ids: list[str] | None = None,
    max_nodes: int | None = None,
) -> dict:
    """Export graph as Lisp S-expressions.

    Returns OMEGA format without macro compression.
    Use mu_context_omega for compressed output.
    """
    ...


@mcp.tool()
def mu_macros() -> dict:
    """Get available macros for this codebase.

    Returns core, standard, and synthesized macro definitions.
    """
    ...
```

### 4.2 CLI Updates

**File:** `src/mu/commands/kernel/export.py` (update)

```bash
# New format option
mu kernel export . --format lisp      # Raw S-expressions
mu kernel export . --format omega     # With macro compression

# Context with OMEGA
mu kernel context "How does auth work?" --format omega
mu kernel context "API endpoints" --format omega --no-synthesized
```

### 4.3 ExportManager Registration

**File:** `src/mu/kernel/export/base.py` (update)

```python
def get_default_manager() -> ExportManager:
    """Get an ExportManager with all default exporters registered."""
    from mu.kernel.export.cytoscape import CytoscapeExporter
    from mu.kernel.export.d2 import D2Exporter
    from mu.kernel.export.json_export import JSONExporter
    from mu.kernel.export.lisp import LispExporter  # NEW
    from mu.kernel.export.mermaid import MermaidExporter
    from mu.kernel.export.mu_text import MUTextExporter

    manager = ExportManager()
    manager.register(MUTextExporter())
    manager.register(JSONExporter())
    manager.register(MermaidExporter())
    manager.register(D2Exporter())
    manager.register(CytoscapeExporter())
    manager.register(LispExporter())  # NEW
    return manager
```

---

## 5. Data Models

### 5.1 New Models

**File:** `src/mu/intelligence/models.py` (additions)

```python
# Add to existing models.py

class MacroTier(Enum):
    """Tiers of macro stability for prompt cache optimization."""

    CORE = "core"
    STANDARD = "standard"
    SYNTHESIZED = "synthesized"


@dataclass
class MacroDefinition:
    """See Section 3.2 for full definition."""
    ...


@dataclass
class SynthesisResult:
    """See Section 3.2 for full definition."""
    ...
```

### 5.2 Context Models Update

**File:** `src/mu/kernel/context/models.py` (additions)

```python
@dataclass
class OmegaManifest:
    """See Section 3.3 for full definition."""
    ...


@dataclass
class OmegaResult:
    """See Section 3.3 for full definition."""
    ...
```

---

## 6. Test Specifications

### 6.1 Unit Tests

**File:** `tests/unit/test_lisp_exporter.py`

```python
class TestLispExporter:
    """Tests for LispExporter."""

    def test_export_empty_graph(self, empty_mubase):
        """Empty graph produces minimal output."""

    def test_export_single_module(self, simple_mubase):
        """Single module exports correctly."""

    def test_export_class_with_methods(self, class_mubase):
        """Class with methods produces nested S-expr."""

    def test_export_function_params(self, func_mubase):
        """Function parameters formatted as name:type."""

    def test_export_inheritance(self, inheritance_mubase):
        """Inheritance uses :bases keyword."""

    def test_export_decorators(self, decorated_mubase):
        """Decorators in :decorators list."""

    def test_escape_special_chars(self, exporter):
        """Special characters escaped in strings."""

    def test_pretty_print_indentation(self, exporter):
        """Pretty print produces readable output."""

    def test_max_depth_truncation(self, deep_mubase):
        """Deep nesting truncated at max_depth."""


class TestMacroDefinition:
    """Tests for MacroDefinition."""

    def test_to_lisp_def(self):
        """Generates valid defmacro form."""

    def test_apply_simple(self):
        """Apply with simple string values."""

    def test_apply_with_list(self):
        """Apply with list parameters."""

    def test_apply_with_spaces(self):
        """Strings with spaces get quoted."""


class TestMacroSynthesizer:
    """Tests for MacroSynthesizer."""

    def test_synthesize_empty_patterns(self, empty_mubase):
        """No patterns produces only core macros."""

    def test_synthesize_api_pattern(self, api_mubase):
        """API pattern produces api macro."""

    def test_synthesize_component_pattern(self, react_mubase):
        """Component pattern produces component macro."""

    def test_max_synthesized_limit(self, many_patterns_mubase):
        """Respects MAX_SYNTHESIZED_MACROS limit."""

    def test_min_frequency_filter(self, low_freq_mubase):
        """Filters patterns below MIN_PATTERN_FREQUENCY."""

    def test_token_savings_calculation(self, synthesizer):
        """Calculates token savings correctly."""

    def test_break_even_filter(self, synthesizer):
        """Rejects macros that don't meet MIN_NET_SAVINGS threshold.

        A macro with 3 instances saving 10 tokens each but costing 20 to define:
        Net = (3 × 10) - 20 = 10 tokens < 50 threshold → REJECTED
        """

    def test_profitable_macro_accepted(self, synthesizer):
        """Accepts macros that exceed MIN_NET_SAVINGS threshold.

        A macro with 20 instances saving 15 tokens each, costing 25 to define:
        Net = (20 × 15) - 25 = 275 tokens > 50 threshold → ACCEPTED
        """


class TestOmegaContextExtractor:
    """Tests for OmegaContextExtractor."""

    def test_extract_basic(self, omega_extractor):
        """Basic extraction produces seed + body."""

    def test_seed_body_separation(self, omega_extractor):
        """Seed contains macros, body contains data."""

    def test_compression_ratio(self, omega_extractor, sigil_extractor):
        """OMEGA achieves better compression than sigils."""

    def test_token_budget_respected(self, omega_extractor):
        """Total tokens within budget."""

    def test_manifest_generation(self, omega_extractor):
        """Manifest lists used macros."""

    def test_cache_optimization_ordering(self, omega_extractor):
        """Core macros come before synthesized."""
```

### 6.2 Integration Tests

**File:** `tests/integration/test_omega_integration.py`

```python
class TestOmegaIntegration:
    """End-to-end OMEGA tests."""

    def test_mu_codebase_compression(self, mu_mubase):
        """Test OMEGA on MU codebase itself."""

    def test_mcp_tool_integration(self, mcp_server):
        """mu_context_omega MCP tool works."""

    def test_cli_export_lisp(self, cli_runner):
        """CLI export --format lisp works."""

    def test_cli_context_omega(self, cli_runner):
        """CLI context --format omega works."""

    def test_roundtrip_parse(self, omega_extractor):
        """OMEGA output can be parsed back to structure."""
```

### 6.3 Benchmark Tests

**File:** `tests/benchmark/test_omega_compression.py`

```python
class TestOmegaCompression:
    """Compression ratio benchmarks."""

    @pytest.mark.benchmark
    def test_compression_vs_sigils(self, benchmark_mubase):
        """Measure compression vs sigil format."""

    @pytest.mark.benchmark
    def test_compression_with_macros(self, benchmark_mubase):
        """Measure additional compression from macros."""

    @pytest.mark.benchmark
    def test_token_density(self, benchmark_mubase):
        """Measure semantics per token."""
```

---

## 7. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Compression Ratio | 3-5x vs sigils | `original_tokens / omega_tokens` |
| Token Density | 2x improvement | Manual semantic scoring |
| Export Speed | <100ms for 1000 nodes | Benchmark tests |
| Macro Cache Hit | >80% header reuse | Prompt cache metrics |
| Test Coverage | >90% | pytest-cov |

---

## 8. Implementation Phases

### Phase 1: Lisp Substrate (Days 1-2)

- [ ] Create `src/mu/kernel/export/lisp.py`
- [ ] Implement `LispExporter` class
- [ ] Register in `ExportManager`
- [ ] Add CLI `--format lisp` option
- [ ] Write unit tests for `LispExporter`

### Phase 2: Macro Synthesis (Days 3-4)

- [ ] Create `src/mu/intelligence/synthesizer.py`
- [ ] Implement `MacroDefinition` dataclass
- [ ] Implement `MacroSynthesizer` class
- [ ] Add standard macro definitions
- [ ] Connect to `PatternDetector`
- [ ] Write unit tests for synthesis

### Phase 3: OMEGA Context (Days 5-6)

- [ ] Create `src/mu/kernel/context/omega.py`
- [ ] Implement `OmegaContextExtractor`
- [ ] Add `OmegaResult` and `OmegaManifest`
- [ ] Integrate with `SmartContextExtractor`
- [ ] Write integration tests

### Phase 4: Integration (Day 7)

- [ ] Add MCP tools (`mu_context_omega`, `mu_export_lisp`, `mu_macros`)
- [ ] Update CLI commands
- [ ] Run benchmarks on MU codebase
- [ ] Documentation updates
- [ ] Final testing and polish

---

## 9. Migration Strategy

### Backward Compatibility

- `mu compress` continues to output sigil format by default
- `mu kernel export --format mu` unchanged
- `mu kernel context` unchanged (still outputs sigil MU)

### New Commands

- `mu kernel export --format lisp` → raw S-expressions
- `mu kernel export --format omega` → S-expr with macros
- `mu kernel context --format omega` → OMEGA compressed context
- `mu macros` → list available macros

### Deprecation Path

None. Sigil format remains fully supported. OMEGA is additive.

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM struggles with S-expr | High | Fallback to sigils; A/B test with models |
| Macro instability hurts cache | Medium | Tiered macros; stable header ordering |
| Compression doesn't meet target | Medium | Aggressive macro synthesis; measure early |
| Complex implementation | Medium | Phased rollout; comprehensive tests |

---

## 11. References

- [MU Text Exporter](src/mu/kernel/export/mu_text.py) - Current sigil format
- [Pattern Detector](src/mu/intelligence/patterns.py) - Pattern mining
- [Smart Context Extractor](src/mu/kernel/context/smart.py) - Context pipeline
- [Export Base](src/mu/kernel/export/base.py) - Exporter protocol

---

## Appendix A: Example Transformations

### Before (Sigil Format)

```
!module mu.mcp.server
@deps [fastmcp, mu.client]

$@dataclass NodeInfo
  @attrs [id, type, name, qualified_name]

#mu_query(query: str) -> QueryResult
#mu_context(question: str) -> ContextResult
#async mu_build(path: str) -> BuildResult
```

### After (OMEGA Format)

```lisp
;; Macro Definitions (Seed)
(defmacro mcp-tool [name params returns]
  "MCP server tool endpoint")

;; Codebase Context (Body)
(mu-lisp :version "1.0" :codebase "mu"
  :standard [mcp-tool]

  (module mu.mcp.server
    :deps [fastmcp mu.client]

    (data NodeInfo [id type name qualified_name])

    (mcp-tool mu_query [query:str] QueryResult)
    (mcp-tool mu_context [question:str] ContextResult)
    (mcp-tool mu_build [path:str] BuildResult :async)))
```

### Token Comparison

| Format | Tokens | Reduction |
|--------|--------|-----------|
| Sigil | ~85 | baseline |
| OMEGA | ~55 | 35% |

---

**END OF PRD**
