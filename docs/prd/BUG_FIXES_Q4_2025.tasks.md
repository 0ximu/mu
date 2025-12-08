# Bug Fixes Q4 2025 - Task Breakdown

**PRD:** [BUG_FIXES_Q4_2025.md](./BUG_FIXES_Q4_2025.md)
**Created:** 2025-12-08

## Phase 1: Critical Fixes

### Task 1.1: Fix MCP Tools Daemon Routing (BUG-002)
**Priority:** P0 | **Effort:** 4h | **Status:** Not Started

#### Subtasks
- [ ] 1.1.1 Audit all MCP tools for daemon routing status
- [ ] 1.1.2 Extract daemon routing pattern from `mu_query` as reusable helper
- [ ] 1.1.3 Add daemon routing to `mu_remember`
- [ ] 1.1.4 Add daemon routing to `mu_recall`
- [ ] 1.1.5 Add daemon routing to `mu_task_context`
- [ ] 1.1.6 Add daemon routing to `mu_warn`
- [ ] 1.1.7 Add daemon routing to `mu_related`
- [ ] 1.1.8 Add daemon routing to `mu_why`
- [ ] 1.1.9 Add tests for each tool with daemon running
- [ ] 1.1.10 Update MCP documentation

#### Files
- `src/mu/mcp/server.py`
- `src/mu/client.py`
- `tests/unit/test_mcp.py`

#### Acceptance Criteria
- All MCP tools work when daemon is running
- No "Database is locked" errors
- Tests pass with daemon running in background

---

### Task 1.2: Implement Daemon Discovery (BUG-001)
**Priority:** P0 | **Effort:** 8h | **Status:** Not Started

#### Subtasks
- [ ] 1.2.1 Design daemon registry format (`~/.mu/daemons.json`)
- [ ] 1.2.2 Add daemon registration on start
- [ ] 1.2.3 Add daemon deregistration on stop
- [ ] 1.2.4 Add project path validation in daemon responses
- [ ] 1.2.5 Update `daemon status` to check registry
- [ ] 1.2.6 Update `daemon stop` to find correct daemon
- [ ] 1.2.7 Add `daemon list` command to show all running daemons
- [ ] 1.2.8 Add `daemon stop --all` to stop all daemons
- [ ] 1.2.9 Handle stale entries (daemon crashed without cleanup)
- [ ] 1.2.10 Add tests for multi-project daemon scenarios

#### Files
- `src/mu/daemon/lifecycle.py`
- `src/mu/daemon/server.py`
- `src/mu/daemon/config.py`
- `src/mu/commands/daemon/start.py`
- `src/mu/commands/daemon/stop.py`
- `src/mu/commands/daemon/status.py`

#### Acceptance Criteria
- Starting daemon in project A then switching to B shows warning
- `daemon stop` finds and stops correct daemon
- `daemon list` shows all running daemons across projects
- Stale PID files are cleaned up automatically

---

### Task 1.3: Fix Test Regex (BUG-008)
**Priority:** P0 | **Effort:** 15m | **Status:** Not Started

#### Subtasks
- [ ] 1.3.1 Update test regex from "No .mubase found" to "No .mu/mubase found"
- [ ] 1.3.2 Run test to verify fix

#### Files
- `tests/unit/test_mcp.py` (line ~130)

#### Acceptance Criteria
- Test passes
- CI is green

---

## Phase 2: High Priority Fixes

### Task 2.1: Fix Diff Path Display (BUG-003)
**Priority:** P1 | **Effort:** 2h | **Status:** Not Started

#### Subtasks
- [ ] 2.1.1 Identify worktree path prefix pattern
- [ ] 2.1.2 Add path stripping to `format_diff`
- [ ] 2.1.3 Add path stripping to `format_diff_markdown`
- [ ] 2.1.4 Add tests for relative path output

#### Files
- `src/mu/diff/formatters.py`
- `tests/unit/test_diff.py`

#### Acceptance Criteria
- `mu diff` shows relative paths like `src/foo.py`
- No temp directory paths in output

---

### Task 2.2: Add LIMIT to FIND Queries (BUG-004)
**Priority:** P1 | **Effort:** 4h | **Status:** Not Started

