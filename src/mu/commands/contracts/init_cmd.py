"""MU contracts init command - Create template contracts file."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command("init")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing file")
def contracts_init(path: Path, force: bool) -> None:
    """Create a template .mu-contracts.yml file.

    Creates a contract file with example rules that you can customize.

    \b
    Example:
        mu contracts init
        mu contracts init . --force
    """
    from mu.errors import ExitCode
    from mu.logging import print_info, print_success, print_warning

    contract_path = path.resolve() / ".mu-contracts.yml"

    if contract_path.exists() and not force:
        print_warning(f"Contract file already exists: {contract_path}")
        print_info("Use --force to overwrite")
        sys.exit(ExitCode.CONFIG_ERROR)

    template = """# MU Contracts - Architecture Rules
# Documentation: https://github.com/0ximu/mu/docs/contracts.md

version: "1.0"
name: "Architecture Contracts"

settings:
  fail_on_warning: false
  exclude_tests: true
  exclude_patterns:
    - "**/test_*.py"
    - "**/__mocks__/**"

contracts:
  # Circular dependency detection
  - name: "No circular dependencies"
    description: "Prevent circular module dependencies"
    severity: error
    rule:
      type: analyze
      analysis: circular
    expect: empty

  # Complexity limits
  - name: "Function complexity limit"
    description: "No function should exceed complexity 500"
    severity: warning
    rule:
      type: query
      muql: |
        SELECT name, file_path, complexity
        FROM functions
        WHERE complexity > 500
    expect: empty

  # Example dependency rule (customize for your project)
  # - name: "Services don't import controllers"
  #   description: "Services should be UI-agnostic"
  #   severity: error
  #   rule:
  #     type: dependency
  #     from: "src/services/**"
  #     to: "src/controllers/**"
  #   expect: empty

  # Example pattern rule (customize for your project)
  # - name: "All services are injectable"
  #   description: "Service classes must have @injectable decorator"
  #   severity: warning
  #   rule:
  #     type: pattern
  #     match: "src/services/**/*.py"
  #     node_type: class
  #     name_pattern: "*Service"
  #     must_have:
  #       decorator: "@injectable"
  #   expect: empty
"""

    contract_path.write_text(template)
    print_success(f"Created {contract_path}")
    print_info("\nNext steps:")
    print_info("  1. Edit .mu-contracts.yml to add your rules")
    print_info("  2. Run 'mu kernel build' to create the graph (if not done)")
    print_info("  3. Run 'mu contracts verify' to check contracts")


__all__ = ["contracts_init"]
