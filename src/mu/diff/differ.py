"""Semantic differ - compares parsed codebases to find semantic changes."""

from __future__ import annotations

from pathlib import Path

from mu.assembler import AssembledOutput, DependencyType
from mu.parser.models import ClassDef, FunctionDef, ModuleDef, ParameterDef
from mu.reducer.generator import ReducedCodebase, ReducedModule

from mu.diff.models import (
    ChangeType,
    ClassDiff,
    DependencyDiff,
    DiffResult,
    DiffStats,
    FunctionDiff,
    ModuleDiff,
    ParameterChange,
)


class SemanticDiffer:
    """Compares two assembled codebases to produce semantic diff."""

    def __init__(
        self,
        base: AssembledOutput,
        target: AssembledOutput,
        base_ref: str,
        target_ref: str,
    ):
        """Initialize differ with two assembled codebases.

        Args:
            base: The base (older) version of the codebase.
            target: The target (newer) version of the codebase.
            base_ref: Git reference for base version.
            target_ref: Git reference for target version.
        """
        self.base = base
        self.target = target
        self.base_ref = base_ref
        self.target_ref = target_ref

    def diff(self) -> DiffResult:
        """Compute semantic diff between base and target.

        Returns:
            DiffResult containing all changes.
        """
        result = DiffResult(
            base_ref=self.base_ref,
            target_ref=self.target_ref,
            source_path=self.target.codebase.source,
        )

        # Build module indexes
        base_modules = {m.path: m for m in self.base.codebase.modules}
        target_modules = {m.path: m for m in self.target.codebase.modules}

        base_paths = set(base_modules.keys())
        target_paths = set(target_modules.keys())

        # Find added, removed, and common modules
        added_paths = target_paths - base_paths
        removed_paths = base_paths - target_paths
        common_paths = base_paths & target_paths

        # Process added modules
        for path in sorted(added_paths):
            module = target_modules[path]
            diff = self._create_added_module_diff(module)
            result.module_diffs.append(diff)
            result.stats.modules_added += 1
            result.stats.functions_added += len(diff.added_functions)
            result.stats.classes_added += len(diff.added_classes)

        # Process removed modules
        for path in sorted(removed_paths):
            module = base_modules[path]
            diff = self._create_removed_module_diff(module)
            result.module_diffs.append(diff)
            result.stats.modules_removed += 1
            result.stats.functions_removed += len(diff.removed_functions)
            result.stats.classes_removed += len(diff.removed_classes)

        # Process modified modules
        for path in sorted(common_paths):
            base_module = base_modules[path]
            target_module = target_modules[path]
            module_diff = self._diff_modules(base_module, target_module)

            if module_diff is not None:
                result.module_diffs.append(module_diff)
                result.stats.modules_modified += 1
                result.stats.functions_added += len(module_diff.added_functions)
                result.stats.functions_removed += len(module_diff.removed_functions)
                result.stats.functions_modified += len(module_diff.modified_functions)
                result.stats.classes_added += len(module_diff.added_classes)
                result.stats.classes_removed += len(module_diff.removed_classes)
                result.stats.classes_modified += len(module_diff.modified_classes)

        # Diff dependencies
        result.dependency_diff = self._diff_dependencies()
        result.stats.external_deps_added = len(result.dependency_diff.added_external)
        result.stats.external_deps_removed = len(result.dependency_diff.removed_external)

        return result

    def _create_added_module_diff(self, module: ReducedModule) -> ModuleDiff:
        """Create diff for a newly added module."""
        return ModuleDiff(
            path=module.path,
            name=module.name,
            change_type=ChangeType.ADDED,
            language=module.language,
            added_functions=[f.name for f in module.functions],
            added_classes=[c.name for c in module.classes],
            added_imports=[i.module for i in module.imports if i.module],
        )

    def _create_removed_module_diff(self, module: ReducedModule) -> ModuleDiff:
        """Create diff for a removed module."""
        return ModuleDiff(
            path=module.path,
            name=module.name,
            change_type=ChangeType.REMOVED,
            language=module.language,
            removed_functions=[f.name for f in module.functions],
            removed_classes=[c.name for c in module.classes],
            removed_imports=[i.module for i in module.imports if i.module],
        )

    def _diff_modules(
        self,
        base: ReducedModule,
        target: ReducedModule,
    ) -> ModuleDiff | None:
        """Diff two versions of the same module.

        Returns None if there are no changes.
        """
        diff = ModuleDiff(
            path=target.path,
            name=target.name,
            change_type=ChangeType.MODIFIED,
            language=target.language,
        )

        # Diff functions
        base_funcs = {f.name: f for f in base.functions}
        target_funcs = {f.name: f for f in target.functions}

        diff.added_functions = sorted(set(target_funcs.keys()) - set(base_funcs.keys()))
        diff.removed_functions = sorted(set(base_funcs.keys()) - set(target_funcs.keys()))

        # Check for modified functions
        for name in sorted(set(base_funcs.keys()) & set(target_funcs.keys())):
            func_diff = self._diff_functions(
                base_funcs[name],
                target_funcs[name],
                target.path,
            )
            if func_diff is not None:
                diff.modified_functions.append(func_diff)

        # Diff classes
        base_classes = {c.name: c for c in base.classes}
        target_classes = {c.name: c for c in target.classes}

        diff.added_classes = sorted(set(target_classes.keys()) - set(base_classes.keys()))
        diff.removed_classes = sorted(set(base_classes.keys()) - set(target_classes.keys()))

        # Check for modified classes
        for name in sorted(set(base_classes.keys()) & set(target_classes.keys())):
            class_diff = self._diff_classes(
                base_classes[name],
                target_classes[name],
                target.path,
            )
            if class_diff is not None:
                diff.modified_classes.append(class_diff)

        # Diff imports
        base_imports = {i.module for i in base.imports if i.module}
        target_imports = {i.module for i in target.imports if i.module}

        diff.added_imports = sorted(target_imports - base_imports)
        diff.removed_imports = sorted(base_imports - target_imports)

        # Check if there are any changes
        has_changes = (
            diff.added_functions
            or diff.removed_functions
            or diff.modified_functions
            or diff.added_classes
            or diff.removed_classes
            or diff.modified_classes
            or diff.added_imports
            or diff.removed_imports
        )

        return diff if has_changes else None

    def _diff_functions(
        self,
        base: FunctionDef,
        target: FunctionDef,
        module_path: str,
        class_name: str | None = None,
    ) -> FunctionDiff | None:
        """Diff two versions of the same function.

        Returns None if there are no changes.
        """
        diff = FunctionDiff(
            name=target.name,
            change_type=ChangeType.MODIFIED,
            module_path=module_path,
            class_name=class_name,
        )

        has_changes = False

        # Check return type
        if base.return_type != target.return_type:
            diff.old_return_type = base.return_type
            diff.new_return_type = target.return_type
            has_changes = True

        # Check async modifier
        if base.is_async != target.is_async:
            diff.async_changed = True
            has_changes = True

        # Check static modifier
        if base.is_static != target.is_static:
            diff.static_changed = True
            has_changes = True

        # Check complexity
        if base.body_complexity != target.body_complexity:
            diff.old_complexity = base.body_complexity
            diff.new_complexity = target.body_complexity
            has_changes = True

        # Diff parameters
        param_changes = self._diff_parameters(base.parameters, target.parameters)
        if param_changes:
            diff.parameter_changes = param_changes
            has_changes = True

        return diff if has_changes else None

    def _diff_parameters(
        self,
        base_params: list[ParameterDef],
        target_params: list[ParameterDef],
    ) -> list[ParameterChange]:
        """Diff function parameters."""
        changes: list[ParameterChange] = []

        base_by_name = {p.name: p for p in base_params}
        target_by_name = {p.name: p for p in target_params}

        base_names = set(base_by_name.keys())
        target_names = set(target_by_name.keys())

        # Added parameters
        for name in sorted(target_names - base_names):
            param = target_by_name[name]
            changes.append(
                ParameterChange(
                    name=name,
                    change_type=ChangeType.ADDED,
                    new_type=param.type_annotation,
                    new_default=param.default_value,
                )
            )

        # Removed parameters
        for name in sorted(base_names - target_names):
            param = base_by_name[name]
            changes.append(
                ParameterChange(
                    name=name,
                    change_type=ChangeType.REMOVED,
                    old_type=param.type_annotation,
                    old_default=param.default_value,
                )
            )

        # Modified parameters
        for name in sorted(base_names & target_names):
            base_param = base_by_name[name]
            target_param = target_by_name[name]

            if (
                base_param.type_annotation != target_param.type_annotation
                or base_param.default_value != target_param.default_value
            ):
                changes.append(
                    ParameterChange(
                        name=name,
                        change_type=ChangeType.MODIFIED,
                        old_type=base_param.type_annotation,
                        new_type=target_param.type_annotation,
                        old_default=base_param.default_value,
                        new_default=target_param.default_value,
                    )
                )

        return changes

    def _diff_classes(
        self,
        base: ClassDef,
        target: ClassDef,
        module_path: str,
    ) -> ClassDiff | None:
        """Diff two versions of the same class.

        Returns None if there are no changes.
        """
        diff = ClassDiff(
            name=target.name,
            change_type=ChangeType.MODIFIED,
            module_path=module_path,
        )

        has_changes = False

        # Check inheritance
        if set(base.bases) != set(target.bases):
            diff.old_bases = list(base.bases)
            diff.new_bases = list(target.bases)
            has_changes = True

        # Diff methods
        base_methods = {m.name: m for m in base.methods}
        target_methods = {m.name: m for m in target.methods}

        diff.added_methods = sorted(set(target_methods.keys()) - set(base_methods.keys()))
        diff.removed_methods = sorted(set(base_methods.keys()) - set(target_methods.keys()))

        if diff.added_methods or diff.removed_methods:
            has_changes = True

        # Check for modified methods
        for name in sorted(set(base_methods.keys()) & set(target_methods.keys())):
            method_diff = self._diff_functions(
                base_methods[name],
                target_methods[name],
                module_path,
                class_name=target.name,
            )
            if method_diff is not None:
                diff.modified_methods.append(method_diff)
                has_changes = True

        # Diff attributes
        base_attrs = set(base.attributes)
        target_attrs = set(target.attributes)

        diff.added_attributes = sorted(target_attrs - base_attrs)
        diff.removed_attributes = sorted(base_attrs - target_attrs)

        if diff.added_attributes or diff.removed_attributes:
            has_changes = True

        return diff if has_changes else None

    def _diff_dependencies(self) -> DependencyDiff:
        """Diff dependency graphs between base and target."""
        diff = DependencyDiff()

        # Get internal dependencies from graphs
        base_internal = set()
        target_internal = set()

        for from_path, to_path, dep_type in self.base.graph.edges:
            if dep_type == DependencyType.INTERNAL:
                base_internal.add((from_path, to_path))

        for from_path, to_path, dep_type in self.target.graph.edges:
            if dep_type == DependencyType.INTERNAL:
                target_internal.add((from_path, to_path))

        diff.added_internal = sorted(target_internal - base_internal)
        diff.removed_internal = sorted(base_internal - target_internal)

        # Get external packages
        base_external = self.base.graph.get_external_packages()
        target_external = self.target.graph.get_external_packages()

        diff.added_external = sorted(target_external - base_external)
        diff.removed_external = sorted(base_external - target_external)

        return diff


def compute_diff(
    base: AssembledOutput,
    target: AssembledOutput,
    base_ref: str,
    target_ref: str,
) -> DiffResult:
    """Convenience function to compute semantic diff.

    Args:
        base: The base (older) assembled codebase.
        target: The target (newer) assembled codebase.
        base_ref: Git reference for base version.
        target_ref: Git reference for target version.

    Returns:
        DiffResult containing all semantic changes.
    """
    differ = SemanticDiffer(base, target, base_ref, target_ref)
    return differ.diff()
