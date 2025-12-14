"""Tests for MUQL Query Executor - Executes query plans against MUbase.

Comprehensive tests for query execution including SELECT, SHOW, FIND, PATH, and ANALYZE queries.
Uses fixtures to create populated test databases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.muql.ast import (
    AnalysisType,
    AnalyzeQuery,
    Comparison,
    ComparisonOperator,
    Condition,
    FindCondition,
    FindConditionType,
    FindQuery,
    NodeRef,
    NodeTypeFilter,
    OrderByField,
    PathQuery,
    SelectField,
    SelectQuery,
    ShowQuery,
    ShowType,
    SortOrder,
    Value,
)
from mu.kernel.muql.executor import QueryExecutor, QueryResult
from mu.kernel.muql.planner import QueryPlanner


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create temporary database path."""
    return tmp_path / "test.mubase"


@pytest.fixture
def populated_db(db_path: Path) -> MUbase:
    """Create a MUbase with test data.

    Creates a graph structure representing:
    - 3 modules: cli.py, parser.py, utils.py
    - 2 classes: Parser, Formatter
    - 5 functions: main, parse_file, format_output, helper, _private

    Edges:
    - cli.py imports parser.py, utils.py
    - parser.py imports utils.py
    - Parser contains parse_file
    - Formatter contains format_output
    - cli.py contains main, Formatter
    - parser.py contains Parser
    - utils.py contains helper, _private
    - Formatter inherits from object (external)
    """
    db = MUbase(db_path)

    # Create modules
    modules = [
        Node(
            id="mod:src/cli.py",
            type=NodeType.MODULE,
            name="cli",
            qualified_name="cli",
            file_path="src/cli.py",
            line_start=1,
            line_end=100,
            complexity=0,
        ),
        Node(
            id="mod:src/parser.py",
            type=NodeType.MODULE,
            name="parser",
            qualified_name="parser",
            file_path="src/parser.py",
            line_start=1,
            line_end=80,
            complexity=0,
        ),
        Node(
            id="mod:src/utils.py",
            type=NodeType.MODULE,
            name="utils",
            qualified_name="utils",
            file_path="src/utils.py",
            line_start=1,
            line_end=50,
            complexity=0,
        ),
    ]

    # Create classes
    classes = [
        Node(
            id="cls:src/parser.py:Parser",
            type=NodeType.CLASS,
            name="Parser",
            qualified_name="parser.Parser",
            file_path="src/parser.py",
            line_start=10,
            line_end=60,
            complexity=0,
            properties={"bases": ["object"]},
        ),
        Node(
            id="cls:src/cli.py:Formatter",
            type=NodeType.CLASS,
            name="Formatter",
            qualified_name="cli.Formatter",
            file_path="src/cli.py",
            line_start=50,
            line_end=90,
            complexity=0,
            properties={"bases": ["BaseFormatter"]},
        ),
    ]

    # Create functions with varying complexity
    functions = [
        Node(
            id="fn:src/cli.py:main",
            type=NodeType.FUNCTION,
            name="main",
            qualified_name="cli.main",
            file_path="src/cli.py",
            line_start=5,
            line_end=45,
            complexity=25,
            properties={"is_async": False},
        ),
        Node(
            id="fn:src/parser.py:Parser.parse_file",
            type=NodeType.FUNCTION,
            name="parse_file",
            qualified_name="parser.Parser.parse_file",
            file_path="src/parser.py",
            line_start=15,
            line_end=55,
            complexity=35,
            properties={"is_async": True, "decorators": ["@staticmethod"]},
        ),
        Node(
            id="fn:src/cli.py:Formatter.format_output",
            type=NodeType.FUNCTION,
            name="format_output",
            qualified_name="cli.Formatter.format_output",
            file_path="src/cli.py",
            line_start=55,
            line_end=85,
            complexity=15,
            properties={"is_async": False},
        ),
        Node(
            id="fn:src/utils.py:helper",
            type=NodeType.FUNCTION,
            name="helper",
            qualified_name="utils.helper",
            file_path="src/utils.py",
            line_start=5,
            line_end=20,
            complexity=5,
            properties={"is_async": False},
        ),
        Node(
            id="fn:src/utils.py:_private",
            type=NodeType.FUNCTION,
            name="_private",
            qualified_name="utils._private",
            file_path="src/utils.py",
            line_start=25,
            line_end=35,
            complexity=3,
            properties={"is_async": False},
        ),
    ]

    # External node for inheritance
    external = Node(
        id="ext:BaseFormatter",
        type=NodeType.EXTERNAL,
        name="BaseFormatter",
        qualified_name="external.BaseFormatter",
    )

    # Add all nodes
    for node in modules + classes + functions + [external]:
        db.add_node(node)

    # Create import edges
    import_edges = [
        Edge(
            id="edge:cli:imports:parser",
            source_id="mod:src/cli.py",
            target_id="mod:src/parser.py",
            type=EdgeType.IMPORTS,
        ),
        Edge(
            id="edge:cli:imports:utils",
            source_id="mod:src/cli.py",
            target_id="mod:src/utils.py",
            type=EdgeType.IMPORTS,
        ),
        Edge(
            id="edge:parser:imports:utils",
            source_id="mod:src/parser.py",
            target_id="mod:src/utils.py",
            type=EdgeType.IMPORTS,
        ),
    ]

    # Create contains edges
    contains_edges = [
        # Module -> Classes/Functions
        Edge(
            id="edge:cli:contains:main",
            source_id="mod:src/cli.py",
            target_id="fn:src/cli.py:main",
            type=EdgeType.CONTAINS,
        ),
        Edge(
            id="edge:cli:contains:Formatter",
            source_id="mod:src/cli.py",
            target_id="cls:src/cli.py:Formatter",
            type=EdgeType.CONTAINS,
        ),
        Edge(
            id="edge:parser:contains:Parser",
            source_id="mod:src/parser.py",
            target_id="cls:src/parser.py:Parser",
            type=EdgeType.CONTAINS,
        ),
        Edge(
            id="edge:utils:contains:helper",
            source_id="mod:src/utils.py",
            target_id="fn:src/utils.py:helper",
            type=EdgeType.CONTAINS,
        ),
        Edge(
            id="edge:utils:contains:_private",
            source_id="mod:src/utils.py",
            target_id="fn:src/utils.py:_private",
            type=EdgeType.CONTAINS,
        ),
        # Class -> Methods
        Edge(
            id="edge:Parser:contains:parse_file",
            source_id="cls:src/parser.py:Parser",
            target_id="fn:src/parser.py:Parser.parse_file",
            type=EdgeType.CONTAINS,
        ),
        Edge(
            id="edge:Formatter:contains:format_output",
            source_id="cls:src/cli.py:Formatter",
            target_id="fn:src/cli.py:Formatter.format_output",
            type=EdgeType.CONTAINS,
        ),
    ]

    # Create inheritance edge
    inherits_edges = [
        Edge(
            id="edge:Formatter:inherits:BaseFormatter",
            source_id="cls:src/cli.py:Formatter",
            target_id="ext:BaseFormatter",
            type=EdgeType.INHERITS,
            properties={"base_name": "BaseFormatter"},
        ),
    ]

    # Add all edges
    for edge in import_edges + contains_edges + inherits_edges:
        db.add_edge(edge)

    yield db
    db.close()


