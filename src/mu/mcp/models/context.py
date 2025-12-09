"""Context extraction models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ContextResult:
    """Result of context extraction."""

    mu_text: str
    token_count: int
    node_count: int
    intent: str | None = None
    """Classified intent type (e.g., 'explain', 'impact', 'locate')."""
    intent_confidence: float = 0.0
    """Confidence score for the intent classification (0.0-1.0)."""
    strategy_used: str = "default"
    """Name of the extraction strategy used."""


@dataclass
class OmegaContextOutput:
    """Result of mu_context_omega - OMEGA compressed context."""

    seed: str
    body: str
    macros_used: list[str]
    seed_tokens: int
    body_tokens: int
    original_tokens: int
    compression_ratio: float
    nodes_included: int
    manifest: dict[str, Any]

    @property
    def full_output(self) -> str:
        """Get complete OMEGA output (seed + body)."""
        if self.seed and self.body:
            return f"{self.seed}\n\n;; Codebase Context\n{self.body}"
        elif self.body:
            return f";; Codebase Context\n{self.body}"
        return self.seed or ""

    @property
    def total_tokens(self) -> int:
        """Get total token count (seed + body)."""
        return self.seed_tokens + self.body_tokens
