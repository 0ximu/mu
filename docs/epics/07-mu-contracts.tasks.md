# MU Contracts - Task Breakdown

## Implementation Status

| Task | Status | Notes |
|------|--------|-------|
| 1.1 Core Models | DONE | `src/mu/contracts/models.py` |
| 1.2 ContractFile | DONE | `src/mu/contracts/models.py` |
| 2.1 PyYAML Dependency | DONE | `pyproject.toml` |
| 2.2 YAML Parser | DONE | `src/mu/contracts/parser.py` |
| 3.1 RuleEvaluator Protocol | DONE | `src/mu/contracts/rules.py` |
| 3.2 QueryRuleEvaluator | DONE | `src/mu/contracts/rules.py` |
| 3.3 AnalyzeRuleEvaluator | DONE | `src/mu/contracts/rules.py` |
| 3.4 DependencyRuleEvaluator | DONE | `src/mu/contracts/rules.py` |
| 3.5 PatternRuleEvaluator | DONE | `src/mu/contracts/rules.py` |
| 4.1 ContractVerifier | DONE | `src/mu/contracts/verifier.py` |
| 5.1 ContractReporter | DONE | `src/mu/contracts/reporter.py` |
| 5.2 CLI Commands | DONE | `src/mu/cli.py` |
| 5.3 Exit Code | DONE | `src/mu/errors.py` |
| 6.1 Unit Tests | DONE | `tests/unit/test_contracts.py` (110 tests) |
| 6.2 CLAUDE.md | DONE | `src/mu/contracts/CLAUDE.md` |

## Quality Checks

- [x] ruff check passes
- [x] mypy passes
- [x] pytest passes (110 tests)
- [x] 96% line coverage
- [x] Code review: APPROVE

---

## Business Context

**Problem**: Developers and architects lack automated verification that their codebase follows architectural rules. Manual code reviews catch violations too late, and there's no way to enforce rules like "controllers must not access repositories directly" or "no function should exceed 500 complexity" in CI pipelines.

**Outcome**: A declarative contract system where:
- Architecture rules are defined in YAML (`.mu-contracts.yml`)
- Rules are verified against the MUbase graph using MUQL queries
- Violations are reported with clear messages and locations
- CI pipelines can fail on contract violations (non-zero exit code)
- JUnit XML output enables integration with test reporting tools

**Users**:
- Architects defining and enforcing layered architecture rules
- Tech leads maintaining code quality standards
- DevOps engineers integrating contracts into CI/CD pipelines
- Developers getting early feedback on architectural violations

---

## Discovered Patterns

| Pattern | File | Relevance |
|---------|------|-----------|
| Dataclass with to_dict() | `/Users/imu/Dev/work/mu/src/mu/diff/models.py:19-266` | Contract, Rule, Violation models follow DiffResult pattern |
| Enum for types | `/Users/imu/Dev/work/mu/src/mu/diff/models.py:10-17` | Severity enum follows ChangeType pattern |
| Error-as-data pattern | `/Users/imu/Dev/work/mu/src/mu/kernel/export/base.py:50-87` | VerificationResult follows ExportResult with `.success` property |
| Protocol for extensibility | `/Users/imu/Dev/work/mu/src/mu/kernel/export/base.py:90-127` | RuleEvaluator protocol follows Exporter pattern |
| Manager/Registry pattern | `/Users/imu/Dev/work/mu/src/mu/kernel/export/base.py:130-210` | ContractVerifier follows ExportManager pattern |
| MUQL Engine usage | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/engine.py:70-106` | Query rules use MUQLEngine.execute() for queries |
| MUbase analysis methods | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/executor.py:361-379` | Circular dependency detection via graph queries |
| Click CLI commands | `/Users/imu/Dev/work/mu/src/mu/cli.py:729-732` | `contracts` command group follows `cache` and `kernel` patterns |
| CLI subcommands | `/Users/imu/Dev/work/mu/src/mu/cli.py:2326-2567` | `contracts verify/init` follows `daemon start/stop` pattern |
| Pydantic config | `/Users/imu/Dev/work/mu/src/mu/config.py` | Settings parsing could use Pydantic for YAML schema |
| Test fixtures | `/Users/imu/Dev/work/mu/tests/unit/test_export.py:29-100` | Contract tests follow db_path, populated_db fixture pattern |
| Module __init__ exports | `/Users/imu/Dev/work/mu/src/mu/daemon/__init__.py:1-67` | Public API with __all__ and docstring examples |

---

## Dependency Check

**MUQL Status**: MUQL is fully implemented (Epic 2 complete). Key files:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/engine.py` - MUQLEngine with execute()/query() methods
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/executor.py` - QueryExecutor with analysis methods
- Analysis types available: complexity, hotspots, circular, unused, coupling, cohesion, impact

MU Contracts can use MUQL directly for query-based rules. For analyze rules, we can leverage existing `_analyze_circular()` and other methods in the executor.

---

## Task Breakdown

### Story 7.1: Contract Definition - Core Models

#### Task 1.1: Create Contracts Module Structure

**Priority**: P0 (Foundation)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/__init__.py` (new)
- `/Users/imu/Dev/work/mu/src/mu/contracts/models.py` (new)

**Pattern**: Follow `src/mu/daemon/__init__.py` and `src/mu/diff/models.py`

**Description**: Create the contracts module with core data models for contracts, rules, expectations, and violations.

**Implementation Notes**:
```python
# models.py - Follow diff/models.py dataclass pattern
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

class RuleType(Enum):
    QUERY = "query"       # MUQL query-based
    ANALYZE = "analyze"   # Built-in analysis (circular, complexity)
    DEPENDENCY = "dependency"  # A should not depend on B
    PATTERN = "pattern"   # All X must have Y

class ExpectationType(Enum):
    EMPTY = "empty"       # Expect no results
    NOT_EMPTY = "not_empty"
    COUNT = "count"       # Expect exact count
    MAX = "max"           # Expect at most N
    MIN = "min"           # Expect at least N

@dataclass
class Expectation:
    type: ExpectationType
    value: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "value": self.value}

@dataclass
class Rule:
    type: RuleType
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "params": self.params}

@dataclass
class Contract:
    name: str
    description: str
    severity: Severity
    rule: Rule
    expect: Expectation
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class Violation:
    contract: Contract
    message: str
    details: list[dict[str, Any]] = field(default_factory=list)
    file_path: str | None = None
    line: int | None = None

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class VerificationResult:
    passed: bool
    contracts_checked: int
    violations: list[Violation] = field(default_factory=list)
    warnings: list[Violation] = field(default_factory=list)
    info: list[Violation] = field(default_factory=list)
    error: str | None = None  # Parse/execution error

    @property
    def success(self) -> bool:
        return self.error is None

    @property
    def error_count(self) -> int:
        return len([v for v in self.violations if v.contract.severity == Severity.ERROR])

    def to_dict(self) -> dict[str, Any]: ...
