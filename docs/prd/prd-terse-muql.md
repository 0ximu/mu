# PRD: Terse MUQL Syntax for LLM Agents

## Business Context

### Problem Statement
MUQL's SQL-like syntax is precise but verbose, consuming unnecessary tokens when LLM agents generate queries:

```sql
-- Current: 52 tokens
SELECT name, complexity FROM functions WHERE complexity > 50 ORDER BY complexity DESC LIMIT 10

-- Could be: 8 tokens
fn c>50 sort c desc limit 10
```

When Claude Code or other AI agents use MU via MCP, every token in the query counts against context limits. The verbose syntax also increases the chance of syntax errors, requiring retries.

**Token analysis from real usage:**
| Query Type | Current Syntax | Terse Syntax | Savings |
|------------|---------------|--------------|---------|
| Find complex functions | 52 tokens | 8 tokens | 85% |
| Show dependencies | 38 tokens | 12 tokens | 68% |
| Find by decorator | 45 tokens | 15 tokens | 67% |
| Path between nodes | 42 tokens | 10 tokens | 76% |

### Outcome
MUQL should support a terse syntax optimized for LLM agents while maintaining full backward compatibility with the verbose SQL-like syntax. Both syntaxes parse to the same AST and execute identically.

### Users
- AI agents (Claude Code, GPT, Gemini) using MU MCP
- Power users who want faster CLI interaction
- Scripts that construct MUQL programmatically

---

## Discovery Phase

**IMPORTANT**: Before implementing, the agent MUST first explore:

1. **Where MUQL parsing lives**
   ```
   mu context "how does MUQL parser work"
   ```

2. **The current grammar**
   ```bash
   find . -name "*.lark" -o -name "*grammar*"
   cat src/mu/kernel/muql/grammar.lark  # or similar
   ```

3. **How the parser transforms to AST**
   ```
   mu query "SELECT file_path, name FROM classes WHERE name LIKE '%Parser%'"
   ```

### Expected Discovery Locations

| Component | Likely Location | What to Look For |
|-----------|-----------------|------------------|
| Lark grammar | `src/mu/kernel/muql/grammar.lark` or inline in parser | Grammar rules |
| Parser | `src/mu/kernel/muql/parser.py` | `MUQLParser`, `MUQLTransformer` |
| AST models | `src/mu/kernel/muql/ast.py` | `SelectQuery`, `ShowQuery`, etc. |
| Rust parser | `mu-daemon/src/muql/parser.rs` | PEG or similar grammar |

---

## Existing Patterns Found

From codebase.mu analysis:

| Pattern | File | Relevance |
|---------|------|-----------|
| `MUQLParser` | `src/mu/kernel/muql/parser.py` | Main parser class |
| `MUQLTransformer` | `src/mu/kernel/muql/parser.py` | Lark transformer to AST |
| `SelectQuery` | `src/mu/kernel/muql/ast.py` | SELECT statement AST |
| `ShowQuery` | `src/mu/kernel/muql/ast.py` | SHOW statement AST |
| `FindQuery` | `src/mu/kernel/muql/ast.py` | FIND statement AST |
| `NodeTypeFilter` | `src/mu/kernel/muql/ast.py` | FUNCTIONS, CLASSES, etc. |
| Rust parser | `mu-daemon/src/muql/parser.rs` | Uses pest for parsing |

---

## Syntax Design

### Design Principles

1. **Backward Compatible**: All existing MUQL queries work unchanged
2. **Unambiguous**: Terse syntax must parse deterministically
3. **Composable**: Queries can be chained with `+` or pipes
4. **Minimal**: Optimize for fewest tokens possible
5. **Memorable**: Abbreviations should be intuitive

### Terse Syntax Reference

#### Node Type Aliases

| Verbose | Terse | Alt |
|---------|-------|-----|
| `functions` | `fn` | `f` |
| `classes` | `cls` | `c` |
| `modules` | `mod` | `m` |
| `methods` | `meth` | `mt` |
| `nodes` | `n` | - |

#### Field Aliases

| Verbose | Terse | Context |
|---------|-------|---------|
| `complexity` | `c` | In WHERE clause |
| `name` | `n` | In WHERE/SELECT |
| `file_path` | `fp` | In WHERE/SELECT |
| `line_start` | `ls` | In WHERE/SELECT |
| `line_end` | `le` | In WHERE/SELECT |
| `qualified_name` | `qn` | In WHERE/SELECT |
| `type` | `t` | In WHERE/SELECT |

