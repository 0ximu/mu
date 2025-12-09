# Node Resolution & Disambiguation UX - Task Breakdown

## Business Context

**Problem**: When users reference a node by name (e.g., `mu deps PayoutService`), MU often resolves to the wrong node when multiple matches exist. Users lose trust when MU analyzes the wrong code.

**Outcome**: Consistent, intelligent node resolution across all interfaces with interactive disambiguation for CLI users.

**Users**: AI agents (Claude Code), CLI developers, automation scripts.

## Discovery Findings

### Current Node Resolution Locations

| Component | File | Function/Method | Behavior |
|-----------|------|-----------------|----------|
| MUQL Executor (Python) | `src/mu/kernel/muql/executor.py:140-170` | `_resolve_node_id()` | Tries exact ID, then exact name, then pattern match. Returns first match. |
| Graph Commands | `src/mu/commands/graph.py:520-596` | `_resolve_node()` | Handles file paths, exact IDs, exact names, suffix matches. Returns first match. |
| Core Commands (read) | `src/mu/commands/core.py:454-470` | Inline resolution | Same pattern - find_by_name then pattern match, first wins. |
| Daemon Client | `src/mu/client.py:372-407` | `find_node()` | Uses MUQL query, returns first match. |
| MUbase | `src/mu/kernel/mubase.py:426-451` | `find_by_name()` | SQL LIKE query, no sorting preference. |
| Rust Daemon | `mu-daemon/src/muql/executor.rs` | N/A | No explicit resolution - uses node IDs directly. |

### Key Insight

The current resolution pattern appears in 4+ locations with subtle differences:
1. `_resolve_node_id()` in MUQL executor
2. `_resolve_node()` in graph commands
3. Inline resolution in `read` command
4. `find_node()` in daemon client

All follow the same anti-pattern: **first match wins** without source-vs-test preference.

### Existing Patterns to Follow

| Pattern | File | Relevance |
|---------|------|-----------|
| `NodeFilter` class | `src/mu/kernel/export/filters.py` | Shows how to encapsulate node filtering logic with MUbase dependency injection |
| `DaemonClient` pattern | `src/mu/client.py` | Shows daemon-first, local-fallback architecture |
| Click commands | `src/mu/commands/graph.py` | Shows CLI argument handling and output formatting |
| Error-as-data pattern | `src/mu/kernel/export/base.py:ExportResult` | Shows how to handle errors without exceptions |

### Test Detection Heuristics (from existing code)

From `src/mu/commands/graph.py:545-549`:
```python
looks_like_path = (
    "/" in node_ref
    or "\\" in node_ref
    or node_ref.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs"))
)
```

This can be extended for test detection using path patterns.

## Task Breakdown

### Task 1: Create NodeResolver Class
**File(s)**: `src/mu/kernel/resolver.py` (new file)

**Pattern**: Follow `src/mu/kernel/export/filters.py:NodeFilter` structure

**Description**: Create centralized node resolution with smart disambiguation and configurable strategies.

**Implementation Notes**:
- Use dataclasses for `ResolvedNode`, `NodeCandidate`
- Use Enum for `ResolutionStrategy`
- Test detection uses path-based heuristics (from `_is_test_node()`)
- Scoring: exact_id > exact_name > suffix > fuzzy
- Source preference: non-test > test, then shorter path

**Acceptance Criteria**:
- [x] `NodeResolver` class with `resolve(reference: str) -> ResolvedNode`
- [x] `ResolutionStrategy` enum: `INTERACTIVE`, `PREFER_SOURCE`, `FIRST_MATCH`, `STRICT`
- [x] `NodeCandidate` dataclass with scoring metadata
- [x] `ResolvedNode` dataclass with node, alternatives, resolution_method, was_ambiguous
- [x] `_is_test_node()` detects test files across Python, TypeScript, Go, Java, C#, Rust
- [x] `_find_candidates()` tries: exact ID -> exact name -> suffix -> fuzzy
- [x] `_disambiguate()` applies strategy-specific selection
- [x] `NodeNotFoundError` and `AmbiguousNodeError` exceptions
- [x] Type hints for all public methods

**Status**: Complete

**Implementation**:
- Created `src/mu/kernel/resolver.py`
- Added exports to `src/mu/kernel/__init__.py`
- Language-agnostic test detection for Python, TypeScript, JavaScript, Go, Java, C#, Rust
- Scoring: exact_id (100) > exact_name (80) > suffix (60) > fuzzy (40) + non-test bonus (+10) + path length bonus