```

**Acceptance Criteria**:
- [ ] `Severity` enum with ERROR, WARNING, INFO
- [ ] `RuleType` enum with QUERY, ANALYZE, DEPENDENCY, PATTERN
- [ ] `ExpectationType` enum with EMPTY, NOT_EMPTY, COUNT, MAX, MIN
- [ ] `Rule` dataclass with type and params dict
- [ ] `Expectation` dataclass with type and optional value
- [ ] `Contract` dataclass with name, description, severity, rule, expect, enabled
- [ ] `Violation` dataclass with contract, message, details, file_path, line
- [ ] `VerificationResult` with passed, violations, warnings, info, and `success` property
- [ ] All models implement `to_dict()` for JSON serialization
- [ ] Type annotations pass mypy
- [ ] `__init__.py` exports all public models with `__all__`

---

#### Task 1.2: Create Contract File Model and Settings

**Priority**: P0 (Required for parser)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/models.py` (modify)

**Pattern**: Follow epic specification Section 3.1

**Dependencies**: Task 1.1 (models)

**Description**: Add ContractFile and ContractSettings dataclasses to represent the full YAML structure.

**Implementation Notes**:
```python
@dataclass
class ContractSettings:
    """Global settings for contract verification."""
    fail_on_warning: bool = False
    exclude_tests: bool = True
    exclude_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fail_on_warning": self.fail_on_warning,
            "exclude_tests": self.exclude_tests,
            "exclude_patterns": self.exclude_patterns,
        }

@dataclass
class ContractFile:
    """Parsed contract file."""
    version: str = "1.0"
    name: str = "MU Contracts"
    settings: ContractSettings = field(default_factory=ContractSettings)
    contracts: list[Contract] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "settings": self.settings.to_dict(),
            "contracts": [c.to_dict() for c in self.contracts],
        }
```

**Acceptance Criteria**:
- [ ] `ContractSettings` with fail_on_warning, exclude_tests, exclude_patterns
- [ ] `ContractFile` with version, name, settings, contracts list
- [ ] Default values match epic specification
- [ ] Both implement `to_dict()`
- [ ] Added to `__init__.py` exports

---

### Story 7.1: Contract Definition - Parser

#### Task 2.1: Add PyYAML Dependency

**Priority**: P0 (Required for parser)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/pyproject.toml` (modify)

**Pattern**: Follow existing dependency format

**Description**: Add PyYAML package for YAML parsing.

**Implementation Notes**:
```toml
# Add to dependencies list
"pyyaml>=6.0",
```

**Acceptance Criteria**:
- [ ] PyYAML added to dependencies in pyproject.toml
- [ ] Version constraint >= 6.0 for security fixes
- [ ] `pip install -e .` succeeds

---

#### Task 2.2: Implement YAML Contract Parser

**Priority**: P0 (Core functionality)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/parser.py` (new)

**Pattern**: Follow error-as-data pattern from `kernel/export/base.py`

**Dependencies**: Task 1.1, 1.2 (models), Task 2.1 (PyYAML)

**Description**: Parse `.mu-contracts.yml` files into ContractFile objects with validation.

**Implementation Notes**:
```python
from pathlib import Path
from typing import Any
import yaml

from mu.contracts.models import (
    Contract, ContractFile, ContractSettings, Expectation, ExpectationType,
    Rule, RuleType, Severity
)

class ContractParseError(Exception):
    """Error parsing contract file."""
    pass

def parse_contracts(content: str) -> ContractFile:
    """Parse YAML content into ContractFile.

    Args:
        content: YAML string content

    Returns:
        ContractFile object

    Raises:
        ContractParseError: If parsing fails
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ContractParseError(f"Invalid YAML: {e}")

    if not isinstance(data, dict):
        raise ContractParseError("Contract file must be a YAML object")

    return _parse_contract_file(data)

def parse_contracts_file(path: Path) -> ContractFile:
    """Parse contract file from path."""
    if not path.exists():
        raise ContractParseError(f"File not found: {path}")

    content = path.read_text()
    return parse_contracts(content)

def _parse_contract_file(data: dict[str, Any]) -> ContractFile:
    """Parse top-level contract file structure."""
    # Parse settings
    settings_data = data.get("settings", {})
    settings = ContractSettings(
        fail_on_warning=settings_data.get("fail_on_warning", False),
        exclude_tests=settings_data.get("exclude_tests", True),
        exclude_patterns=settings_data.get("exclude_patterns", []),
    )

    # Parse contracts
    contracts = []
    for idx, c in enumerate(data.get("contracts", [])):
        try:
            contracts.append(_parse_contract(c))
        except ContractParseError as e:
            raise ContractParseError(f"Contract {idx + 1}: {e}")

    return ContractFile(
        version=data.get("version", "1.0"),
        name=data.get("name", "MU Contracts"),
        settings=settings,
        contracts=contracts,
    )

def _parse_contract(data: dict[str, Any]) -> Contract:
    """Parse single contract definition."""
    # Required fields
    if "name" not in data:
        raise ContractParseError("Missing required field: name")
    if "rule" not in data:
        raise ContractParseError("Missing required field: rule")

    # Parse severity
    severity_str = data.get("severity", "error").lower()
    try:
        severity = Severity(severity_str)
    except ValueError:
        raise ContractParseError(f"Invalid severity: {severity_str}")

    # Parse rule
    rule = _parse_rule(data["rule"])

    # Parse expectation
    expect = _parse_expectation(data.get("expect", "empty"))

    return Contract(
        name=data["name"],
        description=data.get("description", ""),
        severity=severity,
        rule=rule,
        expect=expect,
        enabled=data.get("enabled", True),
    )

def _parse_rule(data: dict[str, Any]) -> Rule:
    """Parse rule definition."""
    if "type" not in data:
        raise ContractParseError("Rule missing required field: type")

    rule_type_str = data["type"].lower()
    try:
        rule_type = RuleType(rule_type_str)
    except ValueError:
        raise ContractParseError(f"Invalid rule type: {rule_type_str}")

    # Extract params based on rule type
    params = {}
    if rule_type == RuleType.QUERY:
        if "muql" not in data:
            raise ContractParseError("Query rule requires 'muql' field")
        params["muql"] = data["muql"]
    elif rule_type == RuleType.ANALYZE:
        if "analysis" not in data:
            raise ContractParseError("Analyze rule requires 'analysis' field")
        params["analysis"] = data["analysis"]
    elif rule_type == RuleType.DEPENDENCY:
        if "from" not in data or "to" not in data:
            raise ContractParseError("Dependency rule requires 'from' and 'to' fields")
        params["from"] = data["from"]
        params["to"] = data["to"]
    elif rule_type == RuleType.PATTERN:
        params["match"] = data.get("match")
        params["node_type"] = data.get("node_type")
        params["name_pattern"] = data.get("name_pattern")
        params["must_have"] = data.get("must_have", {})

    return Rule(type=rule_type, params=params)

def _parse_expectation(data: str | dict[str, Any]) -> Expectation:
    """Parse expectation (can be string shorthand or dict)."""
    if isinstance(data, str):
        # Shorthand: "empty", "not_empty"
        try:
            exp_type = ExpectationType(data.lower())
            return Expectation(type=exp_type)
        except ValueError:
            raise ContractParseError(f"Invalid expectation: {data}")

    if isinstance(data, dict):
        # Dict form: {"max": 10}, {"min": 1}, {"count": 0}
        if "max" in data:
            return Expectation(type=ExpectationType.MAX, value=data["max"])
        if "min" in data:
            return Expectation(type=ExpectationType.MIN, value=data["min"])
        if "count" in data:
            return Expectation(type=ExpectationType.COUNT, value=data["count"])

    raise ContractParseError(f"Invalid expectation format: {data}")
```

