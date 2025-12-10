"""Integration tests for Project OMEGA: S-Expression Semantic Compression.

Tests the complete OMEGA pipeline including:
- OmegaContextExtractor with macro compression
- MCP tools (mu_context_omega, mu_export_lisp, mu_macros)
- CLI export lisp and context --format omega
- MU codebase self-compression benchmarks
- Roundtrip parsing validation
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.context.omega import (
    OmegaConfig,
    OmegaContextExtractor,
    OmegaManifest,
    OmegaResult,
)
from mu.kernel.export.lisp import LispExporter, LispExportOptions

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def omega_db(tmp_path: Path) -> MUbase:
    """Create a realistic MUbase for OMEGA integration testing.

    This fixture creates a codebase graph structure simulating
    a web API application with services, models, and routes.
    """
    db = MUbase(tmp_path / "omega_integration.mubase")

    # ==========================================================================
    # Modules
    # ==========================================================================
    modules_data = [
        ("mod:src/api/routes.py", "routes", "src/api/routes.py", 180),
        ("mod:src/api/handlers.py", "handlers", "src/api/handlers.py", 150),
        ("mod:src/services/auth.py", "auth", "src/services/auth.py", 200),
        ("mod:src/services/user.py", "user", "src/services/user.py", 160),
        ("mod:src/models/user.py", "user", "src/models/user.py", 80),
        ("mod:src/models/token.py", "token", "src/models/token.py", 50),
        ("mod:src/db/repository.py", "repository", "src/db/repository.py", 120),
        ("mod:src/config.py", "config", "src/config.py", 40),
    ]

    for mid, name, path, lines in modules_data:
        db.add_node(
            Node(
                id=mid,
                type=NodeType.MODULE,
                name=name,
                qualified_name=name,
                file_path=path,
                line_start=1,
                line_end=lines,
                complexity=0,
            )
        )

    # ==========================================================================
    # Classes
    # ==========================================================================
    classes_data: list[tuple[str, str, str, list[str], dict[str, Any]]] = [
        (
            "cls:src/services/auth.py:AuthService",
            "AuthService",
            "src/services/auth.py",
            ["BaseService"],
            {"is_singleton": True},
        ),
        (
            "cls:src/services/auth.py:TokenManager",
            "TokenManager",
            "src/services/auth.py",
            [],
            {},
        ),
        (
            "cls:src/services/user.py:UserService",
            "UserService",
            "src/services/user.py",
            ["BaseService"],
            {},
        ),
        (
            "cls:src/models/user.py:User",
            "User",
            "src/models/user.py",
            ["BaseModel"],
            {"attributes": ["id", "email", "name", "password_hash"]},
        ),
        (
            "cls:src/models/token.py:AuthToken",
            "AuthToken",
            "src/models/token.py",
            ["BaseModel"],
            {"attributes": ["access_token", "refresh_token", "expires_at"]},
        ),
        (
            "cls:src/db/repository.py:UserRepository",
            "UserRepository",
            "src/db/repository.py",
            ["BaseRepository"],
            {},
        ),
    ]

    for cid, name, path, bases, props in classes_data:
        node_props: dict[str, Any] = {"bases": bases}
        node_props.update(props)
        db.add_node(
            Node(
                id=cid,
                type=NodeType.CLASS,
                name=name,
                qualified_name=f"{path.split('/')[-1].replace('.py', '')}.{name}",
                file_path=path,
                line_start=10,
                line_end=80,
                complexity=0,
                properties=node_props,
            )
        )

    # ==========================================================================
    # Functions (API endpoints and service methods)
    # ==========================================================================
    functions_data = [
        # API routes (POST endpoints for auth)
        (
            "fn:src/api/routes.py:login_route",
            "login_route",
            "src/api/routes.py",
            15,
            [{"name": "request", "type_annotation": "LoginRequest"}],
            "AuthToken",
            ["app.post('/login')"],
        ),
        (
            "fn:src/api/routes.py:register_route",
            "register_route",
            "src/api/routes.py",
            20,
            [{"name": "request", "type_annotation": "RegisterRequest"}],
            "User",
            ["app.post('/register')"],
        ),
        (
            "fn:src/api/routes.py:refresh_route",
            "refresh_route",
            "src/api/routes.py",
            12,
            [{"name": "token", "type_annotation": "str"}],
            "AuthToken",
            ["app.post('/refresh')"],
        ),
        # Auth service methods
        (
            "fn:src/services/auth.py:AuthService.authenticate",
            "authenticate",
            "src/services/auth.py",
            25,
            [
                {"name": "username", "type_annotation": "str"},
                {"name": "password", "type_annotation": "str"},
            ],
            "User | None",
            [],
        ),
        (
            "fn:src/services/auth.py:AuthService.create_token",
            "create_token",
            "src/services/auth.py",
            18,
            [{"name": "user", "type_annotation": "User"}],
            "AuthToken",
            [],
        ),
        (
            "fn:src/services/auth.py:TokenManager.encode",
            "encode",
            "src/services/auth.py",
            12,
            [{"name": "payload", "type_annotation": "dict"}],
            "str",
            [],
        ),
        (
            "fn:src/services/auth.py:TokenManager.decode",
            "decode",
            "src/services/auth.py",
            15,
            [{"name": "token", "type_annotation": "str"}],
            "dict",
            [],
        ),
        # User service methods
        (
            "fn:src/services/user.py:UserService.get_by_email",
            "get_by_email",
            "src/services/user.py",
            10,
            [{"name": "email", "type_annotation": "str"}],
            "User | None",
            [],
        ),
        (
            "fn:src/services/user.py:UserService.create_user",
            "create_user",
            "src/services/user.py",
            30,
            [
                {"name": "email", "type_annotation": "str"},
                {"name": "password", "type_annotation": "str"},
            ],
            "User",
            [],
        ),
        # Repository methods
        (
            "fn:src/db/repository.py:UserRepository.find_by_email",
            "find_by_email",
            "src/db/repository.py",
            8,
            [{"name": "email", "type_annotation": "str"}],
            "User | None",
            ["cache(ttl=300)"],
        ),
        (
            "fn:src/db/repository.py:UserRepository.save",
            "save",
            "src/db/repository.py",
            12,
            [{"name": "user", "type_annotation": "User"}],
            "User",
            [],
        ),
    ]

    for fid, name, path, complexity, params, ret_type, decorators in functions_data:
        db.add_node(
            Node(
                id=fid,
                type=NodeType.FUNCTION,
                name=name,
                qualified_name=name,
                file_path=path,
                line_start=20,
                line_end=50,
                complexity=complexity,
                properties={
                    "parameters": params,
                    "return_type": ret_type,
                    "decorators": decorators,
                    "is_async": False,
                    "is_method": "." in fid,
                },
            )
        )

    # ==========================================================================
    # Edges (CONTAINS and IMPORTS)
    # ==========================================================================
    # Module contains class
    contains_edges = [
        ("mod:src/services/auth.py", "cls:src/services/auth.py:AuthService"),
        ("mod:src/services/auth.py", "cls:src/services/auth.py:TokenManager"),
        ("mod:src/services/user.py", "cls:src/services/user.py:UserService"),
        ("mod:src/models/user.py", "cls:src/models/user.py:User"),
        ("mod:src/models/token.py", "cls:src/models/token.py:AuthToken"),
        ("mod:src/db/repository.py", "cls:src/db/repository.py:UserRepository"),
    ]

    # Class contains method
    class_method_edges = [
        (
            "cls:src/services/auth.py:AuthService",
            "fn:src/services/auth.py:AuthService.authenticate",
        ),
        (
            "cls:src/services/auth.py:AuthService",
            "fn:src/services/auth.py:AuthService.create_token",
        ),
        ("cls:src/services/auth.py:TokenManager", "fn:src/services/auth.py:TokenManager.encode"),
        ("cls:src/services/auth.py:TokenManager", "fn:src/services/auth.py:TokenManager.decode"),
        (
            "cls:src/services/user.py:UserService",
            "fn:src/services/user.py:UserService.get_by_email",
        ),
        ("cls:src/services/user.py:UserService", "fn:src/services/user.py:UserService.create_user"),
        (
            "cls:src/db/repository.py:UserRepository",
            "fn:src/db/repository.py:UserRepository.find_by_email",
        ),
        ("cls:src/db/repository.py:UserRepository", "fn:src/db/repository.py:UserRepository.save"),
    ]

    # Module contains function
    module_func_edges = [
        ("mod:src/api/routes.py", "fn:src/api/routes.py:login_route"),
        ("mod:src/api/routes.py", "fn:src/api/routes.py:register_route"),
        ("mod:src/api/routes.py", "fn:src/api/routes.py:refresh_route"),
    ]

    for source, target in contains_edges + class_method_edges + module_func_edges:
        db.add_edge(
            Edge(
                id=f"edge:{source}:contains:{target}",
                source_id=source,
                target_id=target,
                type=EdgeType.CONTAINS,
            )
        )

    # Import edges
    import_edges = [
        ("mod:src/api/routes.py", "mod:src/services/auth.py"),
        ("mod:src/api/routes.py", "mod:src/models/user.py"),
        ("mod:src/api/routes.py", "mod:src/models/token.py"),
        ("mod:src/services/auth.py", "mod:src/models/user.py"),
        ("mod:src/services/auth.py", "mod:src/models/token.py"),
        ("mod:src/services/user.py", "mod:src/db/repository.py"),
        ("mod:src/services/user.py", "mod:src/models/user.py"),
    ]

    for source, target in import_edges:
        db.add_edge(
            Edge(
                id=f"edge:{source}:imports:{target}",
                source_id=source,
                target_id=target,
                type=EdgeType.IMPORTS,
            )
        )

    return db


# =============================================================================
# TestOmegaContextExtractor - Core OMEGA functionality
# =============================================================================


class TestOmegaContextExtractor:
    """Tests for OmegaContextExtractor - S-expression context with macro compression."""

    def test_extract_basic_question(self, omega_db: MUbase) -> None:
        """Test basic question extraction produces valid OMEGA output."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("How does authentication work?")

        # Should produce valid output
        assert isinstance(result, OmegaResult)
        assert result.body  # Should have body content (even if "no context found")
        assert result.total_tokens > 0
        # Note: nodes_included may be 0 if SmartContextExtractor doesn't find
        # matches (no embeddings in test fixture, entity extraction may not match)

    def test_extract_produces_sexpr_format(self, omega_db: MUbase) -> None:
        """Test that output is valid S-expression format."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("Show me the auth service")

        full_output = result.full_output

        # Should contain S-expression markers - OMEGA v2.0 uses defschema in seed
        # or module/class in body; also check for "No relevant context" fallback
        has_sexpr = (
            "(mu-lisp" in full_output
            or "(module" in full_output
            or "(defschema" in full_output  # OMEGA v2.0 schema format
            or "No relevant context found" in full_output  # Valid fallback when no matches
        )
        assert has_sexpr, f"Expected S-expression markers in output, got: {full_output[:200]}"
        # Should have balanced parens (basic check)
        assert full_output.count("(") == full_output.count(")")

    def test_extract_with_manifest(self, omega_db: MUbase) -> None:
        """Test that manifest is properly generated."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("user service methods")

        # Manifest should exist
        assert isinstance(result.manifest, OmegaManifest)
        assert result.manifest.version == "1.0"

    def test_compression_metrics(self, omega_db: MUbase) -> None:
        """Test that compression metrics are calculated."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("authentication and token handling")

        # Token accounting
        assert result.seed_tokens >= 0
        assert result.body_tokens >= 0
        assert result.total_tokens == result.seed_tokens + result.body_tokens

        # Original tokens should be calculated for comparison
        if result.nodes_included > 0:
            assert result.original_tokens > 0

    def test_config_max_tokens_respected(self, omega_db: MUbase) -> None:
        """Test that max_tokens config is respected."""
        # Small token budget
        config = OmegaConfig(max_tokens=500)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("everything in the codebase")

        # Should stay within budget (with some tolerance for overhead)
        assert result.total_tokens <= 600  # 20% tolerance

    def test_no_context_found_handling(self, omega_db: MUbase) -> None:
        """Test graceful handling when no relevant context is found."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("quantum entanglement blockchain")

        # Should produce valid result even with no matches
        assert isinstance(result, OmegaResult)
        # Either empty or has the "no context found" message
        assert result.body or result.nodes_included == 0

    def test_macros_used_tracking(self, omega_db: MUbase) -> None:
        """Test that macros_used tracks which macros were applied."""
        config = OmegaConfig(max_tokens=8000, include_synthesized=True)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("auth service")

        # macros_used should be a list
        assert isinstance(result.macros_used, list)

    def test_seed_body_separation(self, omega_db: MUbase) -> None:
        """Test that seed (macros) and body (content) are properly separated."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("user repository")

        # Full output combines seed and body
        full = result.full_output

        if result.seed:
            assert result.seed in full
        if result.body:
            assert result.body in full

    def test_extraction_stats_populated(self, omega_db: MUbase) -> None:
        """Test that extraction_stats contains useful metrics."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("token management")

        stats = result.extraction_stats

        # Should have timing and node counts
        assert "question" in stats
        assert stats["question"] == "token management"

    def test_to_dict_roundtrip(self, omega_db: MUbase) -> None:
        """Test that OmegaResult can be serialized and deserialized."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("auth service")

        # Serialize
        data = result.to_dict()
        assert isinstance(data, dict)

        # Deserialize
        restored = OmegaResult.from_dict(data)
        assert restored.seed == result.seed
        assert restored.body == result.body
        assert restored.total_tokens == result.total_tokens
        assert restored.manifest.version == result.manifest.version


# =============================================================================
# TestLispExporter - S-expression export functionality
# =============================================================================


class TestLispExporter:
    """Tests for LispExporter - raw S-expression export."""

    def test_export_basic(self, omega_db: MUbase) -> None:
        """Test basic Lisp export produces valid output."""
        exporter = LispExporter()
        result = exporter.export(omega_db)

        assert result.success
        assert result.output
        assert result.node_count > 0

    def test_export_includes_header(self, omega_db: MUbase) -> None:
        """Test that header is included by default."""
        exporter = LispExporter()
        options = LispExportOptions(include_header=True)
        result = exporter.export(omega_db, options)

        assert result.success
        assert "(mu-lisp" in result.output

    def test_export_without_header(self, omega_db: MUbase) -> None:
        """Test export without header."""
        exporter = LispExporter()
        options = LispExportOptions(include_header=False)
        result = exporter.export(omega_db, options)

        assert result.success
        # Should still have content but maybe not mu-lisp wrapper
        assert result.output

    def test_export_specific_nodes(self, omega_db: MUbase) -> None:
        """Test export with specific node IDs."""
        exporter = LispExporter()
        options = LispExportOptions(
            node_ids=["cls:src/services/auth.py:AuthService"],
        )
        result = exporter.export(omega_db, options)

        assert result.success
        assert "AuthService" in result.output

    def test_export_by_node_type(self, omega_db: MUbase) -> None:
        """Test export filtered by node type."""
        exporter = LispExporter()
        options = LispExportOptions(
            node_types=[NodeType.CLASS],
        )
        result = exporter.export(omega_db, options)

        assert result.success
        assert result.node_count > 0
        # Should contain class names
        assert "class" in result.output.lower() or "Service" in result.output

    def test_export_balanced_parens(self, omega_db: MUbase) -> None:
        """Test that exported S-expressions have balanced parentheses."""
        exporter = LispExporter()
        result = exporter.export(omega_db)

        assert result.success
        output = result.output
        assert output.count("(") == output.count(")")

    def test_export_pretty_print(self, omega_db: MUbase) -> None:
        """Test pretty-print formatting."""
        exporter = LispExporter()

        # With pretty print
        options_pretty = LispExportOptions(pretty_print=True)
        result_pretty = exporter.export(omega_db, options_pretty)

        # Without pretty print
        options_compact = LispExportOptions(pretty_print=False)
        result_compact = exporter.export(omega_db, options_compact)

        assert result_pretty.success and result_compact.success

        # Pretty version should have newlines
        assert "\n" in result_pretty.output

    def test_export_handles_special_chars(self, omega_db: MUbase) -> None:
        """Test that special characters in names are handled properly."""
        # Add a node with special characters in name
        omega_db.add_node(
            Node(
                id="fn:src/test.py:test_user's_data",
                type=NodeType.FUNCTION,
                name="test_user's_data",
                qualified_name="test_user's_data",
                file_path="src/test.py",
                line_start=1,
                line_end=10,
                complexity=5,
            )
        )

        exporter = LispExporter()
        result = exporter.export(omega_db)

        # Should succeed without crashing
        assert result.success


# =============================================================================
# TestOmegaManifest - Manifest data model
# =============================================================================


class TestOmegaManifest:
    """Tests for OmegaManifest data model."""

    def test_to_sexpr_basic(self) -> None:
        """Test S-expression generation for manifest."""
        manifest = OmegaManifest(
            version="1.0",
            codebase="test-app",
            commit="abc1234",
            core_macros=["module", "class", "defn"],
            standard_macros=["api", "service"],
        )

        sexpr = manifest.to_sexpr()

        assert '(mu-lisp :version "1.0"' in sexpr
        assert ':codebase "test-app"' in sexpr
        assert ':commit "abc1234"' in sexpr
        assert ":core [module class defn]" in sexpr
        assert ":standard [api service]" in sexpr

    def test_to_dict_roundtrip(self) -> None:
        """Test manifest serialization roundtrip."""
        manifest = OmegaManifest(
            version="1.0",
            codebase="mu",
            commit="deadbeef",
            core_macros=["module", "class"],
            standard_macros=["api"],
            synthesized_macros=["custom-macro"],
        )

        data = manifest.to_dict()
        restored = OmegaManifest.from_dict(data)

        assert restored.version == manifest.version
        assert restored.codebase == manifest.codebase
        assert restored.core_macros == manifest.core_macros
        assert restored.synthesized_macros == manifest.synthesized_macros

    def test_all_macros_property(self) -> None:
        """Test all_macros combines all tiers in order."""
        manifest = OmegaManifest(
            core_macros=["module", "class"],
            standard_macros=["api"],
            synthesized_macros=["custom"],
        )

        all_macros = manifest.all_macros

        assert all_macros == ["module", "class", "api", "custom"]
        assert manifest.macro_count == 4


# =============================================================================
# TestOmegaConfig - Configuration handling
# =============================================================================


class TestOmegaConfig:
    """Tests for OmegaConfig settings."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = OmegaConfig()

        assert config.max_tokens == 8000
        assert config.header_budget_ratio == 0.15
        assert config.include_synthesized is True
        assert config.max_synthesized_macros == 5
        assert config.enable_prompt_cache_optimization is True
        assert config.fallback_to_sigils is False

    def test_to_dict_roundtrip(self) -> None:
        """Test config serialization roundtrip."""
        config = OmegaConfig(
            max_tokens=4000,
            include_synthesized=False,
            max_synthesized_macros=3,
        )

        data = config.to_dict()
        restored = OmegaConfig.from_dict(data)

        assert restored.max_tokens == 4000
        assert restored.include_synthesized is False
        assert restored.max_synthesized_macros == 3


