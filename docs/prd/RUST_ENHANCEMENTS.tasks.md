# RUST_ENHANCEMENTS Implementation Tasks

## Overview

This file contains agent-interactive checklists for implementing the Rust Enhancements PRD.
Each phase has a checklist that should be completed in order. Mark items as complete by changing `[ ]` to `[x]`.

**PRD Reference:** `docs/prd/RUST_ENHANCEMENTS.md`

---

## Phase 1: Rust Scanner (`ignore` crate)

**Estimated Time:** 4-6 hours
**Dependencies:** None
**Goal:** Replace Python file discovery with multi-threaded, gitignore-aware Rust scanner.

### Setup

- [x] Add `ignore = "0.4"` to `mu-core/Cargo.toml`
- [x] Create `mu-core/src/scanner.rs` with module structure
- [x] Add `pub mod scanner;` to `mu-core/src/lib.rs`
- [x] Run `cargo check` to verify no compile errors

### Core Types

- [x] Define `FileInfo` struct:
  ```rust
  #[pyclass]
  pub struct ScannedFile {
      pub path: String,
      pub language: String,
      pub size_bytes: u64,
      pub hash: Option<String>,
      pub lines: u32,
  }
  ```
- [x] Define `ScanResult` struct:
  ```rust
  #[pyclass]
  pub struct ScanResult {
      pub files: Vec<ScannedFile>,
      pub skipped_count: usize,
      pub error_count: usize,
      pub duration_ms: f64,
  }
  ```
- [x] Add `#[pymethods]` impl for both structs (getters, `to_dict()`)

### Scanner Implementation

- [x] Implement `build_walker(root: &str, extensions: Option<Vec<String>>)`:
  - Use `ignore::WalkBuilder::new(root)`
  - Add `.hidden(false)` to include dotfiles if needed
  - Add `.git_ignore(true)` for .gitignore support
  - Add `.add_custom_ignore_filename(".muignore")`
- [x] Implement `detect_language(path: &Path) -> String`:
  - Map extensions: `.py` → "python", `.ts/.tsx` → "typescript", etc.
  - Use existing language detection logic from `types.rs`
- [x] Implement parallel collection with rayon:
  ```rust
  files.par_iter().for_each(|path| { ... })
  ```
- [x] Calculate file hash (optional, for cache invalidation) - using xxHash3
- [x] Track timing with `std::time::Instant`

### PyO3 Function

- [x] Implement `scan_directory()` function:
  ```rust
  #[pyfunction]
  #[pyo3(signature = (root_path, extensions=None, ignore_patterns=None, follow_symlinks=false, compute_hashes=false, count_lines_flag=false))]
  pub fn scan_directory(
      py: Python<'_>,
      root_path: &str,
      extensions: Option<Vec<String>>,
      ignore_patterns: Option<Vec<String>>,
      follow_symlinks: bool,
      compute_hashes: bool,
      count_lines_flag: bool,
  ) -> PyResult<ScanResult>
  ```
- [x] Release GIL during scanning: `py.allow_threads(|| { ... })`
- [x] Register function in `lib.rs`: `m.add_function(wrap_pyfunction!(scan_directory, m)?)?;`

### Python Integration

- [x] Update `src/mu/scanner/__init__.py`:
  ```python
  def scan_codebase_auto(root: Path, config: MUConfig) -> ScanResult:
      if _USE_RUST_SCANNER and root.is_dir():
          return _scan_codebase_rust(root, config)
      return scan_codebase(root, config)
  ```
- [x] Add `MU_USE_RUST_SCANNER` environment variable check
- [x] Preserve existing Python scanner as fallback

### Type Stubs

- [x] Add to `src/mu/_core.pyi`:
  ```python
  class ScannedFile:
      path: str
      language: str
      size_bytes: int
      hash: str | None
      lines: int
      def to_dict(self) -> dict[str, object]: ...

  class ScanResult:
      files: list[ScannedFile]
      skipped_count: int
      error_count: int
      duration_ms: float
      def to_dict(self) -> dict[str, object]: ...

  def scan_directory(
      root_path: str,
      extensions: list[str] | None = None,
      ignore_patterns: list[str] | None = None,
      follow_symlinks: bool = False,
      compute_hashes: bool = False,
      count_lines_flag: bool = False,
  ) -> ScanResult: ...
  ```

