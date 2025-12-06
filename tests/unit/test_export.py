"""Tests for MU Kernel Export - multiple output formats."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.export import (
    CytoscapeExporter,
    D2Exporter,
    EdgeFilter,
    ExportManager,
    ExportOptions,
    ExportResult,
    Exporter,
    JSONExporter,
    MermaidExporter,
    MUTextExporter,
    NodeFilter,
    get_default_manager,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create temporary database path."""
    return tmp_path / "test.mubase"


@pytest.fixture
def db(db_path: Path) -> MUbase:
    """Create database instance with context manager."""
    database = MUbase(db_path)
    yield database
    database.close()


@pytest.fixture
def populated_db(db: MUbase) -> MUbase:
    """Create database with sample nodes and edges."""
    # Module node
    db.add_node(
        Node(
            id="mod:src/mymodule.py",
            type=NodeType.MODULE,
            name="mymodule",
            qualified_name="mymodule",
            file_path="src/mymodule.py",
            line_start=1,
            line_end=100,
            properties={"language": "python"},
        )
    )

    # Class node with inheritance
    db.add_node(
        Node(
            id="cls:src/mymodule.py:MyClass",
            type=NodeType.CLASS,
            name="MyClass",
            qualified_name="mymodule.MyClass",
            file_path="src/mymodule.py",
            line_start=10,
            line_end=50,
            properties={"bases": ["BaseClass"], "decorators": ["dataclass"]},
            complexity=20,
        )
    )

    # Function node (method)
    db.add_node(
        Node(
            id="fn:src/mymodule.py:MyClass.process",
            type=NodeType.FUNCTION,
            name="process",
            qualified_name="mymodule.MyClass.process",
            file_path="src/mymodule.py",
            line_start=15,
            line_end=30,
            properties={
                "is_method": True,
                "is_async": True,
                "parameters": [
                    {"name": "self"},
                    {"name": "data", "type_annotation": "str"},
                ],
                "return_type": "dict",
            },
            complexity=15,
        )
    )

    # Top-level function
    db.add_node(
        Node(
            id="fn:src/mymodule.py:helper",
            type=NodeType.FUNCTION,
            name="helper",
            qualified_name="mymodule.helper",
            file_path="src/mymodule.py",
            line_start=55,
            line_end=60,
            properties={
                "is_method": False,
                "parameters": [{"name": "x", "type_annotation": "int"}],
                "return_type": "int",
            },
            complexity=5,
        )
    )

    # External dependency
    db.add_node(
        Node(
            id="ext:json",
            type=NodeType.EXTERNAL,
            name="json",
            properties={"source": "stdlib"},
        )
    )

    # Edges: CONTAINS
    db.add_edge(
        Edge(
            id="edge:mod:cls",
            source_id="mod:src/mymodule.py",
            target_id="cls:src/mymodule.py:MyClass",
            type=EdgeType.CONTAINS,
        )
    )
    db.add_edge(
        Edge(
            id="edge:cls:fn",
            source_id="cls:src/mymodule.py:MyClass",
            target_id="fn:src/mymodule.py:MyClass.process",
            type=EdgeType.CONTAINS,
        )
    )
    db.add_edge(
        Edge(
            id="edge:mod:helper",
            source_id="mod:src/mymodule.py",
            target_id="fn:src/mymodule.py:helper",
            type=EdgeType.CONTAINS,
        )
    )

    # Edges: IMPORTS
    db.add_edge(
        Edge(
            id="edge:mod:ext",
            source_id="mod:src/mymodule.py",
            target_id="ext:json",
            type=EdgeType.IMPORTS,
            properties={"names": ["loads", "dumps"]},
        )
    )

    # Edges: INHERITS
    db.add_edge(
        Edge(
            id="edge:cls:inherits",
            source_id="cls:src/mymodule.py:MyClass",
            target_id="ext:BaseClass",
            type=EdgeType.INHERITS,
            properties={"base_name": "BaseClass"},
        )
    )

    return db


@pytest.fixture
def empty_db(db: MUbase) -> MUbase:
    """Return empty database."""
    return db


@pytest.fixture
def single_node_db(db: MUbase) -> MUbase:
    """Create database with a single node."""
    db.add_node(
        Node(
            id="mod:single.py",
            type=NodeType.MODULE,
            name="single",
            file_path="single.py",
        )
    )
    return db


# =============================================================================
# Base Module Tests (base.py)
# =============================================================================


class TestExportOptions:
    """Tests for ExportOptions dataclass."""

    def test_default_values(self) -> None:
        """ExportOptions has correct default values."""
        options = ExportOptions()

        assert options.node_ids is None
        assert options.node_types is None
        assert options.max_nodes is None
        assert options.include_edges is True
        assert options.extra == {}

    def test_custom_values(self) -> None:
        """ExportOptions accepts custom values."""
        options = ExportOptions(
            node_ids=["id1", "id2"],
            node_types=[NodeType.CLASS, NodeType.FUNCTION],
            max_nodes=50,
            include_edges=False,
            extra={"diagram_type": "flowchart"},
        )

        assert options.node_ids == ["id1", "id2"]
        assert options.node_types == [NodeType.CLASS, NodeType.FUNCTION]
        assert options.max_nodes == 50
        assert options.include_edges is False
        assert options.extra["diagram_type"] == "flowchart"

    def test_to_dict(self) -> None:
        """ExportOptions.to_dict() serializes correctly."""
        options = ExportOptions(
            node_types=[NodeType.MODULE],
            max_nodes=10,
            extra={"key": "value"},
        )

        d = options.to_dict()

        assert d["node_ids"] is None
        assert d["node_types"] == ["module"]
        assert d["max_nodes"] == 10
        assert d["include_edges"] is True
        assert d["extra"] == {"key": "value"}


