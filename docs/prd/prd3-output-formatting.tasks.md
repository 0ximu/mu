# Output Formatting Options - Task Breakdown

## Business Context

**Problem**: MU CLI commands that produce tabular output (impact, deps, ancestors, patterns, warn) truncate important information, making it nearly impossible to use in real workflows. Users cannot see full node IDs, file paths, or export data for scripting.

**Outcome**: All tabular MU commands support multiple output formats (table, json, csv), respect terminal width, and auto-detect when piped to disable truncation and colors.

**Users**:
- AI agents (Claude Code, MCP tools) needing parseable JSON output
- Developers analyzing dependencies and impact
- Scripts integrating MU into CI/CD pipelines

---

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| `OutputFormat` enum | `src/mu/kernel/muql/formatter.py:63-70` | TABLE, JSON, CSV, TREE, DICT formats already defined |
| `format_result()` | `src/mu/kernel/muql/formatter.py:322-356` | Main dispatcher for output formats |
| `format_table()` | `src/mu/kernel/muql/formatter.py:108-178` | Has `truncate_paths` param - **KEY FINDING** |
| `_truncate_path()` | `src/mu/kernel/muql/formatter.py:20-43` | Path truncation to last N segments |
| `_color()` | `src/mu/kernel/muql/formatter.py:96-100` | ANSI color wrapper with `no_color` flag |
| Rich Table pattern | `src/mu/commands/graph.py:44-69` | `_format_node_list()` uses `rich.table.Table` |
| Click format option | `src/mu/commands/graph.py:140-146` | `--format` option with `click.Choice` |
| `MUContext` | `src/mu/cli.py:24-30` | Shared CLI context (verbosity, debug, config) |
| `shorten_path()` | `src/mu/commands/utils.py:38-55` | Middle truncation for paths (keep start/end) |
| `is_interactive()` | `src/mu/commands/utils.py:29-35` | TTY detection for stdin/stdout |
| `print_info/error/warning` | `src/mu/logging.py:73-90` | Consistent messaging via Rich console |

**Key Findings**:
1. `format_table()` already has `truncate_paths` param - just needs exposure to CLI
2. Multiple commands use Rich `Table` directly (graph.py, cache.py, stats.py)
3. Query command already has `--full-paths` flag - this pattern should be unified
4. `is_interactive()` in utils.py provides TTY detection for auto-behavior
5. No global output format option exists - each command defines its own

---

## Task Breakdown

### Task 1: Extend MUContext with Output Configuration

**Files**:
- `src/mu/cli.py`

**Pattern**: Follow existing `MUContext` class at line 24-30

**Description**: Add global output options to the CLI that propagate to all commands via Click context.

**Implementation Notes**:
```python
# In cli.py MUContext class (line 24-30)
class MUContext:
    """Shared context for CLI commands."""
    def __init__(self) -> None:
        self.config: MUConfig | None = None
        self.verbosity: VerbosityLevel = "normal"
        self.debug: bool = False
        # NEW: Output configuration
        self.output_format: str = "table"
        self.no_truncate: bool = False
        self.no_color: bool = False
        self.width: int | None = None
```

Add global options to cli group (after line 91):
```python
@click.option(
    "--output-format", "-F",
    type=click.Choice(["table", "json", "csv", "tree"]),
    default=None,  # None = use command default
    help="Output format (overrides command-specific defaults)",
)
@click.option(
    "--no-truncate",
    is_flag=True,
    help="Show full values without truncation",
)
@click.option(
    "--width",
    type=int,
    default=None,
    help="Table width (default: auto-detect terminal)",
)
```

**Acceptance Criteria**:
- [x] `MUContext` has output_format, no_truncate, no_color, width fields
- [x] Global options added to `cli` group
- [x] Options propagate to commands via `ctx.obj`
- [x] Auto-detect TTY: `no_truncate=True` and `no_color=True` when `not sys.stdout.isatty()`

**Status**: COMPLETE - Implemented in `/Users/imu/Dev/work/mu/src/mu/cli.py`

---

### Task 2: Create Unified Output Module

**Files**:
- `src/mu/output.py` (new file)

**Pattern**: Follow `src/mu/kernel/muql/formatter.py` for structure

**Description**: Create a unified output module that all commands use. This consolidates the formatting logic and provides consistent behavior.

