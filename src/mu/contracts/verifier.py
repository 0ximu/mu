"""Contract verification engine.

This module provides the ContractVerifier class that orchestrates
rule evaluation and produces verification results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mu.contracts.models import (
    Contract,
    ContractFile,
    ContractSettings,
    Severity,
    VerificationResult,
    Violation,
)
from mu.contracts.rules import (
    AnalyzeRuleEvaluator,
    DependencyRuleEvaluator,
    PatternRuleEvaluator,
    QueryRuleEvaluator,
    RuleEvaluator,
)

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class ContractVerifier:
    """Verify architectural contracts against a MUbase graph database.

    Example:
        >>> from mu.kernel import MUbase
        >>> from mu.contracts import ContractVerifier, parse_contracts_file
        >>>
        >>> db = MUbase(Path(".mubase"))
        >>> contracts = parse_contracts_file(Path(".mu-contracts.yml"))
        >>> verifier = ContractVerifier(db)
        >>> result = verifier.verify(contracts)
        >>> print(f"Passed: {result.passed}")
    """

    def __init__(self, mubase: MUbase) -> None:
        """Initialize verifier with database connection.

        Args:
            mubase: The MUbase database to verify against.
        """
        self._mubase = mubase
        self._evaluators: dict[str, RuleEvaluator] = {
            "query": QueryRuleEvaluator(),
            "analyze": AnalyzeRuleEvaluator(),
            "dependency": DependencyRuleEvaluator(),
            "pattern": PatternRuleEvaluator(),
        }

    def register_evaluator(self, evaluator: RuleEvaluator) -> None:
        """Register a custom rule evaluator.

        Args:
            evaluator: The evaluator to register.
        """
        self._evaluators[evaluator.rule_type] = evaluator

    def verify(
        self,
        contracts: ContractFile,
        fail_fast: bool = False,
    ) -> VerificationResult:
        """Verify all contracts against the database.

        Args:
            contracts: Parsed contract file with rules to verify.
            fail_fast: Stop on first error-level violation.

        Returns:
            VerificationResult with all violations categorized by severity.
        """
        all_violations: list[Violation] = []
        checked = 0

        for contract in contracts.contracts:
            # Skip disabled contracts
            if not contract.enabled:
                continue

            # Skip if matches exclude patterns
            if self._should_skip(contract, contracts.settings):
                continue

            checked += 1

            # Get evaluator for this rule type
            evaluator = self._evaluators.get(contract.rule.type.value)
            if evaluator is None:
                violation = Violation(
                    contract=contract,
                    message=f"Unknown rule type: {contract.rule.type.value}",
                    details=[],
                )
                all_violations.append(violation)
                continue

            # Evaluate the rule
            try:
                result = evaluator.evaluate(
                    self._mubase,
                    contract.rule,
                    contract.expect,
                )
            except Exception as e:
                violation = Violation(
                    contract=contract,
                    message=f"Evaluation error: {e}",
                    details=[],
                )
                all_violations.append(violation)
                continue

            # Check if rule passed
            if not result.passed:
                violation = Violation(
                    contract=contract,
                    message=f"Contract violated: {contract.name}",
                    details=result.details,
                )
                all_violations.append(violation)

                # Fail fast on errors
                if fail_fast and contract.severity == Severity.ERROR:
                    break

        # Categorize violations by severity
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

    def _should_skip(
        self,
        contract: Contract,
        settings: ContractSettings,
    ) -> bool:
        """Check if a contract should be skipped based on settings.

        Args:
            contract: The contract to check.
            settings: Global settings.

        Returns:
            True if contract should be skipped.
        """
        # Future: implement exclude pattern matching against contract metadata
        return False
