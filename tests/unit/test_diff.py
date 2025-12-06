"""Tests for the semantic diff module."""

from __future__ import annotations

import pytest
from pathlib import Path

from mu.parser.models import (
    ClassDef,
    FunctionDef,
    ImportDef,
    ModuleDef,
    ParameterDef,
)
from mu.reducer.generator import ReducedCodebase, ReducedModule
from mu.assembler import AssembledOutput, ModuleGraph, ModuleNode, DependencyType


# Test fixtures
@pytest.fixture
def base_module() -> ReducedModule:
    """Create a base module for testing."""
    return ReducedModule(
        name="test_module",
        path="src/test_module.py",
        language="python",
        imports=[
            ImportDef(module="os", names=[], is_from=False),
            ImportDef(module="json", names=["loads"], is_from=True),
        ],
        classes=[
            ClassDef(
                name="MyClass",
                bases=["BaseClass"],
                methods=[
                    FunctionDef(
                        name="my_method",
                        parameters=[
                            ParameterDef(name="x", type_annotation="int"),
                            ParameterDef(name="y", type_annotation="str"),
                        ],
                        return_type="bool",
                        is_method=True,
                    ),
                ],
                attributes=["name", "value"],
            ),
        ],
        functions=[
            FunctionDef(
                name="helper_func",
                parameters=[ParameterDef(name="data", type_annotation="dict")],
                return_type="list",
            ),
        ],
    )


@pytest.fixture
def modified_module() -> ReducedModule:
    """Create a modified version of the base module."""
    return ReducedModule(
        name="test_module",
        path="src/test_module.py",
        language="python",
        imports=[
            ImportDef(module="os", names=[], is_from=False),
            ImportDef(module="typing", names=["Optional"], is_from=True),  # Changed import
        ],
        classes=[
            ClassDef(
                name="MyClass",
                bases=["BaseClass", "Mixin"],  # Added base
                methods=[
                    FunctionDef(
                        name="my_method",
                        parameters=[
                            ParameterDef(name="x", type_annotation="int"),
                            ParameterDef(name="y", type_annotation="str"),
                            ParameterDef(name="z", type_annotation="bool"),  # Added param
                        ],
                        return_type="Optional[bool]",  # Changed return type
                        is_method=True,
                    ),
                    FunctionDef(
                        name="new_method",  # New method
                        parameters=[],
                        return_type="None",
                        is_method=True,
                    ),
                ],
                attributes=["name", "value", "status"],  # Added attribute
            ),
        ],
        functions=[
            FunctionDef(
                name="helper_func",
                parameters=[ParameterDef(name="data", type_annotation="dict")],
                return_type="list",
            ),
            FunctionDef(
                name="new_helper",  # New function
                parameters=[],
                return_type="str",
            ),
        ],
    )


def create_assembled_output(modules: list[ReducedModule]) -> AssembledOutput:
    """Create an AssembledOutput from reduced modules."""
    graph = ModuleGraph()
    for mod in modules:
        node = ModuleNode(
            name=mod.name,
            path=mod.path,
            language=mod.language,
        )
        graph.add_node(node)

    codebase = ReducedCodebase(
        source="/test/path",
        modules=modules,
    )

    return AssembledOutput(
        codebase=codebase,
        graph=graph,
        topological_order=[m.path for m in modules],
        external_packages=set(),
    )


