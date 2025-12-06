"""MUQL Query Executor - Executes query plans against MUbase.

The executor takes execution plans and runs them against a MUbase
database, returning QueryResult objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mu.kernel.muql.planner import (
    AnalysisPlan,
    ExecutionPlan,
    GraphPlan,
    SQLPlan,
)
from mu.kernel.schema import EdgeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


# =============================================================================
# Query Result
# =============================================================================


@dataclass
class QueryResult:
    """Result of executing a MUQL query."""

    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    row_count: int = 0
    error: str | None = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": [list(row) for row in self.rows],
            "row_count": self.row_count,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }

    @property
    def is_success(self) -> bool:
        """Check if query executed successfully."""
        return self.error is None

    def as_dicts(self) -> list[dict[str, Any]]:
        """Convert rows to list of dicts."""
        return [dict(zip(self.columns, row, strict=False)) for row in self.rows]


# =============================================================================
# Query Executor
# =============================================================================


class QueryExecutor:
    """Executes MUQL query plans against a MUbase database."""

    def __init__(self, db: MUbase) -> None:
        """Initialize executor with database connection.

        Args:
            db: The MUbase database to query.
        """
        self._db = db

    def execute(self, plan: ExecutionPlan) -> QueryResult:
        """Execute a query plan and return results.

        Args:
            plan: The execution plan to execute.

        Returns:
            QueryResult with columns, rows, and metadata.
        """
        import time

        start = time.perf_counter()
        try:
            if isinstance(plan, SQLPlan):
                result = self._execute_sql(plan)
            elif isinstance(plan, GraphPlan):
                result = self._execute_graph(plan)
            elif isinstance(plan, AnalysisPlan):
                result = self._execute_analysis(plan)
            else:
                result = QueryResult(error=f"Unknown plan type: {type(plan)}")
        except Exception as e:
            result = QueryResult(error=str(e))

        result.execution_time_ms = (time.perf_counter() - start) * 1000
        return result

    # -------------------------------------------------------------------------
    # SQL Execution
    # -------------------------------------------------------------------------

    def _execute_sql(self, plan: SQLPlan) -> QueryResult:
        """Execute SQL plan using DuckDB."""
        try:
            # Get raw connection for parameterized queries
            conn = self._db.conn

            # Execute with parameters
            if plan.parameters:
                cursor = conn.execute(plan.sql, plan.parameters)
            else:
                cursor = conn.execute(plan.sql)

            # Fetch results
            rows = cursor.fetchall()
            columns = plan.columns if plan.columns else []

            # Try to get column names from cursor if not provided
            if not columns and cursor.description:
                columns = [desc[0] for desc in cursor.description]

            return QueryResult(
                columns=columns,
                rows=[tuple(row) for row in rows],
                row_count=len(rows),
            )
        except Exception as e:
            return QueryResult(error=f"SQL execution error: {e}")

    # -------------------------------------------------------------------------
    # Graph Execution
    # -------------------------------------------------------------------------

    def _execute_graph(self, plan: GraphPlan) -> QueryResult:
        """Execute graph traversal plan using MUbase methods."""
        operation = plan.operation
        target = plan.target_node
        depth = plan.depth

        try:
            if operation == "get_dependencies":
                nodes = self._db.get_dependencies(target, depth=depth)
                return self._nodes_to_result(nodes, "Dependencies")

            elif operation == "get_dependents":
                nodes = self._db.get_dependents(target, depth=depth)
                return self._nodes_to_result(nodes, "Dependents")

            elif operation == "get_children":
                nodes = self._db.get_children(target)
                return self._nodes_to_result(nodes, "Children")

            elif operation == "get_parents":
                # Use reverse of children lookup
                # This would need to be implemented in MUbase
                return self._not_implemented("get_parents")

            elif operation == "get_callers":
                # Callers = dependents (no specific CALLS edge type in MUbase yet)
                nodes = self._db.get_dependents(target, depth=depth)
                return self._nodes_to_result(nodes, "Callers")

            elif operation == "get_callees":
                # Callees = dependencies (no specific CALLS edge type in MUbase yet)
                nodes = self._db.get_dependencies(target, depth=depth)
                return self._nodes_to_result(nodes, "Callees")

            elif operation == "get_inheritance":
                # Inheritance = dependencies with INHERITS edge type
                nodes = self._db.get_dependencies(
                    target, depth=depth, edge_types=[EdgeType.INHERITS]
                )
                return self._nodes_to_result(nodes, "Inheritance")

            elif operation == "get_implementations":
                # Implementations = dependents with INHERITS edge type
                nodes = self._db.get_dependents(target, depth=depth, edge_types=[EdgeType.INHERITS])
                return self._nodes_to_result(nodes, "Implementations")

            elif operation == "find_path":
                to_node = plan.extra_args.get("to_node", "")
                # edge_types filtering not yet implemented in find_path
                path = self._db.find_path(target, to_node, max_depth=depth)
                return self._path_to_result(path)

            elif operation.startswith("find_"):
                # Graph-based FIND queries
                return self._execute_find_graph(plan)

            else:
                return self._not_implemented(operation)

        except Exception as e:
            return QueryResult(error=f"Graph execution error: {e}")

    def _nodes_to_result(self, nodes: list[Any], label: str = "Results") -> QueryResult:
        """Convert list of Node objects to QueryResult."""
        if not nodes:
            return QueryResult(
                columns=["id", "name", "type", "path"],
                rows=[],
                row_count=0,
            )

        rows = []
        for node in nodes:
            if hasattr(node, "id"):
                rows.append((node.id, node.name, node.type.value, node.file_path))
            elif isinstance(node, dict):
                rows.append(
                    (
                        node.get("id", ""),
                        node.get("name", ""),
                        node.get("type", ""),
                        node.get("path", node.get("file_path", "")),
                    )
                )
            else:
                rows.append((str(node), "", "", ""))

        return QueryResult(
            columns=["id", "name", "type", "path"],
            rows=rows,
            row_count=len(rows),
        )

    def _path_to_result(self, path: list[str] | None) -> QueryResult:
        """Convert path list to QueryResult."""
        if path is None:
            return QueryResult(
                columns=["step", "node"],
                rows=[],
                row_count=0,
                error="No path found",
            )

        rows = [(i, node) for i, node in enumerate(path)]
        return QueryResult(
            columns=["step", "node"],
            rows=rows,
            row_count=len(rows),
        )

    def _execute_find_graph(self, plan: GraphPlan) -> QueryResult:
        """Execute graph-based FIND queries."""
        operation = plan.operation
        target = plan.target_node
        # node_type available in plan.extra_args.get("node_type") for filtering

        # These would need specific MUbase methods
        # For now, return not implemented
        return self._not_implemented(f"{operation} for {target}")

    def _not_implemented(self, operation: str) -> QueryResult:
        """Return not implemented error."""
        return QueryResult(error=f"Operation not implemented: {operation}")

    # -------------------------------------------------------------------------
    # Analysis Execution
    # -------------------------------------------------------------------------

    def _execute_analysis(self, plan: AnalysisPlan) -> QueryResult:
        """Execute built-in analysis queries."""
        from mu.kernel.muql.ast import AnalysisType

        analysis_type = plan.analysis_type
        target = plan.target_node

        try:
            if analysis_type == AnalysisType.COMPLEXITY:
                return self._analyze_complexity(target)
            elif analysis_type == AnalysisType.HOTSPOTS:
                return self._analyze_hotspots(target)
            elif analysis_type == AnalysisType.CIRCULAR:
                return self._analyze_circular(target)
            elif analysis_type == AnalysisType.UNUSED:
                return self._analyze_unused(target)
            elif analysis_type == AnalysisType.COUPLING:
                return self._analyze_coupling(target)
            elif analysis_type == AnalysisType.COHESION:
                return self._analyze_cohesion(target)
            elif analysis_type == AnalysisType.IMPACT:
                return self._analyze_impact(target)
            else:
                return self._not_implemented(f"analysis: {analysis_type.value}")
        except Exception as e:
            return QueryResult(error=f"Analysis error: {e}")

    def _analyze_complexity(self, target: str | None) -> QueryResult:
        """Analyze complexity distribution."""
        # Find high-complexity nodes
        if target:
            sql = """
                SELECT name, type, path, complexity
                FROM nodes
                WHERE complexity > 0 AND path LIKE '%' || ? || '%'
                ORDER BY complexity DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql, [target])
        else:
            sql = """
                SELECT name, type, path, complexity
                FROM nodes
                WHERE complexity > 0
                ORDER BY complexity DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql)

        rows = cursor.fetchall()

        return QueryResult(
            columns=["name", "type", "path", "complexity"],
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
        )

    def _analyze_hotspots(self, target: str | None) -> QueryResult:
        """Find hotspots (high complexity + high fan-in)."""
        # Hotspots are nodes with high complexity and many dependents
        if target:
            sql = """
                SELECT n.name, n.type, n.path, n.complexity,
                       COUNT(DISTINCT e.source_id) as dependents
                FROM nodes n
                LEFT JOIN edges e ON e.target_id = n.id
                WHERE n.complexity > 10 AND n.path LIKE '%' || ? || '%'
                GROUP BY n.id, n.name, n.type, n.path, n.complexity
                ORDER BY n.complexity * COUNT(DISTINCT e.source_id) DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql, [target])
        else:
            sql = """
                SELECT n.name, n.type, n.path, n.complexity,
                       COUNT(DISTINCT e.source_id) as dependents
                FROM nodes n
                LEFT JOIN edges e ON e.target_id = n.id
                WHERE n.complexity > 10
                GROUP BY n.id, n.name, n.type, n.path, n.complexity
                ORDER BY n.complexity * COUNT(DISTINCT e.source_id) DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql)

        rows = cursor.fetchall()

        return QueryResult(
            columns=["name", "type", "path", "complexity", "dependents"],
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
        )

    def _analyze_circular(self, target: str | None) -> QueryResult:
        """Detect circular dependencies."""
        # This is a simplified check - real circular detection needs graph traversal
        sql = """
            SELECT DISTINCT e1.source_id, e1.target_id
            FROM edges e1
            JOIN edges e2 ON e1.source_id = e2.target_id AND e1.target_id = e2.source_id
            WHERE e1.type = 'imports'
            LIMIT 50
        """

        cursor = self._db.conn.execute(sql)
        rows = cursor.fetchall()

        return QueryResult(
            columns=["source", "target"],
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
        )

    def _analyze_unused(self, target: str | None) -> QueryResult:
        """Find potentially unused code (no dependents)."""
        if target:
            sql = """
                SELECT n.name, n.type, n.path
                FROM nodes n
                LEFT JOIN edges e ON e.target_id = n.id
                WHERE e.id IS NULL AND n.type IN ('function', 'class')
                      AND n.path LIKE '%' || ? || '%'
                ORDER BY n.path, n.name
                LIMIT 50
            """
            cursor = self._db.conn.execute(sql, [target])
        else:
            sql = """
                SELECT n.name, n.type, n.path
                FROM nodes n
                LEFT JOIN edges e ON e.target_id = n.id
                WHERE e.id IS NULL AND n.type IN ('function', 'class')
                ORDER BY n.path, n.name
                LIMIT 50
            """
            cursor = self._db.conn.execute(sql)

        rows = cursor.fetchall()

        return QueryResult(
            columns=["name", "type", "path"],
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
        )

    def _analyze_coupling(self, target: str | None) -> QueryResult:
        """Analyze module coupling (external dependencies)."""
        if target:
            sql = """
                SELECT n.path, COUNT(DISTINCT e.target_id) as dependencies
                FROM nodes n
                JOIN edges e ON e.source_id = n.id
                WHERE n.type = 'module' AND e.type = 'imports'
                      AND n.path LIKE '%' || ? || '%'
                GROUP BY n.path
                ORDER BY dependencies DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql, [target])
        else:
            sql = """
                SELECT n.path, COUNT(DISTINCT e.target_id) as dependencies
                FROM nodes n
                JOIN edges e ON e.source_id = n.id
                WHERE n.type = 'module' AND e.type = 'imports'
                GROUP BY n.path
                ORDER BY dependencies DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql)

        rows = cursor.fetchall()

        return QueryResult(
            columns=["path", "dependencies"],
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
        )

    def _analyze_cohesion(self, target: str | None) -> QueryResult:
        """Analyze module cohesion (internal vs external calls)."""
        # Simplified cohesion metric
        sql = """
            SELECT n.path,
                   COUNT(DISTINCT c.id) as children,
                   COUNT(DISTINCT e.id) as internal_edges
            FROM nodes n
            JOIN edges c_edge ON c_edge.source_id = n.id AND c_edge.type = 'contains'
            JOIN nodes c ON c.id = c_edge.target_id
            LEFT JOIN edges e ON e.source_id = c.id AND e.target_id IN (
                SELECT c2.id FROM edges c2_edge
                JOIN nodes c2 ON c2.id = c2_edge.target_id
                WHERE c2_edge.source_id = n.id AND c2_edge.type = 'contains'
            )
            WHERE n.type = 'module'
            GROUP BY n.path
            HAVING COUNT(DISTINCT c.id) > 1
            ORDER BY CAST(COUNT(DISTINCT e.id) AS FLOAT) / COUNT(DISTINCT c.id) DESC
            LIMIT 20
        """

        try:
            cursor = self._db.conn.execute(sql)
            rows = cursor.fetchall()

            return QueryResult(
                columns=["path", "children", "internal_edges"],
                rows=[tuple(row) for row in rows],
                row_count=len(rows),
            )
        except Exception as e:
            # Fallback for simpler query - include error for debugging
            return QueryResult(
                columns=["path", "children", "internal_edges"],
                rows=[],
                row_count=0,
                error=f"Cohesion analysis failed: {e}",
            )

    def _analyze_impact(self, target: str | None) -> QueryResult:
        """Analyze impact of a node (transitive dependents)."""
        if not target:
            return QueryResult(error="ANALYZE IMPACT requires FOR clause")

        # Find all nodes that transitively depend on target
        try:
            # First find the node by name
            nodes = self._db.find_by_name(target)
            if not nodes:
                # Try pattern match
                nodes = self._db.find_by_name(f"%{target}%")
            if not nodes:
                return QueryResult(error=f"Node not found: {target}")

            node = nodes[0]

            # Get dependents recursively
            dependents = self._db.get_dependents(node.id, depth=5)

            rows = []
            for dep in dependents:
                rows.append((dep.id, dep.name, dep.type.value, dep.file_path))

            return QueryResult(
                columns=["id", "name", "type", "path"],
                rows=rows,
                row_count=len(rows),
            )
        except Exception as e:
            return QueryResult(error=f"Impact analysis error: {e}")


# =============================================================================
# Convenience Functions
# =============================================================================


def execute_plan(db: MUbase, plan: ExecutionPlan) -> QueryResult:
    """Execute a plan using a new executor instance.

    Args:
        db: The MUbase database.
        plan: The execution plan.

    Returns:
        QueryResult with results or error.
    """
    executor = QueryExecutor(db)
    return executor.execute(plan)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "QueryResult",
    "QueryExecutor",
    "execute_plan",
]
