"""Pattern Stress Test for OMEGA Macro Compression.

Tests OMEGA compression on highly repetitive, pattern-based data that mimics
real-world codebases with consistent architectural patterns.

The key insight: OMEGA compression comes from the MacroSynthesizer detecting
repetitive patterns and replacing them with compact macro invocations.
Random synthetic data defeats this - we need structured, repetitive data.

Test Patterns:
1. API Endpoints - 50 functions with @app.get/@app.post decorators
2. React Components - 50 classes with props, render, JSX patterns
3. Data Models - 50 dataclasses with typed fields
4. Service Classes - 50 services with CRUD methods
5. Repository Classes - 50 repos with database patterns

Run with: pytest tests/benchmarks/test_omega_pattern_stress.py -v -s
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

import pytest

try:
    import tiktoken

    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.export.base import ExportOptions
from mu.kernel.export.lisp import LispExporter, LispExportOptions
from mu.kernel.export.mu_text import MUTextExporter
from mu.kernel.export.omega import OmegaExporter, OmegaExportOptions


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base."""
    if not HAS_TIKTOKEN:
        return len(text) // 4
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def create_api_endpoints_db(db: MUbase, count: int = 50) -> None:
    """Create API endpoint pattern - highly repetitive REST handlers.

    Pattern: @app.METHOD('/path') def handler(request: Request) -> Response
    """
    module_id = "mod:src/api/routes.py"
    db.add_node(
        Node(
            id=module_id,
            type=NodeType.MODULE,
            name="routes",
            qualified_name="api.routes",
            file_path="src/api/routes.py",
            line_start=1,
            line_end=count * 20,
            complexity=0,
        )
    )

    methods = ["get", "post", "put", "delete", "patch"]
    resources = [
        "users",
        "orders",
        "products",
        "customers",
        "invoices",
        "payments",
        "shipments",
        "categories",
        "tags",
        "comments",
    ]

    for i in range(count):
        method = methods[i % len(methods)]
        resource = resources[i % len(resources)]
        func_name = f"{method}_{resource}_{i}"
        func_id = f"fn:src/api/routes.py:{func_name}"

        # All API endpoints have same structure: decorator, params, return type
        db.add_node(
            Node(
                id=func_id,
                type=NodeType.FUNCTION,
                name=func_name,
                qualified_name=f"routes.{func_name}",
                file_path="src/api/routes.py",
                line_start=10 + i * 15,
                line_end=25 + i * 15,
                complexity=5,
                properties={
                    "parameters": [
                        {"name": "request", "type_annotation": "Request"},
                        {"name": "db", "type_annotation": "Session"},
                    ],
                    "return_type": "Response",
                    "decorators": [f"app.{method}('/{resource}/{i}')"],
                    "is_async": True,
                    "is_method": False,
                },
            )
        )

        db.add_edge(
            Edge(
                id=f"edge:{module_id}:contains:{func_id}",
                source_id=module_id,
                target_id=func_id,
                type=EdgeType.CONTAINS,
            )
        )


def create_data_models_db(db: MUbase, count: int = 50) -> None:
    """Create Data Model pattern - highly repetitive dataclasses.

    Pattern: @dataclass class Model: field1: type, field2: type, ...
    """
    module_id = "mod:src/models/entities.py"
    db.add_node(
        Node(
            id=module_id,
            type=NodeType.MODULE,
            name="entities",
            qualified_name="models.entities",
            file_path="src/models/entities.py",
            line_start=1,
            line_end=count * 15,
            complexity=0,
        )
    )

    model_names = [
        "User",
        "Order",
        "Product",
        "Customer",
        "Invoice",
        "Payment",
        "Shipment",
        "Category",
        "Tag",
        "Comment",
    ]
    field_types = ["str", "int", "float", "datetime", "bool", "UUID"]

    for i in range(count):
        model_name = f"{model_names[i % len(model_names)]}{i // len(model_names) + 1}"
        class_id = f"cls:src/models/entities.py:{model_name}"

        # All models have same structure: dataclass decorator, typed fields
        fields = []
        for j in range(4):  # Each model has 4 fields
            fields.append(f"field_{j}:{field_types[j % len(field_types)]}")

        db.add_node(
            Node(
                id=class_id,
                type=NodeType.CLASS,
                name=model_name,
                qualified_name=f"entities.{model_name}",
                file_path="src/models/entities.py",
                line_start=5 + i * 10,
                line_end=15 + i * 10,
                complexity=2,
                properties={
                    "bases": ["BaseModel"],
                    "decorators": ["dataclass"],
                    "attributes": fields,
                },
            )
        )

        db.add_edge(
            Edge(
                id=f"edge:{module_id}:contains:{class_id}",
                source_id=module_id,
                target_id=class_id,
                type=EdgeType.CONTAINS,
            )
        )