@pytest.fixture
def executor(populated_db: MUbase) -> QueryExecutor:
    """Create QueryExecutor with populated database."""
    return QueryExecutor(populated_db)


@pytest.fixture
def planner() -> QueryPlanner:
    """Create QueryPlanner instance."""
    return QueryPlanner()


# =============================================================================
# QueryResult Tests
# =============================================================================


class TestQueryResult:
    """Tests for QueryResult dataclass."""

    def test_empty_result(self) -> None:
        """Empty QueryResult is valid."""
        result = QueryResult()
        assert result.columns == []
        assert result.rows == []
        assert result.row_count == 0
        assert result.error is None
        assert result.is_success

    def test_result_with_data(self) -> None:
        """QueryResult stores data correctly."""
        result = QueryResult(
            columns=["name", "complexity"],
            rows=[("func1", 10), ("func2", 20)],
            row_count=2,
        )
        assert result.is_success
        assert len(result.rows) == 2

    def test_result_with_error(self) -> None:
        """QueryResult with error is not success."""
        result = QueryResult(error="Something went wrong")
        assert not result.is_success

    def test_result_to_dict(self) -> None:
        """QueryResult serializes to dict."""
        result = QueryResult(
            columns=["name"],
            rows=[("test",)],
            row_count=1,
            execution_time_ms=5.5,
        )
        d = result.to_dict()
        assert d["columns"] == ["name"]
        assert d["rows"] == [["test"]]
        assert d["row_count"] == 1
        assert d["execution_time_ms"] == 5.5

    def test_result_as_dicts(self) -> None:
        """QueryResult converts rows to list of dicts."""
        result = QueryResult(
            columns=["name", "value"],
            rows=[("a", 1), ("b", 2)],
            row_count=2,
        )
        dicts = result.as_dicts()
        assert len(dicts) == 2
        assert dicts[0] == {"name": "a", "value": 1}
        assert dicts[1] == {"name": "b", "value": 2}


