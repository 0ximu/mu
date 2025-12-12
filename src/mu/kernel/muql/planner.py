"""MUQL Query Planner - Converts AST to execution plans.

The planner transforms parsed MUQL queries into execution plans that
can be executed against the MUbase database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mu.kernel.muql.ast import (
    AggregateComparison,
    AnalysisType,
    AnalyzeQuery,
    BlameQuery,
    Comparison,
    ComparisonOperator,
    Condition,
    CyclesQuery,
    DescribeQuery,
    DescribeTarget,
    EdgeTypeFilter,
    FindConditionType,
    FindQuery,
    HistoryQuery,
    NodeTypeFilter,
    PathQuery,
    Query,
    SelectField,
    SelectQuery,
    ShowQuery,
    ShowType,
    SortOrder,
)

# =============================================================================
# Resource Limits
# =============================================================================

# Maximum allowed LIMIT value to prevent resource exhaustion
MAX_LIMIT = 10000

# Maximum allowed DEPTH for graph traversals
MAX_DEPTH = 20

# =============================================================================
# Execution Plan Types
# =============================================================================


class PlanType(Enum):
    """Types of execution plans."""

    SQL = "sql"  # Execute SQL against DuckDB
    GRAPH = "graph"  # Graph traversal using MUbase methods
    ANALYSIS = "analysis"  # Built-in analysis functions
    TEMPORAL = "temporal"  # Temporal queries (history, blame, at)


@dataclass
class SQLPlan:
    """An execution plan that runs SQL against DuckDB."""

    plan_type: PlanType = field(default=PlanType.SQL, init=False)
    sql: str = ""
    parameters: list[Any] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_type": self.plan_type.value,
            "sql": self.sql,
            "parameters": self.parameters,
            "columns": self.columns,
        }


@dataclass
class GraphPlan:
    """An execution plan for graph traversal operations."""

    plan_type: PlanType = field(default=PlanType.GRAPH, init=False)
    operation: str = ""  # get_dependencies, get_dependents, find_path, etc.
    target_node: str = ""
    depth: int = 1
    edge_types: list[str] = field(default_factory=list)
    extra_args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_type": self.plan_type.value,
            "operation": self.operation,
            "target_node": self.target_node,
            "depth": self.depth,
            "edge_types": self.edge_types,
            "extra_args": self.extra_args,
        }


@dataclass
class AnalysisPlan:
    """An execution plan for built-in analysis functions."""

    plan_type: PlanType = field(default=PlanType.ANALYSIS, init=False)
    analysis_type: AnalysisType = AnalysisType.COMPLEXITY
    target_node: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_type": self.plan_type.value,
            "analysis_type": self.analysis_type.value,
            "target_node": self.target_node,
        }


@dataclass
class TemporalPlan:
    """An execution plan for temporal queries (history, blame, at)."""

    plan_type: PlanType = field(default=PlanType.TEMPORAL, init=False)
    operation: str = ""  # history, blame, at, between
    target_node: str = ""
    commit: str | None = None
    commit2: str | None = None  # For BETWEEN queries
    limit: int | None = None
    inner_sql: str | None = None  # For AT queries with inner SELECT
    parameters: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_type": self.plan_type.value,
            "operation": self.operation,
            "target_node": self.target_node,
            "commit": self.commit,
            "commit2": self.commit2,
            "limit": self.limit,
            "inner_sql": self.inner_sql,
            "parameters": self.parameters,
        }


ExecutionPlan = SQLPlan | GraphPlan | AnalysisPlan | TemporalPlan


# =============================================================================
# Query Planner
# =============================================================================


class QueryPlanner:
    """Converts MUQL AST queries into execution plans."""

    def plan(self, query: Query) -> ExecutionPlan:
        """Create an execution plan for a query.

        Args:
            query: The parsed MUQL query.

        Returns:
            An execution plan (SQLPlan, GraphPlan, AnalysisPlan, or TemporalPlan).
        """
        if isinstance(query, SelectQuery):
            return self._plan_select(query)
        elif isinstance(query, ShowQuery):
            return self._plan_show(query)
        elif isinstance(query, FindQuery):
            return self._plan_find(query)
        elif isinstance(query, CyclesQuery):
            return self._plan_cycles(query)
        elif isinstance(query, PathQuery):
            return self._plan_path(query)
        elif isinstance(query, AnalyzeQuery):
            return self._plan_analyze(query)
        elif isinstance(query, HistoryQuery):
            return self._plan_history(query)
        elif isinstance(query, BlameQuery):
            return self._plan_blame(query)
        elif isinstance(query, DescribeQuery):
            return self._plan_describe(query)
        else:
            raise ValueError(f"Unknown query type: {type(query)}")

    # -------------------------------------------------------------------------
    # SELECT Query Planning
    # -------------------------------------------------------------------------

    def _plan_select(self, query: SelectQuery) -> SQLPlan | TemporalPlan:
        """Generate SQL for a SELECT query, or temporal plan if AT/BETWEEN is used."""
        # If temporal clause is present, use temporal plan
        if query.temporal:
            return self._plan_select_temporal(query)

        sql_parts: list[str] = []
        params: list[Any] = []
        columns: list[str] = []

        # SELECT clause
        select_clause = self._build_select_clause(query.fields, columns)
        sql_parts.append(f"SELECT {select_clause}")

        # FROM clause (with parameters for type filtering)
        table, table_params = self._node_type_to_table(query.node_type)
        sql_parts.append(f"FROM {table}")
        params.extend(table_params)

        # WHERE clause
        if query.where:
            where_sql, where_params = self._build_where_clause(query.where)
            if where_sql:
                sql_parts.append(f"WHERE {where_sql}")
                params.extend(where_params)

        # GROUP BY clause
        if query.group_by:
            group_fields = [g.name for g in query.group_by]
            sql_parts.append(f"GROUP BY {', '.join(group_fields)}")

        # HAVING clause
        if query.having:
            having_sql, having_params = self._build_where_clause(query.having)
            if having_sql:
                sql_parts.append(f"HAVING {having_sql}")
                params.extend(having_params)

        # ORDER BY clause
        if query.order_by:
            order_parts = []
            for order_field in query.order_by:
                direction = "DESC" if order_field.order == SortOrder.DESC else "ASC"
                order_parts.append(f"{order_field.name} {direction}")
            sql_parts.append(f"ORDER BY {', '.join(order_parts)}")

        # LIMIT clause (capped for resource protection)
        if query.limit is not None:
            capped_limit = min(query.limit, MAX_LIMIT)
            sql_parts.append(f"LIMIT {capped_limit}")

        return SQLPlan(
            sql="\n".join(sql_parts),
            parameters=params,
            columns=columns,
        )

    def _plan_select_temporal(self, query: SelectQuery) -> TemporalPlan:
        """Generate temporal plan for SELECT with AT/BETWEEN."""
        if not query.temporal:
            raise ValueError("No temporal clause in query")

        # Build the base SQL without temporal
        sql_parts: list[str] = []
        params: list[Any] = []
        columns: list[str] = []

        select_clause = self._build_select_clause(query.fields, columns)
        sql_parts.append(f"SELECT {select_clause}")

        table, table_params = self._node_type_to_table(query.node_type)
        sql_parts.append(f"FROM {table}")
        params.extend(table_params)

        if query.where:
            where_sql, where_params = self._build_where_clause(query.where)
            if where_sql:
                sql_parts.append(f"WHERE {where_sql}")
                params.extend(where_params)

        if query.order_by:
            order_parts = []
            for order_field in query.order_by:
                direction = "DESC" if order_field.order == SortOrder.DESC else "ASC"
                order_parts.append(f"{order_field.name} {direction}")
            sql_parts.append(f"ORDER BY {', '.join(order_parts)}")

        if query.limit is not None:
            capped_limit = min(query.limit, MAX_LIMIT)
            sql_parts.append(f"LIMIT {capped_limit}")

        inner_sql = "\n".join(sql_parts)

        if query.temporal.clause_type == "at":
            return TemporalPlan(
                operation="at",
                commit=query.temporal.commit1,
                inner_sql=inner_sql,
                parameters=params,
            )
        else:  # between
            return TemporalPlan(
                operation="between",
                commit=query.temporal.commit1,
                commit2=query.temporal.commit2,
                inner_sql=inner_sql,
                parameters=params,
            )

    def _build_select_clause(self, fields: list[SelectField], columns: list[str]) -> str:
        """Build the SELECT clause from field list."""
        # Full column list matching the nodes table schema order
        all_columns = [
            "id",
            "type",
            "name",
            "qualified_name",
            "file_path",
            "line_start",
            "line_end",
            "properties",
            "complexity",
        ]

        if not fields:
            columns.extend(all_columns)
            return "*"

        parts: list[str] = []
        for select_field in fields:
            if select_field.is_star and not select_field.aggregate:
                columns.extend(all_columns)
                parts.append("*")
            elif select_field.aggregate:
                agg = select_field.aggregate.value.upper()
                if select_field.is_star:
                    col_alias = select_field.alias or f"{agg.lower()}_star"
                    parts.append(f"{agg}(*) AS {col_alias}")
                    columns.append(col_alias)
                else:
                    col_alias = select_field.alias or f"{agg.lower()}_{select_field.name}"
                    parts.append(f"{agg}({select_field.name}) AS {col_alias}")
                    columns.append(col_alias)
            else:
                if select_field.alias:
                    parts.append(f"{select_field.name} AS {select_field.alias}")
                    columns.append(select_field.alias)
                else:
                    parts.append(select_field.name)
                    columns.append(select_field.name)

        return ", ".join(parts)

    def _node_type_to_table(self, node_type: NodeTypeFilter) -> tuple[str, list[Any]]:
        """Convert node type filter to table name or subquery with parameters.

        Returns:
            Tuple of (table_expression, parameters) for safe parameterized queries.
        """
        if node_type == NodeTypeFilter.NODES:
            return "nodes", []
        else:
            # Use parameterized query for defense-in-depth
            # Even though node_type is from a trusted enum, we use parameters for consistency
            return "(SELECT * FROM nodes WHERE type = ?)", [node_type.value]

    def _build_where_clause(self, condition: Condition) -> tuple[str, list[Any]]:
        """Build WHERE clause from condition."""
        if not condition.comparisons and not condition.nested:
            return "", []

        parts: list[str] = []
        params: list[Any] = []

        # Handle direct comparisons (Comparison or AggregateComparison)
        for comp in condition.comparisons:
            if isinstance(comp, AggregateComparison):
                sql, param = self._aggregate_comparison_to_sql(comp)
            else:
                sql, param = self._comparison_to_sql(comp)
            parts.append(sql)
            params.extend(param)

        # Handle nested conditions (OR)
        for nested in condition.nested:
            nested_sql, nested_params = self._build_where_clause(nested)
            if nested_sql:
                parts.append(f"({nested_sql})")
                params.extend(nested_params)

        operator = " OR " if condition.operator == "or" else " AND "
        return operator.join(parts), params

    def _comparison_to_sql(self, comp: Comparison) -> tuple[str, list[Any]]:
        """Convert a comparison to SQL."""
        field = comp.field
        params: list[Any] = []

        if comp.operator == ComparisonOperator.IN:
            if isinstance(comp.value, list):
                placeholders = ", ".join("?" * len(comp.value))
                params = [v.value for v in comp.value]
                return f"{field} IN ({placeholders})", params
        elif comp.operator == ComparisonOperator.NOT_IN:
            if isinstance(comp.value, list):
                placeholders = ", ".join("?" * len(comp.value))
                params = [v.value for v in comp.value]
                return f"{field} NOT IN ({placeholders})", params
        elif comp.operator == ComparisonOperator.LIKE:
            if not isinstance(comp.value, list):
                return f"{field} LIKE ?", [comp.value.value]
        elif comp.operator == ComparisonOperator.CONTAINS:
            if not isinstance(comp.value, list):
                return f"{field} LIKE '%' || ? || '%'", [comp.value.value]
        else:
            # Standard comparison operators
            op_map = {
                ComparisonOperator.EQ: "=",
                ComparisonOperator.NEQ: "!=",
                ComparisonOperator.GT: ">",
                ComparisonOperator.LT: "<",
                ComparisonOperator.GTE: ">=",
                ComparisonOperator.LTE: "<=",
            }
            op = op_map.get(comp.operator, "=")
            if not isinstance(comp.value, list):
                return f"{field} {op} ?", [comp.value.value]

        return "1=1", []

    def _aggregate_comparison_to_sql(self, comp: AggregateComparison) -> tuple[str, list[Any]]:
        """Convert an aggregate comparison to SQL for HAVING clause.

        Examples:
            COUNT(*) > 10 -> "COUNT(*) > ?"
            AVG(complexity) >= 5 -> "AVG(complexity) >= ?"
        """
        agg_name = comp.aggregate.value.upper()

        # Build aggregate expression
        if comp.field == "*":
            agg_expr = f"{agg_name}(*)"
        else:
            agg_expr = f"{agg_name}({comp.field})"

        # Map operator
        op_map = {
            ComparisonOperator.EQ: "=",
            ComparisonOperator.NEQ: "!=",
            ComparisonOperator.GT: ">",
            ComparisonOperator.LT: "<",
            ComparisonOperator.GTE: ">=",
            ComparisonOperator.LTE: "<=",
        }
        op = op_map.get(comp.operator, "=")

        return f"{agg_expr} {op} ?", [comp.value.value]

    # -------------------------------------------------------------------------
    # SHOW Query Planning
    # -------------------------------------------------------------------------

    def _plan_show(self, query: ShowQuery) -> GraphPlan:
        """Generate a graph plan for SHOW query."""
        operation = self._show_type_to_operation(query.show_type)
        target = query.target.name

        # Cap depth for resource protection
        capped_depth = min(query.depth, MAX_DEPTH)

        return GraphPlan(
            operation=operation,
            target_node=target,
            depth=capped_depth,
        )

    def _show_type_to_operation(self, show_type: ShowType) -> str:
        """Map ShowType to MUbase method name."""
        mapping = {
            ShowType.DEPENDENCIES: "get_dependencies",
            ShowType.DEPENDENTS: "get_dependents",
            ShowType.CALLERS: "get_callers",
            ShowType.CALLEES: "get_callees",
            ShowType.INHERITANCE: "get_inheritance",
            ShowType.IMPLEMENTATIONS: "get_implementations",
            ShowType.CHILDREN: "get_children",
            ShowType.PARENTS: "get_parents",
            ShowType.IMPACT: "get_impact",  # Uses GraphManager.impact()
            ShowType.ANCESTORS: "get_ancestors",  # Uses GraphManager.ancestors()
        }
        return mapping.get(show_type, "get_dependencies")

    # -------------------------------------------------------------------------
    # FIND CYCLES Query Planning (Graph cycle detection)
    # -------------------------------------------------------------------------

    def _plan_cycles(self, query: CyclesQuery) -> GraphPlan:
        """Generate a graph plan for FIND CYCLES query.

        Uses GraphManager.find_cycles() backed by petgraph's Kosaraju algorithm.
        """
        return GraphPlan(
            operation="find_cycles",
            target_node="",  # Not applicable for cycles
            depth=0,  # Not applicable for cycles
            edge_types=query.edge_types,
        )

    # -------------------------------------------------------------------------
    # FIND Query Planning
    # -------------------------------------------------------------------------

    def _plan_find(self, query: FindQuery) -> SQLPlan | GraphPlan:
        """Generate plan for FIND query.

        Some FIND queries can be translated to SQL, others require
        graph traversal.
        """
        cond = query.condition
        node_type = query.node_type
        limit = query.limit

        # Pattern matching queries can use SQL
        if cond.condition_type == FindConditionType.MATCHING:
            pattern = cond.pattern or ""
            sql, base_params = self._build_find_matching_sql(node_type, pattern, limit)
            # Combine base params (type filter) with pattern param
            params = base_params + [f"%{pattern}%"]
            return SQLPlan(
                sql=sql,
                parameters=params,
                columns=["id", "name", "type", "path"],
            )

        # Decorator/annotation queries use SQL
        if cond.condition_type in (
            FindConditionType.WITH_DECORATOR,
            FindConditionType.WITH_ANNOTATION,
        ):
            pattern = cond.pattern or ""
            sql, base_params = self._build_find_decorator_sql(node_type, pattern, limit)
            # Combine base params (type filter) with pattern param
            params = base_params + [f"%{pattern}%"]
            return SQLPlan(
                sql=sql,
                parameters=params,
                columns=["id", "name", "type", "path"],
            )

        # Graph traversal queries
        operation = self._find_condition_to_operation(cond.condition_type)
        target = cond.target.name if cond.target else ""

        return GraphPlan(
            operation=operation,
            target_node=target,
            extra_args={"node_type": node_type.value, "limit": limit},
        )

    def _build_find_matching_sql(
        self, node_type: NodeTypeFilter, pattern: str, limit: int | None = None
    ) -> tuple[str, list[Any]]:
        """Build SQL for FIND ... MATCHING query.

        Returns:
            Tuple of (sql, base_params) where base_params are type filter params.
            The caller should append the pattern parameter.
        """
        type_filter = ""
        base_params: list[Any] = []
        if node_type != NodeTypeFilter.NODES:
            type_filter = "type = ? AND "
            base_params.append(node_type.value)

        # Apply limit (capped at MAX_LIMIT)
        limit_clause = ""
        if limit is not None:
            effective_limit = min(limit, MAX_LIMIT)
            limit_clause = f"\nLIMIT {effective_limit}"

        sql = f"""
