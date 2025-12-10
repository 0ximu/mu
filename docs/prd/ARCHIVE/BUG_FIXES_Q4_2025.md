# PRD: MU Bug Fixes - Q4 2025

**Version:** 1.0
**Date:** 2025-12-08
**Author:** Claude (Opus 4.5)
**Status:** Draft

## Executive Summary

Comprehensive testing of MU on its own codebase revealed 17 bugs and issues ranging from critical (data integrity) to minor (UX improvements). This PRD documents all findings and provides prioritized remediation tasks.

## Background

MU (Machine Understanding) is a semantic compression tool with MCP integration for AI assistants. During a comprehensive self-test session, we ran MU against its own codebase testing:
- MCP server tools
- CLI commands
- Kernel operations
- Daemon mode
- MUQL queries
- Edge cases and error handling

## Bug Inventory

### Critical Priority (P0)

#### BUG-001: Orphan Daemon Process Causes Data Leakage

**Severity:** Critical
**Component:** `src/mu/daemon/`
**Impact:** Queries return data from wrong project

**Description:**
When a daemon is started in directory A, then the user switches to directory B and runs commands, all queries are routed to the daemon in directory A - returning completely wrong data. The `mu daemon stop` command fails to find the orphan because it looks for PID file only in the current directory.

**Steps to Reproduce:**
```bash
cd /project-a
mu daemon start .
cd /project-b
mu kernel build .
mu query "SELECT * FROM functions"  # Returns project-a data!
mu daemon stop  # Says "Daemon not running"
```

**Root Cause:**
- Daemon binds to fixed port 8765 regardless of project
- PID file stored in project-local `.mu/daemon.pid`
- No global daemon registry or port-per-project mechanism

**Proposed Fix:**
1. Option A: Use port-per-project based on hash of project path
2. Option B: Implement global daemon registry in `~/.mu/daemons.json`
3. Option C: Add `--port` flag and project validation in daemon responses

**Files to Modify:**
- `src/mu/daemon/lifecycle.py`
- `src/mu/daemon/server.py`
- `src/mu/daemon/config.py`

---

#### BUG-002: MCP Tools Fail with Database Lock When Daemon Running

**Severity:** Critical
**Component:** `src/mu/mcp/server.py`
**Impact:** Major MCP functionality broken in daemon mode

**Description:**
Multiple MCP tools fail with "Database is locked" error when the daemon is running, instead of routing through the daemon like `mu_query` and `mu_context` do.

**Affected Tools:**
- `mu_remember`
- `mu_recall`
- `mu_task_context`
- `mu_warn`
- `mu_related`
- `mu_why`

**Working Tools (for reference):**
- `mu_query` - routes through daemon
- `mu_context` - routes through daemon
- `mu_deps` - routes through daemon

**Root Cause:**
These newer MCP tools were added without implementing daemon routing logic.

**Proposed Fix:**
Add daemon routing to all MCP tools that access the database. Pattern to follow from `mu_query`:
```python
def mu_tool():
    if _is_daemon_running():
        return _query_via_daemon(...)
    else:
        return _query_direct(...)
```

**Files to Modify:**
- `src/mu/mcp/server.py` (functions: `mu_remember`, `mu_recall`, `mu_task_context`, `mu_warn`, `mu_related`, `mu_why`)

---

### High Priority (P1)

#### BUG-003: Semantic Diff Shows Temp Directory Paths

**Severity:** High
**Component:** `src/mu/diff/`
**Impact:** Confusing output, hard to identify actual files

**Description:**
`mu diff` output shows absolute temporary directory paths instead of relative project paths:
```
+ /var/folders/dp/.../worktree-f0c3d52e/benches/__init__.py
```
Should show:
```
+ benches/__init__.py
```

**Root Cause:**
The diff formatter doesn't strip the worktree prefix from paths.

**Proposed Fix:**
Strip worktree path prefix in `format_diff` and `format_diff_markdown` functions.

**Files to Modify:**
- `src/mu/diff/formatters.py`

---

