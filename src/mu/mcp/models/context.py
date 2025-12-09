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


@dataclass
class OmegaContextOutput:
    """Result of mu_context_omega - OMEGA compressed context."""

    seed: str
    body: str
    full_output: str
    macros_used: list[str]
    seed_tokens: int
    body_tokens: int
    total_tokens: int
    original_tokens: int
    compression_ratio: float
    nodes_included: int
    manifest: dict[str, Any]
