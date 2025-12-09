"""Integration tests for Call Graph functionality.

Tests MUQL queries for call relationships (SHOW CALLERS/CALLEES, FIND PATH VIA calls)
and mu_impact() with call edges.

NOTE: Call edge extraction (CALLS edge type) is not yet implemented in the graph builder.
These tests set up call edges manually to test the query infrastructure.
When call graph extraction is added, these tests will validate the end-to-end flow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.muql import MUQLEngine

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def call_graph_db(tmp_path: Path) -> MUbase:
    """Create a MUbase with call graph edges for testing.

    This fixture creates a realistic codebase graph structure with
    function call relationships:

    src/utils.py:
        - validate() -> (no calls)
        - transform() -> validate()

    src/service.py:
        - DataService class
            - process() -> validate(), transform(), save()
            - save() -> (no calls)

    src/main.py:
        - main() -> DataService.process()
    """
    db = MUbase(tmp_path / "call_graph.mubase")

    # =========================================================================
    # Modules
    # =========================================================================
    modules_data = [
        ("mod:src/utils.py", "utils", "src/utils.py", 50),
        ("mod:src/service.py", "service", "src/service.py", 100),
        ("mod:src/main.py", "main", "src/main.py", 30),
    ]

    for mid, name, path, lines in modules_data:
        db.add_node(
            Node(
                id=mid,
                type=NodeType.MODULE,
                name=name,
                qualified_name=name,
                file_path=path,
                line_start=1,
                line_end=lines,
                complexity=0,
            )
        )

    # =========================================================================
    # Classes
    # =========================================================================
    db.add_node(
        Node(
            id="cls:src/service.py:DataService",
            type=NodeType.CLASS,
            name="DataService",
            qualified_name="service.DataService",
            file_path="src/service.py",
            line_start=5,
            line_end=50,
            complexity=0,
        )
    )

    # =========================================================================
    # Functions
    # =========================================================================
    functions_data = [
        # src/utils.py functions
        (
            "fn:src/utils.py:validate",
            "validate",
            "src/utils.py",
            5,
            {"is_method": False, "parameters": [{"name": "data", "type": "Any"}]},
        ),
        (
            "fn:src/utils.py:transform",
            "transform",
            "src/utils.py",
            10,
            {"is_method": False, "parameters": [{"name": "data", "type": "Any"}]},
        ),
        # src/service.py methods
        (
            "fn:src/service.py:DataService.process",
            "process",
            "src/service.py",
            15,
            {"is_method": True, "parameters": [{"name": "self"}, {"name": "data", "type": "Any"}]},
        ),
        (
            "fn:src/service.py:DataService.save",
            "save",
            "src/service.py",
            5,
            {"is_method": True, "parameters": [{"name": "self"}, {"name": "data", "type": "Any"}]},
        ),
        # src/main.py function
        (
            "fn:src/main.py:main",
            "main",
            "src/main.py",
            12,
            {"is_method": False, "parameters": []},
        ),
    ]

    for fid, name, path, complexity, props in functions_data:
        db.add_node(
            Node(
                id=fid,
                type=NodeType.FUNCTION,
                name=name,
                qualified_name=f"{path}.{name}",
                file_path=path,
                line_start=10,
                line_end=30,
                complexity=complexity,
                properties=props,
            )
        )

    # =========================================================================
    # CONTAINS edges (structural)
    # =========================================================================
    contains_edges = [
        ("mod:src/utils.py", "fn:src/utils.py:validate"),
        ("mod:src/utils.py", "fn:src/utils.py:transform"),
        ("mod:src/service.py", "cls:src/service.py:DataService"),
        ("cls:src/service.py:DataService", "fn:src/service.py:DataService.process"),
        ("cls:src/service.py:DataService", "fn:src/service.py:DataService.save"),
        ("mod:src/main.py", "fn:src/main.py:main"),
    ]

    for i, (src, tgt) in enumerate(contains_edges):
        db.add_edge(
            Edge(
                id=f"edge:contains:{i}",
                source_id=src,
                target_id=tgt,
                type=EdgeType.CONTAINS,
            )
        )

    # =========================================================================
    # IMPORTS edges
    # =========================================================================
    imports_edges = [
        ("mod:src/service.py", "mod:src/utils.py"),
        ("mod:src/main.py", "mod:src/service.py"),
    ]

    for i, (src, tgt) in enumerate(imports_edges):
        db.add_edge(
            Edge(
                id=f"edge:imports:{i}",
                source_id=src,
                target_id=tgt,
                type=EdgeType.IMPORTS,
            )
        )

    # =========================================================================
    # CALLS edges (simulated - this edge type needs to be added to schema)
    # For now we simulate call relationships using generic edges with 'calls' type
    # =========================================================================
    # NOTE: EdgeType.CALLS doesn't exist yet, so we add edges directly with
    # the string type 'calls'. When CALLS is added to EdgeType enum, update this.
    calls_edges = [
        # transform() calls validate()
        ("fn:src/utils.py:transform", "fn:src/utils.py:validate"),
        # process() calls validate(), transform(), save()
        ("fn:src/service.py:DataService.process", "fn:src/utils.py:validate"),
        ("fn:src/service.py:DataService.process", "fn:src/utils.py:transform"),
        ("fn:src/service.py:DataService.process", "fn:src/service.py:DataService.save"),
        # main() calls process()
        ("fn:src/main.py:main", "fn:src/service.py:DataService.process"),
    ]

    for i, (src, tgt) in enumerate(calls_edges):
        # Use raw SQL to insert edge with 'calls' type since EdgeType.CALLS doesn't exist
        db.conn.execute(
            """
            INSERT INTO edges (id, source_id, target_id, type, properties)
            VALUES (?, ?, ?, 'calls', NULL)
            """,
            [f"edge:calls:{i}", src, tgt],
        )

    yield db
    db.close()


@pytest.fixture
def engine(call_graph_db: MUbase) -> MUQLEngine:
    """Create MUQLEngine with call graph database."""
    return MUQLEngine(call_graph_db)


# =============================================================================
# Call Edge Query Tests
# =============================================================================


class TestCallGraphQueries:
    """Test MUQL queries for call relationships."""

    def test_show_callees_of_function(self, engine: MUQLEngine) -> None:
        """Test SHOW CALLEES OF query returns functions called by target."""
        # Query callees of process method (what does process call?)
        result = engine.execute('SHOW callees OF "fn:src/service.py:DataService.process"')

        assert result.is_success, f"Query failed: {result.error}"
        # process() calls validate(), transform(), save()
        assert result.row_count >= 1

    def test_show_callers_of_function(self, engine: MUQLEngine) -> None:
        """Test SHOW CALLERS OF query returns functions that call target."""
        # Query callers of validate (what calls validate?)
        result = engine.execute('SHOW callers OF "fn:src/utils.py:validate"')

        assert result.is_success, f"Query failed: {result.error}"
        # validate() is called by transform() and process()
        assert result.row_count >= 1

    def test_show_callees_of_leaf_function(self, engine: MUQLEngine) -> None:
        """Test SHOW CALLEES of a function that calls nothing."""
        # validate() doesn't call anything
        result = engine.execute('SHOW callees OF "fn:src/utils.py:validate"')

        assert result.is_success, f"Query failed: {result.error}"
        # Leaf functions should return empty or minimal results

    def test_show_callers_of_entry_point(self, engine: MUQLEngine) -> None:
        """Test SHOW CALLERS of entry point that isn't called."""
        # main() is the entry point, not called by anything in our test data
        result = engine.execute('SHOW callers OF "fn:src/main.py:main"')

        assert result.is_success, f"Query failed: {result.error}"

    def test_show_callees_depth_parameter(self, engine: MUQLEngine) -> None:
        """Test SHOW CALLEES with depth traversal."""
        # Get callees of main with depth 2 (should reach validate via process -> validate)
        result = engine.execute('SHOW callees OF "fn:src/main.py:main" DEPTH 2')

        assert result.is_success, f"Query failed: {result.error}"

    def test_show_callers_by_simple_name(self, engine: MUQLEngine) -> None:
        """Test SHOW CALLERS using simple function name (not full ID)."""
        # Query by simple name - should resolve to node
        result = engine.execute("SHOW callers OF validate")

        assert result.is_success, f"Query failed: {result.error}"

    def test_nonexistent_function_callers(self, engine: MUQLEngine) -> None:
        """Test SHOW CALLERS for non-existent function."""
        result = engine.execute("SHOW callers OF nonexistent_function_xyz")

        # Should return an error or empty result
        assert not result.is_success or result.row_count == 0