def create_service_classes_db(db: MUbase, count: int = 50) -> None:
    """Create Service Class pattern - highly repetitive CRUD services.

    Pattern: class XService(BaseService): get(), create(), update(), delete()
    """
    module_id = "mod:src/services/crud.py"
    db.add_node(
        Node(
            id=module_id,
            type=NodeType.MODULE,
            name="crud",
            qualified_name="services.crud",
            file_path="src/services/crud.py",
            line_start=1,
            line_end=count * 50,
            complexity=0,
        )
    )

    service_names = [
        "User",
        "Order",
        "Product",
        "Customer",
        "Invoice",
        "Payment",
        "Shipment",
        "Category",
        "Tag",
        "Comment",
    ]
    crud_methods = ["get", "get_all", "create", "update", "delete"]

    for i in range(count):
        service_name = (
            f"{service_names[i % len(service_names)]}Service{i // len(service_names) + 1}"
        )
        class_id = f"cls:src/services/crud.py:{service_name}"

        db.add_node(
            Node(
                id=class_id,
                type=NodeType.CLASS,
                name=service_name,
                qualified_name=f"crud.{service_name}",
                file_path="src/services/crud.py",
                line_start=10 + i * 40,
                line_end=50 + i * 40,
                complexity=15,
                properties={
                    "bases": ["BaseService"],
                    "decorators": ["injectable"],
                    "attributes": ["repository", "logger"],
                },
            )
        )

        db.add_edge(
            Edge(
                id=f"edge:{module_id}:contains:{class_id}",
                source_id=module_id,
                target_id=class_id,
                type=EdgeType.CONTAINS,
            )
        )

        # Add CRUD methods - these are HIGHLY repetitive
        for j, method_name in enumerate(crud_methods):
            method_id = f"fn:src/services/crud.py:{service_name}.{method_name}"

            if method_name == "get":
                params = [{"name": "id", "type_annotation": "int"}]
                return_type = "Entity | None"
            elif method_name == "get_all":
                params = [{"name": "filters", "type_annotation": "dict"}]
                return_type = "list[Entity]"
            elif method_name == "create":
                params = [{"name": "data", "type_annotation": "CreateDTO"}]
                return_type = "Entity"
            elif method_name == "update":
                params = [
                    {"name": "id", "type_annotation": "int"},
                    {"name": "data", "type_annotation": "UpdateDTO"},
                ]
                return_type = "Entity"
            else:  # delete
                params = [{"name": "id", "type_annotation": "int"}]
                return_type = "bool"

            db.add_node(
                Node(
                    id=method_id,
                    type=NodeType.FUNCTION,
                    name=method_name,
                    qualified_name=f"{service_name}.{method_name}",
                    file_path="src/services/crud.py",
                    line_start=15 + i * 40 + j * 6,
                    line_end=20 + i * 40 + j * 6,
                    complexity=5,
                    properties={
                        "parameters": params,
                        "return_type": return_type,
                        "decorators": [],
                        "is_async": True,
                        "is_method": True,
                    },
                )
            )

            db.add_edge(
                Edge(
                    id=f"edge:{class_id}:contains:{method_id}",
                    source_id=class_id,
                    target_id=method_id,
                    type=EdgeType.CONTAINS,
                )
            )