#### Subtasks
- [ ] 2.2.1 Update MUQL grammar to support LIMIT on FIND
- [ ] 2.2.2 Update Rust parser to handle LIMIT clause
- [ ] 2.2.3 Update executor to apply limit
- [ ] 2.2.4 Add tests for FIND with LIMIT

#### Files
- `mu-core/src/muql/parser.rs`
- `mu-core/src/muql/executor.rs`
- `tests/unit/test_muql_parser.py`

#### Acceptance Criteria
- `FIND functions CALLING x LIMIT 5` works
- `FIND classes INHERITING y LIMIT 10` works

---

### Task 2.3: Add MUQL Table Validation (BUG-005)
**Priority:** P1 | **Effort:** 2h | **Status:** Not Started

#### Subtasks
- [ ] 2.3.1 Define valid table names list
- [ ] 2.3.2 Add validation in query parsing/execution
- [ ] 2.3.3 Return clear error message for invalid tables
- [ ] 2.3.4 Add tests for invalid table names

#### Files
- `src/mu/kernel/muql/engine.py` or `mu-core/src/muql/executor.rs`
- `tests/unit/test_muql_executor.py`

#### Acceptance Criteria
- `SELECT * FROM invalid_table` returns error
- Error message lists valid table names

---

## Phase 3: Medium Priority Fixes

### Task 3.1: Fix mu_why Path Resolution (BUG-006)
**Priority:** P2 | **Effort:** 2h | **Status:** Not Started

#### Subtasks
- [ ] 3.1.1 Accept relative paths and resolve to absolute
- [ ] 3.1.2 Accept node names and resolve to file paths
- [ ] 3.1.3 Improve error message with examples
- [ ] 3.1.4 Add tests for various path formats

#### Files
- `src/mu/mcp/server.py`
- `src/mu/intelligence/why.py`

---

### Task 3.2: Fix mu_related File Existence Check (BUG-007)
**Priority:** P2 | **Effort:** 1h | **Status:** Not Started

#### Subtasks
- [ ] 3.2.1 Fix path resolution in existence check
- [ ] 3.2.2 Use absolute paths consistently
- [ ] 3.2.3 Add tests for relative path inputs

#### Files
- `src/mu/intelligence/related.py`

---

### Task 3.3: Fix Semantic Diff Path Normalization (BUG-009)
**Priority:** P2 | **Effort:** 2h | **Status:** Not Started

#### Subtasks
- [ ] 3.3.1 Normalize paths before comparison
- [ ] 3.3.2 Match files by relative path, not absolute
- [ ] 3.3.3 Verify diff counts are accurate

#### Files
- `src/mu/diff/differ.py`

---

## Phase 4: Low Priority Fixes

### Task 4.1: Guard Against :memory: Directory (BUG-010)
**Priority:** P3 | **Effort:** 30m | **Status:** Not Started

#### Subtasks
- [ ] 4.1.1 Add check for `:memory:` special path
- [ ] 4.1.2 Skip directory creation for in-memory databases
- [ ] 4.1.3 Clean up existing `:memory:` directory

#### Files
- `src/mu/kernel/mubase.py`

---

### Task 4.2: Add Empty Question Validation (BUG-011)
**Priority:** P3 | **Effort:** 30m | **Status:** Not Started

#### Subtasks
- [ ] 4.2.1 Add input validation before database access
- [ ] 4.2.2 Return clear "Question cannot be empty" error
- [ ] 4.2.3 Add test for empty input

#### Files
- `src/mu/commands/kernel/context.py`

---

## Progress Tracking

| Phase | Tasks | Completed | Progress |
|-------|-------|-----------|----------|
| Phase 1 | 3 | 0 | 0% |
| Phase 2 | 3 | 0 | 0% |
| Phase 3 | 3 | 0 | 0% |
| Phase 4 | 2 | 0 | 0% |
| **Total** | **11** | **0** | **0%** |

## Quick Start Commands

```bash
# Run all tests before starting
uv run pytest tests/unit/ -x

# After fixes, run full test suite
uv run pytest

# Check for type errors
uv run mypy src/mu

# Format and lint
uv run ruff check src/ && uv run ruff format src/
```

## Definition of Done

- [ ] All subtasks completed
- [ ] Tests added for each fix
- [ ] No regression in existing tests
- [ ] Code reviewed
- [ ] Documentation updated where applicable
- [ ] Changelog entry added