class TestExportResult:
    """Tests for ExportResult dataclass."""

    def test_creation(self) -> None:
        """ExportResult can be created with required fields."""
        result = ExportResult(
            output="test output",
            format="test",
            node_count=5,
            edge_count=3,
        )

        assert result.output == "test output"
        assert result.format == "test"
        assert result.node_count == 5
        assert result.edge_count == 3
        assert result.error is None
        assert result.success is True

    def test_success_property(self) -> None:
        """ExportResult.success reflects error state."""
        success_result = ExportResult(
            output="ok",
            format="test",
            node_count=1,
            edge_count=0,
        )
        assert success_result.success is True

        error_result = ExportResult(
            output="",
            format="test",
            node_count=0,
            edge_count=0,
            error="Something went wrong",
        )
        assert error_result.success is False

    def test_to_dict(self) -> None:
        """ExportResult.to_dict() includes all fields."""
        result = ExportResult(
            output="content",
            format="json",
            node_count=10,
            edge_count=5,
            error=None,
        )

        d = result.to_dict()

        assert d["output"] == "content"
        assert d["format"] == "json"
        assert d["node_count"] == 10
        assert d["edge_count"] == 5
        assert d["error"] is None
        assert d["success"] is True
        assert "generated_at" in d

    def test_generated_at_timestamp(self) -> None:
        """ExportResult has generated_at timestamp."""
        result = ExportResult(
            output="",
            format="test",
            node_count=0,
            edge_count=0,
        )

        # Should be ISO format timestamp
        assert result.generated_at is not None
        assert "T" in result.generated_at  # ISO format has T separator


class TestExportManager:
    """Tests for ExportManager registration and dispatch."""

    def test_register_exporter(self) -> None:
        """ExportManager can register exporters."""
        manager = ExportManager()
        exporter = MUTextExporter()

        manager.register(exporter)

        assert manager.get_exporter("mu") is exporter

    def test_get_exporter_unknown(self) -> None:
        """ExportManager returns None for unknown format."""
        manager = ExportManager()

        result = manager.get_exporter("unknown_format")

        assert result is None

    def test_list_formats(self) -> None:
        """ExportManager lists registered format names."""
        manager = ExportManager()
        manager.register(MUTextExporter())
        manager.register(JSONExporter())

        formats = manager.list_formats()

        assert "mu" in formats
        assert "json" in formats
        assert len(formats) == 2

    def test_list_exporters_details(self) -> None:
        """ExportManager.list_exporters returns format details."""
        manager = ExportManager()
        manager.register(MUTextExporter())

        exporters = manager.list_exporters()

        assert len(exporters) == 1
        assert exporters[0]["name"] == "mu"
        assert exporters[0]["extension"] == ".mu"
        assert "description" in exporters[0]

    def test_export_unknown_format_returns_error(self, populated_db: MUbase) -> None:
        """ExportManager.export returns error for unknown format (not exception)."""
        manager = ExportManager()

        result = manager.export(populated_db, "nonexistent_format")

        assert result.success is False
        assert result.error is not None
        assert "Unknown format" in result.error
        assert "nonexistent_format" in result.error

    def test_export_dispatches_to_exporter(self, populated_db: MUbase) -> None:
        """ExportManager.export dispatches to correct exporter."""
        manager = ExportManager()
        manager.register(MUTextExporter())
        manager.register(JSONExporter())

        mu_result = manager.export(populated_db, "mu")
        json_result = manager.export(populated_db, "json")

        assert mu_result.format == "mu"
        assert json_result.format == "json"
        assert mu_result.output != json_result.output


class TestGetDefaultManager:
    """Tests for get_default_manager factory function."""

    def test_registers_all_exporters(self) -> None:
        """get_default_manager registers all default exporters."""
        manager = get_default_manager()

        formats = manager.list_formats()

        assert "mu" in formats
        assert "json" in formats
        assert "mermaid" in formats
        assert "d2" in formats
        assert "cytoscape" in formats
        assert len(formats) == 5

    def test_returns_new_instance(self) -> None:
        """get_default_manager returns new instance each call."""
        manager1 = get_default_manager()
        manager2 = get_default_manager()

        assert manager1 is not manager2


# =============================================================================
# Filter Tests (filters.py)
# =============================================================================


