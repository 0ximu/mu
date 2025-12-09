"""MU kernel context command - Extract optimal context for a question."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import get_mubase_path

if TYPE_CHECKING:
    from mu.cli import MUContext


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
    "--scores",
    is_flag=True,
    help="Include relevance scores in output",
)
@click.option(
    "--copy",
    is_flag=True,
    help="Copy output to clipboard",
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
    scores: bool,
    copy: bool,
) -> None:
    """Extract optimal context for a question.

    Uses smart context extraction to find the most relevant code
    for answering a natural language question about your codebase.

    \b
    Examples:
        mu kernel context "How does authentication work?"
        mu kernel context "What's in the CLI?" --max-tokens 2000
        mu kernel context "database queries" --exclude-tests -v
        mu kernel context "parser logic" --format json
    """
    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.kernel.context import ExtractionConfig, SmartContextExtractor
    from mu.kernel.context.export import ContextExporter
    from mu.logging import console, print_error, print_info, print_success, print_warning

    # Validate input before any database access
    if not question or not question.strip():
        print_error("Question cannot be empty. Please provide a question about the codebase.")
        sys.exit(ExitCode.CONFIG_ERROR)

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first to create the graph database")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path, read_only=True)

    # Check for embeddings (optional but recommended)
    has_embeddings = db.has_embeddings()
    if not has_embeddings and verbose:
        print_warning("No embeddings found - using entity extraction only")
        print_info("Run 'mu kernel embed' for better semantic matching")

    print_info(f"Extracting context for: {question}")

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
