"""Tests for the /contracts/verify endpoint in MU daemon.

Tests the contract verification HTTP API endpoint including:
- Valid contracts file verification
- Missing contracts file behavior (returns passed=true)
- Invalid contracts file (returns 400)
- Violation reporting format
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mu.daemon.config import DaemonConfig
from mu.kernel import MUbase, Node, NodeType


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
    """Create database with sample nodes for contract testing."""
    # Module node
    db.add_node(
        Node(
            id="mod:src/services/user.py",
            type=NodeType.MODULE,
            name="user",
            file_path="src/services/user.py",
            complexity=50,
        )
    )

    # Function with high complexity
    db.add_node(
        Node(
            id="fn:src/services/user.py:process",
            type=NodeType.FUNCTION,
            name="process",
            file_path="src/services/user.py",
            line_start=10,
            line_end=50,
            complexity=600,  # High complexity for violation testing
        )
    )

    # Function with normal complexity
    db.add_node(
        Node(
            id="fn:src/services/user.py:simple",
            type=NodeType.FUNCTION,
            name="simple",
            file_path="src/services/user.py",
            line_start=55,
            line_end=60,
            complexity=10,
        )
    )

    return db


@pytest.fixture
def contracts_file_passing(tmp_path: Path) -> Path:
    """Create a contracts file that will pass."""
    contracts_content = """
version: "1.0"
name: "Test Contracts"
contracts:
  - name: "Non-existent check"
    description: "This should find nothing"
    severity: error
    rule:
      type: query
      muql: "SELECT * FROM functions WHERE name = 'nonexistent_function_xyz'"
    expect: empty
"""
    contracts_path = tmp_path / ".mu-contracts.yml"
    contracts_path.write_text(contracts_content)
    return contracts_path


@pytest.fixture
def contracts_file_failing(tmp_path: Path) -> Path:
    """Create a contracts file that will have violations."""
    contracts_content = """
version: "1.0"
name: "Test Contracts"
contracts:
  - name: "High complexity check"
    description: "Functions should not exceed complexity 500"
    severity: error
    rule:
      type: query
      muql: "SELECT * FROM functions WHERE complexity > 500"
    expect: empty
"""
    contracts_path = tmp_path / ".mu-contracts.yml"
    contracts_path.write_text(contracts_content)
    return contracts_path


@pytest.fixture
def contracts_file_warning(tmp_path: Path) -> Path:
    """Create a contracts file with warnings."""
    contracts_content = """
version: "1.0"
name: "Test Contracts"
contracts:
  - name: "Moderate complexity warning"
    description: "Functions should ideally stay below 100 complexity"
    severity: warning
    rule:
      type: query
      muql: "SELECT * FROM functions WHERE complexity > 100"
    expect: empty
"""
    contracts_path = tmp_path / ".mu-contracts.yml"
    contracts_path.write_text(contracts_content)
    return contracts_path


@pytest.fixture
def contracts_file_invalid(tmp_path: Path) -> Path:
    """Create an invalid contracts file."""
    contracts_content = """
version: "1.0"
contracts:
  - name: "Invalid rule"
    rule:
      type: invalid_type
      some_param: value
    expect: empty
