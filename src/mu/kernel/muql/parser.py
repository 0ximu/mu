"""MUQL Parser - Parses query strings into AST nodes.

Uses Lark for parsing and transforms parse trees into AST dataclasses.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lark import Lark, Token, Transformer
from lark.exceptions import LarkError, UnexpectedCharacters, UnexpectedToken

from mu.kernel.muql.ast import (
    AggregateComparison,
    AggregateFunction,
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
    FindCondition,
    FindConditionType,
    FindQuery,
    GroupByField,
    HistoryQuery,
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
    TemporalClause,
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
        # items: [IDENTIFIER, value_list] - IN_KW is filtered out by Lark
        field = items[0]
        values = items[-1]  # value_list is always last
        return Comparison(field=str(field), operator=ComparisonOperator.IN, value=values)

    def not_in_comparison(self, items: list[Any]) -> Comparison:
        # items: [IDENTIFIER, NOT_KW, value_list] - NOT_KW token may be present
        # Extract field (first item) and values (last item, which is the value_list)
        field = items[0]
        values = items[-1]  # value_list is always last
        return Comparison(field=str(field), operator=ComparisonOperator.NOT_IN, value=values)

    def contains_comparison(self, items: list[Any]) -> Comparison:
        # items: [IDENTIFIER, value] - CONTAINS_KW is filtered out by Lark
        field = items[0]
        value = items[-1]  # value is always last
        return Comparison(field=str(field), operator=ComparisonOperator.CONTAINS, value=value)

    def grouped_condition(self, items: list[Any]) -> Comparison | AggregateComparison:
        condition = items[0]
        if isinstance(condition, Condition) and condition.comparisons:
            return condition.comparisons[0]
        return Comparison(
            field="", operator=ComparisonOperator.EQ, value=Value(value=None, type="null")
        )

    # -------------------------------------------------------------------------
    # Aggregate Expressions (for HAVING clause)
    # -------------------------------------------------------------------------

    def agg_count_star(self, items: list[Any]) -> tuple[AggregateFunction, str]:
        """COUNT(*) aggregate expression."""
        return (AggregateFunction.COUNT, "*")

    def agg_count_field(self, items: list[Token]) -> tuple[AggregateFunction, str]:
        """COUNT(field) aggregate expression."""
        # Find IDENTIFIER token (skip COUNT_KW)
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                return (AggregateFunction.COUNT, str(item))
        return (AggregateFunction.COUNT, "*")

    def agg_avg_field(self, items: list[Token]) -> tuple[AggregateFunction, str]:
        """AVG(field) aggregate expression."""
        # Find IDENTIFIER token (skip AVG_KW)
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                return (AggregateFunction.AVG, str(item))
        return (AggregateFunction.AVG, "*")

    def agg_max_field(self, items: list[Token]) -> tuple[AggregateFunction, str]:
        """MAX(field) aggregate expression."""
        # Find IDENTIFIER token (skip MAX_KW)
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                return (AggregateFunction.MAX, str(item))
        return (AggregateFunction.MAX, "*")

    def agg_min_field(self, items: list[Token]) -> tuple[AggregateFunction, str]:
        """MIN(field) aggregate expression."""
        # Find IDENTIFIER token (skip MIN_KW)
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                return (AggregateFunction.MIN, str(item))
        return (AggregateFunction.MIN, "*")

    def agg_sum_field(self, items: list[Token]) -> tuple[AggregateFunction, str]:
        """SUM(field) aggregate expression."""
        # Find IDENTIFIER token (skip SUM_KW)
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                return (AggregateFunction.SUM, str(item))
        return (AggregateFunction.SUM, "*")

    def aggregate_expr(
        self, items: list[tuple[AggregateFunction, str]]
    ) -> tuple[AggregateFunction, str]:
        """Pass through aggregate expression tuple."""
        return items[0]

    def aggregate_comparison(self, items: list[Any]) -> AggregateComparison:
        """Transform aggregate comparison like COUNT(*) > 10."""
        # items: [aggregate_expr (tuple), comparison_op, value]
        agg_tuple, op, value = items
        agg_func, field = agg_tuple
        return AggregateComparison(aggregate=agg_func, field=field, operator=op, value=value)

    # -------------------------------------------------------------------------
    # Conditions (AND/OR)
    # -------------------------------------------------------------------------

    def and_condition(self, items: list[Any]) -> Condition:
        flat_comparisons: list[Comparison | AggregateComparison] = []
        for item in items:
            if isinstance(item, (Comparison, AggregateComparison)):
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

    def _extract_alias(self, items: list[Any]) -> str | None:
        """Extract alias from items if AS_KW is present."""
        # Look for AS_KW followed by IDENTIFIER
        for i, item in enumerate(items):
            if isinstance(item, Token) and item.type == "AS_KW" and i + 1 < len(items):
                next_item = items[i + 1]
                if isinstance(next_item, Token) and next_item.type == "IDENTIFIER":
                    return str(next_item)
        return None

    def named_field(self, items: list[Any]) -> SelectField:
        # Items: [IDENTIFIER] or [IDENTIFIER, AS_KW, IDENTIFIER] (with possible Nones)
        name = str(items[0])
        alias = self._extract_alias(items)
        return SelectField(name=name, alias=alias)

    def count_star(self, items: list[Any]) -> SelectField:
        # Items: [] or [AS_KW, IDENTIFIER] (with possible Nones)
        alias = self._extract_alias(items)
        return SelectField(name="*", aggregate=AggregateFunction.COUNT, is_star=True, alias=alias)

    def count_field(self, items: list[Any]) -> SelectField:
        # Items: [COUNT_KW, IDENTIFIER, None?, None?] or [COUNT_KW, IDENTIFIER, AS_KW, IDENTIFIER]
        # Find the field name (first IDENTIFIER after COUNT_KW)
        field_name = None
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                field_name = str(item)
                break
        alias = self._extract_alias(items)
        return SelectField(name=field_name or "*", aggregate=AggregateFunction.COUNT, alias=alias)

    def avg_field(self, items: list[Any]) -> SelectField:
        # Items: [AVG_KW, IDENTIFIER, ...optional alias...]
        field_name = None
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                field_name = str(item)
                break
        alias = self._extract_alias(items)
        return SelectField(name=field_name or "*", aggregate=AggregateFunction.AVG, alias=alias)

    def max_agg_field(self, items: list[Any]) -> SelectField:
        # Items: [MAX_KW, IDENTIFIER, ...optional alias...]
        field_name = None
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                field_name = str(item)
                break
        alias = self._extract_alias(items)
        return SelectField(name=field_name or "*", aggregate=AggregateFunction.MAX, alias=alias)

    def min_agg_field(self, items: list[Any]) -> SelectField:
        # Items: [MIN_KW, IDENTIFIER, ...optional alias...]
        field_name = None
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                field_name = str(item)
                break
        alias = self._extract_alias(items)
        return SelectField(name=field_name or "*", aggregate=AggregateFunction.MIN, alias=alias)

    def sum_field(self, items: list[Any]) -> SelectField:
        # Items: [SUM_KW, IDENTIFIER, ...optional alias...]
        field_name = None
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                field_name = str(item)
                break
        alias = self._extract_alias(items)
        return SelectField(name=field_name or "*", aggregate=AggregateFunction.SUM, alias=alias)

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
    # GROUP BY
    # -------------------------------------------------------------------------

    def group_field(self, items: list[Token]) -> GroupByField:
        """Extract a GROUP BY field name."""
        return GroupByField(name=str(items[0]))

    def group_by_clause(self, items: list[Any]) -> list[GroupByField]:
        """Transform GROUP BY clause to list of GroupByField."""
        # items: [GROUP_KW, BY_KW, group_field, ...]
        result: list[GroupByField] = []
        for item in items:
            if isinstance(item, GroupByField):
                result.append(item)
        return result

    # -------------------------------------------------------------------------
    # HAVING
    # -------------------------------------------------------------------------

    def having_clause(self, items: list[Any]) -> Condition:
        """Transform HAVING clause to Condition."""
        # items: [HAVING_KW, condition]
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
        # Items: [SELECT_KW, select_list, FROM_KW, node_type, where?, temporal?, group_by?, having?, order_by?, limit?]
        # Filter out keyword tokens and None values
        fields: list[SelectField] = []
        node_type: NodeTypeFilter = NodeTypeFilter.NODES
        where: Condition | None = None
        temporal: TemporalClause | None = None
        group_by: list[GroupByField] = []
        having: Condition | None = None
        order_by: list[OrderByField] = []
        limit: int | None = None

        # Track if we've seen group_by to distinguish where from having
        seen_group_by = False

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
                elif item and isinstance(item[0], GroupByField):
                    group_by = item
                    seen_group_by = True
            elif isinstance(item, SelectField):
                fields = [item]
            elif isinstance(item, NodeTypeFilter):
                node_type = item
            elif isinstance(item, Condition):
                # Condition can be WHERE or HAVING - HAVING comes after GROUP BY
                if seen_group_by and having is None:
                    having = item
                else:
                    where = item
            elif isinstance(item, TemporalClause):
                temporal = item
            elif isinstance(item, int):
                limit = item

        return SelectQuery(
            fields=fields,
            node_type=node_type,
            where=where,
            temporal=temporal,
            group_by=group_by,
            having=having,
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

    def show_impact(self, items: list[Any]) -> ShowType:
        return ShowType.IMPACT

    def show_ancestors(self, items: list[Any]) -> ShowType:
        return ShowType.ANCESTORS

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
    # FIND CYCLES Query (Graph cycle detection)
    # -------------------------------------------------------------------------

    def edge_type_string(self, items: list[Token]) -> str:
        """Extract edge type string, removing quotes."""
        raw = str(items[0])
        return raw[1:-1]  # Remove quotes

    def edge_type_value(self, items: list[str]) -> str:
        """Pass through edge type value."""
        return items[0]

    def edge_type_list(self, items: list[str]) -> list[str]:
        """Collect edge type values into list."""
        return list(items)

    def edge_type_filter(self, items: list[Any]) -> list[str]:
        """Transform edge type filter to list of edge types.

        Handles both:
        - WHERE edge_type = 'imports' -> ['imports']
        - WHERE edge_type IN ('imports', 'calls') -> ['imports', 'calls']
        """
        edge_types: list[str] = []
        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, str) and not item.startswith(("=", "!", "<", ">")):
                edge_types.append(item)
            elif isinstance(item, list):
                edge_types.extend(item)
        return edge_types

    def find_cycles_query(self, items: list[Any]) -> CyclesQuery:
        """Transform FIND CYCLES query."""
        # Items: [FIND_KW, CYCLES_KW, edge_type_filter?]
        edge_types: list[str] = []

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, list):
                edge_types = item

        return CyclesQuery(edge_types=edge_types)

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
        # Items: [FIND_KW, find_node_type, find_condition, limit_clause?]
        node_type: NodeTypeFilter = NodeTypeFilter.FUNCTIONS
        condition: FindCondition | None = None
        limit: int | None = None

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, NodeTypeFilter):
                node_type = item
            elif isinstance(item, FindCondition):
                condition = item
            elif isinstance(item, int):
                limit = item

        return FindQuery(
            node_type=node_type,
            condition=condition or FindCondition(FindConditionType.MATCHING),
            limit=limit,
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

    # -------------------------------------------------------------------------
    # TEMPORAL Queries
    # -------------------------------------------------------------------------

    def quoted_commit_ref(self, items: list[Token]) -> str:
        """Extract commit reference from quoted string."""
        raw = str(items[0])
        return raw[1:-1]  # Remove quotes

    def identifier_commit_ref(self, items: list[Token]) -> str:
        """Extract commit reference from identifier."""
        return str(items[0])

    def commit_ref(self, items: list[str]) -> str:
        """Pass through commit reference."""
        return items[0]

    def at_clause(self, items: list[Any]) -> TemporalClause:
        """Transform AT clause to TemporalClause."""
        # items: [AT_KW, commit_ref_string]
        # commit_ref transformer returns a plain str, AT_KW is a Token
        # Token is a subclass of str, so we need to check Token type first
        commit = ""
        for item in items:
            if isinstance(item, Token):
                # Skip keyword tokens
                if item.type == "AT_KW":
                    continue
                # Non-keyword token, use as commit ref
                commit = str(item)
                break
            elif isinstance(item, str):
                # Plain string from commit_ref transformer
                commit = item
                break
        return TemporalClause(clause_type="at", commit1=commit)

    def between_clause(self, items: list[Any]) -> TemporalClause:
        """Transform BETWEEN clause to TemporalClause."""
        # items: [BETWEEN_KW, commit_ref_string, AND_KW, commit_ref_string]
        # Token is a subclass of str, so we need to filter out keyword tokens
        commits: list[str] = []
        for item in items:
            if isinstance(item, Token):
                # Skip keyword tokens (BETWEEN_KW, AND_KW)
                if item.type in ("BETWEEN_KW", "AND_KW"):
                    continue
                # Non-keyword token, use as commit ref
                commits.append(str(item))
            elif isinstance(item, str):
                # Plain string from commit_ref transformer
                commits.append(item)
        commit1 = commits[0] if len(commits) > 0 else ""
        commit2 = commits[1] if len(commits) > 1 else ""
        return TemporalClause(clause_type="between", commit1=commit1, commit2=commit2)

    def temporal_clause(self, items: list[TemporalClause]) -> TemporalClause:
        """Pass through temporal clause."""
        return items[0]

    def history_query(self, items: list[Any]) -> HistoryQuery:
        """Transform HISTORY query."""
        # Items: [HISTORY_KW, OF_KW, node_ref, limit_clause?]
        target: NodeRef = NodeRef(name="")
        limit: int | None = None

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, NodeRef):
                target = item
            elif isinstance(item, int):
                limit = item

        return HistoryQuery(target=target, limit=limit)

    def blame_query(self, items: list[Any]) -> BlameQuery:
        """Transform BLAME query."""
        # Items: [BLAME_KW, node_ref]
        target: NodeRef = NodeRef(name="")

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, NodeRef):
                target = item

        return BlameQuery(target=target)

    # -------------------------------------------------------------------------
    # SHOW TABLES/COLUMNS Query (SQL-compatible aliases)
    # -------------------------------------------------------------------------

    def show_tables_query(self, items: list[Any]) -> DescribeQuery:
        """SHOW TABLES -> DESCRIBE tables (SQL-compatible alias)."""
        return DescribeQuery(target=DescribeTarget.TABLES)

    def show_columns_query(self, items: list[Any]) -> DescribeQuery:
        """SHOW COLUMNS FROM <node_type> -> DESCRIBE columns from <node_type>."""
        # Extract node_type from items (filtering out keyword tokens)
        node_type: NodeTypeFilter | None = None
        for item in items:
            if isinstance(item, NodeTypeFilter):
                node_type = item
                break
        return DescribeQuery(target=DescribeTarget.COLUMNS, node_type=node_type)

    # -------------------------------------------------------------------------
    # DESCRIBE Query
    # -------------------------------------------------------------------------

    def describe_tables(self, items: list[Any]) -> DescribeTarget:
        return DescribeTarget.TABLES

    def describe_columns(self, items: list[Any]) -> tuple[DescribeTarget, NodeTypeFilter]:
        # items: [COLUMNS_KW, FROM_KW, node_type]
        node_type = NodeTypeFilter.NODES
        for item in items:
            if isinstance(item, NodeTypeFilter):
                node_type = item
        return DescribeTarget.COLUMNS, node_type

    def describe_node_type(self, items: list[Any]) -> DescribeTarget:
        # items: [node_type] -> map to DescribeTarget
        for item in items:
            if isinstance(item, NodeTypeFilter):
                mapping = {
                    NodeTypeFilter.FUNCTIONS: DescribeTarget.FUNCTIONS,
                    NodeTypeFilter.CLASSES: DescribeTarget.CLASSES,
                    NodeTypeFilter.MODULES: DescribeTarget.MODULES,
                    NodeTypeFilter.NODES: DescribeTarget.NODES,
                }
                return mapping.get(item, DescribeTarget.NODES)
        return DescribeTarget.NODES

    def describe_target(self, items: list[Any]) -> tuple[DescribeTarget, NodeTypeFilter | None]:
        # Handle different describe target types
        for item in items:
            if isinstance(item, tuple):
                return item  # (DescribeTarget.COLUMNS, node_type)
            if isinstance(item, DescribeTarget):
                return item, None
        return DescribeTarget.TABLES, None

    def describe_query(self, items: list[Any]) -> DescribeQuery:
        """Transform DESCRIBE query."""
        # Items: [DESCRIBE_KW, describe_target]
        target = DescribeTarget.TABLES
        node_type: NodeTypeFilter | None = None

        for item in items:
            if item is None:
                continue
            if isinstance(item, Token):
                continue
            if isinstance(item, tuple):
                target, node_type = item
            elif isinstance(item, DescribeTarget):
                target = item

        return DescribeQuery(target=target, node_type=node_type)


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
            if not isinstance(
                result,
                (
                    SelectQuery,
                    ShowQuery,
                    FindQuery,
                    PathQuery,
                    AnalyzeQuery,
                    HistoryQuery,
                    BlameQuery,
                    DescribeQuery,
                    CyclesQuery,
                ),
            ):
                raise MUQLSyntaxError(f"Unexpected parse result: {type(result)}")
            return result
        except UnexpectedCharacters as e:
            # Check for common mistake patterns
            suggestion = self._suggest_fix(query, e.column)
            error_msg = f"Unexpected character '{e.char}' at position {e.column}"
            if suggestion:
                error_msg += f"\n\n{suggestion}"
            raise MUQLSyntaxError(
                error_msg,
                line=e.line,
                column=e.column,
            ) from e
        except UnexpectedToken as e:
            expected = ", ".join(sorted(e.expected)[:5])
            if len(e.expected) > 5:
                expected += ", ..."
            # Check for common mistake patterns
            suggestion = self._suggest_fix(query, e.column if e.column else 0)
            error_msg = f"Unexpected token '{e.token}'. Expected one of: {expected}"
            if suggestion:
                error_msg += f"\n\n{suggestion}"
            raise MUQLSyntaxError(
                error_msg,
                line=e.line,
                column=e.column,
            ) from e
        except LarkError as e:
            raise MUQLSyntaxError(str(e)) from e

    def _suggest_fix(self, query: str, position: int) -> str | None:
        """Suggest a fix for common query mistakes.

        Args:
            query: The query string
            position: Position where the error occurred

        Returns:
            A suggestion string or None
        """
        query_lower = query.lower().strip()

        # Common pattern: type:function name:foo (key:value syntax from other tools)
        if ":" in query and not query_lower.startswith(
            ("select", "show", "find", "path", "analyze", "describe", "history", "blame")
        ):
            # Extract the key:value parts
            parts = query.split()
            filters = []
            for part in parts:
                if ":" in part:
                    key, value = part.split(":", 1)
                    filters.append(f"{key} = '{value}'")

            if filters:
                suggested = f"SELECT * FROM nodes WHERE {' AND '.join(filters)}"
                return (
                    f"💡 It looks like you're using key:value syntax.\n"
                    f"MUQL uses SQL-like syntax. Try:\n"
                    f"  {suggested}\n\n"
                    f"Common query examples:\n"
                    f"  SELECT * FROM functions WHERE name LIKE '%auth%'\n"
                    f"  SELECT * FROM classes WHERE complexity > 20\n"
                    f"  FIND functions MATCHING 'test_%'\n"
                    f"  SHOW dependencies OF MyClass DEPTH 2"
                )

        # Pattern: just a name without query keyword
        if not any(
            query_lower.startswith(kw)
            for kw in ["select", "show", "find", "path", "analyze", "describe", "history", "blame"]
        ):
            return (
                f"💡 MUQL queries must start with a keyword.\n\n"
                f"Common query formats:\n"
                f"  SELECT * FROM functions WHERE name = '{query.strip()}'\n"
                f"  FIND functions MATCHING '{query.strip()}'\n"
                f"  SHOW dependencies OF {query.strip()}\n\n"
                f"Use 'mu q --examples' to see more examples."
            )

        # Pattern: common SQL mistakes
        if "where type =" in query_lower or "where type=" in query_lower:
            return (
                "💡 Use FROM clause to filter by type, not WHERE.\n\n"
                "Correct:\n"
                "  SELECT * FROM functions WHERE name LIKE '%auth%'\n"
                "  SELECT * FROM classes WHERE complexity > 20"
            )

        # Pattern: invalid table name after FROM
        from_match = re.search(r"\bfrom\s+(\w+)", query_lower)
        if from_match:
            table_name = from_match.group(1)
            valid_tables = ["functions", "classes", "modules", "nodes"]
            if table_name not in valid_tables:
                return (
                    f"💡 Invalid table '{table_name}'.\n\n"
                    f"Valid tables are: {', '.join(valid_tables)}\n\n"
                    f"Examples:\n"
                    f"  SELECT * FROM functions WHERE complexity > 20\n"
                    f"  SELECT * FROM classes WHERE name LIKE '%Service%'\n"
                    f"  SELECT * FROM modules"
                )

        return None


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
