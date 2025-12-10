"""MUQL Result Formatter - Formats query results for output.

Provides formatting in table, JSON, CSV, and tree formats.
"""

from __future__ import annotations

import json
import shutil
from enum import Enum
from typing import Any

from mu.kernel.muql.executor import QueryResult

# =============================================================================
# Path Truncation Helpers
# =============================================================================


def _truncate_path(path: str, max_segments: int = 3) -> str:
    """Truncate path to show only last N segments.

    Args:
        path: The file path to truncate.
        max_segments: Maximum number of path segments to show.

    Returns:
        Truncated path with "..." prefix if shortened.

    Examples:
        >>> _truncate_path("/very/long/path/to/file.py", 3)
        ".../path/to/file.py"
        >>> _truncate_path("short/path.py", 3)
        "short/path.py"
    """
    # Normalize backslashes to forward slashes
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")

    if len(parts) <= max_segments:
        return path

    return ".../" + "/".join(parts[-max_segments:])


def _get_terminal_width() -> int:
    """Get terminal width, default to 120 if unavailable."""
    return shutil.get_terminal_size((120, 24)).columns


def _is_path_column(col_name: str) -> bool:
    """Check if column contains paths.

    Args:
        col_name: The column name to check.

    Returns:
        True if the column likely contains file paths.
    """
    return col_name.lower() in ("path", "file_path", "source_path", "module_path")


class OutputFormat(Enum):
    """Available output formats."""

    TABLE = "table"
    JSON = "json"
    CSV = "csv"
    TREE = "tree"
    DICT = "dict"  # Returns dict for API use (no serialization)


# =============================================================================
# ANSI Colors
# =============================================================================


