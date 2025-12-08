"""MU contracts verify command - Verify architectural contracts."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import CONTRACTS_FILE, get_contracts_path, get_mubase_path


@click.command("verify")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--contract-file",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help=f"Contract file (default: .mu/{CONTRACTS_FILE})",
)
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "junit"]),
    default="text",
    help="Output format",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--fail-fast", is_flag=True, help="Stop on first error")
@click.option("--only", "only_pattern", type=str, help="Only run contracts matching pattern")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file (default: stdout)",
)
def contracts_verify(
    path: Path,
    contract_file: Path | None,
    output_format: str,
    no_color: bool,
    fail_fast: bool,
    only_pattern: str | None,
    output: Path | None,
) -> None:
    """Verify architectural contracts against codebase.

    Loads contracts from .mu/contracts.yml (or specified file) and
    verifies them against the MUbase graph database.

    \b
    Examples:
        mu contracts verify .
        mu contracts verify . --format junit > report.xml
        mu contracts verify . --only "No circular*"
    """
    from fnmatch import fnmatch

    from mu.contracts.parser import ContractParseError, parse_contracts_file
    from mu.contracts.reporter import ContractReporter
    from mu.contracts.verifier import ContractVerifier
    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.logging import console, print_error, print_info, print_success, print_warning

    # Find mubase
    mubase_path = get_mubase_path(path)
    if not mubase_path.exists():
        print_error(f"No mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first to create the graph database")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Find contract file
    if contract_file is None:
        contract_file = get_contracts_path(path)

    if not contract_file.exists():
        print_error(f"Contract file not found: {contract_file}")
        print_info("Run 'mu contracts init' to create a template")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Parse contracts
    try:
        contracts_data = parse_contracts_file(contract_file)
    except ContractParseError as e:
        print_error(f"Failed to parse contracts: {e}")
        sys.exit(ExitCode.CONFIG_ERROR)

    print_info(f"Loaded {len(contracts_data.contracts)} contracts from {contract_file.name}")

    # Filter by --only pattern
    if only_pattern:
        contracts_data.contracts = [
            c for c in contracts_data.contracts if fnmatch(c.name, only_pattern)
        ]
        print_info(
            f"Filtered to {len(contracts_data.contracts)} contracts matching '{only_pattern}'"
        )

    if not contracts_data.contracts:
        print_warning("No contracts to verify")
        return

    # Verify
    db = MUbase(mubase_path)
    try:
        verifier = ContractVerifier(db)
        result = verifier.verify(contracts_data, fail_fast=fail_fast)
    finally:
        db.close()

    # Report
    reporter = ContractReporter()
    if output_format == "json":
        output_str = reporter.report_json(result)
    elif output_format == "junit":
        output_str = reporter.report_junit(result)
    else:
        output_str = reporter.report_text(result, no_color=no_color)

    # Output
    if output:
        output.write_text(output_str)
        print_success(f"Report written to {output}")
    else:
        console.print(output_str)

    # Exit code
    if not result.passed:
        sys.exit(ExitCode.CONTRACT_VIOLATION)


__all__ = ["contracts_verify"]
