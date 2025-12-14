# PRD: MU v0.1.0-alpha.1 Polish & Release

**Author:** Claude + Yavor
**Date:** 2024-12-14
**Status:** Ready for Implementation
**Priority:** Ship Tonight

---

## Executive Summary

MU is a semantic code intelligence CLI tool written in Rust. Core functionality is complete and working (372 tests pass). This PRD covers the polish needed to make it a **10/10 alpha release**.

## Current State

### What Works
- `mu bootstrap` - Initialize and build code graph
- `mu search/grok` - Semantic search with embedded ML model (MU-SIGMA-V2)
- `mu deps/usedby/impact/ancestors` - Graph analysis
- `mu diff` - Semantic git diffs with breaking change detection
- `mu query` - MUQL query language (SQL-like + terse syntax)
- `mu compress/omg` - LLM-optimized output (92-98% compression)
- `mu yolo/sus/wtf/vibe/zen` - Fun analysis commands
- `mu patterns` - Code pattern detection
- `mu export` - Mermaid, D2, JSON, Cytoscape formats
- Shell completions working
- Install script ready

### Stats
- **372 tests pass** across 4 crates
- **7695 nodes, 12789 edges** on Gateway codebase
- **140MB binary** (includes embedded BERT model)
- **17 clippy warnings** remaining (non-critical)

---

## Issues Found During Testing

### P0 - Must Fix

1. **Ambiguous node suggestions unsorted**
   - When multiple nodes match, suggestions are in arbitrary order
   - Should sort by: exact match > class > module > function > relevance
   - File: `mu-cli/src/commands/deps.rs` and `mu-cli/src/commands/graph.rs`

2. **Release workflow uses old CI**
   - Tag checkout gets workflow from that commit, not latest
   - Need to merge CI changes to develop BEFORE tagging
   - Current tag `v0.1.0-alpha.1` is broken - delete and re-tag

### P1 - Should Fix

3. **17 Clippy warnings**
   - 3 in mu-daemon (dead code)
   - 14 in mu-cli (various)
   - Run: `cargo clippy 2>&1 | grep warning`

4. **Config file schema mismatch**
   - `.murc.toml` was using `languages = "auto"` (string)
   - Should be `languages = ["auto"]` (array) or omitted
   - Already fixed but validate schema docs

5. **No progress indicators for slow operations**
   - `mu bootstrap` on large codebases is silent
   - `mu embed` shows progress but others don't
   - Add indicatif progress bars

### P2 - Nice to Have

6. **Command help lacks examples**
   - `mu deps --help` shows flags but no usage examples
   - Add examples section to each command

7. **`mu doctor --fix` doesn't exist**
   - Doctor detects issues but can't fix them
   - Add auto-repair for common issues (stale cache, missing embeddings)

8. **No quickstart in `mu --help`**
   - First-time users don't know where to start
   - Add "Quick Start: Run `mu bootstrap` then `mu status`"

---

## Implementation Plan

### Phase 1: Fix Release Pipeline (30 min)

```bash
# 1. Delete broken tag
git tag -d v0.1.0-alpha.1
git push origin :refs/tags/v0.1.0-alpha.1

# 2. Ensure CI changes are on develop (already merged via PR #24)

# 3. Re-tag on develop HEAD
git checkout develop
git pull
git tag -a v0.1.0-alpha.1 -m "MU v0.1.0-alpha.1"
git push origin v0.1.0-alpha.1
```

### Phase 2: Code Polish (1-2 hours)

#### 2.1 Sort Ambiguous Node Suggestions
File: `mu-cli/src/commands/graph.rs`

```rust
// In resolve_node_id or similar function
// Sort matches by type priority and then by name
matches.sort_by(|a, b| {
    let priority = |n: &Node| match n.node_type.as_str() {
        "class" => 0,
        "module" => 1,
        "function" => 2,
        _ => 3,
    };
    priority(a).cmp(&priority(b)).then(a.name.cmp(&b.name))
});
```

