"""Analysis models (diff, impact, deps)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mu.mcp.models.common import NodeInfo


@dataclass
class DepsResult:
    """Result of dependency lookup."""

    node_id: str
    direction: str
    dependencies: list[NodeInfo]


@dataclass
class ImpactResult:
    """Result of impact analysis."""

    node_id: str
    impacted_nodes: list[str]
    count: int


@dataclass
class SemanticDiffOutput:
    """Result of mu_semantic_diff."""

    base_ref: str
    head_ref: str
    changes: list[dict[str, Any]]
    breaking_changes: list[dict[str, Any]]
    summary_text: str
    has_breaking_changes: bool
    total_changes: int


@dataclass
class ViolationInfo:
    """Information about a pattern violation."""

    file_path: str
    line_start: int | None
    line_end: int | None
    severity: str
    rule: str
    message: str
    suggestion: str
    pattern_category: str


@dataclass
class ReviewDiffOutput:
    """Result of mu_review_diff - semantic diff with pattern validation."""

    base_ref: str
    head_ref: str
    # Semantic diff section
    changes: list[dict[str, Any]]
    breaking_changes: list[dict[str, Any]]
    has_breaking_changes: bool
    total_changes: int
    # Pattern validation section
    violations: list[ViolationInfo]
    patterns_checked: list[str]
    files_checked: list[str]
    error_count: int
    warning_count: int
    info_count: int
    patterns_valid: bool
    # Summary
    review_summary: str
    review_time_ms: float