#### BUG-004: MUQL FIND CALLING Doesn't Support LIMIT

**Severity:** High
**Component:** `mu-core/src/muql/parser.rs`
**Impact:** Can't limit results of FIND queries

**Description:**
```sql
FIND functions CALLING build LIMIT 5
```
Fails with: `Error: Unexpected character 'L' at position 30`

**Root Cause:**
The MUQL grammar doesn't include LIMIT clause for FIND queries.

**Proposed Fix:**
Update MUQL grammar to support LIMIT on FIND queries.

**Files to Modify:**
- `mu-core/src/muql/parser.rs`
- `mu-core/src/muql/grammar.pest` (if exists)

---

#### BUG-005: Invalid Table Query Returns Empty Instead of Error

**Severity:** High
**Component:** `src/mu/kernel/muql/`
**Impact:** Silent failures, hard to debug queries

**Description:**
```sql
SELECT * FROM nonexistent_table
```
Returns: `{"rows":[], "row_count":0}` instead of an error.

**Root Cause:**
The MUQL parser/executor doesn't validate table names against known tables (functions, classes, modules, nodes).

**Proposed Fix:**
Add table name validation before query execution. Return error for unknown tables.

**Files to Modify:**
- `src/mu/kernel/muql/engine.py` or `mu-core/src/muql/executor.rs`

---

### Medium Priority (P2)

#### BUG-006: mu_why Returns "Target Not Found" for Valid Files

**Severity:** Medium
**Component:** `src/mu/mcp/server.py`
**Impact:** Feature doesn't work as expected

**Description:**
```python
mu_why("src/mu/mcp/server.py")
# Returns: "Target not found: src/mu/mcp/server.py"
```
File definitely exists.

**Root Cause:**
The `mu_why` function expects a different path format (possibly node ID or absolute path).

**Proposed Fix:**
- Accept relative paths and resolve to absolute
- Accept node names and resolve to file paths
- Improve error message to suggest correct format

**Files to Modify:**
- `src/mu/mcp/server.py` (function: `mu_why`)
- `src/mu/intelligence/why.py`

---

#### BUG-007: mu_related Reports Existing Files as Non-Existent

**Severity:** Medium
**Component:** `src/mu/intelligence/related.py`
**Impact:** Incorrect suggestions

**Description:**
```python
mu_related("src/mu/mcp/server.py")
# Returns: {"path": "src/mu/__init__.py", "exists": false, ...}
```
But `src/mu/__init__.py` definitely exists (407 bytes).

**Root Cause:**
The file existence check uses wrong path resolution (possibly relative vs absolute).

**Proposed Fix:**
Fix path resolution in `_check_file_exists` or similar function.

**Files to Modify:**
- `src/mu/intelligence/related.py`

---

#### BUG-008: Test Failure Due to Error Message Change

**Severity:** Medium
**Component:** `tests/unit/test_mcp.py`
**Impact:** CI failure

**Description:**
Test `test_query_fallback_to_direct` fails because error message changed:
- Expected: `"No .mubase found"`
- Actual: `"No .mu/mubase found"`

**Root Cause:**
Error message was updated for new `.mu/` directory structure but test wasn't.

**Proposed Fix:**
Update test regex to match new message.

**Files to Modify:**
- `tests/unit/test_mcp.py` (line ~130)

---

#### BUG-009: Semantic Diff Over-Counting Changes

**Severity:** Medium
**Component:** `src/mu/diff/`
**Impact:** Misleading diff statistics

**Description:**
Diff between commits shows `+314 -314 Modules` when actual changes are much smaller. Appears to treat all files as new rather than finding actual diffs.

**Root Cause:**
Likely comparing by path which includes temp directory prefix, so nothing matches.

**Proposed Fix:**
Normalize paths before comparison (related to BUG-003).

**Files to Modify:**
- `src/mu/diff/differ.py`

---

### Low Priority (P3)

#### BUG-010: Weird `:memory:` Directory Created

**Severity:** Low
**Component:** `src/mu/kernel/mubase.py`
**Impact:** Filesystem clutter

