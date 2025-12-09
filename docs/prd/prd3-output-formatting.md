# PRD: Output Formatting Options

## Business Context

### Problem Statement
MU's CLI output, particularly for commands like `mu impact`, truncates important information making it nearly impossible to use:

```
$ mu impact PayoutService
Node                     | Impact
PayoutServiceTest...     | 0.85
InvoicesApiFunct...      | 0.72
TransactionProce...      | 0.68
```

**Problems observed**:
1. Node IDs/names truncated with `...` - users can't see what was actually matched
2. File paths clipped - can't distinguish between similar nodes in different directories
3. No way to get full output - no `--no-truncate` or `--format json` options
4. Table width doesn't adapt to terminal size
5. Rich table rendering prioritizes aesthetics over usability

**User Impact**: The output is decorative but not functional. Users must re-run queries with different tools (grep, MUQL) to get usable data.

### Outcome
All MU commands that produce tabular output should:
1. Support multiple output formats (`table`, `json`, `csv`, `tree`)
2. Respect terminal width OR allow `--no-truncate`
3. Provide `--format json` for programmatic access
4. Show full information by default when piped

### Users
- AI agents (Claude Code) that need parseable output
- Developers analyzing impact/dependencies
- Scripts integrating MU into CI/CD pipelines

---

## Discovery Phase

**IMPORTANT**: Before implementing, the agent MUST first explore:

1. **Where output formatting currently lives**
   ```
   mu context "how does mu format CLI output tables"
   ```

2. **What formatting already exists**
   ```
   mu query "SELECT file_path, name FROM functions WHERE name LIKE '%format%'"
   ```

3. **Which commands produce tabular output**
   ```bash
   grep -rn "table\|format" src/mu/commands/*.py | head -30
   ```

### Expected Discovery Locations

| Component | Likely Location | What to Look For |
|-----------|-----------------|------------------|
| Table formatting | `src/mu/kernel/muql/formatter.py` | `format_table()`, `OutputFormat` enum |
| CLI output helpers | `src/mu/commands/_utils.py` | Shared formatting utilities |
| Rich/Click integration | Various command files | `click.echo()`, `rich.table` |
| Rust formatter | `mu-daemon/src/server/http.rs` | Export format functions |

---

## Existing Patterns Found

From codebase.mu analysis:

| Pattern | File | Relevance |
|---------|------|-----------|
| `OutputFormat` enum | `src/mu/kernel/muql/formatter.py` | TABLE, JSON, CSV, TREE, DICT formats |
| `format_table()` | `src/mu/kernel/muql/formatter.py` | Main table formatting (complexity noted) |
| `format_csv()` | `src/mu/kernel/muql/formatter.py` | CSV output exists |
| `format_result()` | `src/mu/kernel/muql/formatter.py` | Dispatcher for formats |
| `Colors` class | `src/mu/kernel/muql/formatter.py` | ANSI color codes |
| `truncate_paths` param | `src/mu/kernel/muql/formatter.py` | Truncation is configurable! |

**Key Finding**: `format_table()` already has a `truncate_paths` parameter! The issue is that commands aren't exposing this option to users.

---

## Task Breakdown

### Task 1: Add Global Output Format Options to CLI

**File(s)**: `src/mu/cli.py` (main CLI entry point)

**Discovery First**:
```bash
head -50 src/mu/cli.py
```

**Description**: Add global options that all commands inherit for output formatting.

