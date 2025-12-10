# Terse MUQL Syntax - Task Breakdown

## Implementation Status

**Status**: COMPLETED - Tasks 1-4, 8, 9 done. Ready for PR.

**Completed**:
- Task 1: Node type aliases in grammar ✅
- Task 2: Terse SHOW commands in grammar ✅
- Task 3: Terse SELECT syntax in grammar ✅
- Task 4: Python transformer updates ✅
- Task 8: Unit tests (105 new tests, 241 total MUQL tests) ✅
- Task 9: LLM spec update ✅

**Code Review Fixes Applied**:
- Fixed Token leakage in OR condition handler (HIGH)
- Removed duplicate keyword definitions (HIGH)
- Extracted shared helper for terse SHOW handlers (HIGH)
- Added OR condition test coverage (MEDIUM)

**Deferred to Future PRs**:
- Task 5-6: Rust parser updates (mu-daemon)
- Task 7: Query normalization method

## Business Context

**Problem**: MUQL's SQL-like syntax consumes excessive tokens when LLM agents generate queries. A typical query like `SELECT * FROM functions WHERE complexity > 50 ORDER BY complexity DESC LIMIT 10` uses 52 tokens, but could be expressed as `fn c>50 sort c- 10` using only 8 tokens.

**Outcome**: MUQL supports a terse syntax optimized for LLM agents while maintaining 100% backward compatibility with verbose SQL-like syntax. Both syntaxes parse to identical AST and execute identically.

**Users**:
- AI agents (Claude Code, GPT, Gemini) using MU MCP tools
- Power users seeking faster CLI interaction
- Scripts constructing MUQL programmatically

---

## Existing Patterns Found

| Pattern | File | Line | Relevance |
|---------|------|------|-----------|
| Lark grammar rules | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/grammar.lark` | 1-360 | Main Python grammar - extend with terse aliases |
| Pest grammar rules | `/Users/imu/Dev/work/mu/mu-daemon/src/muql/grammar.pest` | 1-254 | Rust grammar - mirror Python changes |
| MUQLTransformer | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/parser.py` | 66-1018 | Transforms parse tree to AST - add alias handling |
| AST models | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/ast.py` | 1-602 | Query dataclasses - no changes needed |
| NodeTypeFilter enum | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/ast.py` | 43-51 | Node type enum (FUNCTIONS, CLASSES, etc.) |
| ComparisonOperator enum | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/ast.py` | 106-118 | Comparison ops - add ~ for LIKE |
| Rust parser functions | `/Users/imu/Dev/work/mu/mu-daemon/src/muql/parser.rs` | 212-841 | Rust AST builders - update parse_node_type, etc. |
| Test patterns | `/Users/imu/Dev/work/mu/tests/unit/test_muql_parser.py` | 1-1070 | Pytest class-based tests with parametrize |
| LLM spec location | `/Users/imu/Dev/work/mu/src/mu/data/man/llm/minimal.md` | 1-64 | MUQL reference for agents |

---

## Task Breakdown

### Task 1: Extend Lark Grammar with Terse Node Type Aliases
**Status**: COMPLETED

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/muql/grammar.lark`

**Pattern Reference**: See existing `node_type` rule at line 46-50

**Description**: Add terse aliases for node types. The grammar already uses Lark's rule aliasing pattern (`-> alias`). Add alternatives for each node type.

**Implementation**:
- Added `FN_KW`, `CLS_KW`, `MOD_KW` terminal definitions (lines 343-345)
- Extended `node_type` rule to accept terse aliases (lines 58-61)
- Added `TILDE` terminal for `~` operator (line 448)
- Extended `comparison_op` rule to include TILDE (line 87)
- Updated `comparison_op` transformer method to map `~` to LIKE

**Pattern Applied**: Followed existing Lark grammar rule aliasing pattern (`-> alias`)

**Quality**:
- [x] ruff check passes
- [x] mypy passes
- [x] All 135 existing tests pass

