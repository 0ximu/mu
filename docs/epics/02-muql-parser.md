# Epic 2: MUQL Parser

**Priority**: P1 - Core query interface for MUbase
**Dependencies**: Kernel (complete)
**Estimated Complexity**: High
**PRD Reference**: Section 0.5

---

## Overview

Implement MUQL (MU Query Language) - a unified query language for graph, vector, and temporal queries. MUQL provides an intuitive SQL-like interface for exploring codebases.

## Goals

1. Parse MUQL syntax into executable query plans
2. Translate queries to efficient DuckDB SQL
3. Support graph traversal, pattern matching, and analysis queries
4. Enable combined queries (graph + vector + temporal)

---

## User Stories

### Story 2.1: MUQL Grammar
**As a** developer
**I want** a well-defined query syntax
**So that** I can write predictable, readable queries

**Acceptance Criteria**:
- [ ] EBNF grammar defined for all query types
- [ ] Lark parser grammar file (.lark)
- [ ] Syntax error messages are helpful
- [ ] Grammar supports all PRD examples

### Story 2.2: SELECT Queries
**As a** developer
**I want** to query nodes with filters
**So that** I can find specific code elements

**Acceptance Criteria**:
- [ ] `SELECT * FROM functions WHERE complexity > 500`
- [ ] Field selection: `SELECT name, complexity FROM functions`
- [ ] Aggregates: `SELECT COUNT(*) FROM classes`
- [ ] ORDER BY and LIMIT clauses
- [ ] Boolean conditions with AND/OR

### Story 2.3: SHOW Queries
**As a** developer
**I want** to explore relationships
**So that** I can understand code dependencies

**Acceptance Criteria**:
- [ ] `SHOW dependencies OF AuthService`
- [ ] `SHOW dependents OF UserRepository`
- [ ] `SHOW callers OF process_payment`
- [ ] `SHOW inheritance OF AdminUser`
- [ ] DEPTH clause for traversal depth

### Story 2.4: FIND Queries
**As a** developer
**I want** pattern-based code search
**So that** I can find code by behavior

**Acceptance Criteria**:
- [ ] `FIND functions CALLING Redis`
- [ ] `FIND classes IMPLEMENTING Repository`
- [ ] `FIND functions WITH DECORATOR "cache"`
- [ ] `FIND functions MUTATING User`
- [ ] Combined conditions

### Story 2.5: PATH Queries
**As a** developer
**I want** to find paths between nodes
**So that** I can understand code flow

**Acceptance Criteria**:
- [ ] `PATH FROM UserController TO Database`
- [ ] MAX DEPTH constraint
- [ ] VIA edge type filter
- [ ] Return shortest path by default

### Story 2.6: ANALYZE Queries
**As a** developer
**I want** built-in analysis commands
**So that** I can assess code quality

**Acceptance Criteria**:
- [ ] `ANALYZE coupling` - module coupling metrics
- [ ] `ANALYZE complexity` - complexity hotspots
- [ ] `ANALYZE circular` - circular dependencies
- [ ] `ANALYZE impact FOR UserService` - impact analysis
- [ ] FOR clause to scope analysis

### Story 2.7: Query CLI
**As a** developer
**I want** MUQL from the command line
**So that** I can query without writing code

**Acceptance Criteria**:
- [ ] `mu query "<MUQL>"` - single query
- [ ] `mu query --interactive` - REPL mode
- [ ] Output formats: table, json, csv
- [ ] Query history in REPL

---

## Technical Design

### Grammar (Lark)

