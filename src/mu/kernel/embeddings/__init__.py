"""MU Kernel Embeddings - Vector layer for semantic search.

Provides embedding generation and storage for code graph nodes,
enabling semantic search across the codebase.

Example:
    >>> from mu.kernel.embeddings import EmbeddingService, NodeEmbedding
    >>> from mu.kernel import MUbase
    >>>
    >>> # Generate embeddings
    >>> service = EmbeddingService(provider="openai")
    >>> embeddings = await service.embed_nodes(nodes)
    >>>
    >>> # Store in database
    >>> db = MUbase(".mubase")
    >>> db.add_embeddings_batch(embeddings)
    >>>
    >>> # Search
    >>> query_vec = await service.embed_query("authentication logic")
    >>> results = db.vector_search(query_vec, limit=10)
"""

from mu.kernel.embeddings.models import EmbeddingStats, NodeEmbedding
from mu.kernel.embeddings.providers import (
    BatchEmbeddingResult,
    EmbeddingProvider,
    EmbeddingProviderType,
    EmbeddingResult,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from mu.kernel.embeddings.service import EmbeddingService, create_embedding_service

__all__ = [
    # Service
    "EmbeddingService",
    "create_embedding_service",
    # Models
    "NodeEmbedding",
    "EmbeddingStats",
    # Providers
    "EmbeddingProvider",
    "EmbeddingProviderType",
    "EmbeddingResult",
    "BatchEmbeddingResult",
    "OpenAIEmbeddingProvider",
    "LocalEmbeddingProvider",
]