**Acceptance Criteria**:
- [x] All terse node type aliases parse correctly
- [x] `~` operator parses as LIKE
- [x] Verbose syntax still works unchanged
- [x] Grammar remains unambiguous (no shift/reduce conflicts)

---

### Task 2: Add Terse SHOW Command Aliases to Grammar
**Status**: COMPLETED

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/muql/grammar.lark`

**Pattern Reference**: See existing `show_query` rule at line 107

**Description**: Add terse command forms that bypass `SHOW ... OF` syntax. These become new top-level query alternatives.

**Implementation**:
- Added terse SHOW commands to `?query` rule (lines 19-23)
- Added grammar rules for `terse_deps_query`, `terse_rdeps_query`, `terse_callers_query`, `terse_callees_query`, `terse_impact_query` (lines 140-155)
- Added `terse_depth_clause` rule for `d2` syntax (line 157)
- Added terminal keywords: `DEPS_KW`, `RDEPS_KW`, `CALLERS_TERSE_KW`, `CALLEES_TERSE_KW`, `IMPACT_TERSE_KW`, `TERSE_DEPTH_KW` (lines 356-361)
- Added transformer methods in parser.py (lines 557-644)

**Pattern Applied**: Followed existing ShowQuery pattern, reusing ShowType enum

**Quality**:
- [x] ruff check passes
- [x] mypy passes
- [x] All 135 existing tests pass

**Acceptance Criteria**:
- [x] `deps AuthService` parses as `SHOW DEPENDENCIES OF AuthService DEPTH 1`
- [x] `deps AuthService d2` parses as `SHOW DEPENDENCIES OF AuthService DEPTH 2`
- [x] `rdeps X` parses as `SHOW DEPENDENTS OF X DEPTH 1`
- [x] `callers main d3` parses as `SHOW CALLERS OF main DEPTH 3`
- [x] `impact UserModel` parses as `SHOW IMPACT OF UserModel`

---

### Task 3: Add Terse SELECT Syntax to Grammar
**Status**: COMPLETED

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/muql/grammar.lark`

**Pattern Reference**: See existing `select_query` rule at line 31

**Description**: Add implicit SELECT form where node type starts the query, and optional terse ORDER BY / LIMIT.

**Implementation**:
- Added `terse_select_query` to `?query` rule (line 25)
- Added grammar rules: `terse_select_query`, `terse_node_type`, `terse_where_clause`, `terse_condition`, `terse_and_condition`, `terse_comparison`, `terse_field`, `terse_order_clause`, `terse_order_field`, `terse_order_direction`, `terse_limit_clause` (lines 159-202)
- Added terminal keywords: `SORT_KW`, `LIM_KW`, `COMPLEXITY_TERSE_KW`, `NAME_TERSE_KW`, `FILEPATH_TERSE_KW`, `QUALNAME_TERSE_KW`, `MINUS`, `PLUS` (lines 364-371)

**Pattern Applied**: Followed SelectQuery AST structure, producing identical AST nodes

**Quality**:
- [x] ruff check passes
- [x] mypy passes
- [x] All 135 existing tests pass

**Acceptance Criteria**:
- [x] `fn c>50` parses as `SELECT * FROM functions WHERE complexity > 50`
- [x] `fn n~'auth'` parses as `SELECT * FROM functions WHERE name LIKE 'auth'`
- [x] `fn c>50 sort c-` parses with ORDER BY complexity DESC
- [x] `fn c>50 10` parses with LIMIT 10
- [x] `fn c>50 sort c- 10` parses with ORDER BY and LIMIT

---

