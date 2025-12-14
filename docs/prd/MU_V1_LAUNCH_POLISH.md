# PRD: MU v1.0 Launch Polish

**Status:** Draft
**Priority:** High
**Author:** Claude + Yavor
**Created:** 2025-12-12
**Target:** v1.0 Release

## Executive Summary

MU has completed the Python→Rust migration. This PRD covers the final polish needed before v1.0 public release. Focus areas: fix critical bugs, improve DX, and ensure production reliability.

---

## Problem Statement

After 7 days of intensive development and a full Rust migration, MU is functional but has rough edges:

1. **DB Lock Conflicts** - CLI commands fail when MCP server holds the database lock
2. **Language-Unaware Linting** - `mu vibe` suggests snake_case for C#/Java (should be PascalCase)
3. **No Incremental Embeddings** - `bootstrap --embed` regenerates all embeddings every time
4. **MCP/Daemon Friction** - Users confused about when to use daemon vs MCP mode

---

## Goals

| Goal | Success Metric |
|------|----------------|
| Zero lock conflicts in normal usage | No "Conflicting lock" errors in happy path |
| Language-aware conventions | `mu vibe` passes on idiomatic C#/Java/Python |
| 10x faster re-indexing | Incremental embedding updates < 5s for single file change |
| Clear daemon/MCP UX | Users understand which mode to use without docs |

## Non-Goals

- New features (save for v1.1)
- Additional language support
- GUI/web interface
- Cloud deployment

---

## Epic 1: Database Concurrency Fix

**Priority:** P0 - Blocking
**Effort:** 1-2 days

### Problem

DuckDB exclusive lock prevents CLI commands when MCP server is running:
```
Error: IO Error: Could not set lock on file ".mu/mubase":
Conflicting lock is held in mu (PID 20875)
```

### Solution Options

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| A. WAL Mode | Simple, one-line change | Slightly slower writes | **Do this first** |
| B. CLI→Daemon proxy | Consistent behavior | More complex | Phase 2 |
| C. Read-only CLI mode | Quick fix | Limited functionality | Fallback only |

### Implementation

#### Option A: Enable WAL Mode (Do First)

```rust
// mu-daemon/src/storage/mubase.rs
impl MUbase {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let conn = Connection::open(path)?;

        // Enable WAL mode for concurrent reads
        conn.execute("PRAGMA journal_mode=WAL", [])?;
        conn.execute("PRAGMA busy_timeout=5000", [])?;

        // ... rest of init
    }
}
```

#### Option B: CLI Daemon Proxy (Phase 2)

```rust
// mu-cli/src/commands/query.rs
pub async fn run(query: &str, format: OutputFormat) -> Result<()> {
    // Check if daemon is running
    if let Ok(client) = DaemonClient::connect().await {
        // Proxy through daemon
        let result = client.query(query).await?;
        output::print(result, format);
    } else {
        // Direct DB access (no daemon)
        let db = MUbase::open(".mu/mubase")?;
        // ...
    }
}
```

### Acceptance Criteria

- [ ] `mu query` works while `mu serve --mcp` is running
- [ ] `mu search` works while daemon is running
- [ ] `mu deps` works while daemon is running
- [ ] No data corruption under concurrent access
- [ ] Add integration test for concurrent access

---

## Epic 2: Language-Aware Vibe Checks

**Priority:** P1 - High
**Effort:** 1 day

### Problem

`mu vibe` applies Python conventions (snake_case) to all languages:

```
X [naming] Function 'TransactionService' should use snake_case
  src/dominaite-gateway-api/Services/TransactionService.cs
  -> Rename to 'transaction_service'
```

This is wrong for C#, Java, TypeScript, Go.

### Solution

Add language detection and convention mapping:

```rust
// mu-cli/src/commands/vibes/vibe.rs

#[derive(Debug, Clone)]
enum NamingConvention {
    SnakeCase,      // python, rust
    PascalCase,     // c#, java (classes)
    CamelCase,      // typescript, javascript
    GoCase,         // go (exported = PascalCase, private = camelCase)
}

fn get_convention(language: &str, entity_type: &str) -> NamingConvention {
    match (language, entity_type) {
        // C# / Java
        ("csharp" | "java", "class" | "interface" | "struct") => PascalCase,
        ("csharp" | "java", "function" | "method") => PascalCase,
        ("csharp" | "java", "variable" | "parameter") => CamelCase,

        // Python / Rust
        ("python" | "rust", "class") => PascalCase,
        ("python" | "rust", "function") => SnakeCase,

        // TypeScript / JavaScript
        ("typescript" | "javascript", "class") => PascalCase,
        ("typescript" | "javascript", "function") => CamelCase,

        // Go
        ("go", _) => GoCase,

        _ => SnakeCase, // default
    }
}

fn check_naming(name: &str, convention: NamingConvention) -> Option<String> {
    match convention {
        PascalCase if !is_pascal_case(name) => {
            Some(format!("should use PascalCase -> {}", to_pascal_case(name)))
        }
        SnakeCase if !is_snake_case(name) => {
            Some(format!("should use snake_case -> {}", to_snake_case(name)))
        }
        CamelCase if !is_camel_case(name) => {
            Some(format!("should use camelCase -> {}", to_camel_case(name)))
        }
        _ => None,
    }
}
```

