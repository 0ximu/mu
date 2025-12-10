# PRD: MU Rust Enhancements - Phase 2

## Overview

**Project:** MU Rust Enhancements - Scanner, Semantic Diff, Incremental Parsing
**Priority:** P1 (after Graph Reasoning ships)
**Effort:** 2-3 days (AI-assisted)
**Risk:** Low-Medium (additive, Python fallbacks maintained)

## Problem Statement

With mu-core now shipping parallel parsing, complexity analysis, and graph reasoning (petgraph), the remaining bottlenecks are:

1. **File Discovery** - Python's `os.walk`/`glob` is single-threaded and slow on large monorepos
2. **Change Detection** - `git diff` gives line numbers (noise), not semantic changes
3. **Daemon Latency** - Full reparse on every file change is wasteful

## Goals

| Goal | Metric | Target |
|------|--------|--------|
| File discovery speed | Time to scan 50k files | < 100ms (from ~2s) |
| Semantic diff quality | Change type accuracy | "Function added param" vs "line 47 changed" |
| Incremental update latency | Time to update after save | < 10ms (from ~500ms) |
| Native gitignore support | Pattern compliance | 100% `.gitignore` + `.muignore` |
| Zero API changes | Python interface | Backward compatible |

## Non-Goals

- Rewriting CLI in Rust (stays Python)
- Changing MCP server architecture
- Adding new language support (covered in separate PRD)
- WebAssembly build (future consideration)

---

## Architecture

### Current State (Post RUST_CORE)

```
mu compress .
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Python CLI                                          │
│  ┌──────────────────┐                               │
│  │ Scanner          │ ← SLOW: os.walk, no .gitignore│
│  │ (Python)         │                               │
│  └────────┬─────────┘                               │
│           │ paths: list[str]                        │
│           ▼                                         │
│  ┌─────────────────────────────────────────────┐   │
│  │  mu._core (Rust via PyO3)                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │ Parser   │→ │ Reducer  │→ │ Exporter │  │   │
│  │  │(parallel)│  │          │  │          │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  │   │
│  └─────────────────────────────────────────────┘   │
│           │                                         │
│           ▼ ParsedFile[]                           │
│  ┌──────────────────┐                               │
│  │ Diff Engine      │ ← NOISE: line-level diff      │
│  │ (Python)         │                               │
│  └──────────────────┘                               │
└─────────────────────────────────────────────────────┘
```

### Target State (Post This PRD)

```
mu compress .
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Python CLI                                          │
│           │                                          │
│           ▼                                          │
│  ┌─────────────────────────────────────────────┐   │
│  │  mu._core (Rust via PyO3)                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │ Scanner  │→ │ Parser   │→ │ Reducer  │  │   │
│  │  │(ignore)  │  │(parallel)│  │          │  │   │
│  │  │.gitignore│  │          │  │          │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  │   │
│  │       │                            │        │   │
│  │       │         ┌──────────────────┘        │   │
│  │       │         ▼                           │   │
│  │       │    ┌──────────┐  ┌──────────┐      │   │
│  │       │    │ Exporter │  │ Differ   │      │   │
│  │       │    │          │  │(semantic)│      │   │
│  │       │    └──────────┘  └──────────┘      │   │
│  │       │                                     │   │
│  │       ▼ (daemon mode)                       │   │
│  │  ┌──────────────────────────────────┐      │   │
│  │  │ Incremental Parser               │      │   │
│  │  │ (tree-sitter edit API)           │      │   │
│  │  │ - Reparse only changed regions   │      │   │
│  │  │ - Sub-10ms updates               │      │   │
│  │  └──────────────────────────────────┘      │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

## Feature Specifications

### Feature 1: Rust Scanner (`ignore` crate)

**Problem:** Python's file discovery is the new bottleneck now that parsing is fast.

**Solution:** Use the `ignore` crate (ripgrep's engine) for multi-threaded, gitignore-aware file walking.

**API Contract:**

```rust
#[pyclass]
pub struct ScanResult {
    #[pyo3(get)]
    pub files: Vec<FileInfo>,
    #[pyo3(get)]
    pub skipped_count: usize,
    #[pyo3(get)]
    pub error_count: usize,
    #[pyo3(get)]
    pub duration_ms: f64,
}