class TestModuleDiff:
    """Tests for module-level diffing."""

    def test_added_module(self, base_module: ReducedModule):
        """Test detecting added modules."""
        from mu.diff.differ import SemanticDiffer

        base = create_assembled_output([])
        target = create_assembled_output([base_module])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert result.has_changes
        assert result.stats.modules_added == 1
        assert len(result.module_diffs) == 1
        assert result.module_diffs[0].change_type.value == "added"
        assert result.module_diffs[0].path == "src/test_module.py"

    def test_removed_module(self, base_module: ReducedModule):
        """Test detecting removed modules."""
        from mu.diff.differ import SemanticDiffer

        base = create_assembled_output([base_module])
        target = create_assembled_output([])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert result.has_changes
        assert result.stats.modules_removed == 1
        assert len(result.module_diffs) == 1
        assert result.module_diffs[0].change_type.value == "removed"

    def test_modified_module(self, base_module: ReducedModule, modified_module: ReducedModule):
        """Test detecting modified modules."""
        from mu.diff.differ import SemanticDiffer

        base = create_assembled_output([base_module])
        target = create_assembled_output([modified_module])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert result.has_changes
        assert result.stats.modules_modified == 1

        mod_diff = result.module_diffs[0]
        assert mod_diff.change_type.value == "modified"
        assert "new_helper" in mod_diff.added_functions
        assert len(mod_diff.modified_classes) == 1

    def test_no_changes(self, base_module: ReducedModule):
        """Test when there are no changes."""
        from mu.diff.differ import SemanticDiffer

        base = create_assembled_output([base_module])
        target = create_assembled_output([base_module])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert not result.has_changes


class TestFunctionDiff:
    """Tests for function-level diffing."""

    def test_added_parameter(self):
        """Test detecting added parameters."""
        from mu.diff.differ import SemanticDiffer

        base_func = FunctionDef(
            name="test_func",
            parameters=[ParameterDef(name="x", type_annotation="int")],
            return_type="int",
        )
        target_func = FunctionDef(
            name="test_func",
            parameters=[
                ParameterDef(name="x", type_annotation="int"),
                ParameterDef(name="y", type_annotation="str"),
            ],
            return_type="int",
        )

        base_mod = ReducedModule(
            name="test", path="test.py", language="python",
            functions=[base_func],
        )
        target_mod = ReducedModule(
            name="test", path="test.py", language="python",
            functions=[target_func],
        )

        base = create_assembled_output([base_mod])
        target = create_assembled_output([target_mod])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert result.has_changes
        assert len(result.module_diffs[0].modified_functions) == 1
        func_diff = result.module_diffs[0].modified_functions[0]
        assert len(func_diff.parameter_changes) == 1
        assert func_diff.parameter_changes[0].name == "y"
        assert func_diff.parameter_changes[0].change_type.value == "added"

    def test_return_type_change(self):
        """Test detecting return type changes."""
        from mu.diff.differ import SemanticDiffer

        base_func = FunctionDef(
            name="test_func",
            parameters=[],
            return_type="int",
        )
        target_func = FunctionDef(
            name="test_func",
            parameters=[],
            return_type="str",
        )

        base_mod = ReducedModule(
            name="test", path="test.py", language="python",
            functions=[base_func],
        )
        target_mod = ReducedModule(
            name="test", path="test.py", language="python",
            functions=[target_func],
        )

        base = create_assembled_output([base_mod])
        target = create_assembled_output([target_mod])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert result.has_changes
        func_diff = result.module_diffs[0].modified_functions[0]
        assert func_diff.old_return_type == "int"
        assert func_diff.new_return_type == "str"


class TestClassDiff:
    """Tests for class-level diffing."""

    def test_inheritance_change(self):
        """Test detecting inheritance changes."""
        from mu.diff.differ import SemanticDiffer

        base_class = ClassDef(name="MyClass", bases=["Base1"])
        target_class = ClassDef(name="MyClass", bases=["Base1", "Base2"])

        base_mod = ReducedModule(
            name="test", path="test.py", language="python",
            classes=[base_class],
        )
        target_mod = ReducedModule(
            name="test", path="test.py", language="python",
            classes=[target_class],
        )

        base = create_assembled_output([base_mod])
        target = create_assembled_output([target_mod])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert result.has_changes
        class_diff = result.module_diffs[0].modified_classes[0]
        assert class_diff.has_inheritance_change
        assert "Base2" in class_diff.new_bases
        assert "Base2" not in class_diff.old_bases

    def test_added_method(self):
        """Test detecting added methods."""
        from mu.diff.differ import SemanticDiffer

        base_class = ClassDef(
            name="MyClass",
            methods=[FunctionDef(name="method1", parameters=[], is_method=True)],
        )
        target_class = ClassDef(
            name="MyClass",
            methods=[
                FunctionDef(name="method1", parameters=[], is_method=True),
                FunctionDef(name="method2", parameters=[], is_method=True),
            ],
        )

        base_mod = ReducedModule(
            name="test", path="test.py", language="python",
            classes=[base_class],
        )
        target_mod = ReducedModule(
            name="test", path="test.py", language="python",
            classes=[target_class],
        )

        base = create_assembled_output([base_mod])
        target = create_assembled_output([target_mod])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert result.has_changes
        class_diff = result.module_diffs[0].modified_classes[0]
        assert "method2" in class_diff.added_methods


