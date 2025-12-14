# MU v1.0 Launch Polish - Task Breakdown

**PRD:** [MU_V1_LAUNCH_POLISH.md](./MU_V1_LAUNCH_POLISH.md)
**Status:** Ready for Development
**Total Effort:** ~7 days

---

## Epic 1: Database Concurrency Fix [P0]

### Task 1.1: Enable WAL Mode
- **File:** `mu-daemon/src/storage/mubase.rs`
- **Effort:** 30 min
- **Status:** [ ] Not Started

```rust
// In MUbase::open()
conn.execute("PRAGMA journal_mode=WAL", [])?;
conn.execute("PRAGMA busy_timeout=5000", [])?;
```

**Acceptance:**
- [ ] WAL mode enabled on database open
- [ ] Existing tests pass
- [ ] Manual test: `mu query` works while `mu serve` running

---

### Task 1.2: Add Concurrent Access Integration Test
- **File:** `mu-daemon/tests/concurrent_access.rs` (new)
- **Effort:** 1 hour
- **Status:** [ ] Not Started

```rust
#[tokio::test]
async fn test_concurrent_read_write() {
    // 1. Open DB in daemon mode (write)
    // 2. Open DB in CLI mode (read)
    // 3. Execute queries concurrently
    // 4. Verify no lock errors
}
```

---

### Task 1.3: Improve Lock Error Message
- **File:** `mu-cli/src/commands/daemon_client.rs`
- **Effort:** 30 min
- **Status:** [ ] Not Started

Add helpful error message when lock conflict detected:
```
ERROR: Database locked by MU daemon (PID 12345)

Options:
  1. Query via daemon: mu query --daemon "SELECT..."
  2. Stop daemon:      mu serve --stop
```

---

## Epic 2: Language-Aware Vibe Checks [P1]

### Task 2.1: Add Naming Convention Types
- **File:** `mu-cli/src/commands/vibes/conventions.rs` (new)
- **Effort:** 1 hour
- **Status:** [ ] Not Started

```rust
pub enum NamingConvention {
    SnakeCase,
    PascalCase,
    CamelCase,
    ScreamingSnakeCase,
}

pub fn convention_for(language: &str, entity: &str) -> NamingConvention;
pub fn check_convention(name: &str, conv: NamingConvention) -> Option<String>;
```

---

### Task 2.2: Add Case Conversion Utilities
- **File:** `mu-cli/src/commands/vibes/conventions.rs`
- **Effort:** 1 hour
- **Status:** [ ] Not Started

```rust
pub fn is_snake_case(s: &str) -> bool;
pub fn is_pascal_case(s: &str) -> bool;
pub fn is_camel_case(s: &str) -> bool;
pub fn to_snake_case(s: &str) -> String;
pub fn to_pascal_case(s: &str) -> String;
pub fn to_camel_case(s: &str) -> String;
```

---

### Task 2.3: Update Vibe Command to Use Conventions
- **File:** `mu-cli/src/commands/vibes/vibe.rs`
- **Effort:** 2 hours
- **Status:** [ ] Not Started

- Get language from file extension or DB
- Apply correct convention per language
- Add `--convention` flag for override

---

### Task 2.4: Add Convention Unit Tests
- **File:** `mu-cli/src/commands/vibes/conventions.rs`
- **Effort:** 1 hour
- **Status:** [ ] Not Started

```rust
#[test]
fn test_csharp_class_pascal_case() {
    assert!(is_valid_name("TransactionService", "csharp", "class"));
    assert!(!is_valid_name("transaction_service", "csharp", "class"));
}

#[test]
fn test_python_function_snake_case() {
    assert!(is_valid_name("get_transaction", "python", "function"));
    assert!(!is_valid_name("getTransaction", "python", "function"));
}
```

---

## Epic 3: Incremental Embedding Updates [P1]

### Task 3.1: Add File Hash Table to Schema
- **File:** `mu-daemon/src/storage/schema.rs`
- **Effort:** 30 min
- **Status:** [ ] Not Started

```sql
CREATE TABLE IF NOT EXISTS file_hashes (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    embedded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### Task 3.2: Implement File Hash Functions
- **File:** `mu-daemon/src/storage/mubase.rs`
- **Effort:** 1 hour
- **Status:** [ ] Not Started

```rust
impl MUbase {
    pub fn get_file_hash(&self, path: &str) -> Result<Option<String>>;
    pub fn set_file_hash(&self, path: &str, hash: &str) -> Result<()>;
    pub fn get_stale_files(&self, current_hashes: &HashMap<String, String>) -> Result<Vec<String>>;
}
```

---

### Task 3.3: Add Content Hash Computation
- **File:** `mu-cli/src/commands/bootstrap.rs`
- **Effort:** 30 min
- **Status:** [ ] Not Started

```rust
use blake3;

fn compute_file_hash(path: &Path) -> Result<String> {
    let content = std::fs::read(path)?;
    Ok(blake3::hash(&content).to_hex().to_string())
}
```

---

### Task 3.4: Implement Incremental Embed Command
- **File:** `mu-cli/src/commands/embed.rs` (new)
- **Effort:** 3 hours
- **Status:** [ ] Not Started

```rust
pub async fn run_incremental(path: &str, force: bool) -> Result<()> {
    // 1. Scan current file hashes
    // 2. Compare with stored hashes
    // 3. Re-embed only changed files
    // 4. Update hash table
}
```

---

### Task 3.5: Add Embed Status Command
- **File:** `mu-cli/src/commands/embed.rs`
- **Effort:** 1 hour
- **Status:** [ ] Not Started

```
$ mu embed --status

Embedding Status
────────────────────────────────────
  Total files:     874
  Embedded:        874
  Stale:           3
  Missing:         0

