"""Tests for task-aware context extraction (Intelligence Layer F1)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mu.intelligence import (
    EntityType,
    FileContext,
    TaskAnalysis,
    TaskAnalyzer,
    TaskContextConfig,
    TaskContextExtractor,
    TaskContextResult,
    TaskType,
)


class TestTaskType:
    """Tests for TaskType enum."""

    def test_task_type_values(self) -> None:
        """All expected task types exist."""
        assert TaskType.CREATE.value == "create"
        assert TaskType.MODIFY.value == "modify"
        assert TaskType.DELETE.value == "delete"
        assert TaskType.REFACTOR.value == "refactor"
        assert TaskType.DEBUG.value == "debug"
        assert TaskType.TEST.value == "test"
        assert TaskType.DOCUMENT.value == "document"
        assert TaskType.REVIEW.value == "review"


class TestEntityType:
    """Tests for EntityType enum."""

    def test_entity_type_values(self) -> None:
        """All expected entity types exist."""
        assert EntityType.API_ENDPOINT.value == "api_endpoint"
        assert EntityType.HOOK.value == "hook"
        assert EntityType.COMPONENT.value == "component"
        assert EntityType.SERVICE.value == "service"
        assert EntityType.REPOSITORY.value == "repository"
        assert EntityType.MODEL.value == "model"
        assert EntityType.FUNCTION.value == "function"
        assert EntityType.CLASS.value == "class"
        assert EntityType.MODULE.value == "module"
        assert EntityType.CONFIG.value == "config"
        assert EntityType.TEST.value == "test"
        assert EntityType.MIDDLEWARE.value == "middleware"
        assert EntityType.UNKNOWN.value == "unknown"


class TestTaskAnalyzer:
    """Tests for TaskAnalyzer."""

    @pytest.fixture
    def analyzer(self) -> TaskAnalyzer:
        """Create a TaskAnalyzer instance."""
        return TaskAnalyzer()

    # Task type detection tests
    def test_detect_create_task(self, analyzer: TaskAnalyzer) -> None:
        """Detects CREATE task type from keywords."""
        result = analyzer.analyze("Add a new API endpoint for user registration")
        assert result.task_type == TaskType.CREATE

    def test_detect_modify_task(self, analyzer: TaskAnalyzer) -> None:
        """Detects MODIFY task type from keywords."""
        result = analyzer.analyze("Update the authentication logic")
        assert result.task_type == TaskType.MODIFY

    def test_detect_delete_task(self, analyzer: TaskAnalyzer) -> None:
        """Detects DELETE task type from keywords."""
        result = analyzer.analyze("Remove the deprecated payment handler")
        assert result.task_type == TaskType.DELETE

    def test_detect_refactor_task(self, analyzer: TaskAnalyzer) -> None:
        """Detects REFACTOR task type from keywords."""
        result = analyzer.analyze("Refactor the UserService to use repository pattern")
        assert result.task_type == TaskType.REFACTOR

    def test_detect_debug_task(self, analyzer: TaskAnalyzer) -> None:
        """Detects DEBUG task type from keywords."""
        result = analyzer.analyze("Fix the bug in the login flow")
        assert result.task_type == TaskType.DEBUG

    def test_detect_test_task(self, analyzer: TaskAnalyzer) -> None:
        """Detects TEST task type from keywords."""
        result = analyzer.analyze("Write unit tests for the payment service")
        assert result.task_type == TaskType.TEST

    def test_detect_document_task(self, analyzer: TaskAnalyzer) -> None:
        """Detects DOCUMENT task type from keywords."""
        result = analyzer.analyze("Document the authentication flow")
        assert result.task_type == TaskType.DOCUMENT

    def test_detect_review_task(self, analyzer: TaskAnalyzer) -> None:
        """Detects REVIEW task type from keywords."""
        result = analyzer.analyze("Review the security of authentication code")
        assert result.task_type == TaskType.REVIEW

    def test_default_to_modify(self, analyzer: TaskAnalyzer) -> None:
        """Defaults to MODIFY when no clear indicators."""
        result = analyzer.analyze("Something about the code")
        assert result.task_type == TaskType.MODIFY

    # Entity type detection tests
    def test_detect_api_entity(self, analyzer: TaskAnalyzer) -> None:
        """Detects API endpoint entity type."""
        result = analyzer.analyze("Create a new REST API endpoint")
        assert EntityType.API_ENDPOINT in result.entity_types

    def test_detect_hook_entity(self, analyzer: TaskAnalyzer) -> None:
        """Detects hook entity type."""
        result = analyzer.analyze("Create a custom hook for authentication")
        assert EntityType.HOOK in result.entity_types

    def test_detect_service_entity(self, analyzer: TaskAnalyzer) -> None:
        """Detects service entity type."""
        result = analyzer.analyze("Add a new service for payment processing")
        assert EntityType.SERVICE in result.entity_types

    def test_detect_component_entity(self, analyzer: TaskAnalyzer) -> None:
        """Detects component entity type."""
        result = analyzer.analyze("Create a UserProfile component")
        assert EntityType.COMPONENT in result.entity_types

    def test_detect_repository_entity(self, analyzer: TaskAnalyzer) -> None:
        """Detects repository entity type."""
        result = analyzer.analyze("Add a UserRepository for data access")
        assert EntityType.REPOSITORY in result.entity_types

    def test_detect_model_entity(self, analyzer: TaskAnalyzer) -> None:
        """Detects model entity type."""
        result = analyzer.analyze("Create a Product model with price field")
        assert EntityType.MODEL in result.entity_types

    def test_detect_middleware_entity(self, analyzer: TaskAnalyzer) -> None:
        """Detects middleware entity type."""
        result = analyzer.analyze("Add rate limiting middleware")
        assert EntityType.MIDDLEWARE in result.entity_types

    def test_default_to_unknown_entity(self, analyzer: TaskAnalyzer) -> None:
        """Defaults to UNKNOWN when no entity type detected."""
        result = analyzer.analyze("Do something generic")
        assert EntityType.UNKNOWN in result.entity_types

    # Keyword extraction tests
    def test_extract_camel_case_keywords(self, analyzer: TaskAnalyzer) -> None:
        """Extracts CamelCase identifiers as keywords."""
        result = analyzer.analyze("Update the AuthService and UserModel")
        assert "AuthService" in result.keywords
        assert "UserModel" in result.keywords

    def test_extract_snake_case_keywords(self, analyzer: TaskAnalyzer) -> None:
        """Extracts snake_case identifiers as keywords."""
        result = analyzer.analyze("Fix the get_user_profile function")
        assert "get_user_profile" in result.keywords

    def test_extract_quoted_keywords(self, analyzer: TaskAnalyzer) -> None:
        """Extracts quoted strings as keywords."""
        result = analyzer.analyze('Update the "config.py" file')
        assert "config.py" in result.keywords

    def test_filters_stop_words(self, analyzer: TaskAnalyzer) -> None:
        """Filters common stop words from keywords."""
        result = analyzer.analyze("This should have some keywords that need filtering")
        assert "this" not in [k.lower() for k in result.keywords]
        assert "should" not in [k.lower() for k in result.keywords]
        assert "that" not in [k.lower() for k in result.keywords]

    # Domain detection tests
    def test_detect_auth_domain(self, analyzer: TaskAnalyzer) -> None:
        """Detects authentication domain hints."""
        result = analyzer.analyze("Fix the login authentication")
        assert "auth" in result.domain_hints

    def test_detect_payment_domain(self, analyzer: TaskAnalyzer) -> None:
        """Detects payment domain hints."""
        result = analyzer.analyze("Add billing integration")
        assert "payment" in result.domain_hints

    def test_detect_user_domain(self, analyzer: TaskAnalyzer) -> None:
        """Detects user domain hints."""
        result = analyzer.analyze("Update the user profile")
        assert "user" in result.domain_hints

    def test_detect_database_domain(self, analyzer: TaskAnalyzer) -> None:
        """Detects database domain hints."""
        result = analyzer.analyze("Optimize the SQL queries")
        assert "database" in result.domain_hints

    def test_detect_multiple_domains(self, analyzer: TaskAnalyzer) -> None:
        """Detects multiple domain hints."""
        result = analyzer.analyze("Fix the user authentication login flow")
        assert "auth" in result.domain_hints
        assert "user" in result.domain_hints

    # Confidence tests
    def test_confidence_increases_with_specificity(self, analyzer: TaskAnalyzer) -> None:
        """Confidence increases with more specific task descriptions."""
        vague = analyzer.analyze("Do something")
        specific = analyzer.analyze(
            "Add a new UserService class for handling authentication"
        )
        assert specific.confidence > vague.confidence

    def test_confidence_bounded(self, analyzer: TaskAnalyzer) -> None:
        """Confidence is bounded between 0 and 1."""
        result = analyzer.analyze(
            "Create a new REST API endpoint for user authentication "
            "with login and registration in the payment service"
        )
        assert 0.0 <= result.confidence <= 1.0


class TestTaskAnalysis:
    """Tests for TaskAnalysis dataclass."""

    def test_to_dict(self) -> None:
        """TaskAnalysis converts to dict correctly."""
        analysis = TaskAnalysis(
            original_task="Add authentication service",
            task_type=TaskType.CREATE,
            entity_types=[EntityType.SERVICE, EntityType.API_ENDPOINT],
            keywords=["AuthService", "authentication"],
            domain_hints=["auth"],
            confidence=0.85,
        )
        d = analysis.to_dict()

        assert d["original_task"] == "Add authentication service"
        assert d["task_type"] == "create"
        assert "service" in d["entity_types"]
        assert "api_endpoint" in d["entity_types"]
        assert "AuthService" in d["keywords"]
        assert "auth" in d["domain_hints"]
        assert d["confidence"] == 0.85


class TestFileContext:
    """Tests for FileContext dataclass."""

    def test_to_dict(self) -> None:
        """FileContext converts to dict correctly."""
        fc = FileContext(
            path="src/services/auth.py",
            relevance=0.95,
            reason="Contains AuthService class",
            is_entry_point=True,
            suggested_action="modify",
        )
        d = fc.to_dict()

        assert d["path"] == "src/services/auth.py"
        assert d["relevance"] == 0.95
        assert d["reason"] == "Contains AuthService class"
        assert d["is_entry_point"] is True
        assert d["suggested_action"] == "modify"


class TestTaskContextConfig:
    """Tests for TaskContextConfig."""

    def test_default_values(self) -> None:
        """TaskContextConfig has sensible defaults."""
        config = TaskContextConfig()

        assert config.max_tokens == 8000
        assert config.include_tests is True
        assert config.include_patterns is True
        assert config.max_files == 20
        assert config.max_examples == 5
        assert config.max_patterns == 5

    def test_custom_values(self) -> None:
        """TaskContextConfig accepts custom values."""
        config = TaskContextConfig(
            max_tokens=4000,
            include_tests=False,
            include_patterns=False,
            max_files=10,
        )

        assert config.max_tokens == 4000
        assert config.include_tests is False
        assert config.include_patterns is False
        assert config.max_files == 10


class TestTaskContextResult:
    """Tests for TaskContextResult dataclass."""

    def test_to_dict_empty(self) -> None:
        """Empty TaskContextResult converts to dict."""
        result = TaskContextResult()
        d = result.to_dict()

        assert d["relevant_files"] == []
        assert d["entry_points"] == []
        assert d["patterns"] == []
        assert d["mu_text"] == ""
        assert d["token_count"] == 0
        assert d["confidence"] == 0.0

    def test_to_dict_with_data(self) -> None:
        """TaskContextResult with data converts to dict correctly."""
        result = TaskContextResult(
            relevant_files=[
                FileContext(
                    path="src/auth.py",
                    relevance=0.9,
                    reason="Main auth file",
                    is_entry_point=True,
                    suggested_action="modify",
                )
            ],
            entry_points=["src/auth.py", "src/api/"],
            mu_text="!module auth\n$AuthService",
            token_count=100,
            confidence=0.85,
            task_analysis=TaskAnalysis(
                original_task="Fix auth",
                task_type=TaskType.DEBUG,
                entity_types=[EntityType.SERVICE],
                keywords=["auth"],
                domain_hints=["auth"],
                confidence=0.8,
            ),
        )
        d = result.to_dict()

        assert len(d["relevant_files"]) == 1
        assert d["relevant_files"][0]["path"] == "src/auth.py"
        assert d["entry_points"] == ["src/auth.py", "src/api/"]
        assert d["mu_text"] == "!module auth\n$AuthService"
        assert d["token_count"] == 100
        assert d["confidence"] == 0.85
        assert d["task_analysis"]["task_type"] == "debug"


class TestTaskContextExtractor:
    """Tests for TaskContextExtractor with a real MUbase."""

    @pytest.fixture
    def temp_mubase(self, tmp_path: Path):
        """Create a temporary MUbase with test data."""
        from mu.kernel import MUbase, NodeType
        from mu.kernel.models import Edge, Node
        from mu.kernel.schema import EdgeType

        mubase_path = tmp_path / ".mubase"
        db = MUbase(mubase_path)

        # Create test nodes
        nodes = [
            Node(
                id="mod:src/services/auth.py",
                type=NodeType.MODULE,
                name="auth",
                file_path="src/services/auth.py",
                line_start=1,
                line_end=100,
            ),
            Node(
                id="cls:src/services/auth.py:AuthService",
                type=NodeType.CLASS,
                name="AuthService",
                file_path="src/services/auth.py",
                line_start=10,
                line_end=80,
            ),
            Node(
                id="fn:src/services/auth.py:AuthService.login",
                type=NodeType.FUNCTION,
                name="login",
                file_path="src/services/auth.py",
                line_start=20,
                line_end=40,
            ),
            Node(
                id="mod:src/api/routes.py",
                type=NodeType.MODULE,
                name="routes",
                file_path="src/api/routes.py",
                line_start=1,
                line_end=50,
            ),
            Node(
                id="fn:src/api/routes.py:get_user",
                type=NodeType.FUNCTION,
                name="get_user",
                file_path="src/api/routes.py",
                line_start=10,
                line_end=25,
            ),
            Node(
                id="mod:src/models/user.py",
                type=NodeType.MODULE,
                name="user",
                file_path="src/models/user.py",
                line_start=1,
                line_end=30,
            ),
            Node(
                id="cls:src/models/user.py:UserModel",
                type=NodeType.CLASS,
                name="UserModel",
                file_path="src/models/user.py",
                line_start=5,
                line_end=25,
            ),
        ]

        edges = [
            Edge(
                id="edge:mod:src/services/auth.py:contains:cls:src/services/auth.py:AuthService",
                source_id="mod:src/services/auth.py",
                target_id="cls:src/services/auth.py:AuthService",
                type=EdgeType.CONTAINS,
            ),
            Edge(
                id="edge:cls:src/services/auth.py:AuthService:contains:fn:src/services/auth.py:AuthService.login",
                source_id="cls:src/services/auth.py:AuthService",
                target_id="fn:src/services/auth.py:AuthService.login",
                type=EdgeType.CONTAINS,
            ),
            Edge(
                id="edge:mod:src/api/routes.py:imports:mod:src/services/auth.py",
                source_id="mod:src/api/routes.py",
                target_id="mod:src/services/auth.py",
                type=EdgeType.IMPORTS,
            ),
        ]

        # Add nodes and edges
        for node in nodes:
            db.add_node(node)
        for edge in edges:
            db.add_edge(edge)

        yield db
        db.close()

    def test_extract_basic(self, temp_mubase) -> None:
        """Basic extraction returns results."""
        config = TaskContextConfig(include_patterns=False)  # Skip patterns for speed
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Fix the AuthService login")

        assert isinstance(result, TaskContextResult)
        assert result.task_analysis is not None
        assert result.task_analysis.task_type == TaskType.DEBUG

    def test_extract_finds_relevant_files(self, temp_mubase) -> None:
        """Extraction finds files matching keywords."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Update the AuthService")

        # Should find auth-related files
        file_paths = [f.path for f in result.relevant_files]
        assert any("auth" in p for p in file_paths)

    def test_extract_identifies_entry_points(self, temp_mubase) -> None:
        """Extraction identifies entry points."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Add API endpoint for users")

        # Should suggest API-related entry points
        assert len(result.entry_points) > 0

    def test_extract_generates_warnings(self, temp_mubase) -> None:
        """Extraction generates appropriate warnings."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Create a new PaymentService")

        # Should warn about creating new code
        assert len(result.warnings) > 0
        warning_messages = [w.message for w in result.warnings]
        assert any("pattern" in m.lower() or "new" in m.lower() for m in warning_messages)

    def test_extract_generates_suggestions(self, temp_mubase) -> None:
        """Extraction generates suggestions."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Modify the user model")

        # Should have suggestions
        assert len(result.suggestions) > 0

    def test_extract_respects_max_tokens(self, temp_mubase) -> None:
        """Extraction respects token budget."""
        config = TaskContextConfig(max_tokens=100, include_patterns=False)
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Show all auth code")

        # Token count should be within budget (with some tolerance)
        # Empty or minimal results are acceptable when budget is very low
        assert result.token_count <= 200  # Allow some overhead

    def test_extract_with_model_entity(self, temp_mubase) -> None:
        """Extraction works with model entity type."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Update the UserModel schema")

        assert result.task_analysis is not None
        assert EntityType.MODEL in result.task_analysis.entity_types

    def test_extract_confidence_is_set(self, temp_mubase) -> None:
        """Extraction sets confidence score."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Fix the AuthService authentication login")

        assert result.confidence > 0.0
        assert result.confidence <= 1.0

    def test_extract_stats_populated(self, temp_mubase) -> None:
        """Extraction populates stats dict."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(temp_mubase, config)

        result = extractor.extract("Update authentication")

        assert "task_length" in result.extraction_stats
        assert "task_type" in result.extraction_stats
        assert "extraction_time_ms" in result.extraction_stats