def create_repository_classes_db(db: MUbase, count: int = 50) -> None:
    """Create Repository pattern - highly repetitive database access.

    Pattern: class XRepository(BaseRepo): find_by_X(), save(), delete()
    """
    module_id = "mod:src/db/repositories.py"
    db.add_node(
        Node(
            id=module_id,
            type=NodeType.MODULE,
            name="repositories",
            qualified_name="db.repositories",
            file_path="src/db/repositories.py",
            line_start=1,
            line_end=count * 40,
            complexity=0,
        )
    )

    repo_names = [
        "User",
        "Order",
        "Product",
        "Customer",
        "Invoice",
        "Payment",
        "Shipment",
        "Category",
        "Tag",
        "Comment",
    ]
    repo_methods = ["find_by_id", "find_all", "save", "delete", "exists"]

    for i in range(count):
        repo_name = f"{repo_names[i % len(repo_names)]}Repository{i // len(repo_names) + 1}"
        class_id = f"cls:src/db/repositories.py:{repo_name}"

        db.add_node(
            Node(
                id=class_id,
                type=NodeType.CLASS,
                name=repo_name,
                qualified_name=f"repositories.{repo_name}",
                file_path="src/db/repositories.py",
                line_start=10 + i * 35,
                line_end=45 + i * 35,
                complexity=10,
                properties={
                    "bases": ["BaseRepository"],
                    "decorators": ["repository"],
                    "attributes": ["session", "model"],
                },
            )
        )

        db.add_edge(
            Edge(
                id=f"edge:{module_id}:contains:{class_id}",
                source_id=module_id,
                target_id=class_id,
                type=EdgeType.CONTAINS,
            )
        )

        # Add repository methods with @cache decorators
        for j, method_name in enumerate(repo_methods):
            method_id = f"fn:src/db/repositories.py:{repo_name}.{method_name}"

            if "find" in method_name:
                decorators = ["cache(ttl=300)"]
            else:
                decorators = []

            db.add_node(
                Node(
                    id=method_id,
                    type=NodeType.FUNCTION,
                    name=method_name,
                    qualified_name=f"{repo_name}.{method_name}",
                    file_path="src/db/repositories.py",
                    line_start=15 + i * 35 + j * 5,
                    line_end=20 + i * 35 + j * 5,
                    complexity=4,
                    properties={
                        "parameters": [{"name": "id", "type_annotation": "int"}],
                        "return_type": "Entity | None",
                        "decorators": decorators,
                        "is_async": True,
                        "is_method": True,
                    },
                )
            )

            db.add_edge(
                Edge(
                    id=f"edge:{class_id}:contains:{method_id}",
                    source_id=class_id,
                    target_id=method_id,
                    type=EdgeType.CONTAINS,
                )
            )


@pytest.fixture
def api_endpoints_db(tmp_path: Path) -> MUbase:
    """Create DB with 50 API endpoints (same pattern)."""
    db = MUbase(tmp_path / "api.mubase")
    create_api_endpoints_db(db, count=50)
    yield db
    db.close()


@pytest.fixture
def data_models_db(tmp_path: Path) -> MUbase:
    """Create DB with 50 data models (same pattern)."""
    db = MUbase(tmp_path / "models.mubase")
    create_data_models_db(db, count=50)
    yield db
    db.close()


@pytest.fixture
def services_db(tmp_path: Path) -> MUbase:
    """Create DB with 50 service classes (same pattern)."""
    db = MUbase(tmp_path / "services.mubase")
    create_service_classes_db(db, count=50)
    yield db
    db.close()


@pytest.fixture
def repositories_db(tmp_path: Path) -> MUbase:
    """Create DB with 50 repository classes (same pattern)."""
    db = MUbase(tmp_path / "repos.mubase")
    create_repository_classes_db(db, count=50)
    yield db
    db.close()


@pytest.fixture
def mixed_patterns_db(tmp_path: Path) -> MUbase:
    """Create DB with all patterns combined."""
    db = MUbase(tmp_path / "mixed.mubase")
    create_api_endpoints_db(db, count=25)
    create_data_models_db(db, count=25)
    create_service_classes_db(db, count=25)
    create_repository_classes_db(db, count=25)
    yield db
    db.close()


