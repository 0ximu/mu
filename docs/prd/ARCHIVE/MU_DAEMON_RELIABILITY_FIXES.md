# PRD: MU Daemon Reliability Fixes

**Version:** 1.0
**Date:** 2025-12-09
**Status:** Draft
**Author:** Engineering Team

---

## Executive Summary

This PRD addresses three critical reliability issues in the MU daemon that prevent core functionality from working correctly:

1. **mu_context returns 0 tokens** despite finding relevant nodes
2. **mu_impact/mu_ancestors return 0 nodes** despite valid node IDs
3. **Intermittent daemon connectivity errors** ("Server disconnected")

These issues block the primary use case of MU: providing intelligent code context to LLM assistants.

---

## Problem Statement

### Current State

Users report that MU tools find data but fail to render it:

```
mu context "How does VoidInvoiceAsync work?"
→ Found 15 nodes
→ Output: 0 tokens (empty mu_text)

mu impact "AuthService"
→ Returns: []

mu read "fn:/.../InvoiceService.cs:VoidInvoiceAsync"
→ Returns exact source code (WORKS!)
```

The graph database contains the correct data. The rendering/traversal layer fails silently.

### Impact

- **mu_context**: Primary feature for LLM context extraction is broken
- **mu_impact/mu_ancestors**: Dependency analysis unusable for change impact assessment
- **Connectivity**: Intermittent failures erode user trust and break automation

---

## Root Cause Analysis

### Issue 1: mu_context Returns Empty Output

**Location:** `mu-daemon/src/context/extractor.rs:209-256`

**Problem:** The `generate_mu_output` function skips MODULE nodes entirely:

```rust
match node.node_type {
    NodeType::Module => {
        // Already shown as file header  ← SKIPPED!
    }
    NodeType::Class => { ... }
    NodeType::Function => { ... }
}
```

When context extraction selects MODULE-type nodes (common for file-path queries), the output contains only headers with no content.

**Secondary Issue:** Python fallback in `src/mu/kernel/context/export.py:170`:

```python
if node.properties.get("is_method"):  # Crashes if properties is None
```

### Issue 2: Impact/Ancestors Return Empty Results

**Location:** `mu-daemon/src/muql/executor.rs:471-481`

**Problem:** The BFS traversal requires exact node ID match in in-memory graph:

```rust
fn traverse_bfs(start: &str, nodes: &[String], ...) -> Vec<String> {
    let node_set: HashSet<&str> = nodes.iter().map(|s| s.as_str()).collect();
    if !node_set.contains(start) {
        return vec![];  // ← Silent failure
    }
    // ...
}
```

**Failure modes:**
1. In-memory `GraphEngine` not synced after mubase updates
2. Node ID resolution not performed before traversal
3. No fallback to database query when in-memory lookup fails

### Issue 3: Intermittent Connectivity Errors

**Location:** `src/mu/client.py:23`

**Problem:** Default timeout is too aggressive:

```python
DEFAULT_TIMEOUT = 0.5  # 500ms
```

This causes spurious "Server disconnected" errors under normal load.

---

## Requirements

### Functional Requirements

#### FR-1: Context Rendering Must Output Content

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1.1 | MODULE nodes must contribute to output (imports, exports, docstring) | P0 |
| FR-1.2 | Empty node selection must return helpful message, not empty string | P0 |
| FR-1.3 | Python exporter must handle `None` properties without crashing | P0 |
| FR-1.4 | Context extraction must include CLASS/FUNCTION nodes, not just MODULEs | P1 |

#### FR-2: Graph Traversal Must Find Connected Nodes

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1 | Node ID must be resolved/normalized before traversal | P0 |
| FR-2.2 | Traversal must fall back to database query if in-memory fails | P0 |
| FR-2.3 | GraphEngine must auto-sync when mubase is updated | P1 |
| FR-2.4 | Traversal must return partial results with warning, not empty | P2 |

#### FR-3: Client Connectivity Must Be Reliable

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-3.1 | Default timeout must be >= 2 seconds | P0 |
| FR-3.2 | Health check failures must include retry with backoff | P1 |
| FR-3.3 | Connection errors must include actionable diagnostic info | P2 |

### Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-1 | Context extraction latency | < 500ms for 95th percentile |
| NFR-2 | Graph traversal latency | < 100ms for depth=2 |
| NFR-3 | Daemon availability | 99.9% when process is running |

---

## Technical Design

### Fix 1: Context Rendering (Rust)

**File:** `mu-daemon/src/context/extractor.rs`

**Change:** Modify `generate_mu_output` to render MODULE nodes with useful content:

```rust
// BEFORE
NodeType::Module => {
    // Already shown as file header
}

// AFTER
NodeType::Module => {
    // Include module-level info: imports, exports, docstring
    if let Some(props) = &node.properties {
        if let Some(imports) = props.get("imports") {
            output.push_str(&format!("  @ imports: {}\n", imports));
        }
        if let Some(docstring) = props.get("docstring") {
            let short_doc = truncate_docstring(docstring, 100);
            output.push_str(&format!("  :: {}\n", short_doc));
        }
    }
}
```

**Additional change:** Ensure context selection prioritizes CLASS/FUNCTION nodes over MODULE when relevant entities exist.

### Fix 2: Context Rendering (Python Fallback)

**File:** `src/mu/kernel/context/export.py`

**Change:** Add defensive checks for `None` properties throughout:

```python
# Line 170 - Method detection
if (node.properties or {}).get("is_method"):

# Line 220 - Class export
props = node.properties or {}

# Line 275 - Function export
props = node.properties or {}
```

**Files to update:**
- `export.py`: Lines 170, 220, 226, 247, 275, 281-286, 292, 311, 316

### Fix 3: Graph Traversal Node Resolution

**File:** `mu-daemon/src/muql/executor.rs`

**Change:** Add node resolution before traversal:

```rust
async fn execute_graph(op: GraphOperation, state: &AppState) -> Result<QueryResult> {
    // NEW: Resolve node ID first
    let resolved_target = resolve_node_id(&op.target, state).await?;

    match op.op_type {
        GraphOpType::Impact => {
            let graph = state.graph.read().await;
            let impacted = traverse_bfs(
                &resolved_target,  // Use resolved ID
                graph.get_nodes(),
                graph.get_edges(),
                Direction::Outgoing,
                op.edge_types.as_deref(),
            );
            // ...
        }
    }
}

/// Resolve a node name/path to its canonical ID
async fn resolve_node_id(input: &str, state: &AppState) -> Result<String> {
    // If already a valid node ID format, verify it exists
    if input.starts_with("mod:") || input.starts_with("cls:") || input.starts_with("fn:") {
        let mubase = state.mubase.read().await;
        if mubase.get_node(input)?.is_some() {
            return Ok(input.to_string());
        }
    }

    // Try to find by name
    let mubase = state.mubase.read().await;
    let sql = format!(
        "SELECT id FROM nodes WHERE name = '{}' OR qualified_name LIKE '%{}' LIMIT 1",
        input.replace('\'', "''"),
        input.replace('\'', "''")
    );

    if let Ok(result) = mubase.query(&sql) {
        if let Some(row) = result.rows.first() {
            if let Some(id) = row.first().and_then(|v| v.as_str()) {
                return Ok(id.to_string());
            }
        }
    }

    // Return original if resolution fails (let traversal handle it)
    Ok(input.to_string())
}
```

### Fix 4: Graph Engine Sync

**File:** `mu-daemon/src/build/pipeline.rs`

**Change:** Auto-refresh GraphEngine after build:

```rust
pub async fn build(&self, root: &Path) -> Result<BuildResult> {
    // ... existing build logic ...

    // Refresh in-memory graph after successful build
    let graph = self.state.mubase.read().await.load_graph()?;
    *self.state.graph.write().await = graph;

    Ok(result)
}
```

### Fix 5: Client Timeout

**File:** `src/mu/client.py`

**Change:** Increase default timeout:

```python
# BEFORE
DEFAULT_TIMEOUT = 0.5

# AFTER
DEFAULT_TIMEOUT = 2.0
```

---

## Implementation Plan

### Phase 1: Critical Fixes (P0)

