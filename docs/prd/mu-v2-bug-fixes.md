# MU v0.1.0 Bug Fixes PRD

> **Version:** 0.1.0
> **Status:** Draft
> **Created:** 2024-12-13
> **Author:** Dogfooding Analysis

## Overview

Critical bugs discovered during dogfooding MU on its own codebase. Issues range from broken core features (graph reasoning) to UX polish (missing CLI flags).

## Goals

1. Fix graph reasoning so `deps`, `ancestors`, `cycles` return actual results
2. Ensure terse MUQL syntax works consistently
3. Respect `.murc.toml` configuration
4. Provide clear errors for schema incompatibility
5. Complete CLI feature parity with daemon

## Non-Goals

- Schema migration (v0.0.1 - just provide clear error message)
- Backward compatibility with Python v1 databases
- New features beyond fixing existing broken ones

---

## Phase 1: Core Functionality (Critical)

### 1.1 Fix Graph Reasoning - Calls Edge Resolution

**Priority:** P0 - Critical
**Effort:** 2-3 hours

**Problem:** `mu deps`, `mu ancestors` return "No dependencies found" for all nodes because CALLS edges are not being created.

**Root Cause:** Key format mismatch in `mu-daemon/src/build/pipeline.rs`:
- `func_lookup` populated with keys: `"main"`, `"src/cli.py:main"` (NO prefix)
- Resolution queries use keys: `"fn:src/cli.py:main"` (WITH `fn:` prefix)
- Keys never match → `resolve_call_site()` returns `None` → no CALLS edges

**Files to Change:**
- `mu-daemon/src/build/pipeline.rs` (lines 197-208, 528-583)

**Solution:**
```rust
// In build_graph(), when populating func_lookup (line ~200):
for node in &nodes {
    if node.node_type == NodeType::Function {
        // Store with full ID format for exact matches
        func_lookup.insert(node.id.clone(), node.id.clone());
        // Also store by simple name for fallback
        func_lookup.insert(node.name.clone(), node.id.clone());
        // And qualified name
        if let Some(ref qname) = node.qualified_name {
            func_lookup.insert(qname.clone(), node.id.clone());
        }
    }
}
```

**Acceptance Criteria:**
- [ ] `duckdb .mu/mubase "SELECT edge_type, COUNT(*) FROM edges GROUP BY edge_type"` shows non-zero `calls` count
- [ ] `mu deps "fn:mu-cli/src/main.rs:main"` returns actual dependencies
- [ ] `mu ancestors "fn:mu-daemon/src/build/pipeline.rs:build_graph"` returns callers

---

### 1.2 Fix Cycles Display Bug

**Priority:** P0 - Critical
**Effort:** 30 minutes

**Problem:** `mu cycles` shows "7 cycles, 0 nodes involved" - cycles detected but nodes are empty.

**Root Cause:** Data structure mismatch in serialization:
- `executor.rs` wraps each cycle as `Value::Array` in single-element row
- `http.rs` calls `.as_str()` on arrays → returns `None` → nodes discarded

**Files to Change:**
- `mu-daemon/src/muql/executor.rs` (lines 120-130)

**Solution:** Flatten cycle arrays in executor output:
```rust
// Change from:
rows: cycles.into_iter().map(|c| {
    vec![serde_json::Value::Array(
        c.into_iter().map(serde_json::Value::String).collect(),
    )]
}).collect(),

// Change to:
rows: cycles.into_iter().map(|c| {
    c.into_iter().map(serde_json::Value::String).collect()
}).collect(),
```

**Acceptance Criteria:**
- [ ] `mu cycles` shows actual node IDs in each cycle
- [ ] Summary shows correct node count matching actual nodes displayed

---

### 1.3 Schema Incompatibility Error

**Priority:** P1 - High
**Effort:** 1 hour

**Problem:** Old v1 databases fail with cryptic "column named model" DuckDB error.

**Root Cause:** Rust v2 uses different column names (`model` vs `model_name`). No detection or error handling.

**Files to Change:**
- `mu-daemon/src/storage/mubase.rs` (lines 106-121)

**Solution:** Detect old schema and provide clear error:
```rust
fn init_schema(&self) -> Result<()> {
    let conn = self.acquire_conn()?;

    // Check for v1 schema (has model_name column in embeddings with old structure)
    let has_old_schema: bool = conn
        .query_row(
            "SELECT COUNT(*) > 0 FROM information_schema.columns
             WHERE table_name = 'embeddings' AND column_name = 'model_name'",
            [],
            |row| row.get(0),
        )
        .unwrap_or(false);

    if has_old_schema {
        anyhow::bail!(
            "Database was created with MU v1 and is incompatible with v2.\n\
             Please delete and rebuild:\n\n\
               rm -rf .mu && mu bootstrap\n"
        );
    }

    conn.execute_batch(SCHEMA_SQL)?;
    Ok(())
}
```

**Acceptance Criteria:**
- [ ] Opening v1 database shows clear error message with fix instructions
- [ ] Fresh databases work normally
- [ ] Error message includes exact command to fix

---

## Phase 2: UX Polish

### 2.1 Fix Terse MUQL Pattern Matching

**Priority:** P2 - Medium
**Effort:** 1-2 hours

**Problem:** `mu q "fn n~'parse'"` returns nothing while `mu q "cls n~'Service'"` works.

**Root Cause:** Suspected database content issue - function names may include module prefixes that classes don't have.

**Files to Change:**
- `mu-daemon/src/muql/executor.rs` (add debug logging)
- `mu-daemon/src/muql/planner.rs` (verify SQL generation)

**Investigation Steps:**
1. Add SQL debug logging to see generated queries
2. Compare function name storage vs class name storage
3. Fix either storage format or query generation