#### Operator Aliases

| Verbose | Terse | Meaning |
|---------|-------|---------|
| `LIKE` | `~` | Pattern match |
| `=` | `=` | Equals (unchanged) |
| `>` | `>` | Greater than |
| `<` | `<` | Less than |
| `>=` | `>=` | Greater or equal |
| `<=` | `<=` | Less or equal |
| `AND` | `&` | Logical AND |
| `OR` | `\|` | Logical OR |
| `NOT` | `!` | Logical NOT |

#### Command Aliases

| Verbose | Terse | Example |
|---------|-------|---------|
| `SELECT * FROM` | (implicit) | `fn c>50` = `SELECT * FROM functions WHERE complexity > 50` |
| `SELECT` | `s` | `s n,c fn c>50` |
| `SHOW DEPENDENCIES OF` | `deps` | `deps AuthService` |
| `SHOW DEPENDENTS OF` | `rdeps` | `rdeps AuthService` |
| `SHOW CALLERS OF` | `callers` | `callers process_payment` |
| `SHOW CALLEES OF` | `callees` | `callees main` |
| `SHOW IMPACT OF` | `impact` | `impact UserModel` |
| `DEPTH` | `d` | `deps X d3` |
| `FIND ... CALLING` | `calling` | `fn calling Redis` |
| `FIND ... CALLED_BY` | `calledby` | `fn calledby main` |
| `FIND CYCLES` | `cycles` | `cycles` |
| `PATH FROM ... TO` | `path` | `path A B` |
| `ORDER BY` | `sort` | `fn sort c desc` |
| `LIMIT` | `lim` or just number | `fn c>50 10` |
| `DESC` | `desc` or `-` | `sort c-` or `sort c desc` |
| `ASC` | `asc` or `+` | `sort c+` or `sort c asc` |

### Query Examples

#### Simple Queries

```sql
-- Find complex functions
-- Verbose:
SELECT * FROM functions WHERE complexity > 50
-- Terse:
fn c>50

-- Find by name pattern
-- Verbose:
SELECT * FROM functions WHERE name LIKE '%auth%'
-- Terse:
fn n~auth

-- Find classes with decorator
-- Verbose:
FIND classes WITH_DECORATOR dataclass
-- Terse:
cls @dataclass
```

#### Relationship Queries

```sql
-- Dependencies
-- Verbose:
SHOW DEPENDENCIES OF AuthService DEPTH 2
-- Terse:
deps AuthService d2

-- Callers
-- Verbose:
SHOW CALLERS OF process_payment DEPTH 3
-- Terse:
callers process_payment d3

-- Impact analysis
-- Verbose:
SHOW IMPACT OF UserModel
-- Terse:
impact UserModel
```

#### Complex Queries

```sql
-- Top 10 complex functions, sorted
-- Verbose:
SELECT name, complexity FROM functions WHERE complexity > 30 ORDER BY complexity DESC LIMIT 10
-- Terse:
s n,c fn c>30 sort c- 10

-- Functions calling Redis in auth module
-- Verbose:
FIND functions CALLING Redis WHERE file_path LIKE '%auth%'
-- Terse:
fn calling Redis fp~auth

-- Path between two nodes
-- Verbose:
PATH FROM AuthService TO DatabaseConnection MAX_DEPTH 5
-- Terse:
path AuthService DatabaseConnection d5
```

#### Chained Queries (New Feature)

```sql
-- Find function and its dependencies
fn n=process_payment + deps d2

-- Find callers and their complexity
callers main + s n,c sort c-
```

---

## Task Breakdown

### Task 1: Extend Lark Grammar with Terse Rules

**File(s)**: `src/mu/kernel/muql/grammar.lark` (or wherever grammar is defined)

**Discovery First**:
```bash
grep -rn "lark\|grammar" src/mu/kernel/muql/
```

**Description**: Add terse alternatives to the existing grammar rules.

