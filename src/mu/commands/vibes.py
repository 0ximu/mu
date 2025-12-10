"""MU Quick Commands - Developer-friendly CLI with personality.

Quick Commands for common workflows:
- mu grok - Understand code - extract relevant context
- mu omg  - Ship mode - OMEGA compressed context
- mu yolo - Impact check - what breaks if I change this?
- mu sus  - Smell check - warnings before touching code
- mu vibe - Pattern check - does this code fit?
- mu wtf  - Git archaeology - why does this code exist?
- mu zen  - Clean up - clear caches
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import find_mubase_path

if TYPE_CHECKING:
    from mu.cli import MUContext


def _prompt_for_input(prompt_text: str, command_name: str = "this command") -> str:
    """Prompt user for input interactively.

    Args:
        prompt_text: The prompt message to display.
        command_name: The command name for error messages.

    Returns:
        User input string.

    Raises:
        SystemExit: If running in non-interactive mode or user cancels.
    """
    # Check if stdin is a TTY (interactive terminal)
    if not sys.stdin.isatty():
        click.echo(
            click.style("Error: ", fg="red")
            + f"{command_name} requires a target argument in non-interactive mode."
        )
        click.echo(click.style(f"Usage: mu {command_name} <target>", dim=True))
        sys.exit(1)

    try:
        result: str = click.prompt(click.style(prompt_text, fg="cyan"))
        return result
    except (click.Abort, EOFError):
        click.echo(click.style("\nCancelled.", dim=True))
        sys.exit(0)


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
    from mu.intelligence import TaskContextConfig, TaskContextExtractor
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
                click.echo(click.style("  → ", fg="green") + ep)
            click.echo()

        # Relevant files
        if result.relevant_files:
            click.echo(click.style(f"Relevant Files ({len(result.relevant_files)})", fg="cyan", bold=True))
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
                click.echo(click.style(f"  ... and {len(result.relevant_files) - 10} more", dim=True))
            click.echo()

        # Patterns
        if result.patterns:
            click.echo(click.style("Patterns to Follow", fg="cyan", bold=True))
            for pattern in result.patterns[:5]:
                click.echo(
                    click.style("  • ", dim=True)
                    + click.style(pattern.name, bold=True)
                    + click.style(f" ({pattern.frequency}x)", dim=True)
                )
                click.echo(click.style(f"    {pattern.description}", dim=True))
            click.echo()

        # Warnings
        if result.warnings:
            click.echo(click.style("Warnings", fg="yellow", bold=True))
            for warning in result.warnings[:5]:
                icon = "⚠️" if warning.level in ("warn", "error") else "ℹ️"
                color = "red" if warning.level == "error" else "yellow"
                click.echo(
                    click.style(f"  {icon} ", fg=color)
                    + warning.message
                )
                if warning.related_file:
                    try:
                        rel_warn_path = str(Path(warning.related_file).relative_to(root_path))
                    except (ValueError, TypeError):
                        rel_warn_path = warning.related_file
                    click.echo(click.style(f"     → {rel_warn_path}", dim=True))
            click.echo()

        # Suggestions
        if result.suggestions:
            click.echo(click.style("Suggestions", fg="cyan", bold=True))
            for suggestion in result.suggestions[:3]:
                click.echo(click.style("  💡 ", dim=True) + suggestion.message)
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
        click.echo(click.style("Ready to ship. Go build something awesome! 🚀", dim=True))

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
        question = _prompt_for_input(prompt_text, "omg")

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
                + click.style(f" ({original_tokens:,} → {total_tokens:,} tokens)", dim=True)
            )
            click.echo(click.style("Your context just lost mass. 🚀", dim=True))
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
                f" ({result.original_tokens:,} → {result.total_tokens:,} tokens)", dim=True
            )
        )
        click.echo(click.style("Your context just lost mass. 🚀", dim=True))

    finally:
        db.close()


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
        question = _prompt_for_input("What do you want to understand?", "grok")

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


@click.command(name="wtf", short_help="Git archaeology - why does this code exist?")
@click.argument("target", required=False)
@click.option("--commits", "-c", default=20, help="Max commits to analyze")
@click.option("--no-cochange", is_flag=True, help="Skip co-change analysis")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def wtf(ctx: MUContext, target: str | None, commits: int, no_cochange: bool, as_json: bool) -> None:
    """Git archaeology - why does this code exist?

    Analyzes git history to understand why code exists:
    - Who introduced it and when
    - The commit message and context
    - What typically changes with this code
    - Whether it's been stable or frequently modified

    \b
    Examples:
        mu wtf src/auth.py         # WTF happened to this file?
        mu wtf AuthService         # WTF is this class doing here?
        mu wtf src/auth.py:10-50   # WTF happened to these lines?
        mu wtf  # Interactive mode
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.intelligence import WhyAnalyzer
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import print_error

    # Interactive mode
    if not target:
        target = _prompt_for_input("What file or symbol do you want to investigate?", "wtf")

    # Find mubase
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    if not mubase_path:
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(1)

    # mubase_path is .mu/mubase, root is parent's parent
    root_path = mubase_path.parent.parent

    # Try daemon first - use it for node resolution if available
    client = DaemonClient()
    db = None
    resolved_target = target

    if client.is_running():
        try:
            # If target looks like a node name (not a file path), resolve it via daemon
            if not (
                "/" in target
                or "\\" in target
                or target.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java"))
                or ":" in target  # file:line_start-line_end format
            ):
                found = client.find_node(target, cwd=str(cwd))
                if found and found.get("file_path"):
                    # Got node info - construct a target that WhyAnalyzer can use
                    found_file_path = found.get("file_path")
                    line_start = found.get("line_start")
                    line_end = found.get("line_end")
                    if found_file_path and line_start and line_end:
                        resolved_target = f"{found_file_path}:{line_start}-{line_end}"
                    elif found_file_path:
                        resolved_target = found_file_path
        except DaemonError:
            pass  # Fall through to local resolution

    # If we couldn't resolve via daemon, try local db
    if resolved_target == target:
        try:
            db = MUbase(mubase_path, read_only=True)
        except MUbaseLockError:
            # If we can't open db and couldn't resolve via daemon, error out
            if "/" not in target and not target.endswith(
                (".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java")
            ):
                print_error(
                    "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
                )
                sys.exit(ExitCode.CONFIG_ERROR)
            # Otherwise target looks like a file path, continue without db

    try:
        analyzer = WhyAnalyzer(db=db, root_path=root_path)
        result = analyzer.analyze(
            resolved_target,
            max_commits=commits,
            include_cochanges=not no_cochange,
        )

        if as_json:
            click.echo(json.dumps(result.to_dict(), indent=2))
            return

        # Pretty print with personality
        click.echo()
        click.echo(
            click.style("WTF: ", fg="red", bold=True) + click.style(result.target, bold=True)
        )
        click.echo()

        # Origin info
        if result.origin_commit:
            origin = result.origin_commit
            days_ago = _days_since(origin.date) if origin.date else 0
            click.echo(
                click.style("Origin ", fg="yellow")
                + click.style(origin.hash[:7], fg="yellow", bold=True)
            )
            click.echo(
                click.style("  Author: ", dim=True)
                + f"@{origin.author}"
                + click.style(f" ({_format_age(days_ago)})", dim=True)
            )
            click.echo(click.style("  Message: ", dim=True) + f'"{origin.message}"')

        # Origin reason
        if result.origin_reason:
            click.echo()
            click.echo(click.style("Reason: ", dim=True) + result.origin_reason)

        # Evolution info
        if result.total_commits > 0:
            click.echo()
            click.echo(click.style("Evolution", fg="cyan"))
            contributor_count = len(result.contributors)
            click.echo(
                click.style("  ", dim=True)
                + f"{result.total_commits} commits by {contributor_count} contributors"
            )
            if result.evolution_summary:
                click.echo(click.style("  ", dim=True) + result.evolution_summary)

        # Primary author
        if result.primary_author:
            click.echo(click.style("  Owner: ", dim=True) + f"@{result.primary_author}")

        # Co-changes
        if result.frequently_changed_with:
            click.echo()
            click.echo(
                click.style("Co-changes", fg="cyan")
                + click.style(" (files that change together)", dim=True)
            )
            for rf in result.frequently_changed_with[:5]:
                click.echo(click.style("  • ", dim=True) + rf)

        # Issue/PR references
        if result.issue_refs or result.pr_refs:
            click.echo()
            click.echo(click.style("References", fg="cyan"))
            refs = result.issue_refs + [f"PR#{pr}" for pr in result.pr_refs]
            for ref in refs[:5]:
                click.echo(click.style("  • ", dim=True) + ref)

        click.echo()
        click.echo(click.style(f"Analysis time: {result.analysis_time_ms:.1f}ms", dim=True))

    finally:
        if db:
            db.close()