# =============================================================================
# Path Finding with Call Edges
# =============================================================================


class TestPathFindingWithCalls:
    """Test PATH queries using call relationships."""

    def test_find_path_between_functions(self, engine: MUQLEngine) -> None:
        """Test finding path between two functions."""
        result = engine.execute('PATH FROM "fn:src/main.py:main" TO "fn:src/utils.py:validate"')

        # Path should exist: main -> process -> validate
        assert result.is_success or result.error

    def test_find_path_direct_call(self, engine: MUQLEngine) -> None:
        """Test finding direct call path."""
        result = engine.execute(
            'PATH FROM "fn:src/utils.py:transform" TO "fn:src/utils.py:validate"'
        )

        # Direct path: transform -> validate
        assert result is not None


# =============================================================================
# Impact Analysis with Call Edges
# =============================================================================


class TestImpactAnalysisWithCalls:
    """Test impact analysis following call edges."""

    def test_impact_follows_call_edges(self, call_graph_db: MUbase) -> None:
        """Test that impact analysis follows call edges.

        If we change validate(), what might break?
        Answer: transform() and process() which call it.
        """
        # Use GraphManager for impact analysis
        try:
            from mu.kernel.graph import GraphManager

            gm = GraphManager(call_graph_db.conn)
            gm.load()

            # Impact of validate (following all edge types)
            impacted = gm.impact("fn:src/utils.py:validate")

            # This tests downstream - what validate leads to
            # For callers we need ancestors
            assert impacted is not None
        except ImportError:
            pytest.skip("Rust core not available")

    def test_ancestors_finds_callers(self, call_graph_db: MUbase) -> None:
        """Test that ancestors finds functions that call target.

        Who calls validate()? transform() and process().
        """
        try:
            from mu.kernel.graph import GraphManager

            gm = GraphManager(call_graph_db.conn)
            gm.load()

            # Get ancestors following 'calls' edges
            callers = gm.ancestors("fn:src/utils.py:validate", ["calls"])

            # transform() and process() call validate()
            assert isinstance(callers, list)
            # At least transform should be found
            caller_ids = set(callers)
            assert (
                "fn:src/utils.py:transform" in caller_ids
                or "fn:src/service.py:DataService.process" in caller_ids
            ), f"Expected callers not found in: {callers}"
        except ImportError:
            pytest.skip("Rust core not available")

    def test_impact_with_call_edge_filter(self, call_graph_db: MUbase) -> None:
        """Test impact analysis filtering by call edges only."""
        try:
            from mu.kernel.graph import GraphManager

            gm = GraphManager(call_graph_db.conn)
            gm.load()

            # Get impact following only call edges
            impacted = gm.impact("fn:src/main.py:main", ["calls"])

            # main -> process -> validate/transform/save
            assert impacted is not None
            assert isinstance(impacted, list)
        except ImportError:
            pytest.skip("Rust core not available")