**Acceptance Criteria**:
- [ ] `parse_contracts(content)` parses YAML string
- [ ] `parse_contracts_file(path)` parses file from Path
- [ ] Validates required fields (name, rule, rule.type)
- [ ] Parses all rule types: query, analyze, dependency, pattern
- [ ] Parses expectation shorthands ("empty") and dict form ({"max": 10})
- [ ] Raises `ContractParseError` with descriptive messages
- [ ] Handles missing files, invalid YAML gracefully
- [ ] Unit tests for all rule types and error cases

---

### Story 7.2-7.4: Rule Evaluators

#### Task 3.1: Create RuleEvaluator Protocol and Base

**Priority**: P0 (Required for all evaluators)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/rules.py` (new)

**Pattern**: Follow `kernel/export/base.py:90-127` Exporter protocol

**Dependencies**: Task 1.1 (models)

**Description**: Define RuleEvaluator protocol and base class for rule evaluation.

**Implementation Notes**:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from mu.contracts.models import Expectation, ExpectationType, Rule

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase

@dataclass
class EvaluationResult:
    """Result of evaluating a rule."""
    passed: bool
    details: list[dict[str, Any]]
    row_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "details": self.details,
            "row_count": self.row_count,
        }

@runtime_checkable
class RuleEvaluator(Protocol):
    """Protocol for rule evaluators."""

    @property
    def rule_type(self) -> str:
        """Return the rule type this evaluator handles."""
        ...

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        """Evaluate rule against database.

        Args:
            mubase: The MUbase database
            rule: Rule definition with params
            expect: Expected outcome

        Returns:
            EvaluationResult with passed flag and violation details
        """
        ...

def check_expectation(
    result_count: int,
    expect: Expectation,
    result_value: int | None = None,
) -> bool:
    """Check if result meets expectation.

    Args:
        result_count: Number of results returned
        expect: The expectation to check
        result_value: Optional single value (for aggregates like COUNT)

    Returns:
        True if expectation is met
    """
    match expect.type:
        case ExpectationType.EMPTY:
            return result_count == 0
        case ExpectationType.NOT_EMPTY:
            return result_count > 0
        case ExpectationType.COUNT:
            return result_count == expect.value
        case ExpectationType.MAX:
            value = result_value if result_value is not None else result_count
            return value <= (expect.value or 0)
        case ExpectationType.MIN:
            value = result_value if result_value is not None else result_count
            return value >= (expect.value or 0)
    return False
```

**Acceptance Criteria**:
- [ ] `RuleEvaluator` protocol with rule_type property and evaluate method
- [ ] `EvaluationResult` dataclass with passed, details, row_count
- [ ] `check_expectation()` helper for all ExpectationType values
- [ ] Protocol is `@runtime_checkable`
- [ ] Type annotations pass mypy

---

#### Task 3.2: Implement QueryRuleEvaluator

**Priority**: P0 (Most common rule type)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/rules.py` (modify)

**Pattern**: Follow `kernel/muql/engine.py:70-106` for MUQL execution

**Dependencies**: Task 3.1 (protocol)

**Description**: Implement evaluator for MUQL query-based rules.

**Implementation Notes**:
```python
from mu.kernel.muql import MUQLEngine

class QueryRuleEvaluator:
    """Evaluate MUQL query rules."""

    @property
    def rule_type(self) -> str:
        return "query"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        muql = rule.params.get("muql", "")
        if not muql:
            return EvaluationResult(
                passed=False,
                details=[{"error": "No MUQL query specified"}],
            )

        engine = MUQLEngine(mubase)
        result = engine.execute(muql)

        if not result.is_success:
            return EvaluationResult(
                passed=False,
                details=[{"error": result.error}],
            )

        # Check expectation
        # For MAX/MIN with aggregates, check first row value
        result_value = None
        if expect.type in (ExpectationType.MAX, ExpectationType.MIN):
            if result.rows and len(result.rows[0]) > 0:
                try:
                    result_value = int(result.rows[0][0])
                except (ValueError, TypeError):
                    pass

        passed = check_expectation(result.row_count, expect, result_value)

        # Convert rows to details
        details = result.as_dicts()

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=result.row_count,
        )
```

**Acceptance Criteria**:
- [ ] Executes MUQL query via MUQLEngine
- [ ] Handles query errors gracefully (returns passed=False with error detail)
- [ ] Checks expectation for EMPTY, NOT_EMPTY, COUNT, MAX, MIN
- [ ] For MAX/MIN, extracts value from first row first column
- [ ] Converts query rows to details list
- [ ] Unit tests with mock MUbase and various expectations

---

#### Task 3.3: Implement AnalyzeRuleEvaluator

**Priority**: P1 (Analysis rules)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/rules.py` (modify)

**Pattern**: Follow `kernel/muql/executor.py:361-517` for analysis methods

**Dependencies**: Task 3.1 (protocol)

**Description**: Implement evaluator for built-in analysis rules (circular, complexity, coupling).