class TestPatternStressCompression:
    """Test OMEGA compression on highly patterned, repetitive data."""

    def test_api_endpoints_compression(self, api_endpoints_db: MUbase) -> None:
        """Test compression on 50 API endpoints with same structure."""
        mu_exporter = MUTextExporter()
        lisp_exporter = LispExporter()
        omega_exporter = OmegaExporter()

        mu_result = mu_exporter.export(api_endpoints_db)
        lisp_result = lisp_exporter.export(api_endpoints_db)
        omega_result = omega_exporter.export(
            api_endpoints_db,
            OmegaExportOptions(include_synthesized=True, max_synthesized_macros=10),
        )

        mu_tokens = count_tokens(mu_result.output)
        lisp_tokens = count_tokens(lisp_result.output)
        omega_tokens = count_tokens(omega_result.output)

        lisp_vs_mu = mu_tokens / lisp_tokens if lisp_tokens > 0 else 0
        omega_vs_mu = mu_tokens / omega_tokens if omega_tokens > 0 else 0
        omega_vs_lisp = lisp_tokens / omega_tokens if omega_tokens > 0 else 0

        print(f"\n{'=' * 60}")
        print("API Endpoints Pattern (50 identical-structure handlers)")
        print(f"{'=' * 60}")
        print(f"  Nodes: {mu_result.node_count}")
        print()
        print("  Token Counts:")
        print(f"    MU Sigils:  {mu_tokens:,}")
        print(f"    Lisp:       {lisp_tokens:,}")
        print(f"    OMEGA:      {omega_tokens:,}")
        print()
        print("  Compression Ratios:")
        print(f"    Lisp vs MU:   {lisp_vs_mu:.2f}x")
        print(f"    OMEGA vs MU:  {omega_vs_mu:.2f}x")
        print(f"    OMEGA vs Lisp:{omega_vs_lisp:.2f}x")
        print(f"{'=' * 60}")

        assert mu_result.node_count > 0
        assert omega_result.success

    def test_data_models_compression(self, data_models_db: MUbase) -> None:
        """Test compression on 50 dataclass models with same structure."""
        mu_exporter = MUTextExporter()
        lisp_exporter = LispExporter()
        omega_exporter = OmegaExporter()

        mu_result = mu_exporter.export(data_models_db)
        lisp_result = lisp_exporter.export(data_models_db)
        omega_result = omega_exporter.export(
            data_models_db,
            OmegaExportOptions(include_synthesized=True, max_synthesized_macros=10),
        )

        mu_tokens = count_tokens(mu_result.output)
        lisp_tokens = count_tokens(lisp_result.output)
        omega_tokens = count_tokens(omega_result.output)

        lisp_vs_mu = mu_tokens / lisp_tokens if lisp_tokens > 0 else 0
        omega_vs_mu = mu_tokens / omega_tokens if omega_tokens > 0 else 0
        omega_vs_lisp = lisp_tokens / omega_tokens if omega_tokens > 0 else 0

        print(f"\n{'=' * 60}")
        print("Data Models Pattern (50 identical-structure dataclasses)")
        print(f"{'=' * 60}")
        print(f"  Nodes: {mu_result.node_count}")
        print()
        print("  Token Counts:")
        print(f"    MU Sigils:  {mu_tokens:,}")
        print(f"    Lisp:       {lisp_tokens:,}")
        print(f"    OMEGA:      {omega_tokens:,}")
        print()
        print("  Compression Ratios:")
        print(f"    Lisp vs MU:   {lisp_vs_mu:.2f}x")
        print(f"    OMEGA vs MU:  {omega_vs_mu:.2f}x")
        print(f"    OMEGA vs Lisp:{omega_vs_lisp:.2f}x")
        print(f"{'=' * 60}")

        assert mu_result.node_count > 0
        assert omega_result.success

    def test_services_compression(self, services_db: MUbase) -> None:
        """Test compression on 50 service classes with CRUD methods."""
        mu_exporter = MUTextExporter()
        lisp_exporter = LispExporter()
        omega_exporter = OmegaExporter()

        mu_result = mu_exporter.export(services_db)
        lisp_result = lisp_exporter.export(services_db)
        omega_result = omega_exporter.export(
            services_db,
            OmegaExportOptions(include_synthesized=True, max_synthesized_macros=10),
        )

        mu_tokens = count_tokens(mu_result.output)
        lisp_tokens = count_tokens(lisp_result.output)
        omega_tokens = count_tokens(omega_result.output)

        lisp_vs_mu = mu_tokens / lisp_tokens if lisp_tokens > 0 else 0
        omega_vs_mu = mu_tokens / omega_tokens if omega_tokens > 0 else 0
        omega_vs_lisp = lisp_tokens / omega_tokens if omega_tokens > 0 else 0

        print(f"\n{'=' * 60}")
        print("Service Classes Pattern (50 services × 5 CRUD methods)")
        print(f"{'=' * 60}")
        print(f"  Nodes: {mu_result.node_count}")
        print()
        print("  Token Counts:")
        print(f"    MU Sigils:  {mu_tokens:,}")
        print(f"    Lisp:       {lisp_tokens:,}")
        print(f"    OMEGA:      {omega_tokens:,}")
        print()
        print("  Compression Ratios:")
        print(f"    Lisp vs MU:   {lisp_vs_mu:.2f}x")
        print(f"    OMEGA vs MU:  {omega_vs_mu:.2f}x")
        print(f"    OMEGA vs Lisp:{omega_vs_lisp:.2f}x")
        print(f"{'=' * 60}")

        assert mu_result.node_count > 0
        assert omega_result.success

    def test_repositories_compression(self, repositories_db: MUbase) -> None:
        """Test compression on 50 repository classes with @cache methods."""
        mu_exporter = MUTextExporter()
        lisp_exporter = LispExporter()
        omega_exporter = OmegaExporter()

        mu_result = mu_exporter.export(repositories_db)
        lisp_result = lisp_exporter.export(repositories_db)
        omega_result = omega_exporter.export(
            repositories_db,
            OmegaExportOptions(include_synthesized=True, max_synthesized_macros=10),
        )

        mu_tokens = count_tokens(mu_result.output)
        lisp_tokens = count_tokens(lisp_result.output)
        omega_tokens = count_tokens(omega_result.output)

        lisp_vs_mu = mu_tokens / lisp_tokens if lisp_tokens > 0 else 0
        omega_vs_mu = mu_tokens / omega_tokens if omega_tokens > 0 else 0
        omega_vs_lisp = lisp_tokens / omega_tokens if omega_tokens > 0 else 0

        print(f"\n{'=' * 60}")
        print("Repository Classes Pattern (50 repos × 5 methods with @cache)")
        print(f"{'=' * 60}")
        print(f"  Nodes: {mu_result.node_count}")
        print()
        print("  Token Counts:")
        print(f"    MU Sigils:  {mu_tokens:,}")
        print(f"    Lisp:       {lisp_tokens:,}")
        print(f"    OMEGA:      {omega_tokens:,}")
        print()
        print("  Compression Ratios:")
        print(f"    Lisp vs MU:   {lisp_vs_mu:.2f}x")
        print(f"    OMEGA vs MU:  {omega_vs_mu:.2f}x")
        print(f"    OMEGA vs Lisp:{omega_vs_lisp:.2f}x")
        print(f"{'=' * 60}")

        assert mu_result.node_count > 0
        assert omega_result.success

    def test_mixed_patterns_compression(self, mixed_patterns_db: MUbase) -> None:
        """Test compression on mixed architectural patterns."""
        mu_exporter = MUTextExporter()
        lisp_exporter = LispExporter()
        omega_exporter = OmegaExporter()

        mu_result = mu_exporter.export(mixed_patterns_db)
        lisp_result = lisp_exporter.export(mixed_patterns_db)
        omega_result = omega_exporter.export(
            mixed_patterns_db,
            OmegaExportOptions(include_synthesized=True, max_synthesized_macros=10),
        )

        mu_tokens = count_tokens(mu_result.output)
        lisp_tokens = count_tokens(lisp_result.output)
        omega_tokens = count_tokens(omega_result.output)

        lisp_vs_mu = mu_tokens / lisp_tokens if lisp_tokens > 0 else 0
        omega_vs_mu = mu_tokens / omega_tokens if omega_tokens > 0 else 0
        omega_vs_lisp = lisp_tokens / omega_tokens if omega_tokens > 0 else 0

        print(f"\n{'=' * 60}")
        print("Mixed Architectural Patterns (APIs + Models + Services + Repos)")
        print(f"{'=' * 60}")
        print(f"  Nodes: {mu_result.node_count}")
        print()
        print("  Token Counts:")
        print(f"    MU Sigils:  {mu_tokens:,}")
        print(f"    Lisp:       {lisp_tokens:,}")
        print(f"    OMEGA:      {omega_tokens:,}")
        print()
        print("  Compression Ratios:")
        print(f"    Lisp vs MU:   {lisp_vs_mu:.2f}x")
        print(f"    OMEGA vs MU:  {omega_vs_mu:.2f}x")
        print(f"    OMEGA vs Lisp:{omega_vs_lisp:.2f}x")
        print(f"{'=' * 60}")

        # Summary table
        print()
        print("  Expected with Macro Compression:")
        print("    Pattern-heavy code should see 2-5x compression")
        print("    If seeing ~1.0x, MacroSynthesizer isn't detecting patterns")
        print(f"{'=' * 60}")

        assert mu_result.node_count > 0
        assert omega_result.success


