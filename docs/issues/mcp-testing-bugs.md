# MCP Testing Bug Report

Date: 2025-12-09
Branch: feature/omega-lisp-exporter

## Critical Bugs

### 1. Database Lock Error - Multiple MCP Tools Don't Route Through Daemon

**Severity**: Critical
**Affected Tools**: `mu_deps`, `mu_impact`, `mu_context_omega`, `mu_patterns`, `mu_warn`, `mu_read`

**Description**: When the daemon is running, several MCP tools fail with a DuckDB lock error because they try to access the `.mubase` file directly instead of routing through the daemon.

**Error Message**:
```
Database is locked by another process.
Original error: IO Error: Could not set lock on file ".mu/mubase":
Conflicting lock is held in mu-daemon/target/release/mu-daemon (PID 20657)
```

**Root Cause**:
- `mu_deps` (analysis.py:43-105): Always uses local `MUbase(mubase_path, read_only=True)`, never tries daemon
- `mu_impact` (analysis.py:128-159): Same issue - always local mode
- `mu_context_omega` (context.py:119-161): Never tries daemon, goes straight to local MUbase
- `mu_patterns` (guidance.py): Likely same pattern
- `mu_warn` (guidance.py): Likely same pattern
- `mu_read` (graph.py:206-232): Falls back to local mode but DuckDB can't share lock

**Expected Behavior**: All MCP tools should first try to communicate with the daemon via HTTP. Only fall back to direct DB access when daemon is not running.

**Fix Location**:
- `src/mu/mcp/tools/analysis.py` - mu_deps, mu_impact need daemon routing
- `src/mu/mcp/tools/context.py` - mu_context_omega needs daemon routing
- `src/mu/mcp/tools/guidance.py` - mu_patterns, mu_warn need daemon routing


### 2. MUQL `FIND functions CALLING X` Returns All Functions

**Severity**: High
**Affected**: MUQL parser/executor

**Description**: The query `FIND functions CALLING process_payment` returns ALL functions instead of filtering to those that call `process_payment`. The target function doesn't even exist in the codebase, yet it returns 100 results.

**Test Case**:
```sql
FIND functions CALLING process_payment
-- Returns 100 functions that have nothing to do with process_payment
```

**Expected**: Should return empty result or only functions that actually call `process_payment`.

**Fix Location**: `mu-daemon/src/muql/` (parser or executor)


### 3. MUQL Query Column Names are Generic

**Severity**: Medium
**Affected**: MUQL query results

**Description**: Query results return generic column names (`col_0`, `col_1`, etc.) instead of meaningful names.

**Test Case**:
```sql
SELECT * FROM functions LIMIT 5
-- Returns columns: ["col_0", "col_1", "col_2", "col_3", "col_4", "col_5", "col_6"]
-- Expected: ["id", "type", "name", "file_path", "line_start", "line_end", "complexity"]
```

**Fix Location**: Query result formatting in daemon or Python client


### 4. mu_context Returns Empty for Some Queries

**Severity**: Medium
**Affected**: `mu_context` tool

**Description**: Some valid questions return empty results when they should find relevant code.

**Test Case**:
```python
mu_context("How does authentication work?")
# Returns: {"mu_text": "", "token_count": 0, "node_count": 0}
```

But this works:
```python
mu_context("How does the parser work?")
# Returns valid results with 508 tokens
```

**Note**: This might be expected if there's no "authentication" code in MU codebase, but the behavior should be investigated.


## Medium Priority

### 5. Error Message Mismatch for Invalid MUQL

**Severity**: Low
**Affected**: MUQL error handling

**Description**: When executing invalid MUQL (like `SELECT * FROM nonexistent_table`), the error message shows "Database is locked" instead of "Table not found".

**Root Cause**: The error is being caught at the wrong level - the daemon lock error masks the actual MUQL parsing/execution error.


## Testing Status

| Tool | Daemon Mode | Local Mode | Status |
|------|-------------|------------|--------|
| mu_status | Working | N/A | OK |
| mu_bootstrap | Working | N/A | OK |
| mu_query | Working | Fails (lock) | Partial |
| mu_read | Working | Fails (lock) | Partial |
| mu_context | Working | Fails (lock) | Partial |
| mu_context_omega | Not implemented | Fails (lock) | BROKEN |
| mu_deps | Not implemented | Fails (lock) | BROKEN |
| mu_impact | Not implemented | Fails (lock) | BROKEN |
| mu_patterns | Not implemented | Fails (lock) | BROKEN |
| mu_warn | Not implemented | Fails (lock) | BROKEN |
| mu_semantic_diff | Working | N/A | OK |
| mu_review_diff | Working | N/A | OK |


## Recommendations

1. **Add daemon endpoints for missing tools**: The Rust daemon needs HTTP endpoints for:
   - `/deps` - dependency traversal
   - `/impact` - impact analysis
   - `/patterns` - pattern detection
   - `/warn` - proactive warnings
   - `/context/omega` - OMEGA compressed context

2. **Fix FIND CALLING query**: The MUQL executor needs to properly filter functions by what they call.

3. **Preserve column names**: Query results should include actual column names from the schema.

4. **Add integration tests**: Tests that run against a live daemon to catch these daemon-vs-local issues.
