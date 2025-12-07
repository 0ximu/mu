"""Contract verification reporters.

This module provides the ContractReporter class for generating
text, JSON, and JUnit XML reports from verification results.
"""

from __future__ import annotations

import json
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from mu.contracts.models import VerificationResult


class ContractReporter:
    """Generate verification reports in various formats.

    Example:
        >>> from mu.contracts import ContractReporter, VerificationResult
        >>>
        >>> reporter = ContractReporter()
        >>> result = VerificationResult(passed=True, contracts_checked=5)
        >>> print(reporter.report_text(result))
        Contract Verification: PASSED
        Checked: 5 contracts
    """

    def report_text(
        self,
        result: VerificationResult,
        no_color: bool = False,
    ) -> str:
        """Generate human-readable text report.

        Args:
            result: The verification result.
            no_color: If True, disable ANSI color codes.

        Returns:
            Formatted text report.
        """
        lines: list[str] = []

        # Status header with optional color
        status = "PASSED" if result.passed else "FAILED"
        if not no_color:
            if result.passed:
                status = f"\033[32m{status}\033[0m"  # Green
            else:
                status = f"\033[31m{status}\033[0m"  # Red

        lines.append(f"Contract Verification: {status}")
        lines.append(f"Checked: {result.contracts_checked} contracts")
        lines.append("")

        # Errors
        if result.violations:
            error_header = f"ERRORS ({len(result.violations)}):"
            if not no_color:
                error_header = f"\033[31m{error_header}\033[0m"
            lines.append(error_header)
            for v in result.violations:
                lines.append(f"  x {v.contract.name}")
                if v.contract.description:
                    lines.append(f"    {v.contract.description}")
                for detail in v.details[:5]:
                    lines.append(f"    - {self._format_detail(detail)}")
                if len(v.details) > 5:
                    lines.append(f"    ... and {len(v.details) - 5} more")
            lines.append("")

        # Warnings
        if result.warnings:
            warning_header = f"WARNINGS ({len(result.warnings)}):"
            if not no_color:
                warning_header = f"\033[33m{warning_header}\033[0m"  # Yellow
            lines.append(warning_header)
            for v in result.warnings:
                lines.append(f"  ! {v.contract.name}")
                if v.contract.description:
                    lines.append(f"    {v.contract.description}")
                for detail in v.details[:3]:
                    lines.append(f"    - {self._format_detail(detail)}")
                if len(v.details) > 3:
                    lines.append(f"    ... and {len(v.details) - 3} more")
            lines.append("")

        # Info
        if result.info:
            lines.append(f"INFO ({len(result.info)}):")
            for v in result.info:
                lines.append(f"  i {v.contract.name}")
            lines.append("")

        # Summary
        lines.append("Summary:")
        lines.append(f"  Errors: {result.error_count}")
        lines.append(f"  Warnings: {result.warning_count}")

        return "\n".join(lines)

    def report_json(self, result: VerificationResult) -> str:
        """Generate JSON report.

        Args:
            result: The verification result.

        Returns:
            JSON string.
        """
        return json.dumps(result.to_dict(), indent=2)

    def report_junit(self, result: VerificationResult) -> str:
        """Generate JUnit XML report for CI integration.

        Args:
            result: The verification result.

        Returns:
            JUnit XML string.
        """
        testsuite = Element(
            "testsuite",
            {
                "name": "MU Contracts",
                "tests": str(result.contracts_checked),
                "failures": str(result.error_count),
                "errors": "0",
                "skipped": "0",
            },
        )

        # Add test cases for errors (failures)
        for v in result.violations:
            testcase = SubElement(
                testsuite,
                "testcase",
                {
                    "name": v.contract.name,
                    "classname": "mu.contracts",
                },
            )
            failure = SubElement(
                testcase,
                "failure",
                {
                    "message": v.message,
                    "type": v.contract.severity.value,
                },
            )
            failure.text = json.dumps(v.details, indent=2)

        # Add test cases for warnings (not failures in JUnit terms)
        for v in result.warnings:
            testcase = SubElement(
                testsuite,
                "testcase",
                {
                    "name": v.contract.name,
                    "classname": "mu.contracts",
                },
            )
            # Use system-out for warnings
            system_out = SubElement(testcase, "system-out")
            system_out.text = f"WARNING: {v.message}\n{json.dumps(v.details, indent=2)}"

        # Add passed contracts as successful test cases
        # Note: We don't have explicit list of passed contracts, so we infer from count
        passed_count = result.contracts_checked - len(result.violations) - len(result.warnings)
        for i in range(passed_count):
            SubElement(
                testsuite,
                "testcase",
                {
                    "name": f"contract_{i + 1}",
                    "classname": "mu.contracts",
                },
            )

        return tostring(testsuite, encoding="unicode")

    def _format_detail(self, detail: dict[str, Any]) -> str:
        """Format a single violation detail.

        Args:
            detail: The detail dictionary.

        Returns:
            Formatted string.
        """
        if "from" in detail and "to" in detail:
            return f"{detail['from']} -> {detail['to']}"
        elif "node" in detail and "missing" in detail:
            path = detail.get("path", "")
            return f"{detail['node']} ({path}) - missing {detail['missing']}"
        elif "error" in detail:
            return f"Error: {detail['error']}"
        elif "name" in detail:
            path = detail.get("path", "")
            complexity = detail.get("complexity", "")
            return f"{detail['name']} ({path})" + (
                f" complexity={complexity}" if complexity else ""
            )
        elif "cycle" in detail:
            return " -> ".join(detail["cycle"])
        else:
            # Fallback: format as key=value pairs
            parts = [f"{k}={v}" for k, v in detail.items() if v is not None]
            return ", ".join(parts) if parts else str(detail)