---

### Task 2: Add Interactive CLI Disambiguation
**File(s)**: `src/mu/commands/utils.py` (new file or extend existing)

**Pattern**: Follow Click prompt patterns from `src/mu/commands/core.py`

**Description**: Create reusable functions for CLI commands to resolve nodes interactively.

**Implementation Notes**:
- `resolve_node_interactive()` for TTY mode
- `resolve_node_auto()` for scripts/pipes (non-TTY)
- Show: name, type, file path (shortened), line range, [TEST] marker
- Default selection is first source file (based on sorting)

**Acceptance Criteria**:
- [x] `resolve_node_interactive(mubase, reference) -> Node` function
- [x] `resolve_node_auto(mubase, reference, prefer_source=True) -> Node` function
- [x] Interactive prompt shows numbered list with context
- [x] Test files marked with `[TEST]`
- [x] Path shortening for long paths
- [x] Default selection highlights most likely source file
- [x] Non-TTY detection falls back to auto resolution

**Status**: Complete

**Implementation**:
- Created `src/mu/commands/utils.py` with:
  - `is_interactive()` - TTY detection
  - `shorten_path()` - Path truncation for display
  - `format_candidate_display()` - Formatted candidate output
  - `interactive_choose()` - Interactive selection prompt
  - `resolve_node_interactive()` - TTY mode resolution
  - `resolve_node_auto()` - Non-interactive resolution
  - `resolve_node_strict()` - Strict mode (errors on ambiguity)
  - `resolve_node_for_command()` - High-level command utility
  - `print_resolution_info()` - Disambiguation info display
  - `format_resolution_for_json()` - JSON metadata formatter

---

### Task 3: Update CLI Commands to Use NodeResolver
**File(s)**:
- `src/mu/commands/graph.py` (impact, ancestors)
- `src/mu/commands/core.py` (read)
- `src/mu/commands/query.py` (if applicable)

**Pattern**: Follow existing command patterns, add `--no-interactive` flag

**Description**: Replace inline resolution logic with centralized NodeResolver.

**Implementation Notes**:
- Replace `_resolve_node()` calls with `resolve_node_interactive()` or `resolve_node_auto()`
- Add `--no-interactive` / `-n` flag to all node-accepting commands
- Keep backward compatibility with full node IDs

**Commands to Update**:
1. `mu impact <node>` - uses `_resolve_node()` at line 238
2. `mu ancestors <node>` - uses `_resolve_node()` at line 378
3. `mu read <node_id>` - inline resolution at line 454-470
4. Any other commands with node arguments

**Acceptance Criteria**:
- [x] `mu impact` uses NodeResolver
- [x] `mu ancestors` uses NodeResolver
- [x] `mu read` uses NodeResolver
- [x] `--no-interactive` flag works on all updated commands
- [x] Full node IDs still work without disambiguation
- [x] Error messages helpful when node not found

**Status**: Complete

**Implementation**:
- Updated `src/mu/commands/graph.py`:
  - `impact` command: Added `--no-interactive/-n` and `--quiet/-q` flags
  - `ancestors` command: Added `--no-interactive/-n` and `--quiet/-q` flags
  - Removed legacy `_resolve_node()` function
- Updated `src/mu/commands/core.py`:
  - `read` command: Added `--no-interactive/-n` and `--quiet/-q` flags
  - Uses `resolve_node_for_command()` for resolution

**Quality Checks**:
- [x] ruff check passes
- [x] ruff format applied
- [x] mypy passes
- [x] Unit tests pass

---

### Task 4: Update Rust Daemon Resolution (Optional)
**File(s)**: `mu-daemon/src/muql/executor.rs`

**Description**: Add source-over-test preference to Rust daemon's node resolution.

**Implementation Notes**:
- The Rust daemon currently doesn't have a `resolve_node_id()` function
- Node resolution happens implicitly through MUQL queries
- May need to add resolution at the HTTP handler level

**Discovery Note**: The Rust daemon doesn't appear to have explicit node resolution logic. The executor at `mu-daemon/src/muql/executor.rs` works directly with node IDs from graph operations.

**Acceptance Criteria**:
- [ ] Investigate if Rust daemon needs explicit resolution
- [ ] If needed: add `is_test_path()` helper function
- [ ] If needed: add source preference sorting in node lookup
- [ ] Maintain performance (< 10ms for resolution)

---

### Task 5: Add Resolution Info to CLI Output
**File(s)**: Commands that use NodeResolver

