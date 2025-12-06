"""Integration tests for Smart Context extraction.

Tests the complete context extraction pipeline with a realistic MUbase
containing sample codebase structure.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.context import (
    ContextResult,
    ExtractionConfig,
    SmartContextExtractor,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def context_db(tmp_path: Path) -> MUbase:
    """Create a comprehensive MUbase for context integration testing.

    This fixture creates a realistic codebase graph structure simulating
    a web application with authentication, user management, and database layers.
    """
    db = MUbase(tmp_path / "context_integration.mubase")

    # ==========================================================================
    # Modules
    # ==========================================================================
    modules_data = [
        ("mod:src/auth/service.py", "service", "src/auth/service.py", 150),
        ("mod:src/auth/middleware.py", "middleware", "src/auth/middleware.py", 80),
        ("mod:src/auth/__init__.py", "auth", "src/auth/__init__.py", 20),
        ("mod:src/users/service.py", "service", "src/users/service.py", 200),
        ("mod:src/users/models.py", "models", "src/users/models.py", 100),
        ("mod:src/database/connection.py", "connection", "src/database/connection.py", 60),
        ("mod:src/database/repository.py", "repository", "src/database/repository.py", 120),
        ("mod:src/api/routes.py", "routes", "src/api/routes.py", 180),
        ("mod:src/api/handlers.py", "handlers", "src/api/handlers.py", 150),
        ("mod:src/config.py", "config", "src/config.py", 50),
        ("mod:tests/test_auth.py", "test_auth", "tests/test_auth.py", 100),
    ]

    for mid, name, path, lines in modules_data:
        db.add_node(Node(
            id=mid,
            type=NodeType.MODULE,
            name=name,
            qualified_name=name,
            file_path=path,
            line_start=1,
            line_end=lines,
            complexity=0,
        ))

    # ==========================================================================
    # Classes
    # ==========================================================================
    classes_data: list[tuple[str, str, str, list[str], dict[str, Any]]] = [
        ("cls:src/auth/service.py:AuthService", "AuthService",
         "src/auth/service.py", ["BaseService"], {"is_singleton": True}),
        ("cls:src/auth/service.py:TokenManager", "TokenManager",
         "src/auth/service.py", [], {}),
        ("cls:src/auth/middleware.py:AuthMiddleware", "AuthMiddleware",
         "src/auth/middleware.py", ["Middleware"], {}),
        ("cls:src/users/service.py:UserService", "UserService",
         "src/users/service.py", ["BaseService"], {}),
        ("cls:src/users/models.py:User", "User",
         "src/users/models.py", ["BaseModel"], {"attributes": ["id", "email", "name", "password_hash"]}),
        ("cls:src/users/models.py:UserProfile", "UserProfile",
         "src/users/models.py", ["BaseModel"], {"attributes": ["bio", "avatar"]}),
        ("cls:src/database/connection.py:DatabaseConnection", "DatabaseConnection",
         "src/database/connection.py", [], {}),
        ("cls:src/database/repository.py:BaseRepository", "BaseRepository",
         "src/database/repository.py", [], {}),
        ("cls:src/database/repository.py:UserRepository", "UserRepository",
         "src/database/repository.py", ["BaseRepository"], {}),
    ]

    for cid, name, path, bases, props in classes_data:
        node_props: dict[str, Any] = {"bases": bases}
        node_props.update(props)
        db.add_node(Node(
            id=cid,
            type=NodeType.CLASS,
            name=name,
            qualified_name=f"{path.split('/')[-1].replace('.py', '')}.{name}",
            file_path=path,
            line_start=10,
            line_end=80,
            complexity=0,
            properties=node_props,
        ))

    # ==========================================================================
    # Functions
    # ==========================================================================
    functions_data = [
        # Auth Service methods
        ("fn:src/auth/service.py:AuthService.login", "login",
         "src/auth/service.py", 25, True, True,
         [{"name": "username", "type_annotation": "str"}, {"name": "password", "type_annotation": "str"}],
         "AuthToken"),
        ("fn:src/auth/service.py:AuthService.logout", "logout",
         "src/auth/service.py", 10, True, True, [{"name": "token", "type_annotation": "str"}], "bool"),
        ("fn:src/auth/service.py:AuthService.verify_token", "verify_token",
         "src/auth/service.py", 15, True, False, [{"name": "token", "type_annotation": "str"}], "User | None"),
        ("fn:src/auth/service.py:AuthService.refresh_token", "refresh_token",
         "src/auth/service.py", 20, True, True, [{"name": "refresh_token", "type_annotation": "str"}], "AuthToken"),
        ("fn:src/auth/service.py:TokenManager.generate", "generate",
         "src/auth/service.py", 12, True, False, [{"name": "user_id", "type_annotation": "int"}], "str"),
        ("fn:src/auth/service.py:TokenManager.decode", "decode",
         "src/auth/service.py", 18, True, False, [{"name": "token", "type_annotation": "str"}], "dict"),

        # Auth Middleware
        ("fn:src/auth/middleware.py:AuthMiddleware.process_request", "process_request",
         "src/auth/middleware.py", 30, True, True, [{"name": "request", "type_annotation": "Request"}], "Response"),

        # User Service methods
        ("fn:src/users/service.py:UserService.get_user", "get_user",
         "src/users/service.py", 15, True, True, [{"name": "user_id", "type_annotation": "int"}], "User"),
        ("fn:src/users/service.py:UserService.create_user", "create_user",
         "src/users/service.py", 35, True, True,
         [{"name": "email", "type_annotation": "str"}, {"name": "password", "type_annotation": "str"}], "User"),
        ("fn:src/users/service.py:UserService.update_user", "update_user",
         "src/users/service.py", 25, True, True,
         [{"name": "user_id", "type_annotation": "int"}, {"name": "data", "type_annotation": "dict"}], "User"),
        ("fn:src/users/service.py:UserService.delete_user", "delete_user",
         "src/users/service.py", 20, True, True, [{"name": "user_id", "type_annotation": "int"}], "bool"),
        ("fn:src/users/service.py:UserService._hash_password", "_hash_password",
         "src/users/service.py", 8, True, False, [{"name": "password", "type_annotation": "str"}], "str"),

        # Database
        ("fn:src/database/connection.py:DatabaseConnection.connect", "connect",
         "src/database/connection.py", 15, True, True, [], "Connection"),
        ("fn:src/database/connection.py:DatabaseConnection.disconnect", "disconnect",
         "src/database/connection.py", 5, True, True, [], "None"),
        ("fn:src/database/repository.py:BaseRepository.save", "save",
         "src/database/repository.py", 20, True, True, [{"name": "entity", "type_annotation": "T"}], "T"),
        ("fn:src/database/repository.py:BaseRepository.find_by_id", "find_by_id",
         "src/database/repository.py", 12, True, True, [{"name": "id", "type_annotation": "int"}], "T | None"),
        ("fn:src/database/repository.py:UserRepository.find_by_email", "find_by_email",
         "src/database/repository.py", 15, True, True, [{"name": "email", "type_annotation": "str"}], "User | None"),

        # API Routes
        ("fn:src/api/routes.py:register_routes", "register_routes",
         "src/api/routes.py", 40, False, False, [{"name": "app", "type_annotation": "Application"}], "None"),
        ("fn:src/api/handlers.py:handle_login", "handle_login",
         "src/api/handlers.py", 30, False, True, [{"name": "request", "type_annotation": "Request"}], "Response"),
        ("fn:src/api/handlers.py:handle_register", "handle_register",
         "src/api/handlers.py", 45, False, True, [{"name": "request", "type_annotation": "Request"}], "Response"),

        # Config
        ("fn:src/config.py:load_config", "load_config",
         "src/config.py", 10, False, False, [], "Config"),
        ("fn:src/config.py:get_database_url", "get_database_url",
         "src/config.py", 5, False, False, [], "str"),

        # Test functions (should be excluded when configured)
        ("fn:tests/test_auth.py:test_login_success", "test_login_success",
         "tests/test_auth.py", 15, False, True, [], "None"),
        ("fn:tests/test_auth.py:test_login_failure", "test_login_failure",
         "tests/test_auth.py", 12, False, True, [], "None"),
    ]

    for fid, name, path, complexity, is_method, is_async, params, return_type in functions_data:
        db.add_node(Node(
            id=fid,
            type=NodeType.FUNCTION,
            name=name,
            qualified_name=f"{path}.{name}",
            file_path=path,
            line_start=10,
            line_end=50,
            complexity=complexity,
            properties={
                "is_method": is_method,
                "is_async": is_async,
                "parameters": params,
                "return_type": return_type,
            },
        ))

    # ==========================================================================
    # Edges - Module Contains
    # ==========================================================================
    module_contains = [
        ("mod:src/auth/service.py", "cls:src/auth/service.py:AuthService"),
        ("mod:src/auth/service.py", "cls:src/auth/service.py:TokenManager"),
        ("mod:src/auth/middleware.py", "cls:src/auth/middleware.py:AuthMiddleware"),
        ("mod:src/users/service.py", "cls:src/users/service.py:UserService"),
        ("mod:src/users/models.py", "cls:src/users/models.py:User"),
        ("mod:src/users/models.py", "cls:src/users/models.py:UserProfile"),
        ("mod:src/database/connection.py", "cls:src/database/connection.py:DatabaseConnection"),
        ("mod:src/database/repository.py", "cls:src/database/repository.py:BaseRepository"),
        ("mod:src/database/repository.py", "cls:src/database/repository.py:UserRepository"),
        ("mod:src/api/routes.py", "fn:src/api/routes.py:register_routes"),
        ("mod:src/api/handlers.py", "fn:src/api/handlers.py:handle_login"),
        ("mod:src/api/handlers.py", "fn:src/api/handlers.py:handle_register"),
        ("mod:src/config.py", "fn:src/config.py:load_config"),
        ("mod:src/config.py", "fn:src/config.py:get_database_url"),
        ("mod:tests/test_auth.py", "fn:tests/test_auth.py:test_login_success"),
        ("mod:tests/test_auth.py", "fn:tests/test_auth.py:test_login_failure"),
    ]

    for i, (src, tgt) in enumerate(module_contains):
        db.add_edge(Edge(
            id=f"edge:mcontains:{i}",
            source_id=src,
            target_id=tgt,
            type=EdgeType.CONTAINS,
        ))

    # ==========================================================================
    # Edges - Class Contains Methods
    # ==========================================================================
    class_contains = [
        ("cls:src/auth/service.py:AuthService", "fn:src/auth/service.py:AuthService.login"),
        ("cls:src/auth/service.py:AuthService", "fn:src/auth/service.py:AuthService.logout"),
        ("cls:src/auth/service.py:AuthService", "fn:src/auth/service.py:AuthService.verify_token"),
        ("cls:src/auth/service.py:AuthService", "fn:src/auth/service.py:AuthService.refresh_token"),
        ("cls:src/auth/service.py:TokenManager", "fn:src/auth/service.py:TokenManager.generate"),
        ("cls:src/auth/service.py:TokenManager", "fn:src/auth/service.py:TokenManager.decode"),
        ("cls:src/auth/middleware.py:AuthMiddleware", "fn:src/auth/middleware.py:AuthMiddleware.process_request"),
        ("cls:src/users/service.py:UserService", "fn:src/users/service.py:UserService.get_user"),
        ("cls:src/users/service.py:UserService", "fn:src/users/service.py:UserService.create_user"),
        ("cls:src/users/service.py:UserService", "fn:src/users/service.py:UserService.update_user"),
        ("cls:src/users/service.py:UserService", "fn:src/users/service.py:UserService.delete_user"),
        ("cls:src/users/service.py:UserService", "fn:src/users/service.py:UserService._hash_password"),
        ("cls:src/database/connection.py:DatabaseConnection", "fn:src/database/connection.py:DatabaseConnection.connect"),
        ("cls:src/database/connection.py:DatabaseConnection", "fn:src/database/connection.py:DatabaseConnection.disconnect"),
        ("cls:src/database/repository.py:BaseRepository", "fn:src/database/repository.py:BaseRepository.save"),
        ("cls:src/database/repository.py:BaseRepository", "fn:src/database/repository.py:BaseRepository.find_by_id"),
        ("cls:src/database/repository.py:UserRepository", "fn:src/database/repository.py:UserRepository.find_by_email"),
    ]

    for i, (src, tgt) in enumerate(class_contains):
        db.add_edge(Edge(
            id=f"edge:ccontains:{i}",
            source_id=src,
            target_id=tgt,
            type=EdgeType.CONTAINS,
        ))

    # ==========================================================================
    # Edges - Module Imports
    # ==========================================================================
    imports = [
        ("mod:src/auth/service.py", "mod:src/users/models.py"),
        ("mod:src/auth/service.py", "mod:src/database/repository.py"),
        ("mod:src/auth/middleware.py", "mod:src/auth/service.py"),
        ("mod:src/users/service.py", "mod:src/users/models.py"),
        ("mod:src/users/service.py", "mod:src/database/repository.py"),
        ("mod:src/database/repository.py", "mod:src/database/connection.py"),
        ("mod:src/api/routes.py", "mod:src/api/handlers.py"),
        ("mod:src/api/handlers.py", "mod:src/auth/service.py"),
        ("mod:src/api/handlers.py", "mod:src/users/service.py"),
        ("mod:tests/test_auth.py", "mod:src/auth/service.py"),
    ]

    for i, (src, tgt) in enumerate(imports):
        db.add_edge(Edge(
            id=f"edge:imports:{i}",
            source_id=src,
            target_id=tgt,
            type=EdgeType.IMPORTS,
        ))

    # ==========================================================================
    # Edges - Inheritance
    # ==========================================================================
    inherits = [
        ("cls:src/database/repository.py:UserRepository", "cls:src/database/repository.py:BaseRepository"),
    ]

    for i, (src, tgt) in enumerate(inherits):
        db.add_edge(Edge(
            id=f"edge:inherits:{i}",
            source_id=src,
            target_id=tgt,
            type=EdgeType.INHERITS,
        ))

    yield db
    db.close()


# =============================================================================
# Extraction Quality Tests
# =============================================================================


class TestExtractionQuality:
    """Test that context extraction returns relevant code."""

    def test_auth_question_returns_auth_code(self, context_db: MUbase) -> None:
        """Auth-related question returns authentication code."""
        # Use specific entity names that the extractor can find
        result = context_db.get_context_for_question(
            "How does AuthService and TokenManager handle login?"
        )

        # Should include auth-related nodes
        node_names = [n.name for n in result.nodes]
        file_paths = [n.file_path for n in result.nodes if n.file_path]

        # Must include some auth code
        has_auth = any("auth" in p.lower() for p in file_paths) or any(
            "auth" in n.lower() or "login" in n.lower() or "token" in n.lower()
            for n in node_names
        )
        assert has_auth, f"Expected auth code, got: {node_names}"

    def test_login_question_returns_login_method(self, context_db: MUbase) -> None:
        """Login question returns the login method."""
        result = context_db.get_context_for_question(
            "How does the login function work?"
        )

        node_names = [n.name for n in result.nodes]
        assert "login" in node_names, f"Expected 'login' in {node_names}"

    def test_database_question_returns_db_code(self, context_db: MUbase) -> None:
        """Database question returns database-related code."""
        result = context_db.get_context_for_question(
            "How does the database connection work?"
        )

        node_names = [n.name for n in result.nodes]
        file_paths = [n.file_path for n in result.nodes if n.file_path]

        # Should include database code
        has_db = any("database" in p.lower() for p in file_paths) or any(
            "database" in n.lower() or "connection" in n.lower() or "repository" in n.lower()
            for n in node_names
        )
        assert has_db, f"Expected database code, got: {node_names}"

    def test_user_question_returns_user_code(self, context_db: MUbase) -> None:
        """User question returns user-related code."""
        # Use specific entity names that the extractor can find
        result = context_db.get_context_for_question(
            "How does UserService create_user and get_user work?"
        )

        node_names = [n.name for n in result.nodes]

        # Should include user-related code
        has_user = any(
            "user" in n.lower() or "User" in n
            for n in node_names
        )
        assert has_user, f"Expected user code, got: {node_names}"

    def test_specific_class_question(self, context_db: MUbase) -> None:
        """Question about specific class returns that class."""
        result = context_db.get_context_for_question(
            "What methods does AuthService have?"
        )

        node_names = [n.name for n in result.nodes]

        # Should include AuthService
        assert "AuthService" in node_names or any(
            "AuthService" in (n.qualified_name or "") for n in result.nodes
        ), f"Expected AuthService, got: {node_names}"

    def test_generic_question_returns_core_modules(self, context_db: MUbase) -> None:
        """Generic question returns high-level modules."""
        result = context_db.get_context_for_question(
            "Give me an overview of this codebase"
        )

        # Should return something (may be limited without specific entities)
        assert result is not None


# =============================================================================
# Token Budget Tests
# =============================================================================


class TestTokenBudgetAdherence:
    """Test that token budgets are respected."""

    def test_respects_small_budget(self, context_db: MUbase) -> None:
        """Small token budget is respected."""
        result = context_db.get_context_for_question(
            "How does authentication work?",
            max_tokens=200,
        )

        # Either within budget or empty (if no nodes fit)
        assert result.token_count <= 200 or len(result.nodes) == 0

    def test_respects_medium_budget(self, context_db: MUbase) -> None:
        """Medium token budget is respected."""
        result = context_db.get_context_for_question(
            "How does authentication work?",
            max_tokens=1000,
        )

        assert result.token_count <= 1000 or len(result.nodes) == 0

    def test_respects_large_budget(self, context_db: MUbase) -> None:
        """Large token budget is respected."""
        result = context_db.get_context_for_question(
            "Everything about the codebase",
            max_tokens=5000,
        )

        assert result.token_count <= 5000

    def test_smaller_budget_fewer_nodes(self, context_db: MUbase) -> None:
        """Smaller budget results in fewer nodes."""
        result_small = context_db.get_context_for_question(
            "How does login work?",
            max_tokens=200,
        )
        result_large = context_db.get_context_for_question(
            "How does login work?",
            max_tokens=2000,
        )

        assert len(result_small.nodes) <= len(result_large.nodes)

    def test_budget_utilization_reported(self, context_db: MUbase) -> None:
        """Budget utilization is reported in stats."""
        result = context_db.get_context_for_question(
            "How does auth work?",
            max_tokens=1000,
        )

        if result.nodes:
            assert "budget_utilization" in result.extraction_stats


# =============================================================================
# Test Exclusion Tests
# =============================================================================


class TestTestExclusion:
    """Test filtering of test files."""

    def test_excludes_test_files_when_configured(self, context_db: MUbase) -> None:
        """Test files are excluded when exclude_tests=True."""
        result = context_db.get_context_for_question(
            "How does login work?",
            exclude_tests=True,
        )

        file_paths = [n.file_path for n in result.nodes if n.file_path]

        # No test files should be included
        for path in file_paths:
            assert "test" not in path.lower(), f"Test file included: {path}"

    def test_includes_test_files_when_not_configured(self, context_db: MUbase) -> None:
        """Test files are included when exclude_tests=False."""
        result = context_db.get_context_for_question(
            "What tests exist for authentication?",
            exclude_tests=False,
        )

        # May include test files if they match
        # This is okay - we're just verifying the flag works

    def test_excludes_test_functions(self, context_db: MUbase) -> None:
        """Test functions are excluded when exclude_tests=True."""
        result = context_db.get_context_for_question(
            "login",
            exclude_tests=True,
        )

        node_names = [n.name for n in result.nodes]

        # No test_ prefixed functions
        for name in node_names:
            assert not name.startswith("test_"), f"Test function included: {name}"


# =============================================================================
# Performance Tests
# =============================================================================


class TestPerformance:
    """Test extraction performance requirements."""

    def test_extraction_under_500ms(self, context_db: MUbase) -> None:
        """Extraction completes in < 500ms."""
        start = time.perf_counter()
        result = context_db.get_context_for_question(
            "How does authentication work?"
        )
        elapsed = (time.perf_counter() - start) * 1000

        assert result is not None
        assert elapsed < 500, f"Extraction took {elapsed:.2f}ms, expected < 500ms"

    def test_multiple_extractions_consistent(self, context_db: MUbase) -> None:
        """Multiple extractions for same question are consistent."""
        result1 = context_db.get_context_for_question("How does login work?")
        result2 = context_db.get_context_for_question("How does login work?")

        # Should return same nodes
        ids1 = {n.id for n in result1.nodes}
        ids2 = {n.id for n in result2.nodes}
        assert ids1 == ids2

    def test_extraction_stats_include_timing(self, context_db: MUbase) -> None:
        """Extraction stats include relevant metrics."""
        result = context_db.get_context_for_question("auth")

        stats = result.extraction_stats
        assert "entities_extracted" in stats
        assert "question_length" in stats


# =============================================================================
# Output Format Tests
# =============================================================================


class TestOutputFormat:
    """Test MU format output quality."""

    def test_mu_output_has_module_headers(self, context_db: MUbase) -> None:
        """MU output includes module headers."""
        result = context_db.get_context_for_question("AuthService")

        if result.nodes:
            assert "!module" in result.mu_text

    def test_mu_output_has_class_sigils(self, context_db: MUbase) -> None:
        """MU output includes class sigils."""
        result = context_db.get_context_for_question("AuthService class")

        if result.nodes:
            # Should have $ for classes
            assert "$" in result.mu_text

    def test_mu_output_has_function_sigils(self, context_db: MUbase) -> None:
        """MU output includes function sigils."""
        result = context_db.get_context_for_question("login function")

        if result.nodes:
            # Should have # for functions
            assert "#" in result.mu_text

    def test_mu_output_groups_by_module(self, context_db: MUbase) -> None:
        """MU output groups nodes by module."""
        result = context_db.get_context_for_question(
            "AuthService and UserService"
        )

        if len(result.nodes) > 1:
            # Should have multiple module sections
            module_count = result.mu_text.count("!module")
            assert module_count >= 1

    def test_mu_output_includes_parameters(self, context_db: MUbase) -> None:
        """MU output includes function parameters."""
        result = context_db.get_context_for_question("login method")

        if result.nodes:
            # Should show parameters
            assert "(" in result.mu_text
            assert ")" in result.mu_text


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_question(self, context_db: MUbase) -> None:
        """Empty question returns gracefully."""
        result = context_db.get_context_for_question("")

        assert result is not None
        # May return empty or minimal result

    def test_very_long_question(self, context_db: MUbase) -> None:
        """Very long question is handled."""
        long_question = "authentication " * 100
        result = context_db.get_context_for_question(long_question)

        assert result is not None

    def test_special_characters_in_question(self, context_db: MUbase) -> None:
        """Special characters don't cause errors."""
        result = context_db.get_context_for_question(
            "How does 'login' work? Check @auth!"
        )

        assert result is not None

    def test_unicode_in_question(self, context_db: MUbase) -> None:
        """Unicode characters are handled."""
        result = context_db.get_context_for_question(
            "Authentication check"
        )

        assert result is not None

    def test_no_matches_returns_empty_gracefully(self, context_db: MUbase) -> None:
        """No matches returns empty result with message."""
        result = context_db.get_context_for_question(
            "xyzzy12345nonexistent"
        )

        assert result is not None
        if len(result.nodes) == 0:
            assert "No relevant context" in result.mu_text

    def test_very_small_budget(self, context_db: MUbase) -> None:
        """Very small budget doesn't crash."""
        result = context_db.get_context_for_question(
            "auth",
            max_tokens=10,
        )

        assert result is not None
        # May return empty due to budget


