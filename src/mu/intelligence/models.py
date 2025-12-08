"""Data models for the Intelligence Layer.

Defines dataclasses for patterns, validation, and context results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PatternCategory(Enum):
    """Categories of detected patterns."""

    ERROR_HANDLING = "error_handling"
    """How errors are created, thrown, and caught."""

    STATE_MANAGEMENT = "state_management"
    """How state is managed (stores, context, local state)."""

    API = "api"
    """API conventions (routes, responses, middleware)."""

    NAMING = "naming"
    """Naming conventions for files, functions, classes, constants."""

    TESTING = "testing"
    """Test patterns (file location, naming, mocking)."""

    COMPONENTS = "components"
    """Component patterns (props, composition, styling)."""

    IMPORTS = "imports"
    """Import organization (grouping, aliases, barrel files)."""

    ARCHITECTURE = "architecture"
    """Architectural patterns (services, repositories, controllers)."""

    ASYNC = "async"
    """Async patterns (async/await, promises, callbacks)."""

    LOGGING = "logging"
    """Logging patterns (levels, formats, context)."""


@dataclass
class PatternExample:
    """A concrete example of a pattern in the codebase."""

    file_path: str
    """Path to the file containing this example."""

    line_start: int
    """Starting line number (1-indexed)."""

    line_end: int
    """Ending line number (1-indexed)."""

    code_snippet: str
    """The actual code demonstrating the pattern."""

    annotation: str
    """Why this is a good example of the pattern."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "code_snippet": self.code_snippet,
            "annotation": self.annotation,
        }


@dataclass
class Pattern:
    """A detected pattern in the codebase."""

    name: str
    """Pattern identifier (e.g., 'custom_error_class', 'api_route_handler')."""

    category: PatternCategory
    """Category this pattern belongs to."""

    description: str
    """Human-readable description of the pattern."""

    frequency: int
    """How many times this pattern appears in the codebase."""

    confidence: float
    """Detection confidence (0.0 to 1.0)."""

    examples: list[PatternExample] = field(default_factory=list)
    """Code examples demonstrating this pattern."""

    anti_patterns: list[str] = field(default_factory=list)
    """Common mistakes or things to avoid."""

    related_patterns: list[str] = field(default_factory=list)
    """Names of related patterns that often appear together."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "frequency": self.frequency,
            "confidence": round(self.confidence, 3),
            "examples": [e.to_dict() for e in self.examples],
            "anti_patterns": self.anti_patterns,
            "related_patterns": self.related_patterns,
        }


@dataclass
class PatternsResult:
    """Result of pattern detection."""

    patterns: list[Pattern] = field(default_factory=list)
    """Detected patterns, sorted by frequency."""

    total_patterns: int = 0
    """Total number of patterns detected."""

    categories_found: list[str] = field(default_factory=list)
    """Categories that have detected patterns."""

    detection_time_ms: float = 0.0
    """Time taken for detection in milliseconds."""

    codebase_stats: dict[str, Any] = field(default_factory=dict)
    """Statistics about the analyzed codebase."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "patterns": [p.to_dict() for p in self.patterns],
            "total_patterns": self.total_patterns,
            "categories_found": self.categories_found,
            "detection_time_ms": round(self.detection_time_ms, 2),
            "codebase_stats": self.codebase_stats,
        }

    def get_by_category(self, category: PatternCategory) -> list[Pattern]:
        """Filter patterns by category.

        Args:
            category: The category to filter by.

        Returns:
            List of patterns in that category.
        """
        return [p for p in self.patterns if p.category == category]

    def get_top_patterns(self, n: int = 10) -> list[Pattern]:
        """Get the top N patterns by frequency.

        Args:
            n: Number of patterns to return.

        Returns:
            Top N patterns sorted by frequency descending.
        """
        return sorted(self.patterns, key=lambda p: p.frequency, reverse=True)[:n]


class TemplateType(Enum):
    """Types of code templates that can be generated."""

    HOOK = "hook"
    """React-style hook (use* function)."""

    COMPONENT = "component"
    """UI Component (class or functional)."""

    SERVICE = "service"
    """Service class for business logic."""

    REPOSITORY = "repository"
    """Repository/Store for data access."""

    API_ROUTE = "api_route"
    """API route handler."""

    TEST = "test"
    """Test file for an existing module."""

    MODEL = "model"
    """Data model/entity class."""

    CONTROLLER = "controller"
    """Controller/Handler class."""


