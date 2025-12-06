"""MUQL Engine - High-level query execution interface.

The MUQLEngine provides a unified interface for parsing, planning,
executing, and formatting MUQL queries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mu.kernel.muql.executor import QueryExecutor, QueryResult
from mu.kernel.muql.formatter import OutputFormat, format_result
from mu.kernel.muql.parser import MUQLParser, MUQLSyntaxError
from mu.kernel.muql.planner import ExecutionPlan, QueryPlanner

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class MUQLEngine:
    """High-level MUQL query engine.

    Provides a unified interface for executing MUQL queries against
    a MUbase database.

    Example:
        >>> from mu.kernel import MUbase
        >>> from mu.kernel.muql import MUQLEngine
        >>>
        >>> db = MUbase(".mubase")
        >>> engine = MUQLEngine(db)
        >>>
        >>> # Execute a query and get results
        >>> result = engine.execute("SELECT * FROM functions WHERE complexity > 20")
        >>> print(result.row_count)
        >>>
        >>> # Execute and format in one step
        >>> output = engine.query("SELECT * FROM functions LIMIT 10")
        >>> print(output)
    """

    def __init__(self, db: MUbase) -> None:
        """Initialize the MUQL engine.

        Args:
            db: The MUbase database to query.
        """
        self._db = db
        self._parser = MUQLParser()
        self._planner = QueryPlanner()
        self._executor = QueryExecutor(db)

    def parse(self, query: str) -> ExecutionPlan:
        """Parse and plan a query without executing.

        Useful for query validation and debugging.

        Args:
            query: The MUQL query string.

        Returns:
            The execution plan.

        Raises:
            MUQLSyntaxError: If the query is invalid.
        """
        ast = self._parser.parse(query)
        return self._planner.plan(ast)

    def execute(self, query: str) -> QueryResult:
        """Execute a MUQL query and return results.

        Args:
            query: The MUQL query string.

        Returns:
            QueryResult with columns, rows, and metadata.
        """
        try:
            plan = self.parse(query)
            return self._executor.execute(plan)
        except MUQLSyntaxError as e:
            return QueryResult(error=str(e))
        except Exception as e:
            return QueryResult(error=f"Query execution failed: {e}")

    def query(
        self,
        query: str,
        output_format: OutputFormat | str = OutputFormat.TABLE,
        no_color: bool = False,
    ) -> str:
        """Execute a query and return formatted output.

        Convenience method that combines execute and format.

        Args:
            query: The MUQL query string.
            output_format: Output format (table, json, csv, tree).
            no_color: If True, disable ANSI colors.

        Returns:
            Formatted output string.
        """
        result = self.execute(query)
        return format_result(result, output_format, no_color)

    def explain(self, query: str) -> str:
        """Explain the execution plan for a query.

        Shows how a query will be executed without running it.

        Args:
            query: The MUQL query string.

        Returns:
            Explanation of the execution plan.
        """
        try:
            plan = self.parse(query)
            lines = [
                "Execution Plan:",
                f"  Type: {plan.plan_type.value}",
            ]

            plan_dict = plan.to_dict()
            for key, value in plan_dict.items():
                if key != "plan_type" and value:
                    if isinstance(value, dict):
                        lines.append(f"  {key}:")
                        for k, v in value.items():
                            lines.append(f"    {k}: {v}")
                    elif isinstance(value, list):
                        lines.append(f"  {key}: {', '.join(str(v) for v in value)}")
                    else:
                        lines.append(f"  {key}: {value}")

            return "\n".join(lines)
        except MUQLSyntaxError as e:
            return f"Parse Error: {e}"
        except Exception as e:
            return f"Error: {e}"


# =============================================================================
# Convenience Functions
# =============================================================================


def create_engine(db: MUbase) -> MUQLEngine:
    """Create a new MUQL engine for a database.

    Args:
        db: The MUbase database.

    Returns:
        A new MUQLEngine instance.
    """
    return MUQLEngine(db)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "MUQLEngine",
    "create_engine",
    # Re-export common types
    "QueryResult",
    "MUQLSyntaxError",
    "OutputFormat",
]