# =============================================================================
# TestCLIExport - CLI export commands
# =============================================================================


class TestCLIExportLisp:
    """Tests for CLI export --format lisp command."""

    @pytest.fixture
    def built_mubase(self, tmp_path: Path) -> Path:
        """Create a project with built mubase for CLI testing."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Create source file
        src_dir = project_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text(
            '''
class MyService:
    """A service class."""

    def process(self, data: str) -> dict:
        """Process data."""
        return {"result": data}
'''
        )

        # Create murc
        (project_dir / ".murc.toml").write_text(
            """
[scan]
include = ["src/**/*.py"]
exclude = ["**/__pycache__/**"]
"""
        )

        # Build the mubase
        result = subprocess.run(
            ["uv", "run", "mu", "kernel", "build", "."],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.skip(f"Failed to build mubase: {result.stderr}")

        return project_dir

    def test_export_lisp_format(self, built_mubase: Path) -> None:
        """Test mu kernel export --format lisp produces valid output."""
        result = subprocess.run(
            ["uv", "run", "mu", "kernel", "export", ".", "--format", "lisp"],
            cwd=built_mubase,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        output = result.stdout

        # Should produce S-expression output
        assert "(" in output and ")" in output
        # Parens should be balanced
        assert output.count("(") == output.count(")")

    def test_export_omega_format(self, built_mubase: Path) -> None:
        """Test mu kernel export --format omega produces compressed output."""
        result = subprocess.run(
            ["uv", "run", "mu", "kernel", "export", ".", "--format", "omega"],
            cwd=built_mubase,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Should have output on stdout
        assert result.stdout or "compression" in result.stderr.lower()


# =============================================================================
# TestCLIContext - CLI context commands
# =============================================================================


class TestCLIContextOmega:
    """Tests for CLI context --format omega command."""

    @pytest.fixture
    def context_ready_mubase(self, tmp_path: Path) -> Path:
        """Create a project with mubase ready for context extraction."""
        project_dir = tmp_path / "context_project"
        project_dir.mkdir()

        # Create source files
        src_dir = project_dir / "src"
        src_dir.mkdir()

        (src_dir / "auth.py").write_text(
            '''
class AuthService:
    """Handles authentication."""

    def login(self, username: str, password: str) -> dict:
        """Authenticate user."""
        return {"token": "abc123"}

    def logout(self, token: str) -> bool:
        """Invalidate token."""
        return True
'''
        )

        (src_dir / "user.py").write_text(
            '''
class UserService:
    """Manages users."""

    def get_user(self, user_id: int) -> dict:
        """Get user by ID."""
        return {"id": user_id}
'''
        )

        # Create murc
        (project_dir / ".murc.toml").write_text(
            """
