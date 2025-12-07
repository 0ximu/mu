# GRAPH_REASONING Implementation Tasks

## Phase 2: MUQL Integration

### Task 1: Add Graph Query Syntax to Grammar
**Status**: ✅ Complete

**Objective**: Extend `grammar.lark` with new graph query syntax.

**New Query Types**:
```sql
-- Cycle detection
FIND CYCLES
FIND CYCLES WHERE edge_type = 'imports'

-- Impact analysis (downstream)
SHOW IMPACT OF "mod:src/auth.py"
SHOW IMPACT OF "mod:src/auth.py" WHERE edge_type IN ('imports', 'calls')

-- Ancestor analysis (upstream)
SHOW ANCESTORS OF "func:process_payment"
SHOW ANCESTORS OF "func:process_payment" DEPTH 3

-- Path finding (already exists, ensure it uses GraphManager)
FIND PATH FROM "mod:a.py" TO "mod:z.py"
FIND PATH FROM "mod:a.py" TO "mod:z.py" WHERE edge_type = 'imports'
```

**Files to Modify**:
- `src/mu/kernel/muql/grammar.lark`

---

### Task 2: Add AST Nodes for Graph Queries
**Status**: 🔲 Pending

**Objective**: Add dataclass models for new query types.

**New AST Types**:
- `CyclesQuery` - For `FIND CYCLES` queries
- Extend `ShowType` enum with `IMPACT`, `ANCESTORS`
- Add `edge_type_filter` support to `ShowQuery`

**Files to Modify**:
- `src/mu/kernel/muql/ast.py`

---

### Task 3: Add Parser Transformers
**Status**: 🔲 Pending

**Objective**: Transform parse tree into new AST nodes.

**New Transformers**:
- `find_cycles_query` → `CyclesQuery`
- `show_impact` → `ShowQuery` with `ShowType.IMPACT`
- `show_ancestors` → `ShowQuery` with `ShowType.ANCESTORS`
- `edge_type_filter_clause` → edge type list

**Files to Modify**:
- `src/mu/kernel/muql/parser.py`

---

### Task 4: Add Query Planner Support
**Status**: 🔲 Pending

**Objective**: Generate `GraphPlan` for new query types.

**New Plan Generation**:
- `_plan_cycles()` → GraphPlan with operation="find_cycles"
- Update `_plan_show()` to handle IMPACT/ANCESTORS
- Add edge_types parameter to GraphPlan from WHERE clause

**Files to Modify**:
- `src/mu/kernel/muql/planner.py`

---

### Task 5: Implement Executor with GraphManager
**Status**: 🔲 Pending

**Objective**: Execute graph queries using petgraph-backed GraphManager.

**New Executor Methods**:
- `_execute_find_cycles()` - calls `gm.find_cycles(edge_types)`
- `_execute_impact()` - calls `gm.impact(node_id, edge_types)`
- `_execute_ancestors()` - calls `gm.ancestors(node_id, edge_types)`
- Update `_execute_graph()` to handle new operations

**GraphManager Integration**:
```python
from mu.kernel.graph import GraphManager

def _execute_find_cycles(self, plan: GraphPlan) -> QueryResult:
    gm = GraphManager(self._db.conn)
    gm.load()
    cycles = gm.find_cycles(plan.edge_types or None)
    return self._cycles_to_result(cycles)
```

**Files to Modify**:
- `src/mu/kernel/muql/executor.py`

---

### Task 6: Export New Types
**Status**: 🔲 Pending

**Objective**: Export new AST types from module `__init__.py`.

**Files to Modify**:
- `src/mu/kernel/muql/__init__.py`

---

### Task 7: Add Unit Tests
**Status**: 🔲 Pending

**Objective**: Test new graph query parsing and execution.

**Test Cases**:
- Parse `FIND CYCLES` basic
- Parse `FIND CYCLES WHERE edge_type = 'imports'`
- Parse `SHOW IMPACT OF node`
- Parse `SHOW ANCESTORS OF node DEPTH 3`
- Parse edge type filters
- Execute cycles query against mock GraphManager
- Execute impact query
- Execute ancestors query

**Files to Create/Modify**:
- `tests/unit/test_muql_parser.py` (add new tests)
- `tests/unit/test_muql_executor.py` (add graph tests)

---

### Task 8: Quality Checks
**Status**: 🔲 Pending

**Objective**: Ensure code quality passes all checks.

**Commands**:
```bash
ruff check src/mu/kernel/muql/
ruff format src/mu/kernel/muql/
mypy src/mu/kernel/muql/
pytest tests/unit/test_muql_parser.py tests/unit/test_muql_executor.py -v
```

---

## Acceptance Criteria

- [ ] `mu q "FIND CYCLES"` returns circular import chains
- [ ] `mu q "SHOW IMPACT OF 'mod:src/auth.py'"` returns downstream nodes
- [ ] `mu q "SHOW ANCESTORS OF 'func:login'"` returns upstream dependencies
- [ ] `mu q "FIND PATH FROM 'mod:a.py' TO 'mod:z.py'"` returns shortest path
- [ ] Edge type filtering works in all graph queries
- [ ] All existing tests pass
- [ ] ruff check passes
- [ ] mypy passes
