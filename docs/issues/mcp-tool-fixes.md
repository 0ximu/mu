# MCP Tool Fixes - Task Breakdown

This document contains task specifications for fixing 7 identified issues in the MU MCP tools. Each task is self-contained with root cause analysis, affected files, and implementation guidance.

## Overview

| Task | Priority | Issue | Estimated Complexity |
|------|----------|-------|---------------------|
| T1 | High | mu_context_omega returns empty when mu_context finds results | Medium |
| T2 | High | Duplicate classes in OMEGA output body | Low |
| T3 | High | OMEGA compression ratio shows expansion (inverted) | Medium |
| T4 | Medium | mu_deps returns empty for all nodes | Medium |
| T5 | Medium | mu_read doesn't resolve simple class/function names | Low |
| T6 | Low | MUQL silently returns empty for invalid queries | Low |
| T7 | Low | mu_warn test coverage detection misses integration tests | Low |

---

## T1: Fix mu_context_omega Empty Results

### Problem Statement

For the same question "How does the OMEGA compression work?":
- `mu_context` returns 53 nodes / 538 tokens
- `mu_context_omega` returns "No relevant context found" with 0 nodes

### Root Cause

`OmegaContextExtractor` reduces the token budget by 15% for the header, which can cause the underlying `SmartContextExtractor` to find fewer or no nodes:

```python
# omega.py:415-417
body_budget = int(self.config.max_tokens * (1 - self.config.header_budget_ratio))
extraction_config = ExtractionConfig(max_tokens=body_budget)
self.smart_extractor = SmartContextExtractor(mubase, extraction_config)
```

Additionally, when `context_result.nodes` is empty, OMEGA returns early with no fallback:

```python
# omega.py:472-481
if not context_result.nodes:
    return OmegaResult(
        seed="",
        body=f";; No relevant context found for: {question}",
        ...
    )
```

### Files to Modify

- `src/mu/kernel/context/omega.py`

### Implementation

1. **Don't reduce budget for initial extraction** - Use full budget for SmartContextExtractor, then trim output if needed:

```python
# In __init__, use full budget initially
extraction_config = ExtractionConfig(max_tokens=self.config.max_tokens)
self.smart_extractor = SmartContextExtractor(mubase, extraction_config)
```

2. **Add fallback when OMEGA finds fewer nodes** - If the body exceeds budget after generation, truncate nodes rather than finding none:

```python
# In extract(), after getting context_result
if not context_result.nodes:
    # Try with relaxed config (no vector search requirement)
    fallback_config = ExtractionConfig(
        max_tokens=self.config.max_tokens,
        min_relevance=0.05,  # Lower threshold
    )
    fallback_extractor = SmartContextExtractor(self.mubase, fallback_config)
    context_result = fallback_extractor.extract(question)
```

3. **Log debug info** when no nodes found to aid troubleshooting:

```python
if not context_result.nodes:
    logger.debug(f"No nodes found for question: {question}")
    logger.debug(f"Extraction stats: {context_result.extraction_stats}")
```

### Acceptance Criteria

- [ ] `mu_context_omega("How does OMEGA compression work?")` returns non-empty results
- [ ] Results are comparable to `mu_context` for the same question
- [ ] No regression in existing OMEGA tests

---

## T2: Fix Duplicate Classes in OMEGA Output

### Problem Statement

Classes like `MUAgent`, `QueryExecutor`, `SemanticDiffer` appear TWICE in the OMEGA output body.

### Root Cause

In `_generate_body`, the code processes class nodes and then calls `get_children()` to fetch methods. But if those methods are already in the input `nodes` list, they get output twice:

```python
# omega.py:731-735
classes = [n for n in module_nodes if n.type == NodeType.CLASS]
# ...
# omega.py:774-775
children = self.mubase.get_children(node.id)
methods = [c for c in children if c.type == NodeType.FUNCTION]
```

### Files to Modify

- `src/mu/kernel/context/omega.py`

### Implementation

1. **Track output node IDs** to prevent duplicates:

```python
def _generate_body(
    self,
    nodes: list[Node],
    node_macro_map: dict[str, MacroDefinition],
) -> str:
    # Track which nodes we've already output
    output_node_ids: set[str] = set()

    # ... existing grouping code ...

    for module_path, module_nodes in sorted(by_module.items()):
        # Filter out already-output nodes
        module_nodes = [n for n in module_nodes if n.id not in output_node_ids]

        # Mark nodes as output
        for n in module_nodes:
            output_node_ids.add(n.id)

        # ... rest of processing ...
```

