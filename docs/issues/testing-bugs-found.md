# MU Testing - Bugs and Issues Found

Date: 2025-12-09

## Critical Bugs

### 1. FIND CALLING Query Ignores Target Function Name
**Severity**: High
**Location**: MUQL executor (daemon or Python)

**Issue**: `FIND functions CALLING nonexistent_function` returns ALL functions instead of filtering by the function name.

**Steps to Reproduce**:
```bash
uv run mu q "FIND functions CALLING nonexistent_xyz"
```

**Expected**: Empty result or error
**Actual**: Returns 100+ unfiltered functions

---

### 2. MUQL SELECT Returns Generic Column Names
**Severity**: Medium
**Location**: Query result column naming (MCP/daemon)

**Issue**: `SELECT * FROM functions` returns columns named `col_0`, `col_1`, etc. instead of descriptive names like `id`, `type`, `name`, `file_path`, etc.

**Steps to Reproduce**:
```python
mu_query("SELECT * FROM functions LIMIT 5")
# Returns: {"columns": ["col_0", "col_1", "col_2", ...]}
```

**Expected**: `{"columns": ["id", "type", "name", "file_path", ...]}`

---

### 3. mu_deps Returns Empty for Valid Nodes
**Severity**: Medium
**Location**: `mu_deps` MCP tool

**Issue**: `mu_deps` returns empty dependencies for nodes that clearly have dependencies (confirmed via `mu_impact` returning many results).

**Steps to Reproduce**:
```python
mu_deps("MUQLParser", depth=2, direction="both")
# Returns: {"node_id": "MUQLParser", "direction": "both", "dependencies": []}

# But mu_impact works:
mu_impact("mod:src/mu/kernel/muql/parser.py")
# Returns: 137 impacted nodes
```

---

### 4. mu_deps Silent Failure for Nonexistent Nodes
**Severity**: Medium
**Location**: `mu_deps` MCP tool

**Issue**: When querying a nonexistent node, `mu_deps` returns an empty result instead of an error.

**Steps to Reproduce**:
```python
mu_deps("nonexistent_node_xyz")
# Returns: {"node_id": "nonexistent_node_xyz", "direction": "outgoing", "dependencies": []}
```

**Expected**: Error message indicating node not found

---

## UX Issues

### 5. Multiple MCP Tools Require Stopping Daemon
**Severity**: High (UX)
**Location**: `mu_context_omega`, `mu_patterns`, `mu_warn`

**Issue**: Several MCP tools fail with "requires direct database access, stop daemon" error. This is problematic because:
- The daemon is the recommended way to use MU
- Users have to stop/restart daemon for these features
- Inconsistent experience with other tools that work through daemon

**Affected Tools**:
- `mu_context_omega()` - OMEGA compressed context
- `mu_patterns()` - Pattern detection
- `mu_warn()` - Proactive warnings

**Error Message**:
```
"OMEGA context requires direct database access. Stop the daemon ('mu daemon stop') or use mu_context() instead."
```

---

### 6. mu vibe Database Lock Error
**Severity**: Medium
**Location**: `mu vibe` CLI command

**Issue**: `mu vibe` command fails with database lock error even though daemon is running.

**Steps to Reproduce**:
```bash
uv run mu vibe
# Error: Database is locked. Start daemon with 'mu daemon start' or stop it with 'mu daemon stop'.
```

**Expected**: Should work with daemon running (like other commands do)

---

### 7. mu read Requires Full Node ID
**Severity**: Low
**Location**: `mu_read` MCP tool / `mu read` CLI

**Issue**: `mu_read("MUQLParser")` fails - requires full qualified node ID like `cls:src/mu/kernel/muql/parser.py:MUQLParser`.

**Error Message**: Helpful - suggests using `mu_query` to find nodes with file paths. This is acceptable behavior but could be improved with fuzzy matching.

---

## Working Features

The following features work correctly:
- `mu_status()` - Returns daemon and database status
- `mu_bootstrap()` - Initializes MU for codebase
- `mu_query()` - Executes MUQL queries (aside from column naming)
- `mu_context()` - Smart context extraction
- `mu_impact()` - Impact analysis
- `mu_read()` - Source code reading (with full node ID)
- `mu_semantic_diff()` - Git semantic diff
- `mu_review_diff()` - Code review with pattern validation
- CLI commands: `mu status`, `mu q`, `mu context`, `mu read`

---

## Recommendations

1. **Priority 1**: Fix FIND CALLING to actually filter by function name
2. **Priority 2**: Route `mu_patterns`, `mu_warn`, `mu_context_omega` through daemon API
3. **Priority 3**: Fix column naming in query results
4. **Priority 4**: Add proper error handling for nonexistent nodes in `mu_deps`
5. **Priority 5**: Fix `mu vibe` database lock issue
