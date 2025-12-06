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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "mu_text": self.mu_text,
            "nodes": [n.to_dict() for n in self.nodes],
            "token_count": self.token_count,
            "relevance_scores": self.relevance_scores,
            "extraction_stats": self.extraction_stats,
        }


__all__ = [
    "ContextResult",
    "ExtractionConfig",
    "ExtractedEntity",
    "ScoredNode",
]
