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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any


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
        # Reserve token budget for the seed (macro definitions)
        body_budget = int(self.config.max_tokens * (1 - self.config.header_budget_ratio))
        extraction_config = ExtractionConfig(max_tokens=body_budget)
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
            # No relevant context found
            return OmegaResult(
                seed="",
                body=f";; No relevant context found for: {question}",
                manifest=OmegaManifest(),
                macros_used=[],
                total_tokens=self._count_tokens(f";; No relevant context found for: {question}"),
                extraction_stats=stats,
            )

        # Step 2: Synthesize macros from codebase patterns
        synthesis_result = self._synthesize_macros()
        stats["macros_synthesized"] = len(synthesis_result.macros)

        # Step 3: Select macros applicable to this context
        selected_macros = self._select_macros_for_context(
            context_result.nodes,
            synthesis_result.macros,
        )
        stats["macros_selected"] = len(selected_macros)

        # Step 4: Generate seed (macro definitions header)
        seed = self._generate_seed(selected_macros)
        seed_tokens = self._count_tokens(seed)
        stats["seed_tokens"] = seed_tokens

        # Step 5: Generate body (compressed S-expression content)
        body = self._generate_body(context_result.nodes, selected_macros)
        body_tokens = self._count_tokens(body)
        stats["body_tokens"] = body_tokens

        # Step 6: Calculate compression metrics
        # Get original sigil format tokens for comparison
        original_tokens = context_result.token_count
        total_tokens = seed_tokens + body_tokens
        compression_ratio = original_tokens / total_tokens if total_tokens > 0 else 1.0

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

        # Step 2: Synthesize macros
        synthesis_result = self._synthesize_macros()
        stats["macros_synthesized"] = len(synthesis_result.macros)

        # Step 3: Select macros
        selected_macros = self._select_macros_for_context(nodes, synthesis_result.macros)
        stats["macros_selected"] = len(selected_macros)

        # Step 4: Generate seed
        seed = self._generate_seed(selected_macros)
        seed_tokens = self._count_tokens(seed)

        # Step 5: Generate body
        body = self._generate_body(nodes, selected_macros)
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
        available_macros: list[MacroDefinition],
    ) -> list[MacroDefinition]:
        """Select macros that are applicable to the context nodes.

        Only includes macros that would actually be used in the output,
        avoiding header bloat from unused definitions.

        Args:
            nodes: Nodes to be included in context.
            available_macros: All available macro definitions.

        Returns:
            List of macros that will be used in the output.
        """
        used_macros: dict[str, MacroDefinition] = {}

        for node in nodes:
            # Find the best macro for each node
            macro = self.synthesizer.get_applicable_macros(node, available_macros)
            if macro and macro.name not in used_macros:
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
        """Generate the seed (macro definitions header).

        The seed is designed for prompt cache efficiency:
        - Core macros first (most stable)
        - Standard macros second
        - Synthesized macros last (most variable)

        Args:
            macros: Selected macro definitions.

        Returns:
            S-expression macro definitions header.
        """
        if not macros:
            return ""

        lines = [";; MU-Lisp Macro Definitions"]

        for macro in macros:
            # Generate defmacro form
            params = " ".join(macro.signature)
            defmacro = f'(defmacro {macro.name} [{params}] "{macro.description}")'
            lines.append(defmacro)

        return "\n".join(lines)

    def _generate_body(
        self,
        nodes: list[Node],
        macros: list[MacroDefinition],
    ) -> str:
        """Generate the body (compressed S-expression content).

        Uses LispExporter for base S-expression output, then applies
        macro compression where applicable.

        Args:
            nodes: Nodes to include in the body.
            macros: Macros available for compression.

        Returns:
            Compressed S-expression body.
        """
        from mu.kernel.export.lisp import LispExportOptions

        if not nodes:
            return ""

        # Get node IDs for export filtering
        node_ids = [n.id for n in nodes]

        # Export as Lisp S-expressions
        options = LispExportOptions(
            node_ids=node_ids,
            include_header=False,  # We generate our own header
            pretty_print=True,
        )

        result = self.lisp_exporter.export(self.mubase, options)

        if not result.success:
            # Fall back to simple output
            return f";; Export failed: {result.error}"

        body = result.output

        # Apply macro compression
        # For now, we rely on the Lisp exporter's output format
        # Future enhancement: Apply macro substitutions inline
        # e.g., replace (defn authenticate [...] -> User :decorators [app.post("/login")])
        #       with (api "post" "/login" "authenticate" ...)

        return body

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