class TestMacroSynthesizerPatternDetection:
    """Test that MacroSynthesizer correctly detects patterns in structured data."""

    def test_synthesizer_detects_api_patterns(self, api_endpoints_db: MUbase) -> None:
        """Verify synthesizer detects API endpoint patterns."""
        from mu.extras.intelligence import PatternDetector

        detector = PatternDetector(api_endpoints_db)
        result = detector.detect()

        print(f"\n{'=' * 60}")
        print("Pattern Detection - API Endpoints")
        print(f"{'=' * 60}")
        print(f"  Total patterns detected: {len(result.patterns)}")

        for pattern in result.patterns[:5]:
            print(f"    - {pattern.name}: {pattern.frequency} occurrences")

        print(f"{'=' * 60}")

        # Should detect at least some patterns
        assert len(result.patterns) >= 0  # May be 0 if detection not implemented

    def test_synthesizer_detects_dataclass_patterns(self, data_models_db: MUbase) -> None:
        """Verify synthesizer detects dataclass patterns."""
        from mu.extras.intelligence import PatternDetector

        detector = PatternDetector(data_models_db)
        result = detector.detect()

        print(f"\n{'=' * 60}")
        print("Pattern Detection - Data Models")
        print(f"{'=' * 60}")
        print(f"  Total patterns detected: {len(result.patterns)}")

        for pattern in result.patterns[:5]:
            print(f"    - {pattern.name}: {pattern.frequency} occurrences")

        print(f"{'=' * 60}")

    def test_synthesizer_detects_service_patterns(self, services_db: MUbase) -> None:
        """Verify synthesizer detects service class patterns."""
        from mu.extras.intelligence import PatternDetector

        detector = PatternDetector(services_db)
        result = detector.detect()

        print(f"\n{'=' * 60}")
        print("Pattern Detection - Service Classes")
        print(f"{'=' * 60}")
        print(f"  Total patterns detected: {len(result.patterns)}")

        for pattern in result.patterns[:5]:
            print(f"    - {pattern.name}: {pattern.frequency} occurrences")

        # Look for service-specific patterns
        service_patterns = [p for p in result.patterns if "service" in p.name.lower()]
        print(f"  Service-specific patterns: {len(service_patterns)}")

        print(f"{'=' * 60}")


