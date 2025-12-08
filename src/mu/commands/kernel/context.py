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
    type=click.Choice(["mu", "json"]),
    default="mu",
    help="Output format",
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

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first to create the graph database")
        sys.exit(ExitCode.CONFIG_ERROR)

    db = MUbase(mubase_path)

    # Check for embeddings (optional but recommended)
    has_embeddings = db.has_embeddings()
    if not has_embeddings and verbose:
        print_warning("No embeddings found - using entity extraction only")
        print_info("Run 'mu kernel embed' for better semantic matching")

    # Build extraction config
    config = ExtractionConfig(
        max_tokens=max_tokens,
        include_imports=not no_imports,
        expand_depth=depth,
        exclude_tests=exclude_tests,
    )

    # Create extractor
    extractor = SmartContextExtractor(db, config)

    # Override exporter if scores requested
    if scores:
        extractor.exporter = ContextExporter(db, include_scores=True)

    print_info(f"Extracting context for: {question}")

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

    # Copy to clipboard if requested
    if copy:
        try:
            import pyperclip

            pyperclip.copy(output_str)
            print_success("Copied to clipboard")
        except Exception as e:
            print_warning(f"Could not copy to clipboard: {e}")

    # Display output
    if not result.nodes:
        print_warning("No relevant context found for the question")
        if verbose:
            print_info("Try a more specific question or run 'mu kernel embed' for semantic search")
    else:
        console.print(output_str)
        if not verbose:
            print_info(f"\n({result.token_count} tokens, {len(result.nodes)} nodes)")


__all__ = ["kernel_context"]
