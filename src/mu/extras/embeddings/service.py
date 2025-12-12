"""Embedding service for generating node embeddings.

Provides batch embedding generation with progress callbacks
and support for multiple providers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mu.config import EmbeddingsConfig
from mu.extras.embeddings.models import EmbeddingStats, NodeEmbedding
from mu.extras.embeddings.providers.base import (
    EmbeddingProvider,
    EmbeddingProviderType,
)
from mu.extras.embeddings.providers.local import LocalEmbeddingProvider

if TYPE_CHECKING:
    from mu.kernel.models import Node


def _get_node_type() -> Any:
    """Lazy import of NodeType to avoid circular imports.

    Returns the NodeType enum class for runtime comparison.
    Type annotation uses Any to avoid circular import at type-check time.
    """
    from mu.kernel.schema import NodeType

    return NodeType


logger = logging.getLogger(__name__)


# Maximum text length for embedding (characters)
MAX_TEXT_LENGTH = 8000


def _truncate_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Truncate text to maximum length."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def _generate_node_text(node: Node) -> str:
    """Generate text representation of a node for embedding.

    Different strategies for different node types:
    - Functions: signature + docstring + first N chars of body
    - Classes: name + docstring + method signatures
    - Modules: docstring + exports list

    Args:
        node: The node to generate text for

    Returns:
        Text representation suitable for embedding
    """
    # Lazy import to avoid circular import
    NodeType = _get_node_type()

    parts: list[str] = []
    props = node.properties or {}

    if node.type == NodeType.FUNCTION:
        # Function: name, signature, docstring, and partial body
        parts.append(f"function {node.name}")

        if signature := props.get("signature"):
            parts.append(f"signature: {signature}")

        if docstring := props.get("docstring"):
            parts.append(f"docstring: {docstring}")

        if body := props.get("body_source"):
            # Include first 500 chars of body
            body_preview = body[:500] + "..." if len(body) > 500 else body
            parts.append(f"body: {body_preview}")

        if return_type := props.get("return_type"):
            parts.append(f"returns: {return_type}")

    elif node.type == NodeType.CLASS:
        # Class: name, bases, docstring, method signatures
        parts.append(f"class {node.name}")

        if bases := props.get("bases"):
            parts.append(f"inherits from: {', '.join(bases)}")

        if docstring := props.get("docstring"):
            parts.append(f"docstring: {docstring}")

        if methods := props.get("methods"):
            # Include method names/signatures
            method_names = [m.get("name", "") for m in methods if isinstance(m, dict)]
            if method_names:
                parts.append(f"methods: {', '.join(method_names)}")

    elif node.type == NodeType.MODULE:
        # Module: docstring and exports
        parts.append(f"module {node.name}")

        if docstring := props.get("docstring"):
            parts.append(f"docstring: {docstring}")

        if exports := props.get("exports"):
            parts.append(f"exports: {', '.join(exports[:20])}")

        if imports := props.get("imports"):
            parts.append(f"imports: {', '.join(imports[:10])}")

    elif node.type == NodeType.EXTERNAL:
        # External: just the name and qualified name
        parts.append(f"external package {node.name}")
        if node.qualified_name:
            parts.append(f"qualified name: {node.qualified_name}")

    # Fallback if no parts generated
    if not parts:
        parts.append(node.name)
        if node.qualified_name:
            parts.append(node.qualified_name)

    text = "\n".join(parts)
    return _truncate_text(text)


def _generate_docstring_text(node: Node) -> str | None:
    """Extract docstring from node for embedding."""
    props = node.properties or {}
    docstring = props.get("docstring")
    if docstring and isinstance(docstring, str) and docstring.strip():
        return _truncate_text(docstring)
    return None


def _generate_name_text(node: Node) -> str:
    """Generate name-based text for embedding."""
    if node.qualified_name:
        return node.qualified_name
    return node.name


class EmbeddingService:
    """Service for generating embeddings for code graph nodes.

    Supports batch processing with concurrency control,
    progress callbacks, and multiple embedding types per node.
    """

    DEFAULT_CONCURRENCY = 5
    DEFAULT_BATCH_SIZE = 100

    def __init__(
        self,
        config: EmbeddingsConfig | None = None,
        provider: str = "openai",
        model: str | None = None,
        model_path: str | None = None,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        """Initialize the embedding service.

        Args:
            config: Embeddings configuration (optional)
            provider: Provider to use ('openai' or 'local')
            model: Model to use (defaults to provider's default)
            model_path: Path to a custom local model directory (local provider only)
            concurrency: Maximum concurrent embedding requests
        """
        self._config = config
        self._provider_type = EmbeddingProviderType(provider)
        self._model = model
        self._model_path = model_path
        self._concurrency = concurrency
        self._provider: EmbeddingProvider | None = None
        self.stats = EmbeddingStats()

    def _create_provider(self) -> EmbeddingProvider:
        """Create the embedding provider based on configuration."""
        if self._provider_type == EmbeddingProviderType.OPENAI:
            raise ValueError(
                "OpenAI embedding provider has been removed. "
                "Use provider='local' with sentence-transformers instead."
            )

        elif self._provider_type == EmbeddingProviderType.LOCAL:
            model = self._model
            device = "auto"
            model_path = self._model_path
            if self._config:
                model = model or self._config.local.model
                device = self._config.local.device
                # Fall back to config model_path if not explicitly provided
                if model_path is None:
                    model_path = self._config.local.model_path
            return LocalEmbeddingProvider(
                model=model or "all-MiniLM-L6-v2",
                device=device,
                model_path=model_path,
            )

        raise ValueError(f"Unknown provider: {self._provider_type}")

    @property
    def provider(self) -> EmbeddingProvider:
        """Get or create the embedding provider."""
        if self._provider is None:
            self._provider = self._create_provider()
        return self._provider

    async def embed_node(self, node: Node) -> NodeEmbedding:
        """Generate embeddings for a single node.

        Args:
            node: The node to embed

        Returns:
            NodeEmbedding with generated vectors
        """
        # Generate text for each embedding type
        code_text = _generate_node_text(node)
        docstring_text = _generate_docstring_text(node)
        name_text = _generate_name_text(node)

        # Generate embeddings
        code_embedding = None
        docstring_embedding = None
        name_embedding = None

        # Code embedding (always generated)
        if code_text:
            result = await self.provider.embed(code_text)
            if result.success:
                code_embedding = result.embedding
                self.stats.add_success()
            else:
                logger.warning(f"Failed to embed code for {node.id}: {result.error}")
                self.stats.add_failure()

        # Docstring embedding (if available)
        if docstring_text:
            result = await self.provider.embed(docstring_text)
            if result.success:
                docstring_embedding = result.embedding

        # Name embedding
        if name_text:
            result = await self.provider.embed(name_text)
            if result.success:
                name_embedding = result.embedding

        return NodeEmbedding(
            node_id=node.id,
            code_embedding=code_embedding,
            docstring_embedding=docstring_embedding,
            name_embedding=name_embedding,
            model_name=self.provider.model_name,
            model_version=self.provider.model_version,
            dimensions=self.provider.dimensions,
            created_at=datetime.now(UTC),
        )

    async def embed_nodes(
        self,
        nodes: list[Node],
        batch_size: int | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[NodeEmbedding]:
        """Generate embeddings for multiple nodes.

        Uses batch processing for efficiency with concurrency control.

        Args:
            nodes: List of nodes to embed
            batch_size: Number of texts per API batch (default: from config or 100)
            on_progress: Optional callback(completed, total) for progress

        Returns:
            List of NodeEmbedding objects in same order as input
        """
        if not nodes:
            return []

        if batch_size is None:
            batch_size = self._config.batch_size if self._config else self.DEFAULT_BATCH_SIZE

        # Reset stats for this batch
        self.stats = EmbeddingStats()

        # Use semaphore to limit concurrency
        semaphore = asyncio.Semaphore(self._concurrency)
        results: list[NodeEmbedding | None] = [None] * len(nodes)
        completed = 0

        async def process_one(index: int, node: Node) -> None:
            nonlocal completed
            async with semaphore:
                embedding = await self.embed_node(node)
                results[index] = embedding
                completed += 1
                if on_progress:
                    on_progress(completed, len(nodes))

        # Process all nodes
        tasks = [process_one(i, node) for i, node in enumerate(nodes)]
        await asyncio.gather(*tasks)

        return [r for r in results if r is not None]

    async def embed_texts_batch(
        self,
        texts: list[str],
    ) -> list[list[float] | None]:
        """Generate embeddings for raw texts.

        Useful for embedding search queries.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors (or None for failed items)
        """
        result = await self.provider.embed_batch(texts)
        return result.embeddings

    async def embed_query(self, query: str) -> list[float] | None:
        """Generate embedding for a search query.

        Args:
            query: The search query text

        Returns:
            Embedding vector or None if failed
        """
        result = await self.provider.embed(query)
        return result.embedding if result.success else None

    async def close(self) -> None:
        """Close the service and release resources."""
        if self._provider is not None:
            # Both OpenAI and Local providers have close() method
            if hasattr(self._provider, "close"):
                close_method = self._provider.close
                await close_method()
            self._provider = None


def create_embedding_service(
    config: EmbeddingsConfig | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> EmbeddingService:
    """Create an embedding service from configuration.

    Args:
        config: Embeddings configuration (uses defaults if None)
        provider: Override provider from config
        model: Override model from config

    Returns:
        Configured EmbeddingService instance
    """
    if config is None:
        from mu.config import EmbeddingsConfig

        config = EmbeddingsConfig()

    provider_name = provider or config.provider

    return EmbeddingService(
        config=config,
        provider=provider_name,
        model=model,
    )


__all__ = [
    "EmbeddingService",
    "create_embedding_service",
]
