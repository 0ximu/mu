"""Output formatters for semantic diff results."""

from __future__ import annotations

import json

from mu.diff.models import (
    ChangeType,
    ClassDiff,
    DiffResult,
    FunctionDiff,
    ModuleDiff,
)


# ANSI color codes
class Colors:
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


def _change_symbol(change_type: ChangeType, no_color: bool = False) -> str:
    """Get symbol for change type."""
    if change_type == ChangeType.ADDED:
        return _color("+", Colors.GREEN, no_color)
    elif change_type == ChangeType.REMOVED:
        return _color("-", Colors.RED, no_color)
    elif change_type == ChangeType.MODIFIED:
        return _color("~", Colors.YELLOW, no_color)
    return " "


def format_diff(result: DiffResult, no_color: bool = False) -> str:
    """Format diff result for terminal output.

    Args:
        result: The diff result to format.
        no_color: If True, disable ANSI colors.

    Returns:
        Formatted string for terminal display.
    """
    lines: list[str] = []

    # Header
    header = f"Semantic diff: {result.base_ref} → {result.target_ref}"
    lines.append(_color(header, Colors.BOLD, no_color))
    lines.append(_color("=" * len(header), Colors.DIM, no_color))
    lines.append("")

    # Summary stats
    stats = result.stats
    if not result.has_changes:
        lines.append(_color("No semantic changes detected.", Colors.DIM, no_color))
        return "\n".join(lines)

    # Stats summary
    lines.append(_color("Summary:", Colors.BOLD, no_color))

    if stats.modules_added or stats.modules_removed or stats.modules_modified:
        parts = []
        if stats.modules_added:
            parts.append(_color(f"+{stats.modules_added}", Colors.GREEN, no_color))
        if stats.modules_removed:
            parts.append(_color(f"-{stats.modules_removed}", Colors.RED, no_color))
        if stats.modules_modified:
            parts.append(_color(f"~{stats.modules_modified}", Colors.YELLOW, no_color))
        lines.append(f"  Modules: {' '.join(parts)}")

    if stats.functions_added or stats.functions_removed or stats.functions_modified:
        parts = []
        if stats.functions_added:
            parts.append(_color(f"+{stats.functions_added}", Colors.GREEN, no_color))
        if stats.functions_removed:
            parts.append(_color(f"-{stats.functions_removed}", Colors.RED, no_color))
        if stats.functions_modified:
            parts.append(_color(f"~{stats.functions_modified}", Colors.YELLOW, no_color))
        lines.append(f"  Functions: {' '.join(parts)}")

    if stats.classes_added or stats.classes_removed or stats.classes_modified:
        parts = []
        if stats.classes_added:
            parts.append(_color(f"+{stats.classes_added}", Colors.GREEN, no_color))
        if stats.classes_removed:
            parts.append(_color(f"-{stats.classes_removed}", Colors.RED, no_color))
        if stats.classes_modified:
            parts.append(_color(f"~{stats.classes_modified}", Colors.YELLOW, no_color))
        lines.append(f"  Classes: {' '.join(parts)}")

    if stats.external_deps_added or stats.external_deps_removed:
        parts = []
        if stats.external_deps_added:
            parts.append(_color(f"+{stats.external_deps_added}", Colors.GREEN, no_color))
        if stats.external_deps_removed:
            parts.append(_color(f"-{stats.external_deps_removed}", Colors.RED, no_color))
        lines.append(f"  External deps: {' '.join(parts)}")

    lines.append("")

    # Module changes
    if result.module_diffs:
        lines.append(_color("Changes:", Colors.BOLD, no_color))
        lines.append("")

        for module_diff in result.module_diffs:
            lines.extend(_format_module_diff(module_diff, no_color))
            lines.append("")

    # Dependency changes
    dep_diff = result.dependency_diff
    if dep_diff.added_external or dep_diff.removed_external:
        lines.append(_color("External Dependencies:", Colors.BOLD, no_color))
        for pkg in dep_diff.added_external:
            lines.append(f"  {_color('+', Colors.GREEN, no_color)} {pkg}")
        for pkg in dep_diff.removed_external:
            lines.append(f"  {_color('-', Colors.RED, no_color)} {pkg}")
        lines.append("")

    return "\n".join(lines)


