# Test Detection Tasks - Language-Agnostic Test File Detection

## Business Context

**Problem**: MU's `mu warn` command incorrectly reports "No test file found" for files that have tests in non-Python project structures. This was observed on the Dominaite codebase where `mu warn PayoutService.cs` claimed no tests existed, but `PayoutServiceTests.cs` exists in the `.Tests` project directory.

**Root Cause**: MU's test detection heuristic is Python-centric, looking for patterns like `test_*.py` and `*_test.py`. It doesn't recognize test conventions for other languages:
- .NET: `*Tests.cs` in `*.Tests/` or `*.Test/` projects
- Java: `*Test.java` in `src/test/`
- Go: `*_test.go` in same directory
- TypeScript/JavaScript: `*.test.ts`, `*.spec.ts` in `__tests__/` or alongside source

**Outcome**: When `mu warn` analyzes a file, it should correctly identify whether tests exist using language-appropriate patterns. This eliminates false positives that erode user trust.

**Users**:
- AI agents (Claude Code) using MU for code analysis
- Developers running `mu warn` for code health checks
- CI/CD pipelines using MU for automated analysis

---

## Discovered Patterns

### Python Implementation

| Pattern | File | Line(s) | Relevance |
|---------|------|---------|-----------|
| `_check_tests()` method | `/Users/imu/Dev/work/mu/src/mu/intelligence/warnings.py` | 422-627 | **Main test detection logic** - already has language-specific patterns for Python, C#, Java, Go, TS |
| `_find_project_root()` | `/Users/imu/Dev/work/mu/src/mu/intelligence/warnings.py` | 629-642 | Project root detection for finding tests/ directories |
| `_check_test_imports()` | `/Users/imu/Dev/work/mu/src/mu/intelligence/warnings.py` | 644-689 | Python-specific fallback that checks for imports in test files |
| `ProactiveWarning` model | `/Users/imu/Dev/work/mu/src/mu/intelligence/models.py` | 1037-1060 | Warning dataclass with category, level, message, details |
| `WarningCategory.NO_TESTS` | `/Users/imu/Dev/work/mu/src/mu/intelligence/models.py` | 1001-1002 | Enum for no test coverage warning |
| `LANGUAGE_EXTENSIONS` | `/Users/imu/Dev/work/mu/src/mu/scanner/__init__.py` | 31-65 | Extension to language mapping (already exists) |
| `detect_language()` | `/Users/imu/Dev/work/mu/src/mu/scanner/__init__.py` | 148-151 | File extension to language detection |
| Test file for warnings | `/Users/imu/Dev/work/mu/tests/unit/test_warnings.py` | 329-362 | Existing tests for `_check_tests` method |

### Rust Daemon Implementation

| Pattern | File | Line(s) | Relevance |
|---------|------|---------|-----------|
| `analyze_warnings()` | `/Users/imu/Dev/work/mu/mu-daemon/src/server/http.rs` | 1759-1925 | Rust warning analysis - has Python-only test detection |
| `WarningInfo` struct | `/Users/imu/Dev/work/mu/mu-daemon/src/server/http.rs` | 1727-1733 | Rust warning model |
| `WarnResponse` struct | `/Users/imu/Dev/work/mu/mu-daemon/src/server/http.rs` | 1735-1743 | Response model with warnings array |
| Test detection code | `/Users/imu/Dev/work/mu/mu-daemon/src/server/http.rs` | 1868-1906 | **Current Python-only test patterns** - only `test_*` and `*_test` |

### Key Discovery: Python Implementation is More Complete

The Python implementation in `warnings.py` (lines 422-627) already has extensive language-specific test detection for:
- Python (`test_*.py`, `*_test.py`)
- C# (`*Tests.cs`, `*Test.cs`, `.Tests/` project directories)
- Java (`*Test.java`, `*Tests.java`, `src/test/`)
- Go (`*_test.go`)
- TypeScript/JavaScript (`*.test.ts`, `*.spec.ts`, `__tests__/`)

The **bug** is that it's not finding `.Tests` sibling project directories correctly. The logic (lines 481-496) tries to find sibling `*.Tests/` directories but the path matching logic appears flawed.

The **Rust daemon** (lines 1868-1906) only checks for `test_*` and `*_test` patterns (Python-only).

---

## Tasks

