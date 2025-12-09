"""MU kernel context command - Extract optimal context for a question.

DEPRECATED: Use 'mu context' instead.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from mu.paths import get_mubase_path

if TYPE_CHECKING:
    from mu.cli import MUContext


def _show_deprecation_warning() -> None:
    """Show deprecation warning for kernel context."""
    click.secho(
        "⚠️  'mu kernel context' is deprecated. Use 'mu context' instead.",
        fg="yellow",
        err=True,
    )


@click.command("context")
@click.argument("question", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--max-tokens",
    "-t",
    type=int,
    default=8000,
    help="Maximum tokens in output",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["mu", "json", "omega"]),
    default="mu",
    help="Output format (omega for S-expression with macro compression)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show extraction statistics",
)
@click.option(
    "--no-imports",
    is_flag=True,
    help="Exclude import context",
)
@click.option(
    "--depth",
    type=int,
    default=1,
    help="Graph expansion depth",
)
@click.option(
    "--exclude-tests",
    is_flag=True,
    help="Exclude test files from results",
)
@click.option(
    "--docstrings/--no-docstrings",
    default=True,
    help="Include docstrings in output (default: enabled)",
)
@click.option(
    "--line-numbers/--no-line-numbers",
    default=False,
    help="Include line numbers for IDE integration (default: disabled)",
)
@click.option(
    "--imports/--no-imports",
    "include_imports",
    default=True,
    help="Include internal module imports (default: enabled)",
)
@click.option(
    "--scores",
    is_flag=True,
    help="Include relevance scores in output",
)
@click.option(
    "--copy",
    is_flag=True,
    help="Copy output to clipboard",
)
@click.option(
    "--offline",
    is_flag=True,
    help="Skip daemon, use local DB directly (also: MU_OFFLINE=1)",
)
@click.pass_obj
def kernel_context(
    ctx: MUContext,
    question: str,
    path: Path,
    max_tokens: int,
    output_format: str,
    verbose: bool,
    no_imports: bool,
    depth: int,
    exclude_tests: bool,
    docstrings: bool,
    line_numbers: bool,
    include_imports: bool,
    scores: bool,
    copy: bool,
    offline: bool,
) -> None:
    """[DEPRECATED] Extract optimal context for a question.

    Use 'mu context' instead.

    \b
    Examples:
        mu context "How does authentication work?"
        mu context "What's in the CLI?" --max-tokens 2000
    """
    _show_deprecation_warning()
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info

    # Validate input before any database access
    if not question or not question.strip():
        print_error("Question cannot be empty. Please provide a question about the codebase.")
        sys.exit(ExitCode.CONFIG_ERROR)

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first to create the graph database")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Check for MU_OFFLINE environment variable
    if os.environ.get("MU_OFFLINE", "").lower() in ("1", "true", "yes"):
        offline = True

    # Try daemon first (Thin Client path - no lock)
    if not offline:
        from mu.client import DaemonClient, DaemonError
        from mu.logging import print_warning

        client = DaemonClient()
        if client.is_running():
            try:
                cwd = str(path.resolve())
                if output_format == "omega":
                    result = client.context_omega(
                        question=question,
                        max_tokens=max_tokens,
                        cwd=cwd,
                    )
                    _handle_daemon_omega_result(result, verbose, max_tokens, copy)
                else:
                    result = client.context(
                        question=question,
                        max_tokens=max_tokens,
                        exclude_tests=exclude_tests,
                        cwd=cwd,
                    )
                    _handle_daemon_context_result(result, output_format, verbose, scores, copy)
                return
            except DaemonError as e:
                print_warning(f"Daemon request failed, falling back to local mode: {e}")

    # Fallback: Local mode (direct database access)
    _execute_context_local(
        mubase_path=mubase_path,
        question=question,
        max_tokens=max_tokens,
        output_format=output_format,
        verbose=verbose,
        no_imports=no_imports,
        depth=depth,
        exclude_tests=exclude_tests,
        docstrings=docstrings,
        line_numbers=line_numbers,
        include_imports=include_imports,
        scores=scores,
        copy=copy,
    )


def _handle_daemon_context_result(
    result: dict[str, Any],
    output_format: str,
    verbose: bool,
    scores: bool,
    copy: bool,
) -> None:
    """Handle context result from daemon."""
    import json as json_module

    from mu.logging import console, print_info, print_success, print_warning

    mu_text = result.get("mu_text", "")
    token_count = result.get("token_count", 0)
    nodes = result.get("nodes", [])
    node_count = len(nodes)

    if verbose:
        stats = result.get("extraction_stats", {})
        print_info("")
        print_info("Extraction Statistics:")
        print_info(f"  Entities found: {stats.get('entities_extracted', 0)}")
        if stats.get("entities"):
            print_info(f"    {', '.join(stats['entities'][:5])}")
        print_info(f"  Named matches: {stats.get('named_nodes_found', 0)}")
        print_info(f"  Vector matches: {stats.get('vector_matches', 0)}")
        print_info(f"  After expansion: {stats.get('candidates_after_expansion', 0)}")
        print_info(f"  Selected nodes: {stats.get('selected_nodes', 0)}")
        print_info(f"  Token count: {token_count}")
        print_info(f"  Budget usage: {stats.get('budget_utilization', 0)}%")
        print_info("")

    # Format output
    if output_format == "json":
        output_str = json_module.dumps(result, indent=2)
    else:
        output_str = mu_text

    # Copy to clipboard if requested
    if copy:
        try:
            import pyperclip

            pyperclip.copy(output_str)
            print_success("Copied to clipboard")
        except Exception as e:
            print_warning(f"Could not copy to clipboard: {e}")

    # Display output
    if node_count == 0:
        print_warning("No relevant context found for the question")
        if verbose:
            print_info("Try a more specific question or run 'mu kernel embed' for semantic search")
    else:
        console.print(output_str)
        if not verbose:
            print_info(f"\n({token_count} tokens, {node_count} nodes)")


def _handle_daemon_omega_result(
    result: dict[str, Any],
    verbose: bool,
    max_tokens: int,
    copy: bool,
) -> None:
    """Handle OMEGA context result from daemon."""
    from mu.logging import console, print_info, print_success, print_warning

    output_str = result.get("full_output", "")
    token_count = result.get("total_tokens", 0)
    node_count = result.get("nodes_included", 0)

    if verbose:
        print_info("")
        print_info("OMEGA Extraction Statistics:")
        print_info(f"  Nodes included: {node_count}")
        macros_used = result.get("macros_used", [])
        print_info(f"  Macros used: {len(macros_used)}")
        if macros_used:
            print_info(f"    {', '.join(macros_used[:5])}")
        print_info(f"  Seed tokens: {result.get('seed_tokens', 0)}")
        print_info(f"  Body tokens: {result.get('body_tokens', 0)}")
        print_info(f"  Total tokens: {token_count} / {max_tokens}")
        print_info(f"  Original tokens (sigils): {result.get('original_tokens', 0)}")
        print_info(f"  Compression ratio: {result.get('compression_ratio', 0):.2f}x")
        savings = result.get("tokens_saved", 0)
        pct = result.get("savings_percent", 0)
        print_info(f"  Tokens saved: {savings} ({pct:.1f}%)")
        print_info("")

    # Copy to clipboard if requested
    if copy:
        try:
            import pyperclip

            pyperclip.copy(output_str)
            print_success("Copied to clipboard")
        except Exception as e:
            print_warning(f"Could not copy to clipboard: {e}")

    # Display output
    if node_count == 0:
        print_warning("No relevant context found for the question")
        if verbose:
            print_info("Try a more specific question or run 'mu kernel embed' for semantic search")
    else:
        console.print(output_str)
        if not verbose:
            print_info(f"\n({token_count} tokens, {node_count} nodes)")


def _execute_context_local(
    mubase_path: Path,
    question: str,
    max_tokens: int,
    output_format: str,
    verbose: bool,
    no_imports: bool,
    depth: int,
    exclude_tests: bool,
    docstrings: bool,
    line_numbers: bool,
    include_imports: bool,
    scores: bool,
    copy: bool,
) -> None:
    """Execute context extraction in local mode (direct database access).

    Opens database in read-only mode to avoid lock conflicts.
    """
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.context import ExtractionConfig, SmartContextExtractor
    from mu.kernel.context.export import ContextExporter
    from mu.logging import console, print_error, print_info, print_success, print_warning

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error("Database is locked by another process.")
        print_info("")
        print_info("The daemon may be running. Try one of these:")
        print_info("  1. Start daemon: mu daemon start")
        print_info("     Then queries route through daemon automatically")
        print_info("  2. Stop daemon:  mu daemon stop")
        print_info("     Then run your query again")
        import sys

        from mu.errors import ExitCode

        sys.exit(ExitCode.CONFIG_ERROR)

    print_info(f"Extracting context for: {question}")

    # Check for embeddings (optional but recommended)
    has_embeddings = db.has_embeddings()
    if not has_embeddings and verbose:
        print_warning("No embeddings found - using entity extraction only")
        print_info("Run 'mu kernel embed' for better semantic matching")

    # Use OMEGA extractor for omega format, standard for others
    if output_format == "omega":
        from mu.kernel.context.omega import OmegaConfig, OmegaContextExtractor

        omega_config = OmegaConfig(max_tokens=max_tokens)
        omega_extractor = OmegaContextExtractor(db, omega_config)
        omega_result = omega_extractor.extract(question)

        db.close()

        # Show verbose stats for omega
        if verbose:
            stats = omega_result.extraction_stats
            print_info("")
            print_info("OMEGA Extraction Statistics:")
            print_info(f"  Nodes included: {omega_result.nodes_included}")
            print_info(f"  Macros used: {len(omega_result.macros_used)}")
            if omega_result.macros_used:
                print_info(f"    {', '.join(omega_result.macros_used[:5])}")
            print_info(f"  Seed tokens: {omega_result.seed_tokens}")
            print_info(f"  Body tokens: {omega_result.body_tokens}")
            print_info(f"  Total tokens: {omega_result.total_tokens} / {max_tokens}")
            print_info(f"  Original tokens (sigils): {omega_result.original_tokens}")
            print_info(f"  Compression ratio: {omega_result.compression_ratio:.2f}x")
            savings = omega_result.tokens_saved
            pct = omega_result.savings_percent
            print_info(f"  Tokens saved: {savings} ({pct:.1f}%)")
            print_info("")

        output_str = omega_result.full_output
        token_count = omega_result.total_tokens
        node_count = omega_result.nodes_included

    else:
        # Build standard extraction config
        config = ExtractionConfig(
            max_tokens=max_tokens,
            include_imports=not no_imports,
            include_docstrings=docstrings,
            include_line_numbers=line_numbers,
            expand_depth=depth,
            exclude_tests=exclude_tests,
        )

        # Create standard extractor
        extractor = SmartContextExtractor(db, config)

        # Override exporter if scores requested
        if scores:
            extractor.exporter = ContextExporter(db, include_scores=True)

        # Extract context
        result = extractor.extract(question)

        db.close()

        # Show verbose stats
        if verbose:
            stats = result.extraction_stats
            print_info("")
            print_info("Extraction Statistics:")
            print_info(f"  Entities found: {stats.get('entities_extracted', 0)}")
            if stats.get("entities"):
                print_info(f"    {', '.join(stats['entities'][:5])}")
            print_info(f"  Named matches: {stats.get('named_nodes_found', 0)}")
            print_info(f"  Vector matches: {stats.get('vector_matches', 0)}")
            print_info(f"  After expansion: {stats.get('candidates_after_expansion', 0)}")
            print_info(f"  Selected nodes: {stats.get('selected_nodes', 0)}")
            print_info(f"  Token count: {result.token_count} / {max_tokens}")
            print_info(f"  Budget usage: {stats.get('budget_utilization', 0)}%")
            print_info("")

        # Format output
        if output_format == "json":
            exporter = ContextExporter(db, include_scores=True)
            output_str = exporter.export_json(result)
        else:
            output_str = result.mu_text

        token_count = result.token_count
        node_count = len(result.nodes)

    # Copy to clipboard if requested
    if copy:
        try:
            import pyperclip

            pyperclip.copy(output_str)
            print_success("Copied to clipboard")
        except Exception as e:
            print_warning(f"Could not copy to clipboard: {e}")

    # Display output
    if node_count == 0:
        print_warning("No relevant context found for the question")
        if verbose:
            print_info("Try a more specific question or run 'mu kernel embed' for semantic search")
    else:
        console.print(output_str)
        if not verbose:
            print_info(f"\n({token_count} tokens, {node_count} nodes)")


__all__ = ["kernel_context"]