#[pyfunction]
#[pyo3(signature = (root_path, extensions=None, ignore_patterns=None, follow_symlinks=false))]
pub fn scan_directory(
    py: Python<'_>,
    root_path: &str,
    extensions: Option<Vec<String>>,      // ["py", "ts", "go"]
    ignore_patterns: Option<Vec<String>>, // Additional patterns beyond .gitignore
    follow_symlinks: bool,
) -> PyResult<ScanResult>;
```

**Behavior:**
- Respects `.gitignore` at all levels (root + nested)
- Respects `.muignore` (custom MU ignore file)
- Parallel directory traversal (rayon)
- Returns `FileInfo` with path, language, size, hash
- Filters by extension when provided

**Performance Target:**
| Repo Size | Current (Python) | Target (Rust) |
|-----------|-----------------|---------------|
| 1k files | 50ms | 5ms |
| 10k files | 500ms | 20ms |
| 50k files | 2s | 100ms |

---

### Feature 2: Semantic Diff Engine

**Problem:** Agents ask "what changed?" and get line numbers, not meaningful changes.

**Solution:** Compare two `ModuleDef` structs and output semantic change descriptions.

**API Contract:**

```rust
#[pyclass]
#[derive(Clone)]
pub struct SemanticChange {
    #[pyo3(get)]
    pub change_type: String,     // "added", "removed", "modified", "renamed"
    #[pyo3(get)]
    pub entity_type: String,     // "function", "class", "method", "import", "parameter"
    #[pyo3(get)]
    pub entity_name: String,     // "login", "AuthService.validate", etc.
    #[pyo3(get)]
    pub file_path: String,
    #[pyo3(get)]
    pub details: Option<String>, // "added parameter 'timeout: int'"
    #[pyo3(get)]
    pub old_signature: Option<String>,
    #[pyo3(get)]
    pub new_signature: Option<String>,
}

#[pyclass]
pub struct DiffResult {
    #[pyo3(get)]
    pub changes: Vec<SemanticChange>,
    #[pyo3(get)]
    pub summary: String,          // "3 functions added, 1 class modified"
    #[pyo3(get)]
    pub breaking_changes: Vec<SemanticChange>, // Removals, signature changes
}

#[pyfunction]
pub fn semantic_diff(
    base_modules: Vec<ModuleDef>,
    head_modules: Vec<ModuleDef>,
) -> PyResult<DiffResult>;

#[pyfunction]
pub fn semantic_diff_files(
    py: Python<'_>,
    base_path: &str,
    head_path: &str,
    language: &str,
) -> PyResult<DiffResult>;
```

**Change Detection Rules:**

| Entity | Added | Removed | Modified |
|--------|-------|---------|----------|
| Function | New name in head | Name in base, not head | Same name, different signature/body |
| Class | New class name | Class in base only | Methods/attributes changed |
| Method | New method in class | Method removed | Signature/decorators changed |
| Parameter | New param in function | Param removed | Type/default changed |
| Import | New import | Import removed | N/A |

**Output Example:**

```python
result = _core.semantic_diff(base_modules, head_modules)
for change in result.changes:
    print(f"{change.change_type}: {change.entity_type} {change.entity_name}")
    # "added: function validate_token"
    # "modified: method AuthService.login - added parameter 'timeout: int'"
    # "removed: class LegacyAuth"
```

---

### Feature 3: Incremental Parser

**Problem:** Daemon mode reparses entire files on every save. Wasteful for large files.

**Solution:** Use tree-sitter's incremental parsing API to only reparse changed regions.

**API Contract:**

```rust
#[pyclass]
pub struct IncrementalParser {
    // Internal: holds tree-sitter Tree + source
}

#[pymethods]
impl IncrementalParser {
    /// Create parser with initial source
    #[new]
    fn new(source: &str, language: &str, file_path: &str) -> PyResult<Self>;

    /// Apply an edit and get updated ModuleDef
    /// Returns only the changed portion's parse time
    fn apply_edit(
        &mut self,
        start_byte: usize,
        old_end_byte: usize,
        new_end_byte: usize,
        new_text: &str,
    ) -> PyResult<IncrementalParseResult>;

    /// Get current ModuleDef
    fn get_module(&self) -> PyResult<ModuleDef>;

    /// Get current source
    fn get_source(&self) -> String;
}

#[pyclass]
pub struct IncrementalParseResult {
    #[pyo3(get)]
    pub module: ModuleDef,
    #[pyo3(get)]
    pub parse_time_ms: f64,
    #[pyo3(get)]
    pub changed_ranges: Vec<(usize, usize)>, // Byte ranges that were reparsed
}
```

**Usage in Daemon:**

```python
# Initial parse
parser = _core.IncrementalParser(source, "python", "auth.py")

