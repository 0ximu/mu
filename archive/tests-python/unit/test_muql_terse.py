"""Tests for Terse MUQL Syntax - LLM-optimized query shortcuts.

Comprehensive tests for the terse syntax feature that reduces token count
for LLM agents while maintaining full backward compatibility with verbose SQL-like syntax.

Test Categories:
1. Node type aliases (fn, cls, mod)
2. Field aliases (c, n, fp, qn)
3. Operator aliases (~ for LIKE)
4. Order aliases (sort, -, +)
5. Limit (bare number, lim keyword)
6. SHOW command aliases (deps, rdeps, callers, callees, impact)
7. Depth clause (d2, d3 etc.)
8. Terse vs verbose equivalence
9. Backward compatibility
10. Edge cases
"""

from __future__ import annotations

import pytest

from mu.kernel.muql.ast import (
    ComparisonOperator,
    Condition,
    NodeTypeFilter,
    SelectQuery,
    ShowQuery,
    ShowType,
    SortOrder,
)
from mu.kernel.muql.parser import MUQLParser, MUQLSyntaxError, parse


# =============================================================================
# Test Node Type Aliases
# =============================================================================


class TestTerseNodeTypeAliases:
    """Tests for terse node type aliases in SELECT statements."""

    @pytest.mark.parametrize(
        "terse,verbose,expected_type",
        [
            ("fn", "functions", NodeTypeFilter.FUNCTIONS),
            ("cls", "classes", NodeTypeFilter.CLASSES),
            ("mod", "modules", NodeTypeFilter.MODULES),
        ],
    )
    def test_node_type_aliases_in_verbose_select(
        self, terse: str, verbose: str, expected_type: NodeTypeFilter
    ) -> None:
        """Terse node type aliases work in verbose SELECT FROM syntax."""
        terse_query = parse(f"SELECT * FROM {terse}")
        verbose_query = parse(f"SELECT * FROM {verbose}")

        assert isinstance(terse_query, SelectQuery)
        assert isinstance(verbose_query, SelectQuery)
        assert terse_query.node_type == expected_type
        assert terse_query.node_type == verbose_query.node_type

    @pytest.mark.parametrize(
        "terse_type,expected_type",
        [
            ("fn", NodeTypeFilter.FUNCTIONS),
            ("cls", NodeTypeFilter.CLASSES),
            ("mod", NodeTypeFilter.MODULES),
        ],
    )
    def test_terse_select_node_types(
        self, terse_type: str, expected_type: NodeTypeFilter
    ) -> None:
        """Terse SELECT syntax recognizes node type aliases."""
        # Terse select with where clause
        query = parse(f"{terse_type} c>50")
        assert isinstance(query, SelectQuery)
        assert query.node_type == expected_type

    def test_node_type_case_insensitive(self) -> None:
        """Node type aliases are case-insensitive."""
        for variant in ["fn", "FN", "Fn"]:
            query = parse(f"SELECT * FROM {variant}")
            assert isinstance(query, SelectQuery)
            assert query.node_type == NodeTypeFilter.FUNCTIONS


# =============================================================================
# Test Field Aliases
# =============================================================================


class TestTerseFieldAliases:
    """Tests for terse field aliases in WHERE clauses."""

    @pytest.mark.parametrize(
        "terse_query,expected_field",
        [
            ("fn c>50", "complexity"),
            ("fn n='main'", "name"),
            ("fn fp='src/'", "file_path"),
            ("fn qn='module.Class'", "qualified_name"),
        ],
    )
    def test_field_aliases_resolve_correctly(
        self, terse_query: str, expected_field: str
    ) -> None:
        """Field aliases resolve to full field names."""
        query = parse(terse_query)
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert len(query.where.comparisons) == 1
        assert query.where.comparisons[0].field == expected_field

    def test_field_alias_with_like_operator(self) -> None:
        """Field aliases work with LIKE (~) operator."""
        query = parse("fn n~'auth'")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.comparisons[0].field == "name"
        assert query.where.comparisons[0].operator == ComparisonOperator.LIKE

    def test_regular_identifier_as_field(self) -> None:
        """Regular identifiers work as field names."""
        query = parse("fn complexity>50")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.comparisons[0].field == "complexity"


# =============================================================================
# Test Operator Aliases
# =============================================================================


