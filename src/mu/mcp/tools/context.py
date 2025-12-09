"""Context extraction tools."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mu.client import DaemonError
from mu.mcp.models import ContextResult, OmegaContextOutput
from mu.mcp.tools._utils import find_mubase, get_client
from mu.paths import MU_DIR, MUBASE_FILE


def mu_context(question: str, max_tokens: int = 8000) -> ContextResult:
    """Extract smart context for a natural language question.

    Analyzes the question, finds relevant code nodes, and returns
    a token-efficient MU format representation.

    Examples:
    - "How does authentication work?"
    - "What calls the payment processing logic?"
    - "Show me the database models"

    Args:
        question: Natural language question about the codebase
        max_tokens: Maximum tokens in the output (default 8000)

    Returns:
        MU format context with token count
    """
    cwd = str(Path.cwd())

    try:
        client = get_client()
        with client:
            result = client.context(question, max_tokens=max_tokens, cwd=cwd)

        # Handle both Rust daemon and Python response formats
        mu_text = result.get("mu_text") or result.get("mu_output", "")
        token_count = result.get("token_count") or result.get("tokens", 0)
        return ContextResult(
            mu_text=mu_text,
            token_count=token_count,
            node_count=len(result.get("nodes", [])),
        )
    except DaemonError:
        mubase_path = find_mubase()
        if not mubase_path:
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu daemon start .' first."
            ) from None

        from mu.kernel import MUbase
        from mu.kernel.context import ExtractionConfig, SmartContextExtractor

        db = MUbase(mubase_path)
        try:
            cfg = ExtractionConfig(max_tokens=max_tokens)
            extractor = SmartContextExtractor(db, cfg)
            ctx_result = extractor.extract(question)
            return ContextResult(
                mu_text=ctx_result.mu_text,
                token_count=ctx_result.token_count,
                node_count=len(ctx_result.nodes),
            )
        finally:
            db.close()


def mu_context_omega(
    question: str,
    max_tokens: int = 8000,
    include_synthesized: bool = True,
    max_synthesized_macros: int = 5,
    include_seed: bool = True,
) -> OmegaContextOutput:
    """Extract OMEGA-compressed context for a natural language question.

    Like mu_context, but uses S-expression format with macro compression
    for 3-5x token reduction. The output is split into:

    - **Seed**: Macro definitions (stable, cacheable)
    - **Body**: Compressed code context using those macros

    This separation optimizes prompt cache efficiency - the seed rarely
    changes between queries.

    Args:
        question: Natural language question about the codebase
        max_tokens: Maximum tokens in the output (default 8000)
        include_synthesized: Include codebase-specific macros (default True)
        max_synthesized_macros: Max synthesized macros to use (default 5)
        include_seed: Include macro definitions in full_output (default True).
                     Set to False on follow-up queries to save ~400 tokens
                     when the seed is already in the conversation context.

    Returns:
        OmegaContextOutput with seed, body, and compression metrics

    Examples:
        - mu_context_omega("How does authentication work?")
        - mu_context_omega("What are the API endpoints?", max_tokens=4000)
        - mu_context_omega("Show database models", include_synthesized=False)
        - mu_context_omega("Next question", include_seed=False)  # Skip seed

    Use Cases:
        - LLM context injection with minimal token usage
        - Prompt cache optimization
        - Large codebase exploration
    """
    mubase_path = find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu kernel build' first.")

    from mu.kernel import MUbase

    db = MUbase(mubase_path, read_only=True)

    try:
        from mu.kernel.context.omega import OmegaConfig, OmegaContextExtractor

        config = OmegaConfig(
            max_tokens=max_tokens,
            include_synthesized=include_synthesized,
            max_synthesized_macros=max_synthesized_macros,
        )

        extractor = OmegaContextExtractor(db, config)
        result = extractor.extract(question)

        # If include_seed=False, only return the body (seed already in context)
        if include_seed:
            full_output = result.full_output
            total_tokens = result.total_tokens
        else:
            full_output = result.body
            total_tokens = result.body_tokens

        return OmegaContextOutput(
            seed=result.seed if include_seed else "",
            body=result.body,
            full_output=full_output,
            macros_used=result.macros_used,
            seed_tokens=result.seed_tokens if include_seed else 0,
            body_tokens=result.body_tokens,
            total_tokens=total_tokens,
            original_tokens=result.original_tokens,
            compression_ratio=result.compression_ratio,
            nodes_included=result.nodes_included,
            manifest=result.manifest.to_dict(),
        )
    finally:
        db.close()


def register_context_tools(mcp: FastMCP) -> None:
    """Register context extraction tools with FastMCP server."""
    mcp.tool()(mu_context)
    mcp.tool()(mu_context_omega)
