# MUQL Parser - Task Breakdown

## Business Context

**Problem**: Developers need a unified, SQL-like query language to explore codebases stored in MUbase. Currently, querying the graph database requires Python code or raw SQL, which is cumbersome and error-prone.

**Outcome**: Implement MUQL (MU Query Language) - an intuitive query interface supporting SELECT, SHOW, FIND, PATH, and ANALYZE queries. Developers can explore code structure, dependencies, and patterns using familiar SQL-like syntax.

**Users**: Developers using MU to understand codebases, find code patterns, analyze dependencies, and assess code quality.

---

## Discovered Patterns

| Pattern | File | Relevance |
|---------|------|-----------|
| Dataclass with `to_dict()` | `/Users/imu/Dev/work/mu/src/mu/kernel/models.py:15-86` | AST nodes should follow this pattern |
| Enum definitions | `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:12-28` | Query types, node types use Enum |
| DuckDB schema SQL | `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:32-76` | Query plans translate to SQL |
| MUbase query methods | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:133-459` | Executor uses existing MUbase methods |
| CLI command structure | `/Users/imu/Dev/work/mu/src/mu/cli.py:999-1103` | `kernel query` command pattern |
| Module `__init__.py` exports | `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py` | Public API exposure pattern |
| Test organization | `/Users/imu/Dev/work/mu/tests/unit/test_kernel.py` | Test class structure |
| Pydantic config models | `/Users/imu/Dev/work/mu/src/mu/config.py:13-231` | Configuration patterns |

---

## Task Breakdown

### Task 1: Create MUQL Module Structure

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/__init__.py`
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/grammar.lark`

**Dependencies**: None (first task)

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py` for module exports

**Description**:
Create the MUQL module directory and the Lark grammar file. Add `lark` to project dependencies in `pyproject.toml`.

**Acceptance**:
- [ ] `src/mu/kernel/muql/` directory exists
- [ ] `__init__.py` with placeholder public API
- [ ] `grammar.lark` with full MUQL grammar from epic
- [ ] `lark>=1.1.0` added to `pyproject.toml` dependencies
- [ ] Grammar compiles without errors

**Status**: pending

---

### Task 2: Implement AST Node Models

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/ast.py`

**Dependencies**: Task 1

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/kernel/models.py` dataclass pattern with `to_dict()`

**Description**:
Define AST dataclasses for all query types: SelectQuery, ShowQuery, FindQuery, PathQuery, AnalyzeQuery. Include Condition, Comparison, and aggregate types.

**Acceptance**:
- [ ] `SelectQuery` dataclass with fields, node_type, where, order_by, limit
- [ ] `ShowQuery` dataclass with show_type, target, depth
- [ ] `FindQuery` dataclass with node_type, condition_type, condition_value
- [ ] `PathQuery` dataclass with from_node, to_node, max_depth, via_edge
- [ ] `AnalyzeQuery` dataclass with analysis_type, target
- [ ] `Condition` and `Comparison` supporting types
- [ ] All dataclasses have `to_dict()` method
- [ ] Union type `Query` for all query types

**Status**: pending

---

### Task 3: Implement Lark Parser and Transformer

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/parser.py`

**Dependencies**: Task 1, Task 2

**Pattern**: Lark transformer pattern (convert parse tree to AST)

**Description**:
Create `MUQLParser` class that loads the grammar and transforms parse trees into AST nodes. Implement `MUQLTransformer` extending `lark.Transformer`.

**Acceptance**:
- [ ] `MUQLParser` class with `parse(query: str) -> Query` method
- [ ] `MUQLTransformer` converts all query types to AST nodes
- [ ] Handles case-insensitive keywords (SELECT, select, Select)
- [ ] Extracts string values without quotes
- [ ] Converts NUMBER tokens to int
- [ ] Handles LIST values in conditions
- [ ] Clear error messages for syntax errors

**Status**: pending

---

### Task 4: Implement Query Planner

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/planner.py`