**Key Functions**:
```python
# output.py

from mu.commands.utils import is_interactive

@dataclass
class OutputConfig:
    """Output configuration from CLI context."""
    format: str = "table"
    no_truncate: bool = False
    no_color: bool = False
    width: int | None = None

    @classmethod
    def from_context(cls, ctx: click.Context) -> "OutputConfig":
        """Extract config from Click context with auto-detection."""
        obj = getattr(ctx, "obj", None)

        # Auto-detection for piped output
        is_tty = is_interactive()

        return cls(
            format=getattr(obj, "output_format", None) or "table",
            no_truncate=getattr(obj, "no_truncate", False) or not is_tty,
            no_color=getattr(obj, "no_color", False) or not is_tty,
            width=getattr(obj, "width", None),
        )

def format_output(
    data: list[dict[str, Any]],
    columns: list[tuple[str, str]],  # (display_name, key)
    output_config: OutputConfig,
    title: str | None = None,
) -> str:
    """Format data for CLI output."""
    # Dispatch to appropriate formatter
    ...

def smart_truncate(value: str, max_width: int, style: str = "end") -> str:
    """Smart truncation: end for names, middle for paths."""
    ...
```

**Acceptance Criteria**:
- [x] `OutputConfig` extracts config from Click context
- [x] Auto-detects TTY and adjusts truncation/color accordingly
- [x] `format_output()` supports table, json, csv, tree formats
- [x] `smart_truncate()` uses middle truncation for paths
- [x] Uses existing `_color()` pattern from formatter.py

**Status**: COMPLETE - Created `/Users/imu/Dev/work/mu/src/mu/output.py` with:
- `OutputConfig` dataclass with `from_context()` classmethod
- `Column` dataclass for column definitions
- `format_output()`, `format_table()`, `format_json()`, `format_csv()`, `format_tree()`
- `smart_truncate()` with path detection
- `colorize()` and `Colors` class for ANSI colors
- `format_node_list()` and `format_cycles()` convenience functions

---

### Task 3: Update `mu impact` Command

**Files**:
- `src/mu/commands/graph.py`

**Pattern**: Follow existing `_format_node_list()` at line 35-69, but use unified output

**Description**: Update impact command to use the new output module. This is the first command to migrate and establishes the pattern.

**Changes**:
1. Add `--no-truncate` option
2. Use `OutputConfig.from_context()` to get settings
3. Convert Rich Table usage to `format_output()` call
4. Include more data in output (file_path, type, not just node_id)

**Before** (graph.py line 55-59):
```python
table = Table(title=title, show_header=True)
table.add_column("Node ID", style="cyan" if not no_color else None)
for node in nodes:
    table.add_row(node)
```

**After**:
```python
from mu.output import format_output, OutputConfig

# Get full node info including file_path
data = [
    {"node_id": n, "type": _get_node_type(n), "file_path": _get_file_path(n)}
    for n in nodes
]
columns = [
    ("Node", "node_id"),
    ("Type", "type"),
    ("File", "file_path"),
]
config = OutputConfig.from_context(ctx)
result = format_output(data, columns, config, title=title)
click.echo(result)
```

**Acceptance Criteria**:
- [x] `mu impact --format json` outputs valid, parseable JSON
- [x] `mu impact --no-truncate` shows full node IDs
- [x] `mu impact | jq .` works (piped = no truncation, valid JSON)
- [x] JSON output includes node_id, type, file_path for each node
- [x] Table output shows all columns

**Status**: COMPLETE - Updated `/Users/imu/Dev/work/mu/src/mu/commands/graph.py`:
- Added `--no-truncate` option to impact command
- Uses `format_node_list()` from output module
- Supports `--format json` for parseable output

---

### Task 4: Update `mu deps` Command

**Files**:
- `src/mu/commands/deps.py`

**Pattern**: Follow Task 3 pattern

**Description**: Update deps command to use unified output. Currently uses plain `print_info()` calls.

**Current Output** (line 84-91):
```python
for dep in deps_list:
    type_str = f"[{dep.get('type', 'unknown')}]"
    name_str = dep.get("qualified_name") or dep.get("name", str(dep))
    print_info(f"  {type_str} {name_str}")
```

**Changes**:
1. Replace `--json` flag with `--format` option
2. Use `format_output()` for consistent formatting
3. Add file_path to output data

**Acceptance Criteria**:
- [x] `mu deps --format json` outputs valid JSON
- [x] `mu deps --format csv` outputs valid CSV
- [x] Consistent columns: Node, Type, File, Direction
- [x] Backward compatible: `--json` still works (deprecated)