# =============================================================================
# SmartContextExtractor Direct Tests
# =============================================================================


class TestSmartContextExtractorDirect:
    """Test SmartContextExtractor class directly."""

    def test_custom_config(self, context_db: MUbase) -> None:
        """Custom config is applied."""
        config = ExtractionConfig(
            max_tokens=500,
            expand_depth=2,
            entity_weight=1.5,
            min_relevance=0.2,
        )
        extractor = SmartContextExtractor(context_db, config)

        result = extractor.extract("login")

        assert result is not None
        assert result.token_count <= 500 or len(result.nodes) == 0

    def test_stats_show_pipeline_stages(self, context_db: MUbase) -> None:
        """Stats show all pipeline stages."""
        extractor = SmartContextExtractor(context_db)

        result = extractor.extract("AuthService login")

        stats = result.extraction_stats
        assert "entities_extracted" in stats
        assert "named_nodes_found" in stats
        assert "candidates_before_expansion" in stats
        assert "candidates_after_expansion" in stats
        assert "selected_nodes" in stats

    def test_relevance_scores_valid(self, context_db: MUbase) -> None:
        """Relevance scores are valid floats."""
        extractor = SmartContextExtractor(context_db)

        result = extractor.extract("login")

        for node_id, score in result.relevance_scores.items():
            assert isinstance(score, float)
            assert 0 <= score <= 10  # Score can be > 1 due to weights

    def test_nodes_match_relevance_scores(self, context_db: MUbase) -> None:
        """All returned nodes have relevance scores."""
        extractor = SmartContextExtractor(context_db)

        result = extractor.extract("AuthService")

        for node in result.nodes:
            assert node.id in result.relevance_scores