2. **Don't re-fetch methods if already in nodes list**:

```python
def _class_to_schema_v2(self, node: Node, existing_node_ids: set[str]) -> str:
    # Get methods, but only those not already in the context
    children = self.mubase.get_children(node.id)
    methods = [
        c for c in children
        if c.type == NodeType.FUNCTION and c.id not in existing_node_ids
    ]
```

### Acceptance Criteria

- [ ] Each class/function appears exactly once in OMEGA output
- [ ] Methods are still included under their parent classes
- [ ] No loss of information (all relevant nodes still output)

---

## T3: Fix OMEGA Compression Ratio (Expansion Issue)

### Problem Statement

`compression_ratio: 0.077` with `body_tokens: 9025` vs `original_tokens: 732` means OMEGA uses ~12x MORE tokens, not fewer.

### Root Cause

The compression ratio calculation is correct (`original/total`), but the body generation expands content by:

1. Calling `get_children()` to fetch ALL methods of a class, not just those in context
2. Including verbose file paths in module declarations
3. Adding schema overhead

```python
# omega.py:774-775 - Fetches ALL children, not just context nodes
children = self.mubase.get_children(node.id)
methods = [c for c in children if c.type == NodeType.FUNCTION]
```

### Files to Modify

- `src/mu/kernel/context/omega.py`

### Implementation

1. **Only output nodes that were in the original context**:

```python
def _generate_body(
    self,
    nodes: list[Node],
    node_macro_map: dict[str, MacroDefinition],
) -> str:
    # Create set of node IDs that should be in output
    context_node_ids = {n.id for n in nodes}

    # ... in _class_to_schema_v2 ...
    # Only include methods that are in the context
    children = self.mubase.get_children(node.id)
    methods = [
        c for c in children
        if c.type == NodeType.FUNCTION and c.id in context_node_ids
    ]
```

2. **Update method signatures** to pass context node IDs:

```python
def _class_to_schema_v2(self, node: Node, context_node_ids: set[str]) -> str:
def _service_to_schema_v2(self, name: str, deps: list[str], methods: list[Node]) -> str:
def _plain_class_to_schema_v2(self, name: str, parent: str, attrs: list[str], methods: list[Node]) -> str:
```

3. **Add a sanity check** for compression:

```python
# After calculating compression_ratio
if compression_ratio < 1.0:
    logger.warning(
        f"OMEGA expansion detected: {total_tokens} tokens vs {original_tokens} original "
        f"(ratio: {compression_ratio:.2f}). Consider reviewing body generation."
    )
```

### Acceptance Criteria

- [ ] `compression_ratio > 1.0` for typical queries (actual compression)
- [ ] Body token count is similar to or less than original_tokens
- [ ] Warning logged if expansion occurs

---

## T4: Fix mu_deps Returning Empty

### Problem Statement

`mu_deps("SmartContextExtractor")` returns empty dependencies, but `mu_impact("mod:src/mu/kernel/context/smart.py")` returns 18 impacted nodes.

### Root Cause

`mu_deps` uses MUQL `SHOW dependencies` which calls `MUbase.get_dependencies()`:

```python
# executor.py:190-192
elif operation == "get_dependencies":
    nodes = self._db.get_dependencies(target, depth=depth)
```

This only follows IMPORTS edges. But `mu_impact` uses `GraphManager.impact()` which does BFS traversal across all edge types.

### Files to Modify

- `src/mu/mcp/tools/analysis.py`
- `src/mu/kernel/muql/executor.py`

### Implementation

**Option A: Use GraphManager for deps too** (Recommended)

```python
# analysis.py - In mu_deps fallback section
from mu.kernel.graph import GraphManager

db = MUbase(mubase_path)
try:
    gm = GraphManager(db.conn)
    gm.load()

    resolved_id = resolve_node_id(db, node_name, root_path)

    if direction == "outgoing":
        # Get what this node depends on (ancestors)
        dep_ids = gm.ancestors(resolved_id)
    elif direction == "incoming":
        # Get what depends on this node (impact)
        dep_ids = gm.impact(resolved_id)
    else:
        # Both directions
        dep_ids = list(set(gm.ancestors(resolved_id)) | set(gm.impact(resolved_id)))

    # Convert IDs to NodeInfo
    deps = []
    for dep_id in dep_ids[:100]:  # Limit results
        node = db.get_node(dep_id)
        if node:
            deps.append(NodeInfo(...))
```

**Option B: Fix the SQL query to include more edge types**

