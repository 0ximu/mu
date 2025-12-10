# Epic 7: MU Contracts

**Priority**: P3 - Architecture verification and enforcement
**Dependencies**: MUQL Parser (Epic 2)
**Estimated Complexity**: Medium
**PRD Reference**: Section 3.1

---

## Overview

MU Contracts enable declarative architecture rules that are verified against the graph. Define what dependencies are allowed, enforce complexity limits, and prevent architectural drift.

## Goals

1. Define architectural rules in YAML
2. Verify rules against MUbase graph
3. Integrate with CI/CD pipelines
4. Provide clear violation reports

---

## User Stories

### Story 7.1: Contract Definition
**As an** architect
**I want** to define rules in YAML
**So that** architectural decisions are codified

**Acceptance Criteria**:
- [ ] `.mu-contracts.yml` file format
- [ ] Support query-based rules
- [ ] Support pattern-based rules
- [ ] Severity levels (error, warning, info)

### Story 7.2: Dependency Rules
**As an** architect
**I want** to enforce dependency rules
**So that** layer violations are caught

**Acceptance Criteria**:
- [ ] "A should not depend on B" rules
- [ ] Module/package-level constraints
- [ ] Allowed exception lists
- [ ] Clear violation messages

### Story 7.3: Complexity Rules
**As a** tech lead
**I want** complexity limits
**So that** code stays maintainable

**Acceptance Criteria**:
- [ ] Max complexity per function/class
- [ ] Module-level thresholds
- [ ] Trend detection (increasing complexity)
- [ ] Exclusion patterns

### Story 7.4: Pattern Rules
**As an** architect
**I want** to enforce patterns
**So that** conventions are followed

**Acceptance Criteria**:
- [ ] "All X must have Y" rules
- [ ] Decorator/annotation requirements
- [ ] Naming convention enforcement
- [ ] Interface implementation checks

### Story 7.5: Contract Verification
**As a** developer
**I want** to verify contracts
**So that** I catch violations early

**Acceptance Criteria**:
- [ ] `mu contracts verify` command
- [ ] Exit code for CI integration
- [ ] Detailed violation report
- [ ] Summary statistics

### Story 7.6: CI Integration
**As a** DevOps engineer
**I want** contracts in CI
**So that** violations block PRs

**Acceptance Criteria**:
- [ ] GitHub Actions example
- [ ] GitLab CI example
- [ ] Non-zero exit on errors
- [ ] JUnit XML output option

---

## Technical Design

### Contract File Format

```yaml
# .mu-contracts.yml

version: "1.0"
name: "MU Architecture Contracts"

# Global settings
settings:
  fail_on_warning: false
  exclude_tests: true
  exclude_patterns:
    - "**/test_*.py"
    - "**/__mocks__/**"

contracts:
  # Dependency rules
  - name: "No circular dependencies"
    description: "Prevent circular module dependencies"
    severity: error
    rule:
      type: analyze
      analysis: circular
    expect: empty

  - name: "Controllers don't access repositories directly"
    description: "Controllers must go through services"
    severity: error
    rule:
      type: query
      muql: |
        FIND functions
        IN "src/controllers/**"
        CALLING ANY IN "src/repositories/**"
    expect: empty

  - name: "Services don't import controllers"
    description: "Services should be UI-agnostic"
    severity: error
    rule:
      type: dependency
      from: "src/services/**"
      to: "src/controllers/**"
    expect: empty

  # Complexity rules
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

  - name: "Module size limit"
    description: "Modules should not exceed 1000 lines"
    severity: warning
    rule:
      type: query
      muql: |
        SELECT name, properties->>'lines' as lines
        FROM modules
        WHERE CAST(properties->>'lines' AS INTEGER) > 1000
    expect: empty

  # Pattern rules
  - name: "All services are injectable"
    description: "Service classes must have @injectable decorator"
    severity: error
    rule:
      type: pattern
      match: "src/services/**/*.py"
      node_type: CLASS
      name_pattern: "*Service"
      must_have:
        decorator: "@injectable"

  - name: "Repositories implement interface"
    description: "All repositories must implement Repository interface"
    severity: error
    rule:
      type: query
      muql: |
        FIND classes
        IN "src/repositories/**"
        WHERE name LIKE '%Repository'
        AND NOT IMPLEMENTING Repository
    expect: empty

  - name: "API handlers have error handling"
    description: "API handlers should use @handle_errors decorator"
    severity: warning
    rule:
      type: pattern
      match: "src/api/**/*.py"
      node_type: FUNCTION
      name_pattern: "handle_*"
      must_have:
        decorator: "@handle_errors"

  # Custom expectations
  - name: "Limited external dependencies"
    description: "Core module should have minimal dependencies"
    severity: warning
    rule:
      type: query
      muql: |
        SELECT COUNT(*) as count
        FROM edges
        WHERE source_id IN (SELECT id FROM modules WHERE file_path LIKE 'src/core/%')
        AND type = 'IMPORTS'
        AND target_id IN (SELECT id FROM nodes WHERE type = 'EXTERNAL')
    expect:
      max: 10
```