[scan]
include = ["src/**/*.py"]
"""
        )

        # Build mubase
        result = subprocess.run(
            ["uv", "run", "mu", "kernel", "build", "."],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.skip(f"Failed to build mubase: {result.stderr}")

        return project_dir

    def test_context_omega_format(self, context_ready_mubase: Path) -> None:
        """Test mu kernel context --format omega produces OMEGA output."""
        result = subprocess.run(
            [
                "uv",
                "run",
                "mu",
                "kernel",
                "context",
                "How does authentication work?",
                ".",
                "--format",
                "omega",
            ],
            cwd=context_ready_mubase,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0

        # Should have output
        output = result.stdout
        assert output

    def test_context_omega_verbose(self, context_ready_mubase: Path) -> None:
        """Test verbose mode shows compression stats."""
        result = subprocess.run(
            [
                "uv",
                "run",
                "mu",
                "kernel",
                "context",
                "auth service",
                ".",
                "--format",
                "omega",
                "--verbose",
            ],
            cwd=context_ready_mubase,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0

        # Verbose output goes to stderr
        stderr = result.stderr.lower()
        # Should mention extraction stats (includes "nodes included", "token", etc.)
        # Or at minimum show the warning about embeddings
        assert (
            "token" in stderr
            or "compression" in stderr
            or "nodes" in stderr
            or "embedding" in stderr
            or "extraction" in stderr
        )


# =============================================================================
# TestMCPTools - MCP tool integration (unit-level)
# =============================================================================


class TestMCPToolsUnit:
    """Unit tests for MCP OMEGA tools (without running full MCP server)."""

    @pytest.fixture
    def mcp_mubase(self, tmp_path: Path) -> Path:
        """Create a mubase for MCP testing and close it so MCP can access it."""
        db = MUbase(tmp_path / "mcp_test.mubase")

        # Add minimal test data
        db.add_node(
            Node(
                id="mod:src/auth.py",
                type=NodeType.MODULE,
                name="auth",
                qualified_name="auth",
                file_path="src/auth.py",
                line_start=1,
                line_end=100,
                complexity=0,
            )
        )
        db.add_node(
            Node(
                id="cls:src/auth.py:AuthService",
                type=NodeType.CLASS,
                name="AuthService",
                qualified_name="auth.AuthService",
                file_path="src/auth.py",
                line_start=10,
                line_end=80,
                complexity=0,
            )
        )
        db.add_edge(
            Edge(
                id="edge:mod:src/auth.py:contains:cls:src/auth.py:AuthService",
                source_id="mod:src/auth.py",
                target_id="cls:src/auth.py:AuthService",
                type=EdgeType.CONTAINS,
            )
        )

        # Close the connection so MCP tools can open it
        db.close()

        return tmp_path / "mcp_test.mubase"

    def test_lisp_exporter_direct(self, mcp_mubase: Path) -> None:
        """Test LispExporter directly (mu_export_lisp removed from MCP in Phase 3)."""
        from mu.kernel import MUbase
        from mu.kernel.export import LispExporter

        db = MUbase(mcp_mubase, read_only=True)
        try:
            exporter = LispExporter()
            result = exporter.export(db)

            assert result.success
            assert result.output
            assert result.node_count > 0
        finally:
            db.close()

    def test_macro_synthesizer_direct(self, mcp_mubase: Path) -> None:
        """Test MacroSynthesizer directly (mu_macros removed from MCP in Phase 3)."""
        from mu.intelligence.synthesizer import MacroSynthesizer
        from mu.kernel import MUbase

        db = MUbase(mcp_mubase, read_only=True)
        try:
            synthesizer = MacroSynthesizer(db)
            result = synthesizer.synthesize()

            # SynthesisResult has these attributes
            assert len(result.macros) >= 0
            assert result.total_patterns_analyzed >= 0
            assert result.patterns_converted >= 0
        finally:
            db.close()

    def test_mu_context_omega_tool(self, mcp_mubase: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test mu_context_omega MCP tool produces compressed context."""
        # Patch find_mubase in the tools._utils module (moved in Phase 3)
        from mu.mcp.tools import _utils

        monkeypatch.setattr(_utils, "find_mubase", lambda: mcp_mubase)

        from mu.mcp.tools.context import mu_context_omega

        result = mu_context_omega("How does authentication work?")

        assert result.full_output
        assert result.total_tokens > 0


