"""Shared Anthropic client for MU-SIGMA.

Provides a reusable async client to avoid per-call instantiation overhead.
"""

from __future__ import annotations

import anthropic


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    """Get a shared Anthropic client.

    The client is created once and reused across calls.
    This avoids the overhead of creating a new client for each LLM call.

    Returns:
        AsyncAnthropic client configured from environment
    """
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


def reset_client() -> None:
    """Reset the shared client (useful for testing)."""
    global _client
    _client = None


# Module-level singleton
_client: anthropic.AsyncAnthropic | None = None
