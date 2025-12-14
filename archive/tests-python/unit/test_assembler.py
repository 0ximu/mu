"""Tests for the assembler module."""

from pathlib import Path

import pytest

from mu.assembler import (
    Assembler,
    AssembledOutput,
    DependencyType,
    ImportResolver,
    ModuleGraph,
    ModuleNode,
    PYTHON_STDLIB,
    ResolvedImport,
    assemble,
)
from mu.parser.models import ClassDef, FunctionDef, ImportDef, ModuleDef
from mu.reducer.generator import ReducedCodebase, ReducedModule, reduce_codebase


class TestDependencyType:
    """Tests for DependencyType enum."""

    def test_dependency_types(self):
        """Test that all dependency types exist."""
        assert DependencyType.INTERNAL.value == "internal"
        assert DependencyType.EXTERNAL.value == "external"
        assert DependencyType.STDLIB.value == "stdlib"


class TestModuleNode:
    """Tests for ModuleNode dataclass."""

    def test_module_node_creation(self):
        """Test creating a module node."""
        node = ModuleNode(
            name="test_module",
            path="src/test_module.py",
            language="python",
            internal_deps=["other_module"],
            external_deps=["requests"],
            stdlib_deps=["os", "sys"],
            exports=["MyClass", "my_function"],
        )

        assert node.name == "test_module"
        assert node.path == "src/test_module.py"
        assert node.language == "python"
        assert node.internal_deps == ["other_module"]
        assert node.external_deps == ["requests"]
        assert node.stdlib_deps == ["os", "sys"]
        assert node.exports == ["MyClass", "my_function"]

    def test_module_node_to_dict(self):
        """Test module node serialization."""
        node = ModuleNode(
            name="test",
            path="test.py",
            language="python",
        )
        d = node.to_dict()

        assert d["name"] == "test"
        assert d["path"] == "test.py"
        assert d["language"] == "python"
        assert d["internal_deps"] == []
        assert d["external_deps"] == []


class TestModuleGraph:
    """Tests for ModuleGraph."""

    def test_graph_creation(self):
        """Test creating an empty graph."""
        graph = ModuleGraph()
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_add_node(self):
        """Test adding a node to the graph."""
        graph = ModuleGraph()
        node = ModuleNode(name="test", path="test.py", language="python")
        graph.add_node(node)

        assert "test.py" in graph.nodes
        assert graph.nodes["test.py"] == node

    def test_add_edge(self):
        """Test adding an edge to the graph."""
        graph = ModuleGraph()
        graph.add_edge("a.py", "b.py", DependencyType.INTERNAL)

        assert len(graph.edges) == 1
        assert graph.edges[0] == ("a.py", "b.py", DependencyType.INTERNAL)

    def test_get_internal_graph(self):
        """Test getting internal dependency graph."""
        graph = ModuleGraph()
        graph.add_edge("a.py", "b.py", DependencyType.INTERNAL)
        graph.add_edge("a.py", "c.py", DependencyType.INTERNAL)
        graph.add_edge("b.py", "c.py", DependencyType.INTERNAL)
        graph.add_edge("a.py", "external", DependencyType.EXTERNAL)

        internal = graph.get_internal_graph()
        assert "a.py" in internal
        assert set(internal["a.py"]) == {"b.py", "c.py"}
        assert "b.py" in internal
        assert internal["b.py"] == ["c.py"]

    def test_get_external_packages(self):
        """Test getting external packages."""
        graph = ModuleGraph()
        node1 = ModuleNode(
            name="a", path="a.py", language="python",
            external_deps=["requests", "flask"],
        )
        node2 = ModuleNode(
            name="b", path="b.py", language="python",
            external_deps=["requests", "click"],
        )
        graph.add_node(node1)
        graph.add_node(node2)

        packages = graph.get_external_packages()
        assert packages == {"requests", "flask", "click"}


class TestPythonStdlib:
    """Tests for Python stdlib detection."""

    def test_common_stdlib_modules(self):
        """Test that common stdlib modules are recognized."""
        assert "os" in PYTHON_STDLIB
        assert "sys" in PYTHON_STDLIB
        assert "json" in PYTHON_STDLIB
        assert "pathlib" in PYTHON_STDLIB
        assert "typing" in PYTHON_STDLIB
        assert "asyncio" in PYTHON_STDLIB
        assert "dataclasses" in PYTHON_STDLIB
        assert "__future__" in PYTHON_STDLIB

    def test_external_packages_not_in_stdlib(self):
        """Test that known external packages are not in stdlib."""
        assert "requests" not in PYTHON_STDLIB
        assert "flask" not in PYTHON_STDLIB
        assert "click" not in PYTHON_STDLIB
        assert "pydantic" not in PYTHON_STDLIB


