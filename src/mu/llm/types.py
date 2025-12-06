"""Type definitions for LLM integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


@dataclass
class SummarizationRequest:
    """Request to summarize a function body."""

    function_name: str
    body_source: str
    language: str
    context: str | None = None  # e.g., "ClassName.method_name" or "module_path"
    file_path: str | None = None


@dataclass
class SummarizationResult:
    """Result of a function summarization."""

    function_name: str
    summary: list[str]  # 3-5 bullet points
    tokens_used: int
    model: str
    cached: bool = False
    error: str | None = None

    @property
    def success(self) -> bool:
        """Check if summarization succeeded."""
        return self.error is None and len(self.summary) > 0


@dataclass
class CostEstimate:
    """Estimated cost for LLM summarization."""

    function_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    model: str
    provider: LLMProvider

    def format_summary(self) -> str:
        """Format cost estimate for display."""
        lines = [
            f"Estimated LLM usage:",
            f"  Functions to summarize: {self.function_count}",
            f"  Estimated input tokens: ~{self.estimated_input_tokens:,}",
            f"  Estimated output tokens: ~{self.estimated_output_tokens:,}",
            f"  Model: {self.model}",
        ]
        if self.provider == LLMProvider.OLLAMA:
            lines.append("  Estimated cost: $0.00 (local)")
        else:
            lines.append(f"  Estimated cost: ~${self.estimated_cost_usd:.4f}")
        return "\n".join(lines)


@dataclass
class LLMStats:
    """Statistics from an LLM summarization run."""

    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    cached_hits: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0

    def add_result(self, result: SummarizationResult, cost_per_token: float = 0.0) -> None:
        """Update stats with a result."""
        self.total_requests += 1
        if result.success:
            self.successful += 1
            if result.cached:
                self.cached_hits += 1
            self.total_tokens += result.tokens_used
            self.total_cost_usd += result.tokens_used * cost_per_token
        else:
            self.failed += 1