@dataclass
class GeneratedFile:
    """A file generated from a template."""

    path: str
    """Relative path where the file should be created."""

    content: str
    """Generated file content."""

    description: str
    """What this file does."""

    is_primary: bool = True
    """Whether this is the main generated file (vs supporting files)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "path": self.path,
            "content": self.content,
            "description": self.description,
            "is_primary": self.is_primary,
        }


@dataclass
class GenerateResult:
    """Result of code generation."""

    template_type: TemplateType
    """Type of template that was used."""

    name: str
    """Name of the generated entity."""

    files: list[GeneratedFile] = field(default_factory=list)
    """Generated files (primary + supporting)."""

    patterns_used: list[str] = field(default_factory=list)
    """Names of patterns used to shape the generation."""

    suggestions: list[str] = field(default_factory=list)
    """Additional suggestions for the user."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "template_type": self.template_type.value,
            "name": self.name,
            "files": [f.to_dict() for f in self.files],
            "patterns_used": self.patterns_used,
            "suggestions": self.suggestions,
        }

    @property
    def primary_file(self) -> GeneratedFile | None:
        """Get the primary generated file."""
        for f in self.files:
            if f.is_primary:
                return f
        return self.files[0] if self.files else None


class TaskType(Enum):
    """Types of development tasks for context extraction."""

    CREATE = "create"
    """Creating new code (files, classes, functions)."""

    MODIFY = "modify"
    """Modifying existing code."""

    DELETE = "delete"
    """Removing code."""

    REFACTOR = "refactor"
    """Restructuring without changing behavior."""

    DEBUG = "debug"
    """Finding and fixing bugs."""

    TEST = "test"
    """Writing or updating tests."""

    DOCUMENT = "document"
    """Adding documentation."""

    REVIEW = "review"
    """Reviewing code for issues."""


class EntityType(Enum):
    """Types of code entities that might be involved in a task."""

    API_ENDPOINT = "api_endpoint"
    """REST/GraphQL endpoint."""

    HOOK = "hook"
    """React-style hook (use* pattern)."""

    COMPONENT = "component"
    """UI component."""

    SERVICE = "service"
    """Service/business logic class."""

    REPOSITORY = "repository"
    """Data access layer."""

    MODEL = "model"
    """Data model/entity."""

    FUNCTION = "function"
    """Standalone function."""

    CLASS = "class"
    """Class or interface."""

    MODULE = "module"
    """File/module level."""

    CONFIG = "config"
    """Configuration file."""

    TEST = "test"
    """Test file or function."""

    MIDDLEWARE = "middleware"
    """Middleware/interceptor."""

    UNKNOWN = "unknown"
    """Unable to determine type."""


@dataclass
class FileContext:
    """Context about a relevant file for a task."""

    path: str
    """File path (relative to project root)."""

    relevance: float
    """Relevance score (0.0 - 1.0)."""

    reason: str
    """Why this file is relevant to the task."""

    is_entry_point: bool = False
    """Whether this is a suggested starting point."""

    suggested_action: str = ""
    """What action to take with this file (read, modify, create)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "path": self.path,
            "relevance": round(self.relevance, 3),
            "reason": self.reason,
            "is_entry_point": self.is_entry_point,
            "suggested_action": self.suggested_action,
        }


@dataclass
class CodeExample:
    """A code example relevant to a task."""

    description: str
    """What this example demonstrates."""

    file_path: str
    """Path to the example file."""

    line_start: int
    """Starting line number."""

    line_end: int
    """Ending line number."""

    code_snippet: str = ""
    """Optional: the actual code."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "description": self.description,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "code_snippet": self.code_snippet,
        }


class MacroTier(Enum):
    """Tiers of macro stability for prompt cache optimization.

    Macros are ordered by tier in output to maximize prompt cache hits:
    CORE (always same) → STANDARD (common) → SYNTHESIZED (dynamic).
    """

    CORE = "core"
    """Built-in macros, always available (module, class, defn, data)."""

    STANDARD = "standard"
    """Common cross-codebase macros (api, component, test, hook)."""

    SYNTHESIZED = "synthesized"
    """Dynamically generated per-codebase macros."""