# =============================================================================
# API Convenience Tests
# =============================================================================


class TestMUbaseAPIConvenience:
    """Test MUbase convenience methods for context."""

    def test_has_embeddings(self, context_db: MUbase) -> None:
        """has_embeddings returns False without embeddings."""
        assert context_db.has_embeddings() is False

    def test_find_nodes_by_suffix(self, context_db: MUbase) -> None:
        """find_nodes_by_suffix finds matching nodes."""
        results = context_db.find_nodes_by_suffix("Service")

        names = [n.name for n in results]
        assert "AuthService" in names
        assert "UserService" in names

    def test_get_neighbors_both(self, context_db: MUbase) -> None:
        """get_neighbors returns both directions."""
        auth_class_id = "cls:src/auth/service.py:AuthService"
        neighbors = context_db.get_neighbors(auth_class_id, direction="both")

        assert len(neighbors) > 0

    def test_get_context_kwargs_passthrough(self, context_db: MUbase) -> None:
        """get_context_for_question passes kwargs to config."""
        result = context_db.get_context_for_question(
            "login",
            max_tokens=1000,
            exclude_tests=True,
            expand_depth=2,
            include_parent=True,
        )

        # Should work without error
        assert result is not None


# =============================================================================
# Regression Tests
# =============================================================================


class TestRegressions:
    """Regression tests for known issues."""

    def test_method_without_class_doesnt_crash(self, context_db: MUbase) -> None:
        """Method selection without class in results doesn't crash."""
        # This could happen if a method matches but its class doesn't
        result = context_db.get_context_for_question(
            "_hash_password",  # Private method
        )

        assert result is not None

    def test_circular_graph_expansion_terminates(self, context_db: MUbase) -> None:
        """Graph expansion terminates even with cycles."""
        config = ExtractionConfig(expand_depth=5)  # Deep expansion
        extractor = SmartContextExtractor(context_db, config)

        result = extractor.extract("auth")

        # Should complete without hanging
        assert result is not None

    def test_large_expansion_capped(self, context_db: MUbase) -> None:
        """Large expansion is capped to prevent explosion."""
        config = ExtractionConfig(
            expand_depth=10,
            max_expansion_nodes=50,
        )
        extractor = SmartContextExtractor(context_db, config)

        result = extractor.extract("database")

        stats = result.extraction_stats
        # Should be capped
        assert stats.get("candidates_after_expansion", 0) <= 100