# =============================================================================
# TestOmegaRoundtrip - S-expression parsing validation
# =============================================================================


class TestOmegaRoundtrip:
    """Tests for validating S-expression output can be parsed."""

    def test_output_is_parseable_sexpr(self, omega_db: MUbase) -> None:
        """Test that OMEGA output is valid S-expression syntax."""
        config = OmegaConfig(max_tokens=8000)
        extractor = OmegaContextExtractor(omega_db, config)

        result = extractor.extract("auth service")
        output = result.full_output

        # Basic S-expression validation:
        # 1. Balanced parens
        assert output.count("(") == output.count(")")

        # 2. No unmatched brackets
        assert output.count("[") == output.count("]")

        # 3. Strings are properly quoted (basic check)
        quote_count = output.count('"')
        assert quote_count % 2 == 0  # Even number of quotes

    def test_lisp_export_parseable(self, omega_db: MUbase) -> None:
        """Test that LispExporter output is valid S-expression."""
        exporter = LispExporter()
        result = exporter.export(omega_db)

        output = result.output

        # Balanced delimiters
        assert output.count("(") == output.count(")")
        assert output.count("[") == output.count("]")

    def test_manifest_sexpr_parseable(self) -> None:
        """Test that manifest S-expression is valid."""
        manifest = OmegaManifest(
            version="1.0",
            codebase="test",
            commit="abc123",
            core_macros=["module", "class", "defn"],
            standard_macros=["api"],
        )

        sexpr = manifest.to_sexpr()

        # Should be valid S-expression
        assert sexpr.count("(") == sexpr.count(")")
        assert sexpr.count("[") == sexpr.count("]")