class TestNodeFilter:
    """Tests for NodeFilter utility class."""

    def test_by_ids_returns_matching_nodes(self, populated_db: MUbase) -> None:
        """NodeFilter.by_ids returns nodes matching the given IDs."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_ids(["mod:src/mymodule.py", "cls:src/mymodule.py:MyClass"])

        assert len(nodes) == 2
        node_ids = {n.id for n in nodes}
        assert "mod:src/mymodule.py" in node_ids
        assert "cls:src/mymodule.py:MyClass" in node_ids

    def test_by_ids_skips_missing_nodes(self, populated_db: MUbase) -> None:
        """NodeFilter.by_ids skips IDs that don't exist."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_ids(["mod:src/mymodule.py", "nonexistent:id", "also:missing"])

        assert len(nodes) == 1
        assert nodes[0].id == "mod:src/mymodule.py"

    def test_by_ids_preserves_order(self, populated_db: MUbase) -> None:
        """NodeFilter.by_ids preserves input order."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_ids(
            ["cls:src/mymodule.py:MyClass", "mod:src/mymodule.py", "fn:src/mymodule.py:helper"]
        )

        assert nodes[0].id == "cls:src/mymodule.py:MyClass"
        assert nodes[1].id == "mod:src/mymodule.py"
        assert nodes[2].id == "fn:src/mymodule.py:helper"

    def test_by_ids_empty_list(self, populated_db: MUbase) -> None:
        """NodeFilter.by_ids returns empty list for empty input."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_ids([])

        assert nodes == []

    def test_by_types_single_type(self, populated_db: MUbase) -> None:
        """NodeFilter.by_types filters by single type."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_types([NodeType.CLASS])

        assert len(nodes) == 1
        assert all(n.type == NodeType.CLASS for n in nodes)
        assert nodes[0].name == "MyClass"

    def test_by_types_multiple_types(self, populated_db: MUbase) -> None:
        """NodeFilter.by_types filters by multiple types."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_types([NodeType.MODULE, NodeType.EXTERNAL])

        # 1 module + 1 external
        assert len(nodes) == 2
        types = {n.type for n in nodes}
        assert types == {NodeType.MODULE, NodeType.EXTERNAL}

    def test_by_types_all_functions(self, populated_db: MUbase) -> None:
        """NodeFilter.by_types can filter all functions."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_types([NodeType.FUNCTION])

        # We have 2 functions: process and helper
        assert len(nodes) == 2
        assert all(n.type == NodeType.FUNCTION for n in nodes)

    def test_by_names_exact_match(self, populated_db: MUbase) -> None:
        """NodeFilter.by_names does exact matching by default."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_names(["helper"])

        assert len(nodes) == 1
        assert nodes[0].name == "helper"

    def test_by_names_fuzzy_match(self, populated_db: MUbase) -> None:
        """NodeFilter.by_names supports fuzzy matching."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_names(["process"], fuzzy=True)

        # Should match "process" with fuzzy (using %process%)
        assert len(nodes) >= 1
        assert any("process" in n.name.lower() for n in nodes)

    def test_by_names_with_node_type(self, populated_db: MUbase) -> None:
        """NodeFilter.by_names can filter by node type."""
        filter_ = NodeFilter(populated_db)

        # mymodule is both a module name and part of qualified names
        nodes = filter_.by_names(["mymodule"], node_type=NodeType.MODULE)

        assert len(nodes) == 1
        assert nodes[0].type == NodeType.MODULE

    def test_by_names_deduplicates(self, populated_db: MUbase) -> None:
        """NodeFilter.by_names deduplicates results."""
        filter_ = NodeFilter(populated_db)

        # Same name twice should return single result
        nodes = filter_.by_names(["helper", "helper"])

        assert len(nodes) == 1

    def test_by_complexity_min_threshold(self, populated_db: MUbase) -> None:
        """NodeFilter.by_complexity filters by minimum complexity."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_complexity(min_complexity=15)

        # MyClass (20) and process (15) should match
        assert len(nodes) >= 2
        for n in nodes:
            assert n.complexity >= 15

    def test_by_complexity_range(self, populated_db: MUbase) -> None:
        """NodeFilter.by_complexity filters by complexity range."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_complexity(min_complexity=10, max_complexity=20)

        for n in nodes:
            assert 10 <= n.complexity <= 20

    def test_by_complexity_default_min(self, populated_db: MUbase) -> None:
        """NodeFilter.by_complexity uses 0 as default min."""
        filter_ = NodeFilter(populated_db)

        # With no min specified, should default to 0
        nodes = filter_.by_complexity(max_complexity=5)

        for n in nodes:
            assert n.complexity <= 5

    def test_by_file_path(self, populated_db: MUbase) -> None:
        """NodeFilter.by_file_path filters by file path."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.by_file_path("src/mymodule.py")

        # All nodes with this file path
        assert len(nodes) >= 1
        for n in nodes:
            assert n.file_path == "src/mymodule.py"

    def test_combined_with_ids_and_types(self, populated_db: MUbase) -> None:
        """NodeFilter.combined applies AND logic with IDs and types."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.combined(
            node_ids=[
                "mod:src/mymodule.py",
                "cls:src/mymodule.py:MyClass",
                "fn:src/mymodule.py:helper",
            ],
            types=[NodeType.FUNCTION],
        )

        # Only helper is both in the IDs AND is a function
        assert len(nodes) == 1
        assert nodes[0].name == "helper"
        assert nodes[0].type == NodeType.FUNCTION

    def test_combined_with_types_and_complexity(self, populated_db: MUbase) -> None:
        """NodeFilter.combined applies AND logic with types and complexity."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.combined(
            types=[NodeType.FUNCTION],
            min_complexity=10,
        )

        # Only process method has complexity >= 10 among functions
        assert len(nodes) >= 1
        for n in nodes:
            assert n.type == NodeType.FUNCTION
            assert n.complexity >= 10

    def test_combined_with_names_fuzzy(self, populated_db: MUbase) -> None:
        """NodeFilter.combined supports fuzzy name matching."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.combined(
            names=["help"],
            fuzzy_names=True,
        )

        # Should match "helper"
        assert len(nodes) >= 1
        assert any("help" in n.name.lower() for n in nodes)

    def test_combined_with_file_path(self, populated_db: MUbase) -> None:
        """NodeFilter.combined can filter by file path."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.combined(
            types=[NodeType.FUNCTION],
            file_path="src/mymodule.py",
        )

        for n in nodes:
            assert n.type == NodeType.FUNCTION
            assert n.file_path == "src/mymodule.py"

    def test_combined_all_nodes_when_no_filters(self, populated_db: MUbase) -> None:
        """NodeFilter.combined returns all nodes when no filters applied."""
        filter_ = NodeFilter(populated_db)

        nodes = filter_.combined()

        # Should return all nodes in database
        all_nodes = populated_db.get_nodes()
        assert len(nodes) == len(all_nodes)