class TestTerseOperators:
    """Tests for terse comparison operators."""

    def test_tilde_parses_as_like(self) -> None:
        """~ operator parses as LIKE in terse SELECT."""
        query = parse("fn n~'auth'")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.comparisons[0].operator == ComparisonOperator.LIKE

    def test_tilde_in_verbose_where(self) -> None:
        """~ operator works in verbose SELECT WHERE clause."""
        query = parse("SELECT * FROM functions WHERE name ~ 'auth'")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.comparisons[0].operator == ComparisonOperator.LIKE

    @pytest.mark.parametrize(
        "operator,expected_op",
        [
            ("=", ComparisonOperator.EQ),
            ("!=", ComparisonOperator.NEQ),
            (">", ComparisonOperator.GT),
            ("<", ComparisonOperator.LT),
            (">=", ComparisonOperator.GTE),
            ("<=", ComparisonOperator.LTE),
            ("~", ComparisonOperator.LIKE),
        ],
    )
    def test_all_comparison_operators_in_terse(
        self, operator: str, expected_op: ComparisonOperator
    ) -> None:
        """All comparison operators work in terse syntax."""
        value = "'test'" if operator in ("=", "!=", "~") else "50"
        query = parse(f"fn n{operator}{value}")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.comparisons[0].operator == expected_op


# =============================================================================
# Test SHOW Command Aliases
# =============================================================================


class TestTerseShowCommands:
    """Tests for terse SHOW command aliases."""

    @pytest.mark.parametrize(
        "terse,expected_type,expected_depth",
        [
            ("deps AuthService", ShowType.DEPENDENCIES, 1),
            ("deps AuthService d2", ShowType.DEPENDENCIES, 2),
            ("deps AuthService d3", ShowType.DEPENDENCIES, 3),
            ("deps AuthService d10", ShowType.DEPENDENCIES, 10),
            ("rdeps AuthService", ShowType.DEPENDENTS, 1),
            ("rdeps AuthService d2", ShowType.DEPENDENTS, 2),
            ("callers main", ShowType.CALLERS, 1),
            ("callers main d5", ShowType.CALLERS, 5),
            ("callees main", ShowType.CALLEES, 1),
            ("callees process_data d3", ShowType.CALLEES, 3),
            ("impact UserModel", ShowType.IMPACT, 1),
        ],
    )
    def test_show_command_aliases(
        self, terse: str, expected_type: ShowType, expected_depth: int
    ) -> None:
        """Terse SHOW commands parse correctly."""
        query = parse(terse)
        assert isinstance(query, ShowQuery)
        assert query.show_type == expected_type
        assert query.depth == expected_depth

    def test_deps_with_quoted_node_ref(self) -> None:
        """deps command accepts quoted node references."""
        query = parse('deps "mod:src/auth.py" d2')
        assert isinstance(query, ShowQuery)
        assert query.show_type == ShowType.DEPENDENCIES
        assert query.target.name == "mod:src/auth.py"
        assert query.target.is_quoted
        assert query.depth == 2

    def test_deps_with_qualified_name(self) -> None:
        """deps command accepts qualified node names."""
        query = parse("deps mu.kernel.mubase d3")
        assert isinstance(query, ShowQuery)
        assert query.target.name == "mu.kernel.mubase"
        assert query.target.is_qualified
        assert query.depth == 3

    @pytest.mark.parametrize(
        "terse,verbose",
        [
            ("deps AuthService", "SHOW dependencies OF AuthService"),
            ("deps AuthService d2", "SHOW dependencies OF AuthService DEPTH 2"),
            ("rdeps AuthService", "SHOW dependents OF AuthService"),
            ("callers main", "SHOW callers OF main"),
            ("callees main", "SHOW callees OF main"),
            ("impact UserModel", "SHOW impact OF UserModel"),
        ],
    )
    def test_terse_show_equivalence_to_verbose(self, terse: str, verbose: str) -> None:
        """Terse SHOW commands produce equivalent AST to verbose."""
        terse_query = parse(terse)
        verbose_query = parse(verbose)

        assert isinstance(terse_query, ShowQuery)
        assert isinstance(verbose_query, ShowQuery)
        assert terse_query.show_type == verbose_query.show_type
        assert terse_query.target.name == verbose_query.target.name
        assert terse_query.depth == verbose_query.depth

    def test_show_commands_case_insensitive(self) -> None:
        """Terse SHOW commands are case-insensitive."""
        for variant in ["deps", "DEPS", "Deps"]:
            query = parse(f"{variant} AuthService")
            assert isinstance(query, ShowQuery)
            assert query.show_type == ShowType.DEPENDENCIES