### Acceptance Criteria

- [ ] `mu vibe` passes on idiomatic C# code (PascalCase methods)
- [ ] `mu vibe` passes on idiomatic Python code (snake_case functions)
- [ ] `mu vibe` passes on idiomatic TypeScript code (camelCase functions)
- [ ] `mu vibe` passes on idiomatic Go code (exported PascalCase)
- [ ] Add `--convention` flag to override auto-detection
- [ ] Add unit tests for each language convention

---

## Epic 3: Incremental Embedding Updates

**Priority:** P1 - High
**Effort:** 2-3 days

### Problem

`mu bootstrap --embed` regenerates all 9,627 embeddings every time (~3-4 minutes).
Single file changes should update in seconds.

### Solution

Track file content hashes and only re-embed changed files:

```rust
// mu-daemon/src/storage/schema.rs
const SCHEMA_SQL: &str = r#"
    -- Existing tables...

    -- New: File hash tracking for incremental updates
    CREATE TABLE IF NOT EXISTS file_hashes (
        file_path TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL,
        embedded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_file_hashes_hash ON file_hashes(content_hash);
"#;

// mu-cli/src/commands/bootstrap.rs
pub async fn run_incremental_embed(path: &str) -> Result<()> {
    let db = MUbase::open(".mu/mubase")?;

    // Get current file hashes
    let current_hashes = scan_file_hashes(path)?;

    // Get stored hashes
    let stored_hashes = db.get_file_hashes()?;

    // Find changed files
    let changed: Vec<_> = current_hashes
        .iter()
        .filter(|(path, hash)| {
            stored_hashes.get(*path) != Some(hash)
        })
        .collect();

    if changed.is_empty() {
        println!("No changes detected. Embeddings up to date.");
        return Ok(());
    }

    println!("Re-embedding {} changed files...", changed.len());

    // Re-embed only changed files
    for (file_path, hash) in changed {
        let nodes = db.get_nodes_for_file(file_path)?;
        let embeddings = model.embed_nodes(&nodes)?;
        db.update_embeddings(file_path, &embeddings)?;
        db.update_file_hash(file_path, hash)?;
    }

    Ok(())
}
```

### File Watcher Integration

```rust
// mu-daemon/src/watcher/mod.rs
impl Watcher {
    async fn on_file_change(&self, path: &Path) -> Result<()> {
        // 1. Re-parse file
        let module = parse_file(path)?;

        // 2. Update graph
        self.db.update_nodes_for_file(path, &module)?;

        // 3. Re-embed (if embeddings enabled)
        if self.embeddings_enabled {
            let nodes = self.db.get_nodes_for_file(path)?;
            let embeddings = self.model.embed_nodes(&nodes)?;
            self.db.update_embeddings(path, &embeddings)?;
        }

        // 4. Notify MCP clients
        self.broadcast_update(path).await?;

        Ok(())
    }
}
```

### Acceptance Criteria

- [ ] Single file change re-embeds in < 5 seconds
- [ ] File hash tracking persists across restarts
- [ ] `mu bootstrap --embed` is idempotent (no changes = no work)
- [ ] Daemon auto-updates embeddings on file save
- [ ] Add `mu embed --incremental` command
- [ ] Add `mu embed --status` to show stale files

---

## Epic 4: Daemon/MCP UX Improvements

**Priority:** P2 - Medium
**Effort:** 1 day

### Problem

Users confused about daemon modes:
- `mu serve` - HTTP daemon on port 9120
- `mu serve --mcp` - MCP server on stdio
- `mu serve -f` - Foreground mode

### Solution

#### 4.1 Better Error Messages

```rust
// mu-cli/src/commands/query.rs
Err(e) if e.to_string().contains("Conflicting lock") => {
    eprintln!("ERROR: Database is locked by MU daemon (PID {})", get_daemon_pid()?);
    eprintln!();
    eprintln!("Options:");
    eprintln!("  1. Use daemon API: curl http://localhost:9120/query?q=...");
    eprintln!("  2. Stop daemon:    mu serve --stop");
    eprintln!("  3. Use MCP mode:   Configure Claude Code to use 'mu serve --mcp'");
    std::process::exit(1);
}
```

#### 4.2 Auto-Detect Best Mode