class TestDependencyDiff:
    """Tests for dependency diffing."""

    def test_added_external_dependency(self):
        """Test detecting added external dependencies."""
        from mu.diff.differ import SemanticDiffer

        base_graph = ModuleGraph()
        target_graph = ModuleGraph()

        node = ModuleNode(name="test", path="test.py", language="python")
        node.external_deps = ["requests"]
        target_graph.add_node(node)

        base = AssembledOutput(
            codebase=ReducedCodebase(source="/test", modules=[]),
            graph=base_graph,
            topological_order=[],
            external_packages=set(),
        )
        target = AssembledOutput(
            codebase=ReducedCodebase(source="/test", modules=[]),
            graph=target_graph,
            topological_order=[],
            external_packages={"requests"},
        )

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        assert "requests" in result.dependency_diff.added_external


class TestFormatters:
    """Tests for diff output formatters."""

    def test_format_diff_terminal(self, base_module: ReducedModule, modified_module: ReducedModule):
        """Test terminal output formatting."""
        from mu.diff.differ import SemanticDiffer
        from mu.diff.formatters import format_diff

        base = create_assembled_output([base_module])
        target = create_assembled_output([modified_module])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        output = format_diff(result, no_color=True)

        assert "main → feature" in output
        assert "Modules:" in output
        assert "test_module.py" in output

    def test_format_diff_json(self, base_module: ReducedModule, modified_module: ReducedModule):
        """Test JSON output formatting."""
        import json
        from mu.diff.differ import SemanticDiffer
        from mu.diff.formatters import format_diff_json

        base = create_assembled_output([base_module])
        target = create_assembled_output([modified_module])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        output = format_diff_json(result)
        data = json.loads(output)

        assert data["base_ref"] == "main"
        assert data["target_ref"] == "feature"
        assert data["has_changes"] is True
        assert "module_diffs" in data

    def test_format_diff_markdown(self, base_module: ReducedModule, modified_module: ReducedModule):
        """Test Markdown output formatting."""
        from mu.diff.differ import SemanticDiffer
        from mu.diff.formatters import format_diff_markdown

        base = create_assembled_output([base_module])
        target = create_assembled_output([modified_module])

        differ = SemanticDiffer(base, target, "main", "feature")
        result = differ.diff()

        output = format_diff_markdown(result)

        assert "# Semantic Diff" in output
        assert "## Summary" in output
        assert "| Modules |" in output


class TestDiffModels:
    """Tests for diff data models."""

    def test_diff_result_to_dict(self):
        """Test DiffResult serialization."""
        from mu.diff.models import DiffResult, DiffStats, ModuleDiff, ChangeType

        result = DiffResult(
            base_ref="main",
            target_ref="feature",
            source_path="/test",
            module_diffs=[
                ModuleDiff(
                    path="test.py",
                    name="test",
                    change_type=ChangeType.ADDED,
                    language="python",
                ),
            ],
            stats=DiffStats(modules_added=1),
        )

        data = result.to_dict()

        assert data["base_ref"] == "main"
        assert data["target_ref"] == "feature"
        assert data["has_changes"] is True
        assert len(data["module_diffs"]) == 1

    def test_function_diff_full_name(self):
        """Test FunctionDiff full name property."""
        from mu.diff.models import FunctionDiff, ChangeType

        # Top-level function
        func = FunctionDiff(
            name="my_func",
            change_type=ChangeType.MODIFIED,
            module_path="test.py",
        )
        assert func.full_name == "my_func"

        # Method
        method = FunctionDiff(
            name="my_method",
            change_type=ChangeType.MODIFIED,
            module_path="test.py",
            class_name="MyClass",
        )
        assert method.full_name == "MyClass.my_method"
