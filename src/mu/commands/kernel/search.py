"""MU kernel search command - Semantic search for code nodes."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import get_mubase_path

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command("search")
@click.argument("query", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--limit",
    "-l",
    type=int,
    default=10,
    help="Maximum number of results",
)
@click.option(
    "--type",
    "-t",
    "node_type",
    type=click.Choice(["module", "class", "function"]),
    help="Filter by node type",
)
@click.option(
    "--embedding",
    "-e",
    type=click.Choice(["code", "docstring", "name"]),
    default="code",
    help="Which embedding to search",
)
@click.option(
    "--provider",
    "-p",
    type=click.Choice(["openai", "local"]),
    help="Provider for query embedding (default: from config)",
)
@click.option(
    "--local",
    is_flag=True,
    help="Force local embeddings for query",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON",
)
@click.pass_obj
def kernel_search(
    ctx: MUContext,
    query: str,
    path: Path,
    limit: int,
    node_type: str | None,
    embedding: str,
    provider: str | None,
    local: bool,
    as_json: bool,
) -> None:
    """Semantic search for code nodes.

    Search the codebase using natural language queries. Finds nodes
    semantically similar to the query, even if they don't contain
    the exact words.

    \b
    Examples:
        mu kernel search "authentication logic"
        mu kernel search "database connection" --type function
        mu kernel search "error handling" --limit 20 --json
    """
    import asyncio
    import json as json_module

    from rich.table import Table

    from mu.config import MUConfig
    from mu.errors import ExitCode
    from mu.kernel import MUbase, NodeType
    from mu.kernel.embeddings import EmbeddingService
    from mu.logging import console, print_error, print_info

    if ctx.config is None:
        ctx.config = MUConfig()

    mubase_path = get_mubase_path(path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' and 'mu kernel embed' first")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Determine provider
    embed_provider = provider
    if local:
        embed_provider = "local"
    elif embed_provider is None:
        embed_provider = ctx.config.embeddings.provider

    # Check for API key if using OpenAI
    if embed_provider == "openai":
        import os

        api_key_env = ctx.config.embeddings.openai.api_key_env
        if not os.environ.get(api_key_env):
            print_error("OpenAI API key not found")
            print_info(f"Set {api_key_env} or use --local for local embeddings")
            sys.exit(ExitCode.CONFIG_ERROR)

    # Open database
    db = MUbase(mubase_path)

    # Check if embeddings exist
    embed_stats = db.embedding_stats()
    if embed_stats["nodes_with_embeddings"] == 0:
        print_error("No embeddings found in database")
        print_info("Run 'mu kernel embed' first to generate embeddings")
        db.close()
        sys.exit(ExitCode.CONFIG_ERROR)

    # Create embedding service for query
    service = EmbeddingService(
        config=ctx.config.embeddings,
        provider=embed_provider,
    )

    # Embed the query
    async def get_query_embedding() -> list[float] | None:
        return await service.embed_query(query)

    print_info(f"Searching for: {query}")
    query_embedding = asyncio.run(get_query_embedding())

    if query_embedding is None:
        print_error("Failed to generate query embedding")
        db.close()
        asyncio.run(service.close())
        sys.exit(ExitCode.FATAL_ERROR)

    # Perform vector search
    nt = NodeType(node_type) if node_type else None
    results = db.vector_search(
        query_embedding=query_embedding,
        embedding_type=embedding,
        limit=limit,
        node_type=nt,
    )

    db.close()
    asyncio.run(service.close())

    if not results:
        print_info("No results found")
        return

    if as_json:
        output = {
            "query": query,
            "results": [
                {
                    "node": node.to_dict(),
                    "similarity": round(score, 4),
                }
                for node, score in results
            ],
        }
        console.print(json_module.dumps(output, indent=2))
        return

    # Display results as table
    table = Table(title=f"Search Results for: {query}")
    table.add_column("Score", style="yellow", width=8)
    table.add_column("Type", style="cyan", width=10)
    table.add_column("Name", style="green")
    table.add_column("File", style="dim")

    for node, score in results:
        file_display = node.file_path or ""
        if len(file_display) > 35:
            file_display = "..." + file_display[-32:]

        table.add_row(
            f"{score:.3f}",
            node.type.value,
            node.name,
            file_display,
        )

    console.print(table)


__all__ = ["kernel_search"]