"""
    contracts_path = tmp_path / ".mu-contracts.yml"
    contracts_path.write_text(contracts_content)
    return contracts_path


@pytest.fixture
def app_client(db: MUbase, db_path: Path, tmp_path: Path):
    """Set up FastAPI test application."""
    from fastapi.testclient import TestClient

    from mu.daemon.server import create_app

    # Close the fixture db since app will open its own
    db.close()

    config = DaemonConfig(
        watch_paths=[tmp_path],
        debounce_ms=10,
    )

    app = create_app(db_path, config)
    with TestClient(app) as client:
        yield client


# =============================================================================
# Response Model Tests
# =============================================================================


class TestContractsResponseModels:
    """Tests for contracts-related Pydantic response models."""

    def test_contracts_request_model(self) -> None:
        """Test ContractsRequest model."""
        from mu.daemon.server import ContractsRequest

        request = ContractsRequest()
        assert request.contracts_path is None

        request_with_path = ContractsRequest(contracts_path=".custom-contracts.yml")
        assert request_with_path.contracts_path == ".custom-contracts.yml"

    def test_contract_violation_response_model(self) -> None:
        """Test ContractViolationResponse model."""
        from mu.daemon.server import ContractViolationResponse

        violation = ContractViolationResponse(
            contract="Test Contract",
            rule="query",
            message="Found 3 violations",
            severity="error",
            file_path="src/test.py",
            line=42,
            node_id="fn:test",
        )

        assert violation.contract == "Test Contract"
        assert violation.rule == "query"
        assert violation.message == "Found 3 violations"
        assert violation.severity == "error"
        assert violation.file_path == "src/test.py"
        assert violation.line == 42
        assert violation.node_id == "fn:test"

    def test_contract_violation_response_optional_fields(self) -> None:
        """Test ContractViolationResponse with optional fields."""
        from mu.daemon.server import ContractViolationResponse

        violation = ContractViolationResponse(
            contract="Test Contract",
            rule="query",
            message="Violation",
            severity="warning",
        )

        assert violation.file_path is None
        assert violation.line is None
        assert violation.node_id is None

    def test_contracts_response_model(self) -> None:
        """Test ContractsResponse model."""
        from mu.daemon.server import ContractViolationResponse, ContractsResponse

        response = ContractsResponse(
            passed=True,
            error_count=0,
            warning_count=0,
            violations=[],
        )

        assert response.passed is True
        assert response.error_count == 0
        assert response.warning_count == 0
        assert len(response.violations) == 0

    def test_contracts_response_with_violations(self) -> None:
        """Test ContractsResponse with violations."""
        from mu.daemon.server import ContractViolationResponse, ContractsResponse

        violations = [
            ContractViolationResponse(
                contract="Test",
                rule="query",
                message="Failed",
                severity="error",
            )
        ]

        response = ContractsResponse(
            passed=False,
            error_count=1,
            warning_count=0,
            violations=violations,
        )

        assert response.passed is False
        assert response.error_count == 1
        assert len(response.violations) == 1


# =============================================================================
# Endpoint Tests with Missing Contracts File
# =============================================================================


class TestContractsEndpointMissingFile:
    """Tests for /contracts/verify when contracts file is missing."""

    def test_verify_missing_contracts_file_returns_passed(self, app_client) -> None:
        """Test that missing contracts file returns passed=true."""
        response = app_client.post(
            "/contracts/verify",
            json={"contracts_path": "nonexistent.yml"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["passed"] is True
        assert data["error_count"] == 0
        assert data["warning_count"] == 0
        assert len(data["violations"]) == 0

    def test_verify_default_path_missing_returns_passed(self, app_client) -> None:
        """Test that missing default contracts file returns passed=true."""
        response = app_client.post(
            "/contracts/verify",
            json={},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["passed"] is True
        assert len(data["violations"]) == 0

    def test_verify_null_path_returns_passed(self, app_client) -> None:
        """Test that null contracts_path uses default and returns passed if missing."""
        response = app_client.post(
            "/contracts/verify",
            json={"contracts_path": None},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["passed"] is True


# =============================================================================
# Endpoint Tests with Valid Contracts File
# =============================================================================


class TestContractsEndpointValidFile:
    """Tests for /contracts/verify with valid contracts files."""

    def test_verify_passing_contracts(
        self, db: MUbase, db_path: Path, tmp_path: Path, contracts_file_passing: Path
    ) -> None:
        """Test verification of contracts that pass."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_file_passing)},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["passed"] is True
            assert data["error_count"] == 0
            assert len(data["violations"]) == 0

    def test_verify_failing_contracts(
        self, populated_db: MUbase, db_path: Path, tmp_path: Path, contracts_file_failing: Path
    ) -> None:
        """Test verification of contracts that fail."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        populated_db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_file_failing)},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["passed"] is False
            assert data["error_count"] >= 1
            assert len(data["violations"]) >= 1

            # Check violation structure
            violation = data["violations"][0]
            assert "contract" in violation
            assert "rule" in violation
            assert "message" in violation
            assert "severity" in violation
            assert violation["severity"] == "error"

    def test_verify_warning_contracts(
        self, populated_db: MUbase, db_path: Path, tmp_path: Path, contracts_file_warning: Path
    ) -> None:
        """Test verification of contracts with warnings."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        populated_db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_file_warning)},
            )

            assert response.status_code == 200
            data = response.json()
            # Warnings don't fail by default
            assert data["warning_count"] >= 1
            # Violations list contains both errors and warnings
            assert len(data["violations"]) >= 1

            # Check severity
            severities = [v["severity"] for v in data["violations"]]
            assert "warning" in severities


# =============================================================================
# Endpoint Tests with Invalid Contracts File
# =============================================================================


class TestContractsEndpointInvalidFile:
    """Tests for /contracts/verify with invalid contracts files."""

    def test_verify_invalid_contracts_returns_400(
        self, db: MUbase, db_path: Path, tmp_path: Path, contracts_file_invalid: Path
    ) -> None:
        """Test that invalid contracts file returns 400."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_file_invalid)},
            )

            assert response.status_code == 400
            assert "detail" in response.json()

    def test_verify_malformed_yaml_returns_400(
        self, db: MUbase, db_path: Path, tmp_path: Path
    ) -> None:
        """Test that malformed YAML returns 400."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        # Create malformed YAML file
        contracts_path = tmp_path / ".mu-contracts.yml"
        contracts_path.write_text("{{invalid yaml syntax")

        db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_path)},
            )

            assert response.status_code == 400
            assert "detail" in response.json()