**Dependencies**: Task 2

**Pattern**: Follow pattern matching style from epic design

**Description**:
Create `QueryPlanner` that converts AST nodes to execution plans. Define `ExecutionPlan` types: `SQLPlan`, `GraphPlan`, `AnalysisPlan`.

**Acceptance**:
- [ ] `ExecutionPlan` base class/protocol
- [ ] `SQLPlan` with sql string, params, expected columns
- [ ] `GraphPlan` for traversal queries (SHOW, PATH)
- [ ] `AnalysisPlan` for ANALYZE queries
- [ ] `QueryPlanner.plan(ast: Query) -> ExecutionPlan` method
- [ ] Pattern matching on query types
- [ ] SQL generation for SELECT queries (WHERE, ORDER BY, LIMIT)
- [ ] Maps node_type to correct DuckDB table filters

**Status**: pending

---

### Task 5: Implement Query Executor - SELECT

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/executor.py`

**Dependencies**: Task 4

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:498-512` execute method

**Description**:
Create `QueryExecutor` that runs execution plans against MUbase. Start with SELECT query support via SQL execution.

**Acceptance**:
- [ ] `QueryExecutor` class with `run(plan: ExecutionPlan) -> QueryResult`
- [ ] `QueryResult` dataclass with columns, rows, total
- [ ] Execute SQLPlan using `mubase.execute()`
- [ ] Field selection (SELECT name, complexity FROM ...)
- [ ] Aggregate functions (COUNT, AVG, MAX, MIN, SUM)
- [ ] WHERE clause conditions (=, !=, >, <, >=, <=, LIKE, IN, CONTAINS)
- [ ] Boolean AND/OR in conditions
- [ ] ORDER BY ASC/DESC
- [ ] LIMIT clause

**Status**: pending

---

### Task 6: Implement Query Executor - SHOW

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/executor.py` (extend)

**Dependencies**: Task 5

**Pattern**: Use existing `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:218-324` get_dependencies/dependents

**Description**:
Add SHOW query execution that uses MUbase graph traversal methods. Return results as tree structure.

**Acceptance**:
- [ ] `TreeResult` dataclass for hierarchical results
- [ ] Execute GraphPlan for SHOW queries
- [ ] `SHOW dependencies OF <node>` uses `mubase.get_dependencies()`
- [ ] `SHOW dependents OF <node>` uses `mubase.get_dependents()`
- [ ] `SHOW callers OF <node>` via CALLS edges (when available)
- [ ] `SHOW callees OF <node>` via CALLS edges (when available)
- [ ] `SHOW inheritance OF <node>` via INHERITS edges
- [ ] `SHOW implementations OF <node>` (future: when interface edges added)
- [ ] DEPTH clause for multi-level traversal
- [ ] Node name resolution (find node by name first)

**Status**: pending

---

### Task 7: Implement Query Executor - FIND

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/executor.py` (extend)

**Dependencies**: Task 5

**Pattern**: SQL JOINs with edges table

**Description**:
Add FIND query execution for pattern-based searches. Uses SQL with edge traversal.

**Acceptance**:
- [ ] `FIND functions CALLING <target>` via edge traversal
- [ ] `FIND functions CALLED BY <source>` via reverse edge traversal
- [ ] `FIND modules IMPORTING <target>` via IMPORTS edges
- [ ] `FIND modules IMPORTED BY <source>` via reverse IMPORTS edges
- [ ] `FIND classes IMPLEMENTING <interface>` (future)
- [ ] `FIND classes INHERITING <base>` via INHERITS edges
- [ ] `FIND functions MUTATING <entity>` (future: when mutation edges added)
- [ ] `FIND functions WITH DECORATOR "<name>"` via properties JSON
- [ ] `FIND functions WITH ANNOTATION "<name>"` via properties JSON
- [ ] `FIND functions MATCHING "<pattern>"` via name LIKE
- [ ] `FIND functions SIMILAR TO <target>` (prepare for vector layer - returns error until vectors available)