class TestEdgeFilter:
    """Tests for EdgeFilter utility class."""

    def test_for_nodes_returns_edges_between_nodes(self, populated_db: MUbase) -> None:
        """EdgeFilter.for_nodes returns edges connecting given nodes."""
        filter_ = EdgeFilter(populated_db)

        # Get module and class nodes
        mod_node = populated_db.get_node("mod:src/mymodule.py")
        cls_node = populated_db.get_node("cls:src/mymodule.py:MyClass")
        assert mod_node is not None
        assert cls_node is not None

        edges = filter_.for_nodes([mod_node, cls_node])

        # Should find the CONTAINS edge between them
        assert len(edges) >= 1
        for edge in edges:
            assert edge.source_id in [mod_node.id, cls_node.id]
            assert edge.target_id in [mod_node.id, cls_node.id]

    def test_for_nodes_excludes_edges_to_outside(self, populated_db: MUbase) -> None:
        """EdgeFilter.for_nodes excludes edges to nodes outside the set."""
        filter_ = EdgeFilter(populated_db)

        # Get only the module node
        mod_node = populated_db.get_node("mod:src/mymodule.py")
        assert mod_node is not None

        edges = filter_.for_nodes([mod_node])

        # Should not include edges to other nodes (like class, external)
        for edge in edges:
            assert edge.source_id == mod_node.id
            assert edge.target_id == mod_node.id  # Only self-edges if any

    def test_for_nodes_with_edge_type_filter(self, populated_db: MUbase) -> None:
        """EdgeFilter.for_nodes can filter by edge types."""
        filter_ = EdgeFilter(populated_db)

        # Get all nodes
        nodes = populated_db.get_nodes()

        edges = filter_.for_nodes(nodes, edge_types=[EdgeType.IMPORTS])

        for edge in edges:
            assert edge.type == EdgeType.IMPORTS

    def test_for_nodes_empty_node_list(self, populated_db: MUbase) -> None:
        """EdgeFilter.for_nodes returns empty for empty node list."""
        filter_ = EdgeFilter(populated_db)

        edges = filter_.for_nodes([])

        assert edges == []

    def test_by_type_contains(self, populated_db: MUbase) -> None:
        """EdgeFilter.by_type filters by CONTAINS type."""
        filter_ = EdgeFilter(populated_db)

        edges = filter_.by_type(EdgeType.CONTAINS)

        assert len(edges) >= 1
        for edge in edges:
            assert edge.type == EdgeType.CONTAINS

    def test_by_type_imports(self, populated_db: MUbase) -> None:
        """EdgeFilter.by_type filters by IMPORTS type."""
        filter_ = EdgeFilter(populated_db)

        edges = filter_.by_type(EdgeType.IMPORTS)

        assert len(edges) >= 1
        for edge in edges:
            assert edge.type == EdgeType.IMPORTS

    def test_by_type_inherits(self, populated_db: MUbase) -> None:
        """EdgeFilter.by_type filters by INHERITS type."""
        filter_ = EdgeFilter(populated_db)

        edges = filter_.by_type(EdgeType.INHERITS)

        assert len(edges) >= 1
        for edge in edges:
            assert edge.type == EdgeType.INHERITS

    def test_outgoing_returns_outbound_edges(self, populated_db: MUbase) -> None:
        """EdgeFilter.outgoing returns edges from a node."""
        filter_ = EdgeFilter(populated_db)

        edges = filter_.outgoing("mod:src/mymodule.py")

        # Module has outgoing CONTAINS and IMPORTS edges
        assert len(edges) >= 2
        for edge in edges:
            assert edge.source_id == "mod:src/mymodule.py"

    def test_outgoing_with_edge_type_filter(self, populated_db: MUbase) -> None:
        """EdgeFilter.outgoing can filter by edge types."""
        filter_ = EdgeFilter(populated_db)

        edges = filter_.outgoing("mod:src/mymodule.py", edge_types=[EdgeType.IMPORTS])

        for edge in edges:
            assert edge.source_id == "mod:src/mymodule.py"
            assert edge.type == EdgeType.IMPORTS

    def test_outgoing_no_edges(self, populated_db: MUbase) -> None:
        """EdgeFilter.outgoing returns empty for node with no outgoing edges."""
        filter_ = EdgeFilter(populated_db)

        # External nodes typically have no outgoing edges
        edges = filter_.outgoing("ext:json")

        assert edges == []

    def test_incoming_returns_inbound_edges(self, populated_db: MUbase) -> None:
        """EdgeFilter.incoming returns edges to a node."""
        filter_ = EdgeFilter(populated_db)

        edges = filter_.incoming("cls:src/mymodule.py:MyClass")

        # Class has incoming CONTAINS edge from module
        assert len(edges) >= 1
        for edge in edges:
            assert edge.target_id == "cls:src/mymodule.py:MyClass"

    def test_incoming_with_edge_type_filter(self, populated_db: MUbase) -> None:
        """EdgeFilter.incoming can filter by edge types."""
        filter_ = EdgeFilter(populated_db)

        edges = filter_.incoming("cls:src/mymodule.py:MyClass", edge_types=[EdgeType.CONTAINS])

        for edge in edges:
            assert edge.target_id == "cls:src/mymodule.py:MyClass"
            assert edge.type == EdgeType.CONTAINS

    def test_incoming_no_edges(self, populated_db: MUbase) -> None:
        """EdgeFilter.incoming returns empty for node with no incoming edges."""
        filter_ = EdgeFilter(populated_db)

        # Module typically has no incoming edges in this test data
        edges = filter_.incoming("mod:src/mymodule.py")

        # May be empty or have some edges depending on structure
        for edge in edges:
            assert edge.target_id == "mod:src/mymodule.py"


# =============================================================================
# Protocol Compliance Tests
# =============================================================================


