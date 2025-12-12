"""MU grok command - Understand code by extracting relevant context.

This command analyzes questions and finds relevant code nodes, returning
a token-efficient representation ready for LLM consumption.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import find_mubase_path

from ._utils import prompt_for_input

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command(name="grok", short_help="Understand code - extract relevant context")
@click.argument("question", required=False)
@click.option("--tokens", "-t", default=8000, help="Max tokens in output")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["mu", "json", "markdown"]),
    default="mu",
    help="Output format",
)
@click.option("--with-tests", is_flag=True, help="Include test files (excluded by default)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON (alias for -f json)")
@click.pass_obj
def grok(
    ctx: MUContext,
    question: str | None,
    tokens: int,
    output_format: str,
    with_tests: bool,
    as_json: bool,
) -> None:
    """Understand code - extract relevant context for your question.

    Analyzes your question, finds relevant code nodes, and returns
    a token-efficient representation ready for LLM consumption.

    By default, test files are excluded to focus on production code.
    Use --with-tests to include them.

    \b
    Examples:
        mu grok "How does authentication work?"
        mu grok "What calls the payment processor?" -t 4000
        mu grok  # Interactive mode
        mu grok "test patterns" --with-tests
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.context import ExtractionConfig, SmartContextExtractor
    from mu.logging import console, print_error

    # Handle --json flag
    if as_json:
        output_format = "json"

    # Interactive mode if no question provided
    if not question:
        question = prompt_for_input("What do you want to understand?", "grok")

    # Find mubase
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    if not mubase_path:
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(1)

    # Try daemon first
    client = DaemonClient()
    if client.is_running():
        try:
            daemon_result = client.context(question, max_tokens=tokens, cwd=str(cwd))
            mu_text = daemon_result.get("mu_text", "")
            token_count = daemon_result.get("token_count", 0)
            nodes = daemon_result.get("nodes", [])

            # Calculate token count if daemon didn't provide it
            if token_count == 0 and mu_text:
                try:
                    import tiktoken

                    enc = tiktoken.get_encoding("cl100k_base")
                    token_count = len(enc.encode(mu_text))
                except ImportError:
                    # Fallback: rough estimate of ~4 chars per token
                    token_count = len(mu_text) // 4

            if output_format == "json":
                click.echo(
                    json.dumps(
                        {
                            "question": question,
                            "mu_text": mu_text,
                            "token_count": token_count,
                            "node_count": len(nodes),
                        },
                        indent=2,
                    )
                )
                return

            # Output with personality
            click.echo()
            click.echo(
                click.style("Grokking... ", fg="blue", bold=True)
                + click.style(f"({len(nodes)} nodes, {token_count} tokens)", dim=True)
            )
            click.echo()
            console.print(mu_text, markup=False)
            click.echo()
            click.echo(click.style("Ready for enlightenment. Feed to your LLM. 🧠", dim=True))
            return
        except DaemonError:
            pass  # Fall through to local mode

    # Local mode
    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)

    try:
        # Exclude tests by default, unless --with-tests is passed
        cfg = ExtractionConfig(max_tokens=tokens, exclude_tests=not with_tests)
        extractor = SmartContextExtractor(db, cfg)
        result = extractor.extract(question)

        if output_format == "json":
            click.echo(
                json.dumps(
                    {
                        "question": question,
                        "mu_text": result.mu_text,
                        "token_count": result.token_count,
                        "node_count": len(result.nodes),
                    },
                    indent=2,
                )
            )
            return

        click.echo()
        click.echo(
            click.style("Grokking... ", fg="blue", bold=True)
            + click.style(
                f"({len(result.nodes)} nodes, {result.token_count} tokens)",
                dim=True,
            )
        )
        click.echo()

        if output_format == "markdown":
            click.echo(f"## Context for: {question}\n")
            click.echo("```mu")
            console.print(result.mu_text, markup=False)
            click.echo("```")
        else:
            console.print(result.mu_text, markup=False)

        click.echo()
        click.echo(click.style("Ready for enlightenment. Feed to your LLM. 🧠", dim=True))

    finally:
        db.close()


__all__ = ["grok"]