@dataclass
class MacroDefinition:
    """A macro definition for pattern compression in OMEGA format.

    This is the critical interface for pattern-to-lisp translation.
    Macros compress repeated code patterns into concise S-expressions.

    Example:
        A macro for API endpoints:
        >>> macro = MacroDefinition(
        ...     name="api",
        ...     tier=MacroTier.STANDARD,
        ...     signature=["method", "path", "name", "params"],
        ...     description="REST API endpoint handler",
        ...     pattern_source="http_method_handlers",
        ...     frequency=42,
        ...     expansion_template='(defn {name} [{params}] -> Response ...)',
        ...     token_savings=15,
        ... )
        >>> macro.apply({"method": "GET", "path": "/users", "name": "get_users", "params": []})
        '(api GET "/users" get_users [])'
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
          :decorators [app.{method}("{path}")])
    """

    token_savings: int = 0
    """Estimated tokens saved by using this macro."""

    def to_lisp_def(self) -> str:
        """Generate the Lisp defmacro form.

        Returns:
            S-expression defining this macro.

        Example:
            (defmacro api [method path name params]
              "REST API endpoint handler")
        """
        params = " ".join(self.signature)
        return f'(defmacro {self.name} [{params}]\n  "{self.description}")'

    def apply(self, node_data: dict[str, Any]) -> str:
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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MacroDefinition:
        """Create MacroDefinition from dictionary.

        Args:
            data: Dictionary with macro definition fields.

        Returns:
            MacroDefinition instance.
        """
        return cls(
            name=data["name"],
            tier=MacroTier(data["tier"]),
            signature=data["signature"],
            description=data["description"],
            pattern_source=data["pattern_source"],
            frequency=data["frequency"],
            expansion_template=data.get("expansion_template", ""),
            token_savings=data.get("token_savings", 0),
        )


@dataclass
class SynthesisResult:
    """Result of macro synthesis from codebase patterns.

    Contains generated macro definitions and synthesis statistics.
    The get_header() method produces a stable macro header optimized
    for prompt caching by ordering macros: CORE → STANDARD → SYNTHESIZED.

    Example:
        >>> result = SynthesisResult(
        ...     macros=[api_macro, service_macro],
        ...     total_patterns_analyzed=50,
        ...     patterns_converted=2,
        ...     estimated_compression=0.35,
        ...     synthesis_time_ms=125.5,
        ... )
        >>> print(result.get_header())
        ;; MU-Lisp Macro Definitions
        ;; Standard (cross-codebase)
        (defmacro api [method path name params]
          "REST API endpoint handler")
        ...
    """

    macros: list[MacroDefinition] = field(default_factory=list)
    """Generated macro definitions."""

    total_patterns_analyzed: int = 0
    """Number of patterns considered during synthesis."""

    patterns_converted: int = 0
    """Number of patterns that became macros."""

    estimated_compression: float = 0.0
    """Estimated compression ratio (0.0 - 1.0, where 0.35 = 35% reduction)."""

    synthesis_time_ms: float = 0.0
    """Time taken for synthesis in milliseconds."""

    def get_header(self) -> str:
        """Generate the macro header for context injection.

        Returns stable core macros first, then standard, then synthesized.
        This ordering optimizes for prompt caching - stable content at
        the start means higher cache hit rates.

        Returns:
            Formatted macro definitions as Lisp comments and defmacro forms.
        """
        lines = [";; MU-Lisp Macro Definitions"]

        # Group by tier for stable ordering
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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "macros": [m.to_dict() for m in self.macros],
            "total_patterns_analyzed": self.total_patterns_analyzed,
            "patterns_converted": self.patterns_converted,
            "estimated_compression": round(self.estimated_compression, 3),
            "synthesis_time_ms": round(self.synthesis_time_ms, 2),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SynthesisResult:
        """Create SynthesisResult from dictionary.

        Args:
            data: Dictionary with synthesis result fields.

        Returns:
            SynthesisResult instance.
        """
        return cls(
            macros=[MacroDefinition.from_dict(m) for m in data.get("macros", [])],
            total_patterns_analyzed=data.get("total_patterns_analyzed", 0),
            patterns_converted=data.get("patterns_converted", 0),
            estimated_compression=data.get("estimated_compression", 0.0),
            synthesis_time_ms=data.get("synthesis_time_ms", 0.0),
        )

    @property
    def macro_count(self) -> int:
        """Total number of macros."""
        return len(self.macros)

    @property
    def core_count(self) -> int:
        """Number of core macros."""
        return sum(1 for m in self.macros if m.tier == MacroTier.CORE)

    @property
    def standard_count(self) -> int:
        """Number of standard macros."""
        return sum(1 for m in self.macros if m.tier == MacroTier.STANDARD)

    @property
    def synthesized_count(self) -> int:
        """Number of synthesized macros."""
        return sum(1 for m in self.macros if m.tier == MacroTier.SYNTHESIZED)


