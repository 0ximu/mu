"""Response formatting utilities for MU Agent."""

from __future__ import annotations

from typing import Any


def format_mu_output(data: dict[str, Any]) -> str:
    """Format query/context result as MU notation.

    Args:
        data: Result dictionary with columns/rows or mu_text.

    Returns:
        MU-formatted string.
    """
    # If already MU text, return as-is
    if "mu_text" in data:
        return str(data["mu_text"])

    # Handle query results
    if "columns" in data and "rows" in data:
        return _format_query_as_mu(data)

    # Handle error results
    if "error" in data:
        return f"Error: {data['error']}"

    # Default: return raw data description
    return str(data)


def _format_query_as_mu(data: dict[str, Any]) -> str:
    """Format a query result as MU notation.

    Args:
        data: Query result with columns and rows.

    Returns:
        MU-formatted string.
    """
    columns = data.get("columns", [])
    rows = data.get("rows", [])

    if not rows:
        return "No results found."

    lines = []

    # Format each row
    for row in rows:
        row_dict = dict(zip(columns, row, strict=False))

        # Determine sigil based on type
        node_type = row_dict.get("type", "")
        name = row_dict.get("name", str(row[0]) if row else "")
        file_path = row_dict.get("file_path") or row_dict.get("path")

        sigil = _get_sigil(node_type)

        line = f"{sigil}{name}"
        if file_path:
            line += f"  # {file_path}"

        lines.append(line)

    return "\n".join(lines)


def _get_sigil(node_type: str) -> str:
    """Get the MU sigil for a node type.

    Args:
        node_type: The type of code node.

    Returns:
        The appropriate MU sigil character.
    """
    sigils = {
        "module": "!",
        "class": "$",
        "function": "#",
        "method": "#",
        "interface": "$",
        "struct": "$",
        "enum": "$",
        "trait": "$",
    }
    return sigils.get(node_type.lower(), "")


def format_deps_tree(deps: list[dict[str, Any]], direction: str) -> str:
    """Format dependency list as a tree.

    Args:
        deps: List of dependency dictionaries.
        direction: Direction of dependencies ("outgoing", "incoming", "both").

    Returns:
        Tree-formatted string.
    """
    if not deps:
        return "No dependencies found."

    direction_label = {
        "outgoing": "Dependencies (what it uses)",
        "incoming": "Dependents (what uses it)",
        "both": "Dependencies and Dependents",
    }.get(direction, "Dependencies")

    lines = [f"{direction_label}:"]

    for dep in deps:
        name = dep.get("name", dep.get("id", "unknown"))
        node_type = dep.get("type", "")
        sigil = _get_sigil(node_type)
        lines.append(f"  {sigil}{name}")

    return "\n".join(lines)


def format_impact_summary(
    node_id: str,
    impacted: list[str],
    max_show: int = 20,
) -> str:
    """Format impact analysis as summary.

    Args:
        node_id: The node being analyzed.
        impacted: List of impacted node IDs.
        max_show: Maximum nodes to show in detail.

    Returns:
        Formatted impact summary.
    """
    if not impacted:
        return f"No downstream impact found for {node_id}."

    lines = [f"Impact of changing {node_id}:"]
    lines.append(f"  Total affected: {len(impacted)} nodes")
    lines.append("")

    # Group by type if possible
    direct: list[str] = []
    transitive: list[str] = []

    for node in impacted[:max_show]:
        # Simple heuristic: first few are likely direct
        if len(direct) < 5:
            direct.append(node)
        else:
            transitive.append(node)

    if direct:
        lines.append("Direct dependents:")
        for node in direct:
            lines.append(f"  - {node}")

    if transitive:
        lines.append("")
        lines.append("Transitive impact:")
        for node in transitive:
            lines.append(f"  - {node}")

    if len(impacted) > max_show:
        lines.append(f"  ... and {len(impacted) - max_show} more")

    return "\n".join(lines)


def format_cycles_summary(cycles: list[list[str]]) -> str:
    """Format circular dependency cycles.

    Args:
        cycles: List of cycles, where each cycle is a list of node IDs.

    Returns:
        Formatted cycles summary.
    """
    if not cycles:
        return "No circular dependencies detected."

    lines = [f"Found {len(cycles)} circular dependency cycles:"]
    lines.append("")

    for i, cycle in enumerate(cycles[:10], 1):
        lines.append(f"Cycle {i}:")
        cycle_str = " -> ".join(cycle)
        if len(cycle) > 0:
            cycle_str += f" -> {cycle[0]}"  # Close the loop
        lines.append(f"  {cycle_str}")
        lines.append("")

    if len(cycles) > 10:
        lines.append(f"... and {len(cycles) - 10} more cycles")

    return "\n".join(lines)


def truncate_response(text: str, max_chars: int = 16000) -> str:
    """Truncate response to fit token budget.

    Attempts to preserve structure by truncating at line boundaries.

    Args:
        text: The text to truncate.
        max_chars: Maximum characters (rough estimate: 4 chars per token).

    Returns:
        Truncated text with indicator if truncation occurred.
    """
    if len(text) <= max_chars:
        return text

    # Find a good breakpoint near the limit
    truncate_at = max_chars - 50  # Leave room for truncation message

    # Try to break at a newline
    last_newline = text.rfind("\n", 0, truncate_at)
    if last_newline > truncate_at * 0.8:  # If we can keep at least 80%
        truncate_at = last_newline

    truncated = text[:truncate_at]
    remaining = len(text) - truncate_at

    return f"{truncated}\n\n... (truncated, {remaining} more characters)"


def format_for_terminal(text: str, width: int = 80) -> str:
    """Format text for terminal display.

    Args:
        text: The text to format.
        width: Terminal width.

    Returns:
        Terminal-formatted text.
    """
    lines = []
    for line in text.split("\n"):
        if len(line) <= width:
            lines.append(line)
        else:
            # Simple word wrap
            words = line.split()
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 <= width:
                    current_line += (" " if current_line else "") + word
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)

    return "\n".join(lines)


__all__ = [
    "format_mu_output",
    "format_deps_tree",
    "format_impact_summary",
    "format_cycles_summary",
    "truncate_response",
    "format_for_terminal",
]