```python
# mubase.py - In get_dependencies
def get_dependencies(self, node_id: str, depth: int = 1, edge_types: list[EdgeType] | None = None):
    if edge_types is None:
        edge_types = [EdgeType.IMPORTS, EdgeType.CONTAINS, EdgeType.INHERITS]
```

### Acceptance Criteria

- [ ] `mu_deps("SmartContextExtractor")` returns non-empty results
- [ ] Results are consistent with `mu_impact` (related nodes appear)
- [ ] Direction parameter works correctly (outgoing/incoming/both)

---

## T5: Fix mu_read Simple Name Resolution

### Problem Statement

`mu_read("SmartContextExtractor")` fails with "Node not found", but `mu_query("SELECT * FROM classes WHERE name = 'SmartContextExtractor'")` finds it.

### Root Cause

`resolve_node_id` in `_utils.py` tries `find_by_name()` but returns the original string if no match:

```python
# _utils.py:51-53
nodes = db.find_by_name(node_ref)
if nodes:
    return str(nodes[0].id)

# ... eventually falls through to ...
# _utils.py:105
return node_ref  # Returns "SmartContextExtractor" unchanged
```

Then `db.get_node("SmartContextExtractor")` fails because the actual ID is `cls:src/mu/kernel/context/smart.py:SmartContextExtractor`.

### Files to Modify

- `src/mu/mcp/tools/_utils.py`

### Implementation

1. **Add case-insensitive name matching**:

```python
def resolve_node_id(db: Any, node_ref: str, root_path: Path | None = None) -> str:
    # ... existing full ID check ...

    # Try exact name match (case-sensitive)
    nodes = db.find_by_name(node_ref)
    if nodes:
        return str(nodes[0].id)

    # Try case-insensitive match via SQL
    result = db.execute(
        "SELECT id FROM nodes WHERE LOWER(name) = LOWER(?) LIMIT 1",
        [node_ref]
    )
    if result:
        return str(result[0][0])

    # ... rest of existing logic ...
```

2. **Add qualified name matching**:

```python
    # Try matching qualified_name
    result = db.execute(
        "SELECT id FROM nodes WHERE qualified_name LIKE ? LIMIT 1",
        [f"%{node_ref}"]
    )
    if result:
        return str(result[0][0])
```

3. **Improve error message** when resolution fails:

```python
# In mu_read, after resolve_node_id
if resolved_id == node_id:  # Resolution didn't change it
    # Provide helpful suggestions
    suggestions = db.execute(
        "SELECT name FROM nodes WHERE name LIKE ? LIMIT 5",
        [f"%{node_id}%"]
    )
    if suggestions:
        suggestion_names = [s[0] for s in suggestions]
        raise ValueError(
            f"Node not found: {node_id}. "
            f"Did you mean: {', '.join(suggestion_names)}?"
        )
```

### Acceptance Criteria

- [ ] `mu_read("SmartContextExtractor")` returns source code
- [ ] `mu_read("smartcontextextractor")` also works (case-insensitive)
- [ ] Helpful error message with suggestions when node not found

---

## T6: Fix MUQL Silent Error Handling

### Problem Statement

- `SELECT * FROM nonexistent_table` returns empty result (should error)
- `INVALID QUERY SYNTAX` returns empty result (should error)

### Root Cause

The MUQL engine captures errors correctly, but the MCP `QueryResult` model doesn't include the `error` field:

```python
# executor.py:40-47 - Error IS in the dict
def to_dict(self) -> dict[str, Any]:
    return {
        "columns": self.columns,
        "rows": [list(row) for row in self.rows],
        "row_count": self.row_count,
        "error": self.error,  # <-- Error included here
        "execution_time_ms": self.execution_time_ms,
    }

# graph.py:59-64 - But MCP QueryResult doesn't have error field
return QueryResult(
    columns=result.get("columns", []),
    rows=result.get("rows", []),
    row_count=result.get("row_count", ...),
    execution_time_ms=result.get("execution_time_ms"),
    # error field missing!
)
```

### Files to Modify

- `src/mu/mcp/models/common.py`
- `src/mu/mcp/tools/graph.py`

### Implementation

1. **Add error field to MCP QueryResult**:

```python
# models/common.py
@dataclass
class QueryResult:
    """Result of a MUQL query."""
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: float | None = None
    error: str | None = None  # Add this field
```

2. **Pass error through in mu_query**:

```python
# graph.py:59-67
return QueryResult(
    columns=result.get("columns", []),
    rows=result.get("rows", []),
    row_count=result.get("row_count", len(result.get("rows", []))),
    execution_time_ms=result.get("execution_time_ms"),
    error=result.get("error"),  # Add this
)
```

