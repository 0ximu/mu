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
    TemporalPlan,
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
    warning: str | None = None
    message: str | None = None  # Informational message (not an error)
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        result = {
            "columns": self.columns,
            "rows": [list(row) for row in self.rows],
            "row_count": self.row_count,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }
        if self.warning:
            result["warning"] = self.warning
        if self.message:
            result["message"] = self.message
        return result

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
            elif isinstance(plan, TemporalPlan):
                result = self._execute_temporal(plan)
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

    def _resolve_node_id(self, target: str) -> str | None:
        """Resolve a node name/reference to a full node ID.

        The target could be:
        - A full node ID: mod:src/cli.py, cls:src/kernel/mubase.py:MUbase
        - A simple name: MUbase, TransactionService
        - A qualified name: kernel.mubase.MUbase
        - A file path: src/auth.py, backend/src/file.py

        Returns the full node ID if found, otherwise returns None.
        """
        # If target already looks like a full node ID, verify it exists
        if target.startswith(("mod:", "cls:", "fn:", "ext:")):
            node = self._db.get_node(target)
            if node:
                return target
            # If not found directly, try suffix match for mod: IDs
            if target.startswith("mod:"):
                path_part = target[4:]  # Remove "mod:" prefix
                result = self._db.execute(
                    "SELECT id FROM nodes WHERE file_path LIKE ? AND type = 'module' LIMIT 1",
                    [f"%{path_part}"],
                )
                if result:
                    return str(result[0][0])
            # Fall through to try name-based lookup

        # Check if it looks like a file path
        looks_like_path = (
            "/" in target
            or "\\" in target
            or target.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs"))
        )

        if looks_like_path:
            # Normalize path separators
            normalized_path = target.replace("\\", "/")

            # Try exact file_path match via SQL
            result = self._db.execute(
                "SELECT id FROM nodes WHERE file_path = ? AND type = 'module' LIMIT 1",
                [normalized_path],
            )
            if result:
                return str(result[0][0])

            # Try matching with path suffix (handles relative vs absolute paths)
            result = self._db.execute(
                "SELECT id FROM nodes WHERE file_path LIKE ? AND type = 'module' LIMIT 1",
                [f"%{normalized_path}"],
            )
            if result:
                return str(result[0][0])

            # Try constructing the node ID directly
            possible_id = f"mod:{normalized_path}"
            if self._db.get_node(possible_id):
                return possible_id

        # Try to find by exact name match
        nodes = self._db.find_by_name(target)
        if nodes:
            return nodes[0].id

        # Try case-insensitive name match
        try:
            result = self._db.execute(
                "SELECT id FROM nodes WHERE LOWER(name) = LOWER(?) LIMIT 1",
                [target],
            )
            if result:
                return str(result[0][0])
        except Exception:
            pass

        # Try pattern match
        nodes = self._db.find_by_name(f"%{target}%")
        if nodes:
            # Prefer exact name matches
            for node in nodes:
                if node.name == target:
                    return node.id
            # Fall back to first match
            return nodes[0].id

        # Return None if no match found
        return None

    def _execute_graph(self, plan: GraphPlan) -> QueryResult:
        """Execute graph traversal plan using MUbase methods or GraphManager."""
        operation = plan.operation
        depth = plan.depth

        # Resolve target node ID (most operations require a target)
        target: str = ""
        if plan.target_node:
            resolved = self._resolve_node_id(plan.target_node)
            if resolved is None:
                # Node not found - return helpful error message
                # Note: We don't embed user input in SQL suggestions to avoid confusion
                return QueryResult(
                    error=f"Node not found: '{plan.target_node}'. "
                    f"Try using a full node ID (e.g., cls:path/to/file.py:ClassName) "
                    f"or verify the node exists with: SELECT * FROM nodes WHERE name LIKE '%<name>%'"
                )
            target = resolved

        try:
            # petgraph-backed operations (use GraphManager)
            if operation == "find_cycles":
                return self._execute_find_cycles(plan)

            elif operation == "get_impact":
                return self._execute_impact(plan, target)

            elif operation == "get_ancestors":
                return self._execute_ancestors(plan, target)

            # MUbase-backed operations (SQL/DuckDB)
            elif operation == "get_dependencies":
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
                to_node_raw = plan.extra_args.get("to_node", "")
                # Resolve the to_node as well (critical for path finding)
                resolved_to = self._resolve_node_id(to_node_raw) if to_node_raw else None
                to_node = resolved_to or ""
                if to_node_raw and not to_node:
                    return QueryResult(
                        error=f"Destination node not found: '{to_node_raw}'. "
                        f"Try using a full node ID or verify the node exists with: "
                        f"SELECT * FROM nodes WHERE name LIKE '%<name>%'"
                    )
                # Use GraphManager for path finding if available
                return self._execute_path(plan, target, to_node, depth)

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
        target = self._resolve_node_id(plan.target_node) if plan.target_node else ""
        node_type = plan.extra_args.get("node_type")
        limit = plan.extra_args.get("limit", 100)

        if not target:
            # Node not found - return empty result with helpful suggestion instead of error
            # Note: We don't embed user input in SQL suggestions for safety
            return QueryResult(
                columns=["id", "name", "type", "path"],
                rows=[],
                row_count=0,
                message=f"No node found matching '{plan.target_node}'. "
                f"Try: SELECT * FROM nodes WHERE name LIKE '%<name>%'",
            )

        try:
            gm = self._get_graph_manager()

            if not gm.has_node(target):
                # Node resolved to an ID but not in graph - return empty result
                return QueryResult(
                    columns=["id", "name", "type", "path"],
                    rows=[],
                    row_count=0,
                    message=f"Node '{plan.target_node}' not found in call graph.",
                )

            result_ids: list[str] = []

            if operation == "find_calling":
                # Find functions that call the target
                # Uses CALLS edges from call graph extraction (Rust parser)
                result_ids = gm.ancestors(target, ["calls"])
            elif operation == "find_called_by":
                # Find functions called by target
                # Uses CALLS edges from call graph extraction (Rust parser)
                result_ids = gm.impact(target, ["calls"])
            elif operation == "find_importing":
                # Find modules that import the target
                # If A imports B, edge is A --imports--> B (A is source, B is target)
                # We want to find A given B (target), so we need ancestors of target
                result_ids = gm.ancestors(target, ["imports"])
            elif operation == "find_imported_by":
                # Find modules imported by target
                # If X imports B, edge is X --imports--> B (X is source, B is target)
                # We want to find B given X (target), so we need impact of target
                result_ids = gm.impact(target, ["imports"])
            elif operation == "find_inheriting":
                # Find classes that inherit from target
                # If A inherits B, edge is A --inherits--> B (A is source/child, B is target/parent)
                # We want to find A given B (target), so we need ancestors of target
                result_ids = gm.ancestors(target, ["inherits"])
            elif operation == "find_implementing":
                # Find classes that target inherits from (what does target implement/extend)
                # If X inherits B, edge is X --inherits--> B (X is source, B is target)
                # We want to find B given X (target), so we need impact of target
                result_ids = gm.impact(target, ["inherits"])
            elif operation == "find_mutating":
                # Find functions that mutate target state - fallback to generic impact
                result_ids = gm.impact(target)
            elif operation == "find_similar":
                # Semantic search - not yet implemented
                return self._not_implemented("find_similar (requires embeddings)")
            else:
                return self._not_implemented(f"{operation}")

            # Filter by node_type if specified
            if node_type and result_ids:
                filtered_ids = []
                for nid in result_ids:
                    node = self._db.get_node(nid)
                    if node and node.type.value == node_type:
                        filtered_ids.append(nid)
                result_ids = filtered_ids

            # Apply limit
            result_ids = result_ids[:limit]

            # Convert to result format with full node info
            rows = []
            for nid in result_ids:
                node = self._db.get_node(nid)
                if node:
                    rows.append((node.id, node.name, node.type.value, node.file_path))
                else:
                    rows.append((nid, "", "", ""))

            return QueryResult(
                columns=["id", "name", "type", "path"],
                rows=rows,
                row_count=len(rows),
            )

        except ImportError as e:
            return QueryResult(error=f"Rust core not available: {e}")
        except Exception as e:
            return QueryResult(error=f"Graph query error: {e}")

    def _not_implemented(self, operation: str) -> QueryResult:
        """Return not implemented error."""
        return QueryResult(error=f"Operation not implemented: {operation}")

    # -------------------------------------------------------------------------
    # GraphManager-backed Operations (petgraph)
    # -------------------------------------------------------------------------

    def _get_graph_manager(self) -> Any:
        """Get GraphManager instance, loading from DuckDB if needed.

        Returns:
            GraphManager with loaded graph data.

        Raises:
            ImportError: If mu._core is not available.
        """
        from mu.kernel.graph import GraphManager

        gm = GraphManager(self._db.conn)
        gm.load()
        return gm

    def _execute_find_cycles(self, plan: GraphPlan) -> QueryResult:
        """Execute FIND CYCLES query using petgraph's Kosaraju algorithm.

        Uses GraphManager.find_cycles() for O(V+E) cycle detection.
        """
        try:
            gm = self._get_graph_manager()

            # Convert edge_types to list or None
            edge_types = plan.edge_types if plan.edge_types else None
            cycles = gm.find_cycles(edge_types)

            return self._cycles_to_result(cycles)
        except ImportError as e:
            return QueryResult(error=f"Rust core not available: {e}")
        except Exception as e:
            return QueryResult(error=f"Cycle detection error: {e}")

    def _execute_impact(self, plan: GraphPlan, target: str) -> QueryResult:
        """Execute SHOW IMPACT query using petgraph BFS traversal.

        "If I change X, what might break?"
        Uses GraphManager.impact() for O(V+E) downstream analysis.
        """
        try:
            gm = self._get_graph_manager()

            if not target:
                return QueryResult(error="SHOW IMPACT requires a target node")

            # Check if node exists
            if not gm.has_node(target):
                return QueryResult(error=f"Node not found: {target}")

            edge_types = plan.edge_types if plan.edge_types else None
            impacted = gm.impact(target, edge_types)

            return self._string_list_to_result(impacted, "Impact Analysis")
        except ImportError as e:
            return QueryResult(error=f"Rust core not available: {e}")
        except Exception as e:
            return QueryResult(error=f"Impact analysis error: {e}")

    def _execute_ancestors(self, plan: GraphPlan, target: str) -> QueryResult:
        """Execute SHOW ANCESTORS query using petgraph BFS traversal.

        "What does X depend on?"
        Uses GraphManager.ancestors() for O(V+E) upstream analysis.
        """
        try:
            gm = self._get_graph_manager()

            if not target:
                return QueryResult(error="SHOW ANCESTORS requires a target node")

            # Check if node exists
            if not gm.has_node(target):
                return QueryResult(error=f"Node not found: {target}")

            edge_types = plan.edge_types if plan.edge_types else None
            ancestors = gm.ancestors(target, edge_types)

            return self._string_list_to_result(ancestors, "Ancestors")
        except ImportError as e:
            return QueryResult(error=f"Rust core not available: {e}")
        except Exception as e:
            return QueryResult(error=f"Ancestors analysis error: {e}")

    def _execute_path(
        self, plan: GraphPlan, from_node: str, to_node: str, max_depth: int
    ) -> QueryResult:
        """Execute PATH query using petgraph BFS.

        Uses GraphManager.shortest_path() for O(V+E) path finding.
        """
        try:
            gm = self._get_graph_manager()

            if not from_node or not to_node:
                return QueryResult(error="PATH requires both FROM and TO nodes")

            edge_types = plan.edge_types if plan.edge_types else None
            path = gm.shortest_path(from_node, to_node, edge_types)

            return self._path_to_result(path)
        except ImportError:
            # Fall back to MUbase implementation
            path = self._db.find_path(from_node, to_node, max_depth=max_depth)
            return self._path_to_result(path)
        except Exception as e:
            return QueryResult(error=f"Path finding error: {e}")

    def _cycles_to_result(self, cycles: list[list[str]]) -> QueryResult:
        """Convert list of cycles to QueryResult."""
        if not cycles:
            return QueryResult(
                columns=["cycle_id", "node"],
                rows=[],
                row_count=0,
            )

        rows = []
        for cycle_id, cycle in enumerate(cycles):
            for node in cycle:
                rows.append((cycle_id, node))

        return QueryResult(
            columns=["cycle_id", "node"],
            rows=rows,
            row_count=len(rows),
        )

    def _string_list_to_result(self, nodes: list[str], label: str = "Results") -> QueryResult:
        """Convert list of node ID strings to QueryResult."""
        if not nodes:
            return QueryResult(
                columns=["node_id"],
                rows=[],
                row_count=0,
            )

        rows = [(node,) for node in nodes]
        return QueryResult(
            columns=["node_id"],
            rows=rows,
            row_count=len(rows),
        )

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
                SELECT name, type, file_path, complexity
                FROM nodes
                WHERE complexity > 0 AND file_path LIKE '%' || ? || '%'
                ORDER BY complexity DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql, [target])
        else:
            sql = """
                SELECT name, type, file_path, complexity
                FROM nodes
                WHERE complexity > 0
                ORDER BY complexity DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql)

        rows = cursor.fetchall()

        return QueryResult(
            columns=["name", "type", "file_path", "complexity"],
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
        )

    def _analyze_hotspots(self, target: str | None) -> QueryResult:
        """Find hotspots (high complexity + high fan-in)."""
        # Hotspots are nodes with high complexity and many dependents
        if target:
            sql = """
                SELECT n.name, n.type, n.file_path, n.complexity,
                       COUNT(DISTINCT e.source_id) as dependents
                FROM nodes n
                LEFT JOIN edges e ON e.target_id = n.id
                WHERE n.complexity > 10 AND n.file_path LIKE '%' || ? || '%'
                GROUP BY n.id, n.name, n.type, n.file_path, n.complexity
                ORDER BY n.complexity * COUNT(DISTINCT e.source_id) DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql, [target])
        else:
            sql = """
                SELECT n.name, n.type, n.file_path, n.complexity,
                       COUNT(DISTINCT e.source_id) as dependents
                FROM nodes n
                LEFT JOIN edges e ON e.target_id = n.id
                WHERE n.complexity > 10
                GROUP BY n.id, n.name, n.type, n.file_path, n.complexity
                ORDER BY n.complexity * COUNT(DISTINCT e.source_id) DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql)

        rows = cursor.fetchall()

        return QueryResult(
            columns=["name", "type", "file_path", "complexity", "dependents"],
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
                SELECT n.name, n.type, n.file_path
                FROM nodes n
                LEFT JOIN edges e ON e.target_id = n.id
                WHERE e.id IS NULL AND n.type IN ('function', 'class')
                      AND n.file_path LIKE '%' || ? || '%'
                ORDER BY n.file_path, n.name
                LIMIT 50
            """
            cursor = self._db.conn.execute(sql, [target])
        else:
            sql = """
                SELECT n.name, n.type, n.file_path
                FROM nodes n
                LEFT JOIN edges e ON e.target_id = n.id
                WHERE e.id IS NULL AND n.type IN ('function', 'class')
                ORDER BY n.file_path, n.name
                LIMIT 50
            """
            cursor = self._db.conn.execute(sql)

        rows = cursor.fetchall()

        return QueryResult(
            columns=["name", "type", "file_path"],
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
        )

    def _analyze_coupling(self, target: str | None) -> QueryResult:
        """Analyze module coupling (external dependencies)."""
        if target:
            sql = """
                SELECT n.file_path, COUNT(DISTINCT e.target_id) as dependencies
                FROM nodes n
                JOIN edges e ON e.source_id = n.id
                WHERE n.type = 'module' AND e.type = 'imports'
                      AND n.file_path LIKE '%' || ? || '%'
                GROUP BY n.file_path
                ORDER BY dependencies DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql, [target])
        else:
            sql = """
                SELECT n.file_path, COUNT(DISTINCT e.target_id) as dependencies
                FROM nodes n
                JOIN edges e ON e.source_id = n.id
                WHERE n.type = 'module' AND e.type = 'imports'
                GROUP BY n.file_path
                ORDER BY dependencies DESC
                LIMIT 20
            """
            cursor = self._db.conn.execute(sql)

        rows = cursor.fetchall()

        return QueryResult(
            columns=["file_path", "dependencies"],
            rows=[tuple(row) for row in rows],
            row_count=len(rows),
        )

    def _analyze_cohesion(self, target: str | None) -> QueryResult:
        """Analyze module cohesion (internal vs external calls)."""
        # Simplified cohesion metric
        sql = """
            SELECT n.file_path,
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
            GROUP BY n.file_path
            HAVING COUNT(DISTINCT c.id) > 1
            ORDER BY CAST(COUNT(DISTINCT e.id) AS FLOAT) / COUNT(DISTINCT c.id) DESC
            LIMIT 20
        """

        try:
            cursor = self._db.conn.execute(sql)
            rows = cursor.fetchall()

            return QueryResult(
                columns=["file_path", "children", "internal_edges"],
                rows=[tuple(row) for row in rows],
                row_count=len(rows),
            )
        except Exception as e:
            # Fallback for simpler query - include error for debugging
            return QueryResult(
                columns=["file_path", "children", "internal_edges"],
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

    # -------------------------------------------------------------------------
    # Temporal Execution
    # -------------------------------------------------------------------------

    def _execute_temporal(self, plan: TemporalPlan) -> QueryResult:
        """Execute temporal query plans (HISTORY, BLAME, AT queries)."""

        operation = plan.operation
        target = plan.target_node
        commit = plan.commit
        limit = plan.limit or 100

        try:
            if operation == "history":
                return self._execute_history(target, limit)
            elif operation == "blame":
                return self._execute_blame(target)
            elif operation == "at":
                return self._execute_at(commit or "", plan.inner_sql or "", plan.parameters)
            elif operation == "between":
                commit2 = plan.commit2 or ""
                return self._execute_between(commit or "", commit2)
            else:
                return self._not_implemented(f"temporal operation: {operation}")
        except Exception as e:
            return QueryResult(error=f"Temporal execution error: {e}")

    def _execute_history(self, target: str, limit: int) -> QueryResult:
        """Execute HISTORY query for a node."""
        from mu.kernel.temporal import HistoryTracker

        tracker = HistoryTracker(self._db)

        # Find the node by name
        nodes = self._db.find_by_name(target)
        if not nodes:
            nodes = self._db.find_by_name(f"%{target}%")
        if not nodes:
            return QueryResult(error=f"Node not found: {target}")

        node = nodes[0]
        changes = tracker.history(node.id, limit=limit)

        rows = []
        for change in changes:
            rows.append(
                (
                    change.commit_hash or "",
                    change.change_type.value,
                    change.commit_message or "",
                    change.commit_author or "",
                    change.commit_date.isoformat() if change.commit_date else "",
                )
            )

        return QueryResult(
            columns=["commit", "change_type", "message", "author", "date"],
            rows=rows,
            row_count=len(rows),
        )

    def _execute_blame(self, target: str) -> QueryResult:
        """Execute BLAME query for a node."""
        from mu.kernel.temporal import HistoryTracker

        tracker = HistoryTracker(self._db)

        # Find the node by name
        nodes = self._db.find_by_name(target)
        if not nodes:
            nodes = self._db.find_by_name(f"%{target}%")
        if not nodes:
            return QueryResult(error=f"Node not found: {target}")

        node = nodes[0]
        blame_info = tracker.blame(node.id)

        if not blame_info:
            return QueryResult(
                columns=["property", "commit", "author", "date"],
                rows=[],
                row_count=0,
            )

        rows = []
        for prop_name, change in blame_info.items():
            rows.append(
                (
                    prop_name,
                    change.commit_hash or "",
                    change.commit_author or "",
                    change.commit_date.isoformat() if change.commit_date else "",
                )
            )

        return QueryResult(
            columns=["property", "commit", "author", "date"],
            rows=rows,
            row_count=len(rows),
        )

    def _execute_at(
        self,
        commit: str,
        inner_sql: str,
        parameters: list[Any] | None,
    ) -> QueryResult:
        """Execute query AT a specific commit."""
        from mu.kernel.temporal import MUbaseSnapshot, SnapshotManager

        manager = SnapshotManager(self._db)
        snapshot = manager.get_snapshot(commit)

        if not snapshot:
            return QueryResult(error=f"No snapshot exists for commit: {commit}")

        # Create temporal view
        temporal_view = MUbaseSnapshot(self._db, snapshot)

        # Execute the inner query against the snapshot
        # For now, return snapshot stats - full query rewriting would need more work
        stats = temporal_view.stats()

        rows = [(k, str(v)) for k, v in stats.items()]

        return QueryResult(
            columns=["stat", "value"],
            rows=rows,
            row_count=len(rows),
        )

    def _execute_between(self, commit1: str, commit2: str) -> QueryResult:
        """Execute diff query BETWEEN two commits."""
        from mu.kernel.temporal import SnapshotManager, TemporalDiffer

        manager = SnapshotManager(self._db)
        differ = TemporalDiffer(manager)

        try:
            diff = differ.diff(commit1, commit2)
        except ValueError as e:
            return QueryResult(error=str(e))

        # Return summary of changes
        stats = diff.stats
        rows = []
        for stat_name, value in stats.items():
            rows.append((stat_name, value))

        return QueryResult(
            columns=["change_type", "count"],
            rows=rows,
            row_count=len(rows),
        )


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