#### 2.2 Fix Remaining Clippy Warnings
```bash
cargo clippy --fix --allow-dirty
# Manual fixes for the rest
```

Key warnings to fix:
- `field 'path' is never read` in mu-daemon/src/storage/mubase.rs
- `field 'mu' is never read` in mu-cli/src/config.rs
- Various style warnings

#### 2.3 Add Progress Bars
File: `mu-cli/src/commands/bootstrap.rs`

```rust
use indicatif::{ProgressBar, ProgressStyle};

let pb = ProgressBar::new(file_count as u64);
pb.set_style(ProgressStyle::default_bar()
    .template("{spinner:.green} [{bar:40.cyan/blue}] {pos}/{len} {msg}")
    .progress_chars("#>-"));

// In loop:
pb.set_message(format!("Parsing {}", file_name));
pb.inc(1);

pb.finish_with_message("Done!");
```

### Phase 3: UX Polish (1 hour)

#### 3.1 Add Examples to Help
File: `mu-cli/src/main.rs`

```rust
#[derive(Parser)]
#[command(
    name = "mu",
    about = "Semantic code intelligence for AI-native development",
    after_help = "QUICK START:\n  mu bootstrap    # Initialize code graph\n  mu status       # Check status\n  mu search \"auth\" # Find auth-related code"
)]
```

#### 3.2 Improve First-Run Experience
- Detect if `.mu/` doesn't exist
- Suggest `mu bootstrap` automatically
- Show helpful message, not cryptic error

---

## Testing Checklist

Before release:
- [ ] `cargo test` - all 372 tests pass
- [ ] `cargo clippy` - 0 warnings (or document exceptions)
- [ ] `cargo build --release` - builds successfully
- [ ] Test on fresh clone (no .mu directory)
- [ ] Test `mu bootstrap` on MU's own codebase
- [ ] Test `mu search "parser"`
- [ ] Test `mu deps MuSigmaModel`
- [ ] Test `mu impact` with `--depth` flag
- [ ] Test ambiguous node resolution shows sorted suggestions
- [ ] Verify install script works: `./scripts/install.sh`
- [ ] Verify shell completions: `mu completions bash`

---

## Release Checklist

1. [ ] All tests pass
2. [ ] Clippy clean (or warnings documented)
3. [ ] CHANGELOG.md updated
4. [ ] Version in Cargo.toml is correct
5. [ ] CI workflow is Rust-based (not Python)
6. [ ] Tag created on develop HEAD
7. [ ] Release workflow completes successfully
8. [ ] Binaries available for Linux/macOS/Windows
9. [ ] Install script tested

---

## File Locations

| What | Where |
|------|-------|
| CLI entry point | `mu-cli/src/main.rs` |
| Commands | `mu-cli/src/commands/*.rs` |
| Graph operations | `mu-cli/src/commands/graph.rs` |
| Node resolution | `mu-cli/src/commands/deps.rs` |
| Config | `mu-cli/src/config.rs` |
| Storage | `mu-daemon/src/storage/mubase.rs` |
| CI workflow | `.github/workflows/ci.yml` |
| Release workflow | `.github/workflows/release.yml` |
| Install script | `scripts/install.sh` |

---

## Success Criteria

**10/10 Alpha means:**
1. Zero crashes on happy path
2. Helpful error messages (not stack traces)
3. Progress feedback for slow operations
4. Sorted, relevant suggestions for ambiguous inputs
5. Works out-of-the-box on Linux/macOS/Windows
6. Documentation matches actual behavior

---

## Notes for Next Session

- Repo: `/Users/imu/Dev/work/mu`
- Remote: `https://github.com/0ximu/mu`
- Branch: `develop` (default)
- Current broken tag: `v0.1.0-alpha.1` (needs delete + re-tag)
- PR #24 already merged with CI fixes
- The user is Yavor, creator of MU
- Vibe: ship fast but ship quality
