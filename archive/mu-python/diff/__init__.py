"""MU Diff - Semantic diff between codebase versions.

Compares MU output between git branches/commits to show:
- Added/removed/modified modules
- Function signature changes
- Class hierarchy changes
- Dependency graph changes

This module provides both Python and Rust implementations:
- Python: `SemanticDiffer` for full assembled codebase diffs
- Rust: `semantic_diff_modules()` for raw ModuleDef diffs (faster)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mu.diff.differ import SemanticDiffer
from mu.diff.formatters import format_diff, format_diff_json, format_diff_markdown
from mu.diff.git_utils import GitWorktreeManager
from mu.diff.models import (
    ChangeType,
    ClassDiff,
    DependencyDiff,
    DiffResult,
    FunctionDiff,
    ModuleDiff,
)

# Type declarations for Rust types when unavailable
DiffSummary: type[Any] | None
EntityChange: type[Any] | None
SemanticDiffResult: type[Any] | None
_rust_semantic_diff: Callable[..., Any] | None

# Import Rust semantic diff types and functions
try:
    from mu._core import (
        DiffSummary,
        EntityChange,
        SemanticDiffResult,
    )
    from mu._core import (
        semantic_diff as _rust_semantic_diff,
    )

    _HAS_RUST_DIFFER = True
except ImportError:
    _HAS_RUST_DIFFER = False
    DiffSummary = None
    EntityChange = None
    SemanticDiffResult = None
    _rust_semantic_diff = None


def semantic_diff_modules(
    base_modules: list[Any],
    head_modules: list[Any],
) -> Any | None:
    """Compute semantic diff between two sets of parsed modules using Rust.

    This is a high-performance alternative to SemanticDiffer for cases where
    you already have ModuleDef objects and don't need dependency graph analysis.

    Args:
        base_modules: List of ModuleDef from the base/old version
        head_modules: List of ModuleDef from the head/new version

    Returns:
        SemanticDiffResult if Rust differ is available, None otherwise.

    Example:
        >>> from mu.parser import parse_file
        >>> from mu.diff import semantic_diff_modules
        >>>
        >>> base = [parse_file("old/main.py")]
        >>> head = [parse_file("new/main.py")]
        >>> result = semantic_diff_modules(base, head)
        >>> if result:
        ...     for change in result.changes:
        ...         print(f"{change.change_type}: {change.entity_name}")
    """
    if not _HAS_RUST_DIFFER or _rust_semantic_diff is None:
        return None
    return _rust_semantic_diff(base_modules, head_modules)


__all__ = [
    # Python types
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
    # Rust types and functions
    "EntityChange",
    "DiffSummary",
    "SemanticDiffResult",
    "semantic_diff_modules",
]