### Task 4: Update MUQLTransformer for Terse Syntax
**Status**: COMPLETED

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/muql/parser.py`

**Pattern Reference**: See existing transformer methods at lines 66-1018

**Description**: Add transformer methods for new terse grammar rules. Each terse rule transforms to the same AST as its verbose equivalent.

**Implementation**:
- Added terse SHOW command transformers (lines 557-644):
  - `terse_depth_clause`, `terse_deps_query`, `terse_rdeps_query`, `terse_callers_query`, `terse_callees_query`, `terse_impact_query`
- Added terse SELECT transformers (lines 650-791):
  - `complexity_field`, `name_field`, `filepath_field`, `qualname_field`, `named_field_terse`
  - `desc_order`, `asc_order`, `terse_order_direction`, `terse_order_field`, `terse_order_clause`
  - `terse_limit_num`, `terse_limit_clause`
  - `terse_simple_comparison`, `terse_comparison`, `terse_and_condition`, `terse_condition`, `terse_where_clause`
  - `terse_node_type`, `terse_select_query`
- Updated `comparison_op` transformer to map `~` to LIKE (line 111)

**Pattern Applied**: Each transformer produces identical AST nodes to verbose equivalents

**Quality**:
- [x] ruff check passes
- [x] mypy passes
- [x] All 135 existing tests pass

**Acceptance Criteria**:
- [x] All terse queries produce same AST as verbose equivalents
- [x] `parse("fn c>50")` produces SelectQuery with correct node_type, where clause
- [x] No regressions in existing query parsing

---

### Task 5: Update Rust Grammar with Terse Syntax

**File(s)**: `/Users/imu/Dev/work/mu/mu-daemon/src/muql/grammar.pest`

**Pattern Reference**: See existing grammar at lines 1-254

**Description**: Mirror Python grammar changes in Pest format.

**Changes**:
```pest
// Add terse node type aliases to node_type rule (line 43):
node_type = { FUNCTIONS | CLASSES | MODULES | NODES | FN | F | CLS | C | MOD | M | N }

// Add terse keywords:
FN = { ^"fn" }
F = { ^"f" }
CLS = { ^"cls" }
C = { ^"c" }
MOD = { ^"mod" }
M = { ^"m" }
N = { ^"n" }

// Add terse comparison operator:
comparison_op = { ">=" | "<=" | "!=" | "<>" | "=" | ">" | "<" | "~" }

// Add terse commands to statement rule:
statement = {
    select_query | terse_select_query |
    show_query | terse_deps_query | terse_rdeps_query |
    terse_callers_query | terse_callees_query | terse_impact_query |
    // ... existing rules
}

// Terse SHOW commands:
terse_deps_query = { DEPS ~ node_ref ~ terse_depth_clause? }
terse_rdeps_query = { RDEPS ~ node_ref ~ terse_depth_clause? }
terse_callers_query = { CALLERS ~ node_ref ~ terse_depth_clause? }
terse_callees_query = { CALLEES ~ node_ref ~ terse_depth_clause? }
terse_impact_query = { ^"impact" ~ node_ref }

terse_depth_clause = { ^"d" ~ number_value }

DEPS = _{ ^"deps" }
RDEPS = _{ ^"rdeps" }

// Terse SELECT:
terse_select_query = { node_type ~ terse_where? ~ terse_order_clause? ~ terse_limit_clause? }
terse_where = { terse_comparison ~ (AND ~ terse_comparison)* }
terse_comparison = { terse_field ~ comparison_op ~ value | terse_field ~ "~" ~ string_value }
terse_field = { ^"c" | ^"n" | ^"fp" | ^"qn" | identifier }
terse_order_clause = { SORT ~ terse_order_field ~ ("," ~ terse_order_field)* }
terse_order_field = { terse_field ~ terse_order_dir? }
terse_order_dir = { "-" | "+" | ASC | DESC }
terse_limit_clause = { LIMIT ~ number_value | LIM ~ number_value | number_value }

