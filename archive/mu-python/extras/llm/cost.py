"""Cost estimation for LLM summarization."""

from __future__ import annotations

from mu.extras.llm.prompts import format_summarize_prompt
from mu.extras.llm.providers import ModelConfig, get_model_config
from mu.extras.llm.types import CostEstimate, LLMProvider, SummarizationRequest

# Average characters per token (rough estimate)
# Actual tokenization varies by model, but ~4 chars/token is reasonable for code
CHARS_PER_TOKEN = 4

# Estimated output tokens per function summary (3-5 bullets, ~15 words each)
ESTIMATED_OUTPUT_TOKENS_PER_FUNCTION = 100


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text string.

    Uses character-based estimation. For more accuracy, could use
    tiktoken (OpenAI) or anthropic's token counter, but this adds
    dependencies and is usually within 20% for code.

    Args:
        text: The text to estimate

    Returns:
        Estimated token count
    """
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_cost(
    requests: list[SummarizationRequest],
    model: str,
    provider: LLMProvider,
) -> CostEstimate:
    """Estimate the cost of summarizing a list of functions.

    Args:
        requests: List of summarization requests
        model: Model identifier
        provider: LLM provider

    Returns:
        CostEstimate with projected costs
    """
    model_config = get_model_config(model, provider)

    # Calculate input tokens (prompt + code for each function)
    total_input_tokens = 0
    for req in requests:
        prompt = format_summarize_prompt(
            body=req.body_source,
            language=req.language,
            context=req.context,
        )
        total_input_tokens += estimate_tokens(prompt)

    # Estimate output tokens
    total_output_tokens = len(requests) * ESTIMATED_OUTPUT_TOKENS_PER_FUNCTION

    # Calculate cost
    input_cost = (total_input_tokens / 1_000_000) * model_config.input_cost_per_million
    output_cost = (total_output_tokens / 1_000_000) * model_config.output_cost_per_million
    total_cost = input_cost + output_cost

    return CostEstimate(
        function_count=len(requests),
        estimated_input_tokens=total_input_tokens,
        estimated_output_tokens=total_output_tokens,
        estimated_cost_usd=total_cost,
        model=model,
        provider=provider,
    )


def calculate_actual_cost(
    input_tokens: int,
    output_tokens: int,
    model_config: ModelConfig,
) -> float:
    """Calculate actual cost from token counts.

    Args:
        input_tokens: Actual input tokens used
        output_tokens: Actual output tokens used
        model_config: Model configuration with pricing

    Returns:
        Cost in USD
    """
    input_cost = (input_tokens / 1_000_000) * model_config.input_cost_per_million
    output_cost = (output_tokens / 1_000_000) * model_config.output_cost_per_million
    return input_cost + output_cost
