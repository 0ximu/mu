"""CLI commands for pattern detection."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from mu.logging import print_error, print_info, print_success, print_warning
from mu.paths import find_mubase_path, get_mubase_path

if TYPE_CHECKING:
    from mu.output import OutputConfig


def _get_output_config(
    ctx: click.Context | None,
    output_format: str,
    no_color: bool,
    no_truncate: bool = False,
) -> OutputConfig:
    """Build OutputConfig from command options and context."""
    from mu.commands.utils import is_interactive
    from mu.output import OutputConfig

    # Check if global options should override command options
    obj = getattr(ctx, "obj", None) if ctx else None

    # Global format overrides command format
    fmt = output_format
    if obj and obj.output_format:
        fmt = obj.output_format

    # TTY auto-detection
    is_tty = is_interactive()

    # Combine flags: command flags OR global flags OR auto-detection
    final_no_truncate = no_truncate or (obj and obj.no_truncate) or not is_tty
    final_no_color = no_color or (obj and obj.no_color) or not is_tty
    width = (obj.width if obj else None) or None

    return OutputConfig(
        format=fmt,
        no_truncate=final_no_truncate,
        no_color=final_no_color,
        width=width,
    )


@click.command("patterns")
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option(
    "-c",
    "--category",
    type=click.Choice(
        [
            "error_handling",
            "state_management",
            "api",
            "naming",
            "testing",
            "components",
            "imports",
            "architecture",
            "async",
            "logging",
        ],
        case_sensitive=False,
    ),
    help="Filter by pattern category",
)
@click.option(
    "--refresh",
    is_flag=True,
    help="Force re-analysis (bypass cache)",
)
@click.option(
    "--examples",
    is_flag=True,
    help="Show code examples for each pattern",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON (deprecated, use --format json)",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--no-truncate", is_flag=True, help="Show full values without truncation")
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum patterns to show (default: 20)",
)
@click.pass_context
def patterns(
    ctx: click.Context,
    path: str,
    category: str | None,
    refresh: bool,
    examples: bool,
    output_format: str,
    output_json: bool,
    no_color: bool,
    no_truncate: bool,
    limit: int,
) -> None:
    """Detect and display codebase patterns.

    Analyzes the codebase to identify recurring patterns including:
    naming conventions, error handling, import organization,
    architectural patterns, and testing practices.

    Examples:

        mu patterns                    # Analyze current directory
        mu patterns src/ --category naming  # Only naming patterns
        mu patterns --refresh          # Force re-analysis
        mu patterns --examples         # Show code examples
        mu patterns --format json      # JSON output
        mu patterns --format csv       # CSV output
    """
    import sys

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.extras.intelligence import PatternCategory, PatternDetector
    from mu.kernel import MUbase, MUbaseLockError
    from mu.output import Column, format_output

    root_path = Path(path).resolve()

    # First try to find mubase by walking up directories (workspace-aware)
    mubase_path = find_mubase_path(root_path)
    if not mubase_path:
        # Fallback to direct path construction for better error message
        mubase_path = get_mubase_path(root_path)
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu bootstrap' first")
        raise SystemExit(1)

    # Derive root_path from mubase_path (.mu/mubase -> parent.parent)
    root_path = mubase_path.parent.parent

    # Handle deprecated --json flag
    effective_format = output_format
    if output_json:
        effective_format = "json"

    # Build output config
    config = _get_output_config(ctx, effective_format, no_color, no_truncate)

    # Try daemon first (no lock)
    client = DaemonClient()
    if client.is_running():
        try:
            daemon_result = client.patterns(
                category=category,
                refresh=refresh,
                cwd=str(root_path),
            )

            patterns_list = daemon_result.get("patterns", [])
            from_cache = not refresh  # Assume cached unless refresh requested

            # Limit results
            patterns_list = patterns_list[:limit]

            # Use unified output for JSON/CSV formats
            if config.format in ("json", "csv"):
                data = _patterns_to_data(patterns_list)
                columns = [
                    Column("Category", "category"),
                    Column("Name", "name"),
                    Column("Description", "description"),
                    Column("Frequency", "frequency"),
                    Column("Confidence", "confidence"),
                ]
                output = format_output(data, columns, config, title="Codebase Patterns")
                click.echo(output)
                return

            # Rich display for table format
            _display_patterns_rich(patterns_list, from_cache, category, examples, config.no_color)
            return
        except DaemonError:
            pass  # Fall through to local mode

    # Local mode (daemon unavailable)
    # We need write access to save patterns, so don't use read_only mode
    try:
        db = MUbase(mubase_path, read_only=False)
    except MUbaseLockError:
        print_error(
            "Database is locked. Daemon should auto-route queries. Try: mu serve --stop && mu serve"
        )
        sys.exit(ExitCode.CONFIG_ERROR)
    try:
        # Convert category string to enum if provided
        cat_enum = None
        if category:
            cat_enum = PatternCategory(category)

        # Check for cached patterns unless refresh requested
        if not refresh and db.has_patterns():
            stored = db.get_patterns(category)
            if stored:
                result_patterns = stored
                from_cache = True
            else:
                detector = PatternDetector(db)
                result = detector.detect(category=cat_enum)
                result_patterns = result.patterns
                from_cache = False
                if not category:
                    db.save_patterns(result_patterns)
        else:
            detector = PatternDetector(db)
            result = detector.detect(category=cat_enum, refresh=refresh)
            result_patterns = result.patterns
            from_cache = False
            if not category:
                db.save_patterns(result_patterns)

        # Limit results
        result_patterns = result_patterns[:limit]

        # Use unified output for JSON/CSV formats
        if config.format in ("json", "csv"):
            data = _patterns_to_data([p.to_dict() for p in result_patterns])
            columns = [
                Column("Category", "category"),
                Column("Name", "name"),
                Column("Description", "description"),
                Column("Frequency", "frequency"),
                Column("Confidence", "confidence"),
            ]
            output = format_output(data, columns, config, title="Codebase Patterns")
            click.echo(output)
            return

        # Rich display for table format
        patterns_as_dicts = [p.to_dict() for p in result_patterns]
        _display_patterns_rich(patterns_as_dicts, from_cache, category, examples, config.no_color)

    finally:
        db.close()


def _patterns_to_data(patterns_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert patterns list to standard data format."""
    data = []
    for p in patterns_list:
        if isinstance(p, dict):
            data.append(
                {
                    "category": p.get("category", "unknown"),
                    "name": p.get("name", ""),
                    "description": p.get("description", ""),
                    "frequency": p.get("frequency", 0),
                    "confidence": f"{p.get('confidence', 0):.0%}",
                }
            )
        else:
            data.append(
                {
                    "category": p.category.value if hasattr(p, "category") else "unknown",
                    "name": p.name if hasattr(p, "name") else "",
                    "description": p.description if hasattr(p, "description") else "",
                    "frequency": p.frequency if hasattr(p, "frequency") else 0,
                    "confidence": f"{p.confidence:.0%}" if hasattr(p, "confidence") else "0%",
                }
            )
    return data