**Implementation Notes**:
```python
class AnalyzeRuleEvaluator:
    """Evaluate built-in analysis rules."""

    @property
    def rule_type(self) -> str:
        return "analyze"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        analysis = rule.params.get("analysis", "")

        match analysis:
            case "circular":
                return self._analyze_circular(mubase, expect)
            case "complexity":
                threshold = rule.params.get("threshold", 500)
                return self._analyze_complexity(mubase, expect, threshold)
            case "coupling":
                threshold = rule.params.get("threshold", 20)
                return self._analyze_coupling(mubase, expect, threshold)
            case "unused":
                return self._analyze_unused(mubase, expect)
            case _:
                return EvaluationResult(
                    passed=False,
                    details=[{"error": f"Unknown analysis type: {analysis}"}],
                )

    def _analyze_circular(
        self,
        mubase: MUbase,
        expect: Expectation,
    ) -> EvaluationResult:
        # Use SQL to find bidirectional import edges
        sql = """
            SELECT DISTINCT e1.source_id, e1.target_id
            FROM edges e1
            JOIN edges e2 ON e1.source_id = e2.target_id
                         AND e1.target_id = e2.source_id
            WHERE e1.type = 'imports'
            LIMIT 50
        """
        cursor = mubase.conn.execute(sql)
        rows = cursor.fetchall()

        details = [{"from": r[0], "to": r[1]} for r in rows]
        passed = check_expectation(len(details), expect)

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=len(details),
        )

    def _analyze_complexity(
        self,
        mubase: MUbase,
        expect: Expectation,
        threshold: int,
    ) -> EvaluationResult:
        sql = """
            SELECT name, type, path, complexity
            FROM nodes
            WHERE complexity > ?
            ORDER BY complexity DESC
            LIMIT 100
        """
        cursor = mubase.conn.execute(sql, [threshold])
        rows = cursor.fetchall()

        details = [
            {"name": r[0], "type": r[1], "path": r[2], "complexity": r[3]}
            for r in rows
        ]
        passed = check_expectation(len(details), expect)

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=len(details),
        )

    # Similar methods for coupling, unused...
```

**Acceptance Criteria**:
- [ ] Supports analysis types: circular, complexity, coupling, unused
- [ ] Circular detection finds bidirectional import edges
- [ ] Complexity finds nodes exceeding threshold
- [ ] Coupling finds modules with high dependency counts
- [ ] Unused finds nodes with no dependents
- [ ] All use parameterized SQL (no injection risk)
- [ ] Unit tests for each analysis type

---

#### Task 3.4: Implement DependencyRuleEvaluator

**Priority**: P1 (Architecture rules)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/rules.py` (modify)

**Pattern**: Use glob pattern matching on file paths

**Dependencies**: Task 3.1 (protocol)

**Description**: Implement evaluator for "A should not depend on B" dependency rules.

**Implementation Notes**:
```python
from fnmatch import fnmatch

class DependencyRuleEvaluator:
    """Evaluate dependency restriction rules."""

    @property
    def rule_type(self) -> str:
        return "dependency"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        from_pattern = rule.params.get("from", "")
        to_pattern = rule.params.get("to", "")

        if not from_pattern or not to_pattern:
            return EvaluationResult(
                passed=False,
                details=[{"error": "Dependency rule requires 'from' and 'to' patterns"}],
            )

        # Find all import edges
        sql = """
            SELECT
                s.path as source_path,
                s.name as source_name,
                t.path as target_path,
                t.name as target_name
            FROM edges e
            JOIN nodes s ON e.source_id = s.id
            JOIN nodes t ON e.target_id = t.id
            WHERE e.type = 'imports'
        """
        cursor = mubase.conn.execute(sql)
        rows = cursor.fetchall()

        # Filter by patterns
        violations = []
        for row in rows:
            source_path = row[0] or ""
            target_path = row[2] or ""

            if fnmatch(source_path, from_pattern) and fnmatch(target_path, to_pattern):
                violations.append({
                    "from": f"{row[1]} ({source_path})",
                    "to": f"{row[3]} ({target_path})",
                    "source_path": source_path,
                    "target_path": target_path,
                })

        passed = check_expectation(len(violations), expect)

        return EvaluationResult(
            passed=passed,
            details=violations,
            row_count=len(violations),
        )
```

**Acceptance Criteria**:
- [ ] Accepts glob patterns for `from` and `to` paths
- [ ] Finds IMPORTS edges matching both patterns
- [ ] Returns violation details with source and target info
- [ ] Handles missing patterns gracefully
- [ ] Uses `fnmatch` for glob pattern matching
- [ ] Unit tests with sample graph and patterns

---

#### Task 3.5: Implement PatternRuleEvaluator

**Priority**: P2 (Convention enforcement)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/rules.py` (modify)

**Pattern**: Query nodes and check properties

**Dependencies**: Task 3.1 (protocol)

**Description**: Implement evaluator for "all X must have Y" pattern rules.

**Implementation Notes**:
```python
class PatternRuleEvaluator:
    """Evaluate pattern-based rules (all X must have Y)."""

    @property
    def rule_type(self) -> str:
        return "pattern"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        match_pattern = rule.params.get("match")
        node_type = rule.params.get("node_type", "").lower()
        name_pattern = rule.params.get("name_pattern")
        must_have = rule.params.get("must_have", {})

        # Build query to find matching nodes
        conditions = []
        params = []

        if match_pattern:
            conditions.append("path LIKE ?")
            params.append(match_pattern.replace("*", "%"))

        if node_type:
            conditions.append("type = ?")
            params.append(node_type)

        if name_pattern:
            conditions.append("name LIKE ?")
            params.append(name_pattern.replace("*", "%"))

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT id, name, type, path, properties FROM nodes WHERE {where}"

        cursor = mubase.conn.execute(sql, params)
        rows = cursor.fetchall()

        # Check must_have requirements
        violations = []
        for row in rows:
            node_id, name, node_type_val, path, props_json = row

            # Parse properties
            import json
            try:
                props = json.loads(props_json) if props_json else {}
            except json.JSONDecodeError:
                props = {}

            # Check required decorator
            if "decorator" in must_have:
                required_decorator = must_have["decorator"]
                decorators = props.get("decorators", [])
                if required_decorator not in decorators:
                    violations.append({
                        "node": name,
                        "path": path,
                        "type": node_type_val,
                        "missing": f"decorator {required_decorator}",
                    })

            # Check required annotation
            if "annotation" in must_have:
                required_annotation = must_have["annotation"]
                annotations = props.get("annotations", [])
                if required_annotation not in annotations:
                    violations.append({
                        "node": name,
                        "path": path,
                        "type": node_type_val,
                        "missing": f"annotation {required_annotation}",
                    })

        passed = check_expectation(len(violations), expect)

        return EvaluationResult(
            passed=passed,
            details=violations,
            row_count=len(violations),
        )
```