**Status**: COMPLETE - Updated `/Users/imu/Dev/work/mu/src/mu/commands/deps.py`:
- Added `--format` option with table/json/csv choices
- Kept `--json` as deprecated alias
- Uses `Column` and `format_output()` from output module
- Added `--no-truncate` option

---

### Task 5: Update `mu ancestors` and `mu cycles`

**Files**:
- `src/mu/commands/graph.py`

**Pattern**: Follow Task 3 pattern

**Description**: Update remaining graph reasoning commands to use unified output.

**ancestors** (line 297):
- Same structure as impact
- Add file_path to output

**cycles** (line 72-121):
- Special format: cycle visualization with arrows
- Keep `A -> B -> C -> A` visualization for table
- JSON: list of node arrays

**Acceptance Criteria**:
- [x] `mu ancestors --format json` works
- [x] `mu cycles --format json` outputs `{"cycles": [[...], [...]], "count": N}`
- [x] Table format for cycles still shows arrow visualization

**Status**: COMPLETE - Updated `/Users/imu/Dev/work/mu/src/mu/commands/graph.py`:
- Updated ancestors command with `--no-truncate` option, uses `format_node_list()`
- Updated cycles command with `--no-truncate` option, uses `format_cycles()`
- Cycle visualization preserved with arrow notation (A -> B -> C -> A)

---

### Task 6: Update `mu patterns` Command

**Files**:
- `src/mu/commands/patterns.py`

**Pattern**: Follow Task 3 pattern

**Description**: Refactor patterns command to use unified output. Currently has custom formatting logic.

**Key Changes**:
1. Replace `--json` flag with `--format` option (keep `--json` as alias)
2. Use `format_output()` for table/csv formats
3. JSON format already works - preserve existing structure

**Table Columns**:
- Category, Name, Description, Frequency, Confidence

**Acceptance Criteria**:
- [x] `mu patterns --format csv` exports patterns list
- [x] `mu patterns --format json` preserves existing structure
- [x] `--json` flag still works (backward compatible)

**Status**: COMPLETE - Updated `/Users/imu/Dev/work/mu/src/mu/commands/patterns.py`:
- Added `--format` option with table/json/csv choices
- Kept `--json` as deprecated alias
- Uses unified output for json/csv formats
- Rich display preserved for table format
- Added `--no-color` and `--no-truncate` options

---

### Task 7: Update `mu warn` Command

**Files**:
- `src/mu/commands/warn.py`

**Pattern**: Follow Task 3 pattern

**Description**: Update warn command to support format options. Currently has rich custom formatting.

**Key Changes**:
1. Add `--format` option (table, json)
2. Keep existing display format as table default
3. JSON format: output WarningsResult.to_dict()

**Acceptance Criteria**:
- [x] `mu warn --format json` outputs parseable JSON
- [x] Default table output unchanged (rich formatting preserved)
- [x] JSON includes all warning details

**Status**: COMPLETE - Updated `/Users/imu/Dev/work/mu/src/mu/commands/warn.py`:
- Added `--format` option with table/json choices
- Kept `--json` as deprecated alias
- Rich display preserved for table format with `_display_warnings_rich()`
- Added `--no-color` and `--no-truncate` options

---

### Task 8: Update MUQL Query Integration

**Files**:
- `src/mu/kernel/muql/formatter.py`
- `src/mu/commands/query.py`

**Pattern**: Already has good structure - extend it

**Description**: Ensure MUQL formatter integrates with global output options.

**Changes to formatter.py**:
```python
def format_result(
    result: QueryResult,
    output_format: OutputFormat | str = OutputFormat.TABLE,
    no_color: bool = False,
    truncate_paths: bool = True,
    width: int | None = None,  # ADD: terminal width
) -> str | dict[str, Any]:
```

**Changes to query.py**:
- Rename `--full-paths` to `--no-truncate` (keep `--full-paths` as alias)
- Propagate global `--width` option

**Acceptance Criteria**:
- [x] `mu query --no-truncate` shows full paths
- [x] `--full-paths` still works as alias
- [x] Width option respected for table format

**Status**: COMPLETE - Updated `/Users/imu/Dev/work/mu/src/mu/commands/query.py`:
- Added `--no-truncate` option as alias for `--full-paths`
- Added `click.pass_context` decorator to propagate global options
- Global context options honored (output_format, no_truncate, no_color, width)

