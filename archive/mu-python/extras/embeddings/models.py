"""Data models for the embeddings layer.

Defines NodeEmbedding dataclass that maps to DuckDB embeddings table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class NodeEmbedding:
    """Embedding vectors for a code graph node.

    Stores multiple embedding types per node:
    - code_embedding: Embedding of the code/body content
    - docstring_embedding: Embedding of documentation
    - name_embedding: Embedding of the node name
    """

    node_id: str
    model_name: str
    model_version: str
    dimensions: int
    created_at: datetime
    code_embedding: list[float] | None = None
    docstring_embedding: list[float] | None = None
    name_embedding: list[float] | None = None

    def to_tuple(
        self,
    ) -> tuple[
        str,
        list[float] | None,
        list[float] | None,
        list[float] | None,
        str,
        str,
        int,
        str,
    ]:
        """Convert to tuple for DuckDB insertion."""
        return (
            self.node_id,
            self.code_embedding,
            self.docstring_embedding,
            self.name_embedding,
            self.model_name,
            self.model_version,
            self.dimensions,
            self.created_at.isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "node_id": self.node_id,
            "code_embedding": self.code_embedding,
            "docstring_embedding": self.docstring_embedding,
            "name_embedding": self.name_embedding,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "dimensions": self.dimensions,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> NodeEmbedding:
        """Create NodeEmbedding from DuckDB row.

        Expected row format:
        (node_id, code_embedding, docstring_embedding, name_embedding,
         model_name, model_version, dimensions, created_at)
        """
        created_at = row[7]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        return cls(
            node_id=row[0],
            code_embedding=list(row[1]) if row[1] is not None else None,
            docstring_embedding=list(row[2]) if row[2] is not None else None,
            name_embedding=list(row[3]) if row[3] is not None else None,
            model_name=row[4],
            model_version=row[5],
            dimensions=row[6],
            created_at=created_at,
        )


@dataclass
class EmbeddingStats:
    """Statistics from an embedding generation run."""

    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    cached_hits: int = 0
    total_tokens: int = 0

    def add_success(self, cached: bool = False) -> None:
        """Record a successful embedding."""
        self.total_requests += 1
        self.successful += 1
        if cached:
            self.cached_hits += 1

    def add_failure(self) -> None:
        """Record a failed embedding."""
        self.total_requests += 1
        self.failed += 1


__all__ = [
    "NodeEmbedding",
    "EmbeddingStats",
]