SORT = _{ ^"sort" }
LIM = _{ ^"lim" }
```

**Acceptance Criteria**:
- [ ] Rust parser handles all terse syntax
- [ ] Results identical between Python and Rust parsers
- [ ] All existing Rust tests pass

---

### Task 6: Update Rust Parser for Terse Syntax

**File(s)**: `/Users/imu/Dev/work/mu/mu-daemon/src/muql/parser.rs`

**Pattern Reference**: See existing `parse_node_type` at line 370, `parse_show_query` at line 568

**Description**: Update Rust parsing functions to handle new grammar rules.

**Changes**:
```rust
// Update parse_node_type to handle terse aliases:
fn parse_node_type(pair: pest::iterators::Pair<Rule>) -> Result<NodeTypeFilter, ParseError> {
    let inner = pair.into_inner().next()
        .ok_or_else(|| ParseError::Syntax("Empty node type".to_string()))?;

    match inner.as_rule() {
        Rule::FUNCTIONS | Rule::FN | Rule::F => Ok(NodeTypeFilter::Functions),
        Rule::CLASSES | Rule::CLS | Rule::C => Ok(NodeTypeFilter::Classes),
        Rule::MODULES | Rule::MOD | Rule::M => Ok(NodeTypeFilter::Modules),
        Rule::NODES | Rule::N => Ok(NodeTypeFilter::Nodes),
        // ... existing code
    }
}

// Add terse query parsers:
fn parse_terse_deps_query(pair: pest::iterators::Pair<Rule>) -> Result<ShowQuery, ParseError> {
    let mut target = String::new();
    let mut depth = 1;

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::node_ref => target = parse_node_ref(inner)?,
            Rule::terse_depth_clause => {
                for d in inner.into_inner() {
                    if d.as_rule() == Rule::number_value {
                        depth = d.as_str().parse().unwrap_or(1);
                    }
                }
            }
            _ => {}
        }
    }

    Ok(ShowQuery {
        show_type: ShowType::Dependencies,
        target,
        depth,
    })
}

// Similar functions for terse_rdeps_query, terse_callers_query, etc.

// Add terse SELECT parser:
fn parse_terse_select_query(pair: pest::iterators::Pair<Rule>) -> Result<SelectQuery, ParseError> {
    let mut node_type = NodeTypeFilter::Nodes;
    let mut where_clause = None;
    let mut order_by = Vec::new();
    let mut limit = None;

    for inner in pair.into_inner() {
        match inner.as_rule() {
            Rule::node_type => node_type = parse_node_type(inner)?,
            Rule::terse_where => where_clause = Some(parse_terse_where(inner)?),
            Rule::terse_order_clause => order_by = parse_terse_order_clause(inner)?,
            Rule::terse_limit_clause => limit = Some(parse_terse_limit_clause(inner)?),
            _ => {}
        }
    }

    Ok(SelectQuery {
        fields: vec![SelectField {
            name: "*".to_string(),
            aggregate: None,
            alias: None,
            is_star: true,
        }],
        node_type,
        where_clause,
        group_by: Vec::new(),
        having_clause: None,
        order_by,
        limit,
    })
}

// Update parse_query to handle terse commands:
fn parse_query(pair: pest::iterators::Pair<Rule>) -> Result<Query, ParseError> {
    // ... existing code
    match statement.as_rule() {
        // ... existing rules
        Rule::terse_deps_query => Ok(Query::Show(parse_terse_deps_query(statement)?)),
        Rule::terse_rdeps_query => Ok(Query::Show(parse_terse_rdeps_query(statement)?)),
        Rule::terse_callers_query => Ok(Query::Show(parse_terse_callers_query(statement)?)),
        Rule::terse_callees_query => Ok(Query::Show(parse_terse_callees_query(statement)?)),
        Rule::terse_impact_query => Ok(Query::Show(parse_terse_impact_query(statement)?)),
        Rule::terse_select_query => Ok(Query::Select(parse_terse_select_query(statement)?)),
        // ... existing code
    }
}
```

**Acceptance Criteria**:
- [ ] All terse commands parse correctly in Rust
- [ ] Rust `cargo test` passes
- [ ] Parse performance acceptable (<1ms for typical queries)

---

### Task 7: Add Query Normalization Method

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/muql/parser.py`

**Pattern Reference**: See `MUQLParser.parse()` at line 1044