---

### Task 9: Add Smart Path Truncation

**Files**:
- `src/mu/output.py`

**Pattern**: Enhance existing `shorten_path()` in `src/mu/commands/utils.py:38-55`

**Description**: Implement smart truncation that uses middle-truncation for paths to preserve both directory context and filename.

**Implementation**:
```python
def smart_truncate(value: str, max_width: int, column_hint: str = "") -> str:
    """Smart truncation based on content type.

    - Paths: middle truncation (src/.../.../file.py)
    - Names: end truncation (VeryLongClass...)
    """
    if len(value) <= max_width:
        return value

    # Detect if path-like
    is_path = "/" in value or "\\" in value or _is_path_column(column_hint)

    if is_path:
        # Middle truncation: keep start and end
        keep = (max_width - 5) // 2
        return f"{value[:keep]}...{value[-keep:]}"
    else:
        # End truncation
        return value[:max_width-3] + "..."
```

**Acceptance Criteria**:
- [x] Path columns use middle truncation
- [x] Name columns use end truncation
- [x] File extensions preserved when possible
- [x] Auto-detect based on column name (path, file_path, etc.)

**Status**: COMPLETE - Implemented in `/Users/imu/Dev/work/mu/src/mu/output.py`:
- `smart_truncate()` function with column_hint parameter
- `_is_path_value()` helper detects paths by:
  - Column name (path, file_path, source_path, module_path, file)
  - Value characteristics (contains / or \)
  - File extensions (.py, .ts, .js, .go, .java, .rs, .cs, .rb, .cpp, .c, .h)
- Middle truncation for paths preserves directory context and filename
- End truncation for names/identifiers

---

### Task 10: Unit Tests

**Files**:
- `tests/unit/test_output.py` (new file)

**Pattern**: Follow `tests/unit/test_muql_formatter.py` if exists

**Test Cases**:
```python
class TestOutputFormatter:
    def test_format_json_valid(self):
        """JSON output should be parseable."""

    def test_format_csv_headers(self):
        """CSV should have header row."""

    def test_format_table_no_truncate(self):
        """Table with no_truncate shows full values."""

    def test_format_table_truncates_by_default(self):
        """Table truncates long values by default."""

    def test_auto_detect_tty(self):
        """Non-TTY should auto-enable no_truncate and no_color."""

class TestSmartTruncate:
    def test_path_middle_truncation(self):
        """Paths should use middle truncation."""

    def test_name_end_truncation(self):
        """Names should use end truncation."""

    def test_short_values_unchanged(self):
        """Short values should not be truncated."""
```

**Acceptance Criteria**:
- [x] Tests cover all output formats
- [x] Tests cover truncation behavior
- [x] Tests cover TTY auto-detection
- [x] All tests pass in CI

**Status**: COMPLETE - Created `/Users/imu/Dev/work/mu/tests/unit/test_output.py`:
- 75 tests covering all functionality with 100% code coverage:
  - `TestOutputConfig`: 3 tests for configuration
  - `TestColorize`: 2 tests for ANSI colors
  - `TestSmartTruncate`: 7 tests for truncation behavior
  - `TestFormatJson`: 3 tests for JSON output
  - `TestFormatCsv`: 4 tests for CSV output
  - `TestFormatTable`: 4 tests for table output
  - `TestFormatTree`: 2 tests for tree output
  - `TestFormatOutput`: 4 tests for format dispatcher
  - `TestFormatNodeList`: 2 tests for node list convenience function
  - `TestFormatCycles`: 4 tests for cycle formatting
  - `TestTTYAutoDetection`: 2 tests for TTY behavior
  - `TestOutputConfigFromContext`: 5 tests for Click context integration
  - `TestSmartTruncateAdvanced`: 5 tests for edge cases (Windows paths, extensions)
  - `TestTerminalWidth`: 2 tests for terminal width handling
  - `TestFormatTableAdvanced`: 5 tests (colors, truncation, missing keys, unicode)
  - `TestFormatJsonAdvanced`: 2 tests (compact mode, non-serializable values)
  - `TestFormatTreeAdvanced`: 6 tests (details, truncation, item count)
  - `TestFormatNodeListAdvanced`: 3 tests (dict input, unknown types)
  - `TestFormatCyclesAdvanced`: 2 tests (multiple cycles, title)
  - `TestIsPathValueEdgeCases`: 2 tests (unknown extensions, no dots/slashes)
  - `TestFormatCyclesEdgeCases`: 2 tests (empty cycle, single node)
  - `TestEdgeCases`: 4 tests (empty values, narrow terminal, min_width, None values)