**Description:**
A literal directory `:memory:/.mu/mubase` was created in the project. This appears to be a bug when using DuckDB's `:memory:` path.

**Root Cause:**
Path handling doesn't check for special `:memory:` case before creating directories.

**Proposed Fix:**
Add guard in `MUbase.__init__` to not create directories for `:memory:` paths.

**Files to Modify:**
- `src/mu/kernel/mubase.py`

**Cleanup Required:**
```bash
rm -rf ":memory:"
```

---

#### BUG-011: Misleading Error for Empty Question

**Severity:** Low
**Component:** `src/mu/commands/kernel/context.py`
**Impact:** Confusing UX

**Description:**
```bash
mu kernel context ""
# Shows: "Database is locked by another process"
```
Should show: "Question cannot be empty"

**Root Cause:**
Validation happens after database access attempt.

**Proposed Fix:**
Add input validation before database operations.

**Files to Modify:**
- `src/mu/commands/kernel/context.py`

---

## Implementation Plan

### Phase 1: Critical Fixes (Week 1)

| Task | Bug | Effort | Owner |
|------|-----|--------|-------|
| Implement daemon routing for all MCP tools | BUG-002 | 4h | - |
| Add daemon discovery/registry mechanism | BUG-001 | 8h | - |
| Fix test regex | BUG-008 | 15m | - |

### Phase 2: High Priority (Week 2)

| Task | Bug | Effort | Owner |
|------|-----|--------|-------|
| Strip worktree paths in diff formatter | BUG-003 | 2h | - |
| Add LIMIT support to FIND queries | BUG-004 | 4h | - |
| Add table name validation to MUQL | BUG-005 | 2h | - |

### Phase 3: Medium Priority (Week 3)

| Task | Bug | Effort | Owner |
|------|-----|--------|-------|
| Fix mu_why path resolution | BUG-006 | 2h | - |
| Fix mu_related file existence check | BUG-007 | 1h | - |
| Fix semantic diff path normalization | BUG-009 | 2h | - |

### Phase 4: Low Priority (Week 4)

| Task | Bug | Effort | Owner |
|------|-----|--------|-------|
| Guard against :memory: directory creation | BUG-010 | 30m | - |
| Add empty question validation | BUG-011 | 30m | - |

## Testing Requirements

### Regression Tests to Add

1. **Daemon isolation test** - Start daemon in dir A, verify queries from dir B fail gracefully
2. **MCP daemon routing test** - All MCP tools work when daemon is running
3. **MUQL table validation test** - Invalid tables return errors
4. **Diff path normalization test** - Output contains relative paths only
5. **mu_why path formats test** - Accepts relative, absolute, and node ID formats

### Manual Testing Checklist

- [ ] Start daemon in project A, switch to project B, verify daemon stop works
- [ ] Run all MCP tools with daemon running
- [ ] Run `mu diff HEAD~1 HEAD` and verify paths are relative
- [ ] Run `FIND functions CALLING x LIMIT 5` and verify it works
- [ ] Run `SELECT * FROM invalid` and verify error message

## Success Metrics

1. All 17 bugs resolved
2. No regression in existing tests
3. New tests added for each bug fix
4. Zero "Database is locked" errors when daemon running

## Appendix: Full Bug Testing Session

The bugs were discovered during a comprehensive testing session running:
- `mu_bootstrap` / `mu_status`
- `mu query` with various MUQL
- `mu compress` on files and directories
- `mu diff` between commits
- `mu daemon start/status/stop`
- `mu_remember` / `mu_recall`
- `mu_task_context` / `mu_why` / `mu_warn` / `mu_related`
- `mu_patterns` / `mu_validate` / `mu_generate`
- `mu_impact` / `mu_cycles` / `mu_ancestors`

Full testing commands and outputs are available in the session transcript.

## References

- [MU Architecture Documentation](../architecture.md)
- [MCP Server Implementation](../../src/mu/mcp/CLAUDE.md)
- [Daemon Documentation](../../src/mu/daemon/CLAUDE.md)