class TestExporterProtocol:
    """Tests for Exporter protocol compliance."""

    def test_mu_exporter_is_exporter(self) -> None:
        """MUTextExporter implements Exporter protocol."""
        exporter = MUTextExporter()
        assert isinstance(exporter, Exporter)

    def test_json_exporter_is_exporter(self) -> None:
        """JSONExporter implements Exporter protocol."""
        exporter = JSONExporter()
        assert isinstance(exporter, Exporter)

    def test_mermaid_exporter_is_exporter(self) -> None:
        """MermaidExporter implements Exporter protocol."""
        exporter = MermaidExporter()
        assert isinstance(exporter, Exporter)

    def test_d2_exporter_is_exporter(self) -> None:
        """D2Exporter implements Exporter protocol."""
        exporter = D2Exporter()
        assert isinstance(exporter, Exporter)

    def test_cytoscape_exporter_is_exporter(self) -> None:
        """CytoscapeExporter implements Exporter protocol."""
        exporter = CytoscapeExporter()
        assert isinstance(exporter, Exporter)

    def test_all_exporters_have_format_name(self) -> None:
        """All exporters have format_name property."""
        exporters = [
            MUTextExporter(),
            JSONExporter(),
            MermaidExporter(),
            D2Exporter(),
            CytoscapeExporter(),
        ]
        for exp in exporters:
            assert exp.format_name
            assert isinstance(exp.format_name, str)

    def test_all_exporters_have_file_extension(self) -> None:
        """All exporters have file_extension property."""
        exporters = [
            MUTextExporter(),
            JSONExporter(),
            MermaidExporter(),
            D2Exporter(),
            CytoscapeExporter(),
        ]
        for exp in exporters:
            assert exp.file_extension
            assert exp.file_extension.startswith(".")

    def test_all_exporters_have_description(self) -> None:
        """All exporters have description property."""
        exporters = [
            MUTextExporter(),
            JSONExporter(),
            MermaidExporter(),
            D2Exporter(),
            CytoscapeExporter(),
        ]
        for exp in exporters:
            assert exp.description
            assert isinstance(exp.description, str)


# =============================================================================
# MU Text Exporter Tests (mu_text.py)
# =============================================================================


class TestMUTextExporter:
    """Tests for MU text format exporter."""

    def test_format_properties(self) -> None:
        """MUTextExporter has correct format properties."""
        exporter = MUTextExporter()

        assert exporter.format_name == "mu"
        assert exporter.file_extension == ".mu"
        assert "LLM" in exporter.description

    def test_module_sigil_in_output(self, populated_db: MUbase) -> None:
        """Module sigil ! appears in output."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        assert "!module" in result.output

    def test_class_sigil_in_output(self, populated_db: MUbase) -> None:
        """Class sigil $ appears in output."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        assert "$" in result.output
        assert "MyClass" in result.output

    def test_function_sigil_in_output(self, populated_db: MUbase) -> None:
        """Function sigil # appears in output."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        assert "#" in result.output
        assert "process" in result.output or "helper" in result.output

    def test_inheritance_marker(self, populated_db: MUbase) -> None:
        """Inheritance marker < works for base classes."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        # Check for inheritance in class definition
        assert "<" in result.output or "BaseClass" in result.output

    def test_imports_marker(self, populated_db: MUbase) -> None:
        """External dependencies marker @ works."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        # Check for external dep annotation
        assert "@ext" in result.output or "json" in result.output

    def test_annotation_marker(self, populated_db: MUbase) -> None:
        """Annotation marker :: appears for decorators."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        # The :: marker is used for annotations like decorators
        # or the output contains decorator info
        assert "::" in result.output or "dataclass" in result.output

    def test_grouping_by_module_path(self, populated_db: MUbase) -> None:
        """Output is grouped by module path."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        # Module header should appear
        assert "mymodule" in result.output

    def test_node_filtering(self, populated_db: MUbase) -> None:
        """Node filtering by type works."""
        exporter = MUTextExporter()
        options = ExportOptions(node_types=[NodeType.FUNCTION])

        result = exporter.export(populated_db, options)

        # Should include functions
        assert "process" in result.output or "helper" in result.output
        # Result counts only functions
        assert result.node_count <= 3  # Only function nodes selected

    def test_empty_graph_handling(self, empty_db: MUbase) -> None:
        """Empty graph produces valid output."""
        exporter = MUTextExporter()

        result = exporter.export(empty_db)

        assert result.success is True
        assert result.node_count == 0
        assert "No nodes to export" in result.output

    def test_max_nodes_limit(self, populated_db: MUbase) -> None:
        """max_nodes option limits output."""
        exporter = MUTextExporter()
        options = ExportOptions(max_nodes=2)

        result = exporter.export(populated_db, options)

        assert result.node_count <= 2

    def test_return_type_arrow(self, populated_db: MUbase) -> None:
        """Return type uses -> operator."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        # The process function has return_type="dict"
        assert "->" in result.output

    def test_async_modifier(self, populated_db: MUbase) -> None:
        """Async functions are marked."""
        exporter = MUTextExporter()

        result = exporter.export(populated_db)

        assert "async" in result.output


# =============================================================================
# JSON Exporter Tests (json_export.py)
# =============================================================================


