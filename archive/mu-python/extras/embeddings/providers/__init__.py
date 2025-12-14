"""Embedding providers for the vector layer.

Provides local sentence-transformers provider for generating embeddings.
"""

from mu.extras.embeddings.providers.base import (
    BatchEmbeddingResult,
    EmbeddingProvider,
    EmbeddingProviderType,
    EmbeddingResult,
)
from mu.extras.embeddings.providers.local import (
    LOCAL_MODELS,
    LocalEmbeddingProvider,
)

__all__ = [
    # Base
    "EmbeddingProvider",
    "EmbeddingProviderType",
    "EmbeddingResult",
    "BatchEmbeddingResult",
    # Local
    "LocalEmbeddingProvider",
    "LOCAL_MODELS",
]