**Pattern**: Follow existing `print_info()` / `print_warning()` patterns

**Description**: Show disambiguation info when resolution was ambiguous.

**Example Output**:
```
$ mu deps PayoutService

Resolved 'PayoutService' -> class:src/Services/PayoutService.cs:PayoutService
  (2 other matches: PayoutServiceTests, PayoutServiceMock)

Dependencies:
  -> IPaymentGateway
  -> ILogger<PayoutService>
```

**Acceptance Criteria**:
- [x] Resolution info shown when `was_ambiguous=True`
- [x] Info suppressed with `--quiet` flag
- [x] JSON output includes `resolution` metadata
- [x] Consistent format across all commands

**Status**: Complete

**Implementation**:
- `print_resolution_info()` displays:
  - Resolved reference and target node ID
  - Count of alternative matches
  - Names of up to 3 alternatives
- `format_resolution_for_json()` provides structured metadata
- `--quiet/-q` flag suppresses resolution info on all updated commands
- Resolution info integrated into `resolve_node_for_command()`

---

### Task 6: Unit Tests for NodeResolver
**File(s)**: `tests/unit/test_resolver.py` (new file)

**Pattern**: Follow `tests/unit/test_kernel.py` fixture patterns

**Description**: Comprehensive unit tests for NodeResolver class.

**Test Cases**:
1. Exact ID match returns immediately
2. PREFER_SOURCE selects source over test
3. STRICT raises on ambiguity
4. INTERACTIVE calls callback
5. NodeNotFoundError on no matches
6. Fuzzy match as fallback
7. Test detection for all supported languages

**Acceptance Criteria**:
- [ ] `TestNodeResolver` class with strategy tests
- [ ] `TestIsTestNode` class with language-specific path tests
- [ ] Mock MUbase fixture with duplicate nodes
- [ ] All tests pass in CI
- [ ] Coverage > 90% for resolver.py

---

### Task 7: Integration Test - Regression Test
**File(s)**: `tests/integration/test_node_resolution.py` (new file)

**Description**: End-to-end test that recreates the original bug scenario.

**Test Scenario**:
1. Create MUbase with `PayoutService` and `PayoutServiceTests`
2. Run `mu deps PayoutService`
3. Assert source file is selected, not test

**Acceptance Criteria**:
- [ ] Test recreates exact scenario from bug report
- [ ] Test marked with `@pytest.mark.regression`
- [ ] Test uses actual CLI or resolver pipeline
- [ ] Test passes in CI

---

## Dependencies

```
Task 1 (NodeResolver)
    |
    +---> Task 2 (CLI Disambiguation)
    |         |
    |         +---> Task 3 (Update Commands)
    |                   |
    |                   +---> Task 5 (Output Enhancement)
    |
    +---> Task 6 (Unit Tests)
              |
              +---> Task 7 (Integration Test)

Task 4 (Rust Daemon) --- Independent track, can run in parallel
```

## Implementation Order

| Priority | Task | Effort | Risk | Notes |
|----------|------|--------|------|-------|
| P0 | Task 1: NodeResolver | 2h | Low | New file, well-defined interface |
| P0 | Task 6: Unit Tests | 1h | Low | Write alongside Task 1 |
| P1 | Task 2: CLI Disambiguation | 1.5h | Low | Builds on Task 1 |
| P1 | Task 3: Update Commands | 2h | Medium | Touches multiple files |
| P2 | Task 5: Output Enhancement | 1h | Low | Polish after core works |
| P2 | Task 7: Integration Test | 30m | Low | Regression coverage |
| P3 | Task 4: Rust Daemon | 1.5h | Medium | May not be needed |

**Estimated Total**: 9.5 hours

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Only test files match | Return test file (it's the only option) |
| Multiple source files match | Prefer shorter path, then alphabetical |
| Node name is substring of another | Exact match wins over suffix match |
| Same name in different modules | Show module path in disambiguation |
| Piped input (non-TTY) | Use PREFER_SOURCE, no interactive prompt |
| Empty node reference | Raise NodeNotFoundError with helpful message |
| Special characters in name | SQL escaping prevents injection |

## Security Considerations

- SQL escaping in `_find_candidates()` to prevent injection
- No user input passed directly to shell commands
- Node IDs validated before file system operations in `read` command

## Rollback Plan

If issues arise:
1. Add `MU_LEGACY_RESOLUTION=1` environment variable
2. Add `--legacy-resolution` flag to commands
3. Feature flag in `.murc.toml` for gradual rollout
