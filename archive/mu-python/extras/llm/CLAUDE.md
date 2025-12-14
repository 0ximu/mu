# LLM Module - Multi-Provider Integration

The LLM module provides async batch summarization of complex functions using multiple LLM providers via LiteLLM.

## Architecture

```
SummarizationRequest -> LLMPool -> LiteLLM -> Provider API
                           |
                      Cache Layer (persistent + memory)
```

### Files

| File | Purpose |
|------|---------|
| `pool.py` | `LLMPool` class - async batch processing, caching, retries |
| `providers.py` | Provider configurations, model mappings |
| `prompts.py` | Summarization prompt templates, response parsing |
| `cost.py` | Token cost estimation per provider |
| `types.py` | Type definitions: `LLMProvider`, `SummarizationRequest`, `SummarizationResult` |

## Supported Providers

| Provider | Config Key | Model Examples |
|----------|------------|----------------|
| Anthropic | `anthropic` | claude-3-opus, claude-3-sonnet, claude-3-haiku |
| OpenAI | `openai` | gpt-4, gpt-4-turbo, gpt-3.5-turbo |
| Ollama | `ollama` | llama2, codellama, mistral |
| OpenRouter | `openrouter` | Various (uses LiteLLM routing) |

## LLMPool Usage

```python
from mu.extras.llm.pool import LLMPool, create_pool
from mu.extras.llm.types import SummarizationRequest

# Create pool from config
pool = create_pool(
    config=llm_config,
    cache_config=cache_config,
    cache_base_path=cache_path,
)

# Single summarization
result = await pool.summarize(SummarizationRequest(
    function_name="process_data",
    body_source="def process_data(items): ...",
    language="python",
    context="Data processing utility",
))

# Batch summarization with progress
results = await pool.summarize_batch(
    requests=requests_list,
    progress_callback=lambda done, total: print(f"{done}/{total}"),
)

# Close when done
pool.close()
```

## Caching Strategy

### Cache Key Components
- Content hash of function body
- Prompt version (`PROMPT_VERSION` in `prompts.py`)
- Model name

### Cache Layers
1. **Persistent cache**: `CacheManager` via diskcache (survives restarts)
2. **Memory cache**: Dict in `LLMPool` (session-local hits)

### Cache Invalidation
Cache is automatically invalidated when:
- Function body changes (different hash)
- Prompt template changes (bump `PROMPT_VERSION`)
- Model changes (different model in config)

## Adding a New Provider

LiteLLM handles most providers. To add a new one:

1. Ensure LiteLLM supports it (check their docs)
2. Add model config in `providers.py`:
   ```python
   MODEL_CONFIGS["new-model"] = ModelConfig(
       provider=LLMProvider.NEW_PROVIDER,
       litellm_model="new_provider/model-name",
       max_tokens=4096,
       cost_per_1k_input=0.001,
       cost_per_1k_output=0.002,
   )
   ```
3. Add provider enum in `types.py` if needed
4. Update configuration in `config.py`

## Prompt Engineering

Prompts in `prompts.py` use a structured format:

```python
SUMMARIZE_PROMPT = """
Summarize this {language} function concisely.
Focus on: what it does, key dependencies, side effects.

Function:
```{language}
{body}
```

Context: {context}

Return 1-3 bullet points.
"""
```

### Prompt Version
When changing prompts, **always bump `PROMPT_VERSION`** to invalidate cache:
```python
PROMPT_VERSION = "v2"  # Was "v1"
```

## Error Handling

```python
result = await pool.summarize(request)

if result.error:
    # Handle error (auth failure, timeout, rate limit exhausted)
    print(f"Error: {result.error}")
else:
    # Use result.summary (list of bullet points)
    for bullet in result.summary:
        print(f"- {bullet}")
```

### Retry Logic
- Rate limits: Exponential backoff (2, 4, 8... up to 60s)
- Timeouts: Configurable via `config.timeout_seconds`
- Auth errors: No retry (immediate failure)
- Other errors: Up to `config.max_retries` attempts

## Cost Estimation

```python
from mu.extras.llm.cost import estimate_cost

# Before making calls
estimated = estimate_cost(
    requests=pending_requests,
    model="claude-3-haiku",
    provider=LLMProvider.ANTHROPIC,
)
print(f"Estimated cost: ${estimated:.4f}")
```

## Configuration

In `.murc.toml`:
```toml
[llm]
provider = "anthropic"  # or "openai", "ollama", "openrouter"
model = "claude-3-haiku"
timeout_seconds = 30
max_retries = 2

[llm.ollama]
base_url = "http://localhost:11434"  # For local Ollama
```

Environment variables:
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `OPENROUTER_API_KEY`

## Anti-Patterns

1. **Never** make synchronous LLM calls - always use async `summarize()` or `summarize_batch()`
2. **Never** bypass `LLMPool` caching - it prevents redundant API calls
3. **Never** change prompts without bumping `PROMPT_VERSION`
4. **Never** hardcode API keys - use environment variables
5. **Never** set concurrency > 10 for API providers (rate limiting)

## Testing

```bash
# Run LLM tests (may require API keys or mocks)
pytest tests/unit/test_llm.py -v

# Test with mock responses
pytest tests/unit/test_llm.py -v -k "mock"
```

Mock the LiteLLM calls for unit tests:
```python
@patch("mu.extras.llm.pool.acompletion")
async def test_summarize(mock_completion):
    mock_completion.return_value = MockResponse(...)
    ...
```
