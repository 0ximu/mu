"""MU Diff - Semantic diff between codebase versions.

Compares MU output between git branches/commits to show:
- Added/removed/modified modules
- Function signature changes
- Class hierarchy changes
- Dependency graph changes
"""

from mu.diff.models import (
    DiffResult,
    ModuleDiff,
    FunctionDiff,
    ClassDiff,
    DependencyDiff,
    ChangeType,
)
from mu.diff.differ import SemanticDiffer
from mu.diff.git_utils import GitWorktreeManager
from mu.diff.formatters import format_diff, format_diff_json, format_diff_markdown

__all__ = [
    "DiffResult",
    "ModuleDiff",
    "FunctionDiff",
    "ClassDiff",
    "DependencyDiff",
    "ChangeType",
    "SemanticDiffer",
    "GitWorktreeManager",
    "format_diff",
    "format_diff_json",
    "format_diff_markdown",
]