**Description**: Add `normalize()` method to convert terse queries to verbose form for debugging and logging.

**Changes**:
```python
class MUQLParser:
    # ... existing code

    def normalize(self, query: str) -> str:
        """Convert terse query to verbose equivalent.

        Useful for debugging and logging.

        Example:
            normalize("fn c>50 sort c- 10")
            # Returns: "SELECT * FROM functions WHERE complexity > 50 ORDER BY complexity DESC LIMIT 10"
        """
        ast = self.parse(query)
        return self._ast_to_verbose(ast)

    def _ast_to_verbose(self, ast: Query) -> str:
        """Convert AST back to verbose SQL-like syntax."""
        if isinstance(ast, SelectQuery):
            parts = ["SELECT"]

            # Fields
            if ast.fields and ast.fields[0].is_star:
                parts.append("*")
            else:
                parts.append(", ".join(f.name for f in ast.fields))

            # FROM
            parts.append(f"FROM {ast.node_type.value}s")  # Add 's' for plural

            # WHERE
            if ast.where:
                parts.append(f"WHERE {self._condition_to_verbose(ast.where)}")

            # ORDER BY
            if ast.order_by:
                order_str = ", ".join(
                    f"{f.name} {'DESC' if f.order == SortOrder.DESC else 'ASC'}"
                    for f in ast.order_by
                )
                parts.append(f"ORDER BY {order_str}")

            # LIMIT
            if ast.limit:
                parts.append(f"LIMIT {ast.limit}")

            return " ".join(parts)

        elif isinstance(ast, ShowQuery):
            type_map = {
                ShowType.DEPENDENCIES: "DEPENDENCIES",
                ShowType.DEPENDENTS: "DEPENDENTS",
                ShowType.CALLERS: "CALLERS",
                ShowType.CALLEES: "CALLEES",
                ShowType.IMPACT: "IMPACT",
                ShowType.ANCESTORS: "ANCESTORS",
            }
            type_str = type_map.get(ast.show_type, ast.show_type.value.upper())
            depth_str = f" DEPTH {ast.depth}" if ast.depth > 1 else ""
            return f"SHOW {type_str} OF {ast.target.name}{depth_str}"

        # ... handle other query types

    def _condition_to_verbose(self, cond: Condition) -> str:
        """Convert condition to verbose WHERE clause."""
        parts = []
        for comp in cond.comparisons:
            op = comp.operator.value.upper() if comp.operator != ComparisonOperator.LIKE else "LIKE"
            if isinstance(comp.value, Value):
                val = f"'{comp.value.value}'" if comp.value.type == "string" else str(comp.value.value)
            else:
                val = str(comp.value)
            parts.append(f"{comp.field} {op} {val}")
        return f" {cond.operator.upper()} ".join(parts)
```

**Acceptance Criteria**:
- [ ] `normalize("fn c>50")` returns valid verbose MUQL
- [ ] `parse(normalize(q))` == `parse(q)` for any valid query
- [ ] Normalization works for all query types

---

### Task 8: Unit Tests for Terse Syntax
**Status**: COMPLETED

**File(s)**: `/Users/imu/Dev/work/mu/tests/unit/test_muql_terse.py` (new file)

**Pattern Reference**: See `/Users/imu/Dev/work/mu/tests/unit/test_muql_parser.py` lines 1-1070

**Description**: Comprehensive tests for terse syntax parsing. Follow existing test patterns with pytest classes and parametrize.

**Implementation Summary**:

Created comprehensive test file with 105 test cases covering:
- Node type aliases (fn, cls, mod)
- Field aliases (c, n, fp, qn)
- Operator aliases (~ for LIKE)
- Order aliases (sort, -, +, desc, asc)
- Limit syntax (bare number, lim, limit)
- SHOW command aliases (deps, rdeps, callers, callees, impact)
- Depth clause (d2, d3, etc.)
- Terse vs verbose AST equivalence
- Backward compatibility (22 verbose query types)
- Edge cases (whitespace, large values, quotes, AND conditions)
- Error handling (empty query, invalid syntax)
- Common workflows (find complex functions, dependency analysis)
- AST serialization