```python
import click
import sys

# Global context settings
class OutputConfig:
    """Configuration for output formatting."""
    def __init__(self):
        self.format: str = "table"
        self.no_truncate: bool = False
        self.no_color: bool = False
        self.width: int | None = None  # Auto-detect if None

pass_output_config = click.make_pass_decorator(OutputConfig, ensure=True)


@click.group()
@click.option(
    "--format", "-f",
    type=click.Choice(["table", "json", "csv", "tree"]),
    default="table",
    help="Output format (default: table)",
)
@click.option(
    "--no-truncate",
    is_flag=True,
    help="Don't truncate long values in table output",
)
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable colored output",
)
@click.option(
    "--width",
    type=int,
    default=None,
    help="Table width (default: auto-detect terminal width)",
)
@click.pass_context
def cli(ctx, format: str, no_truncate: bool, no_color: bool, width: int | None):
    """MU - Machine Understanding for codebases."""
    ctx.ensure_object(OutputConfig)
    ctx.obj.format = format
    ctx.obj.no_truncate = no_truncate
    ctx.obj.no_color = no_color
    ctx.obj.width = width
    
    # Auto-detect: disable truncation when output is piped
    if not sys.stdout.isatty():
        ctx.obj.no_truncate = True
        ctx.obj.no_color = True
```

**Acceptance Criteria**:
- [ ] `--format` option available on all commands
- [ ] `--no-truncate` option available
- [ ] `--no-color` option available
- [ ] `--width` option available
- [ ] Auto-disable truncation when piped

---

### Task 2: Create Unified Output Helper

**File(s)**: `src/mu/output.py` (new file)

**Description**: Centralized output formatting that all commands use.