def _format_module_diff(diff: ModuleDiff, no_color: bool = False) -> list[str]:
    """Format a single module diff."""
    lines: list[str] = []

    # Module header
    symbol = _change_symbol(diff.change_type, no_color)
    module_color = {
        ChangeType.ADDED: Colors.GREEN,
        ChangeType.REMOVED: Colors.RED,
        ChangeType.MODIFIED: Colors.YELLOW,
    }.get(diff.change_type, "")

    lines.append(f"{symbol} {_color(diff.path, module_color + Colors.BOLD, no_color)}")

    indent = "    "

    # For added/removed modules, just show counts
    if diff.change_type == ChangeType.ADDED:
        if diff.added_functions:
            lines.append(
                f"{indent}{_color(f'+{len(diff.added_functions)} functions', Colors.GREEN, no_color)}"
            )
        if diff.added_classes:
            lines.append(
                f"{indent}{_color(f'+{len(diff.added_classes)} classes', Colors.GREEN, no_color)}"
            )
        return lines

    if diff.change_type == ChangeType.REMOVED:
        if diff.removed_functions:
            lines.append(
                f"{indent}{_color(f'-{len(diff.removed_functions)} functions', Colors.RED, no_color)}"
            )
        if diff.removed_classes:
            lines.append(
                f"{indent}{_color(f'-{len(diff.removed_classes)} classes', Colors.RED, no_color)}"
            )
        return lines

    # For modified modules, show details
    # Functions
    for name in diff.added_functions:
        lines.append(
            f"{indent}{_color('+', Colors.GREEN, no_color)} {_color(f'fn {name}', Colors.GREEN, no_color)}"
        )

    for name in diff.removed_functions:
        lines.append(
            f"{indent}{_color('-', Colors.RED, no_color)} {_color(f'fn {name}', Colors.RED, no_color)}"
        )

    for func_diff in diff.modified_functions:
        lines.extend(_format_function_diff(func_diff, indent, no_color))

    # Classes
    for name in diff.added_classes:
        lines.append(
            f"{indent}{_color('+', Colors.GREEN, no_color)} {_color(f'class {name}', Colors.GREEN, no_color)}"
        )

    for name in diff.removed_classes:
        lines.append(
            f"{indent}{_color('-', Colors.RED, no_color)} {_color(f'class {name}', Colors.RED, no_color)}"
        )

    for class_diff in diff.modified_classes:
        lines.extend(_format_class_diff(class_diff, indent, no_color))

    # Import changes (condensed)
    if diff.added_imports:
        lines.append(
            f"{indent}{_color(f'+{len(diff.added_imports)} imports', Colors.DIM + Colors.GREEN, no_color)}"
        )
    if diff.removed_imports:
        lines.append(
            f"{indent}{_color(f'-{len(diff.removed_imports)} imports', Colors.DIM + Colors.RED, no_color)}"
        )

    return lines


def _format_function_diff(diff: FunctionDiff, indent: str, no_color: bool = False) -> list[str]:
    """Format a function diff."""
    lines: list[str] = []

    # Function name with modification indicator
    name = diff.full_name
    lines.append(
        f"{indent}{_color('~', Colors.YELLOW, no_color)} {_color(f'fn {name}', Colors.YELLOW, no_color)}"
    )

    detail_indent = indent + "  "

    # Show signature changes
    if diff.old_return_type != diff.new_return_type:
        old = diff.old_return_type or "None"
        new = diff.new_return_type or "None"
        lines.append(
            f"{detail_indent}return: {_color(old, Colors.RED, no_color)} → {_color(new, Colors.GREEN, no_color)}"
        )

    if diff.async_changed:
        lines.append(f"{detail_indent}async: changed")

    if diff.static_changed:
        lines.append(f"{detail_indent}static: changed")

    # Parameter changes
    for param in diff.parameter_changes:
        if param.change_type == ChangeType.ADDED:
            type_info = f": {param.new_type}" if param.new_type else ""
            lines.append(
                f"{detail_indent}{_color('+', Colors.GREEN, no_color)} param {param.name}{type_info}"
            )
        elif param.change_type == ChangeType.REMOVED:
            type_info = f": {param.old_type}" if param.old_type else ""
            lines.append(
                f"{detail_indent}{_color('-', Colors.RED, no_color)} param {param.name}{type_info}"
            )
        elif param.change_type == ChangeType.MODIFIED:
            old = param.old_type or "untyped"
            new = param.new_type or "untyped"
            lines.append(
                f"{detail_indent}{_color('~', Colors.YELLOW, no_color)} param {param.name}: {old} → {new}"
            )

    return lines