class TestImportResolver:
    """Tests for ImportResolver."""

    def _make_module(
        self, name: str, path: str, language: str = "python"
    ) -> ModuleDef:
        """Helper to create a module def."""
        return ModuleDef(name=name, path=path, language=language)

    def test_resolver_creation(self):
        """Test creating a resolver."""
        modules = [
            self._make_module("foo", "src/foo.py"),
            self._make_module("bar", "src/bar.py"),
        ]
        resolver = ImportResolver(modules, Path("/project"))

        assert len(resolver.modules) == 2

    def test_resolve_stdlib_import(self):
        """Test resolving stdlib imports."""
        modules = [self._make_module("main", "src/main.py")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="os", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.STDLIB

    def test_resolve_stdlib_submodule(self):
        """Test resolving stdlib submodule imports."""
        modules = [self._make_module("main", "src/main.py")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="os.path", is_from=True, names=["join"])
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.STDLIB

    def test_resolve_external_import(self):
        """Test resolving external package imports."""
        modules = [self._make_module("main", "src/main.py")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="requests", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.EXTERNAL

    def test_resolve_internal_import_by_name(self):
        """Test resolving internal imports by module name."""
        modules = [
            self._make_module("main", "src/main.py"),
            self._make_module("utils", "src/utils.py"),
        ]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="utils", is_from=True, names=["helper"])
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.INTERNAL
        assert result.resolved_path == "src/utils.py"

    def test_resolve_internal_import_by_path(self):
        """Test resolving internal imports by path pattern."""
        modules = [
            self._make_module("main", "src/main.py"),
            self._make_module("models", "src/myapp/models.py"),
        ]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="myapp.models", is_from=True, names=["User"])
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.INTERNAL
        assert result.resolved_path == "src/myapp/models.py"


class TestImportResolverRelative:
    """Tests for relative import resolution."""

    def _make_module(self, name: str, path: str) -> ModuleDef:
        return ModuleDef(name=name, path=path, language="python")

    def test_resolve_relative_import_same_package(self):
        """Test resolving relative imports in same package."""
        modules = [
            self._make_module("models", "src/myapp/models.py"),
            self._make_module("utils", "src/myapp/utils.py"),
        ]
        resolver = ImportResolver(modules, Path("/project"))

        # from .utils import helper (from models.py)
        imp = ImportDef(module=".utils", is_from=True, names=["helper"])
        from_module = modules[0]  # models.py

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.INTERNAL