# =============================================================================
# Endpoint Tests with Relative Paths
# =============================================================================


class TestContractsEndpointPaths:
    """Tests for /contracts/verify path resolution."""

    def test_verify_relative_path_resolution(
        self, db: MUbase, db_path: Path, tmp_path: Path
    ) -> None:
        """Test that relative paths are resolved from mubase parent."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        # Create contracts file in mubase parent directory
        contracts_path = db_path.parent / ".mu-contracts.yml"
        contracts_path.write_text("""
version: "1.0"
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT * FROM modules WHERE name = 'nonexistent'"
    expect: empty
""")

        db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            # Use relative path
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": ".mu-contracts.yml"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["passed"] is True

    def test_verify_absolute_path(
        self, db: MUbase, db_path: Path, tmp_path: Path
    ) -> None:
        """Test that absolute paths work correctly."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        # Create contracts file with absolute path
        contracts_path = tmp_path / "custom-contracts.yml"
        contracts_path.write_text("""
version: "1.0"
contracts:
  - name: "Test"
    rule:
      type: query
      muql: "SELECT * FROM modules WHERE name = 'nonexistent'"
    expect: empty
""")

        db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_path)},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["passed"] is True


# =============================================================================
# Violation Detail Tests
# =============================================================================


class TestContractsViolationDetails:
    """Tests for violation detail content."""

    def test_violation_includes_contract_name(
        self, populated_db: MUbase, db_path: Path, tmp_path: Path
    ) -> None:
        """Test that violations include the contract name."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        contracts_path = tmp_path / ".mu-contracts.yml"
        contracts_path.write_text("""
version: "1.0"
contracts:
  - name: "My Specific Contract Name"
    rule:
      type: query
      muql: "SELECT * FROM functions WHERE complexity > 500"
    expect: empty
""")

        populated_db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_path)},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["passed"] is False

            violation = data["violations"][0]
            assert violation["contract"] == "My Specific Contract Name"

    def test_violation_includes_rule_type(
        self, populated_db: MUbase, db_path: Path, tmp_path: Path
    ) -> None:
        """Test that violations include the rule type."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        contracts_path = tmp_path / ".mu-contracts.yml"
        contracts_path.write_text("""
version: "1.0"
contracts:
  - name: "Query Rule Test"
    rule:
      type: query
      muql: "SELECT * FROM functions WHERE complexity > 500"
    expect: empty
""")

        populated_db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_path)},
            )

            assert response.status_code == 200
            data = response.json()

            violation = data["violations"][0]
            assert violation["rule"] == "query"


# =============================================================================
# Edge Cases
# =============================================================================


class TestContractsEndpointEdgeCases:
    """Tests for edge cases in /contracts/verify endpoint."""

    def test_verify_empty_contracts_file(
        self, db: MUbase, db_path: Path, tmp_path: Path
    ) -> None:
        """Test verification with empty contracts file."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        contracts_path = tmp_path / ".mu-contracts.yml"
        contracts_path.write_text("")

        db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_path)},
            )

            # Empty file should be handled gracefully
            assert response.status_code == 200
            data = response.json()
            assert data["passed"] is True
            assert len(data["violations"]) == 0

    def test_verify_contracts_only_disabled(
        self, db: MUbase, db_path: Path, tmp_path: Path
    ) -> None:
        """Test verification with all contracts disabled."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        contracts_path = tmp_path / ".mu-contracts.yml"
        contracts_path.write_text("""
version: "1.0"
contracts:
  - name: "Disabled Contract"
    enabled: false
    rule:
      type: query
      muql: "SELECT * FROM functions"
    expect: empty
""")

        db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_path)},
            )

            assert response.status_code == 200
            data = response.json()
            # No contracts checked = passed
            assert data["passed"] is True
            assert len(data["violations"]) == 0

    def test_verify_multiple_violations(
        self, populated_db: MUbase, db_path: Path, tmp_path: Path
    ) -> None:
        """Test verification with multiple contract violations."""
        from fastapi.testclient import TestClient

        from mu.daemon.server import create_app

        contracts_path = tmp_path / ".mu-contracts.yml"
        contracts_path.write_text("""
version: "1.0"
contracts:
  - name: "High Complexity"
    severity: error
    rule:
      type: query
      muql: "SELECT * FROM functions WHERE complexity > 500"
    expect: empty
  - name: "Any Functions"
    severity: warning
    rule:
      type: query
      muql: "SELECT * FROM functions"
    expect: empty
""")

        populated_db.close()

        config = DaemonConfig(watch_paths=[tmp_path], debounce_ms=10)
        app = create_app(db_path, config)

        with TestClient(app) as client:
            response = client.post(
                "/contracts/verify",
                json={"contracts_path": str(contracts_path)},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["passed"] is False
            assert data["error_count"] >= 1
            assert data["warning_count"] >= 1
            # Should have violations from both contracts
            assert len(data["violations"]) >= 2