```python
"""Unified output formatting for MU CLI commands.

This module provides consistent output formatting across all commands,
supporting multiple formats and respecting user preferences.
"""

import json
import sys
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import Any

import click


class OutputFormat(Enum):
    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    TREE = "tree"


@dataclass
class Column:
    """Definition of a table column."""
    name: str
    key: str  # Key to extract from row dict
    width: int | None = None  # None = auto
    align: str = "left"  # left, right, center
    truncate: bool = True  # Whether this column can be truncated


@dataclass
class OutputConfig:
    """Output configuration from CLI options."""
    format: OutputFormat = OutputFormat.TABLE
    no_truncate: bool = False
    no_color: bool = False
    width: int | None = None
    
    @classmethod
    def from_context(cls, ctx: click.Context) -> "OutputConfig":
        """Extract config from Click context."""
        obj = ctx.obj or {}
        return cls(
            format=OutputFormat(obj.get("format", "table")),
            no_truncate=obj.get("no_truncate", False),
            no_color=obj.get("no_color", False),
            width=obj.get("width"),
        )
    
    @property
    def effective_width(self) -> int:
        """Get effective terminal width."""
        if self.width:
            return self.width
        try:
            return shutil.get_terminal_size().columns
        except Exception:
            return 120  # Fallback


class OutputFormatter:
    """Formats data for CLI output."""
    
    def __init__(self, config: OutputConfig):
        self.config = config
    
    def format(
        self,
        data: list[dict[str, Any]],
        columns: list[Column],
        title: str | None = None,
    ) -> str:
        """Format data according to configured output format."""
        if self.config.format == OutputFormat.JSON:
            return self._format_json(data)
        elif self.config.format == OutputFormat.CSV:
            return self._format_csv(data, columns)
        elif self.config.format == OutputFormat.TREE:
            return self._format_tree(data, columns, title)
        else:
            return self._format_table(data, columns, title)
    
    def _format_json(self, data: list[dict[str, Any]]) -> str:
        """Format as JSON."""
        return json.dumps(data, indent=2, default=str)
    
    def _format_csv(self, data: list[dict[str, Any]], columns: list[Column]) -> str:
        """Format as CSV."""
        lines = []
        
        # Header
        lines.append(",".join(col.name for col in columns))
        
        # Rows
        for row in data:
            values = []
            for col in columns:
                value = str(row.get(col.key, ""))
                # Escape quotes and wrap if contains comma
                if "," in value or '"' in value:
                    value = '"' + value.replace('"', '""') + '"'
                values.append(value)
            lines.append(",".join(values))
        
        return "\n".join(lines)
    
    def _format_table(
        self,
        data: list[dict[str, Any]],
        columns: list[Column],
        title: str | None = None,
    ) -> str:
        """Format as ASCII table."""
        if not data:
            return "No results"
        
        # Calculate column widths
        col_widths = self._calculate_widths(data, columns)
        
        lines = []
        
        # Title
        if title:
            lines.append(self._colorize(title, "bold"))
            lines.append("")
        
        # Header
        header_parts = []
        for col, width in zip(columns, col_widths):
            header_parts.append(self._pad(col.name, width, col.align))
        
        header = " │ ".join(header_parts)
        lines.append(self._colorize(header, "bold"))
        
        # Separator
        sep_parts = ["─" * w for w in col_widths]
        lines.append("─┼─".join(sep_parts))
        
        # Rows
        for row in data:
            row_parts = []
            for col, width in zip(columns, col_widths):
                value = str(row.get(col.key, ""))
                
                # Truncate if needed
                if not self.config.no_truncate and col.truncate and len(value) > width:
                    value = value[:width-3] + "..."
                
                row_parts.append(self._pad(value, width, col.align))
            
            lines.append(" │ ".join(row_parts))
        
        # Footer
        lines.append("")
        lines.append(self._colorize(f"({len(data)} rows)", "dim"))
        
        return "\n".join(lines)
    
    def _format_tree(
        self,
        data: list[dict[str, Any]],
        columns: list[Column],
        title: str | None = None,
    ) -> str:
        """Format as tree structure."""
        lines = []
        
        if title:
            lines.append(self._colorize(title, "bold"))
        
        for i, row in enumerate(data):
            is_last = i == len(data) - 1
            prefix = "└── " if is_last else "├── "
            
            # Primary column (first)
            primary = str(row.get(columns[0].key, ""))
            lines.append(f"{prefix}{primary}")
            
            # Secondary columns as indented details
            indent = "    " if is_last else "│   "
            for col in columns[1:]:
                value = row.get(col.key)
                if value is not None:
                    lines.append(f"{indent}{col.name}: {value}")
        
        return "\n".join(lines)
    
    def _calculate_widths(
        self,
        data: list[dict[str, Any]],
        columns: list[Column],
    ) -> list[int]:
        """Calculate column widths based on content and terminal size."""
        available = self.config.effective_width - (len(columns) - 1) * 3  # Account for separators
        
        # Start with header widths
        widths = [len(col.name) for col in columns]
        
        # Expand based on content (up to a max)
        for row in data:
            for i, col in enumerate(columns):
                value = str(row.get(col.key, ""))
                widths[i] = max(widths[i], min(len(value), 60))
        
        # If total exceeds available, scale down proportionally
        total = sum(widths)
        if total > available and not self.config.no_truncate:
            scale = available / total
            widths = [max(10, int(w * scale)) for w in widths]
        
        return widths
    
    def _pad(self, value: str, width: int, align: str) -> str:
        """Pad value to width with alignment."""
        if len(value) > width:
            value = value[:width]
        
        if align == "right":
            return value.rjust(width)
        elif align == "center":
            return value.center(width)
        else:
            return value.ljust(width)
    
    def _colorize(self, text: str, style: str) -> str:
        """Apply ANSI color if enabled."""
        if self.config.no_color:
            return text
        
        codes = {
            "bold": "\033[1m",
            "dim": "\033[2m",
            "red": "\033[31m",
            "green": "\033[32m",
            "yellow": "\033[33m",
            "blue": "\033[34m",
            "reset": "\033[0m",
        }
        
        code = codes.get(style, "")
        reset = codes["reset"]
        
        return f"{code}{text}{reset}" if code else text


def output(
    data: list[dict[str, Any]],
    columns: list[Column | tuple[str, str]],
    title: str | None = None,
    ctx: click.Context | None = None,
):
    """Convenience function for outputting formatted data.
    
    Args:
        data: List of row dictionaries
        columns: Column definitions (can be tuples of (name, key))
        title: Optional title
        ctx: Click context (for getting format options)
    
    Example:
        output(
            data=[{"name": "foo", "score": 0.9}],
            columns=[("Name", "name"), ("Score", "score")],
            ctx=ctx,
        )
    """
    # Convert tuple columns to Column objects
    col_objs = []
    for col in columns:
        if isinstance(col, tuple):
            col_objs.append(Column(name=col[0], key=col[1]))
        else:
            col_objs.append(col)
    
    # Get config
    if ctx:
        config = OutputConfig.from_context(ctx)
    else:
        # Defaults with auto-detection
        config = OutputConfig(
            no_truncate=not sys.stdout.isatty(),
            no_color=not sys.stdout.isatty(),
        )
    
    formatter = OutputFormatter(config)
    result = formatter.format(data, col_objs, title)
    click.echo(result)
```