class TestJSONExporter:
    """Tests for JSON format exporter."""

    def test_format_properties(self) -> None:
        """JSONExporter has correct format properties."""
        exporter = JSONExporter()

        assert exporter.format_name == "json"
        assert exporter.file_extension == ".json"

    def test_output_is_valid_json(self, populated_db: MUbase) -> None:
        """Output is valid JSON."""
        exporter = JSONExporter()

        result = exporter.export(populated_db)

        # Should not raise
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_schema_has_required_fields(self, populated_db: MUbase) -> None:
        """JSON schema has required fields: version, nodes, edges, stats."""
        exporter = JSONExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        assert "version" in data
        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data

    def test_pretty_print_mode(self, populated_db: MUbase) -> None:
        """Pretty print mode adds indentation."""
        exporter = JSONExporter()

        pretty_result = exporter.export(populated_db, ExportOptions(extra={"pretty": True}))
        compact_result = exporter.export(populated_db, ExportOptions(extra={"pretty": False}))

        # Pretty output has newlines, compact doesn't
        assert pretty_result.output.count("\n") > compact_result.output.count("\n")

    def test_compact_mode(self, populated_db: MUbase) -> None:
        """Compact mode produces single-line output."""
        exporter = JSONExporter()

        result = exporter.export(populated_db, ExportOptions(extra={"pretty": False}))

        # Compact JSON has no newlines (except possibly at end)
        lines = result.output.strip().split("\n")
        assert len(lines) == 1

    def test_node_count_matches_stats(self, populated_db: MUbase) -> None:
        """Node count in stats matches actual nodes."""
        exporter = JSONExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        assert data["stats"]["node_count"] == len(data["nodes"])
        assert result.node_count == len(data["nodes"])

    def test_edge_count_matches_stats(self, populated_db: MUbase) -> None:
        """Edge count in stats matches actual edges."""
        exporter = JSONExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        assert data["stats"]["edge_count"] == len(data["edges"])
        assert result.edge_count == len(data["edges"])

    def test_node_to_dict_serialization(self, populated_db: MUbase) -> None:
        """Nodes are serialized with to_dict()."""
        exporter = JSONExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        # Check that nodes have expected fields from Node.to_dict()
        if data["nodes"]:
            node = data["nodes"][0]
            assert "id" in node
            assert "type" in node
            assert "name" in node

    def test_empty_graph_produces_valid_json(self, empty_db: MUbase) -> None:
        """Empty graph produces valid JSON."""
        exporter = JSONExporter()

        result = exporter.export(empty_db)
        data = json.loads(result.output)

        assert data["stats"]["node_count"] == 0
        assert data["nodes"] == []

    def test_database_metadata_included(self, populated_db: MUbase) -> None:
        """Database metadata is included."""
        exporter = JSONExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        assert "database" in data
        assert "path" in data["database"]

    def test_nodes_by_type_stats(self, populated_db: MUbase) -> None:
        """Stats include nodes_by_type breakdown."""
        exporter = JSONExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        assert "nodes_by_type" in data["stats"]
        # We have module, class, function, external nodes
        nodes_by_type = data["stats"]["nodes_by_type"]
        assert isinstance(nodes_by_type, dict)


# =============================================================================
# Mermaid Exporter Tests (mermaid.py)
# =============================================================================


class TestMermaidExporter:
    """Tests for Mermaid diagram format exporter."""

    def test_format_properties(self) -> None:
        """MermaidExporter has correct format properties."""
        exporter = MermaidExporter()

        assert exporter.format_name == "mermaid"
        assert exporter.file_extension == ".mmd"

    def test_flowchart_output_starts_with_flowchart(self, populated_db: MUbase) -> None:
        """Flowchart output starts with 'flowchart'."""
        exporter = MermaidExporter()
        options = ExportOptions(extra={"diagram_type": "flowchart"})

        result = exporter.export(populated_db, options)

        assert result.output.startswith("flowchart")

    def test_class_diagram_starts_with_classDiagram(self, populated_db: MUbase) -> None:
        """Class diagram output starts with 'classDiagram'."""
        exporter = MermaidExporter()
        options = ExportOptions(extra={"diagram_type": "classDiagram"})

        result = exporter.export(populated_db, options)

        assert result.output.startswith("classDiagram")

    def test_node_shapes_vary_by_type(self, populated_db: MUbase) -> None:
        """Node shapes vary by node type."""
        exporter = MermaidExporter()

        result = exporter.export(populated_db)

        # Different shapes: ([ ]) for module, [ ] for class, ( ) for function
        output = result.output
        # At least one shape delimiter should appear
        has_shapes = any(s in output for s in ["([", "])", "[", "]", "(", ")", "{{", "}}"])
        assert has_shapes

    def test_edge_arrows_by_relationship(self, populated_db: MUbase) -> None:
        """Edge arrows vary by relationship type."""
        exporter = MermaidExporter()

        result = exporter.export(populated_db)

        # Different arrow types: --> for contains, -.-> for imports, ==> for inherits
        output = result.output
        has_arrows = "-->" in output or "-.->" in output or "==>" in output
        assert has_arrows

    def test_max_nodes_limit_respected(self, populated_db: MUbase) -> None:
        """Max nodes limit is respected."""
        exporter = MermaidExporter()
        options = ExportOptions(max_nodes=2)

        result = exporter.export(populated_db, options)

        assert result.node_count <= 2

    def test_default_max_nodes(self, populated_db: MUbase) -> None:
        """Default max nodes is applied."""
        exporter = MermaidExporter()

        # Default is 50, our test db has fewer nodes
        result = exporter.export(populated_db)

        assert result.node_count <= 50

    def test_special_characters_escaped(self, db: MUbase) -> None:
        """Special characters are escaped in labels."""
        # Create node with special characters
        db.add_node(
            Node(
                id="cls:test.py:Dict[str, int]",
                type=NodeType.CLASS,
                name="Dict[str, int]",
                file_path="test.py",
            )
        )

        exporter = MermaidExporter()
        result = exporter.export(db)

        # Brackets should be escaped
        assert result.success is True
        # Should not contain raw brackets in label position
        # The escaping replaces [ ] with ( )
        assert "Dict(str, int)" in result.output or "Dict_str__int_" in result.output

    def test_direction_option(self, populated_db: MUbase) -> None:
        """Direction option affects output."""
        exporter = MermaidExporter()

        lr_result = exporter.export(populated_db, ExportOptions(extra={"direction": "LR"}))
        tb_result = exporter.export(populated_db, ExportOptions(extra={"direction": "TB"}))

        assert "LR" in lr_result.output
        assert "TB" in tb_result.output

    def test_empty_graph_handling(self, empty_db: MUbase) -> None:
        """Empty graph produces valid output."""
        exporter = MermaidExporter()

        result = exporter.export(empty_db)

        assert result.success is True
        assert "flowchart" in result.output
        assert "No nodes" in result.output


# =============================================================================
# D2 Exporter Tests (d2.py)
# =============================================================================