# On file change event (from watchdog)
def on_file_changed(path, old_source, new_source, edit_info):
    result = parser.apply_edit(
        edit_info.start_byte,
        edit_info.old_end_byte,
        edit_info.new_end_byte,
        new_source[edit_info.start_byte:edit_info.new_end_byte]
    )
    # result.parse_time_ms typically < 5ms
    update_graph(result.module)
```

**Performance Target:**
| Edit Type | Full Reparse | Incremental |
|-----------|-------------|-------------|
| Add line | 50-200ms | 1-5ms |
| Modify function | 50-200ms | 2-10ms |
| Large refactor | 50-200ms | 20-50ms |

---

## Implementation Phases

### Phase 1: Rust Scanner (Day 1)

**Objective:** Replace Python file discovery with `ignore` crate.

**Files to Create:**
- `mu-core/src/scanner.rs` - Core scanning logic
- `mu-core/src/scanner/walker.rs` - Parallel directory walker
- `mu-core/src/scanner/patterns.rs` - Ignore pattern handling

**Files to Modify:**
- `mu-core/Cargo.toml` - Add `ignore = "0.4"`
- `mu-core/src/lib.rs` - Export scanner module
- `src/mu/scanner/__init__.py` - Delegate to Rust or fallback
- `src/mu/_core.pyi` - Add type stubs

**Dependencies:** None (can be developed independently)

#### Phase 1 Agent Checklist

```markdown
## Phase 1: Rust Scanner - Implementation Checklist

### Setup
- [ ] Add `ignore = "0.4"` to `mu-core/Cargo.toml`
- [ ] Create `mu-core/src/scanner.rs` module structure
- [ ] Register module in `mu-core/src/lib.rs`

### Core Implementation
- [ ] Implement `FileInfo` struct (path, language, size, hash)
- [ ] Implement `ScanResult` struct with PyO3 bindings
- [ ] Implement `scan_directory()` function
- [ ] Add `.gitignore` support (automatic via ignore crate)
- [ ] Add `.muignore` support (custom ignore file)
- [ ] Add extension filtering
- [ ] Add parallel traversal with rayon
- [ ] Release GIL during scanning (`py.allow_threads`)

### Python Integration
- [ ] Update `src/mu/scanner/__init__.py` to use Rust scanner
- [ ] Add fallback to Python scanner if Rust unavailable
- [ ] Add `MU_USE_RUST_SCANNER=1/0` environment variable
- [ ] Update `src/mu/_core.pyi` with new type stubs

### Testing
- [ ] Unit tests in `mu-core/src/scanner.rs` (Rust)
- [ ] Integration test: scan MU repo, verify file count
- [ ] Integration test: verify .gitignore respected
- [ ] Integration test: verify extension filtering
- [ ] Benchmark: compare Python vs Rust on 10k+ file repo

### Quality Gates
- [ ] `cargo test` passes
- [ ] `cargo clippy` passes
- [ ] `maturin develop` succeeds
- [ ] `pytest tests/unit/test_scanner.py` passes
- [ ] `ruff check src/mu/scanner/` passes
- [ ] `mypy src/mu/scanner/` passes

### Documentation
- [ ] Add docstrings to Rust functions
- [ ] Update `mu-core/CLAUDE.md` with scanner usage
- [ ] Add example usage to `src/mu/scanner/__init__.py`
```

---

### Phase 2: Semantic Diff Engine (Day 1-2)

**Objective:** Compare ModuleDef structs and output meaningful changes.

**Files to Create:**
- `mu-core/src/differ.rs` - Core diff logic
- `mu-core/src/differ/comparator.rs` - Entity comparison
- `mu-core/src/differ/changes.rs` - Change type definitions

**Files to Modify:**
- `mu-core/src/lib.rs` - Export differ module
- `src/mu/diff/__init__.py` - Delegate to Rust
- `src/mu/_core.pyi` - Add type stubs

**Dependencies:** Requires existing `types.rs` (ModuleDef, FunctionDef, etc.)

#### Phase 2 Agent Checklist

```markdown
## Phase 2: Semantic Diff Engine - Implementation Checklist

