"""CLI commands for code generation."""

from __future__ import annotations

import json
from pathlib import Path

import click

from mu.logging import print_error, print_info, print_success, print_warning

TEMPLATE_TYPES = [
    "hook",
    "component",
    "service",
    "repository",
    "api_route",
    "test",
    "model",
    "controller",
]


@click.command("generate")
@click.argument("template_type", type=click.Choice(TEMPLATE_TYPES, case_sensitive=False))
@click.argument("name")
@click.option(
    "-e",
    "--entity",
    help="Entity name for services/repositories (e.g., 'User')",
)
@click.option(
    "-f",
    "--field",
    multiple=True,
    help="Add field to model (format: 'name:type', e.g., 'email:str')",
)
@click.option(
    "-t",
    "--target",
    help="Target module for test generation",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(),
    help="Override output directory",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be generated without creating files",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    help="Output as JSON (implies --dry-run)",
)
@click.option(
    "-p",
    "--path",
    type=click.Path(exists=True),
    default=".",
    help="Path to codebase root (default: current directory)",
)
def generate(
    template_type: str,
    name: str,
    entity: str | None,
    field: tuple[str, ...],
    target: str | None,
    output: str | None,
    dry_run: bool,
    output_json: bool,
    path: str,
) -> None:
    """Generate code following codebase patterns.

    Creates boilerplate code that matches detected patterns and conventions.
    Supports multiple template types for different architectural components.

    Examples:

        mu generate hook useAuth           # Generate React hook
        mu generate service User           # Generate UserService class
        mu generate api_route users        # Generate API route handlers
        mu generate model Product -f price:float -f name:str  # With fields
        mu generate test auth -t src/auth.py  # Test for specific module
        mu generate component UserProfile --dry-run  # Preview only
    """
    from mu.intelligence import CodeGenerator, TemplateType
    from mu.kernel import MUbase

    root_path = Path(path).resolve()
    mubase_path = root_path / ".mubase"

    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu bootstrap' or 'mu kernel build .' first")
        raise SystemExit(1)

    # Parse field options into list of dicts
    fields = []
    for f in field:
        if ":" in f:
            fname, ftype = f.split(":", 1)
            fields.append({"name": fname.strip(), "type": ftype.strip()})
        else:
            fields.append({"name": f.strip(), "type": "str"})

    # Build options dict
    options: dict[str, object] = {}
    if entity:
        options["entity"] = entity
    if fields:
        options["fields"] = fields
    if target:
        options["target"] = target

    db = MUbase(mubase_path)
    try:
        generator = CodeGenerator(db)
        tt = TemplateType(template_type)
        result = generator.generate(tt, name, options)

        if output_json:
            click.echo(json.dumps(result.to_dict(), indent=2))
            return

        # Display results
        print_success(f"Generated {result.template_type.value}: {result.name}\n")

        if result.patterns_used:
            click.echo(click.style("  Patterns used: ", dim=True) + ", ".join(result.patterns_used))
            click.echo()

        for file in result.files:
            is_primary = "●" if file.is_primary else "○"
            click.echo(
                click.style(f"  {is_primary} ", fg="green" if file.is_primary else "blue")
                + click.style(file.path, bold=file.is_primary)
            )
            click.echo(click.style(f"    {file.description}", dim=True))

            if dry_run or output_json:
                # Show file content preview
                click.echo()
                lines = file.content.split("\n")
                preview_lines = lines[:15]
                for line in preview_lines:
                    click.echo(click.style(f"    │ {line}", dim=True))
                if len(lines) > 15:
                    click.echo(click.style(f"    │ ... ({len(lines) - 15} more lines)", dim=True))
                click.echo()

        if not dry_run and not output_json:
            # Write files
            click.echo()
            files_written = 0
            for file in result.files:
                # Determine output path
                if output:
                    file_path = Path(output) / Path(file.path).name
                else:
                    file_path = root_path / file.path

                # Create parent directories
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Check if file exists
                if file_path.exists():
                    print_warning(f"File exists, skipping: {file_path}")
                    continue

                # Write file
                file_path.write_text(file.content)
                print_info(f"Created: {file_path}")
                files_written += 1

            if files_written > 0:
                print_success(f"\n✓ Created {files_written} file(s)")
            else:
                print_warning("\nNo files created (all already exist)")

        if result.suggestions:
            click.echo()
            click.echo(click.style("  Suggestions:", fg="yellow"))
            for suggestion in result.suggestions:
                click.echo(f"    → {suggestion}")

    finally:
        db.close()


__all__ = ["generate"]