Stale files:
  - src/services/TransactionService.cs (modified 2 min ago)
  - src/services/CustomerService.cs (modified 5 min ago)
  - tests/ServiceTests.cs (modified 1 hour ago)

Run 'mu embed --incremental' to update.
```

---

### Task 3.6: Wire File Watcher to Incremental Embed
- **File:** `mu-daemon/src/watcher/mod.rs`
- **Effort:** 2 hours
- **Status:** [ ] Not Started

On file change:
1. Re-parse file
2. Update nodes in DB
3. Re-compute embedding (if enabled)
4. Update file hash

---

## Epic 4: UX Improvements [P2]

### Task 4.1: Add mu doctor Command
- **File:** `mu-cli/src/commands/doctor.rs` (new)
- **Effort:** 2 hours
- **Status:** [ ] Not Started

```
$ mu doctor

MU Health Check
────────────────────────────────────
[OK] Database exists: .mu/mubase (45 MB)
[OK] Schema version: 3 (current)
[OK] Node count: 7695
[OK] Edge count: 10436
[OK] Embeddings: 9627 (100%)
[!!] Daemon: not running
[OK] MCP config: found in .claude.json

Recommendations:
  - Start daemon for better performance: mu serve
```

---

### Task 4.2: Enhance Version Output
- **File:** `mu-cli/src/main.rs`
- **Effort:** 30 min
- **Status:** [ ] Not Started

Add `--verbose` flag to version:
```
$ mu --version --verbose
mu 0.1.0
  mu-cli:        0.1.0
  mu-core:       0.1.0
  mu-daemon:     0.1.0
  mu-embeddings: 0.1.0
  Platform:      aarch64-apple-darwin
```

---

### Task 4.3: Add Progress Bar to Bootstrap
- **File:** `mu-cli/src/commands/bootstrap.rs`
- **Effort:** 1 hour
- **Status:** [ ] Not Started
- **Dependency:** Add `indicatif` crate

```rust
use indicatif::{ProgressBar, ProgressStyle};

let pb = ProgressBar::new(total_files);
pb.set_style(ProgressStyle::default_bar()
    .template("[{elapsed_precise}] {bar:40.cyan/blue} {pos}/{len} {msg}")?);
```

---

### Task 4.4: Add Shell Completions
- **File:** `mu-cli/src/commands/completions.rs` (new)
- **Effort:** 1 hour
- **Status:** [ ] Not Started
- **Dependency:** Add `clap_complete` crate

```rust
use clap_complete::{generate, shells::*};

pub fn run(shell: &str) -> Result<()> {
    let mut cmd = Cli::command();
    match shell {
        "bash" => generate(Bash, &mut cmd, "mu", &mut std::io::stdout()),
        "zsh" => generate(Zsh, &mut cmd, "mu", &mut std::io::stdout()),
        "fish" => generate(Fish, &mut cmd, "mu", &mut std::io::stdout()),
        _ => return Err(anyhow!("Unknown shell: {}", shell)),
    }
    Ok(())
}
```

---

### Task 4.5: Add MCP Tools List Command
- **File:** `mu-cli/src/commands/serve.rs`
- **Effort:** 30 min
- **Status:** [ ] Not Started

```
$ mu serve --list-tools

MU MCP Tools
────────────────────────────────────
  mu/status    Get project status and stats
  mu/query     Execute MUQL query
  mu/search    Semantic code search
  mu/deps      Show node dependencies
  mu/impact    Show change impact analysis
  mu/context   Get smart context for questions
  mu/build     Rebuild database
```

---

## Epic 5: Testing & Release [P2]

### Task 5.1: Add CI Test for Concurrent Access
- **File:** `.github/workflows/test.yml`
- **Effort:** 30 min
- **Status:** [ ] Not Started

Add step to run concurrent access tests.

---

### Task 5.2: Test on Large Codebase
- **Effort:** 2 hours
- **Status:** [ ] Not Started

Manual test on:
- [ ] Gateway codebase (7k nodes)
- [ ] Kubernetes repo (~50k files)
- [ ] Fresh machine (no prior state)

---

### Task 5.3: Update README for v1.0
- **File:** `README.md`
- **Effort:** 1 hour
- **Status:** [ ] Not Started

- [ ] Update installation instructions
- [ ] Add quick start section
- [ ] Document MCP integration
- [ ] Add troubleshooting section

---

### Task 5.4: Create Release Binaries
- **File:** `.github/workflows/release.yml`
- **Effort:** 2 hours
- **Status:** [ ] Not Started

Build for:
- [ ] macOS ARM64 (apple-darwin)
- [ ] macOS x64 (apple-darwin)
- [ ] Linux x64 (unknown-linux-gnu)
- [ ] Linux ARM64 (unknown-linux-gnu)
- [ ] Windows x64 (pc-windows-msvc)

---

## Summary

| Epic | Tasks | Total Effort |
|------|-------|--------------|
| 1. DB Concurrency | 3 | 2 hours |
| 2. Language Vibe | 4 | 5 hours |
| 3. Incremental Embed | 6 | 8 hours |
| 4. UX Improvements | 5 | 5 hours |
| 5. Testing & Release | 4 | 6 hours |
| **Total** | **22** | **~26 hours** |

---

## Suggested Order

1. Task 1.1 (WAL mode) - Unblocks everything
2. Task 2.1-2.4 (Vibe conventions) - Quick win
3. Task 4.3 (Progress bar) - UX improvement
4. Task 3.1-3.6 (Incremental embed) - Performance
5. Task 4.1-4.5 (UX polish) - Final touches
6. Task 5.1-5.4 (Release) - Ship it
