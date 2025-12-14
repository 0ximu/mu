"""CLI utility functions for MU commands.

Provides reusable utilities for node resolution, interactive prompts,
and common CLI operations.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.kernel.models import Node
from mu.kernel.resolver import (
    AmbiguousNodeError,
    NodeCandidate,
    NodeNotFoundError,
    NodeResolver,
    ResolutionStrategy,
    ResolvedNode,
)

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


def is_interactive() -> bool:
    """Check if the terminal is interactive (TTY).

    Returns:
        True if stdin and stdout are both TTY, False otherwise.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def shorten_path(path: str, max_length: int = 50) -> str:
    """Shorten a file path for display.

    Truncates the middle of long paths with '...'.

    Args:
        path: The file path to shorten.
        max_length: Maximum length of the returned string.

    Returns:
        Shortened path string.
    """
    if len(path) <= max_length:
        return path

    # Keep the beginning and end, truncate middle
    keep = (max_length - 3) // 2
    return f"{path[:keep]}...{path[-keep:]}"


def format_candidate_display(candidate: NodeCandidate, index: int) -> str:
    """Format a candidate for interactive display.

    Args:
        candidate: The NodeCandidate to format.
        index: The selection index (1-based).

    Returns:
        Formatted string for display.
    """
    node = candidate.node
    parts = []

    # Index and name
    parts.append(f"  [{index}] {node.name}")

    # Type (module, class, function)
    type_str = node.type.value if hasattr(node.type, "value") else str(node.type)
    parts.append(f" ({type_str})")

    # Test marker
    if candidate.is_test:
        parts.append(" [TEST]")

    # Line info
    if node.line_start and node.line_end:
        parts.append(f" L{node.line_start}-{node.line_end}")

    line1 = "".join(parts)

    # File path on second line, indented
    if node.file_path:
        path_display = shorten_path(node.file_path, 60)
        line2 = f"      {path_display}"
        return f"{line1}\n{line2}"

    return line1


def interactive_choose(candidates: list[NodeCandidate]) -> NodeCandidate:
    """Interactively prompt user to choose from candidates.

    Args:
        candidates: List of candidates to choose from.

    Returns:
        The chosen NodeCandidate.

    Raises:
        click.Abort: If user cancels (Ctrl+C).
    """
    click.echo("\nMultiple matches found:\n")

    for i, candidate in enumerate(candidates, 1):
        click.echo(format_candidate_display(candidate, i))
        click.echo()  # Blank line between entries

    # Default is first (usually best match)
    default = 1

    while True:
        try:
            choice = click.prompt(
                "Select a node",
                type=int,
                default=default,
                show_default=True,
            )

            if 1 <= choice <= len(candidates):
                chosen: NodeCandidate = candidates[choice - 1]
                return chosen
            else:
                click.echo(f"Please enter a number between 1 and {len(candidates)}")
        except click.Abort:
            raise
        except Exception:
            click.echo(f"Please enter a number between 1 and {len(candidates)}")


def resolve_node_interactive(
    mubase: MUbase,
    reference: str,
    root_path: Path | None = None,
) -> ResolvedNode:
    """Resolve a node with interactive disambiguation for TTY mode.

    In TTY mode, prompts the user to choose from multiple matches.
    In non-TTY mode, falls back to automatic resolution.

    Args:
        mubase: The MUbase database.
        reference: Node reference (name, ID, or path).
        root_path: Optional root path for relative path resolution.

    Returns:
        ResolvedNode with the resolved node.

    Raises:
        NodeNotFoundError: If no node matches.
        click.Abort: If user cancels interactive selection.
    """
    if not is_interactive():
        # Non-interactive: use prefer_source strategy
        return resolve_node_auto(mubase, reference, prefer_source=True)

    # Interactive mode
    resolver = NodeResolver(
        mubase,
        strategy=ResolutionStrategy.INTERACTIVE,
        interactive_callback=interactive_choose,
    )

    return resolver.resolve(reference)


def resolve_node_auto(
    mubase: MUbase,
    reference: str,
    prefer_source: bool = True,
) -> ResolvedNode:
    """Resolve a node automatically without user interaction.

    Suitable for scripts, pipelines, and non-TTY environments.

    Args:
        mubase: The MUbase database.
        reference: Node reference (name, ID, or path).
        prefer_source: If True, prefer non-test files. If False, use first match.

    Returns:
        ResolvedNode with the resolved node.

    Raises:
        NodeNotFoundError: If no node matches.
    """
    strategy = ResolutionStrategy.PREFER_SOURCE if prefer_source else ResolutionStrategy.FIRST_MATCH

    resolver = NodeResolver(mubase, strategy=strategy)
    return resolver.resolve(reference)


