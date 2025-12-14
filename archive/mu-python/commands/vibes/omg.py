"""MU omg command - Ship mode with OMEGA compressed context.

This command extracts context for questions using OMEGA S-expression format
with macro compression for maximum token efficiency. Supports task bundle mode
for comprehensive development context.
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


def _omg_task_mode(
    mubase_path: Path,
    task_description: str,
    tokens: int,
    as_json: bool,
    raw: bool,
) -> None:
    """Handle omg --task mode: extract task bundle with patterns, warnings, entry points."""
    import json

    from mu.errors import ExitCode
    from mu.extras.intelligence import TaskContextConfig, TaskContextExtractor
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import console, print_error

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)

    try:
        config = TaskContextConfig(max_tokens=tokens)
        extractor = TaskContextExtractor(db, config)
        result = extractor.extract(task_description)

        if as_json:
            click.echo(json.dumps(result.to_dict(), indent=2))
            return

        if raw:
            # Just the MU text
            click.echo(result.mu_text)
            return

        # Output with task bundle sections
        click.echo()
        click.echo(
            click.style("OMG Task Bundle ", fg="green", bold=True)
            + click.style(f"({result.token_count:,} tokens)", dim=True)
        )
        click.echo()

        # Task analysis
        if result.task_analysis:
            analysis = result.task_analysis
            click.echo(click.style("Task Analysis", fg="cyan", bold=True))
            click.echo(click.style("  Type: ", dim=True) + analysis.task_type.value)
            if analysis.entity_types:
                entity_str = ", ".join(et.value for et in analysis.entity_types[:3])
                click.echo(click.style("  Entities: ", dim=True) + entity_str)
            if analysis.domain_hints:
                click.echo(click.style("  Domains: ", dim=True) + ", ".join(analysis.domain_hints))
            click.echo(click.style("  Confidence: ", dim=True) + f"{analysis.confidence:.0%}")
            click.echo()

        # Entry points
        if result.entry_points:
            click.echo(click.style("Entry Points", fg="cyan", bold=True))
            for ep in result.entry_points[:5]:
                click.echo(click.style("  -> ", fg="green") + ep)
            click.echo()

        # Relevant files
        if result.relevant_files:
            click.echo(
                click.style(f"Relevant Files ({len(result.relevant_files)})", fg="cyan", bold=True)
            )
            # mubase_path is .mu/mubase, root is 2 levels up
            root_path = mubase_path.parent.parent
            for fc in result.relevant_files[:10]:
                relevance_pct = f"{fc.relevance:.0%}"
                # Display relative path if possible
                try:
                    display_path = str(Path(fc.path).relative_to(root_path))
                except (ValueError, TypeError):
                    display_path = fc.path
                click.echo(
                    click.style(f"  [{relevance_pct:>4}] ", dim=True)
                    + display_path
                    + click.style(f" - {fc.reason}", dim=True)
                )
            if len(result.relevant_files) > 10:
                click.echo(
                    click.style(f"  ... and {len(result.relevant_files) - 10} more", dim=True)
                )
            click.echo()

        # Patterns
        if result.patterns:
            click.echo(click.style("Patterns to Follow", fg="cyan", bold=True))
            for pattern in result.patterns[:5]:
                click.echo(
                    click.style("  * ", dim=True)
                    + click.style(pattern.name, bold=True)
                    + click.style(f" ({pattern.frequency}x)", dim=True)
                )
                click.echo(click.style(f"    {pattern.description}", dim=True))
            click.echo()

        # Warnings
        if result.warnings:
            click.echo(click.style("Warnings", fg="yellow", bold=True))
            for warning in result.warnings[:5]:
                icon = "!!" if warning.level in ("warn", "error") else "i"
                color = "red" if warning.level == "error" else "yellow"
                click.echo(click.style(f"  {icon} ", fg=color) + warning.message)
                if warning.related_file:
                    try:
                        rel_warn_path = str(Path(warning.related_file).relative_to(root_path))
                    except (ValueError, TypeError):
                        rel_warn_path = warning.related_file
                    click.echo(click.style(f"     -> {rel_warn_path}", dim=True))
            click.echo()

        # Suggestions
        if result.suggestions:
            click.echo(click.style("Suggestions", fg="cyan", bold=True))
            for suggestion in result.suggestions[:3]:
                click.echo(click.style("  * ", dim=True) + suggestion.message)
            click.echo()

        # Code context
        if result.mu_text:
            click.echo(click.style("Code Context", fg="cyan", bold=True))
            click.echo(click.style(f"  ({result.token_count} tokens)", dim=True))
            click.echo()
            console.print(result.mu_text, markup=False)
            click.echo()

        # Footer
        stats = result.extraction_stats
        click.echo(
            click.style("Extraction: ", dim=True)
            + click.style(f"{stats.get('extraction_time_ms', 0):.0f}ms", fg="cyan")
            + click.style(f" | {stats.get('files_found', 0)} files", dim=True)
            + click.style(f" | {stats.get('patterns_found', 0)} patterns", dim=True)
            + click.style(f" | {stats.get('warnings_found', 0)} warnings", dim=True)
        )
        click.echo(click.style("Ready to ship. Go build something awesome!", dim=True))

    finally:
        db.close()


@click.command(name="omg", short_help="Ship mode - Task bundle or OMEGA context")
@click.argument("question", required=False)
@click.option("--tokens", "-t", default=8000, help="Max tokens in output")
@click.option("--no-seed", is_flag=True, help="Omit schema seed (for follow-up queries)")
@click.option("--raw", is_flag=True, help="Output raw S-expressions only")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--task", "-T", is_flag=True, help="Task bundle mode - include patterns, warnings, entry points"
)
@click.pass_obj
def omg(
    ctx: MUContext,
    question: str | None,
    tokens: int,
    no_seed: bool,
    raw: bool,
    as_json: bool,
    task: bool,
) -> None:
    """Ship mode - Task bundle or OMEGA compressed context.

    Extracts context for your question using OMEGA S-expression format
    with macro compression for maximum token efficiency.

    \b
    Task mode (--task/-T) bundles:
    - Context extraction (relevant code)
    - Codebase patterns (conventions to follow)
    - Proactive warnings (high-impact, security, staleness)
    - Entry points (where to start)
    - Suggestions (related changes)

    \b
    Examples:
        mu omg "How does authentication work?"
        mu omg "What are the API endpoints?" -t 4000
        mu omg  # Interactive mode - prompts for question
        mu omg "auth" --no-seed  # Omit schema for follow-ups
        mu omg "Add rate limiting to API" --task  # Task bundle mode
        mu omg -T "Fix login bug"  # Short form
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.kernel.context.omega import OmegaConfig, OmegaContextExtractor
    from mu.logging import console, print_error

    # Interactive mode if no question provided
    if not question:
        prompt_text = "What task are you working on?" if task else "What do you want to understand?"
        question = prompt_for_input(prompt_text, "omg")

    # Find mubase
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    if not mubase_path:
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(1)

    # Task bundle mode - use TaskContextExtractor
    if task:
        _omg_task_mode(mubase_path, question, tokens, as_json, raw)
        return

    # Try daemon first
    client = DaemonClient()
    if client.is_running():
        try:
            daemon_result = client.context_omega(
                question=question,
                max_tokens=tokens,
                include_seed=not no_seed,
                cwd=str(cwd),
            )

            if as_json:
                click.echo(json.dumps(daemon_result, indent=2))
                return

            full_output = daemon_result.get("full_output", "")
            total_tokens = daemon_result.get("total_tokens", 0)
            seed_tokens = daemon_result.get("seed_tokens", 0)
            body_tokens = daemon_result.get("body_tokens", 0)
            compression_ratio = daemon_result.get("compression_ratio", 1.0)
            original_tokens = daemon_result.get("original_tokens", 0)
            seed = daemon_result.get("seed", "")
            body = daemon_result.get("body", "")

            if raw:
                if no_seed:
                    click.echo(body)
                else:
                    click.echo(full_output)
                return

            # Output with personality
            click.echo()
            click.echo(
                click.style("OMG Context ", fg="green", bold=True)
                + click.style(f"({total_tokens:,} tokens)", dim=True)
            )
            click.echo()

            if not no_seed and seed:
                click.echo(
                    click.style(f";; Schema seed ({seed_tokens} tokens) - cache this", dim=True)
                )
                console.print(seed, markup=False)
                click.echo()

            click.echo(click.style(f";; Body ({body_tokens} tokens)", dim=True))
            console.print(body, markup=False)

            click.echo()
            click.echo(
                click.style("Compression: ", dim=True)
                + click.style(f"{compression_ratio:.1f}x", fg="cyan", bold=True)
                + click.style(f" ({original_tokens:,} -> {total_tokens:,} tokens)", dim=True)
            )
            click.echo(click.style("Your context just lost mass.", dim=True))
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
        config = OmegaConfig(
            max_tokens=tokens,
            include_synthesized=True,
            max_synthesized_macros=5,
        )
        extractor = OmegaContextExtractor(db, config)
        result = extractor.extract(question)

        if as_json:
            click.echo(json.dumps(result.to_dict(), indent=2))
            return

        if raw:
            # Just the S-expressions
            if no_seed:
                click.echo(result.body)
            else:
                click.echo(result.full_output)
            return

        # Output with personality
        click.echo()
        click.echo(
            click.style("OMG Context ", fg="green", bold=True)
            + click.style(f"({result.total_tokens:,} tokens)", dim=True)
        )
        click.echo()

        if not no_seed and result.seed:
            click.echo(
                click.style(f";; Schema seed ({result.seed_tokens} tokens) - cache this", dim=True)
            )
            console.print(result.seed, markup=False)
            click.echo()

        click.echo(click.style(f";; Body ({result.body_tokens} tokens)", dim=True))
        console.print(result.body, markup=False)

        click.echo()
        click.echo(
            click.style("Compression: ", dim=True)
            + click.style(f"{result.compression_ratio:.1f}x", fg="cyan", bold=True)
            + click.style(
                f" ({result.original_tokens:,} -> {result.total_tokens:,} tokens)", dim=True
            )
        )
        click.echo(click.style("Your context just lost mass.", dim=True))

    finally:
        db.close()


__all__ = ["omg"]
