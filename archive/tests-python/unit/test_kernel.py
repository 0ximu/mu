"""Tests for MU Kernel - graph database storage."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mu.kernel import Edge, EdgeType, GraphBuilder, MUbase, Node, NodeType
from mu.parser.models import ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef


class TestSchema:
    """Tests for schema definitions."""

    def test_node_types_defined(self) -> None:
        """All expected node types exist."""
        assert NodeType.MODULE.value == "module"
        assert NodeType.CLASS.value == "class"
        assert NodeType.FUNCTION.value == "function"
        assert NodeType.EXTERNAL.value == "external"

    def test_edge_types_defined(self) -> None:
        """All expected edge types exist."""
        assert EdgeType.CONTAINS.value == "contains"
        assert EdgeType.IMPORTS.value == "imports"
        assert EdgeType.INHERITS.value == "inherits"


class TestNodeModel:
    """Tests for Node dataclass."""

    def test_node_creation(self) -> None:
        """Node can be created with required fields."""
        node = Node(
            id="mod:test.py",
            type=NodeType.MODULE,
            name="test",
        )
        assert node.id == "mod:test.py"
        assert node.type == NodeType.MODULE
        assert node.name == "test"
        assert node.complexity == 0

    def test_node_to_tuple(self) -> None:
        """Node converts to tuple correctly."""
        node = Node(
            id="fn:test.py:foo",
            type=NodeType.FUNCTION,
            name="foo",
            qualified_name="test.foo",
            file_path="test.py",
            line_start=10,
            line_end=20,
            properties={"is_async": True},
            complexity=15,
        )
        t = node.to_tuple()
        assert t[0] == "fn:test.py:foo"
        assert t[1] == "function"
        assert t[2] == "foo"
        assert t[3] == "test.foo"
        assert t[4] == "test.py"
        assert t[5] == 10
        assert t[6] == 20
        assert '"is_async": true' in t[7].lower()
        assert t[8] == 15

    def test_node_to_dict(self) -> None:
        """Node converts to dict correctly."""
        node = Node(
            id="cls:test.py:MyClass",
            type=NodeType.CLASS,
            name="MyClass",
            file_path="test.py",
        )
        d = node.to_dict()
        assert d["id"] == "cls:test.py:MyClass"
        assert d["type"] == "class"
        assert d["name"] == "MyClass"

    def test_node_from_row(self) -> None:
        """Node can be reconstructed from tuple row."""
        row = (
            "mod:test.py",
            "module",
            "test",
            "test",
            "test.py",
            1,
            100,
            '{"language": "python"}',
            0,
        )
        node = Node.from_row(row)
        assert node.id == "mod:test.py"
        assert node.type == NodeType.MODULE
        assert node.properties["language"] == "python"


class TestEdgeModel:
    """Tests for Edge dataclass."""

    def test_edge_creation(self) -> None:
        """Edge can be created with required fields."""
        edge = Edge(
            id="edge:a:contains:b",
            source_id="a",
            target_id="b",
            type=EdgeType.CONTAINS,
        )
        assert edge.source_id == "a"
        assert edge.target_id == "b"
        assert edge.type == EdgeType.CONTAINS

    def test_edge_to_tuple(self) -> None:
        """Edge converts to tuple correctly."""
        edge = Edge(
            id="edge:a:imports:b",
            source_id="a",
            target_id="b",
            type=EdgeType.IMPORTS,
            properties={"names": ["foo", "bar"]},
        )
        t = edge.to_tuple()
        assert t[0] == "edge:a:imports:b"
        assert t[1] == "a"
        assert t[2] == "b"
        assert t[3] == "imports"

    def test_edge_from_row(self) -> None:
        """Edge can be reconstructed from tuple row."""
        row = (
            "edge:x:inherits:y",
            "x",
            "y",
            "inherits",
            '{"base_name": "BaseClass"}',
        )
        edge = Edge.from_row(row)
        assert edge.id == "edge:x:inherits:y"
        assert edge.type == EdgeType.INHERITS
        assert edge.properties["base_name"] == "BaseClass"


class TestGraphBuilder:
    """Tests for GraphBuilder."""

    @pytest.fixture
    def simple_module(self) -> ModuleDef:
        """Create a simple module for testing."""
        return ModuleDef(
            name="mymodule",
            path="src/mymodule.py",
            language="python",
            imports=[
                ImportDef(module="os", is_from=False),
                ImportDef(module="json", names=["loads", "dumps"], is_from=True),
            ],
            classes=[
                ClassDef(
                    name="MyClass",
                    bases=["BaseClass"],
                    methods=[
                        FunctionDef(
                            name="__init__",
                            parameters=[ParameterDef(name="self")],
                            is_method=True,
                            body_complexity=5,
                            start_line=10,
                            end_line=15,
                        ),
                        FunctionDef(
                            name="process",
                            parameters=[
                                ParameterDef(name="self"),
                                ParameterDef(name="data", type_annotation="str"),
                            ],
                            return_type="dict",
                            is_method=True,
                            is_async=True,
                            body_complexity=25,
                            start_line=17,
                            end_line=40,
                        ),
                    ],
                    start_line=5,
                    end_line=50,
                ),
            ],
            functions=[
                FunctionDef(
                    name="helper",
                    parameters=[ParameterDef(name="x", type_annotation="int")],
                    return_type="int",
                    body_complexity=3,
                    start_line=55,
                    end_line=57,
                ),
            ],
            total_lines=60,
        )

    def test_creates_module_node(self, simple_module: ModuleDef) -> None:
        """GraphBuilder creates MODULE node for each module."""
        nodes, edges = GraphBuilder.from_module_defs([simple_module], Path("."))

        module_nodes = [n for n in nodes if n.type == NodeType.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].name == "mymodule"
        assert module_nodes[0].file_path == "src/mymodule.py"

    def test_creates_class_node(self, simple_module: ModuleDef) -> None:
        """GraphBuilder creates CLASS node for each class."""
        nodes, edges = GraphBuilder.from_module_defs([simple_module], Path("."))

        class_nodes = [n for n in nodes if n.type == NodeType.CLASS]
        assert len(class_nodes) == 1
        assert class_nodes[0].name == "MyClass"
        assert "BaseClass" in class_nodes[0].properties["bases"]

    def test_creates_function_nodes(self, simple_module: ModuleDef) -> None:
        """GraphBuilder creates FUNCTION nodes for functions and methods."""
        nodes, edges = GraphBuilder.from_module_defs([simple_module], Path("."))

        func_nodes = [n for n in nodes if n.type == NodeType.FUNCTION]
        assert len(func_nodes) == 3  # __init__, process, helper

        # Check method
        process_node = next(n for n in func_nodes if n.name == "process")
        assert process_node.complexity == 25
        assert process_node.properties["is_async"] is True

        # Check module-level function
        helper_node = next(n for n in func_nodes if n.name == "helper")
        assert helper_node.complexity == 3

    def test_creates_contains_edges(self, simple_module: ModuleDef) -> None:
        """GraphBuilder creates CONTAINS edges for containment hierarchy."""
        nodes, edges = GraphBuilder.from_module_defs([simple_module], Path("."))

        contains_edges = [e for e in edges if e.type == EdgeType.CONTAINS]

        # Module contains Class
        mod_to_class = [e for e in contains_edges if "cls:" in e.target_id and "mod:" in e.source_id]
        assert len(mod_to_class) == 1

        # Module contains helper function
        mod_to_func = [e for e in contains_edges if e.target_id.endswith(":helper")]
        assert len(mod_to_func) == 1

        # Class contains methods
        class_to_methods = [e for e in contains_edges if "cls:" in e.source_id and "fn:" in e.target_id]
        assert len(class_to_methods) == 2

    def test_creates_inherits_edges(self, simple_module: ModuleDef) -> None:
        """GraphBuilder creates INHERITS edges for class inheritance."""
        nodes, edges = GraphBuilder.from_module_defs([simple_module], Path("."))

        inherits_edges = [e for e in edges if e.type == EdgeType.INHERITS]
        assert len(inherits_edges) == 1
        assert inherits_edges[0].properties["base_name"] == "BaseClass"

    def test_qualified_names(self, simple_module: ModuleDef) -> None:
        """GraphBuilder sets qualified names correctly."""
        nodes, edges = GraphBuilder.from_module_defs([simple_module], Path("."))

        class_node = next(n for n in nodes if n.type == NodeType.CLASS)
        assert class_node.qualified_name == "mymodule.MyClass"

        process_node = next(n for n in nodes if n.name == "process")
        assert process_node.qualified_name == "mymodule.MyClass.process"

        helper_node = next(n for n in nodes if n.name == "helper")
        assert helper_node.qualified_name == "mymodule.helper"


class TestMUbase:
    """Tests for MUbase database."""

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        """Create temporary database path."""
        return tmp_path / "test.mubase"

    @pytest.fixture
    def db(self, db_path: Path) -> MUbase:
        """Create database instance."""
        return MUbase(db_path)

    def test_init_creates_schema(self, db: MUbase) -> None:
        """MUbase creates tables on init."""
        stats = db.stats()
        assert stats["version"] == MUbase.VERSION
        assert stats["nodes"] == 0
        assert stats["edges"] == 0
        db.close()

    def test_add_and_get_node(self, db: MUbase) -> None:
        """Nodes can be added and retrieved."""
        node = Node(
            id="test:node",
            type=NodeType.FUNCTION,
            name="test_func",
            complexity=10,
        )
        db.add_node(node)

        retrieved = db.get_node("test:node")
        assert retrieved is not None
        assert retrieved.name == "test_func"
        assert retrieved.type == NodeType.FUNCTION
        assert retrieved.complexity == 10
        db.close()

    def test_add_and_get_edge(self, db: MUbase) -> None:
        """Edges can be added and retrieved."""
        db.add_node(Node(id="a", type=NodeType.MODULE, name="a"))
        db.add_node(Node(id="b", type=NodeType.MODULE, name="b"))

        edge = Edge(
            id="edge:a:imports:b",
            source_id="a",
            target_id="b",
            type=EdgeType.IMPORTS,
        )
        db.add_edge(edge)

        edges = db.get_edges(source_id="a")
        assert len(edges) == 1
        assert edges[0].target_id == "b"
        assert edges[0].type == EdgeType.IMPORTS
        db.close()

    def test_get_nodes_by_type(self, db: MUbase) -> None:
        """Nodes can be filtered by type."""
        db.add_node(Node(id="m1", type=NodeType.MODULE, name="mod1"))
        db.add_node(Node(id="c1", type=NodeType.CLASS, name="class1"))
        db.add_node(Node(id="f1", type=NodeType.FUNCTION, name="func1"))

        modules = db.get_nodes(NodeType.MODULE)
        assert len(modules) == 1
        assert modules[0].name == "mod1"

        functions = db.get_nodes(NodeType.FUNCTION)
        assert len(functions) == 1
        assert functions[0].name == "func1"
        db.close()

    def test_get_dependencies_depth_1(self, db: MUbase) -> None:
        """get_dependencies returns direct dependencies."""
        # Create nodes: A -> B -> C
        db.add_node(Node(id="A", type=NodeType.MODULE, name="A"))
        db.add_node(Node(id="B", type=NodeType.MODULE, name="B"))
        db.add_node(Node(id="C", type=NodeType.MODULE, name="C"))

        db.add_edge(Edge(id="e1", source_id="A", target_id="B", type=EdgeType.IMPORTS))
        db.add_edge(Edge(id="e2", source_id="B", target_id="C", type=EdgeType.IMPORTS))

        deps = db.get_dependencies("A", depth=1)
        assert len(deps) == 1
        assert deps[0].id == "B"
        db.close()

    def test_get_dependencies_depth_n(self, db: MUbase) -> None:
        """get_dependencies traverses multiple levels."""
        # Create nodes: A -> B -> C -> D
        for name in ["A", "B", "C", "D"]:
            db.add_node(Node(id=name, type=NodeType.MODULE, name=name))

        db.add_edge(Edge(id="e1", source_id="A", target_id="B", type=EdgeType.IMPORTS))
        db.add_edge(Edge(id="e2", source_id="B", target_id="C", type=EdgeType.IMPORTS))
        db.add_edge(Edge(id="e3", source_id="C", target_id="D", type=EdgeType.IMPORTS))

        deps = db.get_dependencies("A", depth=3)
        assert len(deps) == 3
        dep_ids = {d.id for d in deps}
        assert dep_ids == {"B", "C", "D"}
        db.close()

    def test_get_dependents(self, db: MUbase) -> None:
        """get_dependents returns nodes that depend on target."""
        # Create: A -> C, B -> C
        for name in ["A", "B", "C"]:
            db.add_node(Node(id=name, type=NodeType.MODULE, name=name))

        db.add_edge(Edge(id="e1", source_id="A", target_id="C", type=EdgeType.IMPORTS))
        db.add_edge(Edge(id="e2", source_id="B", target_id="C", type=EdgeType.IMPORTS))

        dependents = db.get_dependents("C", depth=1)
        assert len(dependents) == 2
        dep_ids = {d.id for d in dependents}
        assert dep_ids == {"A", "B"}
        db.close()

    def test_find_by_complexity(self, db: MUbase) -> None:
        """find_by_complexity returns functions above threshold."""
        db.add_node(Node(id="f1", type=NodeType.FUNCTION, name="simple", complexity=5))
        db.add_node(Node(id="f2", type=NodeType.FUNCTION, name="medium", complexity=15))
        db.add_node(Node(id="f3", type=NodeType.FUNCTION, name="complex", complexity=50))

        complex_funcs = db.find_by_complexity(20)
        assert len(complex_funcs) == 1
        assert complex_funcs[0].name == "complex"

        medium_funcs = db.find_by_complexity(10)
        assert len(medium_funcs) == 2
        db.close()

    def test_find_by_name(self, db: MUbase) -> None:
        """find_by_name supports exact and pattern matching."""
        db.add_node(Node(id="f1", type=NodeType.FUNCTION, name="test_something"))
        db.add_node(Node(id="f2", type=NodeType.FUNCTION, name="test_another"))
        db.add_node(Node(id="f3", type=NodeType.FUNCTION, name="helper"))

        # Exact match
        exact = db.find_by_name("helper")
        assert len(exact) == 1

        # Pattern match
        tests = db.find_by_name("test_%")
        assert len(tests) == 2
        db.close()

    def test_get_children(self, db: MUbase) -> None:
        """get_children returns nodes via CONTAINS edges."""
        db.add_node(Node(id="mod", type=NodeType.MODULE, name="mod"))
        db.add_node(Node(id="cls", type=NodeType.CLASS, name="cls"))
        db.add_node(Node(id="fn", type=NodeType.FUNCTION, name="fn"))

        db.add_edge(Edge(id="e1", source_id="mod", target_id="cls", type=EdgeType.CONTAINS))
        db.add_edge(Edge(id="e2", source_id="cls", target_id="fn", type=EdgeType.CONTAINS))

        mod_children = db.get_children("mod")
        assert len(mod_children) == 1
        assert mod_children[0].id == "cls"

        cls_children = db.get_children("cls")
        assert len(cls_children) == 1
        assert cls_children[0].id == "fn"
        db.close()

    def test_get_parent(self, db: MUbase) -> None:
        """get_parent returns containing node."""
        db.add_node(Node(id="mod", type=NodeType.MODULE, name="mod"))
        db.add_node(Node(id="fn", type=NodeType.FUNCTION, name="fn"))

        db.add_edge(Edge(id="e1", source_id="mod", target_id="fn", type=EdgeType.CONTAINS))

        parent = db.get_parent("fn")
        assert parent is not None
        assert parent.id == "mod"
        db.close()

    def test_stats(self, db: MUbase) -> None:
        """stats returns correct counts."""
        db.add_node(Node(id="m1", type=NodeType.MODULE, name="m1"))
        db.add_node(Node(id="c1", type=NodeType.CLASS, name="c1"))
        db.add_node(Node(id="f1", type=NodeType.FUNCTION, name="f1"))
        db.add_node(Node(id="f2", type=NodeType.FUNCTION, name="f2"))

        db.add_edge(Edge(id="e1", source_id="m1", target_id="c1", type=EdgeType.CONTAINS))
        db.add_edge(Edge(id="e2", source_id="c1", target_id="f1", type=EdgeType.CONTAINS))

        stats = db.stats()
        assert stats["nodes"] == 4
        assert stats["edges"] == 2
        assert stats["nodes_by_type"]["module"] == 1
        assert stats["nodes_by_type"]["class"] == 1
        assert stats["nodes_by_type"]["function"] == 2
        assert stats["edges_by_type"]["contains"] == 2
        db.close()

    def test_context_manager(self, tmp_path: Path) -> None:
        """MUbase works as context manager."""
        db_path = tmp_path / "ctx.mubase"
        with MUbase(db_path) as db:
            db.add_node(Node(id="test", type=NodeType.MODULE, name="test"))
            stats = db.stats()
            assert stats["nodes"] == 1


class TestBuildIntegration:
    """Integration tests for build workflow."""

    @pytest.fixture
    def modules(self) -> list[ModuleDef]:
        """Create test modules with dependencies."""
        return [
            ModuleDef(
                name="main",
                path="src/main.py",
                language="python",
                imports=[
                    ImportDef(module="utils", is_from=False),
                ],
                functions=[
                    FunctionDef(name="run", body_complexity=10),
                ],
                total_lines=20,
            ),
            ModuleDef(
                name="utils",
                path="src/utils.py",
                language="python",
                imports=[],
                functions=[
                    FunctionDef(name="helper", body_complexity=5),
                ],
                total_lines=10,
            ),
        ]

    def test_build_creates_complete_graph(
        self, modules: list[ModuleDef], tmp_path: Path
    ) -> None:
        """build() creates all expected nodes and edges."""
        db_path = tmp_path / "build.mubase"

        with MUbase(db_path) as db:
            db.build(modules, Path("src"))
            stats = db.stats()

            # 2 modules + 2 functions = 4 nodes
            assert stats["nodes"] == 4

            # 2 CONTAINS edges (module -> function) + potential IMPORTS
            assert stats["edges"] >= 2

    def test_build_preserves_complexity(
        self, modules: list[ModuleDef], tmp_path: Path
    ) -> None:
        """build() preserves function complexity."""
        db_path = tmp_path / "complexity.mubase"

        with MUbase(db_path) as db:
            db.build(modules, Path("src"))

            run_func = db.find_by_name("run")
            assert len(run_func) == 1
            assert run_func[0].complexity == 10
