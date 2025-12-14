"""Unified output formatting module for MU CLI commands.

Provides consistent output formatting across all tabular CLI commands,
supporting multiple formats (table, json, csv, tree) with smart truncation
and TTY auto-detection.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import click

# =============================================================================
# Output Configuration
# =============================================================================


@dataclass
class OutputConfig:
    """Output configuration extracted from CLI context.

    Attributes:
        format: Output format (table, json, csv, tree).
        no_truncate: If True, disable truncation of values.
        no_color: If True, disable ANSI colors.
        width: Terminal width for table formatting. None = auto-detect.
    """

    format: str = "table"
    no_truncate: bool = False
    no_color: bool = False
    width: int | None = None

    @classmethod
    def from_context(cls, ctx: click.Context | None, default_format: str = "table") -> OutputConfig:
        """Extract output config from Click context with auto-detection.

        Args:
            ctx: Click context object (may be None).
            default_format: Default format if not specified in context.

        Returns:
            OutputConfig with settings from context or sensible defaults.
        """
        from mu.commands.utils import is_interactive

        # Auto-detection for piped output
        is_tty = is_interactive()

        if ctx is None:
            return cls(
                format=default_format,
                no_truncate=not is_tty,
                no_color=not is_tty,
                width=None,
            )

        obj = getattr(ctx, "obj", None)

        # Get format from context, falling back to default
        fmt = getattr(obj, "output_format", None) or default_format

        return cls(
            format=fmt,
            no_truncate=getattr(obj, "no_truncate", False) or not is_tty,
            no_color=getattr(obj, "no_color", False) or not is_tty,
            width=getattr(obj, "width", None),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "format": self.format,
            "no_truncate": self.no_truncate,
            "no_color": self.no_color,
            "width": self.width,
        }


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


def colorize(text: str, color: str, no_color: bool = False) -> str:
    """Apply color to text if colors are enabled.

    Args:
        text: Text to colorize.
        color: ANSI color code from Colors class.
        no_color: If True, return text without colors.

    Returns:
        Colorized text or plain text if no_color is True.
    """
    if no_color:
        return text
    return f"{color}{text}{Colors.RESET}"


# =============================================================================
# Smart Truncation
# =============================================================================


def smart_truncate(value: str, max_width: int, column_hint: str = "") -> str:
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
    is_path = _is_path_value(value, column_hint)

    if is_path:
        # Middle truncation: keep start and end to preserve filename
        # Reserve 5 chars for ".../"
        keep = (max_width - 4) // 2
        return f"{value[:keep]}...{value[-keep:]}"
    else:
        # End truncation for names/identifiers
        return value[: max_width - 3] + "..."


def _is_path_value(value: str, column_hint: str = "") -> bool:
    """Detect if a value is a file path.

    Args:
        value: The value to check.
        column_hint: Column name hint.

    Returns:
        True if the value appears to be a file path.
    """
    # Check column name
    path_column_names = {"path", "file_path", "source_path", "module_path", "file"}
    if column_hint.lower() in path_column_names:
        return True

    # Check value characteristics
    if "/" in value or "\\" in value:
        return True

    # Check for common file extensions
    if "." in value:
        ext = value.rsplit(".", 1)[-1].lower()
        if ext in {"py", "ts", "js", "go", "java", "rs", "cs", "rb", "cpp", "c", "h"}:
            return True

    return False


def _get_terminal_width(config: OutputConfig | None = None) -> int:
    """Get terminal width with fallback.

    Args:
        config: Optional output config with width override.

    Returns:
        Terminal width in characters.
    """
    if config and config.width:
        return config.width
    return shutil.get_terminal_size((120, 24)).columns


# =============================================================================
# Column Configuration
# =============================================================================


@dataclass
class Column:
    """Column definition for tabular output.

    Attributes:
        name: Display name for column header.
        key: Dictionary key to extract value from data rows.
        color: Optional color for this column's values.
        min_width: Minimum column width (default: 5).
        max_width: Maximum column width (default: None = auto).
        truncate_style: 'end' or 'middle' (default: auto-detect based on key).
    """

    name: str
    key: str
    color: str | None = None
    min_width: int = 5
    max_width: int | None = None
    truncate_style: str | None = None  # 'end', 'middle', or None (auto)


# =============================================================================
# Output Formatters
# =============================================================================


def format_output(
    data: list[dict[str, Any]],
    columns: Sequence[Column | tuple[str, str]],
    config: OutputConfig,
    title: str | None = None,
) -> str:
    """Format data for CLI output.

    Args:
        data: List of dictionaries with row data.
        columns: Column definitions. Can be Column objects or (name, key) tuples.
        config: Output configuration.
        title: Optional title for table output.

    Returns:
        Formatted string ready for output.
    """
    # Normalize columns to Column objects
    normalized_columns: list[Column] = []
    for col in columns:
        if isinstance(col, Column):
            normalized_columns.append(col)
        else:
            name, key = col
            normalized_columns.append(Column(name=name, key=key))

    # Dispatch to appropriate formatter
    if config.format == "json":
        return format_json(data, title=title)
    elif config.format == "csv":
        return format_csv(data, normalized_columns)
    elif config.format == "tree":
        return format_tree(data, normalized_columns, config)
    else:
        # Default: table format
        return format_table(data, normalized_columns, config, title=title)


def format_table(
    data: list[dict[str, Any]],
    columns: list[Column],
    config: OutputConfig,
    title: str | None = None,
) -> str:
    """Format data as ASCII table.

    Args:
        data: List of dictionaries with row data.
        columns: Column definitions.
        config: Output configuration.
        title: Optional table title.

    Returns:
        Formatted table string.
    """
    if not data:
        msg = "No results found."
        return colorize(msg, Colors.DIM, config.no_color)

    # Calculate terminal and column widths
    term_width = _get_terminal_width(config)

    # Calculate natural column widths (header + data)
    col_widths: list[int] = []
    for col in columns:
        header_width = len(col.name)
        max_data_width = max(
            (len(str(row.get(col.key, ""))) for row in data),
            default=0,
        )
        natural_width = max(header_width, max_data_width, col.min_width)
        col_widths.append(natural_width)

    # Apply truncation if needed (when not in no_truncate mode)
    if not config.no_truncate:
        # Reserve space for separators: " | " between columns
        separator_space = (len(columns) - 1) * 3
        available = term_width - separator_space - 4  # margin

        total_width = sum(col_widths)
        if total_width > available:
            # Proportionally reduce widths
            scale = available / total_width
            col_widths = [
                max(col.min_width, int(w * scale))
                for col, w in zip(columns, col_widths, strict=True)
            ]

    # Build rows with truncation
    rows: list[list[str]] = []
    for row_data in data:
        row_values: list[str] = []
        for col, width in zip(columns, col_widths, strict=True):
            value = str(row_data.get(col.key, ""))
            if not config.no_truncate and len(value) > width:
                value = smart_truncate(value, width, col.key)
            row_values.append(value)
        rows.append(row_values)

    # Build output lines
    lines: list[str] = []

    # Title
    if title:
        lines.append(colorize(title, Colors.BOLD, config.no_color))
        lines.append("")

    # Header
    header_parts = []
    for col, width in zip(columns, col_widths, strict=True):
        header_parts.append(col.name.ljust(width))
    header = " | ".join(header_parts)
    lines.append(colorize(header, Colors.BOLD, config.no_color))

    # Separator
    separator_parts = ["-" * w for w in col_widths]
    separator = "-+-".join(separator_parts)
    lines.append(colorize(separator, Colors.DIM, config.no_color))

    # Data rows
    for row_values in rows:
        row_parts = []
        for col, value, width in zip(columns, row_values, col_widths, strict=True):
            padded = value.ljust(width)
            if col.color and not config.no_color:
                padded = colorize(padded, col.color, config.no_color)
            row_parts.append(padded)
        lines.append(" | ".join(row_parts))

    # Footer
    lines.append(colorize(separator, Colors.DIM, config.no_color))
    count_msg = f"{len(data)} row{'s' if len(data) != 1 else ''}"
    lines.append(colorize(count_msg, Colors.DIM, config.no_color))

    return "\n".join(lines)


def format_json(
    data: list[dict[str, Any]],
    title: str | None = None,
    pretty: bool = True,
) -> str:
    """Format data as JSON.

    Args:
        data: List of dictionaries with row data.
        title: Optional title (included in output).
        pretty: If True, format with indentation.

    Returns:
        JSON string.
    """
    output: dict[str, Any] = {
        "data": data,
        "count": len(data),
    }
    if title:
        output["title"] = title

    if pretty:
        return json.dumps(output, indent=2, default=str)
    return json.dumps(output, default=str)


def format_csv(
    data: list[dict[str, Any]],
    columns: list[Column],
) -> str:
    """Format data as CSV.

    Args:
        data: List of dictionaries with row data.
        columns: Column definitions.

    Returns:
        CSV string.
    """
    if not data:
        return ""

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([col.name for col in columns])

    # Data rows
    for row in data:
        writer.writerow([str(row.get(col.key, "")) for col in columns])

    return output.getvalue().strip()


def format_tree(
    data: list[dict[str, Any]],
    columns: list[Column],
    config: OutputConfig,
) -> str:
    """Format data as tree structure.

    Best for hierarchical data like dependency trees.

    Args:
        data: List of dictionaries with row data.
        columns: Column definitions.
        config: Output configuration.

    Returns:
        Tree-formatted string.
    """
    if not data:
        msg = "No results found."
        return colorize(msg, Colors.DIM, config.no_color)

    lines: list[str] = []

    # Use first column as primary display value
    primary_key = columns[0].key if columns else "id"
    primary_color = columns[0].color if columns else Colors.CYAN

    for i, row in enumerate(data):
        is_last = i == len(data) - 1
        prefix = "`-- " if is_last else "|-- "

        value = str(row.get(primary_key, ""))
        if not config.no_truncate:
            value = smart_truncate(value, 60, primary_key)

        colored_value = colorize(value, primary_color or Colors.CYAN, config.no_color)
        lines.append(prefix + colored_value)

        # Show additional columns as details on next line
        if len(columns) > 1:
            detail_prefix = "    " if is_last else "|   "
            details = []
            for col in columns[1:]:
                col_value = row.get(col.key)
                if col_value:
                    details.append(f"{col.name}: {col_value}")
            if details:
                detail_line = ", ".join(details)
                lines.append(detail_prefix + colorize(detail_line, Colors.DIM, config.no_color))

    lines.append("")
    count_msg = f"{len(data)} items"
    lines.append(colorize(count_msg, Colors.DIM, config.no_color))

    return "\n".join(lines)


# =============================================================================
# Convenience Functions
# =============================================================================


def format_node_list(
    nodes: Sequence[str | dict[str, Any]],
    title: str,
    config: OutputConfig,
) -> str:
    """Format a list of nodes for output.

    Convenience function for common case of displaying node lists.

    Args:
        nodes: List of node IDs (strings) or node dictionaries.
        title: Title for the output.
        config: Output configuration.

    Returns:
        Formatted output string.
    """
    # Normalize to list of dicts
    data: list[dict[str, Any]] = []
    for node in nodes:
        if isinstance(node, str):
            # Parse node ID to extract type if possible
            node_type = "unknown"
            if node.startswith("mod:"):
                node_type = "module"
            elif node.startswith("cls:"):
                node_type = "class"
            elif node.startswith("fn:"):
                node_type = "function"

            data.append({"node_id": node, "type": node_type})
        else:
            data.append(node)

    columns = [
        Column("Node ID", "node_id", color=Colors.CYAN),
        Column("Type", "type"),
    ]

    return format_output(data, columns, config, title=title)


def format_cycles(
    cycles: list[list[str]],
    config: OutputConfig,
) -> str:
    """Format cycle detection results.

    Args:
        cycles: List of cycles, where each cycle is a list of node IDs.
        config: Output configuration.

    Returns:
        Formatted output string.
    """
    if config.format == "json":
        return json.dumps(
            {
                "cycles": cycles,
                "cycle_count": len(cycles),
                "total_nodes": sum(len(c) for c in cycles),
            },
            indent=2,
        )

    if config.format == "csv":
        csv_lines = ["cycle_id,node_id"]
        for i, cycle in enumerate(cycles):
            for node in cycle:
                csv_lines.append(f"{i},{node}")
        return "\n".join(csv_lines)

    # Table format with cycle visualization
    if not cycles:
        return colorize("No cycles detected.", Colors.DIM, config.no_color)

    output_lines: list[str] = []
    title_text = f"Circular Dependencies ({len(cycles)} cycles)"
    output_lines.append(colorize(title_text, Colors.BOLD, config.no_color))
    output_lines.append("")

    for i, cycle in enumerate(cycles):
        # Show cycle as: A -> B -> C -> A
        cycle_str = " -> ".join(cycle)
        if cycle:
            cycle_str += f" -> {cycle[0]}"  # Complete the cycle visually

        cycle_num = colorize(f"Cycle {i + 1}:", Colors.YELLOW, config.no_color)
        output_lines.append(f"{cycle_num} {cycle_str}")

    output_lines.append("")
    summary = colorize(f"Found {len(cycles)} cycle(s)", Colors.DIM, config.no_color)
    output_lines.append(summary)

    return "\n".join(output_lines)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Configuration
    "OutputConfig",
    "Column",
    # Colors
    "Colors",
    "colorize",
    # Truncation
    "smart_truncate",
    # Main formatters
    "format_output",
    "format_table",
    "format_json",
    "format_csv",
    "format_tree",
    # Convenience functions
    "format_node_list",
    "format_cycles",
]