class MemoryCategory(Enum):
    """Categories of cross-session memories."""

    PREFERENCE = "preference"
    """User preferences and settings (e.g., coding style, tool choices)."""

    DECISION = "decision"
    """Architectural or design decisions and their rationale."""

    CONTEXT = "context"
    """Project context that persists across sessions."""

    LEARNING = "learning"
    """Learned patterns or insights about the codebase."""

    PITFALL = "pitfall"
    """Known issues, gotchas, or things to avoid."""

    CONVENTION = "convention"
    """Team or project conventions."""

    TODO = "todo"
    """Deferred tasks or ideas for later."""

    REFERENCE = "reference"
    """Reference information (docs, links, examples)."""


@dataclass
class Memory:
    """A persistent memory stored across sessions.

    Memories capture learnings, decisions, preferences, and context
    that should persist across agent sessions.
    """

    id: str
    """Unique memory identifier."""

    category: MemoryCategory
    """Category of this memory."""

    content: str
    """The actual memory content."""

    context: str = ""
    """Optional additional context about when/why this was learned."""

    source: str = ""
    """Where this memory came from (file, conversation, etc.)."""

    confidence: float = 1.0
    """Confidence in this memory (0.0 - 1.0)."""

    importance: int = 1
    """Importance level (1-5, higher = more important)."""

    tags: list[str] = field(default_factory=list)
    """Tags for categorization and search."""

    embedding: list[float] | None = None
    """Optional vector embedding for semantic search."""

    created_at: str = ""
    """ISO timestamp when memory was created."""

    updated_at: str = ""
    """ISO timestamp when memory was last updated."""

    accessed_at: str | None = None
    """ISO timestamp when memory was last accessed."""

    access_count: int = 0
    """Number of times this memory has been recalled."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "category": self.category.value,
            "content": self.content,
            "context": self.context,
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "importance": self.importance,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "accessed_at": self.accessed_at,
            "access_count": self.access_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Memory:
        """Create Memory from dictionary."""
        return cls(
            id=data["id"],
            category=MemoryCategory(data["category"]),
            content=data["content"],
            context=data.get("context", ""),
            source=data.get("source", ""),
            confidence=data.get("confidence", 1.0),
            importance=data.get("importance", 1),
            tags=data.get("tags", []),
            embedding=data.get("embedding"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            accessed_at=data.get("accessed_at"),
            access_count=data.get("access_count", 0),
        )


@dataclass
class RecallResult:
    """Result of memory recall operation."""

    memories: list[Memory] = field(default_factory=list)
    """Retrieved memories sorted by relevance."""

    query: str = ""
    """The query used for recall."""

    total_matches: int = 0
    """Total number of matching memories."""

    recall_time_ms: float = 0.0
    """Time taken for recall in milliseconds."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "memories": [m.to_dict() for m in self.memories],
            "query": self.query,
            "total_matches": self.total_matches,
            "recall_time_ms": round(self.recall_time_ms, 2),
        }


class WarningCategory(Enum):
    """Categories of proactive warnings."""

    HIGH_IMPACT = "high_impact"
    """Target has many dependents that could break."""

    STALE = "stale"
    """Target hasn't been modified in a long time."""

    SECURITY = "security"
    """Target contains security-sensitive code."""

    NO_TESTS = "no_tests"
    """Target has no associated test coverage."""

    DEPRECATED = "deprecated"
    """Target is marked as deprecated."""

    COMPLEXITY = "complexity"
    """Target has high cyclomatic complexity."""

    DIFFERENT_OWNER = "different_owner"
    """Target was primarily authored by someone else."""