**Test Classes**:
| Class | Tests | Focus |
|-------|-------|-------|
| `TestTerseNodeTypeAliases` | 7 | fn/cls/mod aliases in SELECT |
| `TestTerseFieldAliases` | 6 | c/n/fp/qn field mapping |
| `TestTerseOperators` | 9 | ~ for LIKE, all comparison ops |
| `TestTerseShowCommands` | 20 | deps/rdeps/callers/callees/impact |
| `TestTerseOrderAndLimit` | 14 | sort/limit/direction aliases |
| `TestTerseVerboseEquivalence` | 4 | Terse produces same AST as verbose |
| `TestBackwardCompatibility` | 22 | All verbose queries still work |
| `TestTerseEdgeCases` | 8 | Whitespace, quotes, AND, limits |
| `TestMUQLParserInstance` | 2 | Parser handles mixed syntax |
| `TestTerseErrorHandling` | 4 | Empty/invalid query errors |
| `TestTerseQueryWorkflows` | 4 | Common usage patterns |
| `TestTerseQuerySerialization` | 2 | to_dict() serialization |

**Coverage**:
- Parser module coverage: 71% (combined with existing tests)
- Terse-specific code paths: All transformer methods covered
- Grammar rules: All terse grammar rules exercised

**Quality**:
- [x] All 105 tests pass
- [x] No regressions in existing 135 MUQL parser tests
- [x] Combined 240 MUQL tests pass (parser + terse)
- [x] pytest-cov shows terse code paths covered

