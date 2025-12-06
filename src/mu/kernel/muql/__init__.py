"""MUQL - MU Query Language for codebase exploration.

MUQL provides an SQL-like query interface for exploring codebases
stored in MUbase graph databases.

Example:
    >>> from mu.kernel.muql import MUQLEngine
    >>> from mu.kernel import MUbase
    >>>
    >>> db = MUbase(".mubase")
    >>> engine = MUQLEngine(db)
    >>>
    >>> # Execute queries
    >>> result = engine.execute("SELECT * FROM functions WHERE complexity > 20")
    >>> for row in result.rows:
    ...     print(row)
    >>>
    >>> # Get formatted output
    >>> print(engine.query("SHOW dependencies OF MUbase"))
    >>> print(engine.query("FIND functions CALLING parse_file"))
    >>> print(engine.query("PATH FROM cli TO parser MAX DEPTH 5"))
    >>> print(engine.query("ANALYZE complexity"))
"""

from mu.kernel.muql.ast import (
    AnalysisType,
    AnalyzeQuery,
    ComparisonOperator,
    EdgeTypeFilter,
    FindConditionType,
    FindQuery,
    NodeTypeFilter,
    PathQuery,
    Query,
    QueryType,
    SelectQuery,
    ShowQuery,
    ShowType,
)
from mu.kernel.muql.engine import MUQLEngine, create_engine
from mu.kernel.muql.executor import QueryExecutor, QueryResult, execute_plan
from mu.kernel.muql.formatter import OutputFormat, format_result
from mu.kernel.muql.parser import MUQLParser, MUQLSyntaxError, parse
from mu.kernel.muql.planner import (
    AnalysisPlan,
    ExecutionPlan,
    GraphPlan,
    QueryPlanner,
    SQLPlan,
    plan_query,
)

__all__ = [
    # Engine (main interface)
    "MUQLEngine",
    "create_engine",
    # Parser
    "MUQLParser",
    "MUQLSyntaxError",
    "parse",
    # Planner
    "QueryPlanner",
    "plan_query",
    "ExecutionPlan",
    "SQLPlan",
    "GraphPlan",
    "AnalysisPlan",
    # Executor
    "QueryExecutor",
    "QueryResult",
    "execute_plan",
    # Formatter
    "OutputFormat",
    "format_result",
    # AST types
    "Query",
    "QueryType",
    "SelectQuery",
    "ShowQuery",
    "FindQuery",
    "PathQuery",
    "AnalyzeQuery",
    # Enums
    "NodeTypeFilter",
    "ShowType",
    "FindConditionType",
    "EdgeTypeFilter",
    "AnalysisType",
    "ComparisonOperator",
]
