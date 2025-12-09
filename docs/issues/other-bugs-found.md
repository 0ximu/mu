# Other Bugs Found During Testing

## 1. MUQL "FIND functions CALLING" Returns All Functions

**Command:** `mu query "FIND functions CALLING process_payment"`

**Expected:** Only functions that call `process_payment`

**Actual:** Returns ALL functions (100 rows)

**Analysis:** The FIND CALLING query doesn't seem to filter correctly - it returns all functions in the database regardless of the target.

---

## 2. CLI "patterns" Command Fails with DB Lock

**Command:** `mu patterns`

**Error:**
```
Error: Database is locked. Start daemon with 'mu daemon start' or stop it with 'mu daemon stop'.
```

**Analysis:** Same root cause as MCP tools - the CLI patterns command doesn't route through daemon.

---

## 3. CLI "warn" Command Fails with DB Lock

**Command:** `mu warn src/mu/mcp/tools/context.py`

**Error:**
```
Error: Database is locked. Start daemon with 'mu daemon start' or stop it with 'mu daemon stop'.
```

**Analysis:** Same root cause - CLI warn command doesn't route through daemon.

---

## 4. CLI "omg" (OMEGA context) Fails with DB Lock

**Command:** `mu omg "Show me how imports work"`

**Error:**
```
Error: Database is locked. Start daemon with 'mu daemon start' or stop it with 'mu daemon stop'.
```

**Analysis:** Same root cause.

---

## 5. mu_context MCP Returns Empty Results

**Tool:** `mcp__mu__mu_context`

**Input:** `{"question": "How does authentication work?"}`

**Output:**
```json
{"mu_text":"","token_count":0,"node_count":0}
```

**Expected:** Should return relevant code context about authentication

**Analysis:** The context extraction either:
1. Daemon routing fails and returns empty fallback
2. Question matching isn't finding relevant nodes

---

## 6. Impact Command Returns 0 Nodes for Valid Files

**Command:** `mu impact mod:src/mu/mcp/tools/context.py`

**Output:** "0 nodes" impacted

**Analysis:** Either:
1. The module isn't in the graph properly
2. The impact calculation isn't working

---

## 7. MUQL Columns Named "col_0, col_1, col_2..."

**Command:** `mu query "SELECT * FROM functions LIMIT 5"`

**Output columns:** `col_0`, `col_1`, `col_2`, etc.

**Expected:** Named columns like `id`, `name`, `type`, `file_path`, etc.

**Analysis:** The Rust daemon's MUQL parser may not be properly aliasing columns.

---

## 8. Daemon Status Shows "unknown"

**Command:** `mu daemon status`

**Output:**
```
Status: unknown
PID: 20657
Healthy: Yes
```

**Analysis:** Status is "unknown" but daemon is healthy - inconsistent status reporting.

---

## Summary

| Bug | Severity | Category |
|-----|----------|----------|
| MCP DB Lock | High | Architecture |
| CLI DB Lock | High | Architecture |
| FIND CALLING broken | Medium | MUQL Parser |
| Empty context results | Medium | Context Extraction |
| Impact returns 0 | Medium | Graph Analysis |
| Column names wrong | Low | Display |
| Daemon status unknown | Low | Status Reporting |