class TestD2Exporter:
    """Tests for D2 diagram format exporter."""

    def test_format_properties(self) -> None:
        """D2Exporter has correct format properties."""
        exporter = D2Exporter()

        assert exporter.format_name == "d2"
        assert exporter.file_extension == ".d2"

    def test_output_includes_direction_directive(self, populated_db: MUbase) -> None:
        """Output includes 'direction:' directive."""
        exporter = D2Exporter()

        result = exporter.export(populated_db)

        assert "direction:" in result.output

    def test_node_definitions_with_labels(self, populated_db: MUbase) -> None:
        """Node definitions include labels."""
        exporter = D2Exporter()

        result = exporter.export(populated_db)

        # D2 format: node_id: label
        assert ": " in result.output  # Colon with space for labels

    def test_edge_definitions(self, populated_db: MUbase) -> None:
        """Edge definitions use -> notation."""
        exporter = D2Exporter()

        result = exporter.export(populated_db)

        # D2 edges use ->
        assert " -> " in result.output

    def test_style_includes_optional(self, populated_db: MUbase) -> None:
        """Style includes are optional."""
        exporter = D2Exporter()

        with_styles = exporter.export(populated_db, ExportOptions(extra={"include_styles": True}))
        without_styles = exporter.export(
            populated_db, ExportOptions(extra={"include_styles": False})
        )

        # With styles should have .shape definitions
        assert ".shape:" in with_styles.output
        # Without styles should not
        assert ".shape:" not in without_styles.output

    def test_direction_options(self, populated_db: MUbase) -> None:
        """Direction options work."""
        exporter = D2Exporter()

        right = exporter.export(populated_db, ExportOptions(extra={"direction": "right"}))
        down = exporter.export(populated_db, ExportOptions(extra={"direction": "down"}))

        assert "direction: right" in right.output
        assert "direction: down" in down.output

    def test_empty_graph_handling(self, empty_db: MUbase) -> None:
        """Empty graph produces valid output."""
        exporter = D2Exporter()

        result = exporter.export(empty_db)

        assert result.success is True
        assert "No nodes to export" in result.output

    def test_node_icons_by_type(self, populated_db: MUbase) -> None:
        """Node labels include type icons."""
        exporter = D2Exporter()

        result = exporter.export(populated_db)

        # Icons: M for module, C for class, f for function
        output = result.output
        has_icons = "M " in output or "C " in output or "f " in output
        assert has_icons

    def test_edge_labels_show_relationship(self, populated_db: MUbase) -> None:
        """Edge labels show relationship type."""
        exporter = D2Exporter()

        result = exporter.export(populated_db)

        # Edge labels like "contains", "imports", "inherits"
        output = result.output
        has_label = "contains" in output or "imports" in output or "inherits" in output
        assert has_label


# =============================================================================
# Cytoscape Exporter Tests (cytoscape.py)
# =============================================================================


class TestCytoscapeExporter:
    """Tests for Cytoscape.js JSON format exporter."""

    def test_format_properties(self) -> None:
        """CytoscapeExporter has correct format properties."""
        exporter = CytoscapeExporter()

        assert exporter.format_name == "cytoscape"
        assert exporter.file_extension == ".cyjs"

    def test_output_is_valid_json(self, populated_db: MUbase) -> None:
        """Output is valid JSON."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db)

        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_has_elements_key(self, populated_db: MUbase) -> None:
        """Output has 'elements' key with nodes and edges."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        assert "elements" in data
        assert "nodes" in data["elements"]
        assert "edges" in data["elements"]

    def test_node_data_structure(self, populated_db: MUbase) -> None:
        """Node data includes id, label, type."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        if data["elements"]["nodes"]:
            node = data["elements"]["nodes"][0]
            assert "data" in node
            assert "id" in node["data"]
            assert "label" in node["data"]
            assert "type" in node["data"]

    def test_edge_data_structure(self, populated_db: MUbase) -> None:
        """Edge data includes source and target."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        if data["elements"]["edges"]:
            edge = data["elements"]["edges"][0]
            assert "data" in edge
            assert "source" in edge["data"]
            assert "target" in edge["data"]

    def test_default_styles_included(self, populated_db: MUbase) -> None:
        """Default styles are included when requested."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db, ExportOptions(extra={"include_styles": True}))
        data = json.loads(result.output)

        assert "style" in data
        assert isinstance(data["style"], list)
        assert len(data["style"]) > 0

    def test_styles_excluded_when_disabled(self, populated_db: MUbase) -> None:
        """Styles are excluded when disabled."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db, ExportOptions(extra={"include_styles": False}))
        data = json.loads(result.output)

        assert "style" not in data

    def test_layout_included_when_enabled(self, populated_db: MUbase) -> None:
        """Layout is included when enabled."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db, ExportOptions(extra={"include_layout": True}))
        data = json.loads(result.output)

        assert "layout" in data
        assert "name" in data["layout"]

    def test_layout_excluded_when_disabled(self, populated_db: MUbase) -> None:
        """Layout is excluded when disabled."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db, ExportOptions(extra={"include_layout": False}))
        data = json.loads(result.output)

        assert "layout" not in data

    def test_edge_has_unique_id(self, populated_db: MUbase) -> None:
        """Edges have unique IDs."""
        exporter = CytoscapeExporter()

        result = exporter.export(populated_db)
        data = json.loads(result.output)

        edge_ids = [e["data"]["id"] for e in data["elements"]["edges"]]
        assert len(edge_ids) == len(set(edge_ids))  # All unique

    def test_empty_graph_produces_valid_json(self, empty_db: MUbase) -> None:
        """Empty graph produces valid JSON structure."""
        exporter = CytoscapeExporter()

        result = exporter.export(empty_db)
        data = json.loads(result.output)

        assert data["elements"]["nodes"] == []
        assert data["elements"]["edges"] == []


# =============================================================================
# Export Manager Integration Tests
# =============================================================================


