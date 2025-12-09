"""Data models for Smart Context extraction.

Defines dataclasses for context extraction configuration, results,
and intermediate scoring data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mu.kernel.models import Node


@dataclass
class ExtractionConfig:
    """Configuration for smart context extraction.

    Controls token budgets, scoring weights, and extraction behavior.
    """

    max_tokens: int = 8000
    """Maximum tokens in the output context."""

    include_imports: bool = True
    """Whether to include import context for selected nodes."""

    include_parent: bool = True
    """Include parent class when methods are selected."""

    expand_depth: int = 1
    """How many levels of graph neighbors to expand."""

    entity_weight: float = 1.0
    """Weight for named entity match scoring."""

    vector_weight: float = 0.7
    """Weight for embedding similarity scoring."""

    proximity_weight: float = 0.3
    """Weight for graph distance scoring."""

    min_relevance: float = 0.1
    """Minimum score threshold for inclusion."""

    exclude_tests: bool = False
    """Whether to filter out test files from results."""

    vector_search_limit: int = 20
    """Maximum results from vector similarity search."""

    max_expansion_nodes: int = 100
    """Cap on nodes during graph expansion to prevent explosion."""

    include_docstrings: bool = True
    """Whether to include docstrings in output."""

    include_line_numbers: bool = False
    """Whether to include line numbers in output."""

    min_complexity_to_show: int = 0
    """Minimum complexity to show (0 = show all)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "max_tokens": self.max_tokens,
            "include_imports": self.include_imports,
            "include_parent": self.include_parent,
            "expand_depth": self.expand_depth,
            "entity_weight": self.entity_weight,
            "vector_weight": self.vector_weight,
            "proximity_weight": self.proximity_weight,
            "min_relevance": self.min_relevance,
            "exclude_tests": self.exclude_tests,
            "vector_search_limit": self.vector_search_limit,
            "max_expansion_nodes": self.max_expansion_nodes,
            "include_docstrings": self.include_docstrings,
            "include_line_numbers": self.include_line_numbers,
            "min_complexity_to_show": self.min_complexity_to_show,
        }


@dataclass
class ExportConfig:
    """Configuration for MU text export enrichment.

    Controls what additional data is included in MU format output:
    docstrings, line numbers, internal imports, and complexity thresholds.
    """

    # Docstrings
    include_docstrings: bool = True
    """Whether to include docstrings in the output."""

    max_docstring_lines: int = 5
    """Maximum lines to include from multi-line docstrings."""

    truncate_docstring: bool = True
    """Add '...' if docstring is truncated."""

    # Complexity
    min_complexity_to_show: int = 0
    """Minimum complexity threshold for showing complexity annotation. Previously was 20, now show all."""

    # Line numbers
    include_line_numbers: bool = False
    """Whether to include line numbers (opt-in for IDE integration)."""

    # Imports
    include_internal_imports: bool = True
    """Whether to show internal module imports (not just external deps)."""

    include_import_aliases: bool = False
    """Whether to show import aliases."""

    # Attributes
    max_attributes: int = 15
    """Maximum class attributes to show. Previously was 10."""

    # Module metadata
    include_language: bool = False
    """Whether to include language tag for multi-language codebases."""

    include_qualified_names: bool = False
    """Whether to show fully qualified names."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "include_docstrings": self.include_docstrings,
            "max_docstring_lines": self.max_docstring_lines,
            "truncate_docstring": self.truncate_docstring,
            "min_complexity_to_show": self.min_complexity_to_show,
            "include_line_numbers": self.include_line_numbers,
            "include_internal_imports": self.include_internal_imports,
            "include_import_aliases": self.include_import_aliases,
            "max_attributes": self.max_attributes,
            "include_language": self.include_language,
            "include_qualified_names": self.include_qualified_names,
        }


@dataclass
class ExtractedEntity:
    """An entity extracted from a natural language question.

    Represents a code identifier (function name, class name, etc.)
    found in the user's question.
    """

    name: str
    """The extracted entity name."""

    confidence: float = 1.0
    """Confidence score (0-1) based on extraction method."""

    extraction_method: str = "unknown"
    """How the entity was extracted (camel_case, snake_case, quoted, etc.)."""

    is_known: bool = False
    """Whether this entity matches a known node name in the codebase."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "confidence": self.confidence,
            "extraction_method": self.extraction_method,
            "is_known": self.is_known,
        }


@dataclass
class ScoredNode:
    """A node with relevance scores for context selection.

    Contains the node reference and breakdown of how the score was computed.
    """

    node: Node
    """The graph node being scored."""

    score: float
    """Combined relevance score."""

    entity_score: float = 0.0
    """Score from entity name matching."""

    vector_score: float = 0.0
    """Score from embedding similarity."""

    proximity_score: float = 0.0
    """Score from graph distance to seed nodes."""

    estimated_tokens: int = 0
    """Estimated token count for this node's content."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "node": self.node.to_dict(),
            "score": round(self.score, 4),
            "entity_score": round(self.entity_score, 4),
            "vector_score": round(self.vector_score, 4),
            "proximity_score": round(self.proximity_score, 4),
            "estimated_tokens": self.estimated_tokens,
        }


@dataclass
class ContextResult:
    """Result of smart context extraction.

    Contains the generated MU format context and metadata about
    the extraction process.
    """

    mu_text: str
    """Generated MU format context text."""

    nodes: list[Node] = field(default_factory=list)
    """Selected nodes included in the context."""

    token_count: int = 0
    """Actual token count of the output."""

    relevance_scores: dict[str, float] = field(default_factory=dict)
    """Mapping of node_id to relevance score."""

    extraction_stats: dict[str, Any] = field(default_factory=dict)
    """Debug/metrics info about the extraction process."""

    # Intent classification fields (added for question intent classification)
    intent: str | None = None
    """Classified intent type (e.g., 'explain', 'impact', 'locate')."""

    intent_confidence: float = 0.0
    """Confidence score for the intent classification (0.0-1.0)."""

    strategy_used: str = "default"
    """Name of the extraction strategy used."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "mu_text": self.mu_text,
            "nodes": [n.to_dict() for n in self.nodes],
            "token_count": self.token_count,
            "relevance_scores": self.relevance_scores,
            "extraction_stats": self.extraction_stats,
            "intent": self.intent,
            "intent_confidence": round(self.intent_confidence, 4),
            "strategy_used": self.strategy_used,
        }


__all__ = [
    "ContextResult",
    "ExportConfig",
    "ExtractionConfig",
    "ExtractedEntity",
    "ScoredNode",
]