**Status**: pending

---

### Task 8: Implement Query Executor - PATH

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/executor.py` (extend)

**Dependencies**: Task 5

**Pattern**: Use existing `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:411-458` find_path CTE

**Description**:
Add PATH query execution using recursive CTEs for shortest path.

**Acceptance**:
- [ ] `PATH FROM <node> TO <node>` finds shortest path
- [ ] `MAX DEPTH n` constrains search depth
- [ ] `VIA <edge_type>` filters by edge type (CALLS, IMPORTS, INHERITS, USES, CONTAINS)
- [ ] Returns path as list of node names
- [ ] Returns None/empty if no path exists
- [ ] Handles cycles (no infinite loops)

**Status**: pending

---

### Task 9: Implement Query Executor - ANALYZE

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/analyzer.py`
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/executor.py` (extend)

**Dependencies**: Task 5

**Pattern**: SQL aggregation and graph algorithms

**Description**:
Create analyzer module with built-in analysis queries. Execute AnalysisPlan via analyzer.

**Acceptance**:
- [ ] `Analyzer` class with analysis methods
- [ ] `ANALYZE coupling` - module coupling metrics (fan-in/fan-out)
- [ ] `ANALYZE cohesion` - module cohesion metrics
- [ ] `ANALYZE complexity` - complexity hotspots (top N by complexity)
- [ ] `ANALYZE hotspots` - files with most changes (requires git data - future)
- [ ] `ANALYZE circular` - circular dependency detection using CTE
- [ ] `ANALYZE unused` - unused exports (requires usage tracking - future)
- [ ] `ANALYZE impact FOR <node>` - impact analysis (what depends on this)
- [ ] FOR clause scopes analysis to specific module/class
- [ ] Returns AnalysisResult with metrics and recommendations

**Status**: pending

---

### Task 10: Result Formatting

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/formatter.py`

**Dependencies**: Task 5, Task 6

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/diff/formatters.py` pattern

**Description**:
Create formatters for query results supporting table, JSON, and CSV output.

**Acceptance**:
- [ ] `format_table(result: QueryResult) -> str` using Rich tables
- [ ] `format_json(result: QueryResult) -> str` with proper indentation
- [ ] `format_csv(result: QueryResult) -> str` for data export
- [ ] `format_tree(result: TreeResult) -> str` for SHOW queries
- [ ] Handles empty results gracefully
- [ ] Truncates long values for terminal display
- [ ] Color coding for terminal output (optional)

**Status**: pending

---

### Task 11: MUQL Engine Integration

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/__init__.py` (update)
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/engine.py`

**Dependencies**: Task 3, Task 4, Task 5, Task 10

**Pattern**: Facade pattern, follow `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py`

**Description**:
Create `MUQLEngine` class that ties parser, planner, executor, and formatter together. Export public API.

**Acceptance**:
- [ ] `MUQLEngine` class with `execute(query: str) -> QueryResult` method
- [ ] Constructor takes `mubase: MUbase`
- [ ] `execute_formatted(query: str, format: str) -> str` for CLI
- [ ] Public exports in `__init__.py`: `MUQLEngine`, `parse`, `execute`
- [ ] Update `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py` to re-export MUQL classes

**Status**: pending

---

### Task 12: CLI Integration - Single Query

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py`

**Dependencies**: Task 11

**Pattern**: Follow existing `kernel query` command at `/Users/imu/Dev/work/mu/src/mu/cli.py:999-1103`

**Description**:
Add `mu query` command for executing single MUQL queries from command line.

**Acceptance**:
- [ ] `mu query "<MUQL>"` executes query and prints result
- [ ] `--format` option: table (default), json, csv
- [ ] `--output` option to save results to file
- [ ] `--db` option to specify .mubase path (default: .mubase in cwd)
- [ ] Helpful error messages for syntax errors
- [ ] Returns exit code 1 on error
- [ ] Uses existing Rich console for output