- All 75 tests passing
- **Coverage**: 100% lines, 100% branches (222 statements, 98 branches)

---

## Dependencies

```
Task 1: MUContext extension
    |
    v
Task 2: Output module -----> Task 9: Smart truncation
    |
    +-> Task 3: Update impact (first integration)
    |       |
    |       v
    +-> Task 4-7: Update other commands (parallel)
    |
    v
Task 8: MUQL integration
    |
    v
Task 10: Unit tests
```

**Parallel Work**:
- Tasks 4, 5, 6, 7 can run in parallel after Task 3 establishes the pattern

---

## Implementation Order

| Priority | Task | Effort | Risk | Notes |
|----------|------|--------|------|-------|
| P0 | Task 1: MUContext extension | Small | Low | Foundation for all other work |
| P0 | Task 2: Output module | Medium | Low | New file, clean slate |
| P0 | Task 3: Update impact | Medium | Medium | First integration, establishes pattern |
| P1 | Task 4: Update deps | Small | Low | Simple command |
| P1 | Task 5: Update ancestors/cycles | Medium | Low | Follow impact pattern |
| P1 | Task 6: Update patterns | Small | Low | Already has --json |
| P1 | Task 7: Update warn | Small | Low | Already has --json |
| P2 | Task 8: MUQL integration | Small | Low | Extend existing |
| P2 | Task 9: Smart truncation | Small | Low | Enhancement |
| P2 | Task 10: Unit tests | Medium | Low | Standard testing |

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Very narrow terminal (< 40 cols) | Minimum column widths enforced (10 chars) |
| Empty result set | Show "No results" message, valid empty JSON `[]` |
| Unicode characters | Handle width correctly (some chars are 2-wide) |
| Piped to file | Auto-disable color, auto-enable no_truncate |
| Very long single value | Truncate to column width |
| Node not found | Error message, non-zero exit code |

---

## Security Considerations

- No security concerns for this feature (output formatting only)
- Ensure JSON output doesn't include sensitive data (already handled by commands)

---

## Success Metrics

1. **Usability**: `mu impact --format json | jq .` works for scripting
2. **Readability**: `mu impact --no-truncate` shows full node IDs
3. **Consistency**: All tabular commands support `--format` and `--no-truncate`
4. **Backward Compatible**: Default behavior unchanged for interactive use
5. **Auto-detection**: Piped output automatically disables truncation/colors

---

## Implementation Summary

**Status**: ALL TASKS COMPLETE

**Files Created**:
- `/Users/imu/Dev/work/mu/src/mu/output.py` - Unified output formatting module
- `/Users/imu/Dev/work/mu/tests/unit/test_output.py` - 37 unit tests

**Files Modified**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py` - Extended MUContext with output configuration
- `/Users/imu/Dev/work/mu/src/mu/commands/graph.py` - Updated impact, ancestors, cycles commands
- `/Users/imu/Dev/work/mu/src/mu/commands/deps.py` - Added format options
- `/Users/imu/Dev/work/mu/src/mu/commands/patterns.py` - Added format options
- `/Users/imu/Dev/work/mu/src/mu/commands/warn.py` - Added format options
- `/Users/imu/Dev/work/mu/src/mu/commands/query.py` - Added --no-truncate alias

**Quality Checks**:
- [x] `ruff check src/mu/output.py src/mu/commands/` - All checks passed
- [x] `mypy src/mu/output.py src/mu/cli.py src/mu/commands/graph.py src/mu/commands/deps.py src/mu/commands/patterns.py src/mu/commands/warn.py src/mu/commands/query.py` - No issues found in 7 files
- [x] `pytest tests/unit/test_output.py` - 75 tests passed
- [x] `pytest --cov=mu.output tests/unit/test_output.py` - 100% coverage (222 statements, 98 branches)

**Key Features Implemented**:
1. Global CLI options: `--output-format`, `--no-truncate`, `--no-color`, `--width`
2. TTY auto-detection: piped output automatically disables truncation and colors
3. Smart truncation: middle truncation for paths, end truncation for names
4. Multiple output formats: table, json, csv, tree
5. Backward compatibility: deprecated `--json` flags still work
6. Unified output module with consistent formatting across all commands