class Colors:
    """ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"


def _color(text: str, color: str, no_color: bool = False) -> str:
    """Apply color to text."""
    if no_color:
        return text
    return f"{color}{text}{Colors.RESET}"


# =============================================================================
# Table Formatter
# =============================================================================


def _smart_truncate(value: str, max_width: int, column_hint: str = "") -> str:
    """Smart truncation based on content type.

    - Paths: middle truncation (src/.../.../file.py) - preserves directory context and filename
    - Names: end truncation (VeryLongClass...) - preserves start of identifier

    Args:
        value: The string value to truncate.
        max_width: Maximum width in characters.
        column_hint: Column name hint for detecting paths.

    Returns:
        Truncated string or original if within width.
    """
    if len(value) <= max_width or max_width < 10:
        return value

    # Detect if path-like based on content or column name
    is_path = _is_path_column(column_hint) or "/" in value or "\\" in value

    if is_path:
        # Middle truncation: keep start and end to preserve filename
        keep = (max_width - 3) // 2
        return f"{value[:keep]}...{value[-keep:]}"
    else:
        # End truncation for names/identifiers
        return value[: max_width - 3] + "..."


def format_table(
    result: QueryResult,
    no_color: bool = False,
    no_truncate: bool = False,
    terminal_width: int | None = None,
) -> str:
    """Format query result as ASCII table.

    Args:
        result: The query result to format.
        no_color: If True, disable ANSI colors.
        no_truncate: If True, disable all truncation (show full values).
        terminal_width: Optional terminal width override. None = auto-detect.

    Returns:
        Formatted table string.
    """
    if result.error:
        return _color(f"Error: {result.error}", Colors.RED, no_color)

    if not result.rows:
        return _color("No results found.", Colors.DIM, no_color)

    columns = result.columns

    # Convert rows to mutable lists for truncation
    rows: list[list[Any]] = [list(row) for row in result.rows]

    # Calculate natural column widths (header + data)
    MIN_COL_WIDTH = 8
    widths = [max(len(col), MIN_COL_WIDTH) for col in columns]
    for row in rows:
        for i, val in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(val)))

    # Apply adaptive truncation if not disabled
    if not no_truncate:
        term_width = terminal_width or _get_terminal_width()

        # Reserve space for separators: " | " between columns
        separator_space = (len(columns) - 1) * 3
        available = term_width - separator_space - 4  # margin

        total_width = sum(widths)
        if total_width > available and available > 0:
            # Proportionally reduce widths, respecting minimum
            scale = available / total_width
            widths = [max(MIN_COL_WIDTH, int(w * scale)) for w in widths]

    # Apply truncation to cell values
    for row in rows:
        for i, val in enumerate(row):
            if i < len(widths):
                str_val = str(val)
                if not no_truncate and len(str_val) > widths[i]:
                    row[i] = _smart_truncate(str_val, widths[i], columns[i])

    # Build table
    lines: list[str] = []

    # Header
    header_parts = []
    for i, col in enumerate(columns):
        header_parts.append(str(col).ljust(widths[i]))
    header = " | ".join(header_parts)
    lines.append(_color(header, Colors.BOLD, no_color))

    # Separator
    separator_parts = ["-" * w for w in widths]
    separator = "-+-".join(separator_parts)
    lines.append(_color(separator, Colors.DIM, no_color))

    # Rows
    for row in rows:
        row_parts = []
        for i, val in enumerate(row):
            if i < len(widths):
                row_parts.append(str(val).ljust(widths[i]))
        lines.append(" | ".join(row_parts))

    # Footer
    lines.append(_color(separator, Colors.DIM, no_color))
    lines.append(
        _color(f"{result.row_count} rows ({result.execution_time_ms:.2f}ms)", Colors.DIM, no_color)
    )

    return "\n".join(lines)


# =============================================================================
# JSON Formatter
# =============================================================================


def format_json(result: QueryResult, pretty: bool = True) -> str:
    """Format query result as JSON.

    Args:
        result: The query result to format.
        pretty: If True, format with indentation.

    Returns:
        JSON string.
    """
    data = result.to_dict()
    if pretty:
        return json.dumps(data, indent=2)
    return json.dumps(data)


# =============================================================================
# CSV Formatter
# =============================================================================


def format_csv(result: QueryResult, delimiter: str = ",") -> str:
    """Format query result as CSV.

    Args:
        result: The query result to format.
        delimiter: Field delimiter (default: comma).

    Returns:
        CSV string.
    """
    if result.error:
        return f"Error: {result.error}"

    lines: list[str] = []

    # Header
    lines.append(delimiter.join(result.columns))

    # Rows
    for row in result.rows:
        row_values = []
        for val in row:
            # Escape quotes and wrap in quotes if needed
            str_val = str(val)
            if delimiter in str_val or '"' in str_val or "\n" in str_val:
                str_val = '"' + str_val.replace('"', '""') + '"'
            row_values.append(str_val)
        lines.append(delimiter.join(row_values))

    return "\n".join(lines)


# =============================================================================
# Tree Formatter
# =============================================================================


def format_tree(result: QueryResult, no_color: bool = False) -> str:
    """Format query result as tree structure.

    Best for hierarchical data like dependency trees.

    Args:
        result: The query result to format.
        no_color: If True, disable ANSI colors.

    Returns:
        Tree-formatted string.
    """
    if result.error:
        return _color(f"Error: {result.error}", Colors.RED, no_color)

    if not result.rows:
        return _color("No results found.", Colors.DIM, no_color)

    lines: list[str] = []

    # Simple tree for path results (step, node)
    if result.columns == ["step", "node"]:
        for i, row in enumerate(result.rows):
            is_last = i == len(result.rows) - 1
            prefix = "    " if is_last else "    "
            connector = "`-- " if is_last else "|-- "
            node_name = str(row[1])
            lines.append(prefix + connector + _color(node_name, Colors.CYAN, no_color))
        return "\n".join(lines)

    # For other results, show as nested structure
    # Group by path if available
    path_idx = None
    for i, col in enumerate(result.columns):
        if col in ("path", "file_path"):
            path_idx = i
            break

    if path_idx is not None:
        # Group rows by path
        groups: dict[str, list[tuple[Any, ...]]] = {}
        for row in result.rows:
            path = str(row[path_idx])
            if path not in groups:
                groups[path] = []
            groups[path].append(row)

        for path, group_rows in groups.items():
            lines.append(_color(path, Colors.BLUE + Colors.BOLD, no_color))
            for i, row in enumerate(group_rows):
                is_last = i == len(group_rows) - 1
                prefix = "  `-- " if is_last else "  |-- "
                # Show name if available
                name_idx = result.columns.index("name") if "name" in result.columns else None
                if name_idx is not None:
                    lines.append(prefix + _color(str(row[name_idx]), Colors.CYAN, no_color))
                else:
                    lines.append(prefix + str(row[0]))
    else:
        # Simple list
        for i, row in enumerate(result.rows):
            is_last = i == len(result.rows) - 1
            prefix = "`-- " if is_last else "|-- "
            lines.append(prefix + _color(str(row[0]), Colors.CYAN, no_color))

    lines.append("")
    lines.append(
        _color(f"{result.row_count} items ({result.execution_time_ms:.2f}ms)", Colors.DIM, no_color)
    )

    return "\n".join(lines)


# =============================================================================
# Main Formatter Function
# =============================================================================


def format_result(
    result: QueryResult,
    output_format: OutputFormat | str = OutputFormat.TABLE,
    no_color: bool = False,
    no_truncate: bool = False,
    terminal_width: int | None = None,
) -> str | dict[str, Any]:
    """Format query result in the specified format.

    Args:
        result: The query result to format.
        output_format: The output format (table, json, csv, tree, dict).
        no_color: If True, disable ANSI colors.
        no_truncate: If True, disable truncation (show full values).
        terminal_width: Optional terminal width override.

    Returns:
        Formatted string, or dict if output_format is DICT.
    """
    if isinstance(output_format, str):
        try:
            output_format = OutputFormat(output_format.lower())
        except ValueError:
            output_format = OutputFormat.TABLE

    if output_format == OutputFormat.TABLE:
        return format_table(result, no_color, no_truncate, terminal_width)
    elif output_format == OutputFormat.JSON:
        return format_json(result)
    elif output_format == OutputFormat.CSV:
        return format_csv(result)
    elif output_format == OutputFormat.TREE:
        return format_tree(result, no_color)
    elif output_format == OutputFormat.DICT:
        return result.to_dict()
    else:
        return format_table(result, no_color, no_truncate, terminal_width)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "OutputFormat",
    "format_result",
    "format_table",
    "format_json",
    "format_csv",
    "format_tree",
]