```lark
// Existing rule
node_type: "functions"i -> functions
         | "classes"i -> classes
         | "modules"i -> modules
         | "methods"i -> methods
         | "nodes"i -> nodes

// Extended with terse aliases
node_type: "functions"i -> functions
         | "fn"i -> functions
         | "f"i -> functions
         | "classes"i -> classes
         | "cls"i -> classes
         | "c"i -> classes
         | "modules"i -> modules
         | "mod"i -> modules
         | "m"i -> modules
         | "methods"i -> methods
         | "meth"i -> methods
         | "mt"i -> methods
         | "nodes"i -> nodes
         | "n"i -> nodes

// Terse SELECT (implicit FROM)
terse_select: node_type condition? order_clause? limit_clause?
            | "s"i field_list node_type condition? order_clause? limit_clause?

// Terse field names
field_name: "complexity"i -> complexity
          | "c"i -> complexity
          | "name"i -> name_field
          | "n"i -> name_field
          | "file_path"i -> file_path
          | "fp"i -> file_path
          | "qualified_name"i -> qualified_name
          | "qn"i -> qualified_name

// Terse operators
comparison_op: "=" -> eq
             | "!=" -> neq
             | ">" -> gt
             | "<" -> lt
             | ">=" -> gte
             | "<=" -> lte
             | "LIKE"i -> like
             | "~" -> like  // Terse pattern match

// Terse SHOW commands
terse_show: "deps"i node_ref depth_clause? -> show_deps
          | "rdeps"i node_ref depth_clause? -> show_rdeps
          | "callers"i node_ref depth_clause? -> show_callers
          | "callees"i node_ref depth_clause? -> show_callees
          | "impact"i node_ref -> show_impact

// Terse depth
depth_clause: "DEPTH"i INT -> depth
            | "d"i INT -> depth
            | "d" INT -> depth

// Terse order
order_clause: "ORDER"i "BY"i order_field ("," order_field)* -> order_by
            | "sort"i order_field ("," order_field)* -> order_by

order_field: field_name order_dir?
order_dir: "DESC"i -> desc
         | "ASC"i -> asc
         | "-" -> desc
         | "+" -> asc

// Terse limit (just a number at the end)
limit_clause: "LIMIT"i INT -> limit
            | "lim"i INT -> limit
            | INT -> limit  // Bare number at end = limit
```

**Acceptance Criteria**:
- [ ] All terse aliases parse correctly
- [ ] Verbose syntax still works unchanged
- [ ] Grammar is unambiguous
- [ ] Parser tests cover both syntaxes

---

### Task 2: Update MUQLTransformer for Terse Syntax

**File(s)**: `src/mu/kernel/muql/parser.py`

**Description**: Ensure the transformer produces identical AST for both verbose and terse syntax.

```python
class MUQLTransformer(Transformer):
    """Transform parse tree to AST.
    
    Both verbose and terse syntax produce identical AST nodes.
    """
    
    # Node type transforms - all aliases map to same enum
    def functions(self, _): return NodeTypeFilter.FUNCTIONS
    def fn(self, _): return NodeTypeFilter.FUNCTIONS  # Alias
    def f(self, _): return NodeTypeFilter.FUNCTIONS   # Alias
    
    def classes(self, _): return NodeTypeFilter.CLASSES
    def cls(self, _): return NodeTypeFilter.CLASSES   # Alias
    def c(self, _): return NodeTypeFilter.CLASSES     # Alias
    
    # Field transforms
    def complexity(self, _): return "complexity"
    def c_field(self, _): return "complexity"  # Alias (context: field not type)
    
    def name_field(self, _): return "name"
    def n_field(self, _): return "name"  # Alias
    
    # Operator transforms
    def like(self, _): return ComparisonOp.LIKE
    def tilde(self, _): return ComparisonOp.LIKE  # ~ alias
    
    # Terse SELECT handling
    def terse_select(self, items):
        """Handle terse SELECT: `fn c>50` -> full SelectQuery."""
        node_type = items[0]
        condition = None
        order_by = None
        limit = None
        
        for item in items[1:]:
            if isinstance(item, Condition):
                condition = item
            elif isinstance(item, list) and item and isinstance(item[0], OrderField):
                order_by = item
            elif isinstance(item, int):
                limit = item
        
        return SelectQuery(
            query_type=QueryType.SELECT,
            fields=[SelectField(name="*", is_star=True)],
            node_type=node_type,
            where=condition,
            order_by=order_by,
            limit=limit,
        )
    
    # Terse SHOW handling
    def show_deps(self, items):
        """Handle `deps Node` -> ShowQuery."""
        return ShowQuery(
            query_type=QueryType.SHOW,
            show_type=ShowType.DEPENDENCIES,
            target=items[0],
            depth=items[1] if len(items) > 1 else 1,
        )
```

**Acceptance Criteria**:
- [ ] `fn c>50` produces same AST as `SELECT * FROM functions WHERE complexity > 50`
- [ ] `deps X d2` produces same AST as `SHOW DEPENDENCIES OF X DEPTH 2`
- [ ] All aliases tested
- [ ] No regressions in existing query parsing