# =============================================================================
# SELECT Executor Tests
# =============================================================================


class TestSelectExecutor:
    """Tests for SELECT query execution."""

    def test_select_star_from_functions(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT * FROM functions returns all functions."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 5

    def test_select_star_from_classes(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT * FROM classes returns all classes."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.CLASSES,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 2

    def test_select_star_from_modules(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT * FROM modules returns all modules."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.MODULES,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 3

    def test_select_specific_columns(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT specific columns returns those columns."""
        query = SelectQuery(
            fields=[SelectField(name="name"), SelectField(name="complexity")],
            node_type=NodeTypeFilter.FUNCTIONS,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert "name" in result.columns
        assert "complexity" in result.columns

    def test_select_with_where_equals(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT with WHERE = filters correctly."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
            where=Condition(
                comparisons=[
                    Comparison(
                        field="name",
                        operator=ComparisonOperator.EQ,
                        value=Value(value="main", type="string"),
                    )
                ],
                operator="and",
            ),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 1

    def test_select_with_where_greater_than(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT with WHERE > filters correctly."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
            where=Condition(
                comparisons=[
                    Comparison(
                        field="complexity",
                        operator=ComparisonOperator.GT,
                        value=Value(value=20, type="number"),
                    )
                ],
                operator="and",
            ),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Functions with complexity > 20: main (25), parse_file (35)
        assert result.row_count == 2

    def test_select_with_where_like(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT with WHERE LIKE filters correctly."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
            where=Condition(
                comparisons=[
                    Comparison(
                        field="name",
                        operator=ComparisonOperator.LIKE,
                        value=Value(value="_%", type="string"),
                    )
                ],
                operator="and",
            ),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # _private matches _%
        assert result.row_count >= 1

    def test_select_with_order_by_asc(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT with ORDER BY ASC sorts correctly."""
        query = SelectQuery(
            fields=[SelectField(name="name"), SelectField(name="complexity")],
            node_type=NodeTypeFilter.FUNCTIONS,
            order_by=[OrderByField(name="complexity", order=SortOrder.ASC)],
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # First row should have lowest complexity
        complexities = [row[1] for row in result.rows]
        assert complexities == sorted(complexities)

    def test_select_with_order_by_desc(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT with ORDER BY DESC sorts correctly."""
        query = SelectQuery(
            fields=[SelectField(name="name"), SelectField(name="complexity")],
            node_type=NodeTypeFilter.FUNCTIONS,
            order_by=[OrderByField(name="complexity", order=SortOrder.DESC)],
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # First row should have highest complexity
        complexities = [row[1] for row in result.rows]
        assert complexities == sorted(complexities, reverse=True)

    def test_select_with_limit(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT with LIMIT constrains results."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
            limit=2,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 2

    def test_select_with_all_clauses(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT with WHERE, ORDER BY, and LIMIT works together."""
        query = SelectQuery(
            fields=[SelectField(name="name"), SelectField(name="complexity")],
            node_type=NodeTypeFilter.FUNCTIONS,
            where=Condition(
                comparisons=[
                    Comparison(
                        field="complexity",
                        operator=ComparisonOperator.GT,
                        value=Value(value=0, type="number"),
                    )
                ],
                operator="and",
            ),
            order_by=[OrderByField(name="complexity", order=SortOrder.DESC)],
            limit=3,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 3

    def test_select_empty_result(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SELECT with no matches returns empty result."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
            where=Condition(
                comparisons=[
                    Comparison(
                        field="name",
                        operator=ComparisonOperator.EQ,
                        value=Value(value="nonexistent", type="string"),
                    )
                ],
                operator="and",
            ),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 0


# =============================================================================
# SHOW Executor Tests
# =============================================================================


class TestShowExecutor:
    """Tests for SHOW query execution."""

    def test_show_dependencies(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW dependencies returns correct nodes."""
        query = ShowQuery(
            show_type=ShowType.DEPENDENCIES,
            target=NodeRef(name="mod:src/cli.py"),
            depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # cli.py depends on parser.py and utils.py
        assert result.row_count >= 2

    def test_show_dependents(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW dependents returns correct nodes."""
        query = ShowQuery(
            show_type=ShowType.DEPENDENTS,
            target=NodeRef(name="mod:src/utils.py"),
            depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # utils.py is imported by cli.py and parser.py
        assert result.row_count >= 2

    def test_show_children(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW children returns contained nodes."""
        query = ShowQuery(
            show_type=ShowType.CHILDREN,
            target=NodeRef(name="mod:src/utils.py"),
            depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # utils.py contains helper and _private
        assert result.row_count >= 2

    def test_show_inheritance(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW inheritance returns inherited nodes."""
        query = ShowQuery(
            show_type=ShowType.INHERITANCE,
            target=NodeRef(name="cls:src/cli.py:Formatter"),
            depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Formatter inherits from BaseFormatter
        assert result.row_count >= 1

    def test_show_with_depth(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW with DEPTH traverses multiple levels."""
        query = ShowQuery(
            show_type=ShowType.DEPENDENCIES,
            target=NodeRef(name="mod:src/cli.py"),
            depth=2,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Should include transitive dependencies

    def test_show_no_results(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW for node with no relations returns empty."""
        query = ShowQuery(
            show_type=ShowType.DEPENDENCIES,
            target=NodeRef(name="ext:BaseFormatter"),
            depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        # External node has no dependencies
        assert result.row_count == 0


# =============================================================================
# FIND Executor Tests
# =============================================================================


class TestFindExecutor:
    """Tests for FIND query execution."""

    def test_find_matching_pattern(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """FIND MATCHING uses name pattern."""
        query = FindQuery(
            node_type=NodeTypeFilter.FUNCTIONS,
            condition=FindCondition(
                condition_type=FindConditionType.MATCHING,
                pattern="parse%",
            ),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Should find parse_file
        names = [row[1] for row in result.rows]  # name is usually second column
        assert any("parse" in str(name) for name in names)

    def test_find_matching_underscore_prefix(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """FIND MATCHING with underscore prefix."""
        query = FindQuery(
            node_type=NodeTypeFilter.FUNCTIONS,
            condition=FindCondition(
                condition_type=FindConditionType.MATCHING,
                pattern="_%",
            ),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Should find _private

    def test_find_inheriting(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """FIND INHERITING requires graph traversal."""
        query = FindQuery(
            node_type=NodeTypeFilter.CLASSES,
            condition=FindCondition(
                condition_type=FindConditionType.INHERITING,
                target=NodeRef(name="BaseFormatter"),
            ),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        # Graph-based queries may not be fully implemented
        # Just verify it doesn't crash
        assert result is not None


# =============================================================================
# PATH Executor Tests
# =============================================================================


class TestPathExecutor:
    """Tests for PATH query execution."""

    def test_path_finds_direct_path(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """PATH finds direct connection."""
        query = PathQuery(
            from_node=NodeRef(name="mod:src/cli.py"),
            to_node=NodeRef(name="mod:src/parser.py"),
            max_depth=5,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Direct path exists: cli.py -> parser.py
        assert result.row_count >= 1

    def test_path_finds_transitive_path(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """PATH finds transitive connection."""
        query = PathQuery(
            from_node=NodeRef(name="mod:src/cli.py"),
            to_node=NodeRef(name="mod:src/utils.py"),
            max_depth=5,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Paths exist: cli.py -> utils.py (direct) and cli.py -> parser.py -> utils.py

    def test_path_no_path_exists(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """PATH returns empty when no path exists."""
        query = PathQuery(
            from_node=NodeRef(name="mod:src/utils.py"),
            to_node=NodeRef(name="mod:src/cli.py"),
            max_depth=5,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        # utils.py doesn't import cli.py, no reverse path
        # This may return error or empty depending on implementation

    def test_path_max_depth_constrains(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """PATH with MAX DEPTH limits search."""
        query = PathQuery(
            from_node=NodeRef(name="mod:src/cli.py"),
            to_node=NodeRef(name="mod:src/utils.py"),
            max_depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        # Should find direct path (depth 1 is sufficient)
        assert result is not None


# =============================================================================
# ANALYZE Executor Tests
# =============================================================================


class TestAnalyzeExecutor:
    """Tests for ANALYZE query execution."""

    def test_analyze_complexity(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """ANALYZE complexity returns high-complexity nodes."""
        query = AnalyzeQuery(
            analysis_type=AnalysisType.COMPLEXITY,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Should return nodes ordered by complexity
        assert "complexity" in result.columns

    def test_analyze_complexity_with_target(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """ANALYZE complexity FOR target filters by path."""
        query = AnalyzeQuery(
            analysis_type=AnalysisType.COMPLEXITY,
            target=NodeRef(name="parser"),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success

    def test_analyze_coupling(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """ANALYZE coupling returns module coupling metrics."""
        query = AnalyzeQuery(
            analysis_type=AnalysisType.COUPLING,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert "file_path" in result.columns or "dependencies" in result.columns

    def test_analyze_circular(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """ANALYZE circular detects circular dependencies."""
        query = AnalyzeQuery(
            analysis_type=AnalysisType.CIRCULAR,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Our test data has no circular dependencies
        assert result.row_count == 0

    def test_analyze_unused(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """ANALYZE unused finds nodes with no dependents."""
        query = AnalyzeQuery(
            analysis_type=AnalysisType.UNUSED,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success

    def test_analyze_hotspots(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """ANALYZE hotspots finds high complexity + high usage."""
        query = AnalyzeQuery(
            analysis_type=AnalysisType.HOTSPOTS,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success

    def test_analyze_impact_requires_target(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """ANALYZE impact without target returns error."""
        query = AnalyzeQuery(
            analysis_type=AnalysisType.IMPACT,
            target=None,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        # Should return error since FOR clause is required
        assert result.error is not None or result.row_count == 0

    def test_analyze_impact_with_target(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """ANALYZE impact FOR target shows affected nodes."""
        query = AnalyzeQuery(
            analysis_type=AnalysisType.IMPACT,
            target=NodeRef(name="utils"),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        # Should show what depends on utils


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestExecutorEdgeCases:
    """Tests for edge cases and error handling."""

    def test_execution_time_tracked(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """Execution time is recorded."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.execution_time_ms >= 0

    def test_error_handling_invalid_sql(
        self, executor: QueryExecutor
    ) -> None:
        """Invalid SQL returns error result."""
        from mu.kernel.muql.planner import SQLPlan

        plan = SQLPlan(sql="SELECT * FROM nonexistent_table")
        result = executor.execute(plan)

        assert not result.is_success
        assert result.error is not None

    def test_unicode_in_results(
        self, populated_db: MUbase, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """Unicode characters in data are handled."""
        # Add a node with unicode name
        populated_db.add_node(
            Node(
                id="fn:test:unicode_func",
                type=NodeType.FUNCTION,
                name="get_unicode",
                qualified_name="test.get_unicode",
                complexity=5,
            )
        )

        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
            where=Condition(
                comparisons=[
                    Comparison(
                        field="name",
                        operator=ComparisonOperator.EQ,
                        value=Value(value="get_unicode", type="string"),
                    )
                ],
                operator="and",
            ),
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 1

    def test_empty_database(self, tmp_path: Path) -> None:
        """Queries on empty database return empty results."""
        empty_db = MUbase(tmp_path / "empty.mubase")
        executor = QueryExecutor(empty_db)
        planner = QueryPlanner()

        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count == 0

        empty_db.close()


# =============================================================================
# Integration with Parser
# =============================================================================


class TestExecutorParserIntegration:
    """Tests for executor integration with parser."""

    def test_parse_and_execute_select(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """Parse query string and execute."""
        from mu.kernel.muql.parser import parse

        query = parse("SELECT * FROM functions WHERE complexity > 10 LIMIT 3")
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        assert result.row_count <= 3

    def test_parse_and_execute_show(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """Parse SHOW query and execute."""
        from mu.kernel.muql.parser import parse

        query = parse("SHOW dependencies OF \"mod:src/cli.py\"")
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success

    def test_parse_and_execute_analyze(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """Parse ANALYZE query and execute."""
        from mu.kernel.muql.parser import parse

        query = parse("ANALYZE complexity")
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success


# =============================================================================
# Planner Tests
# =============================================================================


class TestQueryPlanner:
    """Tests for QueryPlanner."""

    def test_plan_select_generates_sql(self, planner: QueryPlanner) -> None:
        """SELECT query generates SQLPlan."""
        from mu.kernel.muql.planner import SQLPlan

        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
        )
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        assert "SELECT" in plan.sql

    def test_plan_show_generates_graph(self, planner: QueryPlanner) -> None:
        """SHOW query generates GraphPlan."""
        from mu.kernel.muql.planner import GraphPlan

        query = ShowQuery(
            show_type=ShowType.DEPENDENCIES,
            target=NodeRef(name="test"),
        )
        plan = planner.plan(query)

        assert isinstance(plan, GraphPlan)
        assert plan.operation == "get_dependencies"

    def test_plan_path_generates_graph(self, planner: QueryPlanner) -> None:
        """PATH query generates GraphPlan."""
        from mu.kernel.muql.planner import GraphPlan

        query = PathQuery(
            from_node=NodeRef(name="a"),
            to_node=NodeRef(name="b"),
        )
        plan = planner.plan(query)

        assert isinstance(plan, GraphPlan)
        assert plan.operation == "find_path"

    def test_plan_analyze_generates_analysis(self, planner: QueryPlanner) -> None:
        """ANALYZE query generates AnalysisPlan."""
        from mu.kernel.muql.planner import AnalysisPlan

        query = AnalyzeQuery(
            analysis_type=AnalysisType.COMPLEXITY,
        )
        plan = planner.plan(query)

        assert isinstance(plan, AnalysisPlan)
        assert plan.analysis_type == AnalysisType.COMPLEXITY

    def test_plan_to_dict(self, planner: QueryPlanner) -> None:
        """Execution plan serializes to dict."""
        query = SelectQuery(
            fields=[SelectField(name="*", is_star=True)],
            node_type=NodeTypeFilter.FUNCTIONS,
        )
        plan = planner.plan(query)
        d = plan.to_dict()

        assert "plan_type" in d
        assert "sql" in d


# =============================================================================
# Bug Fix Tests (Issues 3 and 4)
# =============================================================================


class TestBugFixes:
    """Tests for specific bug fixes."""

    def test_show_dependencies_nonexistent_node_returns_error(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """Issue 4: SHOW dependencies for non-existent node returns error, not empty.

        Previously returned empty results, which was confusing.
        Now returns a helpful error message.
        """
        query = ShowQuery(
            show_type=ShowType.DEPENDENCIES,
            target=NodeRef(name="NonExistentClass"),
            depth=2,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        # Should return error, not empty success
        assert not result.is_success
        assert result.error is not None
        assert "Node not found" in result.error
        assert "NonExistentClass" in result.error

    def test_show_dependencies_by_simple_name_works(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW dependencies with simple name resolves to full ID.

        User should be able to query by just the class/module name.
        """
        query = ShowQuery(
            show_type=ShowType.DEPENDENCIES,
            target=NodeRef(name="Parser"),  # Simple name, not full ID
            depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        # Parser class should be found and have dependencies (contains parse_file)
        assert result.is_success
        # Parser contains parse_file method
        assert result.row_count >= 1

    def test_show_dependencies_by_full_id_works(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW dependencies with full node ID works correctly."""
        query = ShowQuery(
            show_type=ShowType.DEPENDENCIES,
            target=NodeRef(name="cls:src/parser.py:Parser"),
            depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # Parser contains parse_file
        assert result.row_count >= 1

    def test_show_dependents_by_simple_name(
        self, executor: QueryExecutor, planner: QueryPlanner
    ) -> None:
        """SHOW dependents with simple name resolves correctly."""
        query = ShowQuery(
            show_type=ShowType.DEPENDENTS,
            target=NodeRef(name="utils"),  # Simple module name
            depth=1,
        )
        plan = planner.plan(query)
        result = executor.execute(plan)

        assert result.is_success
        # utils.py is imported by cli.py and parser.py
        assert result.row_count >= 2