### Testing

- [x] Rust unit tests in `mu-core/src/scanner.rs`:
  - Test basic directory scan
  - Test extension filtering
  - Test .gitignore respect
  - Test .muignore respect
  - Test empty directory
  - Test non-existent path (error handling)
- [x] Python integration tests in `tests/unit/test_scanner.py`:
  - Test scan returns correct file count
  - Test scan respects .gitignore
  - Test extension filtering works
  - Test fallback to Python when Rust unavailable
- [x] Benchmark test comparing Python vs Rust scanner

### Quality Gates

- [x] `cargo check --tests` passes (tests compile)
- [x] `cargo clippy` passes (minor warnings in existing code)
- [x] `maturin develop` succeeds
- [x] `pytest tests/unit/test_scanner.py -v` passes (24/24)
- [x] `ruff check src/mu/scanner/` passes
- [x] `mypy src/mu/scanner/` passes

### Phase 1 Completion Criteria

- [x] `mu scan .` uses Rust scanner by default
- [x] `.gitignore` patterns are respected (when git repo initialized)
- [x] `.muignore` patterns are respected
- [x] Fallback to Python works with `MU_USE_RUST_SCANNER=0`

### Phase 1 Results

**Benchmark on MU repo (384 files, 124k lines):**
- Python scanner: ~76ms (mean)
- Rust scanner: ~11ms (mean)
- **Speedup: 6.9x faster**
- Target was <50ms - achieved 11ms

**CLI commands updated to use Rust scanner:**
- `mu scan` - uses `scan_codebase_auto()`
- `mu compress` - uses `scan_codebase_auto()`
- `mu diff` - uses `scan_codebase_auto()`
- `mu kernel build` - uses `scan_codebase_auto()`

**Benchmark tests:** `tests/benchmarks/test_scanner_benchmark.py`

---

## Phase 2: Semantic Diff Engine

**Estimated Time:** 6-8 hours
**Dependencies:** Phase 1 (for efficient file loading)
**Goal:** Compare `ModuleDef` structs and output meaningful change descriptions.

### Setup

- [ ] Create `mu-core/src/differ/mod.rs`
- [ ] Create `mu-core/src/differ/changes.rs`
- [ ] Create `mu-core/src/differ/comparator.rs`
- [ ] Add `pub mod differ;` to `mu-core/src/lib.rs`
- [ ] Run `cargo check`

### Change Types (`changes.rs`)

- [ ] Define `ChangeType` enum:
  ```rust
  pub enum ChangeType {
      Added,
      Removed,
      Modified,
      Renamed,
  }
  ```
- [ ] Define `EntityType` enum:
  ```rust
  pub enum EntityType {
      Function,
      Class,
      Method,
      Import,
      Parameter,
      Attribute,
      Constant,
  }
  ```
- [ ] Define `SemanticChange` struct with PyO3 bindings:
  ```rust
  #[pyclass]
  pub struct SemanticChange {
      pub change_type: String,
      pub entity_type: String,
      pub entity_name: String,
      pub file_path: String,
      pub details: Option<String>,
      pub old_signature: Option<String>,
      pub new_signature: Option<String>,
  }
  ```
- [ ] Define `DiffResult` struct:
  ```rust
  #[pyclass]
  pub struct DiffResult {
      pub changes: Vec<SemanticChange>,
      pub summary: String,
      pub breaking_changes: Vec<SemanticChange>,
  }
  ```

### Comparator Logic (`comparator.rs`)

- [ ] Implement `diff_modules(base: &[ModuleDef], head: &[ModuleDef]) -> Vec<SemanticChange>`:
  - Build HashMap of modules by path
  - Find added modules (in head, not in base)
  - Find removed modules (in base, not in head)
  - Find modified modules (in both, diff contents)
- [ ] Implement `diff_single_module(base: &ModuleDef, head: &ModuleDef) -> Vec<SemanticChange>`:
  - Compare functions
  - Compare classes
  - Compare imports
  - Compare constants