---

### Task 3: Update Rust Parser for Terse Syntax

**File(s)**: `mu-daemon/src/muql/parser.rs`

**Discovery First**:
```bash
cat mu-daemon/src/muql/parser.rs | head -100
```

**Description**: Mirror the Python parser changes in the Rust implementation.

```rust
// In parser.rs - add terse alternatives to PEG grammar

// Node types
node_type = { 
    ^"functions" | ^"fn" | ^"f" |
    ^"classes" | ^"cls" | ^"c" |
    ^"modules" | ^"mod" | ^"m" |
    ^"methods" | ^"meth" | ^"mt" |
    ^"nodes" | ^"n"
}

// Comparison operators
comparison_op = {
    "=" | "!=" | ">" | "<" | ">=" | "<=" |
    ^"like" | "~"  // ~ as terse LIKE
}

// Terse commands
terse_command = {
    deps_command |
    rdeps_command |
    callers_command |
    callees_command |
    impact_command |
    terse_select
}

deps_command = { ^"deps" ~ node_ref ~ depth_clause? }
callers_command = { ^"callers" ~ node_ref ~ depth_clause? }
depth_clause = { (^"depth" | ^"d") ~ integer }

terse_select = { node_type ~ condition? ~ order_clause? ~ limit_clause? }
```

**Acceptance Criteria**:
- [ ] Rust parser handles all terse syntax
- [ ] Results identical between Python and Rust parsers
- [ ] Performance acceptable (< 1ms parse time)

---

### Task 4: Add Query Normalization for Debugging

**File(s)**: `src/mu/kernel/muql/parser.py`

**Description**: Add ability to normalize terse queries to verbose form for debugging and logging.

```python
class MUQLParser:
    def parse(self, query: str) -> Query:
        """Parse MUQL query (verbose or terse)."""
        # ... existing parsing ...
    
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
            parts.append(f"FROM {ast.node_type.value}")
            
            # WHERE
            if ast.where:
                parts.append(f"WHERE {self._condition_to_verbose(ast.where)}")
            
            # ORDER BY
            if ast.order_by:
                order_str = ", ".join(
                    f"{f.name} {'DESC' if f.descending else 'ASC'}"
                    for f in ast.order_by
                )
                parts.append(f"ORDER BY {order_str}")
            
            # LIMIT
            if ast.limit:
                parts.append(f"LIMIT {ast.limit}")
            
            return " ".join(parts)
        
        elif isinstance(ast, ShowQuery):
            depth_str = f" DEPTH {ast.depth}" if ast.depth else ""
            return f"SHOW {ast.show_type.value} OF {ast.target}{depth_str}"
        
        # ... handle other query types ...
```

**Acceptance Criteria**:
- [ ] `normalize()` converts terse to verbose
- [ ] Normalized queries are valid MUQL
- [ ] Round-trip: `parse(normalize(q))` == `parse(q)`

---

### Task 5: Update `mu llm` Spec with Terse Syntax

**File(s)**: `src/mu/commands/llm_spec.py` or related spec files

**Description**: Include terse syntax in the LLM specification so AI agents know they can use it.

```markdown
## MUQL Terse Syntax (Optimized for LLMs)

MUQL supports a terse syntax optimized for minimal token usage:

### Quick Reference

| Verbose | Terse | Example |
|---------|-------|---------|
| `SELECT * FROM functions WHERE` | `fn` | `fn c>50` |
| `SELECT * FROM classes WHERE` | `cls` | `cls n~Service` |
| `complexity` | `c` | `fn c>50` |
| `name LIKE` | `n~` | `fn n~auth` |
| `SHOW DEPENDENCIES OF X DEPTH N` | `deps X dN` | `deps Auth d2` |
| `SHOW CALLERS OF X` | `callers X` | `callers main` |
| `ORDER BY X DESC` | `sort x-` | `fn sort c-` |
| `LIMIT N` | `N` (at end) | `fn c>50 10` |

### Examples

```
# Find complex functions (top 10)
fn c>50 sort c- 10

# Dependencies of AuthService, 2 levels deep
deps AuthService d2

# Functions calling Redis
fn calling Redis

# Classes with @dataclass decorator  
cls @dataclass

# Path between two nodes
path UserService Database d5
```

Both verbose SQL-like syntax and terse syntax are fully supported.
```

**Acceptance Criteria**:
- [ ] Terse syntax documented in `mu llm` output
- [ ] Examples are accurate and tested
- [ ] Format is LLM-friendly (clear, concise)