```lark
// muql.lark - MUQL Grammar

start: query

query: select_query
     | show_query
     | find_query
     | path_query
     | analyze_query

// SELECT queries
select_query: "SELECT"i fields "FROM"i node_type where_clause? order_clause? limit_clause?

fields: "*" -> all_fields
      | field ("," field)*

field: NAME
     | aggregate

aggregate: ("COUNT"i | "AVG"i | "MAX"i | "MIN"i | "SUM"i) "(" field ")"

node_type: "functions"i -> functions
         | "classes"i -> classes
         | "modules"i -> modules
         | "entities"i -> entities
         | "externals"i -> externals

where_clause: "WHERE"i condition

condition: comparison (("AND"i | "OR"i) comparison)*

comparison: field operator value

operator: "=" -> eq
        | "!=" -> neq
        | ">" -> gt
        | "<" -> lt
        | ">=" -> gte
        | "<=" -> lte
        | "LIKE"i -> like
        | "IN"i -> in_
        | "CONTAINS"i -> contains
        | "SIMILAR"i "TO"i -> similar_to

value: STRING
     | NUMBER
     | BOOLEAN
     | list

list: "(" value ("," value)* ")"

order_clause: "ORDER"i "BY"i field ("ASC"i | "DESC"i)?

limit_clause: "LIMIT"i NUMBER

// SHOW queries
show_query: "SHOW"i show_type "OF"i identifier depth_clause?

show_type: "dependencies"i -> dependencies
         | "dependents"i -> dependents
         | "imports"i -> imports
         | "callers"i -> callers
         | "callees"i -> callees
         | "inheritance"i -> inheritance
         | "implementations"i -> implementations

depth_clause: "DEPTH"i NUMBER

// FIND queries
find_query: "FIND"i node_type find_condition

find_condition: "CALLING"i identifier -> calling
              | "CALLED"i "BY"i identifier -> called_by
              | "IMPORTING"i identifier -> importing
              | "IMPORTED"i "BY"i identifier -> imported_by
              | "SIMILAR"i "TO"i identifier -> similar_to_node
              | "IMPLEMENTING"i identifier -> implementing
              | "INHERITING"i identifier -> inheriting
              | "MUTATING"i identifier -> mutating
              | "WITH"i "DECORATOR"i STRING -> with_decorator
              | "WITH"i "ANNOTATION"i STRING -> with_annotation
              | "MATCHING"i STRING -> matching

// PATH queries
path_query: "PATH"i "FROM"i identifier "TO"i identifier max_depth_clause? via_clause?

max_depth_clause: "MAX"i "DEPTH"i NUMBER

via_clause: "VIA"i edge_type

edge_type: "CALLS"i | "IMPORTS"i | "INHERITS"i | "USES"i | "CONTAINS"i

// ANALYZE queries
analyze_query: "ANALYZE"i analysis_type for_clause?

analysis_type: "coupling"i -> coupling
             | "cohesion"i -> cohesion
             | "complexity"i -> complexity
             | "hotspots"i -> hotspots
             | "circular"i -> circular
             | "unused"i -> unused
             | "impact"i -> impact

for_clause: "FOR"i identifier

// Common
identifier: NAME | QUALIFIED_NAME

NAME: /[a-zA-Z_][a-zA-Z0-9_]*/
QUALIFIED_NAME: /[a-zA-Z_][a-zA-Z0-9_.\/]*/
STRING: /"[^"]*"/ | /'[^']*'/
NUMBER: /\d+/
BOOLEAN: "true"i | "false"i

%import common.WS
%ignore WS
```

### File Structure

```
src/mu/kernel/
├── muql/
│   ├── __init__.py          # Public API: parse(), execute()
│   ├── grammar.lark         # Lark grammar file
│   ├── parser.py            # MUQLParser class
│   ├── ast.py               # Query AST nodes
│   ├── planner.py           # Query planner
│   ├── executor.py          # Query executor
│   ├── analyzer.py          # Built-in analysis queries
│   └── formatter.py         # Result formatting
```

### AST Model

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class SelectQuery:
    """SELECT query AST."""
    fields: list[str] | Literal["*"]
    node_type: str
    where: Condition | None = None
    order_by: tuple[str, str] | None = None  # (field, ASC|DESC)
    limit: int | None = None


@dataclass
class ShowQuery:
    """SHOW query AST."""
    show_type: str  # dependencies, callers, etc.
    target: str     # node identifier
    depth: int = 1


@dataclass
class FindQuery:
    """FIND query AST."""
    node_type: str
    condition_type: str  # calling, implementing, etc.
    condition_value: str


@dataclass
class PathQuery:
    """PATH query AST."""
    from_node: str
    to_node: str
    max_depth: int = 10
    via_edge: str | None = None


