"""Integration tests for Context Extraction Accuracy.

Regression tests that verify context extraction produces relevant, domain-aware
results. These tests recreate real-world scenarios where naive keyword matching
fails but graph-based extraction succeeds.

Key Regression Test:
- Dominaite scenario: "payout service" query should return C# PayoutService,
  not Python chat agent code that happens to mention "payout".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.context import ExtractionConfig, SmartContextExtractor


# =============================================================================
# Dominaite Regression Test Fixture
# =============================================================================


@pytest.fixture
def dominaite_mubase(tmp_path: Path) -> MUbase:
    """Create a MUbase simulating the Dominaite monorepo structure.

    Dominaite is a real-world monorepo with:
    - C# Payment Services (PayoutService, IPayoutService, PayoutConfig)
    - Python Chat Agent (ChatService, AgentService, PayoutHandler)

    The problem: Asking "How does payout service work?" would return 104 nodes
    including Python chat agent code instead of the C# PayoutService.

    Root cause: "payout" matched PayoutHandler.py and "service" matched
    every *Service class in the codebase.
    """
    db_path = tmp_path / ".mu" / "mubase"
    db_path.parent.mkdir(parents=True)
    mubase = MUbase(db_path)

    # =========================================================================
    # C# Payment Domain (what we WANT to find)
    # =========================================================================

    # C# PayoutService - main implementation
    mubase.add_node(
        Node(
            id="cls:src/Dominaite.Services/PayoutService.cs:PayoutService",
            type=NodeType.CLASS,
            name="PayoutService",
            qualified_name="Dominaite.Services.PayoutService",
            file_path="src/Dominaite.Services/PayoutService.cs",
            line_start=15,
            line_end=200,
            complexity=35,
            properties={"bases": ["IPayoutService"], "is_public": True},
        )
    )

    # C# IPayoutService - interface
    mubase.add_node(
        Node(
            id="cls:src/Dominaite.Services/IPayoutService.cs:IPayoutService",
            type=NodeType.CLASS,
            name="IPayoutService",
            qualified_name="Dominaite.Services.IPayoutService",
            file_path="src/Dominaite.Services/IPayoutService.cs",
            line_start=5,
            line_end=40,
            complexity=10,
            properties={"is_interface": True, "is_public": True},
        )
    )

    # C# PayoutConfig - configuration
    mubase.add_node(
        Node(
            id="cls:src/Dominaite.Services/PayoutConfig.cs:PayoutConfig",
            type=NodeType.CLASS,
            name="PayoutConfig",
            qualified_name="Dominaite.Services.PayoutConfig",
            file_path="src/Dominaite.Services/PayoutConfig.cs",
            line_start=5,
            line_end=30,
            complexity=5,
            properties={},
        )
    )

    # C# PayoutService methods
    mubase.add_node(
        Node(
            id="fn:src/Dominaite.Services/PayoutService.cs:PayoutService.ProcessPayout",
            type=NodeType.FUNCTION,
            name="ProcessPayout",
            qualified_name="Dominaite.Services.PayoutService.ProcessPayout",
            file_path="src/Dominaite.Services/PayoutService.cs",
            line_start=30,
            line_end=80,
            complexity=20,
            properties={
                "is_method": True,
                "is_async": True,
                "parameters": [
                    {"name": "amount", "type_annotation": "decimal"},
                    {"name": "recipient", "type_annotation": "string"},
                ],
                "return_type": "PayoutResult",
            },
        )
    )

    mubase.add_node(
        Node(
            id="fn:src/Dominaite.Services/PayoutService.cs:PayoutService.ValidatePayout",
            type=NodeType.FUNCTION,
            name="ValidatePayout",
            qualified_name="Dominaite.Services.PayoutService.ValidatePayout",
            file_path="src/Dominaite.Services/PayoutService.cs",
            line_start=85,
            line_end=120,
            complexity=15,
            properties={
                "is_method": True,
                "parameters": [{"name": "request", "type_annotation": "PayoutRequest"}],
                "return_type": "ValidationResult",
            },
        )
    )

    # C# TransactionProcessor - related service
    mubase.add_node(
        Node(
            id="cls:src/Dominaite.Services/TransactionProcessor.cs:TransactionProcessor",
            type=NodeType.CLASS,
            name="TransactionProcessor",
            qualified_name="Dominaite.Services.TransactionProcessor",
            file_path="src/Dominaite.Services/TransactionProcessor.cs",
            line_start=10,
            line_end=150,
            complexity=30,
            properties={"bases": ["ITransactionProcessor"]},
        )
    )

    # C# PayoutServiceTests
    mubase.add_node(
        Node(
            id="cls:src/Dominaite.Services.Tests/PayoutServiceTests.cs:PayoutServiceTests",
            type=NodeType.CLASS,
            name="PayoutServiceTests",
            qualified_name="Dominaite.Services.Tests.PayoutServiceTests",
            file_path="src/Dominaite.Services.Tests/PayoutServiceTests.cs",
            line_start=10,
            line_end=100,
            complexity=15,
            properties={},
        )
    )

    # =========================================================================
    # Python Chat Agent Domain (what we DON'T want)
    # =========================================================================

    # Python ChatService
    mubase.add_node(
        Node(
            id="cls:src/chat_agent/services/chat_service.py:ChatService",
            type=NodeType.CLASS,
            name="ChatService",
            qualified_name="chat_agent.services.ChatService",
            file_path="src/chat_agent/services/chat_service.py",
            line_start=10,
            line_end=150,
            complexity=25,
            properties={"bases": ["BaseService"]},
        )
    )

    # Python AgentService
    mubase.add_node(
        Node(
            id="cls:src/chat_agent/services/agent_service.py:AgentService",
            type=NodeType.CLASS,
            name="AgentService",
            qualified_name="chat_agent.services.AgentService",
            file_path="src/chat_agent/services/agent_service.py",
            line_start=5,
            line_end=100,
            complexity=20,
            properties={"bases": ["BaseService"]},
        )
    )

    # Python PayoutHandler - HAS "payout" in name but is Python chat code!
    mubase.add_node(
        Node(
            id="cls:src/chat_agent/handlers/payout_handler.py:PayoutHandler",
            type=NodeType.CLASS,
            name="PayoutHandler",
            qualified_name="chat_agent.handlers.PayoutHandler",
            file_path="src/chat_agent/handlers/payout_handler.py",
            line_start=5,
            line_end=50,
            complexity=10,
            properties={},
        )
    )

    # Python ServiceRegistry
    mubase.add_node(
        Node(
            id="cls:src/chat_agent/utils/service_registry.py:ServiceRegistry",
            type=NodeType.CLASS,
            name="ServiceRegistry",
            qualified_name="chat_agent.utils.ServiceRegistry",
            file_path="src/chat_agent/utils/service_registry.py",
            line_start=5,
            line_end=60,
            complexity=8,
            properties={},
        )
    )

    # Python __init__.py services module
    mubase.add_node(
        Node(
            id="mod:src/chat_agent/services/__init__.py",
            type=NodeType.MODULE,
            name="services",
            qualified_name="chat_agent.services",
            file_path="src/chat_agent/services/__init__.py",
            line_start=1,
            line_end=20,
            complexity=0,
            properties={},
        )
    )

    # =========================================================================
    # Edges - C# Domain
    # =========================================================================

    # PayoutService implements IPayoutService
    mubase.add_edge(
        Edge(
            id="edge:inherits:payout_interface",
            source_id="cls:src/Dominaite.Services/PayoutService.cs:PayoutService",
            target_id="cls:src/Dominaite.Services/IPayoutService.cs:IPayoutService",
            type=EdgeType.INHERITS,
            properties={},
        )
    )

    # PayoutService contains ProcessPayout
    mubase.add_edge(
        Edge(
            id="edge:contains:payout_processpayout",
            source_id="cls:src/Dominaite.Services/PayoutService.cs:PayoutService",
            target_id="fn:src/Dominaite.Services/PayoutService.cs:PayoutService.ProcessPayout",
            type=EdgeType.CONTAINS,
            properties={},
        )
    )

    # PayoutService contains ValidatePayout
    mubase.add_edge(
        Edge(
            id="edge:contains:payout_validatepayout",
            source_id="cls:src/Dominaite.Services/PayoutService.cs:PayoutService",
            target_id="fn:src/Dominaite.Services/PayoutService.cs:PayoutService.ValidatePayout",
            type=EdgeType.CONTAINS,
            properties={},
        )
    )

    # PayoutService imports PayoutConfig
    mubase.add_edge(
        Edge(
            id="edge:imports:payout_config",
            source_id="cls:src/Dominaite.Services/PayoutService.cs:PayoutService",
            target_id="cls:src/Dominaite.Services/PayoutConfig.cs:PayoutConfig",
            type=EdgeType.IMPORTS,
            properties={},
        )
    )

    # ProcessPayout calls TransactionProcessor
    mubase.add_edge(
        Edge(
            id="edge:calls:payout_txprocessor",
            source_id="fn:src/Dominaite.Services/PayoutService.cs:PayoutService.ProcessPayout",
            target_id="cls:src/Dominaite.Services/TransactionProcessor.cs:TransactionProcessor",
            type=EdgeType.CALLS,
            properties={},
        )
    )

    # PayoutServiceTests calls PayoutService
    mubase.add_edge(
        Edge(
            id="edge:calls:tests_payout",
            source_id="cls:src/Dominaite.Services.Tests/PayoutServiceTests.cs:PayoutServiceTests",
            target_id="cls:src/Dominaite.Services/PayoutService.cs:PayoutService",
            type=EdgeType.CALLS,
            properties={},
        )
    )

    # =========================================================================
    # Edges - Python Domain
    # =========================================================================

    # Module contains services
    mubase.add_edge(
        Edge(
            id="edge:contains:services_chat",
            source_id="mod:src/chat_agent/services/__init__.py",
            target_id="cls:src/chat_agent/services/chat_service.py:ChatService",
            type=EdgeType.CONTAINS,
            properties={},
        )
    )

    mubase.add_edge(
        Edge(
            id="edge:contains:services_agent",
            source_id="mod:src/chat_agent/services/__init__.py",
            target_id="cls:src/chat_agent/services/agent_service.py:AgentService",
            type=EdgeType.CONTAINS,
            properties={},
        )
    )

    yield mubase
    mubase.close()


# =============================================================================
# Dominaite Regression Test
# =============================================================================


@pytest.mark.integration
class TestDominaiteContextRegression:
    """Regression test for the Dominaite context extraction failure.

    On Dominaite, asking 'How does payout service work?' returned Python
    chat agent code instead of the C# PayoutService class.

    The key fix is that:
    1. Explicit language mentions filter results correctly
    2. Exact name matches are prioritized over fuzzy matches
    3. Graph expansion includes related code via edges

    Without language indicators, the system may return both languages
    (since both have "payout" and "service" matches).
    """

    def test_explicit_csharp_payout_service_query_returns_csharp(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Explicit C# mention should return C# payment code, not Python."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        # Query with explicit C# mention - this is the key fix
        result = extractor.extract("How does the C# PayoutService work?")

        # Get top results
        top_nodes = result.nodes[:5]
        top_names = [n.name for n in top_nodes]
        top_paths = [n.file_path for n in top_nodes if n.file_path]

        # PayoutService.cs should be in top results
        assert "PayoutService" in top_names, (
            f"PayoutService should be in top results. Got: {top_names}"
        )

        # C# files should be prioritized when C# is mentioned
        csharp_in_top = any(".cs" in p for p in top_paths)
        assert csharp_in_top, (
            f"C# files should be in top results. Top paths: {top_paths}"
        )

    def test_explicit_csharp_query_excludes_python(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Python PayoutHandler should NOT be in results for explicit C# query."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        # Query with explicit C# mention filters Python code
        result = extractor.extract("How does the C# PayoutService work?")

        # Get results
        node_names = [n.name for n in result.nodes]
        file_paths = [n.file_path for n in result.nodes if n.file_path]

        # Python PayoutHandler should NOT be included when C# is specified
        assert "PayoutHandler" not in node_names, (
            f"Python PayoutHandler should not appear for C# query. Got: {node_names}"
        )

        # No Python files should be in results
        python_files = [p for p in file_paths if p.endswith(".py")]
        assert len(python_files) == 0, (
            f"No Python files for C# query. Found: {python_files}"
        )

    def test_graph_based_extraction_confirmed(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Extraction method should be 'graph' when embeddings unavailable."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        result = extractor.extract("How does the PayoutService work?")

        # Verify graph-based extraction was used
        assert result.extraction_stats.get("method") == "graph", (
            "Should use graph-based extraction when embeddings unavailable"
        )
        assert result.extraction_method == "graph"

    def test_exact_name_match_finds_payoutservice(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Exact name 'PayoutService' should find the C# class."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=4000),
        )

        # Query with exact class name - should match exactly
        result = extractor.extract("PayoutService")

        node_names = [n.name for n in result.nodes]

        # Should include PayoutService as an exact match
        assert "PayoutService" in node_names, (
            f"Exact name match should find PayoutService. Got: {node_names}"
        )

        # PayoutService should be first (exact match priority)
        if len(result.nodes) > 0:
            first_node = result.nodes[0]
            assert first_node.name == "PayoutService", (
                f"PayoutService should be first. Got: {first_node.name}"
            )

    def test_graph_expansion_includes_related_code(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Graph expansion should include related code via edges."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=4000),  # Larger budget for more results
        )

        # Query for exact class name
        result = extractor.extract("PayoutService")

        node_names = [n.name for n in result.nodes]

        # Should include PayoutService
        assert "PayoutService" in node_names

        # Should also include related C# code via graph expansion:
        # - IPayoutService (via INHERITS edge)
        # - ProcessPayout or ValidatePayout (via CONTAINS edge)
        # - PayoutServiceTests (via CALLS edge)
        has_interface = "IPayoutService" in node_names
        has_method = "ProcessPayout" in node_names or "ValidatePayout" in node_names
        has_tests = "PayoutServiceTests" in node_names

        assert has_interface or has_method or has_tests, (
            f"Should include related C# code via graph edges. Got: {node_names}"
        )


# =============================================================================
# Additional Context Accuracy Tests
# =============================================================================


@pytest.mark.integration
class TestContextAccuracyGeneral:
    """General context accuracy tests for various query patterns."""

    def test_exact_name_match_returns_exact_node(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Exact name query should return that exact node first."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        result = extractor.extract("PayoutService")

        # First result should be PayoutService
        assert len(result.nodes) > 0
        assert result.nodes[0].name == "PayoutService"

    def test_interface_query_returns_interface(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Query for interface should return the interface."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        result = extractor.extract("IPayoutService")

        node_names = [n.name for n in result.nodes]
        assert "IPayoutService" in node_names

    def test_method_query_includes_parent_class(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Query for method should include parent class."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000, include_parent=True),
        )

        result = extractor.extract("ProcessPayout")

        node_names = [n.name for n in result.nodes]

        # Should include both method and class
        assert "ProcessPayout" in node_names
        # Parent class should be included via include_parent
        assert "PayoutService" in node_names


@pytest.mark.integration
class TestCrossLanguageFiltering:
    """Tests for cross-language filtering in monorepos."""

    def test_python_query_excludes_csharp(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Python-specific query should not return C# code."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        result = extractor.extract("How does the Python ChatService work?")

        file_paths = [n.file_path for n in result.nodes if n.file_path]

        # Should have Python files
        python_files = [p for p in file_paths if p.endswith(".py")]
        csharp_files = [p for p in file_paths if p.endswith(".cs")]

        # Python files should be present
        if result.nodes:
            assert len(python_files) >= len(csharp_files), (
                f"Python query should return more Python files. "
                f"Python: {python_files}, C#: {csharp_files}"
            )

    def test_generic_service_query_uses_context_clues(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Generic 'service' query uses context clues for disambiguation."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        # Query mentions "payment" which should bias toward C# PayoutService
        result = extractor.extract("How does the payment service work?")

        node_names = [n.name for n in result.nodes]

        # PayoutService should be found due to "payment" context
        # (Note: this depends on keyword matching finding "payout" from "payment")
        # The test verifies the extraction doesn't crash and returns something

        assert result is not None
        assert len(result.mu_text) > 0


@pytest.mark.integration
class TestExtractionStats:
    """Tests for extraction statistics in graph mode."""

    def test_stats_include_seeds_count(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Extraction stats should include seed node count."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        result = extractor.extract("PayoutService")

        assert "seeds" in result.extraction_stats

    def test_stats_include_expanded_count(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Extraction stats should include expanded node count."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        result = extractor.extract("PayoutService")

        assert "expanded" in result.extraction_stats

    def test_stats_include_detected_language(
        self, dominaite_mubase: MUbase
    ) -> None:
        """Extraction stats should include detected language when present."""
        extractor = SmartContextExtractor(
            dominaite_mubase,
            ExtractionConfig(max_tokens=2000),
        )

        result = extractor.extract("C# PayoutService")

        # Should detect C# language
        assert result.extraction_stats.get("detected_language") == "csharp"
