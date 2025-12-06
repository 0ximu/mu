"""Data models for semantic diff results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChangeType(Enum):
    """Type of change detected."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass
class ParameterChange:
    """Change to a function parameter."""

    name: str
    change_type: ChangeType
    old_type: str | None = None
    new_type: str | None = None
    old_default: str | None = None
    new_default: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "change_type": self.change_type.value,
            "old_type": self.old_type,
            "new_type": self.new_type,
        }


@dataclass
class FunctionDiff:
    """Diff for a single function or method."""

    name: str
    change_type: ChangeType
    module_path: str
    class_name: str | None = None  # For methods

    # Signature changes
    old_return_type: str | None = None
    new_return_type: str | None = None
    parameter_changes: list[ParameterChange] = field(default_factory=list)

    # Modifier changes
    async_changed: bool = False
    static_changed: bool = False

    # Complexity change
    old_complexity: int = 0
    new_complexity: int = 0

    @property
    def has_signature_change(self) -> bool:
        """Check if the function signature changed."""
        return (
            self.old_return_type != self.new_return_type
            or len(self.parameter_changes) > 0
            or self.async_changed
            or self.static_changed
        )

    @property
    def full_name(self) -> str:
        """Get fully qualified name."""
        if self.class_name:
            return f"{self.class_name}.{self.name}"
        return self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "change_type": self.change_type.value,
            "module_path": self.module_path,
            "class_name": self.class_name,
            "old_return_type": self.old_return_type,
            "new_return_type": self.new_return_type,
            "parameter_changes": [p.to_dict() for p in self.parameter_changes],
            "has_signature_change": self.has_signature_change,
        }


@dataclass
class ClassDiff:
    """Diff for a single class."""

    name: str
    change_type: ChangeType
    module_path: str

    # Inheritance changes
    old_bases: list[str] = field(default_factory=list)
    new_bases: list[str] = field(default_factory=list)

    # Method changes
    added_methods: list[str] = field(default_factory=list)
    removed_methods: list[str] = field(default_factory=list)
    modified_methods: list[FunctionDiff] = field(default_factory=list)

    # Attribute changes
    added_attributes: list[str] = field(default_factory=list)
    removed_attributes: list[str] = field(default_factory=list)

    @property
    def has_inheritance_change(self) -> bool:
        """Check if class inheritance changed."""
        return set(self.old_bases) != set(self.new_bases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "change_type": self.change_type.value,
            "module_path": self.module_path,
            "old_bases": self.old_bases,
            "new_bases": self.new_bases,
            "has_inheritance_change": self.has_inheritance_change,
            "added_methods": self.added_methods,
            "removed_methods": self.removed_methods,
            "modified_methods": [m.to_dict() for m in self.modified_methods],
            "added_attributes": self.added_attributes,
            "removed_attributes": self.removed_attributes,
        }


@dataclass
class ModuleDiff:
    """Diff for a single module/file."""

    path: str
    name: str
    change_type: ChangeType
    language: str

    # Content changes
    added_functions: list[str] = field(default_factory=list)
    removed_functions: list[str] = field(default_factory=list)
    modified_functions: list[FunctionDiff] = field(default_factory=list)

    added_classes: list[str] = field(default_factory=list)
    removed_classes: list[str] = field(default_factory=list)
    modified_classes: list[ClassDiff] = field(default_factory=list)

    # Import changes
    added_imports: list[str] = field(default_factory=list)
    removed_imports: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "change_type": self.change_type.value,
            "language": self.language,
            "added_functions": self.added_functions,
            "removed_functions": self.removed_functions,
            "modified_functions": [f.to_dict() for f in self.modified_functions],
            "added_classes": self.added_classes,
            "removed_classes": self.removed_classes,
            "modified_classes": [c.to_dict() for c in self.modified_classes],
            "added_imports": self.added_imports,
            "removed_imports": self.removed_imports,
        }


@dataclass
class DependencyDiff:
    """Changes to module dependencies."""

    # Internal dependency changes (within codebase)
    added_internal: list[tuple[str, str]] = field(default_factory=list)  # (from, to)
    removed_internal: list[tuple[str, str]] = field(default_factory=list)

    # External package changes
    added_external: list[str] = field(default_factory=list)
    removed_external: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_internal": [{"from": f, "to": t} for f, t in self.added_internal],
            "removed_internal": [{"from": f, "to": t} for f, t in self.removed_internal],
            "added_external": self.added_external,
            "removed_external": self.removed_external,
        }


@dataclass
class DiffStats:
    """Summary statistics for the diff."""

    modules_added: int = 0
    modules_removed: int = 0
    modules_modified: int = 0

    functions_added: int = 0
    functions_removed: int = 0
    functions_modified: int = 0

    classes_added: int = 0
    classes_removed: int = 0
    classes_modified: int = 0

    external_deps_added: int = 0
    external_deps_removed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "modules_added": self.modules_added,
            "modules_removed": self.modules_removed,
            "modules_modified": self.modules_modified,
            "functions_added": self.functions_added,
            "functions_removed": self.functions_removed,
            "functions_modified": self.functions_modified,
            "classes_added": self.classes_added,
            "classes_removed": self.classes_removed,
            "classes_modified": self.classes_modified,
            "external_deps_added": self.external_deps_added,
            "external_deps_removed": self.external_deps_removed,
        }


@dataclass
class DiffResult:
    """Complete semantic diff result."""

    base_ref: str  # Git ref (branch, commit, tag) for base version
    target_ref: str  # Git ref for target version
    source_path: str

    # Module-level changes
    module_diffs: list[ModuleDiff] = field(default_factory=list)

    # Dependency changes
    dependency_diff: DependencyDiff = field(default_factory=DependencyDiff)

    # Statistics
    stats: DiffStats = field(default_factory=DiffStats)

    @property
    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return len(self.module_diffs) > 0 or (
            self.dependency_diff.added_external
            or self.dependency_diff.removed_external
            or self.dependency_diff.added_internal
            or self.dependency_diff.removed_internal
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_ref": self.base_ref,
            "target_ref": self.target_ref,
            "source_path": self.source_path,
            "has_changes": self.has_changes,
            "stats": self.stats.to_dict(),
            "module_diffs": [m.to_dict() for m in self.module_diffs],
            "dependency_diff": self.dependency_diff.to_dict(),
        }
