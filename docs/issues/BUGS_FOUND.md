# MU Bugs and Issues Found During Testing

Date: 2025-12-09
Branch: feature/omega-lisp-exporter

## Critical Issues

### Issue 15: Rust daemon panics on /status endpoint
**Severity**: CRITICAL
**Location**: `mu-daemon/src/storage/mubase.rs:308`

The Rust daemon panics when handling HTTP requests with:
```
thread 'tokio-runtime-worker' panicked at duckdb: The statement was not executed yet
thread 'tokio-runtime-worker' panicked at src/storage/mubase.rs:308:37:
called `Result::unwrap()` on an `Err` value: PoisonError { .. }
```

**Root Cause**: In `mubase.rs` line 322-323, the code calls `column_name()` on a statement that hasn't been fully executed. DuckDB requires statement execution before column name access.

**Impact**: Daemon crashes on any query, making all MCP tools non-functional.

### Issue 14: Database path mismatch between Rust daemon and Python tools
**Severity**: HIGH - **FIXED**
**Location**: Rust daemon vs Python CLI

- Rust daemon looks for: `.mubase`
- Python CLI creates: `.mu/mubase`

This causes the daemon to use an old/empty database while Python tools work with the correct one.

**Impact**: Data inconsistency, queries return stale or missing results.

**Fix**: Updated `mu-daemon/src/main.rs` to:
1. Default to `.mu/mubase` (matching Python CLI)
2. Fall back to legacy `.mubase` if it exists (backward compatibility)
3. Log a message suggesting `mu migrate` when using legacy path
4. Automatically create `.mu/` directory if needed

---

## MUQL Query Issues

### Issue 1: SELECT * returns columns named col_0, col_1, etc.
**Severity**: MEDIUM - **FIXED**
**Location**: MUQL query results

When running `SELECT * FROM functions`, columns are returned as `col_0`, `col_1`, etc. instead of proper names like `id`, `type`, `name`, `file_path`.

**Expected**: `{"columns":["id","type","name","file_path",...], ...}`
**Actual**: `{"columns":["col_0","col_1","col_2",...], ...}`

**Root Cause**: In `mu-daemon/src/storage/mubase.rs`, the `query()` method tried to call `stmt.column_name()` before executing the query. In duckdb-rs, column names are only available after executing the query and can be accessed from the `Row` object via `row.as_ref().column_names()`.

**Fix**: Updated the `query()` method to:
1. Execute the query first with `stmt.query([])`
2. Extract column names from the first row using `row.as_ref().column_names()`
3. Handle empty result sets gracefully (columns will be empty)

### Issue 3: FIND...CALLING query returns all functions regardless of filter
**Severity**: HIGH
**Location**: MUQL FIND parser/executor

Running `FIND functions CALLING authenticate` returns 100 unrelated functions instead of filtering to only those that call `authenticate`.

### Issue 4: SHOW dependencies query returns empty results
**Severity**: HIGH
**Location**: MUQL SHOW parser/executor

`SHOW dependencies OF EmbeddingService DEPTH 2` returns empty despite the class existing with dependencies.

---

## MCP Tool Issues

### Issue 5: mu_deps returns empty dependencies
**Severity**: MEDIUM
**Location**: `src/mu/mcp/tools/analysis.py:mu_deps`

`mu_deps("EmbeddingService", depth=2, direction="both")` returns `{"dependencies":[]}` even though the class has dependencies.

### Issue 6: mu_read with invalid node shows misleading database lock error
**Severity**: LOW
**Location**: `src/mu/mcp/tools/graph.py:mu_read`

When calling `mu_read("nonexistent_node")`, it returns a "Database is locked" error instead of "Node not found".

### Issue 7: mu_context_omega fails with database lock
**Severity**: HIGH
**Location**: `src/mu/mcp/tools/context.py:mu_context_omega`

`mu_context_omega` doesn't route through the daemon like `mu_context` does. It attempts direct database access and fails when daemon is running.

**Working**: `mu_context("How does authentication work?")`
**Broken**: `mu_context_omega("How does authentication work?")`

### Issue 9: mu_warn fails with database lock
**Severity**: HIGH
**Location**: `src/mu/mcp/tools/guidance.py:mu_warn`

Same issue as Issue 7 - doesn't route through daemon.

### Issue 10: mu_impact silently returns empty for non-existent nodes
**Severity**: LOW
**Location**: `src/mu/mcp/tools/analysis.py:mu_impact`

`mu_impact("nonexistent_module")` returns `{"impacted_nodes":[], "count":0}` instead of an error.

### Issue 11: mu_patterns fails with database lock
**Severity**: HIGH
**Location**: `src/mu/mcp/tools/guidance.py:mu_patterns`

Same issue as Issues 7, 9 - doesn't route through daemon.

---

## CLI Issues

### Issue 12: mu query shows wrong row count
**Severity**: LOW
**Location**: CLI output formatting

Running `mu query "SELECT name FROM classes LIMIT 3"` shows:
```
-----------------
0 rows (0.00ms)
```
Even though 3 rows were returned and displayed.

### Issue 13: mu kernel context doesn't forward to daemon
**Severity**: MEDIUM
**Location**: `src/mu/commands/kernel/context.py`

CLI commands like `mu kernel context "question"` fail with database lock instead of forwarding requests to the running daemon.

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| CRITICAL | 1     | 0     |
| HIGH     | 6     | 1     |
| MEDIUM   | 3     | 1     |
| LOW      | 3     | 0     |

### Blocking Issues (Must fix before release)
1. Issue 15: Rust daemon crashes on queries
2. ~~Issue 14: Database path mismatch~~ - **FIXED**

### High Priority
3. Issues 7, 9, 11: MCP tools not routing through daemon
4. Issues 3, 4: MUQL FIND/SHOW queries broken

### Medium Priority
5. ~~Issue 1: Column names in SELECT *~~ - **FIXED**
6. Issue 5: mu_deps empty results
7. Issue 13: CLI daemon forwarding

### Low Priority
8. Issues 6, 10, 12: Error messages and display formatting
