"""Base protocol for embedding providers.

Defines the interface that all embedding providers must implement.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class EmbeddingProviderType(str, Enum):
    """Supported embedding providers."""

    OPENAI = "openai"
    LOCAL = "local"


@dataclass
class EmbeddingResult:
    """Result of an embedding operation."""

    embedding: list[float] | None
    tokens_used: int = 0
    cached: bool = False
    error: str | None = None

    @property
    def success(self) -> bool:
        """Check if embedding succeeded."""
        return self.error is None and self.embedding is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "embedding": self.embedding,
            "tokens_used": self.tokens_used,
            "cached": self.cached,
            "error": self.error,
            "success": self.success,
        }


@dataclass
class BatchEmbeddingResult:
    """Result of a batch embedding operation."""

    embeddings: list[list[float] | None]
    tokens_used: int = 0
    errors: list[str | None] | None = None

    @property
    def success_count(self) -> int:
        """Count successful embeddings."""
        return sum(1 for e in self.embeddings if e is not None)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "embeddings": self.embeddings,
            "tokens_used": self.tokens_used,
            "errors": self.errors,
            "success_count": self.success_count,
        }


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers.

    All embedding providers must implement this interface to be used
    with the EmbeddingService.
    """

    @property
    def dimensions(self) -> int:
        """Return the dimension of embeddings produced by this provider."""
        ...

    @property
    def model_name(self) -> str:
        """Return the model name/identifier."""
        ...

    @property
    def model_version(self) -> str:
        """Return the model version."""
        ...

    @property
    def max_tokens(self) -> int:
        """Return the maximum tokens per text input."""
        ...

    @abstractmethod
    async def embed(self, text: str) -> EmbeddingResult:
        """Generate embedding for a single text.

        Args:
            text: The text to embed

        Returns:
            EmbeddingResult with the embedding vector or error
        """
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> BatchEmbeddingResult:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            BatchEmbeddingResult with embeddings in same order as input
        """
        ...


__all__ = [
    "EmbeddingProviderType",
    "EmbeddingResult",
    "BatchEmbeddingResult",
    "EmbeddingProvider",
]