**Acceptance Criteria**:
- [ ] Filters nodes by path pattern, node_type, name_pattern
- [ ] Checks `must_have.decorator` against node properties
- [ ] Checks `must_have.annotation` against node properties
- [ ] Reports missing requirements in violation details
- [ ] Converts glob patterns to SQL LIKE patterns
- [ ] Unit tests for decorator and annotation checks

---

### Story 7.5: Contract Verification Engine

#### Task 4.1: Implement ContractVerifier

**Priority**: P0 (Core engine)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/verifier.py` (new)

**Pattern**: Follow `kernel/export/base.py:130-210` ExportManager pattern

**Dependencies**: Tasks 3.1-3.5 (all evaluators)

**Description**: Create contract verification engine that orchestrates rule evaluation.

**Implementation Notes**:
```python
from __future__ import annotations

from typing import TYPE_CHECKING

from mu.contracts.models import (
    Contract, ContractFile, Severity, Verification Result, Violation
)
from mu.contracts.rules import (
    AnalyzeRuleEvaluator, DependencyRuleEvaluator,
    PatternRuleEvaluator, QueryRuleEvaluator, RuleEvaluator
)

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase

class ContractVerifier:
    """Verify contracts against MUbase graph."""

    def __init__(self, mubase: MUbase) -> None:
        self._mubase = mubase
        self._evaluators: dict[str, RuleEvaluator] = {
            "query": QueryRuleEvaluator(),
            "analyze": AnalyzeRuleEvaluator(),
            "dependency": DependencyRuleEvaluator(),
            "pattern": PatternRuleEvaluator(),
        }

    def register_evaluator(self, evaluator: RuleEvaluator) -> None:
        """Register a custom rule evaluator."""
        self._evaluators[evaluator.rule_type] = evaluator

    def verify(
        self,
        contracts: ContractFile,
        fail_fast: bool = False,
    ) -> VerificationResult:
        """Verify all contracts.

        Args:
            contracts: Parsed contract file
            fail_fast: Stop on first error-level violation

        Returns:
            VerificationResult with all violations
        """
        all_violations: list[Violation] = []
        checked = 0

        for contract in contracts.contracts:
            if not contract.enabled:
                continue

            # Skip if matches exclude patterns
            if self._should_skip(contract, contracts.settings):
                continue

            checked += 1

            # Get evaluator
            evaluator = self._evaluators.get(contract.rule.type.value)
            if evaluator is None:
                violation = Violation(
                    contract=contract,
                    message=f"Unknown rule type: {contract.rule.type.value}",
                    details=[],
                )
                all_violations.append(violation)
                continue

            # Evaluate
            try:
                result = evaluator.evaluate(
                    self._mubase,
                    contract.rule,
                    contract.expect
                )
            except Exception as e:
                violation = Violation(
                    contract=contract,
                    message=f"Evaluation error: {e}",
                    details=[],
                )
                all_violations.append(violation)
                continue

            if not result.passed:
                violation = Violation(
                    contract=contract,
                    message=f"Contract violated: {contract.name}",
                    details=result.details,
                )
                all_violations.append(violation)

                if fail_fast and contract.severity == Severity.ERROR:
                    break

        # Categorize violations
        errors = [v for v in all_violations if v.contract.severity == Severity.ERROR]
        warnings = [v for v in all_violations if v.contract.severity == Severity.WARNING]
        infos = [v for v in all_violations if v.contract.severity == Severity.INFO]

        # Determine pass/fail
        passed = len(errors) == 0
        if contracts.settings.fail_on_warning:
            passed = passed and len(warnings) == 0

        return VerificationResult(
            passed=passed,
            contracts_checked=checked,
            violations=errors,
            warnings=warnings,
            info=infos,
        )

    def _should_skip(self, contract: Contract, settings: ContractSettings) -> bool:
        """Check if contract should be skipped based on settings."""
        # Future: implement exclude pattern matching
        return False
```

**Acceptance Criteria**:
- [ ] `verify()` iterates all enabled contracts
- [ ] Uses correct evaluator based on rule type
- [ ] Catches and reports evaluation errors as violations
- [ ] Supports `fail_fast` option for early exit
- [ ] Categorizes violations by severity (error/warning/info)
- [ ] `passed` respects `fail_on_warning` setting
- [ ] `register_evaluator()` allows custom evaluators
- [ ] Unit tests with mock contracts and evaluators

---

### Story 7.5-7.6: Reporters and CLI

#### Task 5.1: Implement ContractReporter

**Priority**: P1 (Output formatting)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/reporter.py` (new)

**Pattern**: Follow epic specification reporter design

**Dependencies**: Task 4.1 (verifier)

**Description**: Generate text, JSON, and JUnit XML reports from verification results.

**Implementation Notes**:
```python
from __future__ import annotations

import json
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from mu.contracts.models import Severity, VerificationResult, Violation

class ContractReporter:
    """Generate verification reports in various formats."""

    def report_text(self, result: VerificationResult, no_color: bool = False) -> str:
        """Generate human-readable text report."""
        lines = []

        # Status header
        status = "PASSED" if result.passed else "FAILED"
        if not no_color:
            status_color = "\033[32m" if result.passed else "\033[31m"
            reset = "\033[0m"
            status = f"{status_color}{status}{reset}"

        lines.append(f"Contract Verification: {status}")
        lines.append(f"Checked: {result.contracts_checked} contracts")
        lines.append("")

        # Errors
        if result.violations:
            lines.append(f"ERRORS ({len(result.violations)}):")
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
            lines.append(f"WARNINGS ({len(result.warnings)}):")
            for v in result.warnings:
                lines.append(f"  ! {v.contract.name}")
                for detail in v.details[:3]:
                    lines.append(f"    - {self._format_detail(detail)}")
            lines.append("")

        # Summary
        lines.append("Summary:")
        lines.append(f"  Errors: {len(result.violations)}")
        lines.append(f"  Warnings: {len(result.warnings)}")

        return "\n".join(lines)

    def report_json(self, result: VerificationResult) -> str:
        """Generate JSON report."""
        return json.dumps(result.to_dict(), indent=2)

    def report_junit(self, result: VerificationResult) -> str:
        """Generate JUnit XML report for CI integration."""
        testsuite = Element("testsuite", {
            "name": "MU Contracts",
            "tests": str(result.contracts_checked),
            "failures": str(len(result.violations)),
            "warnings": str(len(result.warnings)),
        })

        # Add test cases for failures
        for v in result.violations:
            testcase = SubElement(testsuite, "testcase", {
                "name": v.contract.name,
                "classname": "mu.contracts",
            })
            failure = SubElement(testcase, "failure", {
                "message": v.message,
                "type": v.contract.severity.value,
            })
            failure.text = json.dumps(v.details)

        # Add test cases for warnings (as skipped or separate)
        for v in result.warnings:
            testcase = SubElement(testsuite, "testcase", {
                "name": v.contract.name,
                "classname": "mu.contracts",
            })
            # Use <error> or custom element for warnings
            warning = SubElement(testcase, "system-out")
            warning.text = f"WARNING: {v.message}\n{json.dumps(v.details)}"

        return tostring(testsuite, encoding="unicode")

    def _format_detail(self, detail: dict[str, Any]) -> str:
        """Format a single violation detail."""
        if "from" in detail and "to" in detail:
            return f"{detail['from']} -> {detail['to']}"
        elif "node" in detail and "missing" in detail:
            path = detail.get('path', '')
            return f"{detail['node']} ({path}) - missing {detail['missing']}"
        elif "error" in detail:
            return f"Error: {detail['error']}"
        elif "name" in detail:
            path = detail.get('path', '')
            complexity = detail.get('complexity', '')
            return f"{detail['name']} ({path})" + (f" complexity={complexity}" if complexity else "")
        else:
            return str(detail)
```

