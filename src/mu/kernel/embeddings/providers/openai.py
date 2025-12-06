"""OpenAI embedding provider.

Uses OpenAI's text-embedding-3-small model for generating embeddings.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from mu.kernel.embeddings.providers.base import (
    BatchEmbeddingResult,
    EmbeddingResult,
)

logger = logging.getLogger(__name__)


# Model configurations
OPENAI_MODELS: dict[str, dict[str, Any]] = {
    "text-embedding-3-small": {
        "dimensions": 1536,
        "max_tokens": 8191,
        "version": "3-small",
    },
    "text-embedding-3-large": {
        "dimensions": 3072,
        "max_tokens": 8191,
        "version": "3-large",
    },
    "text-embedding-ada-002": {
        "dimensions": 1536,
        "max_tokens": 8191,
        "version": "ada-002",
    },
}


class OpenAIEmbeddingProvider:
    """OpenAI embedding provider using text-embedding-3-small.

    Uses the OpenAI API directly via httpx for async HTTP calls.
    Supports batch embedding with rate limiting and exponential backoff.
    """

    DEFAULT_MODEL = "text-embedding-3-small"
    API_URL = "https://api.openai.com/v1/embeddings"
    MAX_BATCH_SIZE = 2048  # OpenAI allows up to 2048 texts per request
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 3,
    ) -> None:
        """Initialize OpenAI embedding provider.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (default: text-embedding-3-small)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for failed requests
        """
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY environment variable "
                "or pass api_key parameter."
            )

        if model not in OPENAI_MODELS:
            raise ValueError(
                f"Unknown model: {model}. Available models: {list(OPENAI_MODELS.keys())}"
            )

        self._model = model
        self._model_config = OPENAI_MODELS[model]
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    @property
    def dimensions(self) -> int:
        """Return the dimension of embeddings."""
        return int(self._model_config["dimensions"])

    @property
    def model_name(self) -> str:
        """Return the model name."""
        return self._model

    @property
    def model_version(self) -> str:
        """Return the model version."""
        return str(self._model_config["version"])

    @property
    def max_tokens(self) -> int:
        """Return maximum tokens per input."""
        return int(self._model_config["max_tokens"])

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _make_request(
        self,
        texts: list[str],
        attempt: int = 0,
    ) -> dict[str, Any]:
        """Make API request with retry logic.

        Args:
            texts: List of texts to embed
            attempt: Current attempt number

        Returns:
            API response as dict

        Raises:
            Exception: If all retries exhausted
        """
        client = await self._get_client()

        try:
            response = await client.post(
                self.API_URL,
                json={
                    "model": self._model,
                    "input": texts,
                },
            )

            if response.status_code == 429:
                # Rate limited - exponential backoff
                if attempt < self._max_retries:
                    wait_time = min(60, 2 ** (attempt + 1))
                    logger.warning(
                        f"Rate limited, waiting {wait_time}s before retry "
                        f"({attempt + 1}/{self._max_retries})"
                    )
                    await asyncio.sleep(wait_time)
                    return await self._make_request(texts, attempt + 1)
                raise Exception("Rate limit exceeded, all retries exhausted")

            if response.status_code == 401:
                raise Exception("Authentication failed: invalid API key")

            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

        except httpx.TimeoutException as e:
            if attempt < self._max_retries:
                logger.warning(f"Request timeout, retrying ({attempt + 1}/{self._max_retries})")
                return await self._make_request(texts, attempt + 1)
            raise Exception(f"Request timeout after {self._max_retries} retries") from e

        except httpx.HTTPStatusError as e:
            # Sanitize error response to avoid leaking sensitive info
            status = e.response.status_code
            try:
                error_data = e.response.json()
                error_msg = error_data.get("error", {}).get("message", "Unknown error")
            except Exception:
                error_msg = f"Status {status}"
            raise Exception(f"HTTP error {status}: {error_msg}") from e

    async def embed(self, text: str) -> EmbeddingResult:
        """Generate embedding for a single text.

        Args:
            text: The text to embed

        Returns:
            EmbeddingResult with the embedding vector or error
        """
        if not text.strip():
            return EmbeddingResult(
                embedding=None,
                error="Empty text provided",
            )

        try:
            response = await self._make_request([text])
            data = response.get("data", [])

            if not data:
                return EmbeddingResult(
                    embedding=None,
                    error="No embedding returned from API",
                )

            tokens_used = response.get("usage", {}).get("total_tokens", 0)
            embedding = data[0].get("embedding", [])

            return EmbeddingResult(
                embedding=embedding,
                tokens_used=tokens_used,
            )

        except Exception as e:
            return EmbeddingResult(
                embedding=None,
                error=str(e),
            )

    async def embed_batch(self, texts: list[str]) -> BatchEmbeddingResult:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            BatchEmbeddingResult with embeddings in same order as input
        """
        if not texts:
            return BatchEmbeddingResult(embeddings=[], tokens_used=0)

        # Filter empty texts and track indices
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, text in enumerate(texts):
            if text.strip():
                valid_indices.append(i)
                valid_texts.append(text)

        if not valid_texts:
            return BatchEmbeddingResult(
                embeddings=[None] * len(texts),
                tokens_used=0,
                errors=["Empty text"] * len(texts),
            )

        try:
            # Process in batches if needed
            all_embeddings: list[list[float]] = []
            total_tokens = 0

            for batch_start in range(0, len(valid_texts), self.MAX_BATCH_SIZE):
                batch_end = min(batch_start + self.MAX_BATCH_SIZE, len(valid_texts))
                batch = valid_texts[batch_start:batch_end]

                response = await self._make_request(batch)
                data = response.get("data", [])
                total_tokens += response.get("usage", {}).get("total_tokens", 0)

                # Sort by index to maintain order
                sorted_data = sorted(data, key=lambda x: x.get("index", 0))
                all_embeddings.extend([d.get("embedding", []) for d in sorted_data])

            # Map back to original indices
            result_embeddings: list[list[float] | None] = [None] * len(texts)
            errors: list[str | None] = [None] * len(texts)

            for i, idx in enumerate(valid_indices):
                if i < len(all_embeddings):
                    result_embeddings[idx] = all_embeddings[i]

            # Mark empty texts as errors
            for i, text in enumerate(texts):
                if not text.strip():
                    errors[i] = "Empty text"

            return BatchEmbeddingResult(
                embeddings=result_embeddings,
                tokens_used=total_tokens,
                errors=errors if any(e is not None for e in errors) else None,
            )

        except Exception as e:
            return BatchEmbeddingResult(
                embeddings=[None] * len(texts),
                tokens_used=0,
                errors=[str(e)] * len(texts),
            )

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = [
    "OpenAIEmbeddingProvider",
    "OPENAI_MODELS",
]
