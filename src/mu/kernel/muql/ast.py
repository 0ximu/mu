"""AST node models for MUQL queries.

Defines dataclasses for all query types and supporting structures.
All models follow the project pattern with to_dict() methods.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# =============================================================================
# Enums
# =============================================================================


class QueryType(Enum):
    """Types of MUQL queries."""

    SELECT = "select"
    SHOW = "show"
    FIND = "find"
    FIND_CYCLES = "find_cycles"  # Graph cycle detection using petgraph
    PATH = "path"
    ANALYZE = "analyze"
    HISTORY = "history"
    BLAME = "blame"
    DESCRIBE = "describe"


class DescribeTarget(Enum):
    """Targets for DESCRIBE queries."""

    TABLES = "tables"
    COLUMNS = "columns"
    FUNCTIONS = "function"
    CLASSES = "class"
    MODULES = "module"
    NODES = "nodes"


class NodeTypeFilter(Enum):
    """Node types that can be queried."""

    FUNCTIONS = "function"
    CLASSES = "class"
    MODULES = "module"
    NODES = "nodes"  # All nodes
    METHODS = "function"  # Methods are functions within classes


class ShowType(Enum):
    """Types of SHOW queries."""

    DEPENDENCIES = "dependencies"
    DEPENDENTS = "dependents"
    CALLERS = "callers"
    CALLEES = "callees"
    INHERITANCE = "inheritance"
    IMPLEMENTATIONS = "implementations"
    CHILDREN = "children"
    PARENTS = "parents"
    IMPACT = "impact"  # Downstream impact analysis (what breaks if I change X?)
    ANCESTORS = "ancestors"  # Upstream dependency analysis (what does X depend on?)


class FindConditionType(Enum):
    """Types of FIND conditions."""

    CALLING = "calling"
    CALLED_BY = "called_by"
    IMPORTING = "importing"
    IMPORTED_BY = "imported_by"
    INHERITING = "inheriting"
    IMPLEMENTING = "implementing"
    MUTATING = "mutating"
    WITH_DECORATOR = "with_decorator"
    WITH_ANNOTATION = "with_annotation"
    MATCHING = "matching"
    SIMILAR_TO = "similar_to"


class EdgeTypeFilter(Enum):
    """Edge types for PATH queries."""

    CALLS = "calls"
    IMPORTS = "imports"
    INHERITS = "inherits"
    USES = "uses"
    CONTAINS = "contains"


class AnalysisType(Enum):
    """Types of ANALYZE queries."""

    COUPLING = "coupling"
    COHESION = "cohesion"
    COMPLEXITY = "complexity"
    HOTSPOTS = "hotspots"
    CIRCULAR = "circular"
    UNUSED = "unused"
    IMPACT = "impact"


class ComparisonOperator(Enum):
    """Comparison operators for WHERE clauses."""

    EQ = "="
    NEQ = "!="
    GT = ">"
    LT = "<"
    GTE = ">="
    LTE = "<="
    LIKE = "like"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"


class SortOrder(Enum):
    """Sort order for ORDER BY clauses."""

    ASC = "asc"
    DESC = "desc"


class AggregateFunction(Enum):
    """Aggregate functions for SELECT queries."""

    COUNT = "count"
    AVG = "avg"
    MAX = "max"
    MIN = "min"
    SUM = "sum"


# =============================================================================
# Value Types
# =============================================================================


@dataclass
class Value:
    """A literal value in a query."""

    value: str | int | bool | None
    type: str  # "string", "number", "boolean", "null"

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "type": self.type}


# =============================================================================
# Condition Types
# =============================================================================


@dataclass
class Comparison:
    """A single comparison in a WHERE clause."""

    field: str
    operator: ComparisonOperator
    value: Value | list[Value]  # list for IN comparisons

    def to_dict(self) -> dict[str, Any]:
        val: list[dict[str, Any]] | dict[str, Any]
        if isinstance(self.value, list):
            val = [v.to_dict() for v in self.value]
        else:
            val = self.value.to_dict()
        return {
            "field": self.field,
            "operator": self.operator.value,
            "value": val,
        }


@dataclass
class Condition:
    """A boolean condition (AND/OR of comparisons)."""

    comparisons: list[Comparison]
    operator: str  # "and" or "or"
    nested: list[Condition] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparisons": [c.to_dict() for c in self.comparisons],
            "operator": self.operator,
            "nested": [n.to_dict() for n in self.nested],
        }


# =============================================================================
# Field Types
# =============================================================================


@dataclass
class SelectField:
    """A field in a SELECT clause."""

    name: str
    aggregate: AggregateFunction | None = None
    is_star: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aggregate": self.aggregate.value if self.aggregate else None,
            "is_star": self.is_star,
        }


@dataclass
class OrderByField:
    """A field in an ORDER BY clause."""

    name: str
    order: SortOrder = SortOrder.ASC

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "order": self.order.value}


# =============================================================================
# Node Reference
# =============================================================================


@dataclass
class NodeRef:
    """A reference to a node in the graph."""

    name: str
    is_qualified: bool = False  # True if contains dots (e.g., module.class.method)
    is_quoted: bool = False  # True if was quoted in query

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "is_qualified": self.is_qualified,
            "is_quoted": self.is_quoted,
        }


# =============================================================================
# Query Types
# =============================================================================


@dataclass
class TemporalClause:
    """Temporal modifier for queries (AT or BETWEEN).

    Examples:
        AT "abc123"
        BETWEEN "abc123" AND "def456"
    """

    clause_type: str  # "at" or "between"
    commit1: str
    commit2: str | None = None  # Only for BETWEEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_type": self.clause_type,
            "commit1": self.commit1,
            "commit2": self.commit2,
        }


@dataclass
class SelectQuery:
    """A SELECT query.

    Examples:
        SELECT * FROM functions
        SELECT name, complexity FROM functions WHERE complexity > 20
        SELECT COUNT(*) FROM classes
        SELECT * FROM functions AT "abc123"
    """

    query_type: QueryType = field(default=QueryType.SELECT, init=False)
    fields: list[SelectField] = field(default_factory=list)
    node_type: NodeTypeFilter = NodeTypeFilter.NODES
    where: Condition | None = None
    temporal: TemporalClause | None = None
    order_by: list[OrderByField] = field(default_factory=list)
    limit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "fields": [f.to_dict() for f in self.fields],
            "node_type": self.node_type.value,
            "where": self.where.to_dict() if self.where else None,
            "temporal": self.temporal.to_dict() if self.temporal else None,
            "order_by": [o.to_dict() for o in self.order_by],
            "limit": self.limit,
        }


@dataclass
class ShowQuery:
    """A SHOW query for graph traversal.

    Examples:
        SHOW dependencies OF MUbase
        SHOW dependents OF "cli.py" DEPTH 3
    """

    query_type: QueryType = field(default=QueryType.SHOW, init=False)
    show_type: ShowType = ShowType.DEPENDENCIES
    target: NodeRef = field(default_factory=lambda: NodeRef(""))
    depth: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "show_type": self.show_type.value,
            "target": self.target.to_dict(),
            "depth": self.depth,
        }


@dataclass
class FindCondition:
    """The condition for a FIND query."""

    condition_type: FindConditionType
    target: NodeRef | None = None  # For CALLING, INHERITING, etc.
    pattern: str | None = None  # For MATCHING, WITH_DECORATOR, etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_type": self.condition_type.value,
            "target": self.target.to_dict() if self.target else None,
            "pattern": self.pattern,
        }


@dataclass
class FindQuery:
    """A FIND query for pattern-based search.

    Examples:
        FIND functions CALLING parse_file
        FIND functions WITH DECORATOR "@async"
        FIND classes INHERITING BaseModel
    """

    query_type: QueryType = field(default=QueryType.FIND, init=False)
    node_type: NodeTypeFilter = NodeTypeFilter.FUNCTIONS
    condition: FindCondition = field(
        default_factory=lambda: FindCondition(FindConditionType.MATCHING)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "node_type": self.node_type.value,
            "condition": self.condition.to_dict(),
        }


@dataclass
class PathQuery:
    """A PATH query for finding shortest paths.

    Examples:
        PATH FROM cli TO parser MAX DEPTH 5
        PATH FROM a TO b VIA imports
    """

    query_type: QueryType = field(default=QueryType.PATH, init=False)
    from_node: NodeRef = field(default_factory=lambda: NodeRef(""))
    to_node: NodeRef = field(default_factory=lambda: NodeRef(""))
    max_depth: int = 10
    via_edge: EdgeTypeFilter | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "from_node": self.from_node.to_dict(),
            "to_node": self.to_node.to_dict(),
            "max_depth": self.max_depth,
            "via_edge": self.via_edge.value if self.via_edge else None,
        }


@dataclass
class AnalyzeQuery:
    """An ANALYZE query for built-in analysis.

    Examples:
        ANALYZE complexity
        ANALYZE coupling FOR kernel
    """

    query_type: QueryType = field(default=QueryType.ANALYZE, init=False)
    analysis_type: AnalysisType = AnalysisType.COMPLEXITY
    target: NodeRef | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "analysis_type": self.analysis_type.value,
            "target": self.target.to_dict() if self.target else None,
        }


@dataclass
class HistoryQuery:
    """A HISTORY query for viewing node change history.

    Examples:
        HISTORY OF MUbase
        HISTORY OF "cli.py" LIMIT 10
    """

    query_type: QueryType = field(default=QueryType.HISTORY, init=False)
    target: NodeRef = field(default_factory=lambda: NodeRef(""))
    limit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "target": self.target.to_dict(),
            "limit": self.limit,
        }


@dataclass
class BlameQuery:
    """A BLAME query for showing who changed what.

    Examples:
        BLAME MUbase
        BLAME "cli.py"
    """

    query_type: QueryType = field(default=QueryType.BLAME, init=False)
    target: NodeRef = field(default_factory=lambda: NodeRef(""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "target": self.target.to_dict(),
        }


@dataclass
class DescribeQuery:
    """A DESCRIBE query for schema introspection.

    Examples:
        DESCRIBE tables
        DESCRIBE classes
        DESCRIBE columns FROM functions
    """

    query_type: QueryType = field(default=QueryType.DESCRIBE, init=False)
    target: DescribeTarget = DescribeTarget.TABLES
    node_type: NodeTypeFilter | None = None  # For DESCRIBE COLUMNS FROM

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "target": self.target.value,
            "node_type": self.node_type.value if self.node_type else None,
        }


@dataclass
class CyclesQuery:
    """A FIND CYCLES query for detecting circular dependencies.

    Uses petgraph's Kosaraju algorithm via GraphManager for O(V+E) cycle detection.

    Examples:
        FIND CYCLES
        FIND CYCLES WHERE edge_type = 'imports'
        FIND CYCLES WHERE edge_type IN ('imports', 'calls')
    """

    query_type: QueryType = field(default=QueryType.FIND_CYCLES, init=False)
    edge_types: list[str] = field(default_factory=list)  # Empty = all edge types

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_type": self.query_type.value,
            "edge_types": self.edge_types,
        }


# =============================================================================
# Union Type
# =============================================================================

Query = (
    SelectQuery
    | ShowQuery
    | FindQuery
    | PathQuery
    | AnalyzeQuery
    | HistoryQuery
    | BlameQuery
    | DescribeQuery
    | CyclesQuery
)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Enums
    "QueryType",
    "DescribeTarget",
    "NodeTypeFilter",
    "ShowType",
    "FindConditionType",
    "EdgeTypeFilter",
    "AnalysisType",
    "ComparisonOperator",
    "SortOrder",
    "AggregateFunction",
    # Value types
    "Value",
    # Condition types
    "Comparison",
    "Condition",
    # Field types
    "SelectField",
    "OrderByField",
    # Node reference
    "NodeRef",
    # Temporal types
    "TemporalClause",
    # Query types
    "SelectQuery",
    "ShowQuery",
    "FindCondition",
    "FindQuery",
    "PathQuery",
    "AnalyzeQuery",
    "HistoryQuery",
    "BlameQuery",
    "DescribeQuery",
    "CyclesQuery",
    # Union type
    "Query",
]
