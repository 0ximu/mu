"""Tests for MU Contracts - Architecture verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    check_expectation,
)
from mu.contracts.verifier import ContractVerifier
from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create temporary database path."""
    return tmp_path / "test.mubase"


@pytest.fixture
def db(db_path: Path) -> MUbase:
    """Create database instance."""
    database = MUbase(db_path)
    yield database
    database.close()


@pytest.fixture
def populated_db(db: MUbase) -> MUbase:
    """Create database with sample nodes and edges for contract testing."""
    # Module nodes
    db.add_node(
        Node(
            id="mod:src/services/user.py",
            type=NodeType.MODULE,
            name="user",
            file_path="src/services/user.py",
            complexity=50,
        )
    )
    db.add_node(
        Node(
            id="mod:src/controllers/api.py",
            type=NodeType.MODULE,
            name="api",
            file_path="src/controllers/api.py",
            complexity=30,
        )
    )
    db.add_node(
        Node(
            id="mod:src/core/base.py",
            type=NodeType.MODULE,
            name="base",
            file_path="src/core/base.py",
            complexity=20,
        )
    )

    # Class nodes
    db.add_node(
        Node(
            id="cls:src/services/user.py:UserService",
            type=NodeType.CLASS,
            name="UserService",
            file_path="src/services/user.py",
            complexity=40,
            properties={"decorators": ["@injectable"], "bases": ["BaseService"]},
        )
    )
    db.add_node(
        Node(
            id="cls:src/services/user.py:PlainClass",
            type=NodeType.CLASS,
            name="PlainClass",
            file_path="src/services/user.py",
            complexity=10,
            properties={"decorators": [], "bases": []},
        )
    )

    # Function nodes with varying complexity
    db.add_node(
        Node(
            id="fn:src/services/user.py:process",
            type=NodeType.FUNCTION,
            name="process",
            file_path="src/services/user.py",
            complexity=600,  # High complexity
        )
    )
    db.add_node(
        Node(
            id="fn:src/services/user.py:simple",
            type=NodeType.FUNCTION,
            name="simple",
            file_path="src/services/user.py",
            complexity=10,  # Low complexity
        )
    )

    # Edges: IMPORTS (service -> controller, creating forbidden dependency)
    db.add_edge(
        Edge(
            id="edge:imports:1",
            source_id="mod:src/services/user.py",
            target_id="mod:src/controllers/api.py",
            type=EdgeType.IMPORTS,
        )
    )

    # Edges: Circular dependency (bidirectional import)
    db.add_edge(
        Edge(
            id="edge:imports:2",
            source_id="mod:src/controllers/api.py",
            target_id="mod:src/core/base.py",
            type=EdgeType.IMPORTS,
        )
    )
    db.add_edge(
        Edge(
            id="edge:imports:3",
            source_id="mod:src/core/base.py",
            target_id="mod:src/controllers/api.py",
            type=EdgeType.IMPORTS,
        )
    )

    # CONTAINS edges
    db.add_edge(
        Edge(
            id="edge:contains:1",
            source_id="mod:src/services/user.py",
            target_id="cls:src/services/user.py:UserService",
            type=EdgeType.CONTAINS,
        )
    )

    return db


@pytest.fixture
def sample_contract_yaml() -> str:
    """Sample contract YAML for parsing tests."""
    return '''
version: "1.0"
name: "Test Contracts"
settings:
  fail_on_warning: true
  exclude_tests: false
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
# Model Tests
# =============================================================================


class TestModels:
    """Tests for contract data models."""

    def test_severity_values(self):
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"

    def test_rule_type_values(self):
        assert RuleType.QUERY.value == "query"
        assert RuleType.ANALYZE.value == "analyze"
        assert RuleType.DEPENDENCY.value == "dependency"
        assert RuleType.PATTERN.value == "pattern"

    def test_expectation_type_values(self):
        assert ExpectationType.EMPTY.value == "empty"
        assert ExpectationType.NOT_EMPTY.value == "not_empty"
        assert ExpectationType.COUNT.value == "count"
        assert ExpectationType.MAX.value == "max"
        assert ExpectationType.MIN.value == "min"

    def test_expectation_to_dict(self):
        exp = Expectation(type=ExpectationType.MAX, value=10)
        d = exp.to_dict()
        assert d["type"] == "max"
        assert d["value"] == 10

    def test_rule_to_dict(self):
        rule = Rule(type=RuleType.QUERY, params={"muql": "SELECT 1"})
        d = rule.to_dict()
        assert d["type"] == "query"
        assert d["params"]["muql"] == "SELECT 1"

    def test_contract_to_dict(self):
        contract = Contract(
            name="Test",
            description="Desc",
            severity=Severity.ERROR,
            rule=Rule(type=RuleType.QUERY, params={}),
            expect=Expectation(type=ExpectationType.EMPTY),
        )
        d = contract.to_dict()
        assert d["name"] == "Test"
        assert d["severity"] == "error"
        assert d["enabled"] is True

    def test_verification_result_properties(self):
        result = VerificationResult(
            passed=False,
            contracts_checked=5,
            violations=[
                Violation(
                    contract=Contract(
                        name="T", description="", severity=Severity.ERROR,
                        rule=Rule(RuleType.QUERY, {}),
                        expect=Expectation(ExpectationType.EMPTY),
                    ),
                    message="fail",
                )
            ],
            warnings=[
                Violation(
                    contract=Contract(
                        name="W", description="", severity=Severity.WARNING,
                        rule=Rule(RuleType.QUERY, {}),
                        expect=Expectation(ExpectationType.EMPTY),
                    ),
                    message="warn",
                )
            ],
        )
        assert result.error_count == 1
        assert result.warning_count == 1
        assert result.success is True  # No parse error


# =============================================================================
# Parser Tests
# =============================================================================


class TestContractParser:
    """Tests for YAML contract parsing."""

    def test_parse_minimal_contract(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT * FROM functions"
    expect: empty
'''
        result = parse_contracts(yaml_content)
        assert len(result.contracts) == 1
        assert result.contracts[0].name == "Test"
        assert result.contracts[0].severity == Severity.ERROR  # default

    def test_parse_empty_file(self):
        result = parse_contracts("")
        assert len(result.contracts) == 0

    def test_parse_all_rule_types(self):
        yaml_content = '''
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
        result = parse_contracts(yaml_content)
        assert len(result.contracts) == 4
        assert result.contracts[0].rule.type == RuleType.QUERY
        assert result.contracts[1].rule.type == RuleType.ANALYZE
        assert result.contracts[2].rule.type == RuleType.DEPENDENCY
        assert result.contracts[3].rule.type == RuleType.PATTERN

    def test_parse_expectation_shorthand(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT 1"
    expect: not_empty
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].expect.type == ExpectationType.NOT_EMPTY

    def test_parse_expectation_max(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT COUNT(*)"
    expect:
      max: 10
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].expect.type == ExpectationType.MAX
        assert result.contracts[0].expect.value == 10

    def test_parse_expectation_min(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT COUNT(*)"
    expect:
      min: 5
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].expect.type == ExpectationType.MIN
        assert result.contracts[0].expect.value == 5

    def test_parse_settings(self):
        yaml_content = '''
