"""MU vibe command - Pattern validation for codebase conventions.

This command checks if code matches established codebase patterns,
useful for ensuring consistency and can be used in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mu.paths import find_mubase_path

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command(name="vibe", short_help="Pattern check - does this code fit?")
@click.argument("path", type=click.Path(exists=True, path_type=Path), required=False)
@click.option("--staged", "-s", is_flag=True, help="Check staged git changes only")
@click.option(
    "--category", "-c", help="Category filter: naming, testing, api, imports, architecture"
)
@click.option("--strict", is_flag=True, help="Exit with error if any issues (for CI)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def vibe(
    ctx: MUContext,
    path: Path | None,
    staged: bool,
    category: str | None,
    strict: bool,
    as_json: bool,
) -> None:
    """Pattern check - does this code fit the codebase conventions?

    Checks if your code matches established codebase patterns.
    Use --strict to exit with code 1 if issues found (for CI).

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
        mu vibe --strict              # For CI - exit 1 on issues
    """
    import json
    import subprocess

    from mu.client import DaemonClient, DaemonError
    from mu.errors import ExitCode
    from mu.extras.intelligence import PatternCategory, PatternDetector
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
                print_success("All good. The vibe is immaculate.")
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
            print_success("All good. The vibe is immaculate.")
            return

        # Output with personality
        click.echo()
        click.echo(
            click.style("Vibe Check: ", fg="magenta", bold=True) + f"{len(issues)} issues found"
        )
        click.echo()

        for issue in issues:
            click.echo(
                click.style("X ", fg="red")
                + click.style(f"[{issue['category']}] ", fg="cyan")
                + issue["message"]
            )
            click.echo(click.style(f"  {issue['file']}", dim=True))
            if issue.get("suggestion"):
                click.echo(click.style(f"  -> {issue['suggestion']}", fg="green"))
            click.echo()

        click.echo(click.style("The vibe is... off.", dim=True))

        # Only exit with error code in strict mode (for CI)
        if strict:
            sys.exit(1)

    finally:
        if db:
            db.close()


__all__ = ["vibe"]