- [ ] Implement `diff_functions(base: &[FunctionDef], head: &[FunctionDef]) -> Vec<SemanticChange>`:
  - Match by name
  - Detect added/removed
  - Compare signatures for modified
- [ ] Implement `diff_classes(base: &[ClassDef], head: &[ClassDef]) -> Vec<SemanticChange>`:
  - Match by name
  - Compare bases (inheritance changes)
  - Compare methods
  - Compare attributes
- [ ] Implement `diff_parameters(base: &[ParameterDef], head: &[ParameterDef]) -> Vec<SemanticChange>`:
  - Detect added/removed params
  - Detect type changes
  - Detect default value changes
- [ ] Implement `generate_signature(func: &FunctionDef) -> String`:
  - Format: `func_name(param1: type1, param2: type2) -> return_type`
- [ ] Implement `is_breaking_change(change: &SemanticChange) -> bool`:
  - Removals are breaking
  - Parameter removals are breaking
  - Type changes are breaking (optional)

### Summary Generation

- [ ] Implement `generate_summary(changes: &[SemanticChange]) -> String`:
  - Count by change type and entity type
  - Format: "3 functions added, 1 class modified, 2 methods removed"

### PyO3 Functions

- [ ] Implement `semantic_diff()`:
  ```rust
  #[pyfunction]
  pub fn semantic_diff(
      base_modules: Vec<ModuleDef>,
      head_modules: Vec<ModuleDef>,
  ) -> PyResult<DiffResult>
  ```
- [ ] Implement `semantic_diff_files()`:
  ```rust
  #[pyfunction]
  pub fn semantic_diff_files(
      py: Python<'_>,
      base_path: &str,
      head_path: &str,
      language: &str,
  ) -> PyResult<DiffResult>
  ```
- [ ] Register functions in `lib.rs`

### Python Integration

- [ ] Update `src/mu/diff/__init__.py`:
  - Add `semantic_diff()` wrapper
  - Add fallback to Python implementation
- [ ] Update `mu diff` CLI command to use semantic diff
- [ ] Add `--semantic` flag to `mu diff`

### Type Stubs

- [ ] Add to `src/mu/_core.pyi`:
  ```python
  class SemanticChange:
      change_type: str
      entity_type: str
      entity_name: str
      file_path: str
      details: str | None
      old_signature: str | None
      new_signature: str | None
      def to_dict(self) -> dict[str, Any]: ...

  class DiffResult:
      changes: list[SemanticChange]
      summary: str
      breaking_changes: list[SemanticChange]
      def to_dict(self) -> dict[str, Any]: ...

  def semantic_diff(
      base_modules: list[ModuleDef],
      head_modules: list[ModuleDef],
  ) -> DiffResult: ...

  def semantic_diff_files(
      base_path: str,
      head_path: str,
      language: str,
  ) -> DiffResult: ...
  ```

### Testing

- [ ] Rust unit tests in `mu-core/src/differ/`:
  - Test function added detection
  - Test function removed detection
  - Test function modified (signature change)
  - Test class added/removed
  - Test method changes within class
  - Test parameter changes
  - Test import changes
  - Test breaking change detection
  - Test summary generation
- [ ] Python integration tests:
  - Test diff between two Python files
  - Test diff between two TypeScript files
  - Test breaking change identification
  - Test `mu diff` CLI command

### Quality Gates

- [ ] `cargo test differ` passes
- [ ] `cargo clippy` passes with no warnings
- [ ] `maturin develop` succeeds
- [ ] `pytest tests/unit/test_diff.py -v` passes
- [ ] `ruff check src/mu/diff/` passes
- [ ] `mypy src/mu/diff/` passes

### Phase 2 Completion Criteria

- [ ] `mu diff base head --semantic` outputs meaningful changes
- [ ] Change descriptions are human-readable
- [ ] Breaking changes are identified
- [ ] Works for all 7 supported languages
- [ ] Fallback to line-level diff when Rust unavailable

---

## Phase 3: Incremental Parser

**Estimated Time:** 6-8 hours
**Dependencies:** None (can be developed in parallel with Phase 2)
**Goal:** Enable sub-10ms updates in daemon mode.

