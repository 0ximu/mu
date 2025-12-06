"""Data models for MU Contracts.

This module defines the core data structures for contract definitions,
rules, expectations, violations, and verification results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(Enum):
    """Severity level of a contract violation."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class RuleType(Enum):
    """Type of contract rule."""

    QUERY = "query"  # MUQL query-based rule
    ANALYZE = "analyze"  # Built-in analysis (circular, complexity, etc.)
    DEPENDENCY = "dependency"  # A should not depend on B
    PATTERN = "pattern"  # All X must have Y


class ExpectationType(Enum):
    """Type of expected outcome for a rule."""

    EMPTY = "empty"  # Expect no results (no violations)
    NOT_EMPTY = "not_empty"  # Expect at least one result
    COUNT = "count"  # Expect exact count
    MAX = "max"  # Expect at most N
    MIN = "min"  # Expect at least N


@dataclass
class Expectation:
    """Expected outcome of a rule evaluation."""

    type: ExpectationType
    value: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type.value,
            "value": self.value,
        }


@dataclass
class Rule:
    """A contract rule definition."""

    type: RuleType
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type.value,
            "params": self.params,
        }


@dataclass
class Contract:
    """A single architectural contract."""

    name: str
    description: str
    severity: Severity
    rule: Rule
    expect: Expectation
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "severity": self.severity.value,
            "rule": self.rule.to_dict(),
            "expect": self.expect.to_dict(),
            "enabled": self.enabled,
        }


@dataclass
class ContractSettings:
    """Global settings for contract verification."""

    fail_on_warning: bool = False
    exclude_tests: bool = True
    exclude_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "fail_on_warning": self.fail_on_warning,
            "exclude_tests": self.exclude_tests,
            "exclude_patterns": self.exclude_patterns,
        }


@dataclass
class ContractFile:
    """Parsed contract file containing all contracts and settings."""

    version: str = "1.0"
    name: str = "MU Contracts"
    settings: ContractSettings = field(default_factory=ContractSettings)
    contracts: list[Contract] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "name": self.name,
            "settings": self.settings.to_dict(),
            "contracts": [c.to_dict() for c in self.contracts],
        }


@dataclass
class EvaluationResult:
    """Result of evaluating a single rule."""

    passed: bool
    details: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "passed": self.passed,
            "details": self.details,
            "row_count": self.row_count,
        }


@dataclass
class Violation:
    """A contract violation."""

    contract: Contract
    message: str
    details: list[dict[str, Any]] = field(default_factory=list)
    file_path: str | None = None
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "contract": self.contract.to_dict(),
            "message": self.message,
            "details": self.details,
            "file_path": self.file_path,
            "line": self.line,
        }


@dataclass
class VerificationResult:
    """Result of verifying all contracts."""

    passed: bool
    contracts_checked: int
    violations: list[Violation] = field(default_factory=list)
    warnings: list[Violation] = field(default_factory=list)
    info: list[Violation] = field(default_factory=list)
    error: str | None = None

    @property
    def success(self) -> bool:
        """True if verification completed without parse/execution errors."""
        return self.error is None

    @property
    def error_count(self) -> int:
        """Number of error-level violations."""
        return len(self.violations)

    @property
    def warning_count(self) -> int:
        """Number of warning-level violations."""
        return len(self.warnings)

    @property
    def info_count(self) -> int:
        """Number of info-level violations."""
        return len(self.info)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "passed": self.passed,
            "contracts_checked": self.contracts_checked,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": [v.to_dict() for v in self.warnings],
            "info": [v.to_dict() for v in self.info],
            "error": self.error,
            "summary": {
                "errors": self.error_count,
                "warnings": self.warning_count,
                "info": self.info_count,
            },
        }