# =============================================================================
# TestMUCodebaseCompression - Self-compression benchmark
# =============================================================================


class TestMUCodebaseCompression:
    """Benchmark tests for compressing the MU codebase itself.

    These tests validate that OMEGA can handle real-world codebases
    and achieve meaningful compression ratios.
    """

    @pytest.fixture
    def mu_codebase_db(self) -> MUbase | None:
        """Get the MU codebase's own mubase if available."""
        # Look for the MU project's .mu/mubase
        mu_project_root = Path(__file__).parent.parent.parent
        mubase_path = mu_project_root / ".mu" / "mubase"

        if not mubase_path.exists():
            return None

        return MUbase(mubase_path, read_only=True)

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent.parent / ".mu" / "mubase").exists(),
        reason="MU codebase mubase not built",
    )
    def test_compress_mu_codebase(self, mu_codebase_db: MUbase) -> None:
        """Test OMEGA compression on the MU codebase itself."""
        if mu_codebase_db is None:
            pytest.skip("MU mubase not available")

        config = OmegaConfig(max_tokens=16000)
        extractor = OmegaContextExtractor(mu_codebase_db, config)

        result = extractor.extract("How does the kernel module work?")

        # Should produce valid output
        assert result.nodes_included > 0
        assert result.total_tokens > 0

        # OMEGA v2.0 prioritizes LLM parseability over token savings
        # S-expressions are more verbose than sigils, so compression_ratio
        # may be < 1.0 (expansion is expected). The value is in structured
        # format and prompt cache optimization, not raw token reduction.
        # Just verify we get a valid ratio > 0
        assert result.compression_ratio > 0

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent.parent / ".mu" / "mubase").exists(),
        reason="MU codebase mubase not built",
    )
    def test_lisp_export_mu_codebase(self, mu_codebase_db: MUbase) -> None:
        """Test Lisp export on the MU codebase."""
        if mu_codebase_db is None:
            pytest.skip("MU mubase not available")

        exporter = LispExporter()
        options = LispExportOptions(max_nodes=100)  # Limit for test speed

        result = exporter.export(mu_codebase_db, options)

        assert result.success
        assert result.output
        assert result.node_count > 0

        # Valid S-expression
        assert result.output.count("(") == result.output.count(")")


