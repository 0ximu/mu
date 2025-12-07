"""YAML contract file parser.

This module provides functions to parse `.mu-contracts.yml` files into
ContractFile objects with validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from mu.contracts.models import (
    Contract,
    ContractFile,
    ContractSettings,
    Expectation,
    ExpectationType,
    Rule,
    RuleType,
    Severity,
)


class ContractParseError(Exception):
    """Error parsing a contract file."""

    pass


def parse_contracts(content: str) -> ContractFile:
    """Parse YAML content into a ContractFile.

    Args:
        content: YAML string content.

    Returns:
        Parsed ContractFile object.

    Raises:
        ContractParseError: If parsing fails.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ContractParseError(f"Invalid YAML: {e}") from e

    if data is None:
        # Empty file
        return ContractFile()

    if not isinstance(data, dict):
        raise ContractParseError("Contract file must be a YAML object")

    return _parse_contract_file(data)


def parse_contracts_file(path: Path) -> ContractFile:
    """Parse a contract file from a path.

    Args:
        path: Path to the contract YAML file.

    Returns:
        Parsed ContractFile object.

    Raises:
        ContractParseError: If file not found or parsing fails.
    """
    if not path.exists():
        raise ContractParseError(f"File not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ContractParseError(f"Failed to read file: {e}") from e

    return parse_contracts(content)


def _parse_contract_file(data: dict[str, Any]) -> ContractFile:
    """Parse top-level contract file structure."""
    # Parse settings
    settings_data = data.get("settings", {})
    if not isinstance(settings_data, dict):
        settings_data = {}

    settings = ContractSettings(
        fail_on_warning=settings_data.get("fail_on_warning", False),
        exclude_tests=settings_data.get("exclude_tests", True),
        exclude_patterns=settings_data.get("exclude_patterns", []) or [],
    )

    # Parse contracts
    contracts: list[Contract] = []
    contracts_data = data.get("contracts", [])
    if not isinstance(contracts_data, list):
        contracts_data = []

    for idx, c in enumerate(contracts_data):
        if not isinstance(c, dict):
            raise ContractParseError(f"Contract {idx + 1}: Must be a YAML object")
        try:
            contracts.append(_parse_contract(c))
        except ContractParseError as e:
            raise ContractParseError(f"Contract {idx + 1}: {e}") from e

    return ContractFile(
        version=str(data.get("version", "1.0")),
        name=str(data.get("name", "MU Contracts")),
        settings=settings,
        contracts=contracts,
    )


def _parse_contract(data: dict[str, Any]) -> Contract:
    """Parse a single contract definition."""
    # Required fields
    if "name" not in data:
        raise ContractParseError("Missing required field: name")
    if "rule" not in data:
        raise ContractParseError("Missing required field: rule")

    # Parse severity
    severity_str = str(data.get("severity", "error")).lower()
    try:
        severity = Severity(severity_str)
    except ValueError as e:
        valid = ", ".join(s.value for s in Severity)
        raise ContractParseError(
            f"Invalid severity: {severity_str}. Must be one of: {valid}"
        ) from e

    # Parse rule
    rule_data = data.get("rule")
    if not isinstance(rule_data, dict):
        raise ContractParseError("Rule must be a YAML object")
    rule = _parse_rule(rule_data)

    # Parse expectation
    expect = _parse_expectation(data.get("expect", "empty"))

    return Contract(
        name=str(data["name"]),
        description=str(data.get("description", "")),
        severity=severity,
        rule=rule,
        expect=expect,
        enabled=bool(data.get("enabled", True)),
    )


def _parse_rule(data: dict[str, Any]) -> Rule:
    """Parse a rule definition."""
    if "type" not in data:
        raise ContractParseError("Rule missing required field: type")

    rule_type_str = str(data["type"]).lower()
    try:
        rule_type = RuleType(rule_type_str)
    except ValueError as e:
        valid = ", ".join(r.value for r in RuleType)
        raise ContractParseError(
            f"Invalid rule type: {rule_type_str}. Must be one of: {valid}"
        ) from e

    # Extract params based on rule type
    params: dict[str, Any] = {}

    if rule_type == RuleType.QUERY:
        if "muql" not in data:
            raise ContractParseError("Query rule requires 'muql' field")
        params["muql"] = str(data["muql"])

    elif rule_type == RuleType.ANALYZE:
        if "analysis" not in data:
            raise ContractParseError("Analyze rule requires 'analysis' field")
        analysis = str(data["analysis"]).lower()
        valid_analyses = {"circular", "complexity", "coupling", "unused", "hotspots"}
        if analysis not in valid_analyses:
            raise ContractParseError(
                f"Invalid analysis type: {analysis}. Must be one of: {', '.join(sorted(valid_analyses))}"
            )
        params["analysis"] = analysis
        # Optional threshold for complexity/coupling
        if "threshold" in data:
            params["threshold"] = int(data["threshold"])

    elif rule_type == RuleType.DEPENDENCY:
        if "from" not in data or "to" not in data:
            raise ContractParseError("Dependency rule requires 'from' and 'to' fields")
        params["from"] = str(data["from"])
        params["to"] = str(data["to"])
        # Optional exceptions list
        if "except" in data:
            exceptions = data["except"]
            if isinstance(exceptions, list):
                params["except"] = [str(e) for e in exceptions]

    elif rule_type == RuleType.PATTERN:
        # All optional, but at least one should be provided
        if "match" in data:
            params["match"] = str(data["match"])
        if "node_type" in data:
            params["node_type"] = str(data["node_type"]).lower()
        if "name_pattern" in data:
            params["name_pattern"] = str(data["name_pattern"])
        if "must_have" in data:
            must_have = data["must_have"]
            if isinstance(must_have, dict):
                params["must_have"] = must_have

    return Rule(type=rule_type, params=params)


def _parse_expectation(data: str | dict[str, Any]) -> Expectation:
    """Parse an expectation (can be string shorthand or dict)."""
    if isinstance(data, str):
        # Shorthand: "empty", "not_empty"
        data_lower = data.lower()
        # Handle underscore variations
        data_lower = data_lower.replace("-", "_")
        try:
            exp_type = ExpectationType(data_lower)
            return Expectation(type=exp_type)
        except ValueError as e:
            valid = ", ".join(e_type.value for e_type in ExpectationType)
            raise ContractParseError(f"Invalid expectation: {data}. Must be one of: {valid}") from e

    if isinstance(data, dict):
        # Dict form: {"max": 10}, {"min": 1}, {"count": 0}
        if "max" in data:
            return Expectation(type=ExpectationType.MAX, value=int(data["max"]))
        if "min" in data:
            return Expectation(type=ExpectationType.MIN, value=int(data["min"]))
        if "count" in data:
            return Expectation(type=ExpectationType.COUNT, value=int(data["count"]))
        if "type" in data:
            # Full form: {"type": "empty", "value": null}
            try:
                exp_type = ExpectationType(str(data["type"]).lower())
                value = data.get("value")
                return Expectation(
                    type=exp_type,
                    value=int(value) if value is not None else None,
                )
            except ValueError as e:
                valid = ", ".join(e_type.value for e_type in ExpectationType)
                raise ContractParseError(
                    f"Invalid expectation type: {data['type']}. Must be one of: {valid}"
                ) from e

    raise ContractParseError(f"Invalid expectation format: {data}")