def _format_class_diff(diff: ClassDiff, indent: str, no_color: bool = False) -> list[str]:
    """Format a class diff."""
    lines: list[str] = []

    lines.append(
        f"{indent}{_color('~', Colors.YELLOW, no_color)} {_color(f'class {diff.name}', Colors.YELLOW, no_color)}"
    )

    detail_indent = indent + "  "

    # Inheritance changes
    if diff.has_inheritance_change:
        old = ", ".join(diff.old_bases) or "(none)"
        new = ", ".join(diff.new_bases) or "(none)"
        lines.append(
            f"{detail_indent}bases: {_color(old, Colors.RED, no_color)} → {_color(new, Colors.GREEN, no_color)}"
        )

    # Method changes
    for name in diff.added_methods:
        lines.append(f"{detail_indent}{_color('+', Colors.GREEN, no_color)} method {name}")

    for name in diff.removed_methods:
        lines.append(f"{detail_indent}{_color('-', Colors.RED, no_color)} method {name}")

    for method_diff in diff.modified_methods:
        # Simplified: just show method name as modified
        lines.append(
            f"{detail_indent}{_color('~', Colors.YELLOW, no_color)} method {method_diff.name}"
        )

    # Attribute changes
    if diff.added_attributes:
        lines.append(
            f"{detail_indent}{_color(f'+{len(diff.added_attributes)} attrs', Colors.DIM + Colors.GREEN, no_color)}"
        )
    if diff.removed_attributes:
        lines.append(
            f"{detail_indent}{_color(f'-{len(diff.removed_attributes)} attrs', Colors.DIM + Colors.RED, no_color)}"
        )

    return lines


def format_diff_json(result: DiffResult, pretty: bool = True) -> str:
    """Format diff result as JSON.

    Args:
        result: The diff result to format.
        pretty: If True, format with indentation.

    Returns:
        JSON string.
    """
    data = result.to_dict()

    if pretty:
        return json.dumps(data, indent=2)
    return json.dumps(data)


def format_diff_markdown(result: DiffResult) -> str:
    """Format diff result as Markdown.

    Args:
        result: The diff result to format.

    Returns:
        Markdown formatted string.
    """
    lines: list[str] = []

    # Header
    lines.append(f"# Semantic Diff: `{result.base_ref}` → `{result.target_ref}`")
    lines.append("")

    if not result.has_changes:
        lines.append("*No semantic changes detected.*")
        return "\n".join(lines)

    # Summary
    stats = result.stats
    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | Added | Removed | Modified |")
    lines.append("|----------|-------|---------|----------|")
    lines.append(
        f"| Modules | {stats.modules_added} | {stats.modules_removed} | {stats.modules_modified} |"
    )
    lines.append(
        f"| Functions | {stats.functions_added} | {stats.functions_removed} | {stats.functions_modified} |"
    )
    lines.append(
        f"| Classes | {stats.classes_added} | {stats.classes_removed} | {stats.classes_modified} |"
    )
    lines.append("")

    # Module changes
    if result.module_diffs:
        lines.append("## Changes")
        lines.append("")

        for diff in result.module_diffs:
            emoji = {"added": "🟢", "removed": "🔴", "modified": "🟡"}.get(
                diff.change_type.value, ""
            )
            lines.append(f"### {emoji} `{diff.path}`")
            lines.append("")

            if diff.change_type == ChangeType.ADDED:
                if diff.added_functions:
                    lines.append(f"- Added {len(diff.added_functions)} functions")
                if diff.added_classes:
                    lines.append(f"- Added {len(diff.added_classes)} classes")
            elif diff.change_type == ChangeType.REMOVED:
                if diff.removed_functions:
                    lines.append(f"- Removed {len(diff.removed_functions)} functions")
                if diff.removed_classes:
                    lines.append(f"- Removed {len(diff.removed_classes)} classes")
            else:
                # Modified
                if diff.added_functions:
                    lines.append(
                        f"- **Added functions:** {', '.join(f'`{f}`' for f in diff.added_functions)}"
                    )
                if diff.removed_functions:
                    lines.append(
                        f"- **Removed functions:** {', '.join(f'`{f}`' for f in diff.removed_functions)}"
                    )
                if diff.modified_functions:
                    lines.append(
                        f"- **Modified functions:** {', '.join(f'`{f.full_name}`' for f in diff.modified_functions)}"
                    )
                if diff.added_classes:
                    lines.append(
                        f"- **Added classes:** {', '.join(f'`{c}`' for c in diff.added_classes)}"
                    )
                if diff.removed_classes:
                    lines.append(
                        f"- **Removed classes:** {', '.join(f'`{c}`' for c in diff.removed_classes)}"
                    )
                if diff.modified_classes:
                    lines.append(
                        f"- **Modified classes:** {', '.join(f'`{c.name}`' for c in diff.modified_classes)}"
                    )

            lines.append("")

    # Dependency changes
    dep_diff = result.dependency_diff
    if dep_diff.added_external or dep_diff.removed_external:
        lines.append("## External Dependencies")
        lines.append("")
        if dep_diff.added_external:
            lines.append(f"**Added:** {', '.join(f'`{p}`' for p in dep_diff.added_external)}")
        if dep_diff.removed_external:
            lines.append(f"**Removed:** {', '.join(f'`{p}`' for p in dep_diff.removed_external)}")
        lines.append("")

    return "\n".join(lines)