class TestImportResolverTypeScript:
    """Tests for TypeScript import resolution."""

    def _make_module(self, name: str, path: str) -> ModuleDef:
        return ModuleDef(name=name, path=path, language="typescript")

    def test_resolve_relative_ts_import(self):
        """Test resolving relative TypeScript imports."""
        modules = [
            self._make_module("index", "src/index.ts"),
            self._make_module("utils", "src/utils.ts"),
        ]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="./utils", is_from=True, names=["helper"])
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.INTERNAL
        assert result.resolved_path == "src/utils.ts"

    def test_resolve_node_builtin(self):
        """Test resolving Node.js built-in modules."""
        modules = [self._make_module("server", "src/server.ts")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="fs", is_from=True, names=["readFile"])
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.STDLIB

    def test_resolve_npm_package(self):
        """Test resolving NPM packages."""
        modules = [self._make_module("app", "src/app.ts")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="express", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.EXTERNAL


class TestImportResolverCSharp:
    """Tests for C# import resolution."""

    def _make_module(self, name: str, path: str) -> ModuleDef:
        return ModuleDef(name=name, path=path, language="csharp")

    def test_resolve_system_namespace(self):
        """Test resolving System namespace."""
        modules = [self._make_module("Program", "src/Program.cs")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="System.Collections.Generic", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.STDLIB

    def test_resolve_microsoft_namespace(self):
        """Test resolving Microsoft namespace."""
        modules = [self._make_module("Startup", "src/Startup.cs")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="Microsoft.AspNetCore.Mvc", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.STDLIB

    def test_resolve_nuget_package(self):
        """Test resolving NuGet packages."""
        modules = [self._make_module("Service", "src/Service.cs")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="Newtonsoft.Json", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.EXTERNAL


class TestImportResolverGo:
    """Tests for Go import resolution."""

    def _make_module(self, name: str, path: str) -> ModuleDef:
        return ModuleDef(name=name, path=path, language="go")

    def test_resolve_stdlib_import(self):
        """Test resolving Go standard library imports."""
        modules = [self._make_module("main", "cmd/main.go")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="fmt", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.STDLIB

    def test_resolve_stdlib_subpackage(self):
        """Test resolving Go stdlib subpackage."""
        modules = [self._make_module("main", "cmd/main.go")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="net/http", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.STDLIB

    def test_resolve_external_package(self):
        """Test resolving external Go packages."""
        modules = [self._make_module("main", "cmd/main.go")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="github.com/pkg/errors", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.EXTERNAL

    def test_resolve_external_nested_package(self):
        """Test resolving nested external packages."""
        modules = [self._make_module("main", "cmd/main.go")]
        resolver = ImportResolver(modules, Path("/project"))

        imp = ImportDef(module="github.com/spf13/cobra/doc", is_from=False)
        from_module = modules[0]

        result = resolver.resolve(imp, from_module)
        assert result.dep_type == DependencyType.EXTERNAL


class TestAssembler:
    """Tests for Assembler class."""

    def _make_module(
        self,
        name: str,
        path: str,
        imports: list[ImportDef] | None = None,
        classes: list[ClassDef] | None = None,
        functions: list[FunctionDef] | None = None,
    ) -> ModuleDef:
        return ModuleDef(
            name=name,
            path=path,
            language="python",
            imports=imports or [],
            classes=classes or [],
            functions=functions or [],
        )

    def test_assembler_creation(self):
        """Test creating an assembler."""
        modules = [self._make_module("main", "src/main.py")]
        assembler = Assembler(modules, Path("/project"))

        assert assembler.graph is None

    def test_build_graph(self):
        """Test building module graph."""
        modules = [
            self._make_module("main", "src/main.py", imports=[
                ImportDef(module="utils", is_from=True, names=["helper"]),
                ImportDef(module="os", is_from=False),
            ]),
            self._make_module("utils", "src/utils.py"),
        ]
        assembler = Assembler(modules, Path("/project"))
        graph = assembler.build_graph()

        assert len(graph.nodes) == 2
        assert "src/main.py" in graph.nodes
        assert "src/utils.py" in graph.nodes

        # Check that main depends on utils
        main_node = graph.nodes["src/main.py"]
        assert "src/utils.py" in main_node.internal_deps
        assert "os" in main_node.stdlib_deps

    def test_build_graph_with_exports(self):
        """Test that graph captures exports."""
        modules = [
            self._make_module(
                "mymodule",
                "src/mymodule.py",
                classes=[ClassDef(name="MyClass")],
                functions=[FunctionDef(name="my_function")],
            ),
        ]
        assembler = Assembler(modules, Path("/project"))
        graph = assembler.build_graph()

        node = graph.nodes["src/mymodule.py"]
        assert "MyClass" in node.exports
        assert "my_function" in node.exports

    def test_topological_order(self):
        """Test topological ordering of modules."""
        modules = [
            self._make_module("a", "a.py", imports=[
                ImportDef(module="b", is_from=True, names=["foo"]),
            ]),
            self._make_module("b", "b.py", imports=[
                ImportDef(module="c", is_from=True, names=["bar"]),
            ]),
            self._make_module("c", "c.py"),
        ]
        assembler = Assembler(modules, Path("/project"))
        order = assembler.get_topological_order()

        # c should come before b, b before a
        assert order.index("c.py") < order.index("b.py")
        assert order.index("b.py") < order.index("a.py")

    def test_enhance_reduced_codebase(self):
        """Test enhancing reduced codebase with resolved deps."""
        modules = [
            self._make_module("main", "src/main.py", imports=[
                ImportDef(module="utils", is_from=True, names=["helper"]),
                ImportDef(module="requests", is_from=False),
            ]),
            self._make_module("utils", "src/utils.py"),
        ]
        assembler = Assembler(modules, Path("/project"))

        # Create a reduced codebase
        reduced = ReducedCodebase(source="/project")
        reduced.modules = [
            ReducedModule(name="main", path="src/main.py", language="python"),
            ReducedModule(name="utils", path="src/utils.py", language="python"),
        ]

        enhanced = assembler.enhance_reduced_codebase(reduced)

        # Check that dependency graph was updated
        assert "main" in enhanced.dependency_graph
        assert "utils" in enhanced.dependency_graph["main"]

        # Check that external packages were set
        assert "requests" in enhanced.external_packages


class TestAssemble:
    """Tests for assemble() convenience function."""

    def test_assemble_basic(self):
        """Test basic assembly."""
        modules = [
            ModuleDef(
                name="main",
                path="src/main.py",
                language="python",
                imports=[ImportDef(module="utils", is_from=True, names=["foo"])],
            ),
            ModuleDef(
                name="utils",
                path="src/utils.py",
                language="python",
            ),
        ]

        reduced = ReducedCodebase(source="/project")
        reduced.modules = [
            ReducedModule(name="main", path="src/main.py", language="python"),
            ReducedModule(name="utils", path="src/utils.py", language="python"),
        ]
        reduced.stats = {"total_modules": 2}

        result = assemble(modules, reduced, Path("/project"))

        assert isinstance(result, AssembledOutput)
        assert result.codebase is reduced
        assert result.graph is not None
        assert len(result.topological_order) == 2
        assert isinstance(result.external_packages, set)

    def test_assemble_to_dict(self):
        """Test AssembledOutput serialization."""
        modules = [
            ModuleDef(
                name="app",
                path="app.py",
                language="python",
            ),
        ]

        reduced = ReducedCodebase(source="/project")
        reduced.modules = [
            ReducedModule(name="app", path="app.py", language="python"),
        ]
        reduced.stats = {"total_modules": 1}

        result = assemble(modules, reduced, Path("/project"))
        d = result.to_dict()

        assert "source" in d
        assert "stats" in d
        assert "module_graph" in d
        assert "topological_order" in d
        assert "external_packages" in d
        assert "modules" in d
