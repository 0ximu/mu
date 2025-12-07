"""MU diff command - Show semantic differences between git refs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command()
@click.argument("base_ref")
@click.argument("target_ref")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file (default: stdout)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["terminal", "json", "markdown"]),
    default="terminal",
    help="Output format",
)
@click.option(
    "--path",
    "-p",
    type=click.Path(exists=True, path_type=Path),
    default=Path("."),
    help="Path to compare (default: current directory)",
)
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable colored output",
)
@click.pass_obj
def diff(
    ctx: MUContext,
    base_ref: str,
    target_ref: str,
    output: Path | None,
    format: str,
    path: Path,
    no_color: bool,
) -> None:
    """Show semantic differences between two git refs (branches, commits, or tags).

    Compares the MU representation of your codebase between BASE_REF and TARGET_REF,
    showing added/removed/modified modules, functions, classes, and dependencies.

    \b
    Examples:
        mu diff main feature-branch     # Compare main to feature branch
        mu diff HEAD~5 HEAD             # Compare last 5 commits
        mu diff v1.0.0 v2.0.0           # Compare tagged releases
        mu diff main HEAD -f json       # Output as JSON
    """
    from mu.assembler import AssembledOutput, assemble
    from mu.config import MUConfig
    from mu.diff import (
        SemanticDiffer,
        format_diff,
        format_diff_json,
    )
    from mu.diff.formatters import format_diff_markdown
    from mu.diff.git_utils import GitError, compare_refs
    from mu.errors import ExitCode
    from mu.logging import console, print_error, print_info, print_success, print_warning
    from mu.parser import parse_file
    from mu.parser.models import ModuleDef
    from mu.reducer import reduce_codebase
    from mu.reducer.rules import TransformationRules
    from mu.scanner import scan_codebase_auto

    if ctx.config is None:
        ctx.config = MUConfig()

    print_info(f"Comparing {base_ref} → {target_ref}...")

    try:
        with compare_refs(path, base_ref, target_ref) as (
            base_path,
            target_path,
            base_git_ref,
            target_git_ref,
        ):
            # Shared transformation rules
            rules = TransformationRules(
                strip_stdlib_imports=True,
                strip_relative_imports=False,
                strip_dunder_methods=True,
                strip_property_getters=True,
                strip_empty_methods=True,
                include_docstrings=False,
                include_decorators=True,
                include_type_annotations=True,
            )

            def process_version(
                version_path: Path, label: str
            ) -> tuple[AssembledOutput | None, list[ModuleDef]]:
                """Process a version of the codebase through the MU pipeline."""
                assert ctx.config is not None
                # Scan
                version_scan_result = scan_codebase_auto(version_path, ctx.config)
                if version_scan_result.stats.total_files == 0:
                    return None, []

                # Parse
                version_modules: list[ModuleDef] = []
                for file_info in version_scan_result.files:
                    file_path = version_path / file_info.path
                    parse_result = parse_file(file_path, file_info.language)
                    if parse_result.success and parse_result.module is not None:
                        version_modules.append(parse_result.module)

                # Reduce
                reduced = reduce_codebase(version_modules, version_path, rules)

                # Assemble
                assembled = assemble(version_modules, reduced, version_path)

                return assembled, version_modules

            # Process both versions
            print_info(f"  Processing {base_ref}...")
            base_assembled, _ = process_version(base_path, base_ref)

            print_info(f"  Processing {target_ref}...")
            target_assembled, _ = process_version(target_path, target_ref)

            if base_assembled is None or target_assembled is None:
                print_warning("No supported files found in one or both refs")
                return

            # Compute diff
            print_info("  Computing semantic diff...")
            differ = SemanticDiffer(
                base_assembled,
                target_assembled,
                base_ref,
                target_ref,
            )
            result = differ.diff()

            # Format output
            if format == "json":
                output_str = format_diff_json(result)
            elif format == "markdown":
                output_str = format_diff_markdown(result)
            else:
                output_str = format_diff(result, no_color=no_color)

            # Write output
            if output:
                output.write_text(output_str)
                print_success(f"Diff written to {output}")
            else:
                console.print(output_str)

    except GitError as e:
        print_error(str(e))
        sys.exit(ExitCode.GIT_ERROR)


__all__ = ["diff"]
