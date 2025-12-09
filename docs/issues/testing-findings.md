# MU Testing Findings - December 2024

## Summary

Tested MCP tools and CLI commands. Found several bugs and edge cases.

---

## Critical Bugs

### 1. `mu_read` MCP tool doesn't resolve node names like CLI does

**Severity**: High
**Location**: `src/mu/mcp/tools/graph.py`

The CLI command `mu read EmbeddingService` successfully finds and displays the node, but the MCP tool `mu_read("EmbeddingService")` fails with "Node not found".

**Reproduction**:
```python
# MCP - FAILS
mu_read(node_id="EmbeddingService")  # Error: Node not found

# CLI - WORKS
$ mu read EmbeddingService  # Shows code correctly
```

The CLI has name resolution logic in `_resolve_node_id_local()` that the MCP tool doesn't use properly.

---

### 2. `mu_read` returns wrong content for function nodes

**Severity**: High
**Location**: Line numbers in database may be stale

When reading `fn:/Users/imu/Dev/work/mu/src/mu/mcp/server.py:mu_query`, the returned source shows the `__all__` list (lines 198-251) instead of the actual `mu_query` function definition.

**Reproduction**:
```python
mu_read(node_id="fn:/Users/imu/Dev/work/mu/src/mu/mcp/server.py:mu_query")
# Returns __all__ list content, not the mu_query function
```

This suggests the line numbers stored in the database are incorrect or stale after the recent refactoring.

---

## Medium Bugs

### 3. Empty query error message is excessively verbose

**Severity**: Low
**Location**: `src/mu/kernel/muql/parser.py`

Empty MUQL query produces an extremely long error with repeated "SELECT_KW" ~65 times.

**Reproduction**:
```python
mu_query(query="")
# Returns verbose error with SELECT_KW repeated many times
```

---

### 4. `mu_deps` silently returns empty for nonexistent nodes

**Severity**: Medium
**Location**: `src/mu/mcp/tools/analysis.py`

Looking up dependencies for a nonexistent node returns an empty list instead of an error.

**Reproduction**:
```python
mu_deps(node_name="nonexistent_node_xyz")
# Returns: {"node_id": "nonexistent_node_xyz", "dependencies": []}
# Should probably return an error indicating node not found
```

---

### 5. `mu_context` returns empty for empty question

**Severity**: Low
**Location**: `src/mu/mcp/tools/context.py`

Passing an empty string should return an error or helpful message.

**Reproduction**:
```python
mu_context(question="")
# Returns: {"mu_text": "", "token_count": 0, "node_count": 0}
# Should return an error
```

---

## Cosmetic / UX Issues

### 6. OMEGA module paths include full absolute paths

**Severity**: Low
**Location**: `src/mu/kernel/context/omega.py`

The OMEGA output uses ugly module names like `.Users.imu.Dev.work.mu.src.mu.agent` instead of relative paths like `src.mu.agent`.

---

### 7. Daemon warning on every query

**Severity**: Low

Every CLI query shows:
```
Warning: Daemon query failed, falling back to local mode: Query error: Server
disconnected without sending a response.
```

This is expected if daemon isn't running, but the warning is verbose.

---

## Working Well

- `mu_status` - Returns correct status and next action
- `mu_bootstrap` - Already bootstrapped, works correctly
- `mu_query` - Basic queries work well with helpful error messages for invalid tables
- `mu_patterns` - Returns comprehensive pattern detection
- `mu_warn` - Returns appropriate warnings (tested with nonexistent file - graceful handling)
- `mu_semantic_diff` - Works with valid git refs, proper error for invalid refs
- `mu_review_diff` - Comprehensive review output
- `mu_context_omega` - Returns properly compressed S-expression output
- `mu_impact` - Returns correct impact analysis

---

## Additional Bugs Found (Session 2)

### 8. `FIND functions CALLING` not implemented

**Severity**: Medium
**Location**: `src/mu/kernel/muql/executor.py`

The MUQL query `FIND functions CALLING process_payment` returns an error:
```
Operation not implemented: find_calling for process_payment
```

This query type is documented but not implemented.

---

### 9. `ANALYZE complexity` returns unnamed columns

**Severity**: Low
**Location**: `src/mu/kernel/muql/executor.py`

The ANALYZE query returns columns named `col_0`, `col_1`, `col_2` instead of meaningful names like `id`, `name`, `complexity`.

---

### 10. `mu_impact` fails with relative node paths

**Severity**: Medium
**Location**: `src/mu/mcp/tools/analysis.py`

```python
# FAILS
mu_impact(node_id="mod:src/mu/kernel/muql/engine.py")
# Error: Node not found

# WORKS
mu_impact(node_id="mod:/Users/imu/Dev/work/mu/src/mu/kernel/muql/engine.py")
```

The MCP tool requires absolute paths while the CLI accepts relative paths.

---

### 11. `mu sus` CLI command fails with file paths

**Severity**: High
**Location**: `src/mu/commands/vibes.py:sus`

```bash
# FAILS
$ mu sus src/mu/kernel/muql/parser.py
# Error: Target not found

# FAILS even with absolute path
$ mu sus /Users/imu/Dev/work/mu/src/mu/kernel/muql/parser.py
# Error: is not in the subpath of '/Users/imu/Dev/work/mu/.mu'

# BUT mu warn WORKS
$ mu warn src/mu/kernel/muql/parser.py
# No warnings for src/mu/kernel/muql/parser.py
```

The `mu sus` command has broken path handling - it seems to look in `.mu/` directory instead of the source tree.

---

### 12. `mu_context_omega` returns empty seed

**Severity**: Medium
**Location**: `src/mu/kernel/context/omega.py` or `src/mu/mcp/tools/context.py`

When asking a question that returns no relevant context:
```python
mu_context_omega(question="How does authentication work?")
# Returns: {"seed": "", "body": ";; No relevant context found..."}
```

The seed should still contain macro definitions even when no context is found.

---

### 13. `mu omg` shows OMEGA expansion warning

**Severity**: Low
**Location**: `src/mu/commands/vibes.py:omg`

The command shows a warning that may confuse users:
```
WARNING  OMEGA expansion detected: 1042 tokens vs 432 original (ratio: 0.41).
         Body generation may be including extra content.
```

This appears when the schema seed is included, which is expected behavior.

---

### 14. `mu grok` shows 0 tokens

**Severity**: Low/Bug
**Location**: `src/mu/commands/vibes.py:grok`

```bash
$ mu grok "how does the parser work?"
Grokking... (55 nodes, 0 tokens)
```

Shows 0 tokens even though content was extracted. The token counting may be broken.

---

## Recommendations

1. **Priority 1**: Fix `mu_read` MCP tool to use same name resolution as CLI
2. **Priority 1**: Fix `mu sus` path handling - currently broken
3. **Priority 2**: Implement `FIND functions CALLING` MUQL operation
4. **Priority 2**: Fix `mu_impact` to accept relative paths
5. **Priority 3**: Rebuild mubase to fix stale line numbers
6. **Priority 3**: Fix ANALYZE query column names
7. **Priority 4**: Improve empty query error message
8. **Priority 4**: Make `mu_deps` return error for nonexistent nodes
9. **Priority 5**: Validate empty questions in `mu_context`
10. **Priority 5**: Fix `mu grok` token counting
