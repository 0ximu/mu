"""MU wtf command - Git archaeology to understand why code exists.

This command analyzes git history to understand the origin and evolution
of code, including who introduced it, commit context, and co-change patterns.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import find_mubase_path

from ._utils import days_since, format_age, prompt_for_input

if TYPE_CHECKING:
    from mu.cli import MUContext


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
    from mu.extras.intelligence import WhyAnalyzer
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import print_error

    # Interactive mode
    if not target:
        target = prompt_for_input("What file or symbol do you want to investigate?", "wtf")

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
            days_ago = days_since(origin.date) if origin.date else 0
            click.echo(
                click.style("Origin ", fg="yellow")
                + click.style(origin.hash[:7], fg="yellow", bold=True)
            )
            click.echo(
                click.style("  Author: ", dim=True)
                + f"@{origin.author}"
                + click.style(f" ({format_age(days_ago)})", dim=True)
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
                click.echo(click.style("  * ", dim=True) + rf)

        # Issue/PR references
        if result.issue_refs or result.pr_refs:
            click.echo()
            click.echo(click.style("References", fg="cyan"))
            refs = result.issue_refs + [f"PR#{pr}" for pr in result.pr_refs]
            for ref in refs[:5]:
                click.echo(click.style("  * ", dim=True) + ref)

        click.echo()
        click.echo(click.style(f"Analysis time: {result.analysis_time_ms:.1f}ms", dim=True))

    finally:
        if db:
            db.close()


__all__ = ["wtf"]