@dataclass
class AnalyzeQuery:
    """ANALYZE query AST."""
    analysis_type: str
    target: str | None = None


Query = SelectQuery | ShowQuery | FindQuery | PathQuery | AnalyzeQuery
```

### Query Engine

```python
class MUQLEngine:
    """Parse and execute MUQL queries."""

    def __init__(self, mubase: MUbase):
        self.mubase = mubase
        self.parser = MUQLParser()
        self.planner = QueryPlanner()
        self.executor = QueryExecutor(mubase)

    def execute(self, query: str) -> QueryResult:
        """Parse and execute a MUQL query."""
        ast = self.parser.parse(query)
        plan = self.planner.plan(ast)
        return self.executor.run(plan)


class QueryPlanner:
    """Convert AST to execution plan."""

    def plan(self, ast: Query) -> ExecutionPlan:
        match ast:
            case SelectQuery():
                return self._plan_select(ast)
            case ShowQuery():
                return self._plan_show(ast)
            case FindQuery():
                return self._plan_find(ast)
            case PathQuery():
                return self._plan_path(ast)
            case AnalyzeQuery():
                return self._plan_analyze(ast)

    def _plan_select(self, q: SelectQuery) -> SQLPlan:
        """Convert SELECT to DuckDB SQL."""
        ...


class QueryExecutor:
    """Execute query plans against MUbase."""

    def run(self, plan: ExecutionPlan) -> QueryResult:
        """Execute plan and return results."""
        if isinstance(plan, SQLPlan):
            rows = self.mubase.conn.execute(plan.sql, plan.params).fetchall()
            return QueryResult(
                columns=plan.columns,
                rows=rows,
                total=len(rows),
            )
        elif isinstance(plan, GraphPlan):
            return self._execute_graph(plan)
        ...
```

---

## Implementation Plan

### Phase 1: Grammar & Parser (Day 1)
1. Create `muql/grammar.lark` with full MUQL grammar
2. Implement `MUQLParser` using Lark
3. Add syntax error handling with helpful messages
4. Test parsing of all PRD examples

### Phase 2: AST & Planner (Day 1-2)
1. Define AST dataclasses for all query types
2. Implement Lark transformer to build AST
3. Create `QueryPlanner` with pattern matching
4. Implement SQL generation for SELECT queries

### Phase 3: Executor - SELECT (Day 2)
1. Implement `QueryExecutor` for SQL plans
2. Map node_type to DuckDB table queries
3. Handle field selection and aggregates
4. Add WHERE clause translation
5. Implement ORDER BY and LIMIT

### Phase 4: Executor - SHOW (Day 2-3)
1. Implement graph traversal for SHOW queries
2. Use existing `get_dependencies()` and `get_dependents()`
3. Add depth-limited traversal
4. Format results as tree structure

### Phase 5: Executor - FIND (Day 3)
1. Implement pattern matching queries
2. CALLING/CALLED BY using edge traversal
3. WITH DECORATOR using property queries
4. SIMILAR TO (prepare for vector layer)

### Phase 6: Executor - PATH (Day 3-4)
1. Implement path finding with CTE
2. Add max depth constraint
3. Filter by edge type
4. Return path as node list

### Phase 7: Executor - ANALYZE (Day 4)
1. Implement coupling analysis
2. Implement complexity hotspots
3. Implement circular dependency detection
4. Add impact analysis

### Phase 8: CLI Integration (Day 4-5)
1. Add `mu query` command
2. Implement REPL with readline
3. Add output formatters (table, json, csv)
4. Add query history and tab completion

### Phase 9: Testing (Day 5)
1. Parser tests for all query types
2. Executor tests with sample database
3. Integration tests with real codebase
4. Error handling tests

---

## Query Translation Examples

### SELECT Translation

```
MUQL: SELECT name, complexity FROM functions WHERE complexity > 500 ORDER BY complexity DESC LIMIT 10

SQL:  SELECT name, complexity FROM nodes
      WHERE type = 'FUNCTION' AND complexity > 500
      ORDER BY complexity DESC
      LIMIT 10