### Setup
- [ ] Create `mu-core/src/differ.rs` module structure
- [ ] Create `mu-core/src/differ/changes.rs` for change types
- [ ] Create `mu-core/src/differ/comparator.rs` for comparison logic
- [ ] Register module in `mu-core/src/lib.rs`

### Core Implementation
- [ ] Implement `SemanticChange` struct with PyO3 bindings
- [ ] Implement `DiffResult` struct with summary generation
- [ ] Implement function comparison (name, params, return type)
- [ ] Implement class comparison (name, bases, methods, attributes)
- [ ] Implement method comparison (within class context)
- [ ] Implement import comparison
- [ ] Implement parameter comparison (type, default value)
- [ ] Identify breaking changes (removals, signature changes)
- [ ] Generate human-readable change descriptions

### API Functions
- [ ] Implement `semantic_diff(base: Vec<ModuleDef>, head: Vec<ModuleDef>)`
- [ ] Implement `semantic_diff_files(base_path, head_path, language)`
- [ ] Implement `diff_single_module(base: ModuleDef, head: ModuleDef)`

### Python Integration
- [ ] Update `src/mu/diff/__init__.py` to use Rust differ
- [ ] Add fallback to Python differ if Rust unavailable
- [ ] Update `src/mu/_core.pyi` with new type stubs
- [ ] Integrate with `mu diff` CLI command

### Testing
- [ ] Unit tests for function diff (add, remove, modify)
- [ ] Unit tests for class diff (add, remove, modify methods)
- [ ] Unit tests for parameter changes
- [ ] Unit tests for breaking change detection
- [ ] Integration test: diff two git commits
- [ ] Integration test: verify change descriptions are accurate

### Quality Gates
- [ ] `cargo test` passes
- [ ] `cargo clippy` passes
- [ ] `maturin develop` succeeds
- [ ] `pytest tests/unit/test_diff.py` passes
- [ ] `ruff check src/mu/diff/` passes
- [ ] `mypy src/mu/diff/` passes

### Documentation
- [ ] Add docstrings to Rust functions
- [ ] Document change types in `mu-core/CLAUDE.md`
- [ ] Add example output to PRD
```

---

### Phase 3: Incremental Parser (Day 2-3)

**Objective:** Enable sub-10ms updates in daemon mode.

**Files to Create:**
- `mu-core/src/incremental.rs` - Incremental parser wrapper

**Files to Modify:**
- `mu-core/src/lib.rs` - Export incremental module
- `src/mu/daemon/watcher.py` - Use incremental parser
- `src/mu/_core.pyi` - Add type stubs

**Dependencies:** Requires Phase 1 for efficient file watching context.

#### Phase 3 Agent Checklist

```markdown
## Phase 3: Incremental Parser - Implementation Checklist

### Setup
- [ ] Create `mu-core/src/incremental.rs`
- [ ] Register module in `mu-core/src/lib.rs`
- [ ] Review tree-sitter `Tree::edit()` API

### Core Implementation
- [ ] Implement `IncrementalParser` pyclass with internal Tree state
- [ ] Implement `IncrementalParser::new(source, language, path)`
- [ ] Implement `IncrementalParser::apply_edit(start, old_end, new_end, new_text)`
- [ ] Implement `IncrementalParser::get_module()` for current state
- [ ] Implement `IncrementalParser::get_source()` for current source
- [ ] Implement `IncrementalParseResult` with timing info
- [ ] Track changed byte ranges for targeted re-extraction

### Edit Application
- [ ] Convert Python edit info to tree-sitter `InputEdit`
- [ ] Call `tree.edit(&input_edit)` to update tree
- [ ] Reparse with `parser.parse(new_source, Some(&old_tree))`
- [ ] Extract only changed nodes (optimization)
- [ ] Rebuild ModuleDef from updated tree

### Python Integration
- [ ] Add `IncrementalParser` to `src/mu/_core.pyi`
- [ ] Update daemon watcher to use incremental parser
- [ ] Maintain parser instances per-file in daemon
- [ ] Handle file deletion/creation (new parser instance)

### Testing
- [ ] Unit test: create parser, verify initial ModuleDef
- [ ] Unit test: apply single line edit, verify update
- [ ] Unit test: apply function addition, verify new function
- [ ] Unit test: apply function removal, verify removal
- [ ] Benchmark: compare full reparse vs incremental
- [ ] Integration test: daemon receives edits, graph updates