class TestTaskContextExtractorEdgeCases:
    """Edge case tests for TaskContextExtractor."""

    @pytest.fixture
    def empty_mubase(self, tmp_path: Path):
        """Create an empty MUbase."""
        from mu.kernel import MUbase

        mubase_path = tmp_path / ".mubase"
        db = MUbase(mubase_path)
        yield db
        db.close()

    def test_extract_empty_database(self, empty_mubase) -> None:
        """Extraction handles empty database gracefully."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(empty_mubase, config)

        result = extractor.extract("Add a new feature")

        assert isinstance(result, TaskContextResult)
        # Should handle gracefully with warnings
        assert any("no matching" in w.message.lower() for w in result.warnings)

    def test_extract_empty_task(self, empty_mubase) -> None:
        """Extraction handles empty task string."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(empty_mubase, config)

        result = extractor.extract("")

        assert isinstance(result, TaskContextResult)
        assert result.task_analysis is not None

    def test_extract_unicode_task(self, empty_mubase) -> None:
        """Extraction handles unicode in task description."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(empty_mubase, config)

        result = extractor.extract("Fix the 日本語 service")

        assert isinstance(result, TaskContextResult)

    def test_extract_very_long_task(self, empty_mubase) -> None:
        """Extraction handles very long task descriptions."""
        config = TaskContextConfig(include_patterns=False)
        extractor = TaskContextExtractor(empty_mubase, config)

        long_task = "Add a new feature " * 100
        result = extractor.extract(long_task)

        assert isinstance(result, TaskContextResult)