# =============================================================================
# Test ORDER BY and LIMIT
# =============================================================================


class TestTerseOrderAndLimit:
    """Tests for terse ORDER BY and LIMIT syntax."""

    @pytest.mark.parametrize(
        "terse,expected_field,expected_order",
        [
            ("fn c>50 sort c-", "complexity", SortOrder.DESC),
            ("fn c>50 sort c+", "complexity", SortOrder.ASC),
            ("fn c>50 sort c desc", "complexity", SortOrder.DESC),
            ("fn c>50 sort c asc", "complexity", SortOrder.ASC),
            ("fn c>50 sort n-", "name", SortOrder.DESC),
            ("fn c>50 sort n+", "name", SortOrder.ASC),
        ],
    )
    def test_order_direction_aliases(
        self, terse: str, expected_field: str, expected_order: SortOrder
    ) -> None:
        """Order direction aliases work correctly."""
        query = parse(terse)
        assert isinstance(query, SelectQuery)
        assert len(query.order_by) == 1
        assert query.order_by[0].name == expected_field
        assert query.order_by[0].order == expected_order

    @pytest.mark.parametrize(
        "terse,expected_limit",
        [
            ("fn c>50 10", 10),
            ("fn c>50 100", 100),
            ("fn c>50 lim 10", 10),
            ("fn c>50 limit 10", 10),
            ("fn c>50 sort c- 10", 10),
            ("fn c>50 sort c- lim 20", 20),
        ],
    )
    def test_limit_syntax(self, terse: str, expected_limit: int) -> None:
        """Limit syntax variations work correctly."""
        query = parse(terse)
        assert isinstance(query, SelectQuery)
        assert query.limit == expected_limit

    def test_order_and_limit_combined(self) -> None:
        """Order and limit work together."""
        query = parse("fn c>50 sort c- 10")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert len(query.order_by) == 1
        assert query.order_by[0].name == "complexity"
        assert query.order_by[0].order == SortOrder.DESC
        assert query.limit == 10

    def test_multiple_order_fields(self) -> None:
        """Multiple order fields are supported."""
        query = parse("fn c>50 sort c-, n+")
        assert isinstance(query, SelectQuery)
        assert len(query.order_by) == 2
        assert query.order_by[0].name == "complexity"
        assert query.order_by[0].order == SortOrder.DESC
        assert query.order_by[1].name == "name"
        assert query.order_by[1].order == SortOrder.ASC


# =============================================================================
# Test Terse vs Verbose Equivalence
# =============================================================================


class TestTerseVerboseEquivalence:
    """Tests ensuring terse and verbose queries produce equivalent AST."""

    @pytest.mark.parametrize(
        "terse,verbose",
        [
            ("fn c>50", "SELECT * FROM functions WHERE complexity > 50"),
            ("cls n='MyClass'", "SELECT * FROM classes WHERE name = 'MyClass'"),
            ("mod fp='src/'", "SELECT * FROM modules WHERE file_path = 'src/'"),
        ],
    )
    def test_simple_select_equivalence(self, terse: str, verbose: str) -> None:
        """Simple terse queries produce equivalent AST to verbose."""
        terse_query = parse(terse)
        verbose_query = parse(verbose)

        assert isinstance(terse_query, SelectQuery)
        assert isinstance(verbose_query, SelectQuery)
        assert terse_query.node_type == verbose_query.node_type
        assert terse_query.where is not None
        assert verbose_query.where is not None
        assert (
            terse_query.where.comparisons[0].field
            == verbose_query.where.comparisons[0].field
        )
        assert (
            terse_query.where.comparisons[0].operator
            == verbose_query.where.comparisons[0].operator
        )

    def test_select_star_is_default(self) -> None:
        """Terse SELECT defaults to SELECT *."""
        query = parse("fn c>50")
        assert isinstance(query, SelectQuery)
        assert len(query.fields) == 1
        assert query.fields[0].is_star
        assert query.fields[0].name == "*"


