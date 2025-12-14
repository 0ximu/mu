"""MU sus command - Smell check for warnings before touching code.

This command analyzes a file or node to identify potential issues
before modification, including high impact, staleness, security concerns, etc.
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
    from mu.extras.intelligence import ProactiveWarningGenerator, WarningConfig
    from mu.kernel import MUbase, MUbaseLockError
    from mu.logging import print_error

    # Interactive mode
    if not target:
        target = prompt_for_input("What file or symbol do you want to check?", "sus")

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
                click.echo(click.style("[OK] All clear. Not sus.", fg="green"))
                return

            # Display warnings
            for warning in warnings:
                level = warning.get("level", "warn")
                category = warning.get("category", "unknown")
                message = warning.get("message", "")
                details = warning.get("details", {})

                icon = "!!" if level in ("warn", "error") else "i"
                color = "red" if level == "error" else "yellow"
                click.echo(
                    click.style(f"{icon} ", fg=color)
                    + click.style(category.upper(), fg=color, bold=True)
                )
                click.echo(click.style(f"   {message}", dim=False))
                suggestion = details.get("suggestion") if details else None
                if suggestion:
                    click.echo(click.style(f"   -> {suggestion}", fg="green"))
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
            click.echo(click.style("[OK] All clear. Not sus.", fg="green"))
            return

        # Group warnings by category
        for warning in local_result.warnings:
            icon = "!!" if warning.level in ("warn", "error") else "i"
            color = "red" if warning.level == "error" else "yellow"
            click.echo(
                click.style(f"{icon} ", fg=color)
                + click.style(warning.category.value.upper(), fg=color, bold=True)
            )
            click.echo(click.style(f"   {warning.message}", dim=False))
            # Check for suggestion in details
            suggestion = warning.details.get("suggestion") if warning.details else None
            if suggestion:
                click.echo(click.style(f"   -> {suggestion}", fg="green"))
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


__all__ = ["sus"]