| Task | File | Estimate | Owner |
|------|------|----------|-------|
| Fix Python properties None check | `export.py` | 1 hour | - |
| Fix client timeout | `client.py` | 15 min | - |
| Add node ID resolution | `executor.rs` | 2 hours | - |
| Fix MODULE node rendering | `extractor.rs` | 2 hours | - |

### Phase 2: Reliability Improvements (P1)

| Task | File | Estimate | Owner |
|------|------|----------|-------|
| Auto-sync GraphEngine after build | `pipeline.rs` | 1 hour | - |
| Add health check retry with backoff | `client.py` | 1 hour | - |
| Prioritize CLASS/FUNCTION in context | `extractor.rs` | 2 hours | - |

### Phase 3: Polish (P2)

| Task | File | Estimate | Owner |
|------|------|----------|-------|
| Add diagnostic info to connection errors | `client.py` | 1 hour | - |
| Return partial results with warnings | `executor.rs` | 2 hours | - |

---

## Testing Strategy

### Unit Tests

```python
# test_export.py
def test_export_handles_none_properties():
    """Ensure exporter doesn't crash on nodes with None properties."""
    node = Node(id="fn:test", type=NodeType.FUNCTION, name="test", properties=None)
    scored = ScoredNode(node=node, score=1.0)
    exporter = ContextExporter(mubase, include_scores=False)
    result = exporter.export_mu([scored])
    assert "test" in result  # Should render without crashing

def test_context_includes_function_nodes():
    """Context extraction should include function nodes, not just modules."""
    result = extractor.extract("How does authenticate work?")
    node_types = {n.type for n in result.nodes}
    assert NodeType.FUNCTION in node_types
```

```rust
// executor_test.rs
#[tokio::test]
async fn test_impact_resolves_node_name() {
    // Given a node name (not full ID)
    let result = execute("SHOW impact OF 'AuthService'", &state).await;

    // Should resolve to full ID and return results
    assert!(!result.rows.is_empty());
}

#[tokio::test]
async fn test_impact_with_stale_graph() {
    // Given an in-memory graph that's behind mubase
    // Impact should still work via fallback
}
```

### Integration Tests

```bash
# Test context rendering end-to-end
mu context "authentication" --format json | jq '.token_count'
# Expected: > 0

# Test impact with various input formats
mu impact "AuthService"
mu impact "cls:src/auth.py:AuthService"
mu impact "src/auth.py"
# All should return non-empty results if node exists
```

### Manual Verification

1. Start fresh daemon: `mu daemon start .`
2. Build graph: `mu kernel build .`
3. Test context: `mu context "How does X work?"` → Should return content
4. Test impact: `mu impact "SomeClass"` → Should return dependencies
5. Kill/restart daemon → Connection should recover within 2s

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| mu_context returns content | ~20% of queries | 95%+ |
| mu_impact returns results | ~10% of queries | 95%+ |
| Daemon connectivity success | ~80% | 99%+ |
| Context extraction P95 latency | Unknown | < 500ms |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Node resolution adds latency | Medium | Cache resolved IDs, use prepared statements |
| GraphEngine sync blocks builds | Low | Async refresh, timeout protection |
| Timeout increase masks real issues | Low | Add logging for slow responses |

---

## Appendix

### A. File Change Summary

| File | Changes |
|------|---------|
| `mu-daemon/src/context/extractor.rs` | Render MODULE nodes, prioritize CLASS/FUNCTION |
| `mu-daemon/src/muql/executor.rs` | Add `resolve_node_id()`, improve error handling |
| `mu-daemon/src/build/pipeline.rs` | Auto-sync GraphEngine after build |
| `src/mu/kernel/context/export.py` | Defensive `None` checks on properties |
| `src/mu/client.py` | Increase DEFAULT_TIMEOUT to 2.0s |

### B. Related Issues

- "mu context finds nodes but outputs 0 tokens"
- "Impact/Ancestors returns empty despite valid node"
- "Intermittent Server disconnected errors"

### C. References

- [MU Kernel CLAUDE.md](/src/mu/kernel/CLAUDE.md)
- [Context Module CLAUDE.md](/src/mu/kernel/context/CLAUDE.md)
- [MUQL Executor](/mu-daemon/src/muql/executor.rs)
