"""Tests for LLM integration module."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mu.config import LLMConfig
from mu.llm import (
    CostEstimate,
    LLMPool,
    LLMProvider,
    SummarizationRequest,
    SummarizationResult,
    estimate_cost,
    estimate_tokens,
    format_summarize_prompt,
    get_model_config,
    parse_summary_response,
)
from mu.llm.providers import MODELS, get_default_model


class TestLLMTypes:
    """Tests for LLM type definitions."""

    def test_summarization_request(self):
        """Test SummarizationRequest creation."""
        req = SummarizationRequest(
            function_name="process_data",
            body_source="return data.filter(x => x > 0)",
            language="typescript",
            context="DataProcessor",
        )
        assert req.function_name == "process_data"
        assert req.language == "typescript"
        assert req.context == "DataProcessor"

    def test_summarization_result_success(self):
        """Test successful SummarizationResult."""
        result = SummarizationResult(
            function_name="process_data",
            summary=["Filters positive values from data array"],
            tokens_used=50,
            model="claude-3-haiku-20240307",
        )
        assert result.success
        assert len(result.summary) == 1

    def test_summarization_result_failure(self):
        """Test failed SummarizationResult."""
        result = SummarizationResult(
            function_name="process_data",
            summary=[],
            tokens_used=0,
            model="claude-3-haiku-20240307",
            error="Rate limited",
        )
        assert not result.success
        assert result.error == "Rate limited"

    def test_cost_estimate_format(self):
        """Test CostEstimate formatting."""
        estimate = CostEstimate(
            function_count=10,
            estimated_input_tokens=5000,
            estimated_output_tokens=1000,
            estimated_cost_usd=0.02,
            model="claude-3-haiku-20240307",
            provider=LLMProvider.ANTHROPIC,
        )
        formatted = estimate.format_summary()
        assert "10" in formatted
        assert "5,000" in formatted
        assert "$0.02" in formatted

    def test_cost_estimate_ollama_free(self):
        """Test CostEstimate shows free for Ollama."""
        estimate = CostEstimate(
            function_count=10,
            estimated_input_tokens=5000,
            estimated_output_tokens=1000,
            estimated_cost_usd=0.0,
            model="codellama",
            provider=LLMProvider.OLLAMA,
        )
        formatted = estimate.format_summary()
        assert "$0.00 (local)" in formatted


class TestPrompts:
    """Tests for prompt templates."""

    def test_format_summarize_prompt(self):
        """Test prompt formatting."""
        prompt = format_summarize_prompt(
            body="def add(a, b):\n    return a + b",
            language="python",
            context="MathUtils",
        )
        assert "python" in prompt.lower()
        assert "MathUtils" in prompt
        assert "def add" in prompt

    def test_format_summarize_prompt_no_context(self):
        """Test prompt without context."""
        prompt = format_summarize_prompt(
            body="function add(a, b) { return a + b; }",
            language="javascript",
        )
        assert "javascript" in prompt.lower()
        assert "function add" in prompt

    def test_parse_summary_response_dashes(self):
        """Test parsing bullet points with dashes."""
        response = """
        - Adds two numbers together
        - Returns the sum
        - Pure function with no side effects
        """
        bullets = parse_summary_response(response)
        assert len(bullets) == 3
        assert "Adds two numbers" in bullets[0]

    def test_parse_summary_response_asterisks(self):
        """Test parsing bullet points with asterisks."""
        response = """
        * Primary purpose: data transformation
        * Inputs: array of objects
        * No side effects
        """
        bullets = parse_summary_response(response)
        assert len(bullets) == 3

    def test_parse_summary_response_numbered(self):
        """Test parsing numbered list."""
        response = """
        1. Validates user input
        2. Saves to database
        3. Returns success status
        """
        bullets = parse_summary_response(response)
        assert len(bullets) == 3
        assert "Validates user input" in bullets[0]

    def test_parse_summary_response_caps_at_five(self):
        """Test that response is capped at 5 bullets."""
        response = "\n".join([f"- Point {i}" for i in range(10)])
        bullets = parse_summary_response(response)
        assert len(bullets) == 5


class TestProviders:
    """Tests for provider configuration."""

    def test_known_models_exist(self):
        """Test that expected models are registered."""
        assert "claude-3-haiku-20240307" in MODELS
        assert "gpt-4o-mini" in MODELS
        assert "codellama" in MODELS

    def test_get_model_config_known(self):
        """Test getting config for known model."""
        config = get_model_config("claude-3-haiku-20240307")
        assert config.provider == LLMProvider.ANTHROPIC
        assert config.input_cost_per_million == 0.25

    def test_get_model_config_unknown_with_provider(self):
        """Test getting config for unknown model with provider hint."""
        config = get_model_config("custom-model", LLMProvider.OPENAI)
        assert config.provider == LLMProvider.OPENAI
        assert config.input_cost_per_million == 0.0  # Unknown pricing

    def test_get_model_config_unknown_no_provider_raises(self):
        """Test that unknown model without provider raises."""
        with pytest.raises(ValueError, match="Unknown model"):
            get_model_config("totally-unknown-model")

    def test_get_default_model(self):
        """Test default models per provider."""
        assert get_default_model(LLMProvider.ANTHROPIC) == "claude-3-haiku-20240307"
        assert get_default_model(LLMProvider.OPENAI) == "gpt-4o-mini"
        assert get_default_model(LLMProvider.OLLAMA) == "codellama"


class TestCostEstimation:
    """Tests for cost estimation."""

    def test_estimate_tokens(self):
        """Test token estimation."""
        text = "Hello world"  # 11 chars
        tokens = estimate_tokens(text)
        assert tokens == 2  # ~4 chars per token

    def test_estimate_tokens_empty(self):
        """Test token estimation for empty string."""
        tokens = estimate_tokens("")
        assert tokens == 1  # Minimum 1

    def test_estimate_cost_anthropic(self):
        """Test cost estimation for Anthropic."""
        requests = [
            SummarizationRequest(
                function_name="test",
                body_source="x" * 400,  # ~100 tokens
                language="python",
            )
        ]
        estimate = estimate_cost(
            requests,
            model="claude-3-haiku-20240307",
            provider=LLMProvider.ANTHROPIC,
        )
        assert estimate.function_count == 1
        assert estimate.estimated_input_tokens > 0
        assert estimate.estimated_cost_usd > 0

    def test_estimate_cost_ollama_free(self):
        """Test cost estimation for Ollama is zero."""
        requests = [
            SummarizationRequest(
                function_name="test",
                body_source="x" * 400,
                language="python",
            )
        ]
        estimate = estimate_cost(
            requests,
            model="codellama",
            provider=LLMProvider.OLLAMA,
        )
        assert estimate.estimated_cost_usd == 0.0


class TestLLMPool:
    """Tests for LLMPool."""

    def test_pool_creation(self):
        """Test LLMPool initialization."""
        config = LLMConfig()
        pool = LLMPool(config)
        assert pool.provider == LLMProvider.ANTHROPIC
        assert pool.concurrency == 5

    def test_pool_cache_key_generation(self):
        """Test cache key is deterministic."""
        config = LLMConfig()
        pool = LLMPool(config)
        req = SummarizationRequest(
            function_name="test",
            body_source="def foo(): pass",
            language="python",
        )
        key1 = pool._cache_key(req)
        key2 = pool._cache_key(req)
        assert key1 == key2
        assert len(key1) == 16  # Truncated hash

    def test_pool_cache_key_varies_with_content(self):
        """Test cache key changes with body content."""
        config = LLMConfig()
        pool = LLMPool(config)
        req1 = SummarizationRequest(
            function_name="test",
            body_source="def foo(): pass",
            language="python",
        )
        req2 = SummarizationRequest(
            function_name="test",
            body_source="def bar(): return 1",
            language="python",
        )
        assert pool._cache_key(req1) != pool._cache_key(req2)

    @pytest.mark.asyncio
    async def test_pool_summarize_cached(self):
        """Test that cached results are returned."""
        config = LLMConfig()
        pool = LLMPool(config)

        req = SummarizationRequest(
            function_name="test",
            body_source="def foo(): pass",
            language="python",
        )

        # Pre-populate memory cache
        cached_result = SummarizationResult(
            function_name="test",
            summary=["Does nothing"],
            tokens_used=10,
            model=config.model,
        )
        cache_key = pool._cache_key(req)
        pool._memory_cache[cache_key] = cached_result

        # Should return cached result without calling LLM
        result = await pool.summarize(req)
        assert result.cached
        assert result.summary == ["Does nothing"]
        assert result.tokens_used == 0  # Cached results report 0 tokens

    def test_pool_clear_cache(self):
        """Test cache clearing."""
        config = LLMConfig()
        pool = LLMPool(config)

        # Add items to memory cache
        pool._memory_cache["key1"] = MagicMock()
        pool._memory_cache["key2"] = MagicMock()

        count = pool.clear_cache()
        assert count == 2
        assert len(pool._memory_cache) == 0


class TestLLMPoolIntegration:
    """Integration tests that mock LiteLLM calls."""

    @pytest.mark.asyncio
    async def test_summarize_success(self):
        """Test successful summarization with mocked LLM."""
        config = LLMConfig()
        pool = LLMPool(config)

        req = SummarizationRequest(
            function_name="process_users",
            body_source="""
            for user in users:
                if user.is_active:
                    result.append(user.name)
            return result
            """,
            language="python",
        )

        # Mock the LiteLLM response
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="- Filters active users\n- Returns list of names"))
        ]
        mock_response.usage = MagicMock(total_tokens=50)

        with patch("mu.llm.pool.acompletion", new_callable=AsyncMock) as mock_completion:
            mock_completion.return_value = mock_response
            result = await pool.summarize(req)

        assert result.success
        assert len(result.summary) == 2
        assert result.tokens_used == 50
        assert not result.cached

    @pytest.mark.asyncio
    async def test_summarize_batch(self):
        """Test batch summarization with mocked LLM."""
        config = LLMConfig()
        pool = LLMPool(config)

        requests = [
            SummarizationRequest(
                function_name=f"func_{i}",
                body_source=f"def func_{i}(): return {i}",
                language="python",
            )
            for i in range(3)
        ]

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="- Returns a constant value"))
        ]
        mock_response.usage = MagicMock(total_tokens=20)

        with patch("mu.llm.pool.acompletion", new_callable=AsyncMock) as mock_completion:
            mock_completion.return_value = mock_response
            results = await pool.summarize_batch(requests)

        assert len(results) == 3
        assert all(r.success for r in results)

    @pytest.mark.asyncio
    async def test_summarize_auth_error(self):
        """Test handling of authentication errors."""
        import litellm

        config = LLMConfig()
        pool = LLMPool(config)

        req = SummarizationRequest(
            function_name="test",
            body_source="def test(): pass",
            language="python",
        )

        with patch("mu.llm.pool.acompletion", new_callable=AsyncMock) as mock_completion:
            mock_completion.side_effect = litellm.exceptions.AuthenticationError(
                message="Invalid API key",
                llm_provider="anthropic",
                model="claude-3-haiku",
            )
            result = await pool.summarize(req)

        assert not result.success
        assert "Authentication failed" in result.error