### File Structure

```
src/mu/contracts/
├── __init__.py          # Public API
├── parser.py            # YAML contract parser
├── rules.py             # Rule type implementations
├── verifier.py          # Contract verification engine
├── reporter.py          # Violation reporting
└── models.py            # Contract, Rule, Violation dataclasses
```

### Core Models

```python
from dataclasses import dataclass
from enum import Enum
from typing import Literal

class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Rule:
    """A single contract rule."""
    type: Literal["query", "analyze", "dependency", "pattern"]
    params: dict


@dataclass
class Expectation:
    """Expected outcome of a rule."""
    type: Literal["empty", "not_empty", "count", "max", "min"]
    value: int | None = None


@dataclass
class Contract:
    """A single architectural contract."""
    name: str
    description: str
    severity: Severity
    rule: Rule
    expect: Expectation
    enabled: bool = True


@dataclass
class ContractFile:
    """Parsed contract file."""
    version: str
    name: str
    settings: dict
    contracts: list[Contract]


@dataclass
class Violation:
    """A contract violation."""
    contract: Contract
    message: str
    details: list[dict]  # Specific violations
    file_path: str | None = None
    line: int | None = None


@dataclass
class VerificationResult:
    """Result of contract verification."""
    passed: bool
    contracts_checked: int
    violations: list[Violation]
    warnings: list[Violation]
    info: list[Violation]

    @property
    def error_count(self) -> int:
        return len([v for v in self.violations if v.contract.severity == Severity.ERROR])

    @property
    def warning_count(self) -> int:
        return len([v for v in self.violations if v.contract.severity == Severity.WARNING])
```

### Rule Implementations