def _display_patterns_rich(
    patterns_list: list[dict[str, Any]],
    from_cache: bool,
    category: str | None,
    examples: bool,
    no_color: bool,
) -> None:
    """Display patterns with rich formatting."""
    if not patterns_list:
        print_warning("No patterns detected")
        if category:
            print_info("Try without --category to see all patterns")
        return

    source = "(cached)" if from_cache else "(fresh analysis)"
    print_success(f"Found {len(patterns_list)} patterns {source}\n")

    for pattern in patterns_list:
        # Handle both dict and object formats
        cat_value = (
            pattern.get("category", "unknown")
            if isinstance(pattern, dict)
            else pattern.category.value
        )
        name = pattern.get("name", "") if isinstance(pattern, dict) else pattern.name
        description = (
            pattern.get("description", "") if isinstance(pattern, dict) else pattern.description
        )
        frequency = pattern.get("frequency", 0) if isinstance(pattern, dict) else pattern.frequency
        confidence = (
            pattern.get("confidence", 0) if isinstance(pattern, dict) else pattern.confidence
        )
        anti_patterns = (
            pattern.get("anti_patterns", []) if isinstance(pattern, dict) else pattern.anti_patterns
        )
        pattern_examples = (
            pattern.get("examples", []) if isinstance(pattern, dict) else pattern.examples
        )

        # Header with category badge
        cat_badge = f"[{cat_value}]"
        if no_color:
            click.echo(f"  {cat_badge} {name}")
        else:
            click.echo(click.style(f"  {cat_badge}", fg="cyan") + f" {name}")

        # Description and stats
        click.echo(f"      {description}")
        if no_color:
            click.echo(f"      Frequency: {frequency}  Confidence: {confidence:.0%}")
        else:
            click.echo(
                click.style("      Frequency: ", dim=True)
                + f"{frequency}"
                + click.style("  Confidence: ", dim=True)
                + f"{confidence:.0%}"
            )

        # Anti-patterns
        if anti_patterns:
            if no_color:
                click.echo(f"      Avoid: {anti_patterns[0]}")
            else:
                click.echo(click.style("      Avoid: ", fg="yellow") + anti_patterns[0])

        # Examples (if requested)
        if examples and pattern_examples:
            if no_color:
                click.echo("      Examples:")
            else:
                click.echo(click.style("      Examples:", dim=True))
            for ex in pattern_examples[:2]:
                if isinstance(ex, dict):
                    loc = f"{ex.get('file_path', '')}:{ex.get('line_start', '')}"
                    code_snippet = ex.get("code_snippet", "")
                else:
                    loc = f"{ex.file_path}:{ex.line_start}"
                    code_snippet = ex.code_snippet
                click.echo(f"        - {loc}")
                if code_snippet:
                    first_line = code_snippet.split("\n")[0]
                    if len(first_line) > 60:
                        first_line = first_line[:57] + "..."
                    if no_color:
                        click.echo(f"          {first_line}")
                    else:
                        click.echo(click.style(f"          {first_line}", dim=True))

        click.echo()

    # Summary by category
    categories: dict[str, int] = {}
    for p in patterns_list:
        cat = p.get("category", "unknown") if isinstance(p, dict) else p.category.value
        categories[cat] = categories.get(cat, 0) + 1

    if len(categories) > 1:
        summary = ", ".join(f"{cat}: {count}" for cat, count in sorted(categories.items()))
        if no_color:
            click.echo(f"Summary: {summary}")
        else:
            click.echo(click.style(f"Summary: {summary}", dim=True))


__all__ = ["patterns"]