**Acceptance Criteria**:
- [ ] `OutputFormatter` supports table, json, csv, tree formats
- [ ] Table format respects `no_truncate` option
- [ ] JSON format outputs valid, parseable JSON
- [ ] Auto-detects terminal width
- [ ] Colors disabled when piped

---

### Task 3: Update `mu impact` Command

**File(s)**: `src/mu/commands/impact.py` (or wherever impact lives)

**Discovery First**:
```bash
grep -rn "impact" src/mu/commands/
```

**Description**: Update the impact command to use the new output formatter.

**Before** (likely):
```python
@click.command()
@click.argument("node")
def impact(node: str):
    # ... get impact data ...
    
    # Old: Using Rich or manual formatting
    table = Table()
    table.add_column("Node")
    table.add_column("Impact")
    for item in results:
        table.add_row(item.node[:30] + "...", str(item.impact))  # Truncated!
    console.print(table)
```

**After**:
```python
from mu.output import output, Column

@click.command()
@click.argument("node")
@click.pass_context
def impact(ctx, node: str):
    """Analyze impact of changes to a node."""
    # ... get impact data ...
    
    # Format results as list of dicts
    data = [
        {
            "node_id": item.node_id,
            "node_name": item.name,
            "file_path": item.file_path,
            "impact_score": round(item.impact, 3),
            "type": item.type,
        }
        for item in results
    ]
    
    # Define columns with appropriate settings
    columns = [
        Column(name="Node", key="node_name", truncate=True),
        Column(name="Type", key="type", width=10, truncate=False),
        Column(name="Impact", key="impact_score", width=8, align="right", truncate=False),
        Column(name="File", key="file_path", truncate=True),
    ]
    
    output(data, columns, title=f"Impact Analysis: {node}", ctx=ctx)
```

**Example Output (table, truncated)**:
```
Impact Analysis: PayoutService

Node                 │ Type     │  Impact │ File
─────────────────────┼──────────┼─────────┼────────────────────────────────
PayoutServiceTests   │ class    │   0.850 │ src/Services.Tests/PayoutSer...
InvoicesApiFunction  │ function │   0.720 │ src/Functions/InvoicesApiFun...
TransactionProcessor │ class    │   0.680 │ src/Services/TransactionProc...

(3 rows)
```

**Example Output (json)**:
```json
[
  {
    "node_id": "class:src/Services.Tests/PayoutServiceTests.cs:PayoutServiceTests",
    "node_name": "PayoutServiceTests",
    "file_path": "src/Services.Tests/PayoutServiceTests.cs",
    "impact_score": 0.85,
    "type": "class"
  },
  ...
]
```

**Acceptance Criteria**:
- [ ] `mu impact --format json` outputs valid JSON
- [ ] `mu impact --no-truncate` shows full node IDs
- [ ] `mu impact | jq .` works (piped = no truncation)
- [ ] Table adapts to terminal width

---

### Task 4: Update Other Tabular Commands

**File(s)**:
- `src/mu/commands/deps.py`
- `src/mu/commands/query.py`
- `src/mu/commands/warn.py`
- `src/mu/commands/patterns.py`
- Other commands producing tables

**Description**: Audit all commands that produce tabular output and update them to use the new formatter.

**Discovery First**:
```bash
grep -rn "Table\|table\|echo" src/mu/commands/*.py | grep -v "#"
```