@click.command(name="yolo", short_help="Impact check - what breaks if I change this?")
@click.argument("target", required=False)
@click.option("--depth", "-d", default=2, help="Traversal depth")
@click.option(
    "--type",
    "-t",
    "edge_types",
    multiple=True,
    help="Edge types: imports, calls, inherits, contains",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def yolo(
    ctx: MUContext,
    target: str | None,
    depth: int,
    edge_types: tuple[str, ...],
    as_json: bool,
) -> None:
    """Impact check - what breaks if I change this?

    Shows downstream impact of modifying a file or node.
    Uses BFS traversal to find all dependents.

    \b
    Examples:
        mu yolo src/mu/kernel/mubase.py
        mu yolo MUbase
        mu yolo AuthService -d 3
        mu yolo  # Interactive mode
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import print_error

    # Interactive mode
    if not target:
        target = _prompt_for_input("What file or symbol do you want to check?", "yolo")

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
            # Resolve node to full ID if it's a short name
            resolved_node = target
            if not target.startswith(("mod:", "cls:", "fn:")):
                found = client.find_node(target, cwd=str(cwd))
                if found:
                    resolved_node = found.get("id", target)

            edge_type_list = list(edge_types) if edge_types else None
            result = client.impact(resolved_node, edge_types=edge_type_list, cwd=str(cwd))

            # Handle daemon response format
            impacted = result.get("impacted_nodes", result.get("data", []))
            if isinstance(impacted, dict):
                impacted = []

            if as_json:
                click.echo(
                    json.dumps(
                        {
                            "target": target,
                            "node_id": resolved_node,
                            "impacted_count": len(impacted),
                            "impacted": impacted,
                        },
                        indent=2,
                    )
                )
                return

            click.echo()
            click.echo(
                click.style("YOLO: ", fg="magenta", bold=True) + click.style(target, bold=True)
            )
            click.echo()
            click.echo(click.style(f"{len(impacted)} nodes affected", fg="yellow", bold=True))

            if impacted:
                click.echo()
                click.echo(click.style(f"Impacted nodes ({len(impacted)})", fg="cyan"))
                for node_id in impacted[:15]:
                    click.echo(click.style("  • ", dim=True) + str(node_id))
                if len(impacted) > 15:
                    click.echo(click.style(f"  ... and {len(impacted) - 15} more", dim=True))

            click.echo()
            if len(impacted) > 10:
                click.echo(
                    click.style(
                        f"⚠️  High impact - changes affect {len(impacted)} downstream nodes",
                        fg="yellow",
                    )
                )
            else:
                click.echo(click.style("Low impact. Go ahead, YOLO! 🎲", dim=True))
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
        from mu.commands.utils import resolve_node_for_command
        from mu.kernel.graph import GraphManager

        # Resolve target using NodeResolver (same as mu impact)
        try:
            resolved_node, resolution = resolve_node_for_command(
                db, target, no_interactive=True, quiet=True
            )
        except SystemExit:
            print_error(f"Could not find node: {target}")
            sys.exit(1)

        # Use GraphManager for impact analysis (same as mu impact)
        gm = GraphManager(db.conn)
        gm.load()

        # Check node exists in graph
        if not gm.has_node(resolved_node.id):
            print_error(f"Node not in graph: {resolved_node.id}")
            sys.exit(1)

        # Run impact analysis using petgraph (same as mu impact)
        edge_type_list = list(edge_types) if edge_types else None
        impacted = gm.impact(resolved_node.id, edge_type_list)

        if as_json:
            click.echo(
                json.dumps(
                    {
                        "target": target,
                        "node_id": resolved_node.id,
                        "impacted_count": len(impacted),
                        "impacted": impacted,
                    },
                    indent=2,
                )
            )
            return

        click.echo()
        click.echo(click.style("YOLO: ", fg="magenta", bold=True) + click.style(target, bold=True))
        if resolution.was_ambiguous:
            click.echo(
                click.style("  Resolved to: ", dim=True) + click.style(resolved_node.id, fg="cyan")
            )
        click.echo()
        click.echo(click.style(f"{len(impacted)} nodes affected", fg="yellow", bold=True))

        if impacted:
            click.echo()
            click.echo(click.style(f"Impacted nodes ({len(impacted)})", fg="cyan"))
            for node_id in impacted[:15]:
                click.echo(click.style("  • ", dim=True) + str(node_id))
            if len(impacted) > 15:
                click.echo(click.style(f"  ... and {len(impacted) - 15} more", dim=True))

        click.echo()
        if len(impacted) > 10:
            click.echo(
                click.style(
                    f"⚠️  High impact - changes affect {len(impacted)} downstream nodes",
                    fg="yellow",
                )
            )
        else:
            click.echo(click.style("Low impact. Go ahead, YOLO! 🎲", dim=True))

    finally:
        db.close()


@click.command(name="sus", short_help="Smell check - warnings before touching code")
@click.argument("target", required=False)
@click.option("--strict", is_flag=True, help="Exit with error if any warnings (for CI)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def sus(ctx: MUContext, target: str | None, strict: bool, as_json: bool) -> None:
    """Smell check - warnings before touching scary code.

    Analyzes a file or node to identify potential issues before modification:
    - High impact (many dependents)
    - Stale code (not modified recently)
    - Security sensitive (auth/crypto logic)
    - No tests detected
    - High complexity

    \b
    Examples:
        mu sus src/mu/mcp/server.py
        mu sus MUbase
        mu sus AuthService --strict  # For CI
        mu sus  # Interactive mode
    """
    import json

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.intelligence import ProactiveWarningGenerator, WarningConfig
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import print_error

    # Interactive mode
    if not target:
        target = _prompt_for_input("What file or symbol do you want to check?", "sus")

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
            result = client.warn(target, cwd=str(cwd))

            if as_json:
                click.echo(json.dumps(result, indent=2))
                return

            warnings = result.get("warnings", [])
            risk_score = result.get("risk_score", 0)

            click.echo()
            click.echo(
                click.style("SUS Check: ", fg="yellow", bold=True) + click.style(target, bold=True)
            )
            click.echo()

            if not warnings:
                click.echo(click.style("✓ All clear. Not sus. 👍", fg="green"))
                return

            # Display warnings
            for warning in warnings:
                level = warning.get("level", "warn")
                category = warning.get("category", "unknown")
                message = warning.get("message", "")
                details = warning.get("details", {})

                icon = "⚠️" if level in ("warn", "error") else "ℹ️"
                color = "red" if level == "error" else "yellow"
                click.echo(
                    click.style(f"{icon} ", fg=color)
                    + click.style(category.upper(), fg=color, bold=True)
                )
                click.echo(click.style(f"   {message}", dim=False))
                suggestion = details.get("suggestion") if details else None
                if suggestion:
                    click.echo(click.style(f"   → {suggestion}", fg="green"))
                click.echo()

            # Risk score (daemon returns 0-1, convert to 0-10)
            display_score = risk_score * 10 if risk_score <= 1 else risk_score
            click.echo(
                click.style("Risk Score: ", dim=True)
                + click.style(
                    f"{display_score:.0f}/10",
                    fg="red" if display_score >= 7 else "yellow",
                    bold=True,
                )
                + click.style(
                    " - Proceed with caution" if display_score >= 5 else " - Looks OK", dim=True
                )
            )

            if strict and warnings:
                sys.exit(1)
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
        # mubase_path is .mu/mubase, so root is two levels up
        root_path = mubase_path.parent.parent
        config = WarningConfig()
        generator = ProactiveWarningGenerator(db, config, root_path)
        local_result = generator.analyze(target)

        if as_json:
            click.echo(json.dumps(local_result.to_dict(), indent=2))
            return

        click.echo()
        click.echo(
            click.style("SUS Check: ", fg="yellow", bold=True) + click.style(target, bold=True)
        )
        click.echo()

        if not local_result.warnings:
            click.echo(click.style("✓ All clear. Not sus. 👍", fg="green"))
            return

        # Group warnings by category
        for warning in local_result.warnings:
            icon = "⚠️" if warning.level in ("warn", "error") else "ℹ️"
            color = "red" if warning.level == "error" else "yellow"
            click.echo(
                click.style(f"{icon} ", fg=color)
                + click.style(warning.category.value.upper(), fg=color, bold=True)
            )
            click.echo(click.style(f"   {warning.message}", dim=False))
            # Check for suggestion in details
            suggestion = warning.details.get("suggestion") if warning.details else None
            if suggestion:
                click.echo(click.style(f"   → {suggestion}", fg="green"))
            click.echo()

        # Risk score
        click.echo(
            click.style("Risk Score: ", dim=True)
            + click.style(
                f"{local_result.risk_score}/10",
                fg="red" if local_result.risk_score >= 7 else "yellow",
                bold=True,
            )
            + click.style(
                " - Proceed with caution" if local_result.risk_score >= 5 else " - Looks OK",
                dim=True,
            )
        )

        if strict and local_result.warnings:
            sys.exit(1)

    finally:
        db.close()


@click.command(name="vibe", short_help="Pattern check - does this code fit?")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--staged", "-s", is_flag=True, help="Check staged git changes only")
@click.option(
    "--category", "-c", help="Category filter: naming, testing, api, imports, architecture"
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def vibe(
    ctx: MUContext,
    path: Path | None,
    staged: bool,
    category: str | None,
    as_json: bool,
) -> None:
    """Pattern check - does this code fit the codebase conventions?

    Checks if your code matches established codebase patterns.
    Returns exit code 1 if issues found (useful for CI).

    \b
    Categories:
        naming        - Naming conventions
        architecture  - Architectural patterns
        testing       - Test patterns
        imports       - Import organization
        api           - API patterns
        async         - Async patterns

    \b
    Examples:
        mu vibe                       # Check all uncommitted changes
        mu vibe --staged              # Check staged changes
        mu vibe src/new_feature.py    # Check specific file
        mu vibe -c naming             # Only check naming
    """
    import json
    import subprocess

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.intelligence import PatternCategory, PatternDetector
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import print_error, print_success

    # Find mubase
    cwd = Path.cwd()
    mubase_path = find_mubase_path(cwd)

    if not mubase_path:
        print_error("No .mu/mubase found. Run 'mu bootstrap' first.")
        sys.exit(1)

    # mubase_path is .mu/mubase, root is parent's parent
    root_path = mubase_path.parent.parent

    # Try daemon first (no lock)
    client = DaemonClient()
    db = None
    patterns_from_daemon = None

    if client.is_running():
        try:
            daemon_result = client.patterns(category=category, cwd=str(cwd))
            patterns_from_daemon = daemon_result.get("patterns", [])
        except DaemonError:
            pass  # Fall through to local mode

    # Only open db if we need it (daemon not available)
    if patterns_from_daemon is None:
        try:
            db = MUbase(mubase_path, read_only=True)
        except MUbaseLockError:
            print_error(
                "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
            )
            sys.exit(ExitCode.CONFIG_ERROR)

    try:
        # Determine files to check
        files_to_check: list[str] = []

        if path and path.is_file():
            files_to_check = [str(path.resolve())]
        elif staged:
            try:
                result = subprocess.run(
                    ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                    capture_output=True,
                    text=True,
                    cwd=str(root_path),
                )
                if result.returncode == 0:
                    files_to_check = [
                        str(root_path / f.strip())
                        for f in result.stdout.strip().split("\n")
                        if f.strip()
                    ]
            except Exception:
                print_error("Failed to get staged files from git")
                sys.exit(1)
        else:
            # All uncommitted changes
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=ACMR"],
                    capture_output=True,
                    text=True,
                    cwd=str(root_path),
                )
                if result.returncode == 0:
                    files_to_check = [
                        str(root_path / f.strip())
                        for f in result.stdout.strip().split("\n")
                        if f.strip()
                    ]
                # Also include staged
                result = subprocess.run(
                    ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                    capture_output=True,
                    text=True,
                    cwd=str(root_path),
                )
                if result.returncode == 0:
                    staged_files = [
                        str(root_path / f.strip())
                        for f in result.stdout.strip().split("\n")
                        if f.strip()
                    ]
                    files_to_check = list(set(files_to_check + staged_files))
            except Exception:
                if path:
                    files_to_check = [str(path.resolve())]

        if not files_to_check:
            if as_json:
                click.echo(json.dumps({"issues": [], "message": "No files to check"}))
            else:
                print_success("All good. The vibe is immaculate. ✨")
            return

        # Get patterns (use daemon results if available, otherwise detect locally)
        if patterns_from_daemon is not None:
            patterns_list = patterns_from_daemon
        else:
            assert db is not None, "db should be available if daemon patterns not available"
            detector = PatternDetector(db)
            category_enum = None
            if category:
                try:
                    category_enum = PatternCategory(category)
                except ValueError:
                    print_error(f"Unknown category: {category}")
                    sys.exit(1)

            patterns_result = detector.detect(category=category_enum)
            patterns_list = [
                {
                    "name": p.name,
                    "category": p.category.value,
                    "description": p.description,
                    "frequency": p.frequency,
                    "confidence": p.confidence,
                }
                for p in patterns_result.patterns
            ]

        # Simple pattern matching for files
        issues: list[dict[str, str]] = []

        for file_path in files_to_check:
            rel_path = (
                Path(file_path).relative_to(root_path)
                if Path(file_path).is_relative_to(root_path)
                else Path(file_path)
            )

            # Check naming conventions
            if not category or category == "naming":
                # Check file naming patterns
                for pattern in patterns_list:
                    pattern_category = (
                        pattern.get("category", "")
                        if isinstance(pattern, dict)
                        else pattern.category.value
                    )
                    pattern_name = (
                        pattern.get("name", "") if isinstance(pattern, dict) else pattern.name
                    )
                    if pattern_category == "naming":
                        # Simple check: if pattern mentions test files, check test file naming
                        if "test" in pattern_name.lower() and "test" in str(rel_path).lower():
                            # Check if follows test naming pattern
                            if (
                                not str(rel_path).startswith("tests/")
                                and "_test" not in str(rel_path)
                                and "test_" not in str(rel_path)
                            ):
                                issues.append(
                                    {
                                        "file": str(rel_path),
                                        "category": "naming",
                                        "message": "Test file not in tests/ directory",
                                        "suggestion": f"Move to tests/ following pattern: {pattern_name}",
                                    }
                                )

            # Check if test file exists for new code files
            if not category or category == "testing":
                if (
                    str(rel_path).endswith(".py")
                    and "test" not in str(rel_path).lower()
                    and not str(rel_path).startswith("tests/")
                ):
                    # Check if corresponding test exists
                    test_path = root_path / "tests" / "unit" / f"test_{rel_path.name}"
                    if not test_path.exists():
                        issues.append(
                            {
                                "file": str(rel_path),
                                "category": "testing",
                                "message": "No test file found",
                                "suggestion": f"Create {test_path.relative_to(root_path)}",
                            }
                        )

        if as_json:
            click.echo(
                json.dumps(
                    {
                        "files_checked": len(files_to_check),
                        "issues": issues,
                        "patterns_detected": len(patterns_list),
                    },
                    indent=2,
                )
            )
            return

        if not issues:
            print_success("All good. The vibe is immaculate. ✨")
            return

        # Output with personality
        click.echo()
        click.echo(
            click.style("Vibe Check: ", fg="magenta", bold=True) + f"{len(issues)} issues found"
        )
        click.echo()

        for issue in issues:
            click.echo(
                click.style("✗ ", fg="red")
                + click.style(f"[{issue['category']}] ", fg="cyan")
                + issue["message"]
            )
            click.echo(click.style(f"  {issue['file']}", dim=True))
            if issue.get("suggestion"):
                click.echo(click.style(f"  → {issue['suggestion']}", fg="green"))
            click.echo()

        click.echo(click.style("The vibe is... off. 😬", dim=True))
        sys.exit(1)

    finally:
        if db:
            db.close()


@click.command(name="zen", short_help="Clean up - clear caches")
@click.option(
    "--yes", "-y", "--force", "-f", is_flag=True, help="Actually perform cleanup (default: dry-run)"
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def zen(ctx: MUContext, yes: bool, as_json: bool) -> None:
    """Clean up - clear caches and achieve zen.

    Shows what would be cleaned (dry-run by default).
    Use --yes to actually remove cached data, orphan entries, and temp files.

    \b
    Examples:
        mu zen           # Show what would be cleaned (dry-run)
        mu zen --yes     # Actually clean
        mu zen -y        # Short form
        mu zen --json    # Output stats as JSON
    """
    import json
    import shutil

    from mu.cache import CacheManager
    from mu.config import MUConfig

    cwd = Path.cwd()
    mu_dir = cwd / ".mu"

    # Load config
    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    stats = {
        "cache_entries_removed": 0,
        "bytes_freed": 0,
        "temp_files_removed": 0,
    }

    # Calculate what would be cleaned
    cache_dir = mu_dir / "cache"
    cache_size = 0
    cache_files = 0
    if cache_dir.exists():
        cache_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
        cache_files = len(list(cache_dir.rglob("*")))

    temp_files_to_clean: list[Path] = []
    temp_patterns = ["*.tmp", "*.temp", ".mu-*.tmp"]
    for pattern in temp_patterns:
        temp_files_to_clean.extend(cwd.glob(pattern))

    temp_size = sum(f.stat().st_size for f in temp_files_to_clean if f.exists())

    total_items = cache_files + len(temp_files_to_clean)

    # Dry-run mode (default): just show what would be cleaned
    if not yes and not as_json:
        click.echo()
        click.echo(click.style("Would clean:", bold=True))
        click.echo()
        if cache_files > 0:
            mb = cache_size / 1_000_000
            click.echo(f"  • {cache_files:,} cached entries ({mb:.1f}MB)")
        else:
            click.echo(click.style("  • No cached entries", dim=True))
        if temp_files_to_clean:
            mb = temp_size / 1_000_000
            click.echo(f"  • {len(temp_files_to_clean):,} temp files ({mb:.1f}MB)")
        else:
            click.echo(click.style("  • No temp files", dim=True))
        click.echo()
        if total_items > 0:
            click.echo(click.style("Run with --yes to clean", dim=True))
        else:
            click.echo(click.style("Nothing to clean. Zen achieved. 🧘", dim=True))
        return

    # Actually perform cleanup (--yes mode)
    if cache_dir.exists() and cache_files > 0:
        try:
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            stats["cache_entries_removed"] = cache_files
            stats["bytes_freed"] += cache_size
        except Exception:
            pass

    for temp_file in temp_files_to_clean:
        try:
            size = temp_file.stat().st_size
            temp_file.unlink()
            stats["temp_files_removed"] += 1
            stats["bytes_freed"] += size
        except Exception:
            pass

    # Also use CacheManager
    try:
        cache_manager = CacheManager(config.cache, cwd)
        cache_manager.clear()
        cache_manager.close()
    except Exception:
        pass

    if as_json:
        click.echo(json.dumps(stats, indent=2))
        return

    # Output with personality
    click.echo()
    click.echo(click.style("Cleaning...", bold=True))
    click.echo()

    if stats["cache_entries_removed"] > 0:
        click.echo(
            click.style("✓ ", fg="green")
            + f"Removed {stats['cache_entries_removed']:,} cached entries"
        )

    if stats["temp_files_removed"] > 0:
        click.echo(
            click.style("✓ ", fg="green") + f"Removed {stats['temp_files_removed']:,} temp files"
        )

    mb_freed = stats["bytes_freed"] / 1_000_000
    if mb_freed > 0.01:
        click.echo(click.style("✓ ", fg="green") + f"Freed {mb_freed:.1f}MB")

    if stats["cache_entries_removed"] == 0 and stats["temp_files_removed"] == 0:
        click.echo(click.style("✓ ", fg="green") + "Already clean")

    click.echo()
    click.echo(click.style("Zen achieved. 🧘", dim=True))


def _format_age(days: int) -> str:
    """Format age in days to human-readable string."""
    if days == 0:
        return "today"
    elif days == 1:
        return "yesterday"
    elif days < 7:
        return f"{days} days ago"
    elif days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    elif days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    else:
        years = days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"


def _days_since(dt: datetime | None) -> int:
    """Calculate days since a datetime."""
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    return (now - dt).days


__all__ = ["omg", "grok", "wtf", "yolo", "sus", "vibe", "zen"]
