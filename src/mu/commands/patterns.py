"""CLI commands for pattern detection."""

from __future__ import annotations

import json
from pathlib import Path

import click

from mu.logging import print_error, print_info, print_success, print_warning


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
    from mu.intelligence import PatternCategory, PatternDetector
    from mu.kernel import MUbase

    root_path = Path(path).resolve()
    mubase_path = root_path / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu bootstrap' or 'mu kernel build .' first")
        raise SystemExit(1)

    db = MUbase(mubase_path)
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
        categories: dict[str, int] = {}
        for p in result_patterns:
            cat = p.category.value
            categories[cat] = categories.get(cat, 0) + 1

        if len(categories) > 1:
            summary = ", ".join(f"{cat}: {count}" for cat, count in sorted(categories.items()))
            click.echo(click.style(f"Summary: {summary}", dim=True))

    finally:
        db.close()


__all__ = ["patterns"]
