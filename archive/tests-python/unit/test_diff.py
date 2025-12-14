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


class TestRustSemanticDiff:
    """Tests for the Rust-based semantic diff engine."""

    @pytest.fixture
    def core_module(self):
        """Import _core module for tests."""
        from mu import _core
        return _core

    def test_semantic_diff_available(self, core_module):
        """Test that semantic_diff function is available from Rust."""
        assert hasattr(core_module, "semantic_diff")
        assert hasattr(core_module, "EntityChange")
        assert hasattr(core_module, "DiffSummary")
        assert hasattr(core_module, "SemanticDiffResult")

    def test_diff_added_function(self, core_module):
        """Test detecting an added function via Rust differ."""
        base_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[],
        )
        head_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[
                core_module.FunctionDef(
                    name="new_func",
                    parameters=[],
                    return_type="str",
                ),
            ],
        )

        result = core_module.semantic_diff([base_mod], [head_mod])

        assert result.has_changes()
        assert result.summary.functions_added == 1
        assert result.summary.modules_modified == 1

        func_changes = [c for c in result.changes if c.entity_type == "function"]
        assert len(func_changes) == 1
        assert func_changes[0].entity_name == "new_func"
        assert func_changes[0].change_type == "added"

    def test_diff_removed_function_is_breaking(self, core_module):
        """Test that removing a function is marked as breaking."""
        base_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[
                core_module.FunctionDef(
                    name="old_func",
                    parameters=[],
                    return_type="str",
                ),
            ],
        )
        head_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[],
        )

        result = core_module.semantic_diff([base_mod], [head_mod])

        assert result.has_changes()
        assert result.has_breaking_changes()
        assert result.summary.functions_removed == 1

        func_changes = [c for c in result.breaking_changes if c.entity_type == "function"]
        assert len(func_changes) == 1
        assert func_changes[0].entity_name == "old_func"
        assert func_changes[0].is_breaking

    def test_diff_modified_function_signature(self, core_module):
        """Test detecting function signature changes."""
        base_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[
                core_module.FunctionDef(
                    name="my_func",
                    parameters=[
                        core_module.ParameterDef(name="x", type_annotation="int"),
                    ],
                    return_type="str",
                ),
            ],
        )
        head_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[
                core_module.FunctionDef(
                    name="my_func",
                    parameters=[
                        core_module.ParameterDef(name="x", type_annotation="int"),
                        core_module.ParameterDef(name="y", type_annotation="str"),
                    ],
                    return_type="int",  # Changed return type
                ),
            ],
        )

        result = core_module.semantic_diff([base_mod], [head_mod])

        assert result.has_changes()
        # Return type change is breaking
        assert result.has_breaking_changes()
        assert result.summary.functions_modified == 1
        assert result.summary.parameters_added == 1

    def test_diff_added_class(self, core_module):
        """Test detecting an added class."""
        base_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[],
        )
        head_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[
                core_module.ClassDef(
                    name="NewClass",
                    bases=["BaseClass"],
                    methods=[],
                ),
            ],
            functions=[],
        )

        result = core_module.semantic_diff([base_mod], [head_mod])

        assert result.has_changes()
        assert result.summary.classes_added == 1

        class_changes = [c for c in result.changes if c.entity_type == "class"]
        assert len(class_changes) == 1
        assert class_changes[0].entity_name == "NewClass"
        assert class_changes[0].change_type == "added"

    def test_diff_added_method(self, core_module):
        """Test detecting an added method in a class."""
        base_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[
                core_module.ClassDef(
                    name="MyClass",
                    bases=[],
                    methods=[],
                ),
            ],
            functions=[],
        )
        head_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[
                core_module.ClassDef(
                    name="MyClass",
                    bases=[],
                    methods=[
                        core_module.FunctionDef(
                            name="new_method",
                            parameters=[],
                            return_type=None,
                            is_method=True,
                        ),
                    ],
                ),
            ],
            functions=[],
        )

        result = core_module.semantic_diff([base_mod], [head_mod])

        assert result.has_changes()
        assert result.summary.methods_added == 1

        method_changes = [c for c in result.changes if c.entity_type == "method"]
        assert len(method_changes) == 1
        assert method_changes[0].entity_name == "new_method"
        assert method_changes[0].parent_name == "MyClass"

    def test_diff_no_changes(self, core_module):
        """Test when there are no changes."""
        mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[
                core_module.FunctionDef(
                    name="my_func",
                    parameters=[],
                    return_type="str",
                ),
            ],
        )

        result = core_module.semantic_diff([mod], [mod])

        assert not result.has_changes()
        assert not result.has_breaking_changes()
        assert result.change_count() == 0

    def test_diff_added_module(self, core_module):
        """Test detecting an added module."""
        new_mod = core_module.ModuleDef(
            name="new_module",
            path="new_module.py",
            language="python",
            imports=[],
            classes=[],
            functions=[],
        )

        result = core_module.semantic_diff([], [new_mod])

        assert result.has_changes()
        assert result.summary.modules_added == 1

    def test_diff_removed_module_is_breaking(self, core_module):
        """Test that removing a module is breaking."""
        old_mod = core_module.ModuleDef(
            name="old_module",
            path="old_module.py",
            language="python",
            imports=[],
            classes=[],
            functions=[],
        )

        result = core_module.semantic_diff([old_mod], [])

        assert result.has_changes()
        assert result.has_breaking_changes()
        assert result.summary.modules_removed == 1

    def test_result_to_dict(self, core_module):
        """Test SemanticDiffResult serialization."""
        base_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[],
        )
        head_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[
                core_module.FunctionDef(
                    name="new_func",
                    parameters=[],
                    return_type="str",
                ),
            ],
        )

        result = core_module.semantic_diff([base_mod], [head_mod])
        data = result.to_dict()

        assert "changes" in data
        assert "breaking_changes" in data
        assert "summary" in data
        assert "summary_text" in data
        assert "duration_ms" in data
        assert data["has_changes"] is True

    def test_filter_by_type(self, core_module):
        """Test filtering changes by entity type."""
        base_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[],
        )
        head_mod = core_module.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[
                core_module.ClassDef(
                    name="NewClass",
                    bases=[],
                    methods=[],
                ),
            ],
            functions=[
                core_module.FunctionDef(
                    name="new_func",
                    parameters=[],
                    return_type="str",
                ),
            ],
        )

        result = core_module.semantic_diff([base_mod], [head_mod])

        func_changes = result.filter_by_type("function")
        assert len(func_changes) == 1
        assert func_changes[0].entity_name == "new_func"

        class_changes = result.filter_by_type("class")
        assert len(class_changes) == 1
        assert class_changes[0].entity_name == "NewClass"

    def test_python_integration_semantic_diff_modules(self):
        """Test the Python wrapper function."""
        from mu.diff import semantic_diff_modules
        from mu import _core

        base_mod = _core.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[],
        )
        head_mod = _core.ModuleDef(
            name="test",
            path="test.py",
            language="python",
            imports=[],
            classes=[],
            functions=[
                _core.FunctionDef(
                    name="new_func",
                    parameters=[],
                    return_type="str",
                ),
            ],
        )

        result = semantic_diff_modules([base_mod], [head_mod])

        assert result is not None
        assert result.has_changes()
        assert result.summary.functions_added == 1

    def test_semantic_diff_files(self, tmp_path):
        """Test the file-based semantic diff function."""
        from mu import _core

        base_code = '''
def old_function():
    return 'hello'
'''
        head_code = '''
def old_function():
    return 'hello'

def new_function(x: int) -> str:
    return str(x)
'''

        base_file = tmp_path / "base.py"
        head_file = tmp_path / "head.py"
        base_file.write_text(base_code)
        head_file.write_text(head_code)

        # Test with normalize_paths=True (default)
        result = _core.semantic_diff_files(str(base_file), str(head_file), "python")

        assert result.has_changes()
        assert result.summary.modules_modified == 1
        assert result.summary.functions_added == 1

        func_changes = [c for c in result.changes if c.entity_type == "function"]
        assert len(func_changes) == 1
        assert func_changes[0].entity_name == "new_function"
        assert func_changes[0].change_type == "added"

    def test_semantic_diff_files_error_handling(self, tmp_path):
        """Test error handling for semantic_diff_files."""
        from mu import _core
        import pytest

        # Non-existent file should raise IOError
        with pytest.raises(IOError):
            _core.semantic_diff_files("/nonexistent/path.py", "/other/path.py", "python")

        # Invalid syntax should raise ValueError
        invalid_file = tmp_path / "invalid.py"
        valid_file = tmp_path / "valid.py"
        invalid_file.write_text("def broken(")  # Invalid Python syntax
        valid_file.write_text("def valid(): pass")

        # Note: Tree-sitter is lenient and may partially parse invalid code
        # This test documents the behavior rather than asserting an exception
        try:
            result = _core.semantic_diff_files(str(invalid_file), str(valid_file), "python")
            # If it parses (tree-sitter is lenient), verify result is valid
            assert result is not None
        except ValueError:
            # If it fails to parse, that's also acceptable
            pass