3. **Raise on error for MCP tool** (optional, depends on desired behavior):

```python
# If you want MCP to raise errors instead of returning them:
if result.get("error"):
    raise ValueError(result["error"])
```

### Acceptance Criteria

- [ ] `mu_query("INVALID SYNTAX")` returns result with `error` field populated
- [ ] `mu_query("SELECT * FROM nonexistent")` returns error about invalid table
- [ ] Valid queries still work normally with `error: None`

---

## T7: Improve mu_warn Test Coverage Detection

### Problem Statement

`mu_warn` says "No test file found" for `src/mu/mcp/server.py` but tests exist in `tests/unit/test_mcp.py`.

### Root Cause

Test detection uses file-naming patterns that only look for adjacent test files:

```python
# warnings.py:504-519
patterns.extend([
    parent / f"test_{stem}{suffix}",           # src/mu/mcp/test_server.py
    parent / f"{stem}_test{suffix}",           # src/mu/mcp/server_test.py
    parent / "tests" / f"test_{stem}{suffix}", # src/mu/mcp/tests/test_server.py
    ...
])
```

It doesn't check the top-level `tests/` directory where integration tests live.

### Files to Modify

- `src/mu/intelligence/warnings.py`

### Implementation

1. **Add project-level test directory patterns**:

```python
def _check_tests(self, file_path: Path, nodes: list[Any]) -> list[ProactiveWarning]:
    # ... existing patterns ...

    # Add project-level test directories
    # Find project root (where tests/ directory lives)
    project_root = self._find_project_root(file_path)
    if project_root:
        tests_dir = project_root / "tests"
        if tests_dir.exists():
            # Check for test files that might test this module
            module_name = stem.lower()

            # Common patterns in tests/ directory
            for test_subdir in ["", "unit", "integration"]:
                test_base = tests_dir / test_subdir if test_subdir else tests_dir
                if test_base.exists():
                    patterns.extend([
                        test_base / f"test_{module_name}.py",
                        test_base / f"test_{module_name}s.py",  # plural
                        # Also check for module path in test name
                        # e.g., tests/unit/test_mcp.py for src/mu/mcp/server.py
                    ])
```

2. **Add import-based detection** (more thorough):

```python
def _check_test_imports(self, file_path: Path, nodes: list[Any]) -> bool:
    """Check if any test file imports this module."""
    project_root = self._find_project_root(file_path)
    if not project_root:
        return False

    tests_dir = project_root / "tests"
    if not tests_dir.exists():
        return False

    # Get the module import path
    try:
        rel_path = file_path.relative_to(project_root / "src")
        import_path = str(rel_path.with_suffix("")).replace("/", ".")
    except ValueError:
        return False

    # Search for imports in test files
    for test_file in tests_dir.rglob("test_*.py"):
        try:
            content = test_file.read_text(errors="ignore")
            if import_path in content or file_path.stem in content:
                return True
        except Exception:
            pass

    return False
```

3. **Add helper to find project root**:

```python
def _find_project_root(self, file_path: Path) -> Path | None:
    """Find project root by looking for pyproject.toml, setup.py, or .git."""
    current = file_path.parent
    for _ in range(10):  # Max 10 levels up
        if (current / "pyproject.toml").exists():
            return current
        if (current / "setup.py").exists():
            return current
        if (current / ".git").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None
```

### Acceptance Criteria

- [ ] `mu_warn("src/mu/mcp/server.py")` finds tests in `tests/unit/test_mcp.py`
- [ ] Detection works for both `tests/unit/` and `tests/integration/`
- [ ] No false positives (unrelated test files not matched)

---

## Testing Strategy

After implementing fixes, run:

```bash
# Unit tests
uv run pytest tests/unit/test_mcp.py -v
uv run pytest tests/unit/test_context.py -v
uv run pytest tests/unit/test_muql*.py -v

# Integration tests
uv run pytest tests/integration/ -v -k "mcp or context or omega"

# Manual verification
uv run mu mcp serve &
# Then test each tool via Claude Code or direct MCP calls
```

## Dependencies Between Tasks

```
T1 (omega empty) ─┬─→ T3 (compression ratio)
                  │
T2 (duplicates) ──┘

T4 (deps empty) ──→ Independent

T5 (read names) ──→ Independent

T6 (muql errors) ─→ Independent

T7 (test detect) ─→ Independent
```

T1, T2, and T3 are related and should be done together. The others are independent.