---

### Task 6: Unit Tests for Terse Syntax

**File(s)**: `tests/unit/test_muql_terse.py` (new file)

```python
import pytest
from mu.kernel.muql.parser import MUQLParser
from mu.kernel.muql.ast import (
    SelectQuery, ShowQuery, QueryType, ShowType,
    NodeTypeFilter, ComparisonOp,
)


class TestTerseSyntaxParsing:
    """Tests for terse MUQL syntax."""
    
    @pytest.fixture
    def parser(self):
        return MUQLParser()
    
    # Node type aliases
    @pytest.mark.parametrize("terse,verbose", [
        ("fn c>50", "SELECT * FROM functions WHERE complexity > 50"),
        ("f c>50", "SELECT * FROM functions WHERE complexity > 50"),
        ("cls n~Service", "SELECT * FROM classes WHERE name LIKE '%Service%'"),
        ("c n~Service", "SELECT * FROM classes WHERE name LIKE '%Service%'"),
        ("mod", "SELECT * FROM modules"),
        ("m", "SELECT * FROM modules"),
    ])
    def test_node_type_aliases(self, parser, terse, verbose):
        """Terse and verbose should produce equivalent AST."""
        terse_ast = parser.parse(terse)
        verbose_ast = parser.parse(verbose)
        
        assert type(terse_ast) == type(verbose_ast)
        assert terse_ast.node_type == verbose_ast.node_type
    
    # Field aliases
    @pytest.mark.parametrize("terse,expected_field", [
        ("fn c>50", "complexity"),
        ("fn n~auth", "name"),
        ("fn fp~src/", "file_path"),
        ("fn qn~module.Class", "qualified_name"),
    ])
    def test_field_aliases(self, parser, terse, expected_field):
        """Field aliases should resolve correctly."""
        ast = parser.parse(terse)
        assert ast.where.comparisons[0].field == expected_field
    
    # Operator aliases
    @pytest.mark.parametrize("terse,expected_op", [
        ("fn n~auth", ComparisonOp.LIKE),
        ("fn c>50", ComparisonOp.GT),
        ("fn c>=50", ComparisonOp.GTE),
        ("fn n=main", ComparisonOp.EQ),
    ])
    def test_operator_aliases(self, parser, terse, expected_op):
        """Operator aliases should resolve correctly."""
        ast = parser.parse(terse)
        assert ast.where.comparisons[0].op == expected_op
    
    # Show command aliases
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
    def test_show_aliases(self, parser, terse, expected_type, expected_depth):
        """SHOW command aliases should parse correctly."""
        ast = parser.parse(terse)
        assert isinstance(ast, ShowQuery)
        assert ast.show_type == expected_type
        assert ast.depth == expected_depth
    
    # Order and limit
    @pytest.mark.parametrize("terse,expected_desc,expected_limit", [
        ("fn c>50 sort c-", True, None),
        ("fn c>50 sort c+", False, None),
        ("fn c>50 sort c desc", True, None),
        ("fn c>50 sort c asc", False, None),
        ("fn c>50 10", None, 10),
        ("fn c>50 sort c- 10", True, 10),
        ("fn c>50 lim 10", None, 10),
    ])
    def test_order_and_limit(self, parser, terse, expected_desc, expected_limit):
        """Order and limit aliases should work."""
        ast = parser.parse(terse)
        
        if expected_limit is not None:
            assert ast.limit == expected_limit
        
        if expected_desc is not None:
            assert ast.order_by[0].descending == expected_desc


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
        """Normalization should produce readable verbose syntax."""
        normalized = parser.normalize(terse)
        assert normalized == expected_verbose


class TestBackwardCompatibility:
    """Ensure existing verbose syntax still works."""
    
    @pytest.fixture
    def parser(self):
        return MUQLParser()
    
    @pytest.mark.parametrize("query", [
        "SELECT * FROM functions WHERE complexity > 50",
        "SELECT name, complexity FROM functions ORDER BY complexity DESC",
        "SHOW DEPENDENCIES OF AuthService DEPTH 2",
        "FIND functions CALLING Redis",
        "PATH FROM A TO B MAX_DEPTH 5",
        "FIND CYCLES",
        "ANALYZE COMPLEXITY",
    ])
    def test_verbose_still_works(self, parser, query):
        """All existing verbose queries should still parse."""
        ast = parser.parse(query)
        assert ast is not None
```