**Commands to Update**:

| Command | Current Output | Columns to Include |
|---------|---------------|-------------------|
| `mu deps` | Table of dependencies | Node, Type, File, Direction |
| `mu impact` | Table of impacted nodes | Node, Type, Impact, File |
| `mu query` | MUQL results | Dynamic based on query |
| `mu warn` | Warnings table | Level, Message, File, Line |
| `mu patterns` | Detected patterns | Pattern, Count, Category |
| `mu stats` | Codebase statistics | Metric, Value |

**Acceptance Criteria**:
- [ ] All tabular commands support `--format`
- [ ] All tabular commands support `--no-truncate`
- [ ] Consistent column ordering across commands
- [ ] JSON output is consistently structured

---

### Task 5: Update MUQL Formatter Integration

**File(s)**: `src/mu/kernel/muql/formatter.py`

**Discovery First**:
```bash
head -100 src/mu/kernel/muql/formatter.py
```

**Description**: The existing `format_table()` already has `truncate_paths` - ensure it's exposed properly and integrates with the new output system.

**Changes**:
```python
# Ensure format_result() accepts all options
def format_result(
    result: QueryResult,
    output_format: OutputFormat | str = OutputFormat.TABLE,
    no_color: bool = False,
    no_truncate: bool = False,  # Add this parameter
    width: int | None = None,   # Add this parameter
) -> str | dict[str, Any]:
    """Format query result for output.
    
    Args:
        result: Query result to format
        output_format: Desired format
        no_color: Disable ANSI colors
        no_truncate: Disable truncation of long values
        width: Table width (None = auto-detect)
    """
    if isinstance(output_format, str):
        output_format = OutputFormat(output_format)
    
    if output_format == OutputFormat.JSON:
        return format_json(result)
    elif output_format == OutputFormat.CSV:
        return format_csv(result)
    elif output_format == OutputFormat.TREE:
        return format_tree(result, no_color=no_color)
    elif output_format == OutputFormat.DICT:
        return result_to_dict(result)
    else:
        return format_table(
            result, 
            no_color=no_color, 
            truncate_paths=not no_truncate,  # Invert flag
            width=width,
        )
```

**Acceptance Criteria**:
- [ ] `format_result()` accepts `no_truncate` parameter
- [ ] `mu query --no-truncate` works
- [ ] Existing MUQL formatting still works

---

### Task 6: Add Width Detection and Smart Truncation

**File(s)**: `src/mu/output.py` (enhance existing)

**Description**: Improve truncation to be smarter - truncate from the middle for paths, preserve important parts.

```python
def smart_truncate(value: str, max_width: int, style: str = "end") -> str:
    """Truncate value intelligently based on content type.
    
    Args:
        value: Value to truncate
        max_width: Maximum width
        style: Truncation style
            - "end": Truncate at end (default)
            - "middle": Truncate in middle (good for paths)
            - "start": Truncate at start
    
    Examples:
        smart_truncate("src/very/long/path/to/file.py", 30, "middle")
        # -> "src/very/.../to/file.py"
        
        smart_truncate("VeryLongClassName", 15, "end")
        # -> "VeryLongClas..."
    """
    if len(value) <= max_width:
        return value
    
    if max_width < 5:
        return value[:max_width]
    
    if style == "middle":
        # Keep start and end, truncate middle
        keep = (max_width - 3) // 2
        return value[:keep] + "..." + value[-keep:]
    
    elif style == "start":
        return "..." + value[-(max_width-3):]
    
    else:  # end
        return value[:max_width-3] + "..."


def detect_truncation_style(column_name: str) -> str:
    """Detect appropriate truncation style based on column name."""
    path_indicators = ["path", "file", "dir", "folder", "location"]
    
    if any(ind in column_name.lower() for ind in path_indicators):
        return "middle"
    
    return "end"
```