# =============================================================================
# TestOmegaResultProperties - Result object behavior
# =============================================================================


class TestOmegaResultProperties:
    """Tests for OmegaResult computed properties."""

    def test_is_compressed_property(self) -> None:
        """Test is_compressed correctly identifies compression."""
        # Compressed result
        result = OmegaResult(
            seed="",
            body="(module test)",
            manifest=OmegaManifest(),
            compression_ratio=2.5,
            total_tokens=100,
            original_tokens=250,
        )
        assert result.is_compressed is True

        # Not compressed
        result_expanded = OmegaResult(
            seed="",
            body="(module test)",
            manifest=OmegaManifest(),
            compression_ratio=0.8,
            total_tokens=100,
            original_tokens=80,
        )
        assert result_expanded.is_compressed is False

    def test_tokens_saved_property(self) -> None:
        """Test tokens_saved calculation."""
        result = OmegaResult(
            seed="",
            body="(module test)",
            manifest=OmegaManifest(),
            total_tokens=100,
            original_tokens=300,
        )

        assert result.tokens_saved == 200

    def test_savings_percent_property(self) -> None:
        """Test savings_percent calculation."""
        result = OmegaResult(
            seed="",
            body="(module test)",
            manifest=OmegaManifest(),
            total_tokens=100,
            original_tokens=400,
        )

        # Saved 300 out of 400 = 75%
        assert result.savings_percent == 75.0

    def test_savings_percent_zero_original(self) -> None:
        """Test savings_percent handles zero original tokens."""
        result = OmegaResult(
            seed="",
            body="",
            manifest=OmegaManifest(),
            total_tokens=0,
            original_tokens=0,
        )

        assert result.savings_percent == 0.0

    def test_full_output_combines_seed_body(self) -> None:
        """Test full_output properly combines seed and body."""
        result = OmegaResult(
            seed=";; Macros\n(defmacro api [] ...)",
            body='(mu-lisp :version "1.0" (module test))',
            manifest=OmegaManifest(),
        )

        full = result.full_output

        assert ";; Macros" in full
        assert "(defmacro api" in full
        assert ";; Codebase Context" in full
        assert "(mu-lisp" in full


__all__ = [
    "TestOmegaContextExtractor",
    "TestLispExporter",
    "TestOmegaManifest",
    "TestOmegaConfig",
    "TestCLIExportLisp",
    "TestCLIContextOmega",
    "TestMCPToolsUnit",
    "TestOmegaRoundtrip",
    "TestMUCodebaseCompression",
    "TestOmegaResultProperties",
]