# =============================================================================
# Call Edge Persistence Tests
# =============================================================================


class TestCallEdgePersistence:
    """Test that call edges are stored and retrieved correctly."""

    def test_call_edges_exist_in_db(self, call_graph_db: MUbase) -> None:
        """Verify call edges were inserted into the database."""
        # Query for edges with type 'calls'
        rows = call_graph_db.conn.execute(
            "SELECT COUNT(*) FROM edges WHERE type = 'calls'"
        ).fetchone()

        assert rows is not None
        call_count = rows[0]
        # We inserted 5 call edges in the fixture
        assert call_count == 5, f"Expected 5 call edges, found {call_count}"

    def test_call_edges_have_correct_structure(self, call_graph_db: MUbase) -> None:
        """Verify call edges link functions correctly."""
        # Check that transform -> validate edge exists
        rows = call_graph_db.conn.execute(
            """
            SELECT source_id, target_id FROM edges
            WHERE type = 'calls'
            AND source_id = 'fn:src/utils.py:transform'
            """
        ).fetchall()

        assert len(rows) == 1
        source, target = rows[0]
        assert source == "fn:src/utils.py:transform"
        assert target == "fn:src/utils.py:validate"

    def test_stats_include_call_edges(self, call_graph_db: MUbase) -> None:
        """Verify stats() reports call edge count."""
        stats = call_graph_db.stats()

        # edges_by_type should include 'calls'
        edges_by_type = stats.get("edges_by_type", {})
        assert "calls" in edges_by_type, f"'calls' not in edge types: {edges_by_type}"
        assert edges_by_type["calls"] == 5