@dataclass
class Warning:
    """A warning about potential issues when working on a task."""

    level: str
    """Warning level: info, warn, error."""

    message: str
    """The warning message."""

    related_file: str = ""
    """Optional: file this warning relates to."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "level": self.level,
            "message": self.message,
            "related_file": self.related_file,
        }


@dataclass
class ProactiveWarning:
    """A proactive warning about a code target before modification."""

    category: WarningCategory
    """Category of the warning."""

    level: str
    """Severity level: info, warn, error."""

    message: str
    """Human-readable warning message."""

    details: dict[str, Any] = field(default_factory=dict)
    """Additional structured details about the warning."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "category": self.category.value,
            "level": self.level,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class WarningsResult:
    """Result of proactive warning analysis for a target."""

    target: str
    """The analyzed target (file path or node ID)."""

    target_type: str
    """Type of target: file, module, class, function."""

    warnings: list[ProactiveWarning] = field(default_factory=list)
    """List of warnings for this target."""

    summary: str = ""
    """One-line summary of the warning analysis."""

    risk_score: float = 0.0
    """Overall risk score (0.0 - 1.0) based on warnings."""

    analysis_time_ms: float = 0.0
    """Time taken for analysis in milliseconds."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "target": self.target,
            "target_type": self.target_type,
            "warnings": [w.to_dict() for w in self.warnings],
            "summary": self.summary,
            "risk_score": round(self.risk_score, 3),
            "analysis_time_ms": round(self.analysis_time_ms, 2),
        }

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    @property
    def error_count(self) -> int:
        """Count of error-level warnings."""
        return sum(1 for w in self.warnings if w.level == "error")

    @property
    def warn_count(self) -> int:
        """Count of warn-level warnings."""
        return sum(1 for w in self.warnings if w.level == "warn")

    @property
    def info_count(self) -> int:
        """Count of info-level warnings."""
        return sum(1 for w in self.warnings if w.level == "info")


@dataclass
class Suggestion:
    """A suggestion for the task."""

    suggestion_type: str
    """Type: related_change, test, pattern, alternative."""

    message: str
    """The suggestion message."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.suggestion_type,
            "message": self.message,
        }


@dataclass
class TaskAnalysis:
    """Analysis of a natural language task description."""

    original_task: str
    """The original task description."""

    task_type: TaskType
    """Inferred type of development task."""

    entity_types: list[EntityType]
    """Types of code entities likely involved."""

    keywords: list[str]
    """Extracted keywords for search."""

    domain_hints: list[str]
    """Domain-specific terms (auth, payment, user, etc.)."""

    confidence: float = 0.0
    """Confidence in the analysis (0.0 - 1.0)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "original_task": self.original_task,
            "task_type": self.task_type.value,
            "entity_types": [et.value for et in self.entity_types],
            "keywords": self.keywords,
            "domain_hints": self.domain_hints,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class TaskContextResult:
    """Result of task-aware context extraction.

    Contains everything an AI assistant needs to complete a development task.
    """

    # Core context
    relevant_files: list[FileContext] = field(default_factory=list)
    """Files relevant to the task, sorted by relevance."""

    entry_points: list[str] = field(default_factory=list)
    """Suggested starting points (directories or files)."""

    # Patterns and examples
    patterns: list[Pattern] = field(default_factory=list)
    """Relevant codebase patterns."""

    examples: list[CodeExample] = field(default_factory=list)
    """Similar implementations in the codebase."""

    # Guidance
    warnings: list[Warning] = field(default_factory=list)
    """Warnings about impact, staleness, security, etc."""

    suggestions: list[Suggestion] = field(default_factory=list)
    """Suggestions for related changes, tests, etc."""

    # Analysis
    task_analysis: TaskAnalysis | None = None
    """The task analysis results."""

    # Output
    mu_text: str = ""
    """MU format context (token-efficient representation)."""

    token_count: int = 0
    """Token count of mu_text."""

    confidence: float = 0.0
    """Overall confidence in the context relevance (0.0 - 1.0)."""

    # Metadata
    extraction_stats: dict[str, Any] = field(default_factory=dict)
    """Debug/metrics info about the extraction process."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "relevant_files": [f.to_dict() for f in self.relevant_files],
            "entry_points": self.entry_points,
            "patterns": [p.to_dict() for p in self.patterns],
            "examples": [e.to_dict() for e in self.examples],
            "warnings": [w.to_dict() for w in self.warnings],
            "suggestions": [s.to_dict() for s in self.suggestions],
            "task_analysis": self.task_analysis.to_dict() if self.task_analysis else None,
            "mu_text": self.mu_text,
            "token_count": self.token_count,
            "confidence": round(self.confidence, 3),
            "extraction_stats": self.extraction_stats,
        }


__all__ = [
    "CodeExample",
    "EntityType",
    "FileContext",
    "GeneratedFile",
    "GenerateResult",
    "MacroDefinition",
    "MacroTier",
    "Memory",
    "MemoryCategory",
    "Pattern",
    "PatternCategory",
    "PatternExample",
    "PatternsResult",
    "ProactiveWarning",
    "RecallResult",
    "Suggestion",
    "SynthesisResult",
    "TaskAnalysis",
    "TaskContextResult",
    "TaskType",
    "TemplateType",
    "Warning",
    "WarningCategory",
    "WarningsResult",
]