**Acceptance Criteria**:
- [ ] `report_text()` generates human-readable output with symbols
- [ ] Text output supports `no_color` flag for CI
- [ ] Limits detail output (5 for errors, 3 for warnings)
- [ ] `report_json()` generates structured JSON
- [ ] `report_junit()` generates valid JUnit XML
- [ ] JUnit format compatible with CI test reporters
- [ ] Unit tests for all output formats

---

#### Task 5.2: Add CLI Contract Commands

**Priority**: P0 (User interface)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py` (modify)

**Pattern**: Follow `cli.py:2326-2567` daemon command group

**Dependencies**: Tasks 2.2 (parser), 4.1 (verifier), 5.1 (reporter)

**Description**: Add `mu contracts verify` and `mu contracts init` CLI commands.

**Implementation Notes**:
```python
# Add after daemon commands in cli.py

@cli.group()
def contracts() -> None:
    """MU Contracts - Architecture verification.

    Define and verify architectural rules against the codebase graph.

    \\b
    Examples:
        mu contracts verify           # Verify contracts
        mu contracts init            # Create template file
        mu contracts verify --format json
    """
    pass

@contracts.command("verify")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--contract-file", "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Contract file (default: .mu-contracts.yml)",
)
@click.option(
    "--format", "-f",
    "output_format",
    type=click.Choice(["text", "json", "junit"]),
    default="text",
    help="Output format",
)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("--fail-fast", is_flag=True, help="Stop on first error")
@click.option("--only", type=str, help="Only run contracts matching pattern")
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    help="Output file (default: stdout)",
)
def contracts_verify(
    path: Path,
    contract_file: Path | None,
    output_format: str,
    no_color: bool,
    fail_fast: bool,
    only: str | None,
    output: Path | None,
) -> None:
    """Verify architectural contracts against codebase.

    Loads contracts from .mu-contracts.yml (or specified file) and
    verifies them against the MUbase graph database.

    \\b
    Examples:
        mu contracts verify .
        mu contracts verify . --format junit > report.xml
        mu contracts verify . --only "No circular*"
    """
    from mu.kernel import MUbase
    from mu.contracts.parser import parse_contracts_file, ContractParseError
    from mu.contracts.verifier import ContractVerifier
    from mu.contracts.reporter import ContractReporter

    # Find .mubase
    mubase_path = path.resolve() / ".mubase"
    if not mubase_path.exists():
        print_error(f"No .mubase found at {mubase_path}")
        print_info("Run 'mu kernel build' first to create the graph database")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Find contract file
    if contract_file is None:
        contract_file = path.resolve() / ".mu-contracts.yml"

    if not contract_file.exists():
        print_error(f"Contract file not found: {contract_file}")
        print_info("Run 'mu contracts init' to create a template")
        sys.exit(ExitCode.CONFIG_ERROR)

    # Parse contracts
    try:
        contracts = parse_contracts_file(contract_file)
    except ContractParseError as e:
        print_error(f"Failed to parse contracts: {e}")
        sys.exit(ExitCode.CONFIG_ERROR)

    print_info(f"Loaded {len(contracts.contracts)} contracts from {contract_file.name}")

    # Filter by --only pattern
    if only:
        from fnmatch import fnmatch
        contracts.contracts = [c for c in contracts.contracts if fnmatch(c.name, only)]
        print_info(f"Filtered to {len(contracts.contracts)} contracts matching '{only}'")

    # Verify
    db = MUbase(mubase_path)
    try:
        verifier = ContractVerifier(db)
        result = verifier.verify(contracts, fail_fast=fail_fast)
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

@contracts.command("init")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing file")
def contracts_init(path: Path, force: bool) -> None:
    """Create a template .mu-contracts.yml file.

    Creates a contract file with example rules that you can customize.
    """
    contract_path = path.resolve() / ".mu-contracts.yml"

    if contract_path.exists() and not force:
        print_warning(f"Contract file already exists: {contract_path}")
        print_info("Use --force to overwrite")
        sys.exit(ExitCode.CONFIG_ERROR)

    template = '''# MU Contracts - Architecture Rules
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
        SELECT name, path, complexity
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
'''

    contract_path.write_text(template)
    print_success(f"Created {contract_path}")
    print_info("\nNext steps:")
    print_info("  1. Edit .mu-contracts.yml to add your rules")
    print_info("  2. Run 'mu contracts verify' to check contracts")
```

**Acceptance Criteria**:
- [ ] `mu contracts verify` command with path argument
- [ ] `--contract-file` option to specify custom file
- [ ] `--format` option for text/json/junit output
- [ ] `--no-color` flag for CI environments
- [ ] `--fail-fast` flag for early exit
- [ ] `--only` filter for specific contracts
- [ ] `--output` option for file output
- [ ] Non-zero exit code on violations
- [ ] `mu contracts init` creates template file
- [ ] Template includes commented examples
- [ ] Error messages guide user to solutions

---

#### Task 5.3: Add CONTRACT_VIOLATION Exit Code

**Priority**: P0 (Required for CLI)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/errors.py` (modify)

**Pattern**: Follow existing ExitCode enum

**Dependencies**: None

**Description**: Add exit code for contract violations.

**Implementation Notes**:
```python
# Add to ExitCode enum in errors.py
CONTRACT_VIOLATION = 3  # Architecture contract violation
```