**Acceptance Criteria**:
- [ ] All terse aliases tested
- [ ] Normalization tested
- [ ] Backward compatibility verified
- [ ] Tests pass in CI

---

### Task 7: Integration Test - Token Reduction

**File(s)**: `tests/integration/test_terse_tokens.py`

```python
import pytest
import tiktoken  # or similar tokenizer


class TestTokenReduction:
    """Verify that terse syntax actually reduces token count."""
    
    @pytest.fixture
    def tokenizer(self):
        # Use cl100k_base (GPT-4/Claude tokenizer approximation)
        return tiktoken.get_encoding("cl100k_base")
    
    @pytest.mark.parametrize("verbose,terse,min_savings", [
        (
            "SELECT * FROM functions WHERE complexity > 50",
            "fn c>50",
            0.70,  # Expect at least 70% reduction
        ),
        (
            "SHOW DEPENDENCIES OF AuthService DEPTH 2",
            "deps AuthService d2",
            0.50,
        ),
        (
            "SELECT name, complexity FROM functions WHERE complexity > 30 ORDER BY complexity DESC LIMIT 10",
            "s n,c fn c>30 sort c- 10",
            0.60,
        ),
        (
            "FIND functions CALLING Redis",
            "fn calling Redis",
            0.40,
        ),
    ])
    def test_token_savings(self, tokenizer, verbose, terse, min_savings):
        """Terse syntax should save significant tokens."""
        verbose_tokens = len(tokenizer.encode(verbose))
        terse_tokens = len(tokenizer.encode(terse))
        
        savings = 1 - (terse_tokens / verbose_tokens)
        
        assert savings >= min_savings, (
            f"Expected {min_savings*100}% savings, got {savings*100:.1f}%\n"
            f"Verbose ({verbose_tokens} tokens): {verbose}\n"
            f"Terse ({terse_tokens} tokens): {terse}"
        )
    
    def test_mcp_query_token_budget(self, tokenizer):
        """Typical MCP query should fit in minimal tokens."""
        # Simulate a multi-query MCP interaction
        queries = [
            "fn n~payment c>20",
            "deps PaymentService d2",
            "callers process_payment",
        ]
        
        total_tokens = sum(len(tokenizer.encode(q)) for q in queries)
        
        # All queries combined should be under 50 tokens
        assert total_tokens < 50, f"MCP queries used {total_tokens} tokens"
```

**Acceptance Criteria**:
- [ ] Token savings measured and verified
- [ ] Minimum 50% reduction for common queries
- [ ] MCP query budget stays under 50 tokens for typical workflows

---

## Dependencies

```
Task 1 (Grammar)
    ↓
Task 2 (Python Transformer) ←─── Must match grammar
    ↓
Task 3 (Rust Parser) ←────────── Must match Python behavior
    ↓
Task 4 (Normalization) ←──────── Uses parser internals
    ↓
Task 5 (LLM Spec)
Task 6 (Unit Tests)
Task 7 (Token Tests)
```

---

## Implementation Order

| Priority | Task | Effort | Risk |
|----------|------|--------|------|
| P0 | Task 1: Extend Grammar | Medium (1.5h) | Medium - grammar changes |
| P0 | Task 2: Python Transformer | Medium (1h) | Low |
| P0 | Task 6: Unit Tests | Medium (1h) | Low |
| P1 | Task 3: Rust Parser | Medium (1.5h) | Medium - must match Python |
| P1 | Task 4: Normalization | Small (30m) | Low |
| P2 | Task 5: LLM Spec | Small (30m) | Low |
| P2 | Task 7: Token Tests | Small (30m) | Low |

**Total Estimated Effort**: 6-7 hours

---

## Success Metrics

1. **Token Reduction**: Average 60%+ reduction in query tokens
2. **Backward Compatibility**: 100% of existing queries still work
3. **Parse Performance**: No regression in parse time (< 1ms)
4. **Adoption**: Claude Code uses terse syntax in 80%+ of queries

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| `c` alone (ambiguous: class or complexity?) | Context determines: `c>50` = complexity, `c n~X` = classes |
| Mixed syntax (`SELECT * FROM fn`) | Error - don't mix verbose and terse |
| Unknown alias | Parse error with suggestion |
| Empty query | Error with example syntax |
| Chained queries (`fn c>50 + deps d2`) | Parse as two queries, execute sequentially |

---

## Rollback Plan

If issues arise:
1. Grammar additions are additive - remove terse rules
2. Keep verbose syntax as primary
3. Feature flag: `MU_TERSE_SYNTAX=0` to disable
