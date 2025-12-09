"""CLI commands for pattern detection."""

from __future__ import annotations

import json
from pathlib import Path

import click

from mu.logging import print_error, print_info, print_success, print_warning
from mu.paths import get_mubase_path


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
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum patterns to show (default: 20)",
)
def patterns(
    path: str,
    category: str | None,
    refresh: bool,
    examples: bool,
    output_json: bool,
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
        mu patterns --json             # JSON output
    """
    import sys

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.intelligence import PatternCategory, PatternDetector
    from mu.kernel import MUbase, MUbaseLockError

    root_path = Path(path).resolve()
    mubase_path = get_mubase_path(root_path)

    if not mubase_path.exists():
        print_error(f"No .mu/mubase found at {mubase_path}")
        print_info("Run 'mu bootstrap' or 'mu kernel build .' first")
        raise SystemExit(1)

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

            if output_json:
                output = {
                    "patterns": patterns_list,
                    "total": len(patterns_list),
                    "from_cache": from_cache,
                }
                click.echo(json.dumps(output, indent=2))
                return

            # Display results
            if not patterns_list:
                print_warning("No patterns detected")
                if category:
                    print_info("Try without --category to see all patterns")
                return

            source = "(cached)" if from_cache else "(fresh analysis)"
            print_success(f"Found {len(patterns_list)} patterns {source}\n")

            for pattern in patterns_list:
                # Handle both dict (from daemon) and object formats
                cat_value = pattern.get("category", "unknown") if isinstance(pattern, dict) else pattern.category.value
                name = pattern.get("name", "") if isinstance(pattern, dict) else pattern.name
                description = pattern.get("description", "") if isinstance(pattern, dict) else pattern.description
                frequency = pattern.get("frequency", 0) if isinstance(pattern, dict) else pattern.frequency
                confidence = pattern.get("confidence", 0) if isinstance(pattern, dict) else pattern.confidence
                anti_patterns = pattern.get("anti_patterns", []) if isinstance(pattern, dict) else pattern.anti_patterns
                pattern_examples = pattern.get("examples", []) if isinstance(pattern, dict) else pattern.examples

                # Header with category badge
                cat_badge = f"[{cat_value}]"
                click.echo(click.style(f"  {cat_badge}", fg="cyan") + f" {name}")

                # Description and stats
                click.echo(f"      {description}")
                click.echo(
                    click.style("      Frequency: ", dim=True)
                    + f"{frequency}"
                    + click.style("  Confidence: ", dim=True)
                    + f"{confidence:.0%}"
                )

                # Anti-patterns
                if anti_patterns:
                    click.echo(click.style("      Avoid: ", fg="yellow") + anti_patterns[0])

                # Examples (if requested)
                if examples and pattern_examples:
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
                            click.echo(click.style(f"          {first_line}", dim=True))

                click.echo()

            # Summary by category
            categories: dict[str, int] = {}
            for p in patterns_list:
                cat = p.get("category", "unknown") if isinstance(p, dict) else p.category.value
                categories[cat] = categories.get(cat, 0) + 1

            if len(categories) > 1:
                summary = ", ".join(f"{cat}: {count}" for cat, count in sorted(categories.items()))
                click.echo(click.style(f"Summary: {summary}", dim=True))

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

        if output_json:
            output = {
                "patterns": [p.to_dict() for p in result_patterns],
                "total": len(result_patterns),
                "from_cache": from_cache,
            }
            click.echo(json.dumps(output, indent=2))
            return

        # Display results
        if not result_patterns:
            print_warning("No patterns detected")
            if category:
                print_info("Try without --category to see all patterns")
            return

        source = "(cached)" if from_cache else "(fresh analysis)"
        print_success(f"Found {len(result_patterns)} patterns {source}\n")

        for pattern in result_patterns:
            # Header with category badge
            cat_badge = f"[{pattern.category.value}]"
            click.echo(click.style(f"  {cat_badge}", fg="cyan") + f" {pattern.name}")

            # Description and stats
            click.echo(f"      {pattern.description}")
            click.echo(
                click.style("      Frequency: ", dim=True)
                + f"{pattern.frequency}"
                + click.style("  Confidence: ", dim=True)
                + f"{pattern.confidence:.0%}"
            )

            # Anti-patterns
            if pattern.anti_patterns:
                click.echo(click.style("      Avoid: ", fg="yellow") + pattern.anti_patterns[0])

            # Examples (if requested)
            if examples and pattern.examples:
                click.echo(click.style("      Examples:", dim=True))
                for ex in pattern.examples[:2]:
                    loc = f"{ex.file_path}:{ex.line_start}"
                    click.echo(f"        - {loc}")
                    if ex.code_snippet:
                        # Show first line of snippet
                        first_line = ex.code_snippet.split("\n")[0]
                        if len(first_line) > 60:
                            first_line = first_line[:57] + "..."
                        click.echo(click.style(f"          {first_line}", dim=True))

            click.echo()

        # Summary by category
        local_categories: dict[str, int] = {}
        for p in result_patterns:
            cat = p.category.value
            local_categories[cat] = local_categories.get(cat, 0) + 1

        if len(local_categories) > 1:
            summary = ", ".join(f"{cat}: {count}" for cat, count in sorted(local_categories.items()))
            click.echo(click.style(f"Summary: {summary}", dim=True))

    finally:
        db.close()


__all__ = ["patterns"]