### Setup

- [ ] Create `mu-core/src/incremental.rs`
- [ ] Add `pub mod incremental;` to `mu-core/src/lib.rs`
- [ ] Review tree-sitter `Tree::edit()` documentation
- [ ] Run `cargo check`

### IncrementalParser Struct

- [ ] Define internal state:
  ```rust
  #[pyclass]
  pub struct IncrementalParser {
      parser: tree_sitter::Parser,
      tree: Option<tree_sitter::Tree>,
      source: String,
      language: String,
      file_path: String,
  }
  ```
- [ ] Implement `#[new]` constructor:
  ```rust
  #[new]
  fn new(source: &str, language: &str, file_path: &str) -> PyResult<Self>
  ```
  - Initialize parser with language
  - Parse initial source
  - Store tree and source

### Edit Application

- [ ] Implement `apply_edit()`:
  ```rust
  fn apply_edit(
      &mut self,
      start_byte: usize,
      old_end_byte: usize,
      new_end_byte: usize,
      new_text: &str,
  ) -> PyResult<IncrementalParseResult>
  ```
- [ ] Create `InputEdit` from parameters:
  ```rust
  let input_edit = tree_sitter::InputEdit {
      start_byte,
      old_end_byte,
      new_end_byte,
      start_position: /* calculate from source */,
      old_end_position: /* calculate from source */,
      new_end_position: /* calculate from new_text */,
  };
  ```
- [ ] Apply edit to tree: `self.tree.as_mut().unwrap().edit(&input_edit)`
- [ ] Update source string with new text
- [ ] Reparse with old tree: `self.parser.parse(&self.source, self.tree.as_ref())`
- [ ] Extract ModuleDef from new tree
- [ ] Track changed ranges from tree comparison

### Helper Methods

- [ ] Implement `get_module() -> PyResult<ModuleDef>`:
  - Extract current ModuleDef from tree
- [ ] Implement `get_source() -> String`:
  - Return current source
- [ ] Implement `byte_to_position(byte: usize) -> Point`:
  - Convert byte offset to line/column

### IncrementalParseResult

- [ ] Define result struct:
  ```rust
  #[pyclass]
  pub struct IncrementalParseResult {
      pub module: ModuleDef,
      pub parse_time_ms: f64,
      pub changed_ranges: Vec<(usize, usize)>,
  }
  ```

### PyO3 Registration

- [ ] Register `IncrementalParser` class in `lib.rs`
- [ ] Register `IncrementalParseResult` class in `lib.rs`

### Python Integration

- [ ] Add to `src/mu/_core.pyi`:
  ```python
  class IncrementalParseResult:
      module: ModuleDef
      parse_time_ms: float
      changed_ranges: list[tuple[int, int]]

  class IncrementalParser:
      def __init__(self, source: str, language: str, file_path: str) -> None: ...
      def apply_edit(
          self,
          start_byte: int,
          old_end_byte: int,
          new_end_byte: int,
          new_text: str,
      ) -> IncrementalParseResult: ...
      def get_module(self) -> ModuleDef: ...
      def get_source(self) -> str: ...
  ```
- [ ] Update daemon watcher to use incremental parser:
  - Maintain `Dict[str, IncrementalParser]` per watched file
  - On file change, calculate edit coordinates
  - Call `parser.apply_edit()` instead of full reparse

### Testing

- [ ] Rust unit tests:
  - Test initial parse produces correct ModuleDef
  - Test single line addition
  - Test single line deletion
  - Test function body modification
  - Test function addition
  - Test function removal
  - Test multiple sequential edits
  - Test invalid edit handling
- [ ] Python integration tests:
  - Test parser creation from Python
  - Test edit application from Python
  - Test ModuleDef extraction after edit
- [ ] Benchmark: compare full reparse vs incremental

### Quality Gates

- [ ] `cargo test incremental` passes
- [ ] `cargo clippy` passes with no warnings
- [ ] `maturin develop` succeeds
- [ ] `pytest tests/unit/test_incremental.py -v` passes
- [ ] `mypy src/mu/daemon/` passes (after integration)

