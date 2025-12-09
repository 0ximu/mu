# MCP Tools Database Lock Issues

## Summary

When the MU daemon is running, most MCP tools fail with "Database is locked" errors because they try to open the DuckDB database without `read_only=True` in their fallback paths.

## Root Cause

The MCP tools access the `.mu/mubase` DuckDB database directly in their fallback code paths, but don't use `read_only=True` when opening the database. Since the daemon holds an exclusive lock on the database, any write-mode open attempt fails.

## Affected Tools

### Broken (missing `read_only=True`)

| Tool | File | Line | Status |
|------|------|------|--------|
| `mu_query` | `tools/graph.py` | 57 | `MUbase(mubase_path)` - BROKEN |
| `mu_read` | `tools/graph.py` | 214 | `MUbase(mubase_path)` - BROKEN |
| `mu_deps` | `tools/analysis.py` | 50 | `MUbase(mubase_path)` - BROKEN |
| `mu_impact` | `tools/analysis.py` | 140 | `MUbase(mubase_path)` - BROKEN |
| `mu_patterns` | `tools/guidance.py` | 54 | `MUbase(mubase_path)` - BROKEN |
| `mu_context` | `tools/context.py` | 61 | `MUbase(mubase_path)` - BROKEN |

### Working (has `read_only=True`)

| Tool | File | Line | Status |
|------|------|------|--------|
| `mu_warn` | `tools/guidance.py` | 160 | `MUbase(mubase_path, read_only=True)` - OK |
| `mu_context_omega` | `tools/context.py` | 125 | `MUbase(mubase_path, read_only=True)` - OK |

### Don't Need DB (always work)

| Tool | Status |
|------|--------|
| `mu_status` | OK - only checks health |
| `mu_bootstrap` | OK - uses daemon API |
| `mu_semantic_diff` | OK - parses files directly |
| `mu_review_diff` | OK - parses files directly |

## Fix

Add `read_only=True` to all MUbase instantiations in MCP tools that only need read access:

```python
# Before (broken)
db = MUbase(mubase_path)

# After (fixed)
db = MUbase(mubase_path, read_only=True)
```

## Additional Issue: Daemon Routing

The MCP tools should ideally route through the daemon when it's running (like CLI commands do), not fall back to direct DB access. The fallback should only be used when the daemon is NOT running.

Current behavior:
1. Tool tries daemon -> gets error
2. Falls back to direct MUbase access -> fails with DB lock

Expected behavior:
1. Tool routes through daemon -> succeeds

The `mu_query` and `mu_read` tools try to use the daemon client first, but for tools like `mu_deps`, `mu_impact`, `mu_patterns` they go straight to MUbase without trying daemon first.

## Testing Notes

- `mu_status` MCP tool works fine
- `mu_query` MCP tool returns results via daemon when daemon is healthy
- CLI commands work because they route queries through daemon HTTP API
- The inconsistency is that some MCP tools use daemon routing, others don't