```rust
// mu-cli/src/commands/serve.rs
pub async fn run(port: u16, mcp: bool, ...) -> Result<()> {
    // Detect if running inside Claude Code / Cursor
    let in_ai_editor = std::env::var("CLAUDE_CODE").is_ok()
        || std::env::var("CURSOR_SESSION").is_ok();

    if in_ai_editor && !mcp {
        eprintln!("TIP: Detected AI editor. Consider using --mcp mode for best integration.");
    }

    // ...
}
```

#### 4.3 Status Command Enhancement

```rust
// mu serve --status output
pub fn print_status(status: &DaemonStatus) {
    println!("MU Daemon Status");
    println!("────────────────────────────────────");
    println!("  Mode:      {}", status.mode); // "http" | "mcp" | "stopped"
    println!("  PID:       {}", status.pid.unwrap_or_default());
    println!("  Port:      {}", status.port.unwrap_or(9120));
    println!("  Uptime:    {}", format_duration(status.uptime));
    println!("  DB Lock:   {}", if status.has_lock { "held" } else { "free" });
    println!();
    println!("  Nodes:     {}", status.node_count);
    println!("  Edges:     {}", status.edge_count);
    println!("  Embeddings:{}", status.embedding_count);
    println!();
    if status.mode == "stopped" {
        println!("Start daemon: mu serve");
        println!("Start MCP:    mu serve --mcp");
    }
}
```

### Acceptance Criteria

- [ ] Lock errors include helpful next steps
- [ ] `mu serve --status` shows comprehensive info
- [ ] Auto-detection tip for AI editors
- [ ] Add `mu doctor` command for diagnostics

---

## Epic 5: Quick Wins

**Priority:** P2 - Medium
**Effort:** 2-4 hours each

### 5.1 Version Command Enhancement

```rust
// mu --version output
mu 0.1.0
  mu-cli:        0.1.0
  mu-core:       0.1.0
  mu-daemon:     0.1.0
  mu-embeddings: 0.1.0

  DuckDB:        1.1.0
  Tree-sitter:   0.24.0
  Candle:        0.8.0

  Model:         mu-sigma-v2 (384 dims)
  Platform:      aarch64-apple-darwin
```

### 5.2 Bootstrap Progress Bar

```rust
// mu bootstrap output with progress
[1/4] Scanning files...          ████████████████████ 1028 files
[2/4] Parsing code...            ████████████████████ 874 modules
[3/4] Building graph...          ████████████████████ 10436 edges
[4/4] Generating embeddings...   ████████░░░░░░░░░░░░ 4812/9627 (50%)
```

### 5.3 MCP Tools Documentation

Add `mu mcp --list-tools` command:

```
MU MCP Tools
────────────────────────────────────
  mu/status   - Get daemon status
  mu/query    - Execute MUQL query
  mu/search   - Semantic search
  mu/deps     - Show dependencies
  mu/impact   - Show impact analysis
  mu/context  - Get smart context
  mu/build    - Rebuild database
```

### 5.4 Shell Completions

```bash
# Generate completions
mu completions bash > /etc/bash_completion.d/mu
mu completions zsh > ~/.zfunc/_mu
mu completions fish > ~/.config/fish/completions/mu.fish
```

---

## Testing Requirements

### Unit Tests

- [ ] Naming convention detection for all languages
- [ ] File hash computation
- [ ] WAL mode concurrent access

### Integration Tests

- [ ] CLI + daemon concurrent access
- [ ] Incremental embedding updates
- [ ] MCP server tool calls

### Manual Testing

- [ ] Test in Claude Code with MCP
- [ ] Test on fresh machine (no prior state)
- [ ] Test on large codebase (10k+ files)

---

## Rollout Plan

### Phase 1: Critical Fixes (Days 1-2)
- Epic 1: Database Concurrency (WAL mode)
- Epic 2: Language-Aware Vibe

### Phase 2: Performance (Days 3-4)
- Epic 3: Incremental Embeddings
- Epic 5.2: Progress Bar

### Phase 3: Polish (Days 5-6)
- Epic 4: UX Improvements
- Epic 5: Quick Wins

### Phase 4: Release (Day 7)
- Final testing
- Update README
- Tag v1.0.0
- Publish binary releases

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Lock errors in normal use | Common | Zero |
| `mu vibe` false positives | ~5000 (C# codebase) | < 50 |
| Re-embed single file | ~3 min | < 5 sec |
| User confusion (support issues) | Unknown | Track in v1.0 |

---

## Open Questions

1. **Should MCP mode auto-start daemon?** Currently separate commands.
2. **Should we add `mu init` for new projects?** Currently just `mu bootstrap`.
3. **Telemetry?** Anonymous usage stats for improvement prioritization.

---

## References

- [DuckDB WAL Mode](https://duckdb.org/docs/sql/pragmas#wal-mode)
- [Clap Shell Completions](https://docs.rs/clap_complete/latest/clap_complete/)
- [MCP Protocol Spec](https://modelcontextprotocol.io/)