def resolve_node_strict(
    mubase: MUbase,
    reference: str,
) -> ResolvedNode:
    """Resolve a node with strict mode (error on ambiguity).

    Args:
        mubase: The MUbase database.
        reference: Node reference (name, ID, or path).

    Returns:
        ResolvedNode with the resolved node.

    Raises:
        NodeNotFoundError: If no node matches.
        AmbiguousNodeError: If multiple nodes match.
    """
    resolver = NodeResolver(mubase, strategy=ResolutionStrategy.STRICT)
    return resolver.resolve(reference)


def resolve_node_for_command(
    mubase: MUbase,
    reference: str,
    no_interactive: bool = False,
    quiet: bool = False,
) -> tuple[Node, ResolvedNode]:
    """Resolve a node for CLI command use with proper error handling.

    Handles:
    - Interactive vs. non-interactive mode
    - Error printing for not-found
    - Resolution info printing when ambiguous

    Args:
        mubase: The MUbase database.
        reference: Node reference (name, ID, or path).
        no_interactive: If True, skip interactive prompts even in TTY mode.
        quiet: If True, suppress resolution info messages.

    Returns:
        Tuple of (resolved Node, ResolvedNode with metadata).

    Raises:
        SystemExit: If node not found (prints error and exits).
        click.Abort: If user cancels interactive selection.
    """
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info

    try:
        if no_interactive or not is_interactive():
            result = resolve_node_auto(mubase, reference, prefer_source=True)
        else:
            result = resolve_node_interactive(mubase, reference)

        # Print resolution info if ambiguous and not quiet
        if result.was_ambiguous and not quiet:
            print_resolution_info(result, reference)

        return result.node, result

    except NodeNotFoundError:
        print_error(f"Node not found: {reference}")
        print_info(
            "Try using:\n"
            "  - Full node ID: 'mod:src/file.py' or 'cls:src/file.py:ClassName'\n"
            "  - File path: 'src/file.py'\n"
            "  - Class/function name: 'AuthService' or 'login'"
        )
        sys.exit(ExitCode.CONFIG_ERROR)

    except AmbiguousNodeError as e:
        # This shouldn't happen unless using STRICT mode
        print_error(f"Ambiguous node reference: {reference}")
        print_info(f"Matches: {', '.join(c.node.id for c in e.candidates[:5])}")
        if len(e.candidates) > 5:
            print_info(f"  ... and {len(e.candidates) - 5} more")
        sys.exit(ExitCode.CONFIG_ERROR)


def print_resolution_info(result: ResolvedNode, reference: str) -> None:
    """Print resolution info when disambiguation was used.

    Args:
        result: The ResolvedNode result.
        reference: The original reference string.
    """
    from mu.logging import print_info

    alt_count = len(result.alternatives)
    if alt_count > 0:
        # Get summary of alternatives
        alt_names = [alt.node.name for alt in result.alternatives[:3]]
        if alt_count > 3:
            alt_names.append(f"... +{alt_count - 3} more")
        alt_str = ", ".join(alt_names)

        print_info(
            f"Resolved '{reference}' -> {result.node.id}\n"
            f"  ({alt_count} other match{'es' if alt_count > 1 else ''}: {alt_str})"
        )


def format_resolution_for_json(result: ResolvedNode, reference: str) -> dict[str, object]:
    """Format resolution metadata for JSON output.

    Args:
        result: The ResolvedNode result.
        reference: The original reference string.

    Returns:
        Dictionary with resolution metadata.
    """
    return {
        "reference": reference,
        "resolved_id": result.node.id,
        "resolved_name": result.node.name,
        "resolution_method": result.resolution_method,
        "was_ambiguous": result.was_ambiguous,
        "alternative_count": len(result.alternatives),
        "alternatives": [
            {
                "node_id": alt.node.id,
                "name": alt.node.name,
                "is_test": alt.is_test,
            }
            for alt in result.alternatives[:10]  # Limit for output size
        ],
    }


__all__ = [
    "is_interactive",
    "shorten_path",
    "format_candidate_display",
    "interactive_choose",
    "resolve_node_interactive",
    "resolve_node_auto",
    "resolve_node_strict",
    "resolve_node_for_command",
    "print_resolution_info",
    "format_resolution_for_json",
]
