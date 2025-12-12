"""MU kernel embed command - Generate embeddings for codebase nodes."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import get_mubase_path

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command("embed")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--provider",
    "-p",
    type=click.Choice(["openai", "local"]),
    help="Embedding provider to use (default: from config)",
)
@click.option(
    "--model",
    "-m",
    type=str,
    help="Embedding model to use",
)
@click.option(
    "--batch-size",
    "-b",
    type=int,
    default=100,
    help="Batch size for embedding generation",
)
@click.option(
    "--local",
    is_flag=True,
    help="Force local embeddings (sentence-transformers)",
)
@click.option(
    "--model-path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to a custom sentence-transformers model directory",
)
@click.option(
    "--type",
    "-t",
    "node_types",
    type=click.Choice(["module", "class", "function"]),
    multiple=True,
    help="Node types to embed (default: all)",
)
@click.pass_obj
def kernel_embed(
    ctx: MUContext,
    path: Path,
    provider: str | None,
    model: str | None,
    batch_size: int,
    local: bool,
    model_path: Path | None,
    node_types: tuple[str, ...],
) -> None:
    """Generate embeddings for codebase nodes.

    Creates vector embeddings for code graph nodes to enable semantic search.
    Requires a .mubase file - run 'mu bootstrap' first.

    \b
    Examples:
        mu embed .                    # Embed all nodes with OpenAI
        mu embed . --local            # Use local sentence-transformers
        mu embed . --type function    # Only embed functions
        mu embed . --provider openai --model text-embedding-3-large
        mu embed . --model-path ./models/my-model  # Use custom local model
    """
    import asyncio

    from mu.config import MUConfig
    from mu.errors import ExitCode
    from mu.extras.embeddings import EmbeddingService
    from mu.extras.embeddings.models import NodeEmbedding
    from mu.kernel import MUbase, NodeType
    from mu.logging import create_progress, print_error, print_info, print_success, print_warning

    if ctx.config is None:
        ctx.config = MUConfig()

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first to create the graph database")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Determine provider
    embed_provider = provider
    if model_path is not None:
        # Custom model path implies local provider
        embed_provider = "local"
    elif local:
        embed_provider = "local"
    elif embed_provider is None:
        embed_provider = ctx.config.embeddings.provider

    # Check for API key if using OpenAI
    if embed_provider == "openai":
        import os

        api_key_env = ctx.config.embeddings.openai.api_key_env
        if not os.environ.get(api_key_env):
            print_error(f"OpenAI API key not found in environment variable {api_key_env}")
            print_info("Set the environment variable or use --local for local embeddings")
            sys.exit(ExitCode.CONFIG_ERROR)

    if model_path:
        print_info(f"Using custom model from {model_path}")
    else:
        print_info(f"Using {embed_provider} embedding provider")

    # Open database
    from mu.kernel import MUbaseLockError

    try:
        db = MUbase(mubase_path)
    except MUbaseLockError:
        print_error(
            "Database is locked by another process.\n\n"
            "This usually means the daemon is running. Options:\n"
            "  1. Stop the daemon: mu serve --stop\n"
            "  2. Let the daemon handle it: Use the MCP server or daemon API"
        )
        sys.exit(ExitCode.CONFIG_ERROR)

    # Get nodes to embed
    nodes = []
    if node_types:
        for nt in node_types:
            nodes.extend(db.get_nodes(NodeType(nt)))
    else:
        # Get all non-external nodes
        for node_type in [NodeType.MODULE, NodeType.CLASS, NodeType.FUNCTION]:
            nodes.extend(db.get_nodes(node_type))

    if not nodes:
        print_warning("No nodes found to embed")
        db.close()
        return

    print_info(f"Found {len(nodes)} nodes to embed")

    # Create embedding service
    service = EmbeddingService(
        config=ctx.config.embeddings,
        provider=embed_provider,
        model=model,
        model_path=str(model_path) if model_path else None,
    )

    async def run_embedding() -> list[NodeEmbedding]:
        with create_progress() as progress:
            task = progress.add_task(
                "Generating embeddings...",
                total=len(nodes),
            )

            def on_progress(completed: int, total: int) -> None:
                progress.update(task, completed=completed)

            embeddings = await service.embed_nodes(
                nodes,
                batch_size=batch_size,
                on_progress=on_progress,
            )

            return embeddings

    embeddings = asyncio.run(run_embedding())

    # Store embeddings
    print_info("Storing embeddings...")
    db.add_embeddings_batch(embeddings)

    # Report results
    stats = service.stats
    print_success(f"Generated {stats.successful} embeddings")
    if stats.failed > 0:
        print_warning(f"  {stats.failed} failed")

    # Show embedding stats
    embed_stats = db.embedding_stats()
    print_info(f"  Coverage: {embed_stats['coverage_percent']:.1f}%")

    db.close()

    # Cleanup
    asyncio.run(service.close())


__all__ = ["kernel_embed"]
