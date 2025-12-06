# ADR-0003: Use LiteLLM for Multi-Provider LLM Integration

## Status

Accepted

## Date

2025-01

## Context

MU uses LLMs for enhanced function summarization when the `--llm` flag is provided. We need to support multiple LLM providers:
- Anthropic (Claude)
- OpenAI (GPT-4)
- Local models (Ollama)
- OpenRouter (multiple models)

Managing multiple provider SDKs with different APIs, authentication, and error handling would be complex.

## Decision

Use LiteLLM as a unified interface for all LLM providers.

LiteLLM provides a consistent OpenAI-compatible API that works with 100+ LLM providers, handling:
- Authentication
- Request formatting
- Response parsing
- Error handling
- Rate limiting

## Consequences

### Positive
- Single API for all providers
- Easy to add new providers without code changes
- Built-in retry logic and error handling
- Cost tracking and logging
- Community-maintained provider support

### Negative
- Additional dependency
- Slight abstraction overhead
- May lag behind provider-specific features
- Must use async operations to avoid blocking

### Neutral
- Configuration via environment variables (standard pattern)
- Provider selection via `--llm-provider` CLI flag

## Alternatives Considered

### Alternative 1: Direct provider SDKs
- Pros: Full access to provider-specific features
- Cons: Multiple SDKs, inconsistent APIs, maintenance burden
- Why rejected: Too much complexity for our use case

### Alternative 2: Custom abstraction layer
- Pros: Full control, no external dependency
- Cons: Significant development effort, ongoing maintenance
- Why rejected: LiteLLM already solves this well

### Alternative 3: LangChain
- Pros: Rich ecosystem, many integrations
- Cons: Heavy dependency, too many features we don't need
- Why rejected: Overkill for simple LLM calls

## References

- [LiteLLM documentation](https://docs.litellm.ai/)
- [Supported providers](https://docs.litellm.ai/docs/providers)
- Implementation: `src/mu/llm/`