```python
from abc import ABC, abstractmethod

class RuleEvaluator(ABC):
    """Base class for rule evaluators."""

    @abstractmethod
    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation
    ) -> tuple[bool, list[dict]]:
        """Evaluate rule and return (passed, details)."""
        ...


class QueryRuleEvaluator(RuleEvaluator):
    """Evaluate MUQL query rules."""

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation
    ) -> tuple[bool, list[dict]]:
        # Execute query
        result = mubase.query(rule.params["muql"])

        # Check expectation
        match expect.type:
            case "empty":
                passed = len(result.rows) == 0
            case "not_empty":
                passed = len(result.rows) > 0
            case "max":
                # Assume single row with count
                count = result.rows[0]["count"] if result.rows else 0
                passed = count <= expect.value
            case "min":
                count = result.rows[0]["count"] if result.rows else 0
                passed = count >= expect.value
            case "count":
                passed = len(result.rows) == expect.value

        details = [dict(zip(result.columns, row)) for row in result.rows]
        return passed, details


class AnalyzeRuleEvaluator(RuleEvaluator):
    """Evaluate analysis rules."""

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation
    ) -> tuple[bool, list[dict]]:
        analysis_type = rule.params["analysis"]

        match analysis_type:
            case "circular":
                cycles = mubase.find_circular_dependencies()
                passed = len(cycles) == 0 if expect.type == "empty" else len(cycles) > 0
                details = [{"cycle": c} for c in cycles]

            case "coupling":
                metrics = mubase.analyze_coupling()
                # Check against threshold
                ...

            case _:
                raise ValueError(f"Unknown analysis: {analysis_type}")

        return passed, details


class DependencyRuleEvaluator(RuleEvaluator):
    """Evaluate dependency rules."""

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation
    ) -> tuple[bool, list[dict]]:
        from_pattern = rule.params["from"]
        to_pattern = rule.params["to"]

        # Find violating edges
        violations = mubase.find_dependencies(from_pattern, to_pattern)

        passed = len(violations) == 0 if expect.type == "empty" else len(violations) > 0
        details = [
            {
                "from": v.source_name,
                "to": v.target_name,
                "file": v.file_path
            }
            for v in violations
        ]

        return passed, details


class PatternRuleEvaluator(RuleEvaluator):
    """Evaluate pattern rules."""

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation
    ) -> tuple[bool, list[dict]]:
        # Find matching nodes
        nodes = mubase.find_by_pattern(
            path_pattern=rule.params.get("match"),
            node_type=rule.params.get("node_type"),
            name_pattern=rule.params.get("name_pattern")
        )

        must_have = rule.params.get("must_have", {})
        violations = []

        for node in nodes:
            # Check required decorators
            if "decorator" in must_have:
                decorators = node.properties.get("decorators", [])
                if must_have["decorator"] not in decorators:
                    violations.append({
                        "node": node.name,
                        "file": node.file_path,
                        "missing": f"decorator {must_have['decorator']}"
                    })

            # Check required annotations
            # Check required implementations
            # etc.

        passed = len(violations) == 0 if expect.type == "empty" else len(violations) > 0
        return passed, violations
```

### Contract Verifier

```python
class ContractVerifier:
    """Verify contracts against MUbase."""

    evaluators: dict[str, RuleEvaluator] = {
        "query": QueryRuleEvaluator(),
        "analyze": AnalyzeRuleEvaluator(),
        "dependency": DependencyRuleEvaluator(),
        "pattern": PatternRuleEvaluator(),
    }

    def __init__(self, mubase: MUbase):
        self.mubase = mubase

    def verify(
        self,
        contracts: ContractFile,
        fail_fast: bool = False
    ) -> VerificationResult:
        """Verify all contracts."""
        violations = []

        for contract in contracts.contracts:
            if not contract.enabled:
                continue

            # Skip if excluded by settings
            if self._should_skip(contract, contracts.settings):
                continue

            # Evaluate rule
            evaluator = self.evaluators.get(contract.rule.type)
            if not evaluator:
                raise ValueError(f"Unknown rule type: {contract.rule.type}")

            passed, details = evaluator.evaluate(
                self.mubase,
                contract.rule,
                contract.expect
            )

            if not passed:
                violation = Violation(
                    contract=contract,
                    message=f"Contract violated: {contract.name}",
                    details=details
                )
                violations.append(violation)

                if fail_fast and contract.severity == Severity.ERROR:
                    break

        # Categorize by severity
        errors = [v for v in violations if v.contract.severity == Severity.ERROR]
        warnings = [v for v in violations if v.contract.severity == Severity.WARNING]
        infos = [v for v in violations if v.contract.severity == Severity.INFO]

        return VerificationResult(
            passed=len(errors) == 0,
            contracts_checked=len(contracts.contracts),
            violations=errors,
            warnings=warnings,
            info=infos
        )

    def _should_skip(self, contract: Contract, settings: dict) -> bool:
        """Check if contract should be skipped."""
        # Check exclude patterns
        # Check enabled flag
        return False
```