### Quality Gates
- [ ] `cargo test` passes
- [ ] `cargo clippy` passes
- [ ] `maturin develop` succeeds
- [ ] `pytest tests/unit/test_incremental.py` passes
- [ ] `ruff check src/mu/daemon/` passes
- [ ] `mypy src/mu/daemon/` passes

### Documentation
- [ ] Add docstrings explaining edit coordinate system
- [ ] Document limitations (e.g., no cross-file incremental)
- [ ] Update daemon CLAUDE.md with incremental usage
```

---

### Phase 4: Integration & Polish (Day 3)

**Objective:** Wire everything together, ensure quality.

#### Phase 4 Agent Checklist

```markdown
## Phase 4: Integration & Polish - Checklist

### End-to-End Integration
- [ ] `mu scan` uses Rust scanner
- [ ] `mu compress` uses Rust scanner → Rust parser pipeline
- [ ] `mu diff` uses Rust semantic differ
- [ ] `mu daemon` uses incremental parser
- [ ] All commands work with `MU_USE_RUST=0` fallback

### Performance Validation
- [ ] Benchmark scanner on large repo (target: <100ms for 50k files)
- [ ] Benchmark full pipeline (target: <3s for 10k files)
- [ ] Benchmark incremental update (target: <10ms)
- [ ] Memory profile (target: <500MB for 100k file repo)

### MCP Tool Updates
- [ ] `mu_context` benefits from faster scanning
- [ ] `mu_deps` unaffected (uses graph)
- [ ] Add `mu_diff` MCP tool using semantic differ

### CLI Updates
- [ ] `mu scan --stats` shows Rust vs Python performance
- [ ] `mu diff --semantic` uses new semantic differ
- [ ] Add `--no-rust` flag for fallback

### CI/CD
- [ ] All tests pass on Linux/macOS/Windows
- [ ] Wheels build successfully
- [ ] Type stubs are complete

### Documentation
- [ ] Update main CLAUDE.md with new features
- [ ] Update `mu describe` output
- [ ] Add changelog entry

### Final Quality Gates
- [ ] `pytest` - all tests pass
- [ ] `mypy src/mu` - no type errors
- [ ] `ruff check src/` - no lint errors
- [ ] `cargo test` - all Rust tests pass
- [ ] `cargo clippy` - no warnings
- [ ] `maturin build --release` - wheels build
```

---

## Cargo.toml Updates

```toml
[dependencies]
# Existing...
pyo3 = { version = "0.22", features = ["extension-module", "abi3-py311"] }
rayon = "1.10"
petgraph = "0.6"
tree-sitter = "0.24"
# ... tree-sitter grammars

# New for this PRD
ignore = "0.4"          # Fast parallel file walking with gitignore support
```

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| `ignore` crate API changes | Low | Low | Pin version, simple wrapper |
| Incremental parse edge cases | Medium | Medium | Extensive testing, full reparse fallback |
| Semantic diff false positives | Medium | Low | Conservative change detection, user feedback |
| Platform-specific scanning issues | Low | Medium | CI on Linux/macOS/Windows |
| Memory leaks in incremental parser | Low | High | Careful lifetime management, periodic full rebuild |

---

## Success Metrics

| Metric | Before | Target | Measured |
|--------|--------|--------|----------|
| Scan 50k files | ~2s | < 100ms | |
| `mu compress` on MU repo | ~1.5s | < 800ms | |
| Diff between commits | Line-level only | Semantic changes | |
| Daemon update latency | ~500ms | < 10ms | |
| Memory (incremental mode) | N/A | < 50MB overhead | |

---

## Open Questions

1. **Semantic diff granularity** - Should we track statement-level changes within function bodies?
   - **Recommendation:** No, start with signature-level. Add body diff later if needed.

2. **Incremental parser cache** - Should we persist parser state to disk for faster cold start?
   - **Recommendation:** No, in-memory only. Daemon startup can do full parse.

3. **Graph visualization export** - Should this PRD include Mermaid/Graphviz export?
   - **Recommendation:** Separate small PRD, ~2-3 hours of work.

---

## References

- [ignore crate docs](https://docs.rs/ignore/latest/ignore/)
- [tree-sitter incremental parsing](https://tree-sitter.github.io/tree-sitter/using-parsers#editing)
- RUST_CORE PRD: `docs/prd/RUST_CORE.md`
- GRAPH_REASONING PRD: `docs/prd/GRAPH_REASONING.md`