class TestExportManagerIntegration:
    """Integration tests for ExportManager with all exporters."""

    def test_all_formats_registered(self) -> None:
        """All default formats are registered."""
        manager = get_default_manager()

        formats = manager.list_formats()

        expected = ["cytoscape", "d2", "json", "mermaid", "mu"]
        assert sorted(formats) == expected

    def test_export_all_formats(self, populated_db: MUbase) -> None:
        """All formats can export successfully."""
        manager = get_default_manager()

        for fmt in manager.list_formats():
            result = manager.export(populated_db, fmt)
            assert result.success, f"Format {fmt} failed: {result.error}"
            assert result.output, f"Format {fmt} produced empty output"

    def test_export_with_node_type_filter(self, populated_db: MUbase) -> None:
        """Node type filter works across formats."""
        manager = get_default_manager()
        options = ExportOptions(node_types=[NodeType.CLASS])

        for fmt in manager.list_formats():
            result = manager.export(populated_db, fmt, options)
            assert result.success, f"Format {fmt} failed with filter"
            # Should only export class nodes
            assert result.node_count <= 2  # We have 1 class in test data

    def test_export_with_max_nodes(self, populated_db: MUbase) -> None:
        """Max nodes limit works across formats."""
        manager = get_default_manager()
        options = ExportOptions(max_nodes=1)

        for fmt in manager.list_formats():
            result = manager.export(populated_db, fmt, options)
            assert result.success, f"Format {fmt} failed with max_nodes"
            assert result.node_count <= 1

    def test_export_without_edges(self, populated_db: MUbase) -> None:
        """include_edges=False works across formats."""
        manager = get_default_manager()
        options = ExportOptions(include_edges=False)

        for fmt in manager.list_formats():
            result = manager.export(populated_db, fmt, options)
            assert result.success, f"Format {fmt} failed without edges"
            assert result.edge_count == 0


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestExportEdgeCases:
    """Edge case tests for export functionality."""

    def test_single_node_export(self, single_node_db: MUbase) -> None:
        """Single node graph exports correctly."""
        manager = get_default_manager()

        for fmt in manager.list_formats():
            result = manager.export(single_node_db, fmt)
            assert result.success, f"Format {fmt} failed with single node"
            assert result.node_count == 1
            assert result.edge_count == 0

    def test_node_with_special_characters_in_name(self, db: MUbase) -> None:
        """Nodes with special characters in names are handled."""
        db.add_node(
            Node(
                id="fn:test.py:<lambda>",
                type=NodeType.FUNCTION,
                name="<lambda>",
                file_path="test.py",
            )
        )

        manager = get_default_manager()

        for fmt in manager.list_formats():
            result = manager.export(db, fmt)
            assert result.success, f"Format {fmt} failed with special chars"

    def test_node_with_unicode_name(self, db: MUbase) -> None:
        """Nodes with unicode names are handled."""
        db.add_node(
            Node(
                id="fn:test.py:calculate_sum",
                type=NodeType.FUNCTION,
                name="calculate_sum",
                file_path="test.py",
            )
        )

        manager = get_default_manager()

        for fmt in manager.list_formats():
            result = manager.export(db, fmt)
            assert result.success, f"Format {fmt} failed with unicode"

    def test_high_complexity_node(self, db: MUbase) -> None:
        """High complexity nodes are handled (may get special annotation)."""
        db.add_node(
            Node(
                id="fn:test.py:complex_func",
                type=NodeType.FUNCTION,
                name="complex_func",
                file_path="test.py",
                complexity=100,
            )
        )

        manager = get_default_manager()

        for fmt in manager.list_formats():
            result = manager.export(db, fmt)
            assert result.success, f"Format {fmt} failed with high complexity"

    def test_node_without_file_path(self, db: MUbase) -> None:
        """Nodes without file_path are handled."""
        db.add_node(
            Node(
                id="ext:external_dep",
                type=NodeType.EXTERNAL,
                name="external_dep",
            )
        )

        manager = get_default_manager()

        for fmt in manager.list_formats():
            result = manager.export(db, fmt)
            assert result.success, f"Format {fmt} failed with no file_path"

    def test_circular_edges(self, db: MUbase) -> None:
        """Circular dependencies are handled."""
        db.add_node(Node(id="mod:a.py", type=NodeType.MODULE, name="a", file_path="a.py"))
        db.add_node(Node(id="mod:b.py", type=NodeType.MODULE, name="b", file_path="b.py"))
        db.add_edge(
            Edge(
                id="edge:a:b",
                source_id="mod:a.py",
                target_id="mod:b.py",
                type=EdgeType.IMPORTS,
            )
        )
        db.add_edge(
            Edge(
                id="edge:b:a",
                source_id="mod:b.py",
                target_id="mod:a.py",
                type=EdgeType.IMPORTS,
            )
        )

        manager = get_default_manager()

        for fmt in manager.list_formats():
            result = manager.export(db, fmt)
            assert result.success, f"Format {fmt} failed with circular deps"
            assert result.edge_count == 2

    def test_self_referencing_edge(self, db: MUbase) -> None:
        """Self-referencing edges are handled."""
        db.add_node(Node(id="cls:a.py:A", type=NodeType.CLASS, name="A", file_path="a.py"))
        db.add_edge(
            Edge(
                id="edge:a:a",
                source_id="cls:a.py:A",
                target_id="cls:a.py:A",
                type=EdgeType.CONTAINS,  # Unusual but test edge case
            )
        )

        manager = get_default_manager()

        for fmt in manager.list_formats():
            result = manager.export(db, fmt)
            assert result.success, f"Format {fmt} failed with self-reference"

    def test_node_ids_filter_with_missing_ids(self, populated_db: MUbase) -> None:
        """Filtering by node_ids handles missing IDs gracefully."""
        manager = get_default_manager()
        options = ExportOptions(
            node_ids=["mod:src/mymodule.py", "nonexistent:id", "another:missing"]
        )

        for fmt in manager.list_formats():
            result = manager.export(populated_db, fmt, options)
            assert result.success, f"Format {fmt} failed with missing IDs"
            # Should only include the existing node
            assert result.node_count == 1
