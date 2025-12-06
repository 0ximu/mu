# Contracts Module - Architecture Verification

The contracts module provides declarative architecture rules that are verified against the MUbase graph database. Define what dependencies are allowed, enforce complexity limits, and prevent architectural drift.

## Architecture

```
.mu-contracts.yml → ContractParser → ContractFile
                                          ↓
                    MUbase ← ContractVerifier → VerificationResult
                                          ↓
                              ContractReporter → Text/JSON/JUnit
```

### Files

| File | Purpose |
|------|---------|
| `models.py` | Data models: Contract, Rule, Expectation, Violation, etc. |
| `parser.py` | YAML contract file parsing with validation |
| `rules.py` | RuleEvaluator protocol and implementations |
| `verifier.py` | ContractVerifier orchestrates rule evaluation |
| `reporter.py` | Text, JSON, and JUnit XML report generation |

## Contract File Format

```yaml
# .mu-contracts.yml
version: "1.0"
name: "Architecture Contracts"

settings:
  fail_on_warning: false  # Fail verification on warnings
  exclude_tests: true     # Exclude test files from analysis
  exclude_patterns:       # Glob patterns to exclude
    - "**/test_*.py"

contracts:
  - name: "Contract Name"
    description: "Optional description"
    severity: error       # error, warning, info
    enabled: true         # Can disable contracts
    rule:
      type: query         # query, analyze, dependency, pattern
      # type-specific params...
    expect: empty         # empty, not_empty, {max: N}, {min: N}, {count: N}
```

## Rule Types

### Query Rules

Execute MUQL queries and check result counts.

```yaml
- name: "Function complexity limit"
  rule:
    type: query
    muql: |
      SELECT name, file_path, complexity
      FROM functions
      WHERE complexity > 500
  expect: empty  # No results means pass
```

### Analyze Rules

Built-in analysis types: `circular`, `complexity`, `coupling`, `unused`, `hotspots`.

```yaml
- name: "No circular dependencies"
  rule:
    type: analyze
    analysis: circular
  expect: empty

- name: "No high complexity"
  rule:
    type: analyze
    analysis: complexity
    threshold: 500  # Optional threshold
  expect: empty
```

### Dependency Rules

Forbid imports between module patterns.

```yaml
- name: "Services don't import controllers"
  rule:
    type: dependency
    from: "src/services/**"
    to: "src/controllers/**"
  expect: empty  # No such imports should exist
```

### Pattern Rules

Enforce that nodes matching a pattern have required properties.

```yaml
- name: "All services are injectable"
  rule:
    type: pattern
    match: "src/services/**/*.py"
    node_type: class
    name_pattern: "*Service"
    must_have:
      decorator: "@injectable"
  expect: empty  # All matching nodes should have decorator
```

## Expectations

| Type | Description |
|------|-------------|
| `empty` | Expect no results (violations) |
| `not_empty` | Expect at least one result |
| `{count: N}` | Expect exactly N results |
| `{max: N}` | Expect at most N results |
| `{min: N}` | Expect at least N results |

## Usage

### Python API

```python
from pathlib import Path
from mu.kernel import MUbase
from mu.contracts import (
    ContractVerifier,
    ContractReporter,
    parse_contracts_file,
)

# Parse contracts
contracts = parse_contracts_file(Path(".mu-contracts.yml"))

# Verify against database
db = MUbase(Path(".mubase"))
verifier = ContractVerifier(db)
result = verifier.verify(contracts)

# Report results
reporter = ContractReporter()
print(reporter.report_text(result))

# Check pass/fail
if not result.passed:
    print(f"Errors: {result.error_count}")
    for v in result.violations:
        print(f"  - {v.contract.name}: {v.message}")
```

### CLI Usage

```bash
# Create template contract file
mu contracts init .

# Verify contracts
mu contracts verify .

# With options
mu contracts verify . --format json
mu contracts verify . --format junit > report.xml
mu contracts verify . --only "No circular*"
mu contracts verify . --fail-fast

# Check exit code for CI
mu contracts verify . && echo "Passed" || echo "Failed"
```

## Adding Custom Evaluators

Implement the `RuleEvaluator` protocol:

```python
from mu.contracts.models import EvaluationResult, Expectation, Rule
from mu.contracts.rules import RuleEvaluator, check_expectation
from mu.kernel.mubase import MUbase

class CustomRuleEvaluator:
    @property
    def rule_type(self) -> str:
        return "custom"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        # Custom logic here
        violations = []

        passed = check_expectation(len(violations), expect)
        return EvaluationResult(
            passed=passed,
            details=violations,
            row_count=len(violations),
        )

# Register with verifier
verifier = ContractVerifier(db)
verifier.register_evaluator(CustomRuleEvaluator())
```

## CI Integration

### GitHub Actions

```yaml
- name: Verify Contracts
  run: mu contracts verify . --format junit > contracts.xml

- name: Upload Results
  uses: actions/upload-artifact@v3
  with:
    name: contracts-report
    path: contracts.xml
```

### GitLab CI

```yaml
contracts:
  script:
    - mu kernel build
    - mu contracts verify . --format junit > contracts.xml
  artifacts:
    reports:
      junit: contracts.xml
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All contracts passed |
| 1 | Configuration error (missing file, parse error) |
| 5 | Contract violation (architecture rule failed) |

## Anti-Patterns

1. **Never** put secrets in contract files
2. **Never** use overly broad patterns (like `**/*`)
3. **Never** set `fail_on_warning: true` without reviewing all warnings first
4. **Never** ignore contract violations - fix them or adjust the rule

## Testing

```bash
pytest tests/unit/test_contracts.py -v
```

Key test scenarios:
- Parser handles all rule types and expectations
- Parser validates required fields
- Each evaluator finds expected violations
- Verifier categorizes by severity
- Reporter generates valid output formats
