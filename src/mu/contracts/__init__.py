"""MU Contracts - Architecture verification and enforcement.

Provides declarative architecture rules that are verified against the MUbase graph.
Define what dependencies are allowed, enforce complexity limits, and prevent
architectural drift.

Example:
    Verify contracts from CLI:

        $ mu contracts init .
        Created .mu-contracts.yml with example contracts

        $ mu contracts verify .
        Contract Verification: PASSED
        Checked: 5 contracts

    Or use the Python API:

        >>> from mu.kernel import MUbase
        >>> from mu.contracts import ContractVerifier, parse_contracts_file
        >>>
        >>> contracts = parse_contracts_file(Path(".mu-contracts.yml"))
        >>> db = MUbase(Path(".mubase"))
        >>> verifier = ContractVerifier(db)
        >>> result = verifier.verify(contracts)
        >>> print(f"Passed: {result.passed}, Errors: {len(result.violations)}")

Contract File Format:
    Contracts are defined in YAML files (typically `.mu-contracts.yml`):

        version: "1.0"
        name: "Architecture Contracts"
        settings:
          fail_on_warning: false
        contracts:
          - name: "No circular dependencies"
            severity: error
            rule:
              type: analyze
              analysis: circular
            expect: empty

Rule Types:
    - query: Execute MUQL query, check result count
    - analyze: Built-in analysis (circular, complexity, coupling)
    - dependency: A should not depend on B (glob patterns)
    - pattern: All X must have Y (decorator/annotation checks)

Expectations:
    - empty: Expect no results (violations)
    - not_empty: Expect at least one result
    - count: Expect exact number of results
    - max: Expect at most N results
    - min: Expect at least N results
"""

from mu.contracts.models import (
    Contract,
    ContractFile,
    ContractSettings,
    EvaluationResult,
    Expectation,
    ExpectationType,
    Rule,
    RuleType,
    Severity,
    VerificationResult,
    Violation,
)
from mu.contracts.parser import (
    ContractParseError,
    parse_contracts,
    parse_contracts_file,
)
from mu.contracts.reporter import ContractReporter
from mu.contracts.rules import (
    AnalyzeRuleEvaluator,
    DependencyRuleEvaluator,
    PatternRuleEvaluator,
    QueryRuleEvaluator,
    RuleEvaluator,
    check_expectation,
)
from mu.contracts.verifier import ContractVerifier

__all__ = [
    # Models
    "Severity",
    "RuleType",
    "ExpectationType",
    "Rule",
    "Expectation",
    "Contract",
    "ContractSettings",
    "ContractFile",
    "Violation",
    "VerificationResult",
    "EvaluationResult",
    # Parser
    "parse_contracts",
    "parse_contracts_file",
    "ContractParseError",
    # Rule Evaluators
    "RuleEvaluator",
    "QueryRuleEvaluator",
    "AnalyzeRuleEvaluator",
    "DependencyRuleEvaluator",
    "PatternRuleEvaluator",
    "check_expectation",
    # Verifier
    "ContractVerifier",
    # Reporter
    "ContractReporter",
]
