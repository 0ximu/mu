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

## Phase 2: Semantic Diff Engine ✅

**Status:** COMPLETED
**Completed:** 2025-12-07
**Goal:** Compare `ModuleDef` structs and output meaningful change descriptions.

### Setup ✅

- [x] Create `mu-core/src/differ/mod.rs`
- [x] Create `mu-core/src/differ/changes.rs`
- [x] Create `mu-core/src/differ/comparator.rs`
- [x] Add `pub mod differ;` to `mu-core/src/lib.rs`
- [x] Run `cargo check`

### Change Types (`changes.rs`) ✅

- [x] Define `ChangeType` enum (Added, Removed, Modified, Renamed)
- [x] Define `EntityType` enum (Module, Function, Class, Method, Parameter, Import, Attribute, Constant)
- [x] Define `EntityChange` struct with PyO3 bindings (includes parent_name, is_breaking)
- [x] Define `DiffSummary` struct with detailed counts per entity/change type
- [x] Define `SemanticDiffResult` struct with changes, breaking_changes, summary

### Comparator Logic (`comparator.rs`) ✅

- [x] Implement `semantic_diff_modules()` with HashMap indexing and parallel comparison
- [x] Implement `diff_single_module()` comparing functions, classes, imports
- [x] Implement `diff_functions()` with signature comparison
- [x] Implement `diff_classes()` with inheritance and method comparison
- [x] Implement `diff_parameters()` for added/removed/type changes
- [x] Implement `generate_signature()` for human-readable function signatures
- [x] Implement breaking change detection (removals, type changes)

### Summary Generation ✅

- [x] Implement `DiffSummary.text()` for human-readable summaries
- [x] Implement `DiffSummary.record()` for counting by entity/change type

### PyO3 Functions ✅

- [x] Implement `semantic_diff()` with GIL release for parallel processing
- [x] Implement `semantic_diff_files()` for file-based diffing (read, parse, diff in one call)
  - Includes `normalize_paths` option (default: True) for comparing file versions
- [x] Register functions and types in `lib.rs`

### Python Integration ✅

- [x] Update `src/mu/diff/__init__.py` with `semantic_diff_modules()` wrapper
- [x] Add fallback when Rust module unavailable

### Type Stubs ✅

- [x] Add `EntityChange`, `DiffSummary`, `SemanticDiffResult` to `src/mu/_core.pyi`
- [x] Add `semantic_diff()` function stub
- [x] Add `semantic_diff_files()` function stub

### Testing ✅

- [x] Rust unit tests in `mu-core/src/differ/`:
  - Test function added detection
  - Test function removed detection (breaking)
  - Test function modified (signature change)
  - Test class added/removed
  - Test method changes within class
  - Test parameter changes
  - Test import changes
  - Test breaking change detection
  - Test summary generation
  - Test no changes scenario
- [x] Python integration tests (14 tests in `TestRustSemanticDiff`):
  - Test semantic_diff available
  - Test diff added/removed/modified functions
  - Test diff added class
  - Test diff added method
  - Test no changes
  - Test added/removed module
  - Test result serialization
  - Test filter_by_type
  - Test semantic_diff_files with file paths
  - Test semantic_diff_files error handling

### Quality Gates ✅

- [x] `cargo check --tests` passes
- [x] `cargo clippy` passes
- [x] `maturin develop` succeeds
- [x] `pytest tests/unit/test_diff.py -v` passes (28 tests)
- [x] `ruff check src/mu/diff/` passes
- [x] `mypy src/mu/diff/` passes

### Phase 2 Completion Criteria ✅

- [x] `semantic_diff_modules()` outputs meaningful changes from Python
- [x] Change descriptions are human-readable (summary_text, EntityChange.details)
- [x] Breaking changes are identified (is_breaking flag, breaking_changes list)
- [x] Works for all 7 supported languages (language-agnostic ModuleDef comparison)
- [x] Fallback when Rust unavailable (returns None)

---

## Phase 3: Incremental Parser ✅

**Status:** COMPLETED
**Completed:** 2025-12-07
**Goal:** Enable sub-10ms updates in daemon mode.

### Setup ✅

- [x] Create `mu-core/src/incremental.rs`
- [x] Add `pub mod incremental;` to `mu-core/src/lib.rs`
- [x] Review tree-sitter `Tree::edit()` documentation
- [x] Run `cargo check`

### IncrementalParser Struct ✅

