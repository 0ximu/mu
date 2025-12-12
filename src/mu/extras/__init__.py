"""MU Extras - Optional features that can be installed separately.

This package contains optional modules that add extra functionality to MU:

- llm: LLM-powered summarization via LiteLLM
- intelligence: Pattern detection, warnings, code analysis
- embeddings: Vector embeddings for semantic search (local model only)

Install with: pip install mu[llm,intelligence,embeddings]
"""

__all__ = [
    "llm",
    "intelligence",
    "embeddings",
]
