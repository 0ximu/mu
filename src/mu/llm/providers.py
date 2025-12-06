"""LLM provider configurations and pricing."""

from __future__ import annotations

from dataclasses import dataclass

from mu.llm.types import LLMProvider


@dataclass
class ModelConfig:
    """Configuration for a specific model."""

    provider: LLMProvider
    model_id: str
    litellm_model: str  # Format for LiteLLM (e.g., "anthropic/claude-3-haiku")
    input_cost_per_million: float  # USD per 1M input tokens
    output_cost_per_million: float  # USD per 1M output tokens
    max_tokens: int = 4096  # Default max output tokens
    supports_system_prompt: bool = True


# Model registry with pricing (as of Dec 2024)
MODELS: dict[str, ModelConfig] = {
    # Anthropic
    "claude-3-haiku-20240307": ModelConfig(
        provider=LLMProvider.ANTHROPIC,
        model_id="claude-3-haiku-20240307",
        litellm_model="anthropic/claude-3-haiku-20240307",
        input_cost_per_million=0.25,
        output_cost_per_million=1.25,
    ),
    "claude-3-5-haiku-20241022": ModelConfig(
        provider=LLMProvider.ANTHROPIC,
        model_id="claude-3-5-haiku-20241022",
        litellm_model="anthropic/claude-3-5-haiku-20241022",
        input_cost_per_million=1.00,
        output_cost_per_million=5.00,
    ),
    "claude-3-5-sonnet-20241022": ModelConfig(
        provider=LLMProvider.ANTHROPIC,
        model_id="claude-3-5-sonnet-20241022",
        litellm_model="anthropic/claude-3-5-sonnet-20241022",
        input_cost_per_million=3.00,
        output_cost_per_million=15.00,
    ),
    # OpenAI
    "gpt-4o-mini": ModelConfig(
        provider=LLMProvider.OPENAI,
        model_id="gpt-4o-mini",
        litellm_model="gpt-4o-mini",
        input_cost_per_million=0.15,
        output_cost_per_million=0.60,
    ),
    "gpt-4o": ModelConfig(
        provider=LLMProvider.OPENAI,
        model_id="gpt-4o",
        litellm_model="gpt-4o",
        input_cost_per_million=2.50,
        output_cost_per_million=10.00,
    ),
    "gpt-4-turbo": ModelConfig(
        provider=LLMProvider.OPENAI,
        model_id="gpt-4-turbo",
        litellm_model="gpt-4-turbo",
        input_cost_per_million=10.00,
        output_cost_per_million=30.00,
    ),
    # Ollama (local, free)
    "codellama": ModelConfig(
        provider=LLMProvider.OLLAMA,
        model_id="codellama",
        litellm_model="ollama/codellama",
        input_cost_per_million=0.0,
        output_cost_per_million=0.0,
        supports_system_prompt=True,
    ),
    "deepseek-coder": ModelConfig(
        provider=LLMProvider.OLLAMA,
        model_id="deepseek-coder",
        litellm_model="ollama/deepseek-coder",
        input_cost_per_million=0.0,
        output_cost_per_million=0.0,
    ),
    "llama3.2": ModelConfig(
        provider=LLMProvider.OLLAMA,
        model_id="llama3.2",
        litellm_model="ollama/llama3.2",
        input_cost_per_million=0.0,
        output_cost_per_million=0.0,
    ),
    "qwen2.5-coder": ModelConfig(
        provider=LLMProvider.OLLAMA,
        model_id="qwen2.5-coder",
        litellm_model="ollama/qwen2.5-coder",
        input_cost_per_million=0.0,
        output_cost_per_million=0.0,
    ),
}

# Default models per provider
DEFAULT_MODELS: dict[LLMProvider, str] = {
    LLMProvider.ANTHROPIC: "claude-3-haiku-20240307",
    LLMProvider.OPENAI: "gpt-4o-mini",
    LLMProvider.OLLAMA: "codellama",
    LLMProvider.OPENROUTER: "gpt-4o-mini",  # OpenRouter uses same model names
}


def get_model_config(model_id: str, provider: LLMProvider | None = None) -> ModelConfig:
    """Get configuration for a model.

    Args:
        model_id: The model identifier
        provider: Optional provider hint for unknown models

    Returns:
        ModelConfig for the model

    Raises:
        ValueError: If model is unknown and no provider given
    """
    if model_id in MODELS:
        return MODELS[model_id]

    # Handle unknown models (user-specified)
    if provider is None:
        raise ValueError(
            f"Unknown model '{model_id}'. Either use a known model or specify --llm-provider."
        )

    # Create config for unknown model with zero cost (unknown pricing)
    return ModelConfig(
        provider=provider,
        model_id=model_id,
        litellm_model=_build_litellm_model(model_id, provider),
        input_cost_per_million=0.0,  # Unknown - don't estimate
        output_cost_per_million=0.0,
    )


def _build_litellm_model(model_id: str, provider: LLMProvider) -> str:
    """Build LiteLLM model string for a provider."""
    if provider == LLMProvider.ANTHROPIC:
        return f"anthropic/{model_id}"
    elif provider == LLMProvider.OPENAI:
        return model_id  # OpenAI models don't need prefix
    elif provider == LLMProvider.OLLAMA:
        return f"ollama/{model_id}"
    elif provider == LLMProvider.OPENROUTER:
        return f"openrouter/{model_id}"
    return model_id


def get_default_model(provider: LLMProvider) -> str:
    """Get the default model for a provider."""
    return DEFAULT_MODELS.get(provider, "gpt-4o-mini")


def list_models(provider: LLMProvider | None = None) -> list[ModelConfig]:
    """List available models, optionally filtered by provider."""
    models = list(MODELS.values())
    if provider:
        models = [m for m in models if m.provider == provider]
    return models
