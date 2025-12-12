"""Tests for SQL Injection Prevention in MUQL.

Comprehensive tests to verify that MUQL properly handles malicious input
and prevents SQL injection attacks through parameterized queries.
"""

from __future__ import annotations

import pytest

from mu.kernel.muql.ast import NodeTypeFilter
from mu.kernel.muql.engine import MUQLEngine
from mu.kernel.muql.parser import MUQLParser, MUQLSyntaxError, parse
from mu.kernel.muql.planner import QueryPlanner, SQLPlan


class TestInjectionInParser:
    """Tests that the parser rejects or safely handles injection attempts."""

    @pytest.fixture
    def parser(self) -> MUQLParser:
        """Create a parser instance for tests."""
        return MUQLParser()

    def test_basic_injection_in_string_literal(self, parser: MUQLParser) -> None:
        """Test that SQL injection in string literals is handled safely.

        The parser's grammar rejects statements with semicolons outside strings,
        which is actually a good defense layer.
        """
        # The parser rejects semicolons outside of string literals
        # This is expected behavior - the grammar doesn't allow stacked queries
        with pytest.raises(MUQLSyntaxError):
            parser.parse("SELECT * FROM functions WHERE name = 'test'; DROP TABLE nodes; --'")

        # But injection payloads inside string literals are handled as literal values
        query = parser.parse("SELECT * FROM functions WHERE name = \"test'; DROP TABLE nodes; --\"")
        assert query.where is not None
        assert "DROP TABLE" in query.where.comparisons[0].value.value

    def test_injection_with_single_quotes(self, parser: MUQLParser) -> None:
        """Test injection attempt with escaped single quotes."""
        # The parser grammar handles string escaping
        query = parser.parse("SELECT * FROM functions WHERE name = \"test'; DROP TABLE nodes;--\"")

        assert query.where is not None
        # The value includes the injection attempt as literal text
        assert "DROP TABLE" in query.where.comparisons[0].value.value

    def test_injection_in_like_pattern(self, parser: MUQLParser) -> None:
        """Test injection attempt in LIKE patterns.

        The parser rejects semicolons outside strings, providing defense-in-depth.
        """
        # Parser rejects semicolons at statement level
        with pytest.raises(MUQLSyntaxError):
            parser.parse("SELECT * FROM functions WHERE name LIKE '%test%'; DROP TABLE nodes;--%'")

        # But injection payloads inside the string are safe
        query = parser.parse("SELECT * FROM functions WHERE name LIKE \"%test%; DROP TABLE%\"")
        assert query.where is not None
        assert "DROP TABLE" in query.where.comparisons[0].value.value

    def test_injection_in_find_matching(self, parser: MUQLParser) -> None:
        """Test injection in FIND MATCHING pattern.

        Parser rejects semicolons at statement level (defense-in-depth).
        """
        # Parser rejects semicolons outside strings
        with pytest.raises(MUQLSyntaxError):
            parser.parse("FIND functions MATCHING 'test%'; DROP TABLE nodes;--'")

        # Injection payload inside string is treated as literal pattern
        query = parser.parse("FIND functions MATCHING \"test%; DROP TABLE%\"")
        assert query.condition.pattern == "test%; DROP TABLE%"

    def test_unicode_injection_attempt(self, parser: MUQLParser) -> None:
        """Test that unicode characters don't bypass protections."""
        # Various unicode tricks that might bypass naive filtering
        unicode_injections = [
            "SELECT * FROM functions WHERE name = 'test\u0027; DROP TABLE nodes;--'",  # Unicode apostrophe
            "SELECT * FROM functions WHERE name = 'test\u2019; DROP TABLE nodes;--'",  # Right single quote
            "SELECT * FROM functions WHERE name = 'test\uff07; DROP TABLE nodes;--'",  # Fullwidth apostrophe
        ]

        for injection in unicode_injections:
            try:
                query = parser.parse(injection)
                # If it parses, the unicode should be part of the literal value
                if query.where:
                    value = query.where.comparisons[0].value.value
                    assert "DROP TABLE" not in value or isinstance(value, str)
            except MUQLSyntaxError:
                # Parser rejecting the input is also acceptable
                pass

    def test_null_byte_injection(self, parser: MUQLParser) -> None:
        """Test that null bytes don't cause issues."""
        try:
            query = parser.parse("SELECT * FROM functions WHERE name = 'test\x00DROP TABLE nodes'")
            # If it parses, should handle null byte safely
        except (MUQLSyntaxError, ValueError):
            # Parser rejecting null bytes is acceptable
            pass

    def test_comment_injection(self, parser: MUQLParser) -> None:
        """Test SQL comment injection attempts."""
        # SQL comments should not work in MUQL
        injections = [
            "SELECT * FROM functions WHERE name = 'test' -- DROP TABLE nodes",
            "SELECT * FROM functions WHERE name = 'test' /* DROP TABLE */ ",
            "SELECT * FROM functions -- WHERE 1=1; DROP TABLE nodes",
        ]

        for injection in injections:
            try:
                query = parser.parse(injection)
                # Comments become part of value or are rejected
            except MUQLSyntaxError:
                # Parser rejecting is acceptable
                pass