### Reporter

```python
class ContractReporter:
    """Generate violation reports."""

    def report_text(self, result: VerificationResult) -> str:
        """Generate text report."""
        lines = []

        # Header
        status = "PASSED" if result.passed else "FAILED"
        lines.append(f"Contract Verification: {status}")
        lines.append(f"Checked: {result.contracts_checked} contracts")
        lines.append("")

        # Errors
        if result.violations:
            lines.append(f"ERRORS ({len(result.violations)}):")
            for v in result.violations:
                lines.append(f"  ✗ {v.contract.name}")
                lines.append(f"    {v.contract.description}")
                for detail in v.details[:5]:  # Limit details
                    lines.append(f"    - {self._format_detail(detail)}")
                if len(v.details) > 5:
                    lines.append(f"    ... and {len(v.details) - 5} more")
            lines.append("")

        # Warnings
        if result.warnings:
            lines.append(f"WARNINGS ({len(result.warnings)}):")
            for v in result.warnings:
                lines.append(f"  ⚠ {v.contract.name}")
                for detail in v.details[:3]:
                    lines.append(f"    - {self._format_detail(detail)}")
            lines.append("")

        # Summary
        lines.append("Summary:")
        lines.append(f"  Errors: {result.error_count}")
        lines.append(f"  Warnings: {result.warning_count}")

        return "\n".join(lines)

    def report_json(self, result: VerificationResult) -> str:
        """Generate JSON report."""
        return json.dumps({
            "passed": result.passed,
            "contracts_checked": result.contracts_checked,
            "errors": [self._violation_to_dict(v) for v in result.violations],
            "warnings": [self._violation_to_dict(v) for v in result.warnings],
            "summary": {
                "errors": result.error_count,
                "warnings": result.warning_count
            }
        }, indent=2)

    def report_junit(self, result: VerificationResult) -> str:
        """Generate JUnit XML report for CI."""
        from xml.etree.ElementTree import Element, SubElement, tostring

        testsuite = Element("testsuite", {
            "name": "MU Contracts",
            "tests": str(result.contracts_checked),
            "failures": str(result.error_count),
        })

        for v in result.violations:
            testcase = SubElement(testsuite, "testcase", {
                "name": v.contract.name,
                "classname": "mu.contracts"
            })
            failure = SubElement(testcase, "failure", {
                "message": v.message,
                "type": v.contract.severity.value
            })
            failure.text = json.dumps(v.details)

        return tostring(testsuite, encoding="unicode")

    def _format_detail(self, detail: dict) -> str:
        """Format a single violation detail."""
        if "from" in detail and "to" in detail:
            return f"{detail['from']} → {detail['to']} ({detail.get('file', '')})"
        elif "node" in detail:
            return f"{detail['node']} in {detail.get('file', '')} - {detail.get('missing', '')}"
        elif "cycle" in detail:
            return " → ".join(detail["cycle"])
        else:
            return str(detail)
```

---

## Implementation Plan

### Phase 1: Models & Parser (Day 1)
1. Define all dataclasses
2. Implement YAML parser
3. Validate contract file format
4. Handle defaults and inheritance

### Phase 2: Query Rules (Day 1-2)
1. Implement `QueryRuleEvaluator`
2. Support all expectation types
3. Handle MUQL execution
4. Format results

### Phase 3: Analyze Rules (Day 2)
1. Implement `AnalyzeRuleEvaluator`
2. Add circular dependency analysis
3. Add coupling analysis
4. Add complexity analysis

### Phase 4: Dependency Rules (Day 2-3)
1. Implement `DependencyRuleEvaluator`
2. Add glob pattern matching
3. Support exception lists
4. Generate clear messages

### Phase 5: Pattern Rules (Day 3)
1. Implement `PatternRuleEvaluator`
2. Add decorator checks
3. Add naming convention checks
4. Add interface implementation checks