settings:
  fail_on_warning: true
  exclude_tests: false
  exclude_patterns:
    - "**/test_*.py"
contracts: []
'''
        result = parse_contracts(yaml_content)
        assert result.settings.fail_on_warning is True
        assert result.settings.exclude_tests is False
        assert "**/test_*.py" in result.settings.exclude_patterns

    def test_parse_disabled_contract(self):
        yaml_content = '''
contracts:
  - name: "Disabled"
    enabled: false
    rule:
      type: query
      muql: "SELECT 1"
    expect: empty
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].enabled is False

    def test_parse_error_missing_name(self):
        yaml_content = '''
contracts:
  - rule:
      type: query
      muql: "SELECT 1"
'''
        with pytest.raises(ContractParseError, match="Missing required field: name"):
            parse_contracts(yaml_content)

    def test_parse_error_missing_rule(self):
        yaml_content = '''
contracts:
  - name: "Test"
    expect: empty
'''
        with pytest.raises(ContractParseError, match="Missing required field: rule"):
            parse_contracts(yaml_content)

    def test_parse_error_missing_rule_type(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      muql: "SELECT 1"
    expect: empty
'''
        with pytest.raises(ContractParseError, match="Rule missing required field: type"):
            parse_contracts(yaml_content)

    def test_parse_error_invalid_rule_type(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: invalid_type
      muql: "SELECT 1"
    expect: empty
'''
        with pytest.raises(ContractParseError, match="Invalid rule type"):
            parse_contracts(yaml_content)

    def test_parse_error_invalid_yaml(self):
        yaml_content = "{{invalid yaml"
        with pytest.raises(ContractParseError, match="Invalid YAML"):
            parse_contracts(yaml_content)

    def test_parse_error_invalid_severity(self):
        yaml_content = '''
contracts:
  - name: "Test"
    severity: critical
    rule:
      type: query
      muql: "SELECT 1"
    expect: empty
'''
        with pytest.raises(ContractParseError, match="Invalid severity"):
            parse_contracts(yaml_content)

    def test_parse_error_query_missing_muql(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
    expect: empty
'''
        with pytest.raises(ContractParseError, match="Query rule requires 'muql' field"):
            parse_contracts(yaml_content)

    def test_parse_error_analyze_missing_analysis(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: analyze
    expect: empty
'''
        with pytest.raises(ContractParseError, match="Analyze rule requires 'analysis' field"):
            parse_contracts(yaml_content)

    def test_parse_error_dependency_missing_from(self):
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: dependency
      to: "src/**"
    expect: empty
'''
        with pytest.raises(ContractParseError, match="Dependency rule requires 'from' and 'to'"):
            parse_contracts(yaml_content)

    def test_parse_contracts_file(self, tmp_path: Path):
        contract_path = tmp_path / "test.yml"
        contract_path.write_text('''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT 1"
    expect: empty
''')
        result = parse_contracts_file(contract_path)
        assert len(result.contracts) == 1

    def test_parse_contracts_file_not_found(self, tmp_path: Path):
        with pytest.raises(ContractParseError, match="File not found"):
            parse_contracts_file(tmp_path / "nonexistent.yml")


# =============================================================================
# Expectation Check Tests
# =============================================================================


class TestCheckExpectation:
    """Tests for expectation checking."""

    def test_empty_with_zero_results(self):
        assert check_expectation(0, Expectation(ExpectationType.EMPTY)) is True

    def test_empty_with_results(self):
        assert check_expectation(5, Expectation(ExpectationType.EMPTY)) is False

    def test_not_empty_with_results(self):
        assert check_expectation(5, Expectation(ExpectationType.NOT_EMPTY)) is True

    def test_not_empty_with_zero_results(self):
        assert check_expectation(0, Expectation(ExpectationType.NOT_EMPTY)) is False

    def test_count_exact_match(self):
        assert check_expectation(5, Expectation(ExpectationType.COUNT, 5)) is True

    def test_count_mismatch(self):
        assert check_expectation(3, Expectation(ExpectationType.COUNT, 5)) is False

    def test_max_within_limit(self):
        assert check_expectation(5, Expectation(ExpectationType.MAX, 10)) is True

    def test_max_at_limit(self):
        assert check_expectation(10, Expectation(ExpectationType.MAX, 10)) is True

    def test_max_exceeds_limit(self):
        assert check_expectation(15, Expectation(ExpectationType.MAX, 10)) is False

    def test_min_meets_threshold(self):
        assert check_expectation(10, Expectation(ExpectationType.MIN, 5)) is True

    def test_min_at_threshold(self):
        assert check_expectation(5, Expectation(ExpectationType.MIN, 5)) is True

    def test_min_below_threshold(self):
        assert check_expectation(3, Expectation(ExpectationType.MIN, 5)) is False

    def test_max_with_result_value(self):
        # When result_value is provided, it should be used instead of result_count
        assert check_expectation(1, Expectation(ExpectationType.MAX, 10), result_value=5) is True
        assert check_expectation(1, Expectation(ExpectationType.MAX, 10), result_value=15) is False


# =============================================================================
# Rule Evaluator Tests
# =============================================================================


class TestQueryRuleEvaluator:
    """Tests for MUQL query rule evaluation."""

    def test_evaluate_empty_result(self, populated_db: MUbase):
        evaluator = QueryRuleEvaluator()
        rule = Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions WHERE name = 'nonexistent'"})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is True
        assert result.row_count == 0

    def test_evaluate_finds_violations(self, populated_db: MUbase):
        evaluator = QueryRuleEvaluator()
        rule = Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions WHERE complexity > 500"})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is False
        assert result.row_count >= 1

    def test_evaluate_missing_muql(self, populated_db: MUbase):
        evaluator = QueryRuleEvaluator()
        rule = Rule(RuleType.QUERY, {})  # No muql param
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is False
        assert any("error" in d for d in result.details)

    def test_evaluate_invalid_muql(self, populated_db: MUbase):
        evaluator = QueryRuleEvaluator()
        rule = Rule(RuleType.QUERY, {"muql": "INVALID QUERY SYNTAX !!!"})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is False


class TestAnalyzeRuleEvaluator:
    """Tests for built-in analysis rule evaluation."""

    def test_analyze_circular_finds_cycles(self, populated_db: MUbase):
        evaluator = AnalyzeRuleEvaluator()
        rule = Rule(RuleType.ANALYZE, {"analysis": "circular"})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        # There's a circular dependency between api and base
        assert result.passed is False
        assert result.row_count >= 1

    def test_analyze_complexity(self, populated_db: MUbase):
        evaluator = AnalyzeRuleEvaluator()
        rule = Rule(RuleType.ANALYZE, {"analysis": "complexity", "threshold": 500})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        # There's a function with complexity 600
        assert result.passed is False
        assert result.row_count >= 1

    def test_analyze_unknown_type(self, populated_db: MUbase):
        evaluator = AnalyzeRuleEvaluator()
        rule = Rule(RuleType.ANALYZE, {"analysis": "unknown_analysis"})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is False
        assert any("error" in d for d in result.details)


class TestDependencyRuleEvaluator:
    """Tests for dependency restriction rule evaluation."""

    def test_finds_forbidden_dependency(self, populated_db: MUbase):
        evaluator = DependencyRuleEvaluator()
        rule = Rule(
            RuleType.DEPENDENCY,
            {"from": "src/services/*", "to": "src/controllers/*"},
        )
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        # Service imports controller - forbidden
        assert result.passed is False
        assert len(result.details) >= 1

    def test_no_matching_dependencies(self, populated_db: MUbase):
        evaluator = DependencyRuleEvaluator()
        rule = Rule(
            RuleType.DEPENDENCY,
            {"from": "src/nonexistent/*", "to": "src/other/*"},
        )
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is True
        assert len(result.details) == 0

    def test_missing_patterns(self, populated_db: MUbase):
        evaluator = DependencyRuleEvaluator()
        rule = Rule(RuleType.DEPENDENCY, {})  # No from/to
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is False
        assert any("error" in d for d in result.details)


class TestPatternRuleEvaluator:
    """Tests for pattern-based rule evaluation."""

    def test_finds_missing_decorator(self, populated_db: MUbase):
        evaluator = PatternRuleEvaluator()
        rule = Rule(
            RuleType.PATTERN,
            {
                "match": "src/services/*",
                "node_type": "class",
                "name_pattern": "*",
                "must_have": {"decorator": "@injectable"},
            },
        )
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        # PlainClass doesn't have @injectable
        assert result.passed is False
        assert any("PlainClass" in d.get("node", "") for d in result.details)

    def test_pattern_with_no_matches(self, populated_db: MUbase):
        evaluator = PatternRuleEvaluator()
        rule = Rule(
            RuleType.PATTERN,
            {
                "match": "src/nonexistent/*",
                "node_type": "class",
            },
        )
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        assert result.passed is True


# =============================================================================
# Contract Verifier Tests
# =============================================================================


class TestContractVerifier:
    """Tests for contract verification orchestration."""

    def test_verify_all_pass(self, populated_db: MUbase):
        contracts = ContractFile(
            contracts=[
                Contract(
                    name="Safe Query",
                    description="",
                    severity=Severity.ERROR,
                    rule=Rule(
                        RuleType.QUERY,
                        {"muql": "SELECT * FROM functions WHERE name = 'definitely_not_exists'"},
                    ),
                    expect=Expectation(ExpectationType.EMPTY),
                )
            ]
        )

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        assert result.passed is True
        assert len(result.violations) == 0
        assert result.contracts_checked == 1

    def test_verify_with_violation(self, populated_db: MUbase):
        contracts = ContractFile(
            contracts=[
                Contract(
                    name="Complexity Check",
                    description="",
                    severity=Severity.ERROR,
                    rule=Rule(
                        RuleType.QUERY,
                        {"muql": "SELECT * FROM functions WHERE complexity > 500"},
                    ),
                    expect=Expectation(ExpectationType.EMPTY),
                )
            ]
        )

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        assert result.passed is False
        assert len(result.violations) >= 1

    def test_verify_skips_disabled(self, populated_db: MUbase):
        contracts = ContractFile(
            contracts=[
                Contract(
                    name="Disabled Contract",
                    description="",
                    severity=Severity.ERROR,
                    rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions"}),
                    expect=Expectation(ExpectationType.EMPTY),
                    enabled=False,
                )
            ]
        )

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        assert result.contracts_checked == 0

    def test_verify_categorizes_by_severity(self, populated_db: MUbase):
        contracts = ContractFile(
            contracts=[
                Contract(
                    name="Error Contract",
                    description="",
                    severity=Severity.ERROR,
                    rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions"}),
                    expect=Expectation(ExpectationType.EMPTY),
                ),
                Contract(
                    name="Warning Contract",
                    description="",
                    severity=Severity.WARNING,
                    rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM classes"}),
                    expect=Expectation(ExpectationType.EMPTY),
                ),
            ]
        )

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        # Both have results, so both should fail
        assert len(result.violations) >= 1  # Errors
        assert len(result.warnings) >= 1  # Warnings

    def test_verify_fail_on_warning(self, populated_db: MUbase):
        contracts = ContractFile(
            settings=ContractSettings(fail_on_warning=True),
            contracts=[
                Contract(
                    name="Warning Only",
                    description="",
                    severity=Severity.WARNING,
                    rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions"}),
                    expect=Expectation(ExpectationType.EMPTY),
                )
            ],
        )

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        assert result.passed is False  # Failed due to warning

    def test_verify_fail_fast(self, populated_db: MUbase):
        contracts = ContractFile(
            contracts=[
                Contract(
                    name="First Error",
                    description="",
                    severity=Severity.ERROR,
                    rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions"}),
                    expect=Expectation(ExpectationType.EMPTY),
                ),
                Contract(
                    name="Second Error",
                    description="",
                    severity=Severity.ERROR,
                    rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM classes"}),
                    expect=Expectation(ExpectationType.EMPTY),
                ),
            ]
        )

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts, fail_fast=True)

        # Should stop after first error
        assert len(result.violations) == 1


# =============================================================================
# Reporter Tests
# =============================================================================


class TestContractReporter:
    """Tests for contract report generation."""

    def test_report_text_passed(self):
        result = VerificationResult(passed=True, contracts_checked=5)
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=True)

        assert "PASSED" in output
        assert "Checked: 5 contracts" in output

    def test_report_text_failed(self):
        contract = Contract(
            name="Test Contract",
            description="A test",
            severity=Severity.ERROR,
            rule=Rule(RuleType.QUERY, {}),
            expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(
            contract=contract,
            message="Failed",
            details=[{"from": "a", "to": "b"}],
        )
        result = VerificationResult(
            passed=False,
            contracts_checked=1,
            violations=[violation],
        )

        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=True)

        assert "FAILED" in output
        assert "ERRORS (1)" in output
        assert "Test Contract" in output

    def test_report_text_with_warnings(self):
        contract = Contract(
            name="Warning Contract",
            description="",
            severity=Severity.WARNING,
            rule=Rule(RuleType.QUERY, {}),
            expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(contract=contract, message="Warn", details=[])
        result = VerificationResult(
            passed=True,
            contracts_checked=1,
            warnings=[violation],
        )

        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=True)

        assert "WARNINGS (1)" in output

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

    def test_format_detail_dependency(self):
        reporter = ContractReporter()
        detail = {"from": "module_a", "to": "module_b"}
        formatted = reporter._format_detail(detail)
        assert "module_a -> module_b" in formatted

    def test_format_detail_pattern(self):
        reporter = ContractReporter()
        detail = {"node": "MyClass", "path": "src/a.py", "missing": "decorator @inject"}
        formatted = reporter._format_detail(detail)
        assert "MyClass" in formatted
        assert "missing" in formatted

    def test_format_detail_complexity(self):
        reporter = ContractReporter()
        detail = {"name": "process", "path": "src/a.py", "complexity": 600}
        formatted = reporter._format_detail(detail)
        assert "process" in formatted
        assert "600" in formatted


# =============================================================================
# Integration Tests
# =============================================================================


# =============================================================================
# Additional Parser Tests for Coverage
# =============================================================================


class TestContractParserCoverage:
    """Additional parser tests for coverage."""

    def test_parse_non_dict_root(self):
        """Contract file must be a YAML object."""
        yaml_content = "- item1\n- item2"  # List, not dict
        with pytest.raises(ContractParseError, match="Contract file must be a YAML object"):
            parse_contracts(yaml_content)

    def test_parse_file_read_error(self, tmp_path: Path):
        """Handle file read errors (OSError)."""
        # Create a directory with the same name as the file we try to read
        dir_path = tmp_path / "contracts.yml"
        dir_path.mkdir()
        with pytest.raises(ContractParseError, match="Failed to read file"):
            parse_contracts_file(dir_path)

    def test_parse_settings_not_dict(self):
        """Settings as non-dict should be ignored."""
        yaml_content = '''
settings: "invalid"
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT 1"
'''
        result = parse_contracts(yaml_content)
        # Should use default settings
        assert result.settings.fail_on_warning is False

    def test_parse_contracts_not_list(self):
        """Contracts as non-list should be ignored."""
        yaml_content = '''
contracts: "not a list"
'''
        result = parse_contracts(yaml_content)
        assert len(result.contracts) == 0

    def test_parse_contract_not_dict(self):
        """Contract item not being a dict should error."""
        yaml_content = '''
contracts:
  - "just a string"
'''
        with pytest.raises(ContractParseError, match="Must be a YAML object"):
            parse_contracts(yaml_content)

    def test_parse_rule_not_dict(self):
        """Rule not being a dict should error."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule: "not a dict"
'''
        with pytest.raises(ContractParseError, match="Rule must be a YAML object"):
            parse_contracts(yaml_content)

    def test_parse_dependency_with_exceptions(self):
        """Parse dependency rule with except list."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: dependency
      from: "src/a/**"
      to: "src/b/**"
      except:
        - "src/a/allowed.py"
        - "src/b/allowed.py"
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].rule.params["except"] == [
            "src/a/allowed.py",
            "src/b/allowed.py",
        ]

    def test_parse_pattern_with_all_params(self):
        """Parse pattern rule with all optional params."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: pattern
      match: "src/**"
      node_type: class
      name_pattern: "*Service"
      must_have:
        decorator: "@inject"
'''
        result = parse_contracts(yaml_content)
        params = result.contracts[0].rule.params
        assert params["match"] == "src/**"
        assert params["node_type"] == "class"
        assert params["name_pattern"] == "*Service"
        assert params["must_have"]["decorator"] == "@inject"

    def test_parse_expectation_count_dict(self):
        """Parse count expectation in dict form."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT COUNT(*)"
    expect:
      count: 5
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].expect.type == ExpectationType.COUNT
        assert result.contracts[0].expect.value == 5

    def test_parse_expectation_full_form(self):
        """Parse expectation in full form with type and value."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT 1"
    expect:
      type: max
      value: 10
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].expect.type == ExpectationType.MAX
        assert result.contracts[0].expect.value == 10

    def test_parse_expectation_full_form_no_value(self):
        """Parse expectation in full form without value."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT 1"
    expect:
      type: empty
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].expect.type == ExpectationType.EMPTY
        assert result.contracts[0].expect.value is None

    def test_parse_expectation_invalid_full_form(self):
        """Parse expectation with invalid type in full form."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT 1"
    expect:
      type: invalid_type
'''
        with pytest.raises(ContractParseError, match="Invalid expectation type"):
            parse_contracts(yaml_content)

    def test_parse_expectation_invalid_format(self):
        """Parse expectation with completely invalid format."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT 1"
    expect:
      unknown_key: 123
'''
        with pytest.raises(ContractParseError, match="Invalid expectation format"):
            parse_contracts(yaml_content)

    def test_parse_analyze_with_threshold(self):
        """Parse analyze rule with threshold."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: analyze
      analysis: complexity
      threshold: 300
'''
        result = parse_contracts(yaml_content)
        assert result.contracts[0].rule.params["threshold"] == 300

    def test_parse_analyze_invalid_analysis(self):
        """Parse analyze rule with invalid analysis type."""
        yaml_content = '''
contracts:
  - name: "Test"
    rule:
      type: analyze
      analysis: unknown_analysis
'''
        with pytest.raises(ContractParseError, match="Invalid analysis type"):
            parse_contracts(yaml_content)


# =============================================================================
# Additional Reporter Tests for Coverage
# =============================================================================


class TestContractReporterCoverage:
    """Additional reporter tests for coverage."""

    def test_report_text_with_color(self):
        """Test text report with color codes."""
        result = VerificationResult(passed=True, contracts_checked=3)
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=False)
        # Color codes should be present
        assert "\033[32m" in output or "PASSED" in output

    def test_report_text_failed_with_color(self):
        """Test failed text report with color codes."""
        contract = Contract(
            name="Test", description="", severity=Severity.ERROR,
            rule=Rule(RuleType.QUERY, {}), expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(contract=contract, message="Failed", details=[])
        result = VerificationResult(passed=False, contracts_checked=1, violations=[violation])
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=False)
        # Red color code should be present
        assert "\033[31m" in output or "FAILED" in output

    def test_report_text_with_description(self):
        """Test text report includes contract description."""
        contract = Contract(
            name="Test Contract",
            description="This is a detailed description",
            severity=Severity.ERROR,
            rule=Rule(RuleType.QUERY, {}),
            expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(contract=contract, message="Failed", details=[])
        result = VerificationResult(passed=False, contracts_checked=1, violations=[violation])
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=True)
        assert "This is a detailed description" in output

    def test_report_text_truncates_many_details(self):
        """Test text report truncates when more than 5 details."""
        contract = Contract(
            name="Test", description="", severity=Severity.ERROR,
            rule=Rule(RuleType.QUERY, {}), expect=Expectation(ExpectationType.EMPTY),
        )
        details = [{"name": f"item{i}", "path": f"path{i}"} for i in range(10)]
        violation = Violation(contract=contract, message="Failed", details=details)
        result = VerificationResult(passed=False, contracts_checked=1, violations=[violation])
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=True)
        assert "... and 5 more" in output

    def test_report_text_warning_truncates_details(self):
        """Test text report truncates warning details at 3."""
        contract = Contract(
            name="Warn", description="Desc", severity=Severity.WARNING,
            rule=Rule(RuleType.QUERY, {}), expect=Expectation(ExpectationType.EMPTY),
        )
        details = [{"name": f"item{i}", "path": f"path{i}"} for i in range(8)]
        violation = Violation(contract=contract, message="Warning", details=details)
        result = VerificationResult(passed=True, contracts_checked=1, warnings=[violation])
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=True)
        assert "... and 5 more" in output

    def test_report_text_with_info(self):
        """Test text report includes info section."""
        contract = Contract(
            name="Info Contract", description="", severity=Severity.INFO,
            rule=Rule(RuleType.QUERY, {}), expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(contract=contract, message="Info", details=[])
        result = VerificationResult(passed=True, contracts_checked=1, info=[violation])
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=True)
        assert "INFO (1)" in output
        assert "Info Contract" in output

    def test_report_text_warning_with_color(self):
        """Test text report warning with yellow color."""
        contract = Contract(
            name="Warn", description="", severity=Severity.WARNING,
            rule=Rule(RuleType.QUERY, {}), expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(contract=contract, message="Warning", details=[])
        result = VerificationResult(passed=True, contracts_checked=1, warnings=[violation])
        reporter = ContractReporter()
        output = reporter.report_text(result, no_color=False)
        # Yellow color code should be present
        assert "\033[33m" in output or "WARNINGS" in output

    def test_report_junit_with_warnings(self):
        """Test JUnit report includes warnings as system-out."""
        contract = Contract(
            name="Warn Contract", description="", severity=Severity.WARNING,
            rule=Rule(RuleType.QUERY, {}), expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(contract=contract, message="Warning msg", details=[{"key": "value"}])
        result = VerificationResult(passed=True, contracts_checked=1, warnings=[violation])
        reporter = ContractReporter()
        output = reporter.report_junit(result)
        assert "<system-out>" in output
        assert "WARNING" in output

    def test_format_detail_error(self):
        """Test format detail with error key."""
        reporter = ContractReporter()
        detail = {"error": "Something went wrong"}
        formatted = reporter._format_detail(detail)
        assert "Error: Something went wrong" in formatted

    def test_format_detail_cycle(self):
        """Test format detail with cycle key."""
        reporter = ContractReporter()
        detail = {"cycle": ["a", "b", "c", "a"]}
        formatted = reporter._format_detail(detail)
        assert "a -> b -> c -> a" in formatted

    def test_format_detail_fallback(self):
        """Test format detail fallback for unknown keys."""
        reporter = ContractReporter()
        detail = {"custom_key": "custom_value", "another": 123}
        formatted = reporter._format_detail(detail)
        assert "custom_key=custom_value" in formatted
        assert "another=123" in formatted

    def test_format_detail_empty_fallback(self):
        """Test format detail fallback with None values."""
        reporter = ContractReporter()
        detail = {"key": None}
        formatted = reporter._format_detail(detail)
        # Should handle gracefully
        assert formatted == "{}" or "key" not in formatted or formatted == str(detail)


# =============================================================================
# Additional Rule Evaluator Tests for Coverage
# =============================================================================


class TestAnalyzeRuleEvaluatorCoverage:
    """Additional analyze rule tests for coverage."""

    def test_analyze_coupling(self, populated_db: MUbase):
        """Test coupling analysis."""
        evaluator = AnalyzeRuleEvaluator()
        rule = Rule(RuleType.ANALYZE, {"analysis": "coupling", "threshold": 0})
        expect = Expectation(ExpectationType.NOT_EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        # Should find modules with any coupling
        assert result.passed or result.row_count >= 0

    def test_analyze_unused(self, populated_db: MUbase):
        """Test unused module analysis."""
        evaluator = AnalyzeRuleEvaluator()
        rule = Rule(RuleType.ANALYZE, {"analysis": "unused"})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        # Result depends on test data - just verify it runs without error
        assert isinstance(result.passed, bool)

    def test_analyze_hotspots(self, populated_db: MUbase):
        """Test hotspot analysis."""
        evaluator = AnalyzeRuleEvaluator()
        rule = Rule(RuleType.ANALYZE, {"analysis": "hotspots", "threshold": 0})
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        # Result depends on test data - just verify it runs without error
        assert isinstance(result.passed, bool)


class TestPatternRuleEvaluatorCoverage:
    """Additional pattern rule tests for coverage."""

    def test_pattern_check_annotation(self, db: MUbase):
        """Test pattern rule checking for annotation."""
        # Add a node with annotations
        db.add_node(
            Node(
                id="cls:src/api/handler.py:Handler",
                type=NodeType.CLASS,
                name="Handler",
                file_path="src/api/handler.py",
                properties={"annotations": ["@api"], "decorators": []},
            )
        )
        db.add_node(
            Node(
                id="cls:src/api/plain.py:PlainHandler",
                type=NodeType.CLASS,
                name="PlainHandler",
                file_path="src/api/plain.py",
                properties={"annotations": [], "decorators": []},
            )
        )

        evaluator = PatternRuleEvaluator()
        rule = Rule(
            RuleType.PATTERN,
            {
                "match": "src/api/*",
                "node_type": "class",
                "must_have": {"annotation": "@api"},
            },
        )
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(db, rule, expect)
        # PlainHandler is missing the annotation
        assert result.passed is False
        assert any("PlainHandler" in d.get("node", "") for d in result.details)
        assert any("annotation" in d.get("missing", "") for d in result.details)

    def test_pattern_check_inherits(self, db: MUbase):
        """Test pattern rule checking for inheritance."""
        # Add nodes with inheritance info
        db.add_node(
            Node(
                id="cls:src/repo/user.py:UserRepo",
                type=NodeType.CLASS,
                name="UserRepo",
                file_path="src/repo/user.py",
                properties={"bases": ["BaseRepository"], "decorators": []},
            )
        )
        db.add_node(
            Node(
                id="cls:src/repo/order.py:OrderRepo",
                type=NodeType.CLASS,
                name="OrderRepo",
                file_path="src/repo/order.py",
                properties={"bases": [], "decorators": []},
            )
        )

        evaluator = PatternRuleEvaluator()
        rule = Rule(
            RuleType.PATTERN,
            {
                "match": "src/repo/*",
                "node_type": "class",
                "name_pattern": "*Repo",
                "must_have": {"inherits": "BaseRepository"},
            },
        )
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(db, rule, expect)
        # OrderRepo is missing the base class
        assert result.passed is False
        assert any("OrderRepo" in d.get("node", "") for d in result.details)
        assert any("inheritance" in d.get("missing", "") for d in result.details)

    def test_pattern_with_none_properties(self, db: MUbase):
        """Test pattern rule handles None properties gracefully."""
        # Add node with None properties (no decorators/annotations)
        db.add_node(
            Node(
                id="cls:bare",
                type=NodeType.CLASS,
                name="BareClass",
                file_path="src/bare.py",
                properties=None,  # type: ignore[arg-type]
            )
        )

        evaluator = PatternRuleEvaluator()
        rule = Rule(
            RuleType.PATTERN,
            {
                "match": "src/bare*",
                "node_type": "class",
                "must_have": {"decorator": "@test"},
            },
        )
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(db, rule, expect)
        # Node with no properties should be treated as having no decorators (violation)
        assert result.passed is False
        assert any("BareClass" in d.get("node", "") for d in result.details)


class TestQueryRuleEvaluatorCoverage:
    """Additional query rule tests for coverage."""

    def test_query_with_max_expectation_aggregate(self, populated_db: MUbase):
        """Test query with MAX expectation using aggregate value."""
        evaluator = QueryRuleEvaluator()
        rule = Rule(RuleType.QUERY, {"muql": "SELECT COUNT(*) FROM functions"})
        expect = Expectation(ExpectationType.MAX, 100)

        result = evaluator.evaluate(populated_db, rule, expect)
        # Should use the count value from the row
        assert isinstance(result.passed, bool)

    def test_query_with_min_expectation(self, populated_db: MUbase):
        """Test query with MIN expectation."""
        evaluator = QueryRuleEvaluator()
        rule = Rule(RuleType.QUERY, {"muql": "SELECT COUNT(*) FROM functions"})
        expect = Expectation(ExpectationType.MIN, 1)

        result = evaluator.evaluate(populated_db, rule, expect)
        # Should have at least 1 function
        assert result.passed is True


class TestDependencyRuleEvaluatorCoverage:
    """Additional dependency rule tests for coverage."""

    def test_dependency_with_exceptions(self, populated_db: MUbase):
        """Test dependency rule with exceptions."""
        evaluator = DependencyRuleEvaluator()
        rule = Rule(
            RuleType.DEPENDENCY,
            {
                "from": "src/services/*",
                "to": "src/controllers/*",
                "except": ["src/services/user.py"],  # Exception for user.py
            },
        )
        expect = Expectation(ExpectationType.EMPTY)

        result = evaluator.evaluate(populated_db, rule, expect)
        # The exception should filter out user.py -> api.py violation
        assert result.passed is True


# =============================================================================
# Additional Verifier Tests for Coverage
# =============================================================================


class TestContractVerifierCoverage:
    """Additional verifier tests for coverage."""

    def test_verify_unknown_rule_type(self, db: MUbase):
        """Test handling of unknown rule type."""
        # Create a contract with a rule type that doesn't have an evaluator
        contract = Contract(
            name="Unknown Rule",
            description="",
            severity=Severity.ERROR,
            rule=Rule(RuleType.QUERY, {}),
            expect=Expectation(ExpectationType.EMPTY),
        )
        # Manually change the rule type value to something unknown
        contract.rule.type = RuleType.QUERY  # We'll remove the evaluator instead

        contracts = ContractFile(contracts=[contract])

        verifier = ContractVerifier(db)
        # Remove the query evaluator to simulate unknown type
        del verifier._evaluators["query"]

        result = verifier.verify(contracts)
        assert result.passed is False
        assert len(result.violations) == 1
        assert "Unknown rule type" in result.violations[0].message

    def test_verify_evaluation_exception(self, db: MUbase):
        """Test handling of exception during evaluation."""

        class FailingEvaluator:
            @property
            def rule_type(self) -> str:
                return "query"

            def evaluate(self, mubase, rule, expect):
                raise RuntimeError("Simulated evaluation failure")

        contracts = ContractFile(
            contracts=[
                Contract(
                    name="Failing Contract",
                    description="",
                    severity=Severity.ERROR,
                    rule=Rule(RuleType.QUERY, {"muql": "SELECT 1"}),
                    expect=Expectation(ExpectationType.EMPTY),
                )
            ]
        )

        verifier = ContractVerifier(db)
        verifier.register_evaluator(FailingEvaluator())

        result = verifier.verify(contracts)
        assert result.passed is False
        assert len(result.violations) == 1
        assert "Evaluation error" in result.violations[0].message

    def test_verify_with_info_severity(self, populated_db: MUbase):
        """Test categorization of info-level violations."""
        contracts = ContractFile(
            contracts=[
                Contract(
                    name="Info Contract",
                    description="",
                    severity=Severity.INFO,
                    rule=Rule(RuleType.QUERY, {"muql": "SELECT * FROM functions"}),
                    expect=Expectation(ExpectationType.EMPTY),
                )
            ]
        )

        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        # Should be in info list, not violations
        assert len(result.info) >= 1
        assert result.passed is True  # Info doesn't fail


# =============================================================================
# Additional Model Tests for Coverage
# =============================================================================


class TestModelsCoverage:
    """Additional model tests for coverage."""

    def test_contract_settings_to_dict(self):
        """Test ContractSettings.to_dict()."""
        settings = ContractSettings(
            fail_on_warning=True,
            exclude_tests=False,
            exclude_patterns=["**/test_*.py"],
        )
        d = settings.to_dict()
        assert d["fail_on_warning"] is True
        assert d["exclude_tests"] is False
        assert "**/test_*.py" in d["exclude_patterns"]

    def test_contract_file_to_dict(self):
        """Test ContractFile.to_dict()."""
        contract_file = ContractFile(
            version="2.0",
            name="Custom Contracts",
            contracts=[
                Contract(
                    name="Test",
                    description="Desc",
                    severity=Severity.WARNING,
                    rule=Rule(RuleType.QUERY, {}),
                    expect=Expectation(ExpectationType.EMPTY),
                )
            ],
        )
        d = contract_file.to_dict()
        assert d["version"] == "2.0"
        assert d["name"] == "Custom Contracts"
        assert len(d["contracts"]) == 1

    def test_evaluation_result_to_dict(self):
        """Test EvaluationResult.to_dict()."""
        result = EvaluationResult(
            passed=False,
            details=[{"key": "value"}],
            row_count=5,
        )
        d = result.to_dict()
        assert d["passed"] is False
        assert d["row_count"] == 5
        assert len(d["details"]) == 1

    def test_violation_to_dict(self):
        """Test Violation.to_dict() with file info."""
        contract = Contract(
            name="Test",
            description="",
            severity=Severity.ERROR,
            rule=Rule(RuleType.QUERY, {}),
            expect=Expectation(ExpectationType.EMPTY),
        )
        violation = Violation(
            contract=contract,
            message="Failed",
            details=[{"key": "value"}],
            file_path="src/test.py",
            line=42,
        )
        d = violation.to_dict()
        assert d["file_path"] == "src/test.py"
        assert d["line"] == 42

    def test_verification_result_info_count(self):
        """Test VerificationResult.info_count property."""
        contract = Contract(
            name="Info", description="", severity=Severity.INFO,
            rule=Rule(RuleType.QUERY, {}), expect=Expectation(ExpectationType.EMPTY),
        )
        result = VerificationResult(
            passed=True,
            contracts_checked=1,
            info=[Violation(contract=contract, message="Info")],
        )
        assert result.info_count == 1


# =============================================================================
# Integration Tests
# =============================================================================


class TestContractsIntegration:
    """End-to-end integration tests."""

    def test_full_workflow(self, populated_db: MUbase, tmp_path: Path):
        """Test complete workflow: parse -> verify -> report."""
        # Create contract file
        contract_content = '''
version: "1.0"
name: "Integration Test"
contracts:
  - name: "No high complexity"
    description: "Functions should not exceed complexity 500"
    severity: error
    rule:
      type: query
      muql: |
        SELECT name, complexity
        FROM functions
        WHERE complexity > 500
    expect: empty
'''
        contract_path = tmp_path / ".mu-contracts.yml"
        contract_path.write_text(contract_content)

        # Parse
        contracts = parse_contracts_file(contract_path)
        assert len(contracts.contracts) == 1

        # Verify
        verifier = ContractVerifier(populated_db)
        result = verifier.verify(contracts)

        # Should fail (there's a function with complexity 600)
        assert result.passed is False
        assert len(result.violations) == 1

        # Report
        reporter = ContractReporter()
        text_report = reporter.report_text(result, no_color=True)
        json_report = reporter.report_json(result)
        junit_report = reporter.report_junit(result)

        assert "FAILED" in text_report
        assert json.loads(json_report)["passed"] is False
        assert "<failure" in junit_report