### Phase 3 Completion Criteria

- [ ] Single line edit takes < 5ms (vs ~100ms full reparse)
- [ ] Function addition/removal takes < 10ms
- [ ] Daemon mode uses incremental parser
- [ ] Memory overhead is minimal (< 50MB per 100 files)
- [ ] Graceful fallback to full reparse on error

---

## Phase 4: Integration & Polish

**Estimated Time:** 4-6 hours
**Dependencies:** Phases 1, 2, 3
**Goal:** Wire everything together, validate performance, ensure quality.

### End-to-End Integration

- [ ] Verify `mu scan` uses Rust scanner
- [ ] Verify `mu compress` uses scanner → parser pipeline
- [ ] Verify `mu diff` uses semantic differ
- [ ] Verify `mu daemon` uses incremental parser
- [ ] Test all commands with `MU_USE_RUST=0` fallback

### Performance Validation

- [ ] Benchmark scanner on large repo:
  - Target: < 100ms for 50k files
  - Measured: ___ms
- [ ] Benchmark full pipeline on MU repo:
  - Target: < 800ms
  - Measured: ___ms
- [ ] Benchmark incremental update:
  - Target: < 10ms
  - Measured: ___ms
- [ ] Memory profile on 100k file repo:
  - Target: < 500MB
  - Measured: ___MB

### MCP Tool Updates

- [ ] Verify `mu_context` benefits from faster scanning
- [ ] Add `mu_semantic_diff` MCP tool (optional):
  ```python
  @mcp_tool
  def mu_semantic_diff(base_ref: str, head_ref: str) -> DiffResult:
      """Get semantic diff between git refs."""
  ```

### CLI Updates

- [ ] Add `mu scan --stats` to show timing info
- [ ] Add `mu diff --semantic` flag
- [ ] Add `--no-rust` global flag for fallback
- [ ] Update `mu describe` output with new features

### CI/CD Verification

- [ ] All tests pass on Linux
- [ ] All tests pass on macOS
- [ ] All tests pass on Windows
- [ ] Wheels build for all platforms
- [ ] Type stubs match implementation

### Documentation

- [ ] Update `mu-core/CLAUDE.md` with new modules
- [ ] Update main `CLAUDE.md` with new features
- [ ] Add changelog entry for release
- [ ] Update `mu describe --format markdown`

### Final Quality Gates

- [ ] `pytest` - all tests pass
- [ ] `mypy src/mu` - no type errors
- [ ] `ruff check src/` - no lint errors
- [ ] `cargo test` - all Rust tests pass
- [ ] `cargo clippy` - no warnings
- [ ] `maturin build --release` - wheels build

### Phase 4 Completion Criteria

- [ ] All performance targets met
- [ ] All quality gates pass
- [ ] Documentation is current
- [ ] Ready for merge to develop

---

## Summary

| Phase | Goal | Estimated Hours | Status |
|-------|------|-----------------|--------|
| 1 | Rust Scanner | 4-6 | ✅ Complete |
| 2 | Semantic Diff | 6-8 | Not Started |
| 3 | Incremental Parser | 6-8 | Not Started |
| 4 | Integration | 4-6 | Not Started |

**Total Estimated Time:** 20-28 hours (2-3 days AI-assisted)

---

## Agent Instructions

When implementing each phase:

1. **Read the checklist** - Understand all tasks before starting
2. **Work sequentially** - Complete each checkbox in order within a section
3. **Mark progress** - Update `[ ]` to `[x]` as you complete items
4. **Run quality gates** - Don't proceed until quality gates pass
5. **Document issues** - Add notes for any blockers or deviations
6. **Commit frequently** - Commit after completing each major section

### Commit Message Format

```
feat(mu-core): implement rust scanner with ignore crate

- Add scan_directory() function with parallel traversal
- Support .gitignore and .muignore patterns
- Add extension filtering
- Benchmark shows 20x speedup on large repos
```

### When Blocked

If you encounter a blocker:
1. Document the issue in this file under the relevant task
2. Note what was attempted
3. Suggest potential solutions
4. Continue with other independent tasks if possible