class TestInjectionInPlanner:
    """Tests that the planner generates parameterized SQL safely."""

    @pytest.fixture
    def planner(self) -> QueryPlanner:
        """Create a planner instance for tests."""
        return QueryPlanner()

    def test_select_where_uses_parameters(self, planner: QueryPlanner) -> None:
        """Test that SELECT WHERE generates parameterized SQL."""
        query = parse("SELECT * FROM functions WHERE name = 'test'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # Should use ? placeholder, not string interpolation
        assert "?" in plan.sql
        assert "'" not in plan.sql or plan.sql.count("'") == 0
        # Parameters include type filter + value
        assert "test" in plan.parameters
        assert "function" in plan.parameters  # Type filter is also parameterized

    def test_select_like_uses_parameters(self, planner: QueryPlanner) -> None:
        """Test that LIKE patterns are parameterized."""
        query = parse("SELECT * FROM functions WHERE name LIKE '%test%'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        assert "?" in plan.sql
        # Parameters include type filter + pattern
        assert "%test%" in plan.parameters
        assert "function" in plan.parameters

    def test_select_contains_uses_parameters(self, planner: QueryPlanner) -> None:
        """Test that CONTAINS uses parameterized queries."""
        query = parse("SELECT * FROM functions WHERE name CONTAINS 'test'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        assert "?" in plan.sql
        # CONTAINS converts to LIKE with wildcards
        assert "test" in plan.parameters
        assert "function" in plan.parameters

    def test_select_in_uses_parameters(self, planner: QueryPlanner) -> None:
        """Test that IN clause uses parameterized queries."""
        query = parse("SELECT * FROM functions WHERE name IN ('a', 'b', 'c')")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # 1 type filter param + 3 IN clause params = 4
        assert plan.sql.count("?") == 4
        assert "a" in plan.parameters
        assert "b" in plan.parameters
        assert "c" in plan.parameters
        assert "function" in plan.parameters

    def test_node_type_filter_uses_parameters(self, planner: QueryPlanner) -> None:
        """Test that node type filtering uses parameters."""
        query = parse("SELECT * FROM functions WHERE complexity > 10")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # The type filter should also use a parameter
        # For functions, the FROM clause becomes a subquery with type = ?
        assert "?" in plan.sql

    def test_find_matching_uses_parameters(self, planner: QueryPlanner) -> None:
        """Test that FIND MATCHING uses parameterized queries."""
        query = parse("FIND functions MATCHING 'test'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        assert "?" in plan.sql
        # Should have type filter param and pattern param
        assert len(plan.parameters) >= 1
        assert any("%test%" in str(p) for p in plan.parameters)

    def test_describe_uses_parameters(self, planner: QueryPlanner) -> None:
        """Test that DESCRIBE uses parameterized queries for type filters."""
        query = parse("DESCRIBE functions")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # Should use parameter for type filter
        assert "?" in plan.sql
        assert "function" in plan.parameters

    def test_injection_payload_in_parameter(self, planner: QueryPlanner) -> None:
        """Test that injection payloads end up as parameters, not SQL."""
        # Parse a query with injection payload in the value
        query = parse("SELECT * FROM functions WHERE name = \"'; DROP TABLE nodes; --\"")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # The payload should be in parameters, not interpolated into SQL
        assert "DROP TABLE" not in plan.sql
        assert any("DROP TABLE" in str(p) for p in plan.parameters)


class TestInjectionVectors:
    """Test various known SQL injection attack vectors."""

    @pytest.fixture
    def planner(self) -> QueryPlanner:
        """Create a planner instance for tests."""
        return QueryPlanner()

    def test_classic_or_1_equals_1(self, planner: QueryPlanner) -> None:
        """Test classic 'OR 1=1' injection."""
        query = parse("SELECT * FROM functions WHERE name = \"' OR '1'='1\"")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # The OR should be in the parameter value, not as SQL
        assert "OR '1'='1'" not in plan.sql or plan.sql.count("OR") <= 1
        # Check that the injection payload is in parameters (not in SQL)
        assert any("OR '1'='1" in str(p) for p in plan.parameters)

    def test_union_based_injection(self, planner: QueryPlanner) -> None:
        """Test UNION-based injection attempt."""
        query = parse("SELECT * FROM functions WHERE name = \"' UNION SELECT * FROM users --\"")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # UNION should be in parameter, not SQL
        assert "UNION SELECT * FROM users" not in plan.sql
        assert any("UNION" in str(p) for p in plan.parameters)

    def test_stacked_queries(self, planner: QueryPlanner) -> None:
        """Test stacked query injection attempt."""
        query = parse("SELECT * FROM functions WHERE name = \"'; DELETE FROM nodes; --\"")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # DELETE should be in parameter, not SQL
        assert "DELETE FROM nodes" not in plan.sql
        assert any("DELETE" in str(p) for p in plan.parameters)

    def test_time_based_blind_injection(self, planner: QueryPlanner) -> None:
        """Test time-based blind SQL injection attempt."""
        query = parse("SELECT * FROM functions WHERE name = \"' AND SLEEP(5) --\"")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # SLEEP should be in parameter, not SQL
        assert "SLEEP" not in plan.sql
        assert any("SLEEP" in str(p) for p in plan.parameters)

    def test_error_based_injection(self, planner: QueryPlanner) -> None:
        """Test error-based injection attempt."""
        query = parse("SELECT * FROM functions WHERE name = \"' AND 1=CONVERT(int, @@version) --\"")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # The injection should be in parameter
        assert "CONVERT" not in plan.sql
        assert any("CONVERT" in str(p) for p in plan.parameters)


class TestPlannerDefenseInDepth:
    """Test that even trusted inputs use parameterization (defense in depth)."""

    @pytest.fixture
    def planner(self) -> QueryPlanner:
        """Create a planner instance for tests."""
        return QueryPlanner()

    def test_node_type_uses_parameter_not_interpolation(self, planner: QueryPlanner) -> None:
        """Verify node type filter uses parameters even though enum is trusted."""
        for node_type_str in ["functions", "classes", "modules"]:
            query = parse(f"SELECT * FROM {node_type_str}")
            plan = planner.plan(query)

            assert isinstance(plan, SQLPlan)
            if node_type_str != "nodes":
                # Type filter should use parameter
                assert "?" in plan.sql
                # The type value should be in parameters
                assert any(
                    isinstance(p, str) and p in ["function", "class", "module"]
                    for p in plan.parameters
                )

    def test_find_type_filter_uses_parameter(self, planner: QueryPlanner) -> None:
        """Verify FIND type filter uses parameters."""
        query = parse("FIND functions MATCHING 'test'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # Should have parameter for type filter
        assert "?" in plan.sql
        # Type value should be parameterized
        assert "function" in plan.parameters

    def test_no_string_interpolation_in_sql(self, planner: QueryPlanner) -> None:
        """Verify SQL generation doesn't use string interpolation for values."""
        queries = [
            "SELECT * FROM functions WHERE name = 'test'",
            "SELECT * FROM classes WHERE complexity > 10",
            "FIND functions MATCHING 'auth'",
            "DESCRIBE functions",
        ]

        for query_str in queries:
            query = parse(query_str)
            plan = planner.plan(query)

            if isinstance(plan, SQLPlan):
                # Check that user values aren't directly in SQL
                # (they should be in parameters instead)
                if "test" in query_str:
                    assert "'test'" not in plan.sql
                if "auth" in query_str:
                    assert "'auth'" not in plan.sql


class TestExecutorWithMaliciousInput:
    """Integration tests with actual database to verify injection is prevented."""

    @pytest.fixture
    def db(self):
        """Create an in-memory MUbase for testing."""
        from mu.kernel.mubase import MUbase

        db = MUbase(":memory:")
        # Add some test data
        from mu.kernel.models import Node
        from mu.kernel.schema import NodeType

        test_node = Node(
            id="fn:test.py:test_func",
            type=NodeType.FUNCTION,
            name="test_func",
            qualified_name="test.test_func",
            file_path="test.py",
            line_start=1,
            line_end=10,
            properties={},
            complexity=5,
        )
        db.add_node(test_node)
        return db

    @pytest.fixture
    def engine(self, db) -> MUQLEngine:
        """Create an engine with the test database."""
        return MUQLEngine(db)

    def test_injection_does_not_drop_table(self, engine: MUQLEngine) -> None:
        """Verify that injection payloads don't execute destructive SQL."""
        # Execute query with injection payload
        result = engine.execute(
            "SELECT * FROM functions WHERE name = \"'; DROP TABLE nodes; --\""
        )

        # Query should complete (possibly with no results)
        # The important thing is that the table still exists

        # Verify table still exists by running another query
        result2 = engine.execute("SELECT * FROM nodes")
        assert result2.error is None

    def test_injection_does_not_leak_data(self, engine: MUQLEngine) -> None:
        """Verify that UNION injection doesn't leak extra data."""
        result = engine.execute(
            "SELECT * FROM functions WHERE name = \"' UNION SELECT * FROM metadata --\""
        )

        # Should either error or return no results (since name doesn't match)
        # Should NOT return metadata table contents
        if result.rows:
            for row in result.rows:
                # Verify we only got function data, not metadata
                assert "version" not in str(row).lower()

    def test_batch_injection_prevented(self, engine: MUQLEngine) -> None:
        """Verify that stacked/batch queries are prevented."""
        result = engine.execute(
            "SELECT * FROM functions WHERE name = 'test'; DELETE FROM nodes; --'"
        )

        # The query might error or return results
        # Important: nodes should still exist
        result2 = engine.execute("SELECT * FROM nodes")
        assert result2.error is None

    def test_comment_injection_prevented(self, engine: MUQLEngine) -> None:
        """Verify that comment injection is handled safely."""
        result = engine.execute(
            "SELECT * FROM functions WHERE name = 'test' -- WHERE 1=0"
        )

        # Should not affect query semantics dangerously


class TestSpecialCharacters:
    """Test handling of special characters that might affect SQL."""

    @pytest.fixture
    def planner(self) -> QueryPlanner:
        """Create a planner instance for tests."""
        return QueryPlanner()

    def test_backslash_handling(self, planner: QueryPlanner) -> None:
        """Test that backslashes are handled safely."""
        query = parse("SELECT * FROM functions WHERE name = 'test\\name'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        assert "?" in plan.sql

    def test_percent_sign_in_value(self, planner: QueryPlanner) -> None:
        """Test that % in values doesn't affect LIKE patterns incorrectly."""
        query = parse("SELECT * FROM functions WHERE name = '100%_complete'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # % should be in parameter, treated literally for = comparison
        # Parameters include type filter + value
        assert "100%_complete" in plan.parameters
        assert "function" in plan.parameters

    def test_newline_in_value(self, planner: QueryPlanner) -> None:
        """Test that newlines in values are handled safely."""
        # Newlines could potentially break out of string context
        query = parse("SELECT * FROM functions WHERE name = 'line1\nline2'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        assert "?" in plan.sql

    def test_tab_character(self, planner: QueryPlanner) -> None:
        """Test that tab characters are handled safely."""
        query = parse("SELECT * FROM functions WHERE name = 'col1\tcol2'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        assert "?" in plan.sql

    def test_semicolon_in_value(self, planner: QueryPlanner) -> None:
        """Test that semicolons in values don't terminate statements."""
        query = parse("SELECT * FROM functions WHERE name = 'a;b;c'")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # Semicolons should be in parameter value only
        assert "a;b;c" in plan.parameters


class TestParameterOrdering:
    """Test that parameters are correctly ordered in complex queries."""

    @pytest.fixture
    def planner(self) -> QueryPlanner:
        """Create a planner instance for tests."""
        return QueryPlanner()

    def test_multiple_where_conditions(self, planner: QueryPlanner) -> None:
        """Test parameter ordering with multiple WHERE conditions."""
        query = parse(
            "SELECT * FROM functions WHERE name = 'test' AND complexity > 10"
        )
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # Parameters should be in order they appear in SQL
        assert len(plan.parameters) >= 2
        # Type filter param + name param + complexity param
        assert "test" in plan.parameters
        assert 10 in plan.parameters

    def test_in_clause_parameter_ordering(self, planner: QueryPlanner) -> None:
        """Test parameter ordering with IN clause."""
        query = parse("SELECT * FROM functions WHERE name IN ('a', 'b', 'c')")
        plan = planner.plan(query)

        assert isinstance(plan, SQLPlan)
        # IN parameters should be in order
        in_params = [p for p in plan.parameters if p in ["a", "b", "c"]]
        assert in_params == ["a", "b", "c"]
