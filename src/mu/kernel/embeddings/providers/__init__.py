"""Embedding providers for the vector layer.

Provides OpenAI and local sentence-transformers providers for
generating embeddings.
"""

from mu.kernel.embeddings.providers.base import (
    BatchEmbeddingResult,
    EmbeddingProvider,
    EmbeddingProviderType,
    EmbeddingResult,
)
from mu.kernel.embeddings.providers.local import (
    LOCAL_MODELS,
    LocalEmbeddingProvider,
)
from mu.kernel.embeddings.providers.openai import (
    OPENAI_MODELS,
    OpenAIEmbeddingProvider,
)

__all__ = [
    # Base
    "EmbeddingProvider",
    "EmbeddingProviderType",
    "EmbeddingResult",
    "BatchEmbeddingResult",
    # OpenAI
    "OpenAIEmbeddingProvider",
    "OPENAI_MODELS",
    # Local
    "LocalEmbeddingProvider",
    "LOCAL_MODELS",
]
