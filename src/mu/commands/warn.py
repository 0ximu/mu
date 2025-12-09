"""CLI command for proactive warnings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from mu.logging import print_error, print_info, print_success
from mu.paths import get_mubase_path


@click.command("warn")
@click.argument("target")
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
def warn(target: str, output_json: bool) -> None:
    """Get proactive warnings about a target before modification.

    Analyzes a file or code node to identify potential issues that should
    be considered before making changes.

    Warning categories:

    \b
      - high_impact:  Many files depend on this (>10 dependents)
      - stale:        Not modified in >6 months
      - security:     Contains auth/crypto/secrets logic
      - no_tests:     No test coverage detected
      - complexity:   Cyclomatic complexity >20
      - deprecated:   Marked as deprecated in code

    Examples:

    \b
        mu warn src/auth.py          # Check a file
        mu warn AuthService          # Check a class by name
        mu warn mod:src/payments.py  # Check by node ID
        mu warn src/api/ --json      # JSON output
    """
    import sys

    from mu.errors import ExitCode
    from mu.intelligence.warnings import ProactiveWarningGenerator
    from mu.kernel import MUbase, MUbaseLockError

    # Find .mu/mubase
    root_path = Path.cwd()
    mubase_path = get_mubase_path(root_path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu bootstrap' first")
        raise SystemExit(1)

    try:
        db = MUbase(mubase_path, read_only=True)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)
    try:
        generator = ProactiveWarningGenerator(db, root_path=root_path)
        result = generator.analyze(target)

        if output_json:
            click.echo(json.dumps(result.to_dict(), indent=2))
            return

        # Display results
        if not result.warnings:
            print_success(f"No warnings for {target}")
            click.echo(click.style(f"  Risk score: {result.risk_score:.0%}", dim=True))
            return

        # Header
        click.echo()
        click.echo(
            click.style("  Target: ", dim=True)
            + click.style(result.target, bold=True)
            + click.style(f" ({result.target_type})", dim=True)
        )
        click.echo(click.style("  Risk score: ", dim=True) + _risk_color(result.risk_score))
        click.echo()

        # Display each warning
        for w in result.warnings:
            # Level icon and color
            level_config = {
                "error": ("!", "red"),
                "warn": ("~", "yellow"),
                "info": ("i", "blue"),
            }
            icon, color = level_config.get(w.level, ("?", "white"))

            # Category badge
            cat_badge = f"[{w.category.value}]"

            click.echo(
                click.style(f"  {icon} ", fg=color, bold=True)
                + click.style(cat_badge, fg="cyan")
                + f" {w.message}"
            )

            # Show relevant details
            if w.details:
                details_to_show = _format_details(w.details)
                if details_to_show:
                    click.echo(click.style(f"      {details_to_show}", dim=True))

        click.echo()

        # Summary
        click.echo(click.style(f"  Summary: {result.summary}", dim=True))
        click.echo(click.style(f"  Analysis time: {result.analysis_time_ms:.1f}ms", dim=True))

    finally:
        db.close()


def _risk_color(score: float) -> str:
    """Format risk score with color."""
    if score >= 0.7:
        return click.style(f"{score:.0%} (HIGH)", fg="red", bold=True)
    elif score >= 0.4:
        return click.style(f"{score:.0%} (MEDIUM)", fg="yellow")
    else:
        return click.style(f"{score:.0%} (LOW)", fg="green")


def _format_details(details: dict[str, Any]) -> str:
    """Format warning details for display."""
    parts = []

    # Pick interesting details to show
    if "dependent_count" in details:
        parts.append(f"{details['dependent_count']} dependents")
    if "days_since_modified" in details:
        parts.append(f"{details['days_since_modified']} days old")
    if "complexity" in details:
        parts.append(f"complexity: {details['complexity']}")
    if "indicators" in details:
        indicators = details["indicators"]
        if isinstance(indicators, list) and indicators:
            parts.append(f"{indicators[0]}")
    if "checked_patterns" in details:
        patterns = details["checked_patterns"]
        if isinstance(patterns, list) and patterns:
            parts.append(f"tried: {Path(patterns[0]).name}")

    return ", ".join(parts[:3])  # Max 3 details


__all__ = ["warn"]