**Status**: pending

---

### Task 13: CLI Integration - REPL Mode

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py` (extend)
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/repl.py`

**Dependencies**: Task 12

**Pattern**: Standard readline-based REPL

**Description**:
Add interactive REPL mode with history and basic tab completion.

**Acceptance**:
- [ ] `mu query --interactive` or `mu query -i` enters REPL
- [ ] `MUQL>` prompt for input
- [ ] Query history via readline (up/down arrows)
- [ ] `.quit` or `.exit` to exit
- [ ] `.help` shows available commands and syntax
- [ ] `.format <format>` changes output format
- [ ] `.clear` clears screen
- [ ] Multiline query support (semicolon to execute)
- [ ] Error recovery (don't exit on syntax error)
- [ ] History persistence (~/.mu_history)

**Status**: pending

---

### Task 14: Parser Unit Tests

**Files**:
- `/Users/imu/Dev/work/mu/tests/unit/test_muql_parser.py`

**Dependencies**: Task 3

**Pattern**: Follow `/Users/imu/Dev/work/mu/tests/unit/test_kernel.py` organization

**Description**:
Comprehensive parser tests for all query types and edge cases.

**Acceptance**:
- [ ] `TestSelectParser` class with tests for:
  - [ ] SELECT * FROM functions
  - [ ] SELECT with field selection
  - [ ] SELECT with WHERE clause
  - [ ] SELECT with ORDER BY
  - [ ] SELECT with LIMIT
  - [ ] SELECT with aggregates (COUNT, AVG, etc.)
  - [ ] Complex boolean conditions (AND/OR)
- [ ] `TestShowParser` class with tests for all show_types
- [ ] `TestFindParser` class with tests for all find conditions
- [ ] `TestPathParser` class with MAX DEPTH and VIA
- [ ] `TestAnalyzeParser` class with FOR clause
- [ ] `TestParserErrors` class for syntax error messages
- [ ] Test case-insensitivity (SELECT, select, Select)
- [ ] Test string escaping and special characters

**Status**: pending

---

### Task 15: Executor Unit Tests

**Files**:
- `/Users/imu/Dev/work/mu/tests/unit/test_muql_executor.py`

**Dependencies**: Task 5, Task 6, Task 7, Task 8, Task 9

**Pattern**: Use pytest fixtures for populated MUbase

**Description**:
Executor tests with sample database for all query types.

**Acceptance**:
- [ ] `@pytest.fixture` for populated test MUbase
- [ ] `TestSelectExecutor` tests:
  - [ ] Returns correct columns
  - [ ] WHERE filtering works
  - [ ] ORDER BY sorts correctly
  - [ ] LIMIT constrains results
  - [ ] Aggregates compute correctly
- [ ] `TestShowExecutor` tests:
  - [ ] Dependencies returned correctly
  - [ ] Dependents returned correctly
  - [ ] DEPTH traversal works
- [ ] `TestFindExecutor` tests:
  - [ ] CALLING finds correct functions
  - [ ] WITH DECORATOR filters by decorator
  - [ ] MATCHING uses LIKE pattern
- [ ] `TestPathExecutor` tests:
  - [ ] Finds shortest path
  - [ ] MAX DEPTH limits search
  - [ ] Returns None when no path
- [ ] `TestAnalyzeExecutor` tests:
  - [ ] Coupling metrics calculated
  - [ ] Circular dependencies detected
  - [ ] Complexity hotspots returned

**Status**: pending

---

### Task 16: Integration Tests

**Files**:
- `/Users/imu/Dev/work/mu/tests/integration/test_muql_integration.py`

**Dependencies**: Task 11, Task 12

**Pattern**: End-to-end tests with real codebase

**Description**:
Integration tests running MUQL against MU's own codebase.

**Acceptance**:
- [ ] Build MUbase from MU source
- [ ] Execute PRD example queries
- [ ] Verify correct results
- [ ] Test CLI command execution
- [ ] Test error handling
- [ ] Performance test: queries complete < 100ms

**Status**: pending

---

### Task 17: Documentation

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/CLAUDE.md`
- `/Users/imu/Dev/work/mu/README.md` (update)

**Dependencies**: Task 11

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/kernel/CLAUDE.md`

**Description**:
Create CLAUDE.md for the MUQL module and update README with query examples.

**Acceptance**:
- [ ] CLAUDE.md documents:
  - [ ] Module architecture
  - [ ] Query type reference
  - [ ] Usage examples
  - [ ] Extension patterns
- [ ] README updated with MUQL section
- [ ] CLI help text is comprehensive

**Status**: pending

---

## Dependencies Graph

```
Task 1 (Module Structure)
    |
    v
Task 2 (AST Models)
    |
    +---> Task 3 (Parser) ---> Task 4 (Planner) ---> Task 5 (Executor SELECT)
    |                                                      |
    |                                                      +---> Task 6 (Executor SHOW)
    |                                                      |
    |                                                      +---> Task 7 (Executor FIND)
    |                                                      |
    |                                                      +---> Task 8 (Executor PATH)
    |                                                      |
    |                                                      +---> Task 9 (Analyzer)
    |                                                      |
    |                                                      v
    |                                               Task 10 (Formatter)
    |                                                      |
    |                                                      v
    +------------------------------------------------> Task 11 (Engine)
                                                          |
                                                          v
                                                   Task 12 (CLI Single)
                                                          |
                                                          v
                                                   Task 13 (CLI REPL)

Task 14 (Parser Tests)    - depends on Task 3
Task 15 (Executor Tests)  - depends on Tasks 5-9
Task 16 (Integration)     - depends on Tasks 11-12
Task 17 (Documentation)   - depends on Task 11
```

---

## Edge Cases

1. **Node name ambiguity**: Same function name in multiple modules
   - Require qualified name or return multiple matches with disambiguation

2. **Missing nodes**: Query references non-existent node
   - Return helpful "Node not found: X. Did you mean Y?" message

3. **Empty results**: Query matches nothing
   - Return empty result with clear message, not error

4. **Very deep traversals**: DEPTH 100 on large graph
   - Cap maximum depth (default: 20)
   - Add timeout for long-running queries

5. **Circular dependencies**: PATH with cycles
   - Already handled by `find_path` CTE with `NOT list_contains()`

6. **Unicode in names**: Classes/functions with unicode characters
   - Ensure parser handles unicode identifiers

7. **Reserved words as names**: Function named `SELECT`
   - Support quoting: `"SELECT"` or `[SELECT]`

---

## Security Considerations

1. **SQL Injection**: User input goes into queries
   - Always use parameterized queries
   - Never concatenate user strings into SQL
   - Validate node_type against allowed enum values

2. **Path Traversal**: Node names could contain path chars
   - Sanitize file_path references
   - Use normalized paths only

3. **Resource Exhaustion**: Malicious queries
   - Limit result set size
   - Add query timeout
   - Cap DEPTH parameter

---

## Performance Considerations

1. **Query caching**: Same query = same result
   - Consider result caching for repeated queries

2. **Index usage**: Ensure queries use existing indexes
   - `idx_nodes_type`, `idx_nodes_name`, `idx_edges_source/target`

3. **Batch operations**: REPL with multiple queries
   - Keep DB connection open, don't reconnect per query

4. **Large result sets**: SELECT * on big codebase
   - Default LIMIT 100 for unbounded queries
   - Streaming for large exports

---

## Out of Scope (Future Work)

1. **SIMILAR TO queries**: Requires vector layer (Epic 01)
2. **Temporal queries**: Requires temporal layer (Epic 04)
3. **CALLS/MUTATES edges**: Requires call graph analysis
4. **Hotspot analysis**: Requires git integration
5. **Tab completion**: Basic support only, full semantic completion later