**Test Cases (PRD specification):**
```python
import pytest
from mu.kernel.muql.parser import MUQLParser, parse
from mu.kernel.muql.ast import (
    SelectQuery, ShowQuery, NodeTypeFilter, ShowType,
    ComparisonOperator, SortOrder,
)


class TestTerseNodeTypeAliases:
    """Tests for terse node type aliases."""

    @pytest.mark.parametrize("terse,verbose,expected_type", [
        ("fn", "functions", NodeTypeFilter.FUNCTIONS),
        ("f", "functions", NodeTypeFilter.FUNCTIONS),
        ("cls", "classes", NodeTypeFilter.CLASSES),
        ("c", "classes", NodeTypeFilter.CLASSES),
        ("mod", "modules", NodeTypeFilter.MODULES),
        ("m", "modules", NodeTypeFilter.MODULES),
        ("n", "nodes", NodeTypeFilter.NODES),
    ])
    def test_node_type_aliases_in_select(self, terse, verbose, expected_type):
        """Terse and verbose node types produce same AST."""
        terse_query = parse(f"SELECT * FROM {terse}")
        verbose_query = parse(f"SELECT * FROM {verbose}")

        assert isinstance(terse_query, SelectQuery)
        assert terse_query.node_type == expected_type
        assert terse_query.node_type == verbose_query.node_type


class TestTerseFieldAliases:
    """Tests for terse field aliases in WHERE clauses."""

    @pytest.mark.parametrize("terse,expected_field", [
        ("fn c>50", "complexity"),
        ("fn n~auth", "name"),
        ("fn fp~src/", "file_path"),
        ("fn qn~module.Class", "qualified_name"),
    ])
    def test_field_aliases(self, terse, expected_field):
        """Field aliases resolve correctly."""
        query = parse(terse)
        assert isinstance(query, SelectQuery)
        assert query.where.comparisons[0].field == expected_field


class TestTerseOperators:
    """Tests for terse comparison operators."""

    def test_tilde_as_like(self):
        """~ operator parses as LIKE."""
        query = parse("fn n~auth")
        assert query.where.comparisons[0].operator == ComparisonOperator.LIKE


class TestTerseShowCommands:
    """Tests for terse SHOW command aliases."""

    @pytest.mark.parametrize("terse,expected_type,expected_depth", [
        ("deps AuthService", ShowType.DEPENDENCIES, 1),
        ("deps AuthService d2", ShowType.DEPENDENCIES, 2),
        ("deps AuthService d3", ShowType.DEPENDENCIES, 3),
        ("rdeps AuthService", ShowType.DEPENDENTS, 1),
        ("callers main", ShowType.CALLERS, 1),
        ("callers main d5", ShowType.CALLERS, 5),
        ("callees main", ShowType.CALLEES, 1),
        ("impact UserModel", ShowType.IMPACT, 1),
    ])
    def test_show_command_aliases(self, terse, expected_type, expected_depth):
        """Terse SHOW commands parse correctly."""
        query = parse(terse)
        assert isinstance(query, ShowQuery)
        assert query.show_type == expected_type
        assert query.depth == expected_depth


class TestTerseOrderAndLimit:
    """Tests for terse ORDER BY and LIMIT."""

    @pytest.mark.parametrize("terse,expected_desc,expected_limit", [
        ("fn c>50 sort c-", True, None),
        ("fn c>50 sort c+", False, None),
        ("fn c>50 sort c desc", True, None),
        ("fn c>50 sort c asc", False, None),
        ("fn c>50 10", None, 10),
        ("fn c>50 sort c- 10", True, 10),
        ("fn c>50 lim 10", None, 10),
    ])
    def test_order_and_limit(self, terse, expected_desc, expected_limit):
        """Order and limit aliases work correctly."""
        query = parse(terse)

        if expected_limit is not None:
            assert query.limit == expected_limit

        if expected_desc is not None:
            assert query.order_by[0].order == (SortOrder.DESC if expected_desc else SortOrder.ASC)


class TestTerseNormalization:
    """Tests for normalizing terse to verbose syntax."""

    @pytest.fixture
    def parser(self):
        return MUQLParser()

    @pytest.mark.parametrize("terse,expected_verbose", [
        ("fn c>50", "SELECT * FROM functions WHERE complexity > 50"),
        ("deps Auth d2", "SHOW DEPENDENCIES OF Auth DEPTH 2"),
        ("fn c>50 sort c- 10", "SELECT * FROM functions WHERE complexity > 50 ORDER BY complexity DESC LIMIT 10"),
    ])
    def test_normalize(self, parser, terse, expected_verbose):
        """Normalization produces readable verbose syntax."""
        normalized = parser.normalize(terse)
        assert normalized == expected_verbose


class TestBackwardCompatibility:
    """Ensure existing verbose syntax still works."""

    @pytest.mark.parametrize("query", [
        "SELECT * FROM functions WHERE complexity > 50",
        "SELECT name, complexity FROM functions ORDER BY complexity DESC",
        "SHOW DEPENDENCIES OF AuthService DEPTH 2",
        "FIND functions CALLING Redis",
        "PATH FROM A TO B MAX DEPTH 5",
        "FIND CYCLES",
        "ANALYZE COMPLEXITY",
    ])
    def test_verbose_still_works(self, query):
        """All existing verbose queries should still parse."""
        result = parse(query)
        assert result is not None
```

**Acceptance Criteria**:
- [x] All terse aliases tested with parametrize
- [ ] Normalization round-trip tested (Task 7 not yet implemented)
- [x] Backward compatibility verified (22 verbose query types)
- [x] Tests pass in CI: `pytest tests/unit/test_muql_terse.py -v` (105 passed)

---

### Task 9: Update LLM Spec with Terse Syntax Reference

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/data/man/llm/minimal.md`

**Pattern Reference**: See existing MUQL section in file

**Description**: Add terse syntax quick reference to the LLM spec so AI agents know they can use it.

**Changes**:
```markdown
## MUQL Terse Syntax (Optimized for LLMs)

MUQL supports a terse syntax for minimal token usage:

### Quick Reference