SELECT id, name, type, file_path
FROM nodes
WHERE {type_filter}name LIKE ?
ORDER BY name{limit_clause}
"""
        return sql, base_params

    def _build_find_decorator_sql(
        self, node_type: NodeTypeFilter, pattern: str, limit: int | None = None
    ) -> tuple[str, list[Any]]:
        """Build SQL for FIND ... WITH DECORATOR query.

        Returns:
            Tuple of (sql, base_params) where base_params are type filter params.
            The caller should append the pattern parameter.
        """
        type_filter = ""
        base_params: list[Any] = []
        if node_type != NodeTypeFilter.NODES:
            type_filter = "type = ? AND "
            base_params.append(node_type.value)

        # Apply limit (capped at MAX_LIMIT)
        limit_clause = ""
        if limit is not None:
            effective_limit = min(limit, MAX_LIMIT)
            limit_clause = f"\nLIMIT {effective_limit}"

        # Decorators are stored in node metadata
        sql = f"""
SELECT id, name, type, file_path
FROM nodes
WHERE {type_filter}metadata LIKE ?
ORDER BY name{limit_clause}
"""
        return sql, base_params

    def _find_condition_to_operation(self, condition_type: FindConditionType) -> str:
        """Map FindConditionType to operation name."""
        mapping = {
            FindConditionType.CALLING: "find_calling",
            FindConditionType.CALLED_BY: "find_called_by",
            FindConditionType.IMPORTING: "find_importing",
            FindConditionType.IMPORTED_BY: "find_imported_by",
            FindConditionType.INHERITING: "find_inheriting",
            FindConditionType.IMPLEMENTING: "find_implementing",
            FindConditionType.MUTATING: "find_mutating",
            FindConditionType.SIMILAR_TO: "find_similar",
        }
        return mapping.get(condition_type, "find_nodes")

    # -------------------------------------------------------------------------
    # PATH Query Planning
    # -------------------------------------------------------------------------

    def _plan_path(self, query: PathQuery) -> GraphPlan:
        """Generate plan for PATH query."""
        edge_types: list[str] = []
        if query.via_edge:
            edge_types = [self._edge_type_to_string(query.via_edge)]

        # Cap depth for resource protection
        capped_depth = min(query.max_depth, MAX_DEPTH)

        return GraphPlan(
            operation="find_path",
            target_node=query.from_node.name,
            depth=capped_depth,
            edge_types=edge_types,
            extra_args={"to_node": query.to_node.name},
        )

    def _edge_type_to_string(self, edge_type: EdgeTypeFilter) -> str:
        """Convert edge type filter to string."""
        return edge_type.value

    # -------------------------------------------------------------------------
    # ANALYZE Query Planning
    # -------------------------------------------------------------------------

    def _plan_analyze(self, query: AnalyzeQuery) -> AnalysisPlan:
        """Generate plan for ANALYZE query."""
        target = query.target.name if query.target else None

        return AnalysisPlan(
            analysis_type=query.analysis_type,
            target_node=target,
        )

    # -------------------------------------------------------------------------
    # TEMPORAL Query Planning
    # -------------------------------------------------------------------------

    def _plan_history(self, query: HistoryQuery) -> TemporalPlan:
        """Generate plan for HISTORY query."""
        limit = query.limit
        if limit is not None:
            limit = min(limit, MAX_LIMIT)

        return TemporalPlan(
            operation="history",
            target_node=query.target.name,
            limit=limit,
        )

    def _plan_blame(self, query: BlameQuery) -> TemporalPlan:
        """Generate plan for BLAME query."""
        return TemporalPlan(
            operation="blame",
            target_node=query.target.name,
        )

    # -------------------------------------------------------------------------
    # DESCRIBE Query Planning
    # -------------------------------------------------------------------------

    def _plan_describe(self, query: DescribeQuery) -> SQLPlan:
        """Generate plan for DESCRIBE query."""
        if query.target == DescribeTarget.TABLES:
            # DuckDB uses information_schema or SHOW TABLES
            return SQLPlan(
                sql="SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name",
                columns=["table_name"],
            )
        elif query.target == DescribeTarget.COLUMNS:
            # Get columns for a specific node type (all use nodes table)
            return SQLPlan(
                sql="SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'nodes' ORDER BY ordinal_position",
                columns=["column_name", "data_type"],
            )
        else:
            # Describe a node type (functions, classes, modules)
            type_value = query.target.value
            if type_value == "nodes":
                sql = """
                    SELECT type, COUNT(*) as count
                    FROM nodes
                    GROUP BY type
                    ORDER BY count DESC
                """
                return SQLPlan(
                    sql=sql,
                    columns=["type", "count"],
                )
            else:
                # Use parameterized query for type filter
                sql = """
                    SELECT name, file_path as path, complexity
                    FROM nodes
                    WHERE type = ?
                    ORDER BY name
                    LIMIT 100
                """
                return SQLPlan(
                    sql=sql,
                    parameters=[type_value],
                    columns=["name", "path", "complexity"],
                )


# =============================================================================
# Convenience Functions
# =============================================================================


def plan_query(query: Query) -> ExecutionPlan:
    """Plan a query using a default planner instance.

    Args:
        query: The parsed MUQL query.

    Returns:
        An execution plan.
    """
    planner = QueryPlanner()
    return planner.plan(query)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Plan types
    "PlanType",
    "SQLPlan",
    "GraphPlan",
    "AnalysisPlan",
    "TemporalPlan",
    "ExecutionPlan",
    # Planner
    "QueryPlanner",
    "plan_query",
]
