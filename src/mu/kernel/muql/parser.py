"""MUQL Parser - Parses query strings into AST nodes.

Uses Lark for parsing and transforms parse trees into AST dataclasses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lark import Lark, Token, Transformer
from lark.exceptions import LarkError, UnexpectedCharacters, UnexpectedToken

from mu.kernel.muql.ast import (
    AggregateFunction,
    AnalysisType,
    AnalyzeQuery,
    Comparison,
    ComparisonOperator,
    Condition,
    EdgeTypeFilter,
    FindCondition,
    FindConditionType,
    FindQuery,
    NodeRef,
    NodeTypeFilter,
    OrderByField,
    PathQuery,
    Query,
    SelectField,
    SelectQuery,
    ShowQuery,
    ShowType,
    SortOrder,
    Value,
)

# =============================================================================
# Parse Error
# =============================================================================


class MUQLSyntaxError(Exception):
    """Error raised when a MUQL query has invalid syntax."""

    def __init__(self, message: str, line: int | None = None, column: int | None = None):
        self.line = line
        self.column = column
        super().__init__(message)


# =============================================================================
# Lark Transformer
# =============================================================================


class MUQLTransformer(Transformer[Token, Any]):
    """Transforms Lark parse tree into MUQL AST nodes."""

    # -------------------------------------------------------------------------
    # Values
    # -------------------------------------------------------------------------

    def string_value(self, items: list[Token]) -> Value:
        """Extract string value, removing quotes."""
        raw = str(items[0])
        # Remove surrounding quotes (single or double)
        value = raw[1:-1]
        return Value(value=value, type="string")

    def number_value(self, items: list[Token]) -> Value:
        """Convert number token to int."""
        return Value(value=int(str(items[0])), type="number")

    def true_value(self, items: list[Token]) -> Value:
        return Value(value=True, type="boolean")

    def false_value(self, items: list[Token]) -> Value:
        return Value(value=False, type="boolean")

    def null_value(self, items: list[Token]) -> Value:
        return Value(value=None, type="null")

    def value_list(self, items: list[Value]) -> list[Value]:
        return items

    # -------------------------------------------------------------------------
    # Comparison Operators
    # -------------------------------------------------------------------------

    def comparison_op(self, items: list[Token]) -> ComparisonOperator:
        op = str(items[0]).upper()
        mapping = {
            "=": ComparisonOperator.EQ,
            "!=": ComparisonOperator.NEQ,
            "<>": ComparisonOperator.NEQ,
            ">": ComparisonOperator.GT,
            "<": ComparisonOperator.LT,
            ">=": ComparisonOperator.GTE,
            "<=": ComparisonOperator.LTE,
            "LIKE": ComparisonOperator.LIKE,
        }
        return mapping.get(op, ComparisonOperator.EQ)

    # -------------------------------------------------------------------------
    # Comparisons
    # -------------------------------------------------------------------------

    def simple_comparison(self, items: list[Any]) -> Comparison:
        field, op, value = items
        return Comparison(field=str(field), operator=op, value=value)

    def in_comparison(self, items: list[Any]) -> Comparison:
        field, values = items
        return Comparison(field=str(field), operator=ComparisonOperator.IN, value=values)

    def not_in_comparison(self, items: list[Any]) -> Comparison:
        field, values = items
        return Comparison(field=str(field), operator=ComparisonOperator.NOT_IN, value=values)

    def contains_comparison(self, items: list[Any]) -> Comparison:
        field, value = items
        return Comparison(field=str(field), operator=ComparisonOperator.CONTAINS, value=value)

    def grouped_condition(self, items: list[Any]) -> Comparison:
        condition = items[0]
        if isinstance(condition, Condition) and condition.comparisons:
            return condition.comparisons[0]
        return Comparison(
            field="", operator=ComparisonOperator.EQ, value=Value(value=None, type="null")
        )

    # -------------------------------------------------------------------------
    # Conditions (AND/OR)
    # -------------------------------------------------------------------------

    def and_condition(self, items: list[Any]) -> Condition:
        flat_comparisons: list[Comparison] = []
        for item in items:
            if isinstance(item, Comparison):
                flat_comparisons.append(item)
            elif isinstance(item, Condition):
                flat_comparisons.extend(item.comparisons)
        return Condition(comparisons=flat_comparisons, operator="and")

    def or_condition(self, items: list[Condition]) -> Condition:
        if len(items) == 1:
            return items[0]
        return Condition(comparisons=[], operator="or", nested=items)

    # -------------------------------------------------------------------------
    # SELECT Fields
    # -------------------------------------------------------------------------

    def field(self, items: list[Token]) -> SelectField:
        return SelectField(name=str(items[0]))

    def count_star(self, items: list[Token]) -> SelectField:
        return SelectField(name="*", aggregate=AggregateFunction.COUNT, is_star=True)

    def count_field(self, items: list[Token]) -> SelectField:
        # Items: [COUNT_KW, IDENTIFIER]
        field_name = str(items[-1])  # Last item is the field name
        return SelectField(name=field_name, aggregate=AggregateFunction.COUNT)

    def avg_field(self, items: list[Token]) -> SelectField:
        field_name = str(items[-1])
        return SelectField(name=field_name, aggregate=AggregateFunction.AVG)

    def max_agg_field(self, items: list[Token]) -> SelectField:
        field_name = str(items[-1])
        return SelectField(name=field_name, aggregate=AggregateFunction.MAX)

    def min_agg_field(self, items: list[Token]) -> SelectField:
        field_name = str(items[-1])
        return SelectField(name=field_name, aggregate=AggregateFunction.MIN)

    def sum_field(self, items: list[Token]) -> SelectField:
        field_name = str(items[-1])
        return SelectField(name=field_name, aggregate=AggregateFunction.SUM)

    def field_list(self, items: list[SelectField]) -> list[SelectField]:
        return items

    def select_list(self, items: list[Any]) -> list[SelectField]:
        first = items[0] if items else None
        if isinstance(first, Token) and str(first) == "*":
            return [SelectField(name="*", is_star=True)]
        if isinstance(first, list):
            return first
        if isinstance(first, SelectField):
            return [first]
        return items

    # -------------------------------------------------------------------------
    # ORDER BY
    # -------------------------------------------------------------------------

    def order_direction(self, items: list[Token]) -> SortOrder:
        direction = str(items[0]).upper()
        return SortOrder.DESC if direction == "DESC" else SortOrder.ASC

    def order_field(self, items: list[Any]) -> OrderByField:
        name = items[0]
        direction = items[1] if len(items) > 1 else SortOrder.ASC
        return OrderByField(name=str(name), order=direction)

    def order_by_clause(self, items: list[Any]) -> list[OrderByField]:
        # items: [ORDER_KW, BY_KW, order_field, ...]
        result: list[OrderByField] = []
        for item in items:
            if isinstance(item, OrderByField):
                result.append(item)
        return result

    # -------------------------------------------------------------------------
    # LIMIT
    # -------------------------------------------------------------------------

    def limit_clause(self, items: list[Token]) -> int:
        # items contains [LIMIT_KW, NUMBER]
        for item in items:
            if str(item).isdigit():
                return int(str(item))
        return 100  # Default

    # -------------------------------------------------------------------------
    # WHERE
    # -------------------------------------------------------------------------

    def where_clause(self, items: list[Any]) -> Condition:
        # items: [WHERE_KW, condition]
        for item in items:
            if isinstance(item, Condition):
                return item
        return Condition(comparisons=[], operator="and")

    # -------------------------------------------------------------------------
    # Node Types
    # -------------------------------------------------------------------------

    def functions_type(self, items: list[Any]) -> NodeTypeFilter:
        return NodeTypeFilter.FUNCTIONS

    def classes_type(self, items: list[Any]) -> NodeTypeFilter:
        return NodeTypeFilter.CLASSES

    def modules_type(self, items: list[Any]) -> NodeTypeFilter:
        return NodeTypeFilter.MODULES

    def nodes_type(self, items: list[Any]) -> NodeTypeFilter:
        return NodeTypeFilter.NODES

    def node_type(self, items: list[NodeTypeFilter]) -> NodeTypeFilter:
        return items[0]

    # -------------------------------------------------------------------------
    # SELECT Query
    # -------------------------------------------------------------------------

    def select_query(self, items: list[Any]) -> SelectQuery:
        # Items: [SELECT_KW, select_list, FROM_KW, node_type, where?, order_by?, limit?]
        # Filter out keyword tokens and None values
        fields: list[SelectField] = []
        node_type: NodeTypeFilter = NodeTypeFilter.NODES
        where: Condition | None = None
        order_by: list[OrderByField] = []
        limit: int | None = None

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                # Skip keyword tokens
                continue
            if isinstance(item, list):
                if item and isinstance(item[0], SelectField):
                    fields = item
                elif item and isinstance(item[0], OrderByField):
                    order_by = item
            elif isinstance(item, SelectField):
                fields = [item]
            elif isinstance(item, NodeTypeFilter):
                node_type = item
            elif isinstance(item, Condition):
                where = item
            elif isinstance(item, int):
                limit = item

        return SelectQuery(
            fields=fields,
            node_type=node_type,
            where=where,
            order_by=order_by,
            limit=limit,
        )

    # -------------------------------------------------------------------------
    # Node References
    # -------------------------------------------------------------------------

    def quoted_node_ref(self, items: list[Token]) -> NodeRef:
        raw = str(items[0])
        name = raw[1:-1]  # Remove quotes
        return NodeRef(name=name, is_quoted=True)

    def identifier_node_ref(self, items: list[Token]) -> NodeRef:
        return NodeRef(name=str(items[0]))

    def qualified_name(self, items: list[Token]) -> str:
        return ".".join(str(p) for p in items)

    def qualified_node_ref(self, items: list[str]) -> NodeRef:
        return NodeRef(name=items[0], is_qualified=True)

    def node_ref(self, items: list[NodeRef]) -> NodeRef:
        return items[0]

    # -------------------------------------------------------------------------
    # SHOW Query
    # -------------------------------------------------------------------------

    def show_dependencies(self, items: list[Any]) -> ShowType:
        return ShowType.DEPENDENCIES

    def show_dependents(self, items: list[Any]) -> ShowType:
        return ShowType.DEPENDENTS

    def show_callers(self, items: list[Any]) -> ShowType:
        return ShowType.CALLERS

    def show_callees(self, items: list[Any]) -> ShowType:
        return ShowType.CALLEES

    def show_inheritance(self, items: list[Any]) -> ShowType:
        return ShowType.INHERITANCE

    def show_implementations(self, items: list[Any]) -> ShowType:
        return ShowType.IMPLEMENTATIONS

    def show_children(self, items: list[Any]) -> ShowType:
        return ShowType.CHILDREN

    def show_parents(self, items: list[Any]) -> ShowType:
        return ShowType.PARENTS

    def show_type(self, items: list[ShowType]) -> ShowType:
        return items[0]

    def depth_clause(self, items: list[Token]) -> int:
        # items contains [DEPTH_KW, NUMBER]
        for item in items:
            if str(item).isdigit():
                return int(str(item))
        return 1  # Default

    def show_query(self, items: list[Any]) -> ShowQuery:
        # Items: [SHOW_KW, show_type, OF_KW, node_ref, depth_clause?]
        # Filter out keyword tokens and None values
        show_type: ShowType = ShowType.DEPENDENCIES
        target: NodeRef = NodeRef(name="")
        depth: int = 1

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, ShowType):
                show_type = item
            elif isinstance(item, NodeRef):
                target = item
            elif isinstance(item, int):
                depth = item

        return ShowQuery(show_type=show_type, target=target, depth=depth)

    # -------------------------------------------------------------------------
    # FIND Query
    # -------------------------------------------------------------------------

    def find_functions(self, items: list[Any]) -> NodeTypeFilter:
        return NodeTypeFilter.FUNCTIONS

    def find_classes(self, items: list[Any]) -> NodeTypeFilter:
        return NodeTypeFilter.CLASSES

    def find_modules(self, items: list[Any]) -> NodeTypeFilter:
        return NodeTypeFilter.MODULES

    def find_methods(self, items: list[Any]) -> NodeTypeFilter:
        return NodeTypeFilter.METHODS

    def find_node_type(self, items: list[Any]) -> NodeTypeFilter:
        for item in items:
            if isinstance(item, NodeTypeFilter):
                return item
        return NodeTypeFilter.FUNCTIONS

    def _extract_node_ref(self, items: list[Any]) -> NodeRef:
        """Extract NodeRef from items, filtering out tokens."""
        for item in items:
            if isinstance(item, NodeRef):
                return item
        return NodeRef(name="")

    def find_calling(self, items: list[Any]) -> FindCondition:
        return FindCondition(
            condition_type=FindConditionType.CALLING, target=self._extract_node_ref(items)
        )

    def find_called_by(self, items: list[Any]) -> FindCondition:
        return FindCondition(
            condition_type=FindConditionType.CALLED_BY, target=self._extract_node_ref(items)
        )

    def find_importing(self, items: list[Any]) -> FindCondition:
        return FindCondition(
            condition_type=FindConditionType.IMPORTING, target=self._extract_node_ref(items)
        )

    def find_imported_by(self, items: list[Any]) -> FindCondition:
        return FindCondition(
            condition_type=FindConditionType.IMPORTED_BY, target=self._extract_node_ref(items)
        )

    def find_inheriting(self, items: list[Any]) -> FindCondition:
        return FindCondition(
            condition_type=FindConditionType.INHERITING, target=self._extract_node_ref(items)
        )

    def find_implementing(self, items: list[Any]) -> FindCondition:
        return FindCondition(
            condition_type=FindConditionType.IMPLEMENTING, target=self._extract_node_ref(items)
        )

    def find_mutating(self, items: list[Any]) -> FindCondition:
        return FindCondition(
            condition_type=FindConditionType.MUTATING, target=self._extract_node_ref(items)
        )

    def find_with_decorator(self, items: list[Token]) -> FindCondition:
        # items: [WITH_KW, DECORATOR_KW, STRING]
        for item in items:
            raw = str(item)
            if raw.startswith('"') or raw.startswith("'"):
                value = raw[1:-1]
                return FindCondition(condition_type=FindConditionType.WITH_DECORATOR, pattern=value)
        return FindCondition(condition_type=FindConditionType.WITH_DECORATOR, pattern="")

    def find_with_annotation(self, items: list[Token]) -> FindCondition:
        # items: [WITH_KW, ANNOTATION_KW, STRING]
        for item in items:
            raw = str(item)
            if raw.startswith('"') or raw.startswith("'"):
                value = raw[1:-1]
                return FindCondition(
                    condition_type=FindConditionType.WITH_ANNOTATION, pattern=value
                )
        return FindCondition(condition_type=FindConditionType.WITH_ANNOTATION, pattern="")

    def find_matching(self, items: list[Token]) -> FindCondition:
        # items: [MATCHING_KW, STRING]
        for item in items:
            raw = str(item)
            if raw.startswith('"') or raw.startswith("'"):
                value = raw[1:-1]
                return FindCondition(condition_type=FindConditionType.MATCHING, pattern=value)
        return FindCondition(condition_type=FindConditionType.MATCHING, pattern="")

    def find_similar_to(self, items: list[Any]) -> FindCondition:
        return FindCondition(
            condition_type=FindConditionType.SIMILAR_TO, target=self._extract_node_ref(items)
        )

    def find_condition(self, items: list[Any]) -> FindCondition:
        for item in items:
            if isinstance(item, FindCondition):
                return item
        return FindCondition(condition_type=FindConditionType.MATCHING, pattern="")

    def find_query(self, items: list[Any]) -> FindQuery:
        # Items: [FIND_KW, find_node_type, find_condition]
        node_type: NodeTypeFilter = NodeTypeFilter.FUNCTIONS
        condition: FindCondition | None = None

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, NodeTypeFilter):
                node_type = item
            elif isinstance(item, FindCondition):
                condition = item

        return FindQuery(
            node_type=node_type,
            condition=condition or FindCondition(FindConditionType.MATCHING),
        )

    # -------------------------------------------------------------------------
    # PATH Query
    # -------------------------------------------------------------------------

    def max_depth_clause(self, items: list[Token]) -> int:
        # items contains [MAX_KW, DEPTH_KW, NUMBER]
        for item in items:
            if str(item).isdigit():
                return int(str(item))
        return 10  # Default

    def edge_calls(self, items: list[Any]) -> EdgeTypeFilter:
        return EdgeTypeFilter.CALLS

    def edge_imports(self, items: list[Any]) -> EdgeTypeFilter:
        return EdgeTypeFilter.IMPORTS

    def edge_inherits(self, items: list[Any]) -> EdgeTypeFilter:
        return EdgeTypeFilter.INHERITS

    def edge_uses(self, items: list[Any]) -> EdgeTypeFilter:
        return EdgeTypeFilter.USES

    def edge_contains(self, items: list[Any]) -> EdgeTypeFilter:
        return EdgeTypeFilter.CONTAINS

    def edge_type(self, items: list[EdgeTypeFilter]) -> EdgeTypeFilter:
        return items[0]

    def via_clause(self, items: list[Any]) -> EdgeTypeFilter:
        # items: [VIA_KW, edge_type]
        for item in items:
            if isinstance(item, EdgeTypeFilter):
                return item
        return EdgeTypeFilter.IMPORTS  # Default

    def path_query(self, items: list[Any]) -> PathQuery:
        # Items: [PATH_KW, FROM_KW, node_ref, TO_KW, node_ref, max_depth?, via_edge?]
        from_node: NodeRef = NodeRef(name="")
        to_node: NodeRef = NodeRef(name="")
        max_depth: int = 10
        via_edge: EdgeTypeFilter | None = None

        node_refs: list[NodeRef] = []
        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, NodeRef):
                node_refs.append(item)
            elif isinstance(item, int):
                max_depth = item
            elif isinstance(item, EdgeTypeFilter):
                via_edge = item

        if len(node_refs) >= 2:
            from_node = node_refs[0]
            to_node = node_refs[1]
        elif len(node_refs) == 1:
            from_node = node_refs[0]

        return PathQuery(
            from_node=from_node,
            to_node=to_node,
            max_depth=max_depth,
            via_edge=via_edge,
        )

    # -------------------------------------------------------------------------
    # ANALYZE Query
    # -------------------------------------------------------------------------

    def analyze_coupling(self, items: list[Any]) -> AnalysisType:
        return AnalysisType.COUPLING

    def analyze_cohesion(self, items: list[Any]) -> AnalysisType:
        return AnalysisType.COHESION

    def analyze_complexity(self, items: list[Any]) -> AnalysisType:
        return AnalysisType.COMPLEXITY

    def analyze_hotspots(self, items: list[Any]) -> AnalysisType:
        return AnalysisType.HOTSPOTS

    def analyze_circular(self, items: list[Any]) -> AnalysisType:
        return AnalysisType.CIRCULAR

    def analyze_unused(self, items: list[Any]) -> AnalysisType:
        return AnalysisType.UNUSED

    def analyze_impact(self, items: list[Any]) -> AnalysisType:
        return AnalysisType.IMPACT

    def analysis_type(self, items: list[AnalysisType]) -> AnalysisType:
        return items[0]

    def for_clause(self, items: list[Any]) -> NodeRef:
        # items: [FOR_KW, node_ref]
        for item in items:
            if isinstance(item, NodeRef):
                return item
        return NodeRef(name="")

    def analyze_query(self, items: list[Any]) -> AnalyzeQuery:
        # Items: [ANALYZE_KW, analysis_type, for_clause?]
        analysis_type: AnalysisType = AnalysisType.COMPLEXITY
        target: NodeRef | None = None

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, AnalysisType):
                analysis_type = item
            elif isinstance(item, NodeRef):
                target = item

        return AnalyzeQuery(analysis_type=analysis_type, target=target)


# =============================================================================
# Parser Class
# =============================================================================


class MUQLParser:
    """Parser for MUQL queries.

    Loads the grammar file and provides methods for parsing query strings.
    """

    def __init__(self) -> None:
        """Initialize the parser with the MUQL grammar."""
        grammar_path = Path(__file__).parent / "grammar.lark"
        self._grammar = grammar_path.read_text()
        # Use Earley parser to handle keyword/identifier disambiguation
        # properly. LALR has issues with case-insensitive keyword matching.
        self._lark = Lark(
            self._grammar,
            start="start",
            parser="earley",
        )
        self._transformer = MUQLTransformer()

    def parse(self, query: str) -> Query:
        """Parse a MUQL query string into an AST node.

        Args:
            query: The MUQL query string.

        Returns:
            A Query AST node (SelectQuery, ShowQuery, FindQuery, PathQuery, or AnalyzeQuery).

        Raises:
            MUQLSyntaxError: If the query has invalid syntax.
        """
        try:
            tree = self._lark.parse(query)
            result = self._transformer.transform(tree)
            if not isinstance(result, (SelectQuery, ShowQuery, FindQuery, PathQuery, AnalyzeQuery)):
                raise MUQLSyntaxError(f"Unexpected parse result: {type(result)}")
            return result
        except UnexpectedCharacters as e:
            raise MUQLSyntaxError(
                f"Unexpected character '{e.char}' at position {e.column}",
                line=e.line,
                column=e.column,
            ) from e
        except UnexpectedToken as e:
            expected = ", ".join(sorted(e.expected)[:5])
            if len(e.expected) > 5:
                expected += ", ..."
            raise MUQLSyntaxError(
                f"Unexpected token '{e.token}'. Expected one of: {expected}",
                line=e.line,
                column=e.column,
            ) from e
        except LarkError as e:
            raise MUQLSyntaxError(str(e)) from e


# =============================================================================
# Convenience Function
# =============================================================================


_default_parser: MUQLParser | None = None


def parse(query: str) -> Query:
    """Parse a MUQL query string.

    Convenience function that uses a shared parser instance.

    Args:
        query: The MUQL query string.

    Returns:
        A Query AST node.

    Raises:
        MUQLSyntaxError: If the query has invalid syntax.
    """
    global _default_parser
    if _default_parser is None:
        _default_parser = MUQLParser()
    return _default_parser.parse(query)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "MUQLParser",
    "MUQLTransformer",
    "MUQLSyntaxError",
    "parse",
]