# =============================================================================
# Test Backward Compatibility
# =============================================================================


class TestBackwardCompatibility:
    """Ensure existing verbose syntax still works unchanged."""

    @pytest.mark.parametrize(
        "query",
        [
            # SELECT queries
            "SELECT * FROM functions",
            "SELECT * FROM functions WHERE complexity > 50",
            "SELECT name, complexity FROM functions ORDER BY complexity DESC",
            "SELECT * FROM classes WHERE name LIKE '%Service%'",
            "SELECT COUNT(*) FROM functions",
            "SELECT AVG(complexity) FROM functions",
            # SHOW queries
            "SHOW dependencies OF AuthService",
            "SHOW dependencies OF AuthService DEPTH 2",
            "SHOW dependents OF parser",
            "SHOW callers OF main",
            "SHOW callees OF process_data",
            "SHOW impact OF MUbase",
            "SHOW ancestors OF cli",
            # FIND queries
            "FIND functions CALLING parse_file",
            "FIND modules IMPORTING parser",
            'FIND functions MATCHING "test_%"',
            'FIND functions WITH DECORATOR "@property"',
            # PATH queries
            "PATH FROM cli TO parser",
            "PATH FROM a TO b MAX DEPTH 5",
            "PATH FROM main TO helper VIA calls",
            # ANALYZE queries
            "ANALYZE complexity",
            "ANALYZE coupling",
            "ANALYZE hotspots FOR kernel",
            # FIND CYCLES
            "FIND CYCLES",
            "FIND CYCLES WHERE edge_type = 'imports'",
        ],
    )
    def test_verbose_syntax_unchanged(self, query: str) -> None:
        """All existing verbose queries should still parse successfully."""
        result = parse(query)
        assert result is not None


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestTerseEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_terse_select_without_where(self) -> None:
        """Terse SELECT without WHERE clause (just node type)."""
        # Note: The grammar requires at least one clause after node type
        # This tests what happens with just the node type and limit
        query = parse("fn 10")
        assert isinstance(query, SelectQuery)
        assert query.node_type == NodeTypeFilter.FUNCTIONS
        assert query.limit == 10

    def test_whitespace_optional_around_operators(self) -> None:
        """Whitespace is optional around operators."""
        q1 = parse("fn c>50")
        q2 = parse("fn c > 50")
        assert isinstance(q1, SelectQuery)
        assert isinstance(q2, SelectQuery)
        # Both should parse to equivalent results
        assert q1.where is not None
        assert q2.where is not None

    def test_depth_with_large_values(self) -> None:
        """Depth clause accepts large values."""
        query = parse("deps AuthService d100")
        assert isinstance(query, ShowQuery)
        assert query.depth == 100

    def test_string_values_single_quotes(self) -> None:
        """String values work with single quotes."""
        query = parse("fn n='test'")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.comparisons[0].value.value == "test"

    def test_string_values_double_quotes(self) -> None:
        """String values work with double quotes."""
        query = parse('fn n="test"')
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.comparisons[0].value.value == "test"

    def test_and_conditions_in_terse(self) -> None:
        """AND conditions work in terse syntax."""
        query = parse("fn c>50 AND n~'auth'")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert len(query.where.comparisons) == 2
        assert query.where.operator == "and"

    def test_or_conditions_in_terse(self) -> None:
        """OR conditions work in terse syntax (Token filtering test).

        This test verifies that OR keyword tokens are properly filtered out
        of the condition list, leaving only the actual Condition objects.
        """
        query = parse("fn c>50 OR n~'auth'")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.operator == "or"
        # Verify nested conditions contain only Condition objects, not Tokens
        assert len(query.where.nested) == 2
        assert all(isinstance(n, Condition) for n in query.where.nested)

    def test_identifier_with_underscore(self) -> None:
        """Identifiers with underscores work as node references."""
        query = parse("deps process_data")
        assert isinstance(query, ShowQuery)
        assert query.target.name == "process_data"

    def test_limit_zero(self) -> None:
        """LIMIT 0 is valid in terse syntax."""
        query = parse("fn c>50 0")
        assert isinstance(query, SelectQuery)
        assert query.limit == 0


# =============================================================================
# Test Parser Instance
# =============================================================================