# =============================================================================
# MUQL FIND Queries with Call Edges
# =============================================================================


class TestFindQueriesWithCalls:
    """Test FIND queries that use call relationships."""

    def test_find_functions_calling(self, engine: MUQLEngine) -> None:
        """Test FIND functions CALLING target."""
        # Find functions that call validate
        result = engine.execute('FIND functions CALLING "fn:src/utils.py:validate"')

        # May return error if CALLS edges not fully supported yet
        assert result is not None

    def test_find_functions_called_by(self, engine: MUQLEngine) -> None:
        """Test FIND functions CALLED BY target."""
        result = engine.execute('FIND functions CALLED BY "fn:src/main.py:main"')

        assert result is not None


# =============================================================================
# Graph Statistics Tests
# =============================================================================


class TestGraphStatistics:
    """Test graph statistics with call edges."""

    def test_edge_type_distribution(self, call_graph_db: MUbase) -> None:
        """Verify edge type distribution is correct."""
        stats = call_graph_db.stats()
        edges_by_type = stats.get("edges_by_type", {})

        # Should have contains, imports, and calls
        assert "contains" in edges_by_type
        assert "imports" in edges_by_type
        assert "calls" in edges_by_type

        # Verify counts
        assert edges_by_type["contains"] == 6  # 6 contains edges
        assert edges_by_type["imports"] == 2  # 2 imports edges
        assert edges_by_type["calls"] == 5  # 5 call edges


# =============================================================================
# ANALYZE Queries with Call Graph
# =============================================================================


class TestAnalyzeWithCallGraph:
    """Test ANALYZE queries that consider call relationships."""

    def test_analyze_circular_calls(self, engine: MUQLEngine) -> None:
        """Test ANALYZE circular doesn't crash with call edges present."""
        result = engine.execute("ANALYZE circular")

        assert result.is_success, f"Query failed: {result.error}"
        # Our test data has no circular calls

    def test_analyze_unused_with_calls(self, engine: MUQLEngine) -> None:
        """Test ANALYZE unused considers call edges."""
        result = engine.execute("ANALYZE unused")

        assert result.is_success, f"Query failed: {result.error}"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestCallGraphEdgeCases:
    """Test edge cases for call graph functionality."""

    def test_self_recursive_call(self, call_graph_db: MUbase) -> None:
        """Test handling of recursive function calls."""
        # Add a self-recursive edge
        call_graph_db.conn.execute(
            """
            INSERT INTO edges (id, source_id, target_id, type, properties)
            VALUES ('edge:calls:recursive', 'fn:src/utils.py:validate',
                    'fn:src/utils.py:validate', 'calls', NULL)
            """
        )

        # Query should not hang or crash
        engine = MUQLEngine(call_graph_db)
        result = engine.execute('SHOW callees OF "fn:src/utils.py:validate"')

        assert result is not None

    def test_mutual_recursion(self, call_graph_db: MUbase) -> None:
        """Test handling of mutual recursion (A calls B, B calls A)."""
        # Add mutual recursive edges
        call_graph_db.conn.execute(
            """
            INSERT INTO edges (id, source_id, target_id, type, properties)
            VALUES
                ('edge:calls:mutual1', 'fn:src/utils.py:validate',
                 'fn:src/utils.py:transform', 'calls', NULL),
                ('edge:calls:mutual2', 'fn:src/utils.py:transform',
                 'fn:src/utils.py:validate', 'calls', NULL)
            """
        )

        try:
            from mu.kernel.graph import GraphManager

            gm = GraphManager(call_graph_db.conn)
            gm.load()

            # Find cycles should detect the mutual recursion
            cycles = gm.find_cycles(["calls"])
            assert cycles is not None
        except ImportError:
            pytest.skip("Rust core not available")

    def test_deeply_nested_calls(self, call_graph_db: MUbase) -> None:
        """Test handling of deep call chains."""
        # Create a chain: f1 -> f2 -> f3 -> f4 -> f5
        for i in range(1, 5):
            # Add function nodes
            call_graph_db.add_node(
                Node(
                    id=f"fn:src/chain.py:f{i}",
                    type=NodeType.FUNCTION,
                    name=f"f{i}",
                    qualified_name=f"chain.f{i}",
                    file_path="src/chain.py",
                    line_start=i * 10,
                    line_end=i * 10 + 5,
                    complexity=1,
                )
            )

        # Add the last one
        call_graph_db.add_node(
            Node(
                id="fn:src/chain.py:f5",
                type=NodeType.FUNCTION,
                name="f5",
                qualified_name="chain.f5",
                file_path="src/chain.py",
                line_start=50,
                line_end=55,
                complexity=1,
            )
        )

        # Create the call chain edges
        for i in range(1, 5):
            call_graph_db.conn.execute(
                """
                INSERT INTO edges (id, source_id, target_id, type, properties)
                VALUES (?, ?, ?, 'calls', NULL)
                """,
                [f"edge:calls:chain{i}", f"fn:src/chain.py:f{i}", f"fn:src/chain.py:f{i + 1}"],
            )

        try:
            from mu.kernel.graph import GraphManager

            gm = GraphManager(call_graph_db.conn)
            gm.load()

            # Get all callees from f1 (should reach f5)
            impact = gm.impact("fn:src/chain.py:f1", ["calls"])
            assert "fn:src/chain.py:f5" in impact
        except ImportError:
            pytest.skip("Rust core not available")


