"""Guidance models (patterns, warnings)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PatternInfo:
    """Information about a detected pattern."""

    name: str
    category: str
    description: str
    frequency: int
    confidence: float
    examples: list[dict[str, Any]]
    anti_patterns: list[str]


@dataclass
class PatternsOutput:
    """Result of mu_patterns - detected codebase patterns."""

    patterns: list[PatternInfo]
    total_patterns: int
    categories_found: list[str]
    detection_time_ms: float


@dataclass
class WarningInfo:
    """Information about a proactive warning."""

    category: str
    level: str
    message: str
    details: dict[str, Any] | None = None


@dataclass
class WarningsOutput:
    """Result of mu_warn - proactive warnings for a target."""

    target: str
    target_type: str
    warnings: list[WarningInfo]
    summary: str
    risk_score: float
    analysis_time_ms: float