- [x] Define internal state:
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
- [x] Implement `#[new]` constructor with language initialization and initial parse
- [x] Support all 7 languages (Python, TypeScript, JavaScript, Go, Java, Rust, C#)
- [x] Language alias support (py→python, ts→typescript, rs→rust, etc.)

### Edit Application ✅

- [x] Implement `apply_edit()` with full InputEdit creation
- [x] Byte offset validation (start_byte, old_end_byte, new_end_byte)
- [x] Apply edit to tree with `tree.edit(&input_edit)`
- [x] Update source string with new text
- [x] Reparse with old tree for incremental parsing
- [x] Extract ModuleDef from new tree
- [x] Track changed ranges from tree comparison

### Helper Methods ✅

- [x] Implement `get_module() -> PyResult<ModuleDef>`
- [x] Implement `get_source() -> String`
- [x] Implement `get_language() -> String`
- [x] Implement `get_file_path() -> String`
- [x] Implement `byte_to_position(byte: usize) -> (line, column)`
- [x] Implement `position_to_byte(line, column) -> byte`
- [x] Implement `has_tree() -> bool`
- [x] Implement `has_errors() -> bool`
- [x] Implement `line_count() -> usize`
- [x] Implement `byte_count() -> usize`
- [x] Implement `reset(source) -> IncrementalParseResult`

### IncrementalParseResult ✅

- [x] Define result struct with PyO3 bindings:
  ```rust
  #[pyclass]
  pub struct IncrementalParseResult {
      pub module: ModuleDef,
      pub parse_time_ms: f64,
      pub changed_ranges: Vec<(usize, usize)>,
  }
  ```
- [x] Implement `to_dict()` serialization

### PyO3 Registration ✅

- [x] Register `IncrementalParser` class in `lib.rs`
- [x] Register `IncrementalParseResult` class in `lib.rs`

### Python Type Stubs ✅

- [x] Add comprehensive type stubs to `src/mu/_core.pyi`:
  - `IncrementalParseResult` with all attributes
  - `IncrementalParser` with all methods and docstrings

### Testing ✅

- [x] Rust unit tests (18 tests in `mu-core/src/incremental.rs`):
  - Test byte_offset_to_point conversion
  - Test normalize_language aliases
  - Test get_tree_sitter_language for all 7 languages
  - Test parser creation success
  - Test unsupported language error
  - Test apply_edit insert
  - Test apply_edit delete
  - Test apply_edit replace
  - Test multiline edits
  - Test add/remove function
  - Test sequential edits
  - Test invalid byte offset handling
  - Test syntax error detection
  - Test changed ranges tracking
  - Test reset functionality
  - Test TypeScript and Go parsers
- [x] Python integration tests (27 tests in `tests/unit/test_incremental.py`):
  - Test parser creation for all languages
  - Test module extraction
  - Test all edit operations (insert, delete, replace)
  - Test byte/position conversions
  - Test error handling
  - Test sequential edits workflow
  - Test simulated typing workflow
  - Test simulated refactoring workflow
  - Test error recovery

### Quality Gates ✅

- [x] `cargo check` passes
- [x] `cargo clippy` passes (only minor warnings in existing code)
- [x] `maturin develop` succeeds
- [x] `pytest tests/unit/test_incremental.py -v` passes (27/27 tests)
- [x] Type stubs validate with mypy

### Phase 3 Results

**Performance:**
- Incremental parse: < 5ms for single line edits (target met)
- Function addition/removal: < 10ms (target met)
- All 27 Python tests pass in 0.06s

**Features Implemented:**
- Full incremental parsing with tree-sitter Tree::edit()
- Changed range tracking for selective updates
- Position/byte conversion utilities
- Error recovery support
- All 7 languages supported

**Daemon Integration:** Ready for Phase 4 (update daemon watcher to use IncrementalParser)

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

### MCP Tool Updates - Bootstrap Tools (P0)

These tools enable agents to fully bootstrap a codebase without manual intervention:

- [ ] Add `mu_init` MCP tool:
  ```python
  @mcp.tool()
  def mu_init(path: str = ".") -> dict:
      """Initialize MU configuration for a codebase.

      Creates .murc.toml with sensible defaults.
      Safe to run multiple times (won't overwrite existing config).

      Args:
          path: Path to initialize (default: current directory)

      Returns:
          {"success": True, "config_path": ".murc.toml", "message": "..."}
      """
  ```

- [ ] Add `mu_build` MCP tool:
  ```python
  @mcp.tool()
  def mu_build(path: str = ".", force: bool = False) -> dict:
      """Build or rebuild the .mubase code graph.

      This is the main bootstrap command. Run this before using
      mu_query, mu_context, mu_deps, etc.

      Args:
          path: Path to codebase (default: current directory)
          force: Force rebuild even if .mubase exists

      Returns:
          {"success": True, "stats": {"nodes": N, "edges": M}, "duration_ms": ...}
      """
  ```

- [ ] Add `mu_semantic_diff` MCP tool:
  ```python
  @mcp.tool()
  def mu_semantic_diff(
      base_ref: str,
      head_ref: str,
      path: str = "."
  ) -> SemanticDiffResult:
      """Compare two git refs and return semantic changes.

      Returns structured diff with:
      - Added/removed/modified functions, classes, methods
      - Breaking change detection
      - Human-readable summary

      Args:
          base_ref: Base git ref (e.g., "main", "HEAD~1")
          head_ref: Head git ref (e.g., "feature-branch", "HEAD")
          path: Path to codebase (default: current directory)

      Returns:
          SemanticDiffResult with changes, breaking_changes, summary_text

      Example:
          result = mu_semantic_diff("main", "HEAD")
          if result.has_breaking_changes():
              for bc in result.breaking_changes:
                  print(f"BREAKING: {bc.change_type} {bc.entity_name}")
      """
  ```

### MCP Tool Updates - Discovery Tools (P1)

- [ ] Add `mu_scan` MCP tool:
  ```python
  @mcp.tool()
  def mu_scan(
      path: str = ".",
      extensions: list[str] | None = None
  ) -> dict:
      """Scan codebase and return file statistics.

      Fast discovery without full graph build.
      Uses Rust scanner (6-7x faster than Python).

      Args:
          path: Path to scan (default: current directory)
          extensions: Filter by extensions (e.g., ["py", "ts"])

      Returns:
          {
              "files": [{"path": "...", "language": "...", "lines": N}, ...],
              "total_files": N,
              "total_lines": M,
              "by_language": {"python": 50, "typescript": 30, ...},
              "duration_ms": ...
          }
      """
  ```

- [ ] Add `mu_compress` MCP tool:
  ```python
  @mcp.tool()
  def mu_compress(
      path: str,
      format: str = "mu"
  ) -> dict:
      """Generate compressed MU representation of a file or directory.

      Args:
          path: File or directory to compress
          format: Output format ("mu", "json", "markdown")

      Returns:
          {"output": "...", "token_count": N, "compression_ratio": 0.95}
      """
  ```

### MCP Tool Updates - Embedding Tools (P2)

- [ ] Add `mu_embed` MCP tool:
  ```python
  @mcp.tool()
  def mu_embed(path: str = ".") -> dict:
      """Generate vector embeddings for semantic search.

      Required for mu_context to work with natural language queries.

      Args:
          path: Path to codebase

      Returns:
          {"success": True, "nodes_embedded": N, "duration_ms": ...}
      """
  ```

### MCP Tool Updates - Daemon Tools (P2)

- [ ] Add `mu_daemon_start` MCP tool:
  ```python
  @mcp.tool()
  def mu_daemon_start(path: str = ".") -> dict:
      """Start the MU daemon for real-time updates.

      Daemon watches for file changes and updates graph incrementally.

      Returns:
          {"success": True, "pid": N, "url": "http://localhost:9120"}
      """
  ```

- [ ] Add `mu_daemon_stop` MCP tool:
  ```python
  @mcp.tool()
  def mu_daemon_stop() -> dict:
      """Stop the running MU daemon.

      Returns:
          {"success": True, "message": "Daemon stopped"}
      """
  ```

### MCP - Update mu_status

- [ ] Enhance `mu_status` to return actionable next steps:
  ```python
  # Current: just returns status
  # New: returns status + what agent should do next
  {
      "daemon_running": False,
      "mubase_exists": False,
      "embeddings_exist": False,
      "next_action": "mu_build",  # <-- Tells agent what to do
      "message": "No .mubase found. Run mu_build() to initialize."
  }
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
| 1 | Rust Scanner | 4-6 | ✅ Complete (6.9x speedup) |
| 2 | Semantic Diff | 6-8 | ✅ Complete |
| 3 | Incremental Parser | 6-8 | ✅ Complete (<5ms edits) |
| 4 | Integration + MCP | 6-8 | Not Started |

**Total Estimated Time:** 22-30 hours (2-3 days AI-assisted)

### Phase 4 MCP Tools Summary

| Tool | Priority | Purpose |
|------|----------|---------|
| `mu_build` | P0 | Bootstrap - build .mubase graph |
| `mu_semantic_diff` | P0 | PR review - semantic changes between refs |
| `mu_init` | P0 | Bootstrap - create config |
| `mu_scan` | P1 | Discovery - fast file stats |
| `mu_compress` | P1 | Output - generate MU format |
| `mu_embed` | P2 | Enable semantic search |
| `mu_daemon_start` | P2 | Real-time updates |
| `mu_daemon_stop` | P2 | Cleanup |

**Agent Bootstrap Flow:**
```
mu_status() → "next_action": "mu_build"
     ↓
mu_build(".") → builds .mubase
     ↓
mu_context("How does auth work?") → works!
     ↓
mu_semantic_diff("main", "HEAD") → PR review
```

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