**Acceptance Criteria**:
- [ ] `ExitCode.CONTRACT_VIOLATION` added with value 3
- [ ] Documented in enum docstring
- [ ] Used by `contracts verify` command

---

### Story 7.6: Testing and Documentation

#### Task 6.1: Write Unit Tests for Contracts Module

**Priority**: P1 (Quality)
**Complexity**: Large
**Files**:
- `/Users/imu/Dev/work/mu/tests/unit/test_contracts.py` (new)

**Pattern**: Follow `tests/unit/test_export.py` organization

**Dependencies**: All previous tasks

**Description**: Comprehensive unit tests for contract parsing, evaluation, and verification.

**Implementation Notes**:
```python
"""Tests for MU Contracts - Architecture verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mu.kernel import MUbase, Node, NodeType, Edge, EdgeType
from mu.contracts.models import (
    Contract, ContractFile, ContractSettings, Expectation, ExpectationType,
    Rule, RuleType, Severity, VerificationResult, Violation
)
from mu.contracts.parser import (
    ContractParseError, parse_contracts, parse_contracts_file
)
from mu.contracts.rules import (
    AnalyzeRuleEvaluator, DependencyRuleEvaluator,
    PatternRuleEvaluator, QueryRuleEvaluator, check_expectation
)
from mu.contracts.verifier import ContractVerifier
from mu.contracts.reporter import ContractReporter

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.mubase"

@pytest.fixture
def db(db_path: Path) -> MUbase:
    database = MUbase(db_path)
    yield database
    database.close()

@pytest.fixture
def populated_db(db: MUbase) -> MUbase:
    # Add sample nodes for testing
    db.add_node(Node(
        id="mod:src/services/user.py",
        type=NodeType.MODULE,
        name="user",
        file_path="src/services/user.py",
    ))
    db.add_node(Node(
        id="mod:src/controllers/api.py",
        type=NodeType.MODULE,
        name="api",
        file_path="src/controllers/api.py",
    ))
    db.add_node(Node(
        id="fn:src/services/user.py:process",
        type=NodeType.FUNCTION,
        name="process",
        file_path="src/services/user.py",
        complexity=600,
    ))
    # Add edge
    db.add_edge(Edge(
        id="edge:1",
        type=EdgeType.IMPORTS,
        source_id="mod:src/services/user.py",
        target_id="mod:src/controllers/api.py",
    ))
    return db

@pytest.fixture
def sample_contract_yaml() -> str:
    return '''
version: "1.0"
name: "Test Contracts"
settings:
  fail_on_warning: true
contracts:
  - name: "Test Query Rule"
    description: "Find complex functions"
    severity: error
    rule:
      type: query
      muql: "SELECT * FROM functions WHERE complexity > 500"
    expect: empty
'''

# =============================================================================
# Parser Tests
# =============================================================================

class TestContractParser:
    def test_parse_minimal_contract(self):
        yaml = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT * FROM functions"
    expect: empty
'''
        result = parse_contracts(yaml)
        assert len(result.contracts) == 1
        assert result.contracts[0].name == "Test"
        assert result.contracts[0].severity == Severity.ERROR  # default

    def test_parse_all_rule_types(self):
        yaml = '''
contracts:
  - name: "Query"
    rule:
      type: query
      muql: "SELECT * FROM functions"
    expect: empty
  - name: "Analyze"
    rule:
      type: analyze
      analysis: circular
    expect: empty
  - name: "Dependency"
    rule:
      type: dependency
      from: "src/a/**"
      to: "src/b/**"
    expect: empty
  - name: "Pattern"
    rule:
      type: pattern
      match: "src/**"
      must_have:
        decorator: "@inject"
    expect: empty
'''
        result = parse_contracts(yaml)
        assert len(result.contracts) == 4
        assert result.contracts[0].rule.type == RuleType.QUERY
        assert result.contracts[1].rule.type == RuleType.ANALYZE
        assert result.contracts[2].rule.type == RuleType.DEPENDENCY
        assert result.contracts[3].rule.type == RuleType.PATTERN

    def test_parse_expectation_shorthand(self):
        yaml = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT 1"
    expect: not_empty
'''
        result = parse_contracts(yaml)
        assert result.contracts[0].expect.type == ExpectationType.NOT_EMPTY

    def test_parse_expectation_max(self):
        yaml = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT COUNT(*)"
    expect:
      max: 10
'''
        result = parse_contracts(yaml)
        assert result.contracts[0].expect.type == ExpectationType.MAX
        assert result.contracts[0].expect.value == 10

    def test_parse_error_missing_name(self):
        yaml = '''
contracts:
  - rule:
      type: query
      muql: "SELECT 1"
'''
        with pytest.raises(ContractParseError, match="Missing required field: name"):
            parse_contracts(yaml)

    def test_parse_error_invalid_yaml(self):
        yaml = "{{invalid yaml"
        with pytest.raises(ContractParseError, match="Invalid YAML"):
            parse_contracts(yaml)

# =============================================================================
# Evaluator Tests
# =============================================================================

class TestCheckExpectation:
    def test_empty_with_zero_results(self):
        assert check_expectation(0, Expectation(ExpectationType.EMPTY)) is True

    def test_empty_with_results(self):
        assert check_expectation(5, Expectation(ExpectationType.EMPTY)) is False

    def test_not_empty_with_results(self):
        assert check_expectation(5, Expectation(ExpectationType.NOT_EMPTY)) is True

    def test_max_within_limit(self):
        assert check_expectation(5, Expectation(ExpectationType.MAX, 10)) is True

    def test_max_exceeds_limit(self):
        assert check_expectation(15, Expectation(ExpectationType.MAX, 10)) is False

class TestQueryRuleEvaluator:
    def test_evaluate_empty_result(self, populated_db):
        evaluator = QueryRuleEvaluator()
        rule = Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions WHERE name = 'nonexistent'"})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is True
        assert result.row_count == 0

    def test_evaluate_finds_violations(self, populated_db):
        evaluator = QueryRuleEvaluator()
        rule = Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions WHERE complexity > 500"})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is False
        assert result.row_count >= 1

class TestDependencyRuleEvaluator:
    def test_finds_forbidden_dependency(self, populated_db):
        evaluator = DependencyRuleEvaluator()
        rule = Rule(RuleType.DEPENDENCY, {
            "from": "src/services/*",
            "to": "src/controllers/*",
        })
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is False
        assert len(result.details) >= 1

# =============================================================================
# Verifier Tests
# =============================================================================

class TestContractVerifier:
    def test_verify_all_pass(self, populated_db):
        contracts = ContractFile(contracts=[
            Contract(
                name="Safe Query",
                description="",
                severity=Severity.ERROR,
                rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions WHERE name = 'xyz'"}),
                expect=Expectation(ExpectationType.EMPTY),
            )
        ])

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        assert result.passed is True
        assert len(result.violations) == 0

    def test_verify_with_violation(self, populated_db):
        contracts = ContractFile(contracts=[
            Contract(
                name="Complexity Check",
                description="",
                severity=Severity.ERROR,
                rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions WHERE complexity > 500"}),
                expect=Expectation(ExpectationType.EMPTY),
            )
        ])

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        assert result.passed is False
        assert len(result.violations) >= 1

    def test_verify_skips_disabled(self, populated_db):
        contracts = ContractFile(contracts=[
            Contract(
                name="Disabled Contract",
                description="",
                severity=Severity.ERROR,
                rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions"}),
                expect=Expectation(ExpectationType.EMPTY),
                enabled=False,
            )
        ])

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        assert result.contracts_checked == 0

# =============================================================================
# Reporter Tests
# =============================================================================

class TestContractReporter:
    def test_report_text_passed(self):
        result = VerificationResult(passed=True, contracts_checked=5)
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=True)

        assert "PASSED" in output
        assert "Checked: 5 contracts" in output

    def test_report_json(self):
        result = VerificationResult(passed=False, contracts_checked=3)
        reporter = ContractReporter()
        output = reporter.report_json(result)

        data = json.loads(output)
        assert data["passed"] is False
        assert data["contracts_checked"] == 3

    def test_report_junit(self):
        contract = Contract(
            name="Test",
            description="",
            severity=Severity.ERROR,
            rule=Rule(RuleType.QUERY, {}),
            expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(contract=contract, message="Failed", details=[])
        result = VerificationResult(
            passed=False,
            contracts_checked=1,
            violations=[violation],
        )

        reporter = ContractReporter()
        output = reporter.report_junit(result)

        assert "<testsuite" in output
        assert 'name="Test"' in output
        assert "<failure" in output
```