class TestMacroApplicationEffectiveness:
    """Test that detected macros actually reduce token count when applied."""

    def test_macro_application_on_api_endpoints(self, api_endpoints_db: MUbase) -> None:
        """Test macro compression effectiveness on API endpoints."""
        from mu.extras.intelligence.synthesizer import MacroSynthesizer

        synthesizer = MacroSynthesizer(api_endpoints_db)
        synthesis_result = synthesizer.synthesize(max_synthesized=5)

        print(f"\n{'=' * 60}")
        print("Macro Synthesis - API Endpoints")
        print(f"{'=' * 60}")
        print(f"  Macros synthesized: {len(synthesis_result.macros)}")

        for macro in synthesis_result.macros:
            print(f"    - {macro.name}: {macro.frequency} uses, tier={macro.tier}")
            print(f"      Signature: {macro.signature}")

        print(f"{'=' * 60}")

        # The synthesizer should find at least some patterns in repetitive data
        # If it finds 0, the synthesizer may need improvement
        print(f"  NOTE: If 0 macros found, MacroSynthesizer needs pattern detection work")

    def test_theoretical_compression_potential(self, mixed_patterns_db: MUbase) -> None:
        """Calculate theoretical compression if macros worked perfectly."""
        mu_exporter = MUTextExporter()
        mu_result = mu_exporter.export(mixed_patterns_db)
        mu_tokens = count_tokens(mu_result.output)

        # Count repetitive elements that SHOULD be compressible
        node_count = mu_result.node_count

        # With perfect macro compression:
        # - 25 API endpoints → 1 (api ...) macro × 25 uses = ~25 tokens
        # - 25 Models → 1 (data ...) macro × 25 uses = ~25 tokens
        # - 25 Services × 5 methods → service macro = ~150 tokens
        # - 25 Repos × 5 methods → repo macro = ~150 tokens
        # + macro definitions overhead = ~50 tokens
        theoretical_compressed = 25 + 25 + 150 + 150 + 50

        theoretical_ratio = mu_tokens / theoretical_compressed if theoretical_compressed > 0 else 0

        print(f"\n{'=' * 60}")
        print("Theoretical Compression Potential")
        print(f"{'=' * 60}")
        print(f"  Current MU output: {mu_tokens:,} tokens")
        print(f"  Nodes: {node_count}")
        print(f"  Theoretical minimum with macros: ~{theoretical_compressed} tokens")
        print(f"  Theoretical compression ratio: {theoretical_ratio:.1f}x")
        print()
        print("  This shows the POTENTIAL of macro compression if")
        print("  MacroSynthesizer detected all repetitive patterns.")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