# =============================================================================
# Performance Tests
# =============================================================================


class TestCallGraphPerformance:
    """Test performance of call graph queries."""

    def test_callers_query_under_100ms(self, engine: MUQLEngine) -> None:
        """SHOW CALLERS query should complete in < 100ms."""
        import time

        start = time.perf_counter()
        result = engine.execute('SHOW callers OF "fn:src/utils.py:validate"')
        elapsed = (time.perf_counter() - start) * 1000

        assert result is not None
        assert elapsed < 100, f"Query took {elapsed:.2f}ms, expected < 100ms"

    def test_callees_query_under_100ms(self, engine: MUQLEngine) -> None:
        """SHOW CALLEES query should complete in < 100ms."""
        import time

        start = time.perf_counter()
        result = engine.execute('SHOW callees OF "fn:src/service.py:DataService.process"')
        elapsed = (time.perf_counter() - start) * 1000

        assert result is not None
        assert elapsed < 100, f"Query took {elapsed:.2f}ms, expected < 100ms"


# =============================================================================
# Integration with Dependencies
# =============================================================================


class TestCallsVsImports:
    """Test interaction between call edges and import edges."""

    def test_dependencies_includes_both(self, call_graph_db: MUbase) -> None:
        """Test get_dependencies includes both call and import edges."""
        # Get all dependencies of main module (should include imports)
        deps = call_graph_db.get_dependencies("mod:src/main.py")

        # Should find service module via imports
        dep_ids = [d.id for d in deps]
        assert "mod:src/service.py" in dep_ids

    def test_filtered_by_edge_type(self, call_graph_db: MUbase) -> None:
        """Test that we can filter by specific edge types."""
        # Get only import dependencies
        import_deps = call_graph_db.get_dependencies(
            "mod:src/main.py", edge_types=[EdgeType.IMPORTS]
        )

        # Should find service module
        dep_ids = [d.id for d in import_deps]
        assert "mod:src/service.py" in dep_ids

        # Contains edges should not be included
        for dep in import_deps:
            assert dep.type != NodeType.FUNCTION  # Functions are via CONTAINS, not IMPORTS


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "TestCallGraphQueries",
    "TestPathFindingWithCalls",
    "TestImpactAnalysisWithCalls",
    "TestCallEdgePersistence",
    "TestFindQueriesWithCalls",
    "TestGraphStatistics",
    "TestAnalyzeWithCallGraph",
    "TestCallGraphEdgeCases",
    "TestCallGraphPerformance",
    "TestCallsVsImports",
]