**Solution:** Add debug flag, then fix based on findings:
```rust
// In executor.rs - temporary debug
if std::env::var("MU_DEBUG_SQL").is_ok() {
    eprintln!("SQL: {}", sql);
}
```

**Acceptance Criteria:**
- [ ] `mu q "fn n~'parse'"` returns functions containing "parse"
- [ ] `mu q "fn n~'build'"` returns functions containing "build"
- [ ] Pattern matching works consistently for all node types

---

### 2.2 Load .murc.toml Configuration

**Priority:** P2 - Medium
**Effort:** 2 hours

**Problem:** `.murc.toml` is created by bootstrap but never loaded. Scanner ignores custom ignore patterns.

**Root Cause:** Scanner called with `ignore_patterns = None` in both daemon and CLI.

**Files to Change:**
- `mu-cli/src/commands/bootstrap.rs` (line 264) - pass ignore patterns
- `mu-daemon/src/build/pipeline.rs` (line 45) - pass ignore patterns
- New: `mu-cli/src/config.rs` - config loading utility

**Solution:**
```rust
// New: mu-cli/src/config.rs
use serde::Deserialize;
use std::path::Path;

#[derive(Deserialize, Default)]
pub struct MuConfig {
    pub scanner: Option<ScannerConfig>,
}

#[derive(Deserialize, Default)]
pub struct ScannerConfig {
    pub ignore: Option<Vec<String>>,
}

pub fn load_config(root: &Path) -> MuConfig {
    let config_path = root.join(".murc.toml");
    if config_path.exists() {
        std::fs::read_to_string(&config_path)
            .ok()
            .and_then(|content| toml::from_str(&content).ok())
            .unwrap_or_default()
    } else {
        MuConfig::default()
    }
}

// In bootstrap.rs:
let config = config::load_config(&root);
let ignore_patterns: Option<Vec<&str>> = config
    .scanner
    .as_ref()
    .and_then(|s| s.ignore.as_ref())
    .map(|v| v.iter().map(|s| s.as_str()).collect());

let scan_result = mu_core::scanner::scan_directory_sync(
    root_str,
    None,
    ignore_patterns.as_deref(),
    false, false, false
);
```

**Also:** Add `archive/` to default ignore list in bootstrap template.

**Acceptance Criteria:**
- [ ] Files in `.murc.toml` `scanner.ignore` list are excluded from scan
- [ ] `archive/` added to default ignore list
- [ ] `mu status` shows only relevant files (not archive/)

---

## Phase 3: Feature Completeness

### 3.1 Add Export --limit Flag

**Priority:** P3 - Low
**Effort:** 30 minutes

**Problem:** `mu export --limit` documented but not implemented in CLI.

**Files to Change:**
- `mu-cli/src/main.rs` (Export struct)
- `mu-cli/src/commands/export.rs`

**Solution:**
```rust
// In main.rs, Export struct:
#[derive(Parser)]
pub struct Export {
    /// Maximum number of nodes to export
    #[arg(short = 'n', long)]
    limit: Option<usize>,
    // ... existing fields
}

// In export.rs:
if let Some(limit) = args.limit {
    query_params.push(("max_nodes", limit.to_string()));
}
```

**Acceptance Criteria:**
- [ ] `mu export -F json --limit 100` exports max 100 nodes
- [ ] `mu export --help` shows --limit flag
- [ ] Works with all export formats

---

### 3.2 Documentation Updates

**Priority:** P3 - Low
**Effort:** 30 minutes

**Files to Change:**
- `CLAUDE.md`
- `.claude/CLAUDE.md`

**Changes:**
- Remove `--limit` from export examples until implemented
- Add note about `rm -rf .mu` for fresh start
- Update terse MUQL examples with working queries
- Add troubleshooting section

**Acceptance Criteria:**
- [ ] All CLI examples in docs actually work
- [ ] Troubleshooting section covers common issues

---

## Implementation Order

```
Phase 1 (Critical - Do First)
├── 1.1 Fix calls edge resolution ............ [2-3h]
├── 1.2 Fix cycles display ................... [30m]
└── 1.3 Schema error message ................. [1h]

Phase 2 (UX - Do Second)
├── 2.1 Debug/fix terse MUQL ................. [1-2h]
└── 2.2 Load .murc.toml config ............... [2h]

Phase 3 (Polish - Do Last)
├── 3.1 Export --limit flag .................. [30m]
└── 3.2 Documentation updates ................ [30m]

Total: ~8-10 hours
```

---

## Testing Plan

### Phase 1 Verification
```bash
rm -rf .mu && mu bootstrap
duckdb .mu/mubase "SELECT edge_type, COUNT(*) FROM edges GROUP BY edge_type"
# Should show: calls | N (where N > 0)

mu deps "fn:mu-cli/src/main.rs:main"
# Should show actual dependencies

mu cycles
# Should show actual node IDs, not "0 nodes"
```

### Phase 2 Verification
```bash
MU_DEBUG_SQL=1 mu q "fn n~'parse'"
# Debug output shows SQL, results should appear

mu status
# Should NOT show archive/ files
```

### Phase 3 Verification
```bash
mu export -F json --limit 10 | jq '.nodes | length'
# Should output: 10
```

---

## Success Metrics

- [ ] All 6 issues resolved
- [ ] `mu deps`, `mu ancestors`, `mu cycles` return meaningful results
- [ ] Terse MUQL works consistently
- [ ] Config file is respected
- [ ] Clear error for incompatible databases
- [ ] All documented CLI flags exist
- [ ] `cargo test` passes
- [ ] `cargo clippy` clean