class TestMUQLParserInstance:
    """Tests for MUQLParser class with terse syntax."""

    @pytest.fixture
    def parser(self) -> MUQLParser:
        """Create parser instance."""
        return MUQLParser()

    def test_parser_handles_terse_queries(self, parser: MUQLParser) -> None:
        """MUQLParser instance parses terse queries."""
        result = parser.parse("fn c>50")
        assert isinstance(result, SelectQuery)

    def test_parser_reusable_for_mixed_syntax(self, parser: MUQLParser) -> None:
        """Parser handles both terse and verbose queries."""
        q1 = parser.parse("fn c>50")
        q2 = parser.parse("SELECT * FROM functions WHERE complexity > 50")
        q3 = parser.parse("deps AuthService d2")
        q4 = parser.parse("SHOW dependencies OF AuthService DEPTH 2")

        assert isinstance(q1, SelectQuery)
        assert isinstance(q2, SelectQuery)
        assert isinstance(q3, ShowQuery)
        assert isinstance(q4, ShowQuery)


# =============================================================================
# Test Error Handling
# =============================================================================


class TestTerseErrorHandling:
    """Tests for error handling in terse syntax."""

    def test_empty_query_raises_error(self) -> None:
        """Empty query raises syntax error."""
        with pytest.raises(MUQLSyntaxError):
            parse("")

    def test_whitespace_only_raises_error(self) -> None:
        """Whitespace-only query raises syntax error."""
        with pytest.raises(MUQLSyntaxError):
            parse("   ")

    def test_invalid_node_type_raises_error(self) -> None:
        """Invalid node type in terse syntax raises error."""
        with pytest.raises(MUQLSyntaxError):
            parse("invalid c>50")

    def test_incomplete_comparison_raises_error(self) -> None:
        """Incomplete comparison raises syntax error."""
        with pytest.raises(MUQLSyntaxError):
            parse("fn c>")


# =============================================================================
# Test Integration: Full Query Workflows
# =============================================================================


class TestTerseQueryWorkflows:
    """Tests for common terse query workflows."""

    def test_find_complex_functions(self) -> None:
        """Common workflow: find high-complexity functions."""
        query = parse("fn c>50 sort c- 10")
        assert isinstance(query, SelectQuery)
        assert query.node_type == NodeTypeFilter.FUNCTIONS
        assert query.where is not None
        assert query.where.comparisons[0].field == "complexity"
        assert query.where.comparisons[0].operator == ComparisonOperator.GT
        assert query.limit == 10
        assert len(query.order_by) == 1
        assert query.order_by[0].order == SortOrder.DESC

    def test_find_by_name_pattern(self) -> None:
        """Common workflow: find by name pattern."""
        query = parse("fn n~'test_'")
        assert isinstance(query, SelectQuery)
        assert query.where is not None
        assert query.where.comparisons[0].field == "name"
        assert query.where.comparisons[0].operator == ComparisonOperator.LIKE

    def test_dependency_analysis(self) -> None:
        """Common workflow: analyze dependencies."""
        query = parse("deps AuthService d3")
        assert isinstance(query, ShowQuery)
        assert query.show_type == ShowType.DEPENDENCIES
        assert query.depth == 3

    def test_impact_analysis(self) -> None:
        """Common workflow: impact analysis."""
        query = parse("impact UserModel")
        assert isinstance(query, ShowQuery)
        assert query.show_type == ShowType.IMPACT
        assert query.target.name == "UserModel"


# =============================================================================
# Test AST Serialization
# =============================================================================


class TestTerseQuerySerialization:
    """Tests for AST serialization of terse queries."""

    def test_terse_select_to_dict(self) -> None:
        """Terse SELECT query serializes correctly."""
        query = parse("fn c>50 sort c- 10")
        assert isinstance(query, SelectQuery)

        d = query.to_dict()
        assert d["query_type"] == "select"
        assert d["node_type"] == "function"
        assert d["limit"] == 10
        assert len(d["order_by"]) == 1

    def test_terse_show_to_dict(self) -> None:
        """Terse SHOW query serializes correctly."""
        query = parse("deps AuthService d2")
        assert isinstance(query, ShowQuery)

        d = query.to_dict()
        assert d["query_type"] == "show"
        assert d["show_type"] == "dependencies"
        assert d["depth"] == 2