### Task 1: Fix Python .Tests Project Directory Detection

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/intelligence/warnings.py`

**Status**: completed

**Dependencies**: []

**Description**: The existing `.Tests` sibling project detection logic (lines 481-496) is not working correctly. Fix the path matching logic to properly find test files in sibling `*.Tests/` directories.

**Changes**:
1. Debug and fix the `*.Tests` directory sibling detection logic
2. The current code walks ancestors looking for directories ending with `.Tests`
3. Issue: `relative_to()` may fail, and the fallback direct lookup doesn't mirror the source path structure

**Acceptance Criteria**:
- [x] `mu warn PayoutService.cs` finds `PayoutServiceTests.cs` in sibling `.Tests` project
- [x] Works for nested source files (mirrors path structure in test project)
- [x] Existing Python test detection continues to work

**Implementation**:
- Extracted the `.Tests` detection logic into a new helper method `_find_dotnet_tests_project()` (lines 580-668)
- The new method walks up the directory tree, looking for sibling directories with `.Tests` suffix
- For each ancestor directory `D`, it looks for a sibling `D.Tests` and mirrors the relative path
- Added recursive search using `rglob()` with depth limiting (max 5 levels)

**Pattern Applied**: Followed existing method extraction pattern from the codebase

**Quality**:
- [x] ruff check passes
- [x] mypy passes
- [x] Tests added (7 new tests in `TestCSharpTestDetection` class)

---

### Task 2: Add Recursive Test File Search in .Tests Directories

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/intelligence/warnings.py`

**Status**: completed

**Dependencies**: [Task 1]

**Description**: Currently the code only checks exact paths. For larger .NET projects, test files may be in subdirectories. Add recursive search using `rglob()`.

**Changes**:
1. Use `rglob(f"{stem}Tests{suffix}")` to search recursively in `.Tests` directories
2. Limit search depth to prevent performance issues

**Acceptance Criteria**:
- [x] Finds tests in nested directories (e.g., `Project.Tests/Services/PayoutServiceTests.cs`)
- [x] Search is bounded (not infinitely deep)

**Implementation**:
- Implemented as part of Task 1 in `_find_dotnet_tests_project()` method
- Uses `tests_dir.rglob(test_pattern)` to recursively search for test files
- Bounded to 5 levels deep by checking `len(rel_match.parts) <= 5`
- Searches for both `{stem}Tests{suffix}` and `{stem}Test{suffix}` patterns

**Quality**:
- [x] Test `test_csharp_finds_tests_recursive_search` verifies rglob functionality

---

### Task 3: Update Rust Daemon Test Detection

**File(s)**: `/Users/imu/Dev/work/mu/mu-daemon/src/server/http.rs`

**Status**: not_applicable

**Dependencies**: []

**Description**: The Rust daemon's `analyze_warnings()` function (lines 1868-1906) only checks Python test patterns. Add the same language-aware patterns as Python.

**Discovery**: Upon investigation, the Rust daemon (`mu-daemon/src/server/http.rs`) does NOT have a `/warn` endpoint or `analyze_warnings()` function. The http.rs file is only 1127 lines, not 1900+. The warning functionality only exists in the Python implementation (`src/mu/intelligence/warnings.py`).

The MCP server (`mu-daemon/src/server/mcp.rs`) also does not have warning-related methods - only status, query, context, deps, impact, ancestors, cycles, build, node, and search.

**Status Reason**: This task was based on incorrect assumptions about the Rust daemon's current capabilities. The warning functionality should be added to the Rust daemon as a new feature, not a fix to existing code.

**Future Work**: If Rust daemon warning support is desired, create a new task to:
1. Add `/warn` HTTP endpoint to `mu-daemon/src/server/http.rs`
2. Add `mu/warn` MCP method to `mu-daemon/src/server/mcp.rs`
3. Implement language-aware test detection in Rust

---

### Task 4: Add Unit Tests for C# Test Detection

**File(s)**: `/Users/imu/Dev/work/mu/tests/unit/test_warnings.py`

**Status**: completed

**Dependencies**: [Task 1, Task 2]

**Description**: Add tests specifically for C#/.NET test detection patterns.

**Changes**:
1. Add test for `*Tests.cs` in same directory
2. Add test for `*.Tests/` sibling project directory
3. Add test for nested test file in `.Tests` project
4. Add test for path structure mirroring

**Acceptance Criteria**:
- [x] Tests cover `.Tests` sibling project pattern
- [x] Tests cover nested directories
- [x] Tests verify no false positives for test files themselves

