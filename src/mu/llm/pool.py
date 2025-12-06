"""LLM Pool - Multi-provider abstraction over LiteLLM."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

import litellm
from litellm import acompletion

from mu.cache import CacheManager
from mu.config import CacheConfig, LLMConfig
from mu.llm.prompts import (
    PROMPT_VERSION,
    format_summarize_prompt,
    parse_summary_response,
)
from mu.llm.providers import get_model_config, ModelConfig
from mu.llm.types import (
    LLMProvider,
    LLMStats,
    SummarizationRequest,
    SummarizationResult,
)


logger = logging.getLogger(__name__)

# Disable LiteLLM's verbose logging
litellm.suppress_debug_info = True


class LLMPool:
    """Multi-provider LLM pool for function summarization.

    Wraps LiteLLM to provide:
    - Unified interface across providers
    - Async batch processing with concurrency limits
    - Persistent caching via CacheManager (with in-memory fallback)
    - Retry logic with exponential backoff
    """

    DEFAULT_CONCURRENCY = 5
    DEFAULT_MAX_RETRIES = 2

    def __init__(
        self,
        config: LLMConfig,
        concurrency: int = DEFAULT_CONCURRENCY,
        cache_config: CacheConfig | None = None,
        cache_base_path: Path | None = None,
    ):
        """Initialize the LLM pool.

        Args:
            config: LLM configuration from MUConfig
            concurrency: Maximum concurrent requests (default: 5)
            cache_config: Optional cache configuration for persistent caching
            cache_base_path: Base path for cache directory
        """
        self.config = config
        self.concurrency = concurrency
        self.provider = LLMProvider(config.provider)
        self.model_config = get_model_config(config.model, self.provider)

        # Persistent cache via CacheManager (preferred)
        self._cache_manager: CacheManager | None = None
        if cache_config is not None:
            self._cache_manager = CacheManager(cache_config, cache_base_path)

        # Fallback in-memory cache when no cache_config provided
        self._memory_cache: dict[str, SummarizationResult] = {}

        # Stats tracking
        self.stats = LLMStats()

        # Configure LiteLLM for Ollama if needed
        if self.provider == LLMProvider.OLLAMA:
            litellm.api_base = config.ollama.base_url

    def _cache_key(self, request: SummarizationRequest) -> str:
        """Generate cache key for a request.

        Key includes body hash + prompt version + model to invalidate
        when any of these change.
        """
        return CacheManager.compute_llm_cache_key(
            request.body_source,
            PROMPT_VERSION,
            self.config.model,
        )

    def _get_cached(self, cache_key: str) -> SummarizationResult | None:
        """Get cached result from persistent or memory cache."""
        # Try persistent cache first
        if self._cache_manager and self._cache_manager.enabled:
            cached = self._cache_manager.get_llm_result(cache_key)
            if cached:
                return SummarizationResult(
                    function_name=cached.function_name,
                    summary=cached.summary,
                    tokens_used=0,  # Cached results report 0 tokens
                    model=cached.model,
                    cached=True,
                )

        # Fallback to memory cache
        if cache_key in self._memory_cache:
            cached = self._memory_cache[cache_key]
            return SummarizationResult(
                function_name=cached.function_name,
                summary=cached.summary,
                tokens_used=0,
                model=cached.model,
                cached=True,
            )

        return None

    def _set_cached(
        self,
        cache_key: str,
        result: SummarizationResult,
    ) -> None:
        """Store result in persistent and memory cache."""
        # Store in persistent cache
        if self._cache_manager and self._cache_manager.enabled:
            self._cache_manager.set_llm_result(
                cache_key=cache_key,
                function_name=result.function_name,
                summary=result.summary,
                model=result.model,
                prompt_version=PROMPT_VERSION,
            )

        # Also store in memory cache for session-local hits
        self._memory_cache[cache_key] = result

    async def summarize(
        self,
        request: SummarizationRequest,
    ) -> SummarizationResult:
        """Summarize a single function.

        Args:
            request: The summarization request

        Returns:
            SummarizationResult with summary or error
        """
        # Check cache first (persistent + memory)
        cache_key = self._cache_key(request)
        cached_result = self._get_cached(cache_key)
        if cached_result:
            # Update function name in case it differs
            cached_result.function_name = request.function_name
            return cached_result

        # Build prompt
        prompt = format_summarize_prompt(
            body=request.body_source,
            language=request.language,
            context=request.context,
        )

        # Call LLM with retries
        last_error: str | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await acompletion(
                    model=self.model_config.litellm_model,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=self.config.timeout_seconds,
                    max_tokens=500,  # Summaries are short
                )

                # Extract response text
                response_text = response.choices[0].message.content
                summary = parse_summary_response(response_text)

                # Get token usage
                tokens_used = 0
                if hasattr(response, "usage") and response.usage:
                    tokens_used = (
                        getattr(response.usage, "total_tokens", 0)
                        or getattr(response.usage, "prompt_tokens", 0)
                        + getattr(response.usage, "completion_tokens", 0)
                    )

                result = SummarizationResult(
                    function_name=request.function_name,
                    summary=summary,
                    tokens_used=tokens_used,
                    model=self.config.model,
                    cached=False,
                )

                # Cache successful result (persistent + memory)
                self._set_cached(cache_key, result)
                return result

            except litellm.exceptions.RateLimitError as e:
                last_error = f"Rate limited: {e}"
                if attempt < self.config.max_retries:
                    wait_time = min(60, 2 ** (attempt + 1))  # Exponential backoff, max 60s
                    logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                    await asyncio.sleep(wait_time)

            except litellm.exceptions.AuthenticationError as e:
                # Don't retry auth errors
                return SummarizationResult(
                    function_name=request.function_name,
                    summary=[],
                    tokens_used=0,
                    model=self.config.model,
                    error=f"Authentication failed: {e}",
                )

            except asyncio.TimeoutError:
                last_error = f"Timeout after {self.config.timeout_seconds}s"
                if attempt < self.config.max_retries:
                    logger.warning(f"Timeout, retrying ({attempt + 1}/{self.config.max_retries})")

            except Exception as e:
                last_error = str(e)
                if attempt < self.config.max_retries:
                    logger.warning(f"Error: {e}, retrying ({attempt + 1}/{self.config.max_retries})")

        # All retries exhausted
        return SummarizationResult(
            function_name=request.function_name,
            summary=[],
            tokens_used=0,
            model=self.config.model,
            error=last_error or "Unknown error",
        )

    async def summarize_batch(
        self,
        requests: list[SummarizationRequest],
        progress_callback: Any | None = None,
    ) -> list[SummarizationResult]:
        """Summarize multiple functions with concurrency control.

        Args:
            requests: List of summarization requests
            progress_callback: Optional callback(completed, total) for progress updates

        Returns:
            List of results in same order as requests
        """
        if not requests:
            return []

        # Use semaphore to limit concurrency
        semaphore = asyncio.Semaphore(self.concurrency)
        results: list[SummarizationResult | None] = [None] * len(requests)
        completed = 0

        async def process_one(index: int, request: SummarizationRequest) -> None:
            nonlocal completed
            async with semaphore:
                result = await self.summarize(request)
                results[index] = result
                self.stats.add_result(result)
                completed += 1
                if progress_callback:
                    progress_callback(completed, len(requests))

        # Run all tasks
        tasks = [
            process_one(i, req)
            for i, req in enumerate(requests)
        ]
        await asyncio.gather(*tasks)

        return [r for r in results if r is not None]

    def clear_cache(self) -> int:
        """Clear both persistent and in-memory caches.

        Returns:
            Number of entries cleared (memory cache only, persistent handled separately)
        """
        count = len(self._memory_cache)
        self._memory_cache.clear()
        # Note: Persistent cache clearing is handled by CacheManager.clear()
        return count

    def close(self) -> None:
        """Close cache connections."""
        if self._cache_manager:
            self._cache_manager.close()


def create_pool(
    config: LLMConfig,
    cache_config: CacheConfig | None = None,
    cache_base_path: Path | None = None,
) -> LLMPool:
    """Create an LLM pool from configuration.

    Args:
        config: LLM configuration
        cache_config: Optional cache configuration for persistent caching
        cache_base_path: Base path for cache directory

    Returns:
        Configured LLMPool instance
    """
    return LLMPool(
        config,
        cache_config=cache_config,
        cache_base_path=cache_base_path,
    )