### Phase 6: Verifier (Day 3-4)
1. Implement `ContractVerifier`
2. Add exclude pattern handling
3. Add fail-fast option
4. Aggregate results

### Phase 7: Reporters (Day 4)
1. Implement text reporter
2. Implement JSON reporter
3. Implement JUnit XML reporter
4. Add colorized output

### Phase 8: CLI Integration (Day 4-5)
1. Add `mu contracts verify` command
2. Add `mu contracts init` to create template
3. Add format options
4. Set exit codes

### Phase 9: Testing (Day 5)
1. Unit tests for each rule type
2. Integration tests with sample contracts
3. CI example testing
4. Edge case handling

---

## CLI Interface

```bash
# Verify contracts
$ mu contracts verify
Contract Verification: FAILED
Checked: 8 contracts

ERRORS (2):
  ✗ Controllers don't access repositories directly
    Controllers must go through services
    - UserController.get_user → UserRepository.find_by_id (src/controllers/user.py)
    - OrderController.list_orders → OrderRepository.list (src/controllers/order.py)

  ✗ No circular dependencies
    Prevent circular module dependencies
    - auth → user → permissions → auth

WARNINGS (1):
  ⚠ Function complexity limit
    - process_payment (complexity: 723) in src/services/payment.py

Summary:
  Errors: 2
  Warnings: 1

$ echo $?
1

# JSON output for CI
$ mu contracts verify --format json
{
  "passed": false,
  "errors": [...],
  "warnings": [...],
  "summary": {"errors": 2, "warnings": 1}
}

# JUnit XML for CI
$ mu contracts verify --format junit > contracts-report.xml

# Initialize contract file
$ mu contracts init
Created .mu-contracts.yml with example contracts

# Verify specific contracts
$ mu contracts verify --only "No circular*"
```

---

## CI Integration Examples

### GitHub Actions

```yaml
name: Architecture Contracts

on: [push, pull_request]

jobs:
  verify-contracts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install MU
        run: pip install mu-cli

      - name: Build graph
        run: mu kernel build

      - name: Verify contracts
        run: mu contracts verify --format junit > contracts-report.xml

      - name: Upload results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: contracts-report
          path: contracts-report.xml

      - name: Publish Test Results
        uses: EnricoMi/publish-unit-test-result-action@v2
        if: always()
        with:
          files: contracts-report.xml
```

### GitLab CI

```yaml
verify-contracts:
  stage: test
  script:
    - pip install mu-cli
    - mu kernel build
    - mu contracts verify --format junit > contracts-report.xml
  artifacts:
    reports:
      junit: contracts-report.xml
    when: always
```

---

## Testing Strategy

### Unit Tests
```python
def test_parse_contract_file():
    content = """
    version: "1.0"
    contracts:
      - name: "Test"
        severity: error
        rule:
          type: query
          muql: "SELECT * FROM functions"
        expect: empty
    """
    contracts = parse_contracts(content)
    assert len(contracts.contracts) == 1
    assert contracts.contracts[0].name == "Test"

def test_query_rule_empty_expectation(mubase):
    rule = Rule(type="query", params={"muql": "SELECT * FROM functions WHERE name = 'nonexistent'"})
    expect = Expectation(type="empty")
    evaluator = QueryRuleEvaluator()
    passed, _ = evaluator.evaluate(mubase, rule, expect)
    assert passed
```

---

## Success Criteria

- [ ] All rule types implemented
- [ ] Clear violation messages
- [ ] CI integration works
- [ ] JUnit output valid
- [ ] Exit code correct for failures

---

## Future Enhancements

1. **Baseline mode**: Track existing violations, fail on new ones
2. **Auto-fix suggestions**: Suggest how to fix violations
3. **Contract inheritance**: Extend base contracts
4. **Custom rules**: Plugin system for custom evaluators
5. **Trend tracking**: Track violations over time