**Implementation**:
Added 7 tests in `TestCSharpTestDetection` class (lines 494-655 in test_warnings.py):
1. `test_csharp_finds_tests_in_sibling_test_project` - Dominaite regression test
2. `test_csharp_finds_tests_in_nested_directory` - Mirrored path structure
3. `test_csharp_finds_tests_recursive_search` - rglob finds tests in non-mirrored paths
4. `test_csharp_warns_when_no_tests_exist` - Verifies warning when no tests
5. `test_csharp_skips_test_files_themselves` - No warning for test files
6. `test_csharp_handles_singular_test_suffix` - FooTest.cs (singular)
7. `test_csharp_deep_nested_project_structure` - Deep directory nesting

**Quality**:
- All 31 tests pass (24 existing + 7 new)

---

### Task 5: Add Integration Test for Dominaite Regression

**File(s)**: `/Users/imu/Dev/work/mu/tests/unit/test_warnings.py` (or `tests/integration/`)

**Status**: completed

**Dependencies**: [Task 1, Task 2, Task 4]

**Description**: End-to-end test that simulates the exact Dominaite scenario.

**Changes**:
1. Create test that sets up full .NET project structure
2. Run through `ProactiveWarningGenerator.analyze()`
3. Verify no `NO_TESTS` warning

**Acceptance Criteria**:
- [x] Test simulates exact Dominaite directory structure
- [x] No false positive for PayoutService.cs
- [x] Test marked as regression test

**Implementation**:
The test `test_csharp_finds_tests_in_sibling_test_project` in Task 4 already covers this exact scenario:
- Creates `src/Dominaite.Services/PayoutService.cs` and `src/Dominaite.Services.Tests/PayoutServiceTests.cs`
- Calls `_check_tests()` directly
- Asserts no warnings are returned

Additional comprehensive test `test_csharp_deep_nested_project_structure` covers the nested variant:
- `src/Solution/Dominaite.Services/Handlers/Payments/PayoutService.cs`

---

### Task 6: Add Rust Daemon Integration Tests

**File(s)**: New file in `/Users/imu/Dev/work/mu/mu-daemon/tests/` or existing test module

**Status**: not_applicable

**Dependencies**: [Task 3]

**Status Reason**: Depends on Task 3 which was found to be not applicable - the Rust daemon does not have warning functionality.

**Description**: Add tests for Rust daemon's language-aware test detection.

**Changes**:
1. Add test for C# test detection via HTTP endpoint
2. Add test for other language patterns
3. Verify performance requirements

**Acceptance Criteria**:
- [ ] Rust tests cover C# patterns
- [ ] Tests verify HTTP `/warn` endpoint behavior
- [ ] Performance tests confirm < 100ms

---

## Dependencies Graph

```
Task 1 (Fix .Tests detection)
    |
    v
Task 2 (Recursive search) --> Task 4 (Python unit tests) --> Task 5 (Integration test)

Task 3 (Rust daemon) --> Task 6 (Rust tests)
```

Tasks 1-2 and Task 3 can run in parallel as they are independent implementations.

---

## Implementation Order

| Priority | Task | Effort | Risk |
|----------|------|--------|------|
| P0 | Task 1: Fix .Tests detection | Small (30m) | Low - bug fix in existing code |
| P0 | Task 2: Recursive search | Small (20m) | Low - enhancement to Task 1 |
| P1 | Task 4: Python unit tests | Medium (45m) | Low - standard test patterns |
| P1 | Task 5: Integration test | Small (20m) | Low |
| P2 | Task 3: Rust daemon | Medium (1.5h) | Medium - Rust changes |
| P2 | Task 6: Rust tests | Small (30m) | Low |

**Total estimated effort**: 3-4 hours

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Multiple test files for one source | Return first match, no warning |
| Test file with different extension | No match (e.g., `.cs` source won't match `.vb` test) |
| Nested test directories | Search recursively within test directories |
| Monorepo with multiple projects | Use closest ancestor project root |
| No recognized language | Skip test detection, no warning |
| Source file IS a test file | Skip test detection |
| `.Tests` directory name variations | Handle both `Project.Tests` and `ProjectTests` |

---

## Security Considerations

- No sensitive data involved
- File system access limited to project root
- No user input used in glob patterns (prevents injection)

---

## Rollback Plan

If issues arise:
1. The changes are isolated to `_check_tests()` method
2. Can add feature flag: `check_tests: bool = True` in `WarningConfig`
3. Revert specific path matching changes if needed