**Example**:
```
# Old (end truncation):
src/Services.Tests/PayoutServiceTests...

# New (middle truncation for paths):
src/Services.Tests/.../PayoutServiceTests.cs
```

**Acceptance Criteria**:
- [ ] Path columns use middle truncation
- [ ] Name columns use end truncation
- [ ] File extensions preserved when possible
- [ ] Truncation style auto-detected from column name

---

### Task 7: Unit Tests for Output Formatting

**File(s)**: `tests/unit/test_output.py` (new file)

```python
import pytest
import json
from click.testing import CliRunner

from mu.output import (
    OutputFormatter,
    OutputConfig,
    OutputFormat,
    Column,
    smart_truncate,
)


class TestOutputFormatter:
    """Tests for OutputFormatter class."""
    
    @pytest.fixture
    def sample_data(self):
        return [
            {"name": "PayoutService", "type": "class", "score": 0.85, "path": "src/Services/PayoutService.cs"},
            {"name": "InvoicesApi", "type": "function", "score": 0.72, "path": "src/Functions/InvoicesApi.cs"},
        ]
    
    @pytest.fixture
    def columns(self):
        return [
            Column(name="Name", key="name"),
            Column(name="Type", key="type"),
            Column(name="Score", key="score", align="right"),
            Column(name="Path", key="path"),
        ]
    
    def test_format_json(self, sample_data, columns):
        """JSON format should produce valid JSON."""
        config = OutputConfig(format=OutputFormat.JSON)
        formatter = OutputFormatter(config)
        
        result = formatter.format(sample_data, columns)
        
        # Should be valid JSON
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "PayoutService"
    
    def test_format_csv(self, sample_data, columns):
        """CSV format should produce valid CSV."""
        config = OutputConfig(format=OutputFormat.CSV)
        formatter = OutputFormatter(config)
        
        result = formatter.format(sample_data, columns)
        lines = result.strip().split("\n")
        
        assert lines[0] == "Name,Type,Score,Path"
        assert "PayoutService" in lines[1]
    
    def test_format_table_no_truncate(self, sample_data, columns):
        """Table with no_truncate should show full values."""
        config = OutputConfig(format=OutputFormat.TABLE, no_truncate=True)
        formatter = OutputFormatter(config)
        
        result = formatter.format(sample_data, columns)
        
        assert "..." not in result
        assert "PayoutService" in result
        assert "src/Services/PayoutService.cs" in result
    
    def test_format_table_truncates_by_default(self, columns):
        """Table should truncate long values by default."""
        long_data = [
            {"name": "A" * 100, "type": "class", "score": 0.5, "path": "x" * 100},
        ]
        config = OutputConfig(format=OutputFormat.TABLE, no_truncate=False, width=80)
        formatter = OutputFormatter(config)
        
        result = formatter.format(long_data, columns)
        
        assert "..." in result
    
    def test_format_tree(self, sample_data, columns):
        """Tree format should produce tree structure."""
        config = OutputConfig(format=OutputFormat.TREE)
        formatter = OutputFormatter(config)
        
        result = formatter.format(sample_data, columns)
        
        assert "├──" in result or "└──" in result
        assert "PayoutService" in result


class TestSmartTruncate:
    """Tests for smart_truncate function."""
    
    def test_no_truncation_needed(self):
        """Short values should not be truncated."""
        assert smart_truncate("short", 10) == "short"
    
    def test_end_truncation(self):
        """End truncation should add ... at end."""
        result = smart_truncate("VeryLongClassName", 10, "end")
        assert result == "VeryLon..."
        assert len(result) == 10
    
    def test_middle_truncation(self):
        """Middle truncation should preserve start and end."""
        result = smart_truncate("src/very/long/path/to/file.py", 25, "middle")
        assert result.startswith("src/")
        assert result.endswith("file.py") or "..." in result
        assert len(result) <= 25
    
    def test_start_truncation(self):
        """Start truncation should add ... at start."""
        result = smart_truncate("VeryLongClassName", 10, "start")
        assert result.startswith("...")
        assert len(result) == 10


class TestPipedOutput:
    """Tests for behavior when output is piped."""
    
    def test_no_color_when_not_tty(self, monkeypatch):
        """Colors should be disabled when not a TTY."""
        import sys
        from io import StringIO
        
        # Simulate piped output
        fake_stdout = StringIO()
        fake_stdout.isatty = lambda: False
        monkeypatch.setattr(sys, 'stdout', fake_stdout)
        
        config = OutputConfig(
            no_color=not fake_stdout.isatty(),
            no_truncate=not fake_stdout.isatty(),
        )
        
        assert config.no_color == True
        assert config.no_truncate == True
```

