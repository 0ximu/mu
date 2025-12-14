"""MU Kernel Temporal Layer - Git-linked snapshots and time-travel queries.

This module provides temporal capabilities for MUbase:
- Create snapshots of the code graph at specific git commits
- Query historical states of the codebase
- Track node/edge changes over time
- Blame-like attribution for code entities
- Semantic diff between points in time
"""

from __future__ import annotations

from mu.kernel.schema import ChangeType
from mu.kernel.temporal.diff import TemporalDiffer
from mu.kernel.temporal.git import CommitInfo, GitError, GitIntegration
from mu.kernel.temporal.history import HistoryTracker
from mu.kernel.temporal.models import (
    EdgeChange,
    EdgeDiff,
    GraphDiff,
    NodeChange,
    NodeDiff,
    Snapshot,
)
from mu.kernel.temporal.snapshot import MUbaseSnapshot, SnapshotManager

__all__ = [
    # Enums
    "ChangeType",
    # Models
    "Snapshot",
    "NodeChange",
    "EdgeChange",
    "NodeDiff",
    "EdgeDiff",
    "GraphDiff",
    # Git integration
    "GitError",
    "CommitInfo",
    "GitIntegration",
    # Core classes
    "SnapshotManager",
    "MUbaseSnapshot",
    "HistoryTracker",
    "TemporalDiffer",
]