**Acceptance Criteria**:
- [ ] Parser tests for all rule types and expectations
- [ ] Parser error tests for invalid input
- [ ] Evaluator tests for each rule type
- [ ] Verifier tests for pass/fail scenarios
- [ ] Reporter tests for all output formats
- [ ] Tests use populated_db fixture with sample data
- [ ] All tests pass with `pytest tests/unit/test_contracts.py`

---

#### Task 6.2: Create Contracts CLAUDE.md Documentation

**Priority**: P2 (Developer docs)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/contracts/CLAUDE.md` (new)

**Pattern**: Follow `src/mu/daemon/CLAUDE.md`

**Dependencies**: All previous tasks

**Description**: Create comprehensive module documentation.

**Acceptance Criteria**:
- [ ] Architecture overview with file purposes
- [ ] Contract file format specification
- [ ] Rule type documentation with examples
- [ ] Expectation type reference
- [ ] CLI usage examples
- [ ] CI integration examples (GitHub Actions, GitLab CI)
- [ ] Extension points (custom evaluators)
- [ ] Anti-patterns section
- [ ] Testing instructions

---

## Dependencies Graph

```
Task 1.1 (Models)
    |
    +-- Task 1.2 (ContractFile) --> Task 2.2 (Parser)
    |
    +-- Task 3.1 (RuleEvaluator Protocol)
            |
            +-- Task 3.2 (QueryRuleEvaluator)
            +-- Task 3.3 (AnalyzeRuleEvaluator)
            +-- Task 3.4 (DependencyRuleEvaluator)
            +-- Task 3.5 (PatternRuleEvaluator)
                    |
                    v
            Task 4.1 (ContractVerifier)
                    |
                    +-- Task 5.1 (ContractReporter)
                            |
                            v
                    Task 5.2 (CLI Commands) <-- Task 5.3 (Exit Code)
                            |
                            v
                    Task 6.1 (Tests)
                    Task 6.2 (Documentation)

Task 2.1 (PyYAML) --> Task 2.2 (Parser)
```

---

## Implementation Order

**Phase 1: Foundation (Tasks 1.1, 1.2, 2.1, 2.2)**
1. Task 1.1: Core models (Contract, Rule, Violation, etc.)
2. Task 1.2: ContractFile and settings models
3. Task 2.1: Add PyYAML dependency
4. Task 2.2: YAML contract parser

**Phase 2: Rule Evaluators (Tasks 3.1-3.5)**
5. Task 3.1: RuleEvaluator protocol and helpers
6. Task 3.2: QueryRuleEvaluator (MUQL queries)
7. Task 3.3: AnalyzeRuleEvaluator (built-in analysis)
8. Task 3.4: DependencyRuleEvaluator (A->B rules)
9. Task 3.5: PatternRuleEvaluator (must_have rules)

**Phase 3: Verification Engine (Tasks 4.1, 5.1)**
10. Task 4.1: ContractVerifier orchestration
11. Task 5.1: ContractReporter (text/JSON/JUnit)

**Phase 4: CLI Integration (Tasks 5.2, 5.3)**
12. Task 5.3: Add CONTRACT_VIOLATION exit code
13. Task 5.2: CLI commands (verify, init)

**Phase 5: Quality (Tasks 6.1, 6.2)**
14. Task 6.1: Comprehensive unit tests
15. Task 6.2: CLAUDE.md documentation

---

## Edge Cases

1. **Empty contract file**: Valid but no contracts checked
2. **All contracts disabled**: Return passed=True, checked=0
3. **MUQL syntax error**: Report as violation with error detail
4. **Missing .mubase**: Clear error with "run kernel build" hint
5. **Circular dependency in self**: A imports A (edge case)
6. **Glob pattern edge cases**: `**` vs `*`, trailing slashes
7. **Large violation count**: Limit details in output
8. **Non-UTF8 contract file**: Handle encoding errors
9. **Concurrent access**: MUbase is SQLite, handle locking
10. **Empty MUQL result for MAX/MIN**: Handle gracefully

---

## Security Considerations

1. **YAML parsing**: Use `yaml.safe_load()` only (no code execution)
2. **MUQL injection**: MUQL parser validates syntax, but parameterize where possible
3. **Path traversal**: Validate contract file path is within project
4. **Large files**: Limit contract file size to prevent DoS
5. **Recursive patterns**: Limit glob recursion depth

---

## Performance Considerations

1. **Query caching**: MUQL queries may be repeated - consider caching
2. **Batch evaluation**: Could parallelize independent contract checks
3. **Large codebases**: Limit detail output, use pagination
4. **Graph traversal**: Use indexed queries for dependency checks
5. **Target latency**: Full verification < 30 seconds for typical codebase