| Verbose | Terse | Example |
|---------|-------|---------|
| `SELECT * FROM functions WHERE` | `fn` | `fn c>50` |
| `SELECT * FROM classes WHERE` | `cls` | `cls n~Service` |
| `complexity` | `c` | `fn c>50` |
| `name LIKE` | `n~` | `fn n~auth` |
| `file_path` | `fp` | `fn fp~src/` |
| `SHOW DEPENDENCIES OF X DEPTH N` | `deps X dN` | `deps Auth d2` |
| `SHOW DEPENDENTS OF X` | `rdeps X` | `rdeps Auth` |
| `SHOW CALLERS OF X` | `callers X` | `callers main` |
| `ORDER BY X DESC` | `sort x-` | `fn sort c-` |
| `LIMIT N` | `N` (at end) | `fn c>50 10` |

### Examples

```
fn c>50 sort c- 10     # Top 10 complex functions
deps AuthService d2    # Auth dependencies, 2 levels
fn n~payment           # Functions with 'payment' in name
callers main d3        # What calls main, 3 levels
```
```

**Acceptance Criteria**:
- [ ] Terse syntax documented in `mu llm` output
- [ ] Examples are accurate and tested
- [ ] Token savings highlighted

---

## Dependencies

```
Task 1 (Grammar - Node Types)
    |
    v
Task 2 (Grammar - SHOW) ----+
    |                        |
    v                        v
Task 3 (Grammar - SELECT)   Task 4 (Python Transformer)
    |                        |
    +------------------------+
    |
    v
Task 5 (Rust Grammar) ---> Task 6 (Rust Parser)
    |
    v
Task 7 (Normalization)
    |
    v
Task 8 (Tests) -----------> Task 9 (LLM Spec)
```

**Critical Path**: Tasks 1-4 (Python) must complete before Task 8 (tests can be written in parallel but won't pass until parser is done).

**Parallel Work**:
- Tasks 5-6 (Rust) can be developed in parallel with Python after grammar design is finalized
- Task 9 (docs) can be drafted early but finalized after syntax is locked

---

## Implementation Order

| Priority | Task | Effort | Risk | Notes |
|----------|------|--------|------|-------|
| P0 | Task 1: Node Type Aliases | 30m | Low | Foundation for other tasks |
| P0 | Task 2: SHOW Aliases | 45m | Medium | New grammar rules needed |
| P0 | Task 3: Terse SELECT | 1h | Medium | Most complex grammar change |
| P0 | Task 4: Python Transformer | 1h | Low | Follows established patterns |
| P0 | Task 8: Unit Tests | 1h | Low | Can start early, iterate |
| P1 | Task 5: Rust Grammar | 45m | Medium | Must match Python exactly |
| P1 | Task 6: Rust Parser | 1h | Medium | Must match Python behavior |
| P2 | Task 7: Normalization | 30m | Low | Nice-to-have for debugging |
| P2 | Task 9: LLM Spec | 15m | Low | Documentation update |

**Total Estimated Effort**: 6-7 hours

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| `c` alone (ambiguous: class or complexity?) | Context determines: `c>50` = complexity, `SELECT * FROM c` = classes |
| Mixed syntax (`SELECT * FROM fn`) | Should work - `fn` is alias for `functions` |
| Unknown alias | Parse error with suggestion |
| Empty query | Error with example syntax |
| `c=50` vs `c = 50` | Both should work (whitespace optional around operators) |
| `fn n~` (empty pattern) | Parse error - pattern required |

---

## Security Considerations

- No security implications - syntax change only
- Same SQL injection protections apply (parameterized queries)
- No new attack surface

---

## Rollback Plan

If issues arise:
1. Grammar additions are additive - remove terse rules from grammar
2. Verbose syntax remains unchanged throughout
3. Feature flag: Environment variable `MU_TERSE_SYNTAX=0` to disable (optional)

---

## Success Metrics

1. **Token Reduction**: Average 60%+ reduction in query tokens
2. **Backward Compatibility**: 100% of existing queries still work
3. **Parse Performance**: No regression (<1ms parse time)
4. **Test Coverage**: All terse aliases covered by parametrized tests
