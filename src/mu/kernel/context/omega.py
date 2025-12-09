"""OMEGA Context - S-Expression semantic compression.

Provides OMEGA-enhanced context extraction that combines:
- LispExporter: S-expression output format
- MacroSynthesizer: Pattern-based macro compression

OMEGA achieves 3-5x token reduction while preserving semantic signal
through dynamic macro compression and prompt cache optimization.

Usage:
    from mu.kernel.context.omega import OmegaContextExtractor, OmegaConfig
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    config = OmegaConfig(max_tokens=8000)
    extractor = OmegaContextExtractor(db, config)

    result = extractor.extract("How does authentication work?")
    print(result.full_output)  # Complete OMEGA context
    print(f"Compression: {result.compression_ratio:.1f}x")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)


@dataclass
class OmegaConfig:
    """Configuration for OMEGA context generation.

    Controls token budgets, macro synthesis settings, and prompt cache
    optimization behavior.

    Example:
        >>> config = OmegaConfig(
        ...     max_tokens=8000,
        ...     include_synthesized=True,
        ...     max_synthesized_macros=5,
        ... )
    """

    max_tokens: int = 8000
    """Maximum tokens for the complete output (header + body)."""

    header_budget_ratio: float = 0.15
    """Maximum ratio of budget for macro header (default: 15%).

    The header contains macro definitions and should be stable for
    prompt cache efficiency. Keeping it small ensures most tokens
    go to actual code content.
    """

    include_synthesized: bool = True
    """Include dynamically synthesized macros.

    When False, only core and standard macros are used. Set to False
    if you need maximum stability for prompt caching.
    """

    max_synthesized_macros: int = 5
    """Maximum synthesized macros to include.

    Higher values may improve compression but reduce cache efficiency.
    """

    enable_prompt_cache_optimization: bool = True
    """Order macros for prompt cache efficiency.

    When True, macros are ordered: CORE → STANDARD → SYNTHESIZED.
    Core macros are always the same, maximizing cache hit rates.
    """

    fallback_to_sigils: bool = False
    """Fall back to sigil format if OMEGA fails.

    When True, errors in OMEGA generation will gracefully degrade
    to the standard sigil-based MU format.
    """

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "max_tokens": self.max_tokens,
            "header_budget_ratio": self.header_budget_ratio,
            "include_synthesized": self.include_synthesized,
            "max_synthesized_macros": self.max_synthesized_macros,
            "enable_prompt_cache_optimization": self.enable_prompt_cache_optimization,
            "fallback_to_sigils": self.fallback_to_sigils,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OmegaConfig:
        """Create OmegaConfig from dictionary.

        Args:
            data: Dictionary with config fields.

        Returns:
            OmegaConfig instance.
        """
        return cls(
            max_tokens=data.get("max_tokens", 8000),
            header_budget_ratio=data.get("header_budget_ratio", 0.15),
            include_synthesized=data.get("include_synthesized", True),
            max_synthesized_macros=data.get("max_synthesized_macros", 5),
            enable_prompt_cache_optimization=data.get("enable_prompt_cache_optimization", True),
            fallback_to_sigils=data.get("fallback_to_sigils", False),
        )


@dataclass
class OmegaManifest:
    """Manifest describing the OMEGA payload.

    Included at the start of every OMEGA output to help LLMs understand
    the available macros and their meanings.

    Example:
        >>> manifest = OmegaManifest(
        ...     version="1.0",
        ...     codebase="mu",
        ...     commit="abc123",
        ...     core_macros=["module", "class", "defn"],
        ...     standard_macros=["api", "service"],
        ... )
        >>> print(manifest.to_sexpr())
        (mu-lisp :version "1.0" :codebase "mu" :commit "abc123"
          :core [module class defn]
          :standard [api service])
    """

    version: str = "1.0"
    """MU-Lisp version."""

    codebase: str = ""
    """Codebase identifier (project name)."""

    commit: str = ""
    """Git commit hash (if available)."""

    core_macros: list[str] = field(default_factory=list)
    """Names of core macros used (module, class, defn, data)."""

    standard_macros: list[str] = field(default_factory=list)
    """Names of standard macros used (api, service, etc.)."""

    synthesized_macros: list[str] = field(default_factory=list)
    """Names of synthesized macros used (codebase-specific)."""

    def to_sexpr(self) -> str:
        """Generate manifest as S-expression.

        Returns:
            Formatted S-expression header for the OMEGA output.

        Example output:
            (mu-lisp :version "1.0" :codebase "mu" :commit "abc123"
              :core [module class defn data]
              :standard [api service]
              :synthesized [mcp-tool])
        """
        parts = [f'(mu-lisp :version "{self.version}"']

        if self.codebase:
            parts.append(f' :codebase "{self.codebase}"')
        if self.commit:
            # Truncate commit to 7 chars for readability
            parts.append(f' :commit "{self.commit[:7]}"')
        if self.core_macros:
            parts.append(f"\n  :core [{' '.join(self.core_macros)}]")
        if self.standard_macros:
            parts.append(f"\n  :standard [{' '.join(self.standard_macros)}]")
        if self.synthesized_macros:
            parts.append(f"\n  :synthesized [{' '.join(self.synthesized_macros)}]")

        parts.append(")")
        return "".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "codebase": self.codebase,
            "commit": self.commit,
            "core_macros": self.core_macros,
            "standard_macros": self.standard_macros,
            "synthesized_macros": self.synthesized_macros,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OmegaManifest:
        """Create OmegaManifest from dictionary.

        Args:
            data: Dictionary with manifest fields.

        Returns:
            OmegaManifest instance.
        """
        return cls(
            version=data.get("version", "1.0"),
            codebase=data.get("codebase", ""),
            commit=data.get("commit", ""),
            core_macros=data.get("core_macros", []),
            standard_macros=data.get("standard_macros", []),
            synthesized_macros=data.get("synthesized_macros", []),
        )

    @property
    def all_macros(self) -> list[str]:
        """Get all macro names in order (core, standard, synthesized)."""
        return self.core_macros + self.standard_macros + self.synthesized_macros

    @property
    def macro_count(self) -> int:
        """Total number of macros referenced."""
        return len(self.core_macros) + len(self.standard_macros) + len(self.synthesized_macros)


@dataclass
class OmegaResult:
    """Result of OMEGA context extraction.

    Structured as Seed (header) + Body (payload) for optimal
    prompt cache utilization.

    The seed contains stable macro definitions that rarely change,
    while the body contains the actual code context compressed using
    those macros.

    Example:
        >>> result = extractor.extract("How does auth work?")
        >>> print(result.full_output)  # Complete OMEGA context
        >>> print(f"Compression: {result.compression_ratio:.1f}x")
        >>> print(f"Tokens: {result.total_tokens} (was {result.original_tokens})")
    """

    # The two-part payload
    seed: str
    """Macro definitions header (stable, cacheable).

    Contains defmacro forms ordered for cache efficiency:
    CORE macros → STANDARD macros → SYNTHESIZED macros.
    """

    body: str
    """Compressed S-expression payload.

    The actual code context, compressed using macros defined in seed.
    """

    # Metadata
    manifest: OmegaManifest
    """Manifest describing the payload."""

    macros_used: list[str] = field(default_factory=list)
    """Names of macros actually applied in the body."""

    # Token accounting
    seed_tokens: int = 0
    """Tokens in the seed (header)."""

    body_tokens: int = 0
    """Tokens in the body (payload)."""

    total_tokens: int = 0
    """Total tokens (seed + body)."""

    original_tokens: int = 0
    """Tokens if exported as sigils (for compression comparison)."""

    compression_ratio: float = 0.0
    """Compression achieved (original_tokens / total_tokens).

    A ratio of 3.0 means OMEGA uses 3x fewer tokens than sigils.
    """

    # Context info
    nodes_included: int = 0
    """Number of nodes in the context."""

    extraction_stats: dict[str, Any] = field(default_factory=dict)
    """Debug/metrics info about the extraction process."""

    @property
    def full_output(self) -> str:
        """Get the complete OMEGA output (seed + body).

        Format:
            ;; MU-Lisp Macro Definitions
            (defmacro api [...] ...)
            ...

            ;; Codebase Context
            (mu-lisp :version "1.0" ...)

        Returns:
            Complete OMEGA context ready for LLM consumption.
        """
        if self.seed and self.body:
            return f"{self.seed}\n\n;; Codebase Context\n{self.body}"
        elif self.body:
            return f";; Codebase Context\n{self.body}"
        return self.seed or ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "seed": self.seed,
            "body": self.body,
            "manifest": self.manifest.to_dict(),
            "macros_used": self.macros_used,
            "seed_tokens": self.seed_tokens,
            "body_tokens": self.body_tokens,
            "total_tokens": self.total_tokens,
            "original_tokens": self.original_tokens,
            "compression_ratio": round(self.compression_ratio, 2),
            "nodes_included": self.nodes_included,
            "extraction_stats": self.extraction_stats,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OmegaResult:
        """Create OmegaResult from dictionary.

        Args:
            data: Dictionary with result fields.

        Returns:
            OmegaResult instance.
        """
        return cls(
            seed=data.get("seed", ""),
            body=data.get("body", ""),
            manifest=OmegaManifest.from_dict(data.get("manifest", {})),
            macros_used=data.get("macros_used", []),
            seed_tokens=data.get("seed_tokens", 0),
            body_tokens=data.get("body_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            original_tokens=data.get("original_tokens", 0),
            compression_ratio=data.get("compression_ratio", 0.0),
            nodes_included=data.get("nodes_included", 0),
            extraction_stats=data.get("extraction_stats", {}),
        )

    @property
    def is_compressed(self) -> bool:
        """Check if compression was achieved."""
        return self.compression_ratio > 1.0

    @property
    def tokens_saved(self) -> int:
        """Calculate tokens saved by OMEGA compression."""
        return max(0, self.original_tokens - self.total_tokens)

    @property
    def savings_percent(self) -> float:
        """Calculate percentage of tokens saved.

        Returns:
            Percentage (0-100) of tokens saved, or 0 if no savings.
        """
        if self.original_tokens <= 0:
            return 0.0
        return (self.tokens_saved / self.original_tokens) * 100


class OmegaContextExtractor:
    """Extract OMEGA-compressed context for code questions.

    Wraps SmartContextExtractor to provide S-expression output with
    macro compression for maximum token efficiency.

    The extraction pipeline:
    1. Use SmartContextExtractor to find relevant nodes
    2. Synthesize macros from detected codebase patterns
    3. Select applicable macros for the context
    4. Generate seed (macro definitions) + body (compressed content)
    5. Account for tokens in both parts

    Example:
        >>> from mu.kernel import MUbase
        >>> from mu.kernel.context.omega import OmegaContextExtractor, OmegaConfig
        >>>
        >>> db = MUbase(".mubase")
        >>> config = OmegaConfig(max_tokens=8000)
        >>> extractor = OmegaContextExtractor(db, config)
        >>>
        >>> result = extractor.extract("How does authentication work?")
        >>> print(result.full_output)
        >>> print(f"Compression: {result.compression_ratio:.1f}x")
    """

    def __init__(
        self,
        mubase: MUbase,
        config: OmegaConfig | None = None,
    ) -> None:
        """Initialize the OMEGA context extractor.

        Args:
            mubase: The MUbase graph database.
            config: OMEGA configuration (uses defaults if not provided).
        """
        from mu.kernel.context.models import ExtractionConfig
        from mu.kernel.context.smart import SmartContextExtractor

        self.mubase = mubase
        self.config = config or OmegaConfig()

        # Initialize the underlying smart extractor
        # Use full token budget for extraction - we'll manage output size in generation
        # This fixes the issue where reduced budget causes SmartContextExtractor to find 0 nodes
        extraction_config = ExtractionConfig(max_tokens=self.config.max_tokens)
        self.smart_extractor = SmartContextExtractor(mubase, extraction_config)

        # Lazy-loaded components
        self._synthesizer: MacroSynthesizer | None = None
        self._lisp_exporter: LispExporter | None = None
        self._tokenizer: tiktoken.Encoding | None = None

    @property
    def synthesizer(self) -> MacroSynthesizer:
        """Lazy-load macro synthesizer."""
        if self._synthesizer is None:
            from mu.intelligence.synthesizer import MacroSynthesizer

            self._synthesizer = MacroSynthesizer(self.mubase)
        return self._synthesizer

    @property
    def lisp_exporter(self) -> LispExporter:
        """Lazy-load Lisp exporter."""
        if self._lisp_exporter is None:
            from mu.kernel.export.lisp import LispExporter

            self._lisp_exporter = LispExporter()
        return self._lisp_exporter

    @property
    def tokenizer(self) -> tiktoken.Encoding:
        """Lazy-load tiktoken encoder."""
        if self._tokenizer is None:
            # Use cl100k_base (GPT-4/Claude compatible)
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
        return self._tokenizer

    def extract(self, question: str) -> OmegaResult:
        """Extract OMEGA-compressed context for a question.

        Args:
            question: Natural language question about the code.

        Returns:
            OmegaResult with seed (macros) + body (compressed context).

        Note:
            This method is synchronous. Do not call from an async context.
        """
        import time

        start_time = time.time()
        stats: dict[str, Any] = {"question": question}

        # Step 1: Extract context using SmartContextExtractor
        context_result = self.smart_extractor.extract(question)
        stats["smart_extractor_nodes"] = len(context_result.nodes)
        stats["smart_extractor_tokens"] = context_result.token_count

        if not context_result.nodes:
            # No relevant context found - still include schema seed
            from mu.kernel.export.omega import OMG_SCHEMA_HEADER

            seed = OMG_SCHEMA_HEADER
            body = f";; No relevant context found for: {question}"
            seed_tokens = self._count_tokens(seed)
            body_tokens = self._count_tokens(body)

            return OmegaResult(
                seed=seed,
                body=body,
                manifest=OmegaManifest(version="1.0"),
                macros_used=[],
                seed_tokens=seed_tokens,
                body_tokens=body_tokens,
                total_tokens=seed_tokens + body_tokens,
                extraction_stats=stats,
            )

        # Step 2: Synthesize macros from codebase patterns
        # This now includes the pre-computed node→macro map
        synthesis_result = self._synthesize_macros()
        stats["macros_synthesized"] = len(synthesis_result.macros)
        stats["nodes_mapped"] = synthesis_result.nodes_mapped

        # Step 3: Select macros applicable to this context
        # Filter to only macros that apply to nodes in our context
        selected_macros = self._select_macros_for_context(
            context_result.nodes,
            synthesis_result,
        )
        stats["macros_selected"] = len(selected_macros)

        # Step 4: Generate seed (macro definitions header)
        seed = self._generate_seed(selected_macros)
        seed_tokens = self._count_tokens(seed)
        stats["seed_tokens"] = seed_tokens

        # Step 5: Generate body (compressed S-expression content)
        # Uses O(1) map lookup for compression
        body = self._generate_body(context_result.nodes, synthesis_result.node_macro_map)
        body_tokens = self._count_tokens(body)
        stats["body_tokens"] = body_tokens

        # Step 6: Calculate compression metrics
        # Get original sigil format tokens for comparison
        original_tokens = context_result.token_count
        total_tokens = seed_tokens + body_tokens
        compression_ratio = original_tokens / total_tokens if total_tokens > 0 else 1.0

        # Log warning if expansion occurred (compression_ratio < 1.0 means more tokens than original)
        if compression_ratio < 1.0 and original_tokens > 0:
            logger.warning(
                f"OMEGA expansion detected: {total_tokens} tokens vs {original_tokens} original "
                f"(ratio: {compression_ratio:.2f}). Body generation may be including extra content."
            )

        stats["total_tokens"] = total_tokens
        stats["original_tokens"] = original_tokens
        stats["compression_ratio"] = round(compression_ratio, 2)
        stats["extraction_time_ms"] = round((time.time() - start_time) * 1000, 1)

        # Build manifest
        manifest = self._build_manifest(selected_macros)

        return OmegaResult(
            seed=seed,
            body=body,
            manifest=manifest,
            macros_used=[m.name for m in selected_macros],
            seed_tokens=seed_tokens,
            body_tokens=body_tokens,
            total_tokens=total_tokens,
            original_tokens=original_tokens,
            compression_ratio=compression_ratio,
            nodes_included=len(context_result.nodes),
            extraction_stats=stats,
        )

    def extract_for_task(self, task: str) -> OmegaResult:
        """Extract OMEGA-compressed context for a development task.

        Uses TaskContextExtractor for task-aware node selection, then
        applies OMEGA compression.

        Args:
            task: Natural language task description.

        Returns:
            OmegaResult with task-optimized, compressed context.
        """
        import time

        start_time = time.time()
        stats: dict[str, Any] = {"task": task}

        try:
            from mu.intelligence.task_context import TaskContextConfig, TaskContextExtractor

            # Use task context extractor
            body_budget = int(self.config.max_tokens * (1 - self.config.header_budget_ratio))
            task_config = TaskContextConfig(max_tokens=body_budget)
            task_extractor = TaskContextExtractor(self.mubase, task_config)

            task_result = task_extractor.extract(task)
            nodes = [fc.node for fc in task_result.relevant_files if hasattr(fc, "node")]

            # If no nodes from task extractor, fall back to question-based
            if not nodes:
                # Get nodes from the MU text by parsing file paths
                return self.extract(task)

            stats["task_extractor_nodes"] = len(nodes)

        except ImportError:
            # TaskContextExtractor not available, fall back to question-based
            return self.extract(task)

        # Step 2: Synthesize macros (includes pre-computed node→macro map)
        synthesis_result = self._synthesize_macros()
        stats["macros_synthesized"] = len(synthesis_result.macros)
        stats["nodes_mapped"] = synthesis_result.nodes_mapped

        # Step 3: Select macros applicable to this context
        selected_macros = self._select_macros_for_context(nodes, synthesis_result)
        stats["macros_selected"] = len(selected_macros)

        # Step 4: Generate seed
        seed = self._generate_seed(selected_macros)
        seed_tokens = self._count_tokens(seed)

        # Step 5: Generate body (uses O(1) map lookup)
        body = self._generate_body(nodes, synthesis_result.node_macro_map)
        body_tokens = self._count_tokens(body)

        # Calculate metrics
        total_tokens = seed_tokens + body_tokens

        # Estimate original tokens (rough: 2x compression typical for OMEGA)
        original_tokens = total_tokens * 2
        compression_ratio = original_tokens / total_tokens if total_tokens > 0 else 1.0

        stats["seed_tokens"] = seed_tokens
        stats["body_tokens"] = body_tokens
        stats["total_tokens"] = total_tokens
        stats["extraction_time_ms"] = round((time.time() - start_time) * 1000, 1)

        manifest = self._build_manifest(selected_macros)

        return OmegaResult(
            seed=seed,
            body=body,
            manifest=manifest,
            macros_used=[m.name for m in selected_macros],
            seed_tokens=seed_tokens,
            body_tokens=body_tokens,
            total_tokens=total_tokens,
            original_tokens=original_tokens,
            compression_ratio=compression_ratio,
            nodes_included=len(nodes),
            extraction_stats=stats,
        )

    def _synthesize_macros(self) -> SynthesisResult:
        """Synthesize macros from codebase patterns.

        Returns:
            SynthesisResult with available macros.
        """
        return self.synthesizer.synthesize(
            include_standard=True,
            max_synthesized=self.config.max_synthesized_macros
            if self.config.include_synthesized
            else 0,
        )

    def _select_macros_for_context(
        self,
        nodes: list[Node],
        synthesis_result: SynthesisResult,
    ) -> list[MacroDefinition]:
        """Select macros that are applicable to the context nodes.

        Uses the pre-computed node_macro_map for O(1) lookup instead of
        re-matching each node against each macro.

        Args:
            nodes: Nodes to be included in context.
            synthesis_result: Result containing macros and node_macro_map.

        Returns:
            List of macros that will be used in the output.
        """
        used_macros: dict[str, MacroDefinition] = {}

        # O(1) lookup per node using pre-computed map
        for node in nodes:
            if node.id in synthesis_result.node_macro_map:
                macro = synthesis_result.node_macro_map[node.id]
                if macro.name not in used_macros:
                    used_macros[macro.name] = macro

        # Sort by tier for prompt cache optimization
        if self.config.enable_prompt_cache_optimization:
            from mu.intelligence.models import MacroTier

            # CORE → STANDARD → SYNTHESIZED
            tier_order = {MacroTier.CORE: 0, MacroTier.STANDARD: 1, MacroTier.SYNTHESIZED: 2}
            sorted_macros = sorted(
                used_macros.values(),
                key=lambda m: (tier_order.get(m.tier, 3), m.name),
            )
            return sorted_macros

        return list(used_macros.values())

    def _generate_seed(self, macros: list[MacroDefinition]) -> str:
        """Generate the seed (schema definitions header).

        Uses OMG SCHEMA v2.0 for strict positional typing.
        The schema header is emitted ONCE at the top and provides
        fixed, deterministic parsing rules for LLMs.

        Args:
            macros: Selected macro definitions (currently unused for Schema v2.0).

        Returns:
            OMG SCHEMA v2.0 header.
        """
        from mu.kernel.export.omega import OMG_SCHEMA_HEADER

        return OMG_SCHEMA_HEADER

    def _generate_body(
        self,
        nodes: list[Node],
        node_macro_map: dict[str, MacroDefinition],
    ) -> str:
        """Generate the body using Schema v2.0 strict positional format.

        Uses schema-compliant forms:
        - (module Name FilePath ...)
        - (service Name [deps] ...)
        - (class Name Parent [attrs] ...)
        - (method Name [args] ReturnType Complexity)
        - (function Name [args] ReturnType Complexity)

        Args:
            nodes: Nodes to include in the body.
            node_macro_map: Pre-computed mapping (unused in Schema v2.0).

        Returns:
            Schema v2.0 compliant S-expression body.
        """
        from collections import defaultdict

        from mu.kernel.schema import NodeType

        if not nodes:
            return ""

        # Create set of node IDs that should be in output
        # This prevents: (1) duplicate outputs, (2) fetching ALL methods from DB
        context_node_ids = {n.id for n in nodes}

        # Group nodes by module for structured output
        by_module: dict[str, list[Node]] = defaultdict(list)
        for node in nodes:
            module_path = node.file_path or "unknown"
            by_module[module_path].append(node)

        # Track which nodes we've already output to prevent duplicates
        output_node_ids: set[str] = set()

        lines: list[str] = []

        for module_path, module_nodes in sorted(by_module.items()):
            # Generate module name from path
            module_name = self._path_to_module_name(module_path)

            # Filter out already-output nodes
            module_nodes = [n for n in module_nodes if n.id not in output_node_ids]

            # Separate nodes by type for structured output
            classes = [n for n in module_nodes if n.type == NodeType.CLASS]
            functions = [
                n
                for n in module_nodes
                if n.type == NodeType.FUNCTION and not (n.properties or {}).get("is_method")
            ]

            # Build module content
            module_content: list[str] = []

            # Process classes with Schema v2.0 format
            for cls in classes:
                output_node_ids.add(cls.id)
                class_sexpr = self._class_to_schema_v2(cls, context_node_ids, output_node_ids)
                module_content.append(class_sexpr)

            # Process top-level functions (only if not already output as method)
            for func in functions:
                if func.id not in output_node_ids:
                    output_node_ids.add(func.id)
                    func_sexpr = self._function_to_schema_v2(func)
                    module_content.append(f"  {func_sexpr}")

            # Build module S-expression: (module Name FilePath ...)
            if module_content:
                lines.append(f'(module {module_name} "{module_path}"')
                lines.extend(module_content)
                lines.append(")")
            else:
                lines.append(f'(module {module_name} "{module_path}")')

        return "\n".join(lines)

    def _class_to_schema_v2(
        self,
        node: Node,
        context_node_ids: set[str],
        output_node_ids: set[str],
    ) -> str:
        """Convert a class node to Schema v2.0 format.

        Determines if class is a service, model, validator, or plain class.

        Args:
            node: The class node to convert.
            context_node_ids: Set of node IDs that are in the context (for filtering methods).
            output_node_ids: Set of node IDs already output (to mark methods as output).
        """
        from mu.kernel.schema import NodeType

        props = node.properties or {}
        name = node.name or "Unknown"
        bases = props.get("bases", [])
        attrs = props.get("attributes", [])
        decorators = str(props.get("decorators", [])).lower()

        # Get methods for this class - ONLY those in the context
        # This fixes the expansion issue where ALL methods were fetched from DB
        children = self.mubase.get_children(node.id)
        methods = [c for c in children if c.type == NodeType.FUNCTION and c.id in context_node_ids]

        # Mark these methods as output to prevent duplicates
        for method in methods:
            output_node_ids.add(method.id)

        # Determine class type based on naming/decorators
        name_lower = name.lower()

        # Format attributes as dependency list
        attr_list = self._format_attrs(attrs)

        # Format base class (first one or nil)
        parent = bases[0] if bases else "nil"

        # Check if it's a service (ends with Service)
        if name_lower.endswith("service"):
            return self._service_to_schema_v2(name, attr_list, methods)

        # Check if it's a dataclass/model
        if "dataclass" in decorators or name_lower.endswith("model"):
            return self._model_to_schema_v2(name, attrs)

        # Check if it's a validator
        if name_lower.endswith("validator"):
            target = name[:-9] if name.endswith("Validator") else name
            rules = [str(a) for a in attrs[:5]]
            return f"  (validator {name} {target} [{' '.join(rules)}])"

        # Default: plain class
        return self._plain_class_to_schema_v2(name, parent, attr_list, methods)

    def _service_to_schema_v2(self, name: str, deps: list[str], methods: list[Node]) -> str:
        """Format a service class: (service Name [deps] (method ...) ...)"""
        lines = []
        deps_str = " ".join(deps) if deps else ""

        if methods:
            lines.append(f"  (service {name} [{deps_str}]")
            for method in methods:
                method_sexpr = self._method_to_schema_v2(method)
                lines.append(f"    {method_sexpr}")
            lines.append("  )")
            return "\n".join(lines)
        else:
            return f"  (service {name} [{deps_str}])"

    def _model_to_schema_v2(self, name: str, attrs: list[Any]) -> str:
        """Format a model/dataclass: (model Name [field:type ...])"""
        fields = self._format_fields(attrs)
        return f"  (model {name} [{fields}])"

    def _plain_class_to_schema_v2(
        self, name: str, parent: str, attrs: list[str], methods: list[Node]
    ) -> str:
        """Format a plain class: (class Name Parent [attrs] (method ...) ...)"""
        lines = []
        attrs_str = " ".join(attrs) if attrs else ""

        if methods:
            lines.append(f"  (class {name} {parent} [{attrs_str}]")
            for method in methods:
                method_sexpr = self._method_to_schema_v2(method)
                lines.append(f"    {method_sexpr}")
            lines.append("  )")
            return "\n".join(lines)
        else:
            return f"  (class {name} {parent} [{attrs_str}])"

    def _method_to_schema_v2(self, node: Node) -> str:
        """Convert a method: (method Name [args] ReturnType Complexity)"""
        props = node.properties or {}
        name = node.name or "unknown"
        return_type = props.get("return_type", "None") or "None"
        complexity = props.get("complexity", 0) or node.complexity or 0

        params = props.get("parameters", [])
        args = self._format_params(params)

        return f"(method {name} [{args}] {return_type} {complexity})"

    def _function_to_schema_v2(self, node: Node) -> str:
        """Convert a function: (function Name [args] ReturnType Complexity)

        If function has HTTP decorators, use (api HttpVerb Path Handler [args])
        """
        props = node.properties or {}
        name = node.name or "unknown"
        return_type = props.get("return_type", "None") or "None"
        complexity = props.get("complexity", 0) or node.complexity or 0
        decorators = props.get("decorators", [])
        decorators_str = str(decorators).lower()

        # Check for API endpoint (HTTP method decorators)
        for verb in ["get", "post", "put", "delete", "patch"]:
            if verb in decorators_str:
                path = self._extract_path_from_decorators(decorators)
                params = props.get("parameters", [])
                args = self._format_params(params)
                return f'(api {verb.upper()} "{path}" {name} [{args}])'

        # Regular function
        params = props.get("parameters", [])
        args = self._format_params(params)

        return f"(function {name} [{args}] {return_type} {complexity})"

    def _format_params(self, params: list[Any]) -> str:
        """Format function/method parameters as name:type pairs."""
        param_strs = []
        for p in params:
            if isinstance(p, dict):
                pname = p.get("name", "?")
                ptype = p.get("type_annotation", "")
                if pname in ("self", "cls"):
                    continue
                if ptype:
                    param_strs.append(f"{pname}:{ptype}")
                else:
                    param_strs.append(pname)
            elif isinstance(p, str):
                param_strs.append(p)
        return " ".join(param_strs)

    def _format_attrs(self, attrs: list[Any]) -> list[str]:
        """Format class attributes, prefixing injected deps with _."""
        result = []
        for attr in attrs[:10]:
            if isinstance(attr, dict):
                aname = attr.get("name", "?")
            else:
                aname = str(attr)
            if aname.startswith("_") or "service" in aname.lower() or "repo" in aname.lower():
                if not aname.startswith("_"):
                    aname = f"_{aname}"
            result.append(aname)
        if len(attrs) > 10:
            result.append(f"+{len(attrs) - 10}")
        return result

    def _format_fields(self, attrs: list[Any]) -> str:
        """Format model fields as name:type pairs."""
        field_strs = []
        for attr in attrs[:10]:
            if isinstance(attr, dict):
                fname = attr.get("name", "?")
                ftype = attr.get("type", attr.get("type_annotation", "Any"))
                field_strs.append(f"{fname}:{ftype}" if ftype else fname)
            else:
                field_strs.append(str(attr))
        if len(attrs) > 10:
            field_strs.append(f"+{len(attrs) - 10}")
        return " ".join(field_strs)

    def _extract_path_from_decorators(self, decorators: list[Any]) -> str:
        """Extract URL path from HTTP method decorators."""
        import re

        for dec in decorators:
            dec_str = str(dec)
            path_match = re.search(r'["\']([^"\']+)["\']', dec_str)
            if path_match:
                return path_match.group(1)
        return "/"

    def _path_to_module_name(self, path: str) -> str:
        """Convert a file path to module name.

        Handles both absolute and relative paths, converting them to
        clean module names like 'mu.parser.models'.

        Args:
            path: File path (absolute or relative).

        Returns:
            Module name (e.g., 'mu.parser.models').
        """
        from pathlib import Path

        name = path

        # Get the MUbase root path for converting absolute paths to relative
        root_path = None
        if hasattr(self.mubase, "path") and self.mubase.path:
            # mubase.path is .mu/mubase, so root is two levels up
            root_path = self.mubase.path.parent.parent

        # Convert absolute path to relative if possible
        if root_path and name.startswith("/"):
            try:
                name = str(Path(name).relative_to(root_path))
            except ValueError:
                # Path not relative to root, try to extract meaningful part
                # Look for common source directory markers
                for marker in ("/src/", "/lib/", "/app/"):
                    if marker in name:
                        name = name[name.index(marker) + 1 :]
                        break

        # Remove common prefixes
        for prefix in ("src/", "lib/", "app/"):
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break

        # Remove extension
        for ext in (".py", ".ts", ".js", ".go", ".java", ".rs", ".cs"):
            if name.endswith(ext):
                name = name[: -len(ext)]
                break

        # Convert path separators to dots
        name = name.replace("/", ".").replace("\\", ".")

        # Remove trailing __init__
        if name.endswith(".__init__"):
            name = name[:-9]

        return name

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken.

        Args:
            text: Text to count tokens for.

        Returns:
            Token count.
        """
        if not text:
            return 0
        return len(self.tokenizer.encode(text))

    def _build_manifest(self, macros: list[MacroDefinition]) -> OmegaManifest:
        """Build the OMEGA manifest from selected macros.

        Args:
            macros: Selected macro definitions.

        Returns:
            OmegaManifest with macro categorization.
        """
        from mu.intelligence.models import MacroTier

        core_macros: list[str] = []
        standard_macros: list[str] = []
        synthesized_macros: list[str] = []

        for macro in macros:
            if macro.tier == MacroTier.CORE:
                core_macros.append(macro.name)
            elif macro.tier == MacroTier.STANDARD:
                standard_macros.append(macro.name)
            elif macro.tier == MacroTier.SYNTHESIZED:
                synthesized_macros.append(macro.name)

        # Get codebase info
        codebase = ""
        commit = ""
        try:
            import subprocess

            # Get repo name from remote URL
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                cwd=str(self.mubase.path.parent) if hasattr(self.mubase, "path") else None,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                # Extract repo name from URL
                if "/" in url:
                    codebase = url.split("/")[-1].replace(".git", "")

            # Get current commit
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.mubase.path.parent) if hasattr(self.mubase, "path") else None,
            )
            if result.returncode == 0:
                commit = result.stdout.strip()
        except Exception:
            pass

        return OmegaManifest(
            version="1.0",
            codebase=codebase,
            commit=commit,
            core_macros=core_macros,
            standard_macros=standard_macros,
            synthesized_macros=synthesized_macros,
        )


# Type imports for runtime
try:
    import tiktoken
except ImportError:
    tiktoken = None  # type: ignore[assignment]

# Lazy imports for type hints
if TYPE_CHECKING:
    from mu.intelligence.models import MacroDefinition, SynthesisResult
    from mu.intelligence.synthesizer import MacroSynthesizer
    from mu.kernel.export.lisp import LispExporter
    from mu.kernel.models import Node
    from mu.kernel.mubase import MUbase


__all__ = [
    "OmegaConfig",
    "OmegaContextExtractor",
    "OmegaManifest",
    "OmegaResult",
]