```

### SHOW Translation

```
MUQL: SHOW dependencies OF AuthService DEPTH 3

Execution:
1. Find node with name = 'AuthService'
2. Call mubase.get_dependencies(node_id, depth=3)
3. Format as tree
```

### FIND Translation

```
MUQL: FIND functions CALLING Redis

SQL:  SELECT DISTINCT n.* FROM nodes n
      JOIN edges e ON n.id = e.source_id
      WHERE n.type = 'FUNCTION'
        AND e.type = 'CALLS'
        AND e.target_id IN (
          SELECT id FROM nodes WHERE name = 'Redis'
        )
```

### PATH Translation

```
MUQL: PATH FROM UserController TO Database MAX DEPTH 5

SQL:  WITH RECURSIVE paths AS (
        SELECT source_id, target_id, [source_id, target_id] as path, 1 as depth
        FROM edges WHERE source_id = <UserController.id>
        UNION ALL
        SELECT p.source_id, e.target_id, list_append(p.path, e.target_id), p.depth + 1
        FROM paths p JOIN edges e ON p.target_id = e.source_id
        WHERE p.depth < 5 AND NOT list_contains(p.path, e.target_id)
      )
      SELECT path FROM paths WHERE target_id = <Database.id>
      ORDER BY depth LIMIT 1
```

---

## CLI Interface

```bash
# Single query
$ mu query "SELECT * FROM functions WHERE complexity > 500"
┌────────────────────┬────────────┬────────────┐
│ name               │ complexity │ file_path  │
├────────────────────┼────────────┼────────────┤
│ process_payment    │ 723        │ payments.py│
│ validate_order     │ 612        │ orders.py  │
└────────────────────┴────────────┴────────────┘

# JSON output
$ mu query "SHOW dependencies OF AuthService" --format json
{
  "node": "AuthService",
  "dependencies": [
    {"name": "UserRepository", "type": "internal"},
    {"name": "jwt", "type": "external"}
  ]
}

# Interactive REPL
$ mu query --interactive
MUQL> SELECT COUNT(*) FROM functions
┌──────────┐
│ count(*) │
├──────────┤
│ 342      │
└──────────┘

MUQL> SHOW dependencies OF AuthService DEPTH 2
AuthService
├── UserRepository
│   └── Database
├── TokenService
│   └── jwt
└── CacheService
    └── Redis

MUQL> .quit
```

---

## Testing Strategy

### Parser Tests
```python
def test_parse_select_with_where():
    ast = parse("SELECT name FROM functions WHERE complexity > 100")
    assert isinstance(ast, SelectQuery)
    assert ast.fields == ["name"]
    assert ast.node_type == "functions"
    assert ast.where is not None

def test_parse_show_with_depth():
    ast = parse("SHOW dependencies OF AuthService DEPTH 3")
    assert isinstance(ast, ShowQuery)
    assert ast.depth == 3
```

### Executor Tests
```python
def test_select_returns_results(populated_mubase):
    result = execute(populated_mubase, "SELECT * FROM functions")
    assert len(result.rows) > 0
    assert "name" in result.columns

def test_show_dependencies(populated_mubase):
    result = execute(populated_mubase, "SHOW dependencies OF main")
    assert isinstance(result, TreeResult)
```

---

## Success Criteria

- [ ] All PRD example queries parse correctly
- [ ] Query execution returns correct results
- [ ] REPL provides good developer experience
- [ ] Error messages are helpful for debugging
- [ ] Query performance < 100ms for typical queries

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Complex grammar | High | Start with core queries, add incrementally |
| Lark learning curve | Medium | Lark is well-documented; simple grammar |
| Performance | Medium | Use DuckDB SQL where possible |
| Edge cases | Medium | Comprehensive test suite |

---

## Future Enhancements

1. **Temporal queries**: `AT commit`, `BETWEEN commits`
2. **Vector queries**: `SIMILAR TO "description"`
3. **Combined queries**: Graph + Vector + Temporal
4. **Query optimization**: Plan caching, index hints
5. **Saved queries**: Named queries in .murc.toml