**Acceptance Criteria**:
- [ ] Tests cover all output formats
- [ ] Tests cover truncation behavior
- [ ] Tests cover piped output detection
- [ ] Tests pass in CI

---

### Task 8: Documentation Update

**File(s)**: `docs/cli.md` or similar

**Description**: Document the new output options.

```markdown
## Output Formatting

All MU commands support consistent output formatting options:

### Global Options

| Option | Description |
|--------|-------------|
| `--format, -f` | Output format: `table`, `json`, `csv`, `tree` |
| `--no-truncate` | Show full values without truncation |
| `--no-color` | Disable colored output |
| `--width N` | Set table width (default: terminal width) |

### Examples

```bash
# Get JSON output for scripting
mu impact PayoutService --format json | jq '.[] | select(.impact_score > 0.5)'

# Get full paths without truncation
mu deps MyClass --no-truncate

# Export to CSV
mu query "SELECT name, complexity FROM functions" --format csv > functions.csv

# Pipe-friendly (auto-disables color and truncation)
mu impact Service | grep "critical"
```

### Format Details

#### Table (default)
Human-readable ASCII table with smart truncation.

#### JSON
Machine-readable JSON array. Each row is an object.

#### CSV
Standard CSV format with headers.

#### Tree
Hierarchical tree view for dependency-like data.
```

**Acceptance Criteria**:
- [ ] All options documented
- [ ] Examples provided for common use cases
- [ ] Format differences explained

---

## Dependencies

```
Task 1 (Global Options)
    ↓
Task 2 (Output Helper) ←─────── Core formatting logic
    ↓
Task 3 (Update impact) ←─────── First command to use it
Task 4 (Update other commands)
Task 5 (MUQL integration)
    ↓
Task 6 (Smart truncation) ←──── Enhancement
    ↓
Task 7 (Unit tests)
Task 8 (Documentation)
```

---

## Implementation Order

| Priority | Task | Effort | Risk |
|----------|------|--------|------|
| P0 | Task 1: Global Options | Small (30m) | Low |
| P0 | Task 2: Output Helper | Medium (2h) | Low - new file |
| P0 | Task 3: Update impact | Small (1h) | Medium - first integration |
| P1 | Task 4: Update other commands | Medium (2h) | Medium - multiple files |
| P1 | Task 5: MUQL integration | Small (30m) | Low |
| P2 | Task 6: Smart truncation | Small (1h) | Low |
| P2 | Task 7: Unit tests | Medium (1h) | Low |
| P2 | Task 8: Documentation | Small (30m) | Low |

---

## Success Metrics

1. **Usability**: `mu impact --format json | jq .` works for scripting
2. **Readability**: `mu impact --no-truncate` shows full node IDs
3. **Consistency**: All tabular commands support same options
4. **Backward Compatible**: Default behavior unchanged for interactive use

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Very narrow terminal (< 40 cols) | Minimum column widths enforced |
| Very long single value | Truncate to column width or wrap |
| Empty result set | Show "No results" message |
| Unicode characters | Handle width correctly (some chars are 2-wide) |
| Piped to file | Auto-disable color, disable truncation |

---

## Rollback Plan

If issues arise:
1. Keep old formatting code alongside new
2. Environment variable `MU_LEGACY_OUTPUT=1`
3. Gradually migrate commands one at a time
