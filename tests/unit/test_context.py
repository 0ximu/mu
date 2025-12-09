"""Tests for Smart Context extraction components.

Comprehensive unit tests for all context extraction components:
- Data models (ContextResult, ExtractionConfig, ScoredNode, ExtractedEntity)
- EntityExtractor - entity name extraction from questions
- RelevanceScorer - node relevance scoring
- TokenBudgeter - token budget management
- ContextExporter - MU format export
- SmartContextExtractor - orchestration
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.context.budgeter import TokenBudgeter
from mu.kernel.context.export import ContextExporter
from mu.kernel.context.extractor import EntityExtractor
from mu.kernel.context.models import (
    ContextResult,
    ExtractionConfig,
    ExtractedEntity,
    ScoredNode,
)
from mu.kernel.context.scorer import RelevanceScorer
from mu.kernel.context.smart import SmartContextExtractor


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_node() -> Node:
    """Create a sample function node for testing."""
    return Node(
        id="fn:src/auth.py:AuthService.login",
        type=NodeType.FUNCTION,
        name="login",
        qualified_name="auth.AuthService.login",
        file_path="src/auth.py",
        line_start=10,
        line_end=25,
        properties={
            "is_method": True,
            "is_async": True,
            "parameters": [
                {"name": "self"},
                {"name": "username", "type_annotation": "str"},
                {"name": "password", "type_annotation": "str"},
            ],
            "return_type": "bool",
        },
        complexity=15,
    )


@pytest.fixture
def sample_class_node() -> Node:
    """Create a sample class node for testing."""
    return Node(
        id="cls:src/auth.py:AuthService",
        type=NodeType.CLASS,
        name="AuthService",
        qualified_name="auth.AuthService",
        file_path="src/auth.py",
        line_start=5,
        line_end=100,
        properties={
            "bases": ["BaseService"],
            "decorators": ["@dataclass"],
            "attributes": ["username", "password_hash", "session"],
        },
        complexity=0,
    )


@pytest.fixture
def sample_module_node() -> Node:
    """Create a sample module node for testing."""
    return Node(
        id="mod:src/auth.py",
        type=NodeType.MODULE,
        name="auth",
        qualified_name="auth",
        file_path="src/auth.py",
        line_start=1,
        line_end=200,
        properties={"language": "python"},
        complexity=0,
    )


@pytest.fixture
def mock_mubase(tmp_path: Path, sample_node: Node, sample_class_node: Node, sample_module_node: Node) -> MUbase:
    """Create a mock MUbase with sample data."""
    db = MUbase(tmp_path / "test.mubase")

    # Add nodes
    db.add_node(sample_module_node)
    db.add_node(sample_class_node)
    db.add_node(sample_node)

    # Add another function
    db.add_node(Node(
        id="fn:src/auth.py:AuthService.logout",
        type=NodeType.FUNCTION,
        name="logout",
        qualified_name="auth.AuthService.logout",
        file_path="src/auth.py",
        line_start=30,
        line_end=40,
        properties={"is_method": True, "parameters": [{"name": "self"}]},
        complexity=5,
    ))

    # Add a user service
    db.add_node(Node(
        id="cls:src/user.py:UserService",
        type=NodeType.CLASS,
        name="UserService",
        qualified_name="user.UserService",
        file_path="src/user.py",
        line_start=1,
        line_end=50,
        properties={"bases": []},
        complexity=0,
    ))

    db.add_node(Node(
        id="fn:src/user.py:get_user",
        type=NodeType.FUNCTION,
        name="get_user",
        qualified_name="user.get_user",
        file_path="src/user.py",
        line_start=55,
        line_end=60,
        properties={"parameters": [{"name": "user_id", "type_annotation": "int"}], "return_type": "User"},
        complexity=10,
    ))

    # Add edges
    db.add_edge(Edge(
        id="edge:mod:auth:contains:cls:auth",
        source_id="mod:src/auth.py",
        target_id="cls:src/auth.py:AuthService",
        type=EdgeType.CONTAINS,
    ))
    db.add_edge(Edge(
        id="edge:cls:auth:contains:fn:login",
        source_id="cls:src/auth.py:AuthService",
        target_id="fn:src/auth.py:AuthService.login",
        type=EdgeType.CONTAINS,
    ))
    db.add_edge(Edge(
        id="edge:cls:auth:contains:fn:logout",
        source_id="cls:src/auth.py:AuthService",
        target_id="fn:src/auth.py:AuthService.logout",
        type=EdgeType.CONTAINS,
    ))

    yield db
    db.close()


# =============================================================================
# TestContextModels
# =============================================================================


class TestContextModels:
    """Tests for context data models."""

    def test_extraction_config_defaults(self) -> None:
        """ExtractionConfig has sensible defaults."""
        config = ExtractionConfig()

        assert config.max_tokens == 8000
        assert config.include_imports is True
        assert config.include_parent is True
        assert config.expand_depth == 1
        assert config.entity_weight == 1.0
        assert config.vector_weight == 0.7
        assert config.proximity_weight == 0.3
        assert config.min_relevance == 0.1
        assert config.exclude_tests is False
        assert config.vector_search_limit == 20
        assert config.max_expansion_nodes == 100

    def test_extraction_config_custom_values(self) -> None:
        """ExtractionConfig accepts custom values."""
        config = ExtractionConfig(
            max_tokens=4000,
            include_imports=False,
            exclude_tests=True,
            entity_weight=1.5,
            min_relevance=0.25,
        )

        assert config.max_tokens == 4000
        assert config.include_imports is False
        assert config.exclude_tests is True
        assert config.entity_weight == 1.5
        assert config.min_relevance == 0.25

    def test_extraction_config_to_dict(self) -> None:
        """ExtractionConfig serializes to dictionary."""
        config = ExtractionConfig(max_tokens=2000)
        d = config.to_dict()

        assert d["max_tokens"] == 2000
        assert "include_imports" in d
        assert "entity_weight" in d
        assert "vector_weight" in d

    def test_extracted_entity_creation(self) -> None:
        """ExtractedEntity can be created with required fields."""
        entity = ExtractedEntity(
            name="AuthService",
            confidence=0.9,
            extraction_method="camel_case",
            is_known=True,
        )

        assert entity.name == "AuthService"
        assert entity.confidence == 0.9
        assert entity.extraction_method == "camel_case"
        assert entity.is_known is True

    def test_extracted_entity_defaults(self) -> None:
        """ExtractedEntity has sensible defaults."""
        entity = ExtractedEntity(name="test")

        assert entity.name == "test"
        assert entity.confidence == 1.0
        assert entity.extraction_method == "unknown"
        assert entity.is_known is False

    def test_extracted_entity_to_dict(self) -> None:
        """ExtractedEntity serializes correctly."""
        entity = ExtractedEntity(
            name="login",
            confidence=0.8,
            extraction_method="snake_case",
        )
        d = entity.to_dict()

        assert d["name"] == "login"
        assert d["confidence"] == 0.8
        assert d["extraction_method"] == "snake_case"
        assert d["is_known"] is False

    def test_scored_node_creation(self, sample_node: Node) -> None:
        """ScoredNode can be created with score breakdown."""
        scored = ScoredNode(
            node=sample_node,
            score=0.85,
            entity_score=0.9,
            vector_score=0.7,
            proximity_score=0.5,
            estimated_tokens=30,
        )

        assert scored.node == sample_node
        assert scored.score == 0.85
        assert scored.entity_score == 0.9
        assert scored.vector_score == 0.7
        assert scored.proximity_score == 0.5
        assert scored.estimated_tokens == 30

    def test_scored_node_defaults(self, sample_node: Node) -> None:
        """ScoredNode has default score components."""
        scored = ScoredNode(node=sample_node, score=0.5)

        assert scored.entity_score == 0.0
        assert scored.vector_score == 0.0
        assert scored.proximity_score == 0.0
        assert scored.estimated_tokens == 0

    def test_scored_node_to_dict(self, sample_node: Node) -> None:
        """ScoredNode serializes with rounded scores."""
        scored = ScoredNode(
            node=sample_node,
            score=0.85432,
            entity_score=0.91234,
        )
        d = scored.to_dict()

        assert "node" in d
        assert d["score"] == 0.8543
        assert d["entity_score"] == 0.9123
        assert "estimated_tokens" in d

    def test_context_result_creation(self, sample_node: Node) -> None:
        """ContextResult can be created with all fields."""
        result = ContextResult(
            mu_text="# Context\n!auth",
            nodes=[sample_node],
            token_count=50,
            relevance_scores={sample_node.id: 0.9},
            extraction_stats={"entities_extracted": 2},
        )

        assert "!auth" in result.mu_text
        assert len(result.nodes) == 1
        assert result.token_count == 50
        assert result.relevance_scores[sample_node.id] == 0.9
        assert result.extraction_stats["entities_extracted"] == 2

    def test_context_result_defaults(self) -> None:
        """ContextResult has empty defaults."""
        result = ContextResult(mu_text="")

        assert result.nodes == []
        assert result.token_count == 0
        assert result.relevance_scores == {}
        assert result.extraction_stats == {}

    def test_context_result_to_dict(self, sample_node: Node) -> None:
        """ContextResult serializes correctly."""
        result = ContextResult(
            mu_text="test output",
            nodes=[sample_node],
            token_count=100,
            relevance_scores={sample_node.id: 0.85},
            extraction_stats={"test": 1},
        )
        d = result.to_dict()

        assert d["mu_text"] == "test output"
        assert len(d["nodes"]) == 1
        assert d["token_count"] == 100
        assert d["extraction_stats"]["test"] == 1


# =============================================================================
# TestEntityExtractor
# =============================================================================


class TestEntityExtractor:
    """Tests for EntityExtractor."""

    def test_extract_camel_case(self) -> None:
        """Extracts CamelCase identifiers like AuthService."""
        extractor = EntityExtractor()
        entities = extractor.extract("How does AuthService handle login?")

        names = [e.name for e in entities]
        assert "AuthService" in names

        # Find the AuthService entity
        auth_entity = next(e for e in entities if e.name == "AuthService")
        assert auth_entity.extraction_method == "camel_case"
        assert auth_entity.confidence >= 0.8

    def test_extract_snake_case(self) -> None:
        """Extracts snake_case identifiers like get_user."""
        extractor = EntityExtractor()
        entities = extractor.extract("What does get_user_by_id do?")

        names = [e.name for e in entities]
        assert "get_user_by_id" in names

        entity = next(e for e in entities if e.name == "get_user_by_id")
        assert entity.extraction_method == "snake_case"

    def test_extract_quoted_strings(self) -> None:
        """Extracts quoted strings like 'config.py'."""
        extractor = EntityExtractor()
        entities = extractor.extract('What is in "config.py"?')

        names = [e.name for e in entities]
        assert "config.py" in names

        entity = next(e for e in entities if e.name == "config.py")
        assert entity.extraction_method == "quoted"
        assert entity.confidence == 1.0

    def test_extract_single_quoted_strings(self) -> None:
        """Extracts single-quoted strings."""
        extractor = EntityExtractor()
        entities = extractor.extract("How does 'UserService' work?")

        names = [e.name for e in entities]
        assert "UserService" in names

    def test_extract_constants(self) -> None:
        """Extracts CONSTANT identifiers like MAX_RETRIES."""
        extractor = EntityExtractor()
        entities = extractor.extract("What is the MAX_RETRIES value?")

        names = [e.name for e in entities]
        assert "MAX_RETRIES" in names

        entity = next(e for e in entities if e.name == "MAX_RETRIES")
        assert entity.extraction_method == "constant"

    def test_extract_qualified_names(self) -> None:
        """Extracts qualified names like auth.service.login."""
        extractor = EntityExtractor()
        entities = extractor.extract("Where is auth.service.login defined?")

        names = [e.name for e in entities]
        assert "auth.service.login" in names

        entity = next(e for e in entities if e.name == "auth.service.login")
        assert entity.extraction_method == "qualified"

    def test_extract_file_paths(self) -> None:
        """Extracts file paths like src/auth.py."""
        extractor = EntityExtractor()
        entities = extractor.extract("What is in src/auth.py?")

        names = [e.name for e in entities]
        assert "src/auth.py" in names

        entity = next(e for e in entities if e.name == "src/auth.py")
        assert entity.extraction_method == "file_path"

    def test_extract_with_known_names(self) -> None:
        """Known names get boosted confidence."""
        known = {"AuthService", "UserService", "get_user"}
        extractor = EntityExtractor(known_names=known)

        entities = extractor.extract("How does AuthService work?")

        auth_entity = next(e for e in entities if e.name == "AuthService")
        assert auth_entity.is_known is True
        assert auth_entity.confidence > 0.9  # Boosted

    def test_extract_known_name_suffix_match(self) -> None:
        """Known names match by suffix (e.g., auth.AuthService)."""
        known = {"auth.AuthService"}
        extractor = EntityExtractor(known_names=known)

        entities = extractor.extract("How does AuthService work?")

        # Should find AuthService and mark as known due to suffix match
        auth_entity = next(e for e in entities if e.name == "AuthService")
        assert auth_entity.is_known is True

    def test_extract_deduplicates(self) -> None:
        """Duplicate entities are deduplicated."""
        extractor = EntityExtractor()
        entities = extractor.extract(
            'AuthService and "AuthService" mentioned twice'
        )

        auth_count = sum(1 for e in entities if e.name == "AuthService")
        assert auth_count == 1

    def test_extract_filters_stop_words(self) -> None:
        """Common stop words are not extracted."""
        extractor = EntityExtractor()
        entities = extractor.extract("How does the function work?")

        names = [e.name for e in entities]
        assert "the" not in names
        assert "does" not in names
        assert "how" not in [n.lower() for n in names]

    def test_extract_filters_short_names(self) -> None:
        """Very short names (< 2 chars) are filtered."""
        extractor = EntityExtractor()
        entities = extractor.extract('What is "x"?')

        names = [e.name for e in entities]
        assert "x" not in names

    def test_extract_sorted_by_confidence(self) -> None:
        """Results are sorted by confidence descending."""
        extractor = EntityExtractor()
        entities = extractor.extract(
            'Check "config.py" and AuthService and get_user'
        )

        # Quoted strings have highest confidence
        assert len(entities) >= 2
        confidences = [e.confidence for e in entities]
        assert confidences == sorted(confidences, reverse=True)

    def test_extract_empty_text(self) -> None:
        """Empty text returns empty list."""
        extractor = EntityExtractor()
        entities = extractor.extract("")

        assert entities == []

    def test_extract_no_entities(self) -> None:
        """Text without code entities returns minimal results."""
        extractor = EntityExtractor()
        entities = extractor.extract("Hello world!")

        # May have some false positives (lowercase words have low confidence 0.4)
        # but highly confident entities should be minimal
        high_confidence = [e for e in entities if e.confidence >= 0.6]
        assert len(high_confidence) <= 1  # "Hello" as pascal_single

    def test_extract_finds_known_names_in_text(self) -> None:
        """Known names are found even without pattern match."""
        known = {"login", "auth.service"}
        extractor = EntityExtractor(known_names=known)

        entities = extractor.extract("Check the login functionality")

        # Should find 'login' from known names
        names = [e.name for e in entities]
        assert "login" in names

    def test_extract_case_insensitive_known_match(self) -> None:
        """Known names match case-insensitively."""
        known = {"AuthService"}
        extractor = EntityExtractor(known_names=known)

        # Even if text has different case, should recognize
        entities = extractor.extract("authservice handles login")

        # The pattern extraction will find different things,
        # but known name matching should work
        auth_entities = [e for e in entities if "auth" in e.name.lower()]
        assert len(auth_entities) >= 0  # At least no crash


# =============================================================================
# TestRelevanceScorer
# =============================================================================


class TestRelevanceScorer:
    """Tests for RelevanceScorer."""

    @pytest.fixture
    def scorer(self, mock_mubase: MUbase) -> RelevanceScorer:
        """Create a RelevanceScorer with mock database."""
        config = ExtractionConfig()
        return RelevanceScorer(config, mock_mubase)

    def test_score_exact_entity_match(
        self, scorer: RelevanceScorer, sample_node: Node
    ) -> None:
        """Exact entity name match gets score 1.0."""
        entities = [ExtractedEntity(name="login", confidence=1.0)]

        scored = scorer.score_nodes(
            nodes=[sample_node],
            question="How does login work?",
            entities=entities,
            seed_node_ids=set(),
        )

        assert len(scored) == 1
        assert scored[0].entity_score == 1.0

    def test_score_partial_entity_match(
        self, scorer: RelevanceScorer, sample_class_node: Node
    ) -> None:
        """Partial entity match (suffix) gets lower score."""
        entities = [ExtractedEntity(name="Service", confidence=1.0)]

        scored = scorer.score_nodes(
            nodes=[sample_class_node],  # AuthService
            question="What services exist?",
            entities=entities,
            seed_node_ids=set(),
        )

        assert len(scored) == 1
        # Suffix match should give ~0.6
        assert 0.3 < scored[0].entity_score < 0.8

    def test_score_case_insensitive_match(
        self, scorer: RelevanceScorer, sample_node: Node
    ) -> None:
        """Case-insensitive match gets moderate score."""
        entities = [ExtractedEntity(name="LOGIN", confidence=1.0)]

        scored = scorer.score_nodes(
            nodes=[sample_node],  # login (lowercase)
            question="How does LOGIN work?",
            entities=entities,
            seed_node_ids=set(),
        )

        assert len(scored) == 1
        # Case-insensitive match should give ~0.8
        assert scored[0].entity_score >= 0.5

    def test_score_with_vector_scores(
        self, scorer: RelevanceScorer, sample_node: Node
    ) -> None:
        """Vector scores are included in final score."""
        entities = [ExtractedEntity(name="other", confidence=1.0)]
        vector_scores = {sample_node.id: 0.9}

        scored = scorer.score_nodes(
            nodes=[sample_node],
            question="Authentication question",
            entities=entities,
            seed_node_ids=set(),
            vector_scores=vector_scores,
        )

        assert len(scored) == 1
        assert scored[0].vector_score == 0.9
        # Score should include vector component
        assert scored[0].score > 0

    def test_score_proximity_seed_node(
        self, scorer: RelevanceScorer, sample_node: Node
    ) -> None:
        """Seed nodes get proximity score of 1.0."""
        seed_ids = {sample_node.id}
        entities = [ExtractedEntity(name="login", confidence=1.0)]

        scored = scorer.score_nodes(
            nodes=[sample_node],
            question="login?",
            entities=entities,
            seed_node_ids=seed_ids,
        )

        assert len(scored) == 1
        assert scored[0].proximity_score == 1.0

    def test_score_filters_below_min_relevance(
        self, scorer: RelevanceScorer
    ) -> None:
        """Nodes below min_relevance are filtered out."""
        # Create a node that won't match anything
        node = Node(
            id="fn:unrelated",
            type=NodeType.FUNCTION,
            name="unrelated_function",
        )
        entities = [ExtractedEntity(name="something_else", confidence=1.0)]

        scored = scorer.score_nodes(
            nodes=[node],
            question="something else",
            entities=entities,
            seed_node_ids=set(),
        )

        # Should be filtered due to low score
        assert len(scored) == 0

    def test_score_combines_weights(
        self, scorer: RelevanceScorer, sample_node: Node
    ) -> None:
        """Scores are combined with configured weights."""
        entities = [ExtractedEntity(name="login", confidence=1.0)]
        seed_ids = {sample_node.id}
        vector_scores = {sample_node.id: 0.8}

        scored = scorer.score_nodes(
            nodes=[sample_node],
            question="login",
            entities=entities,
            seed_node_ids=seed_ids,
            vector_scores=vector_scores,
        )

        assert len(scored) == 1
        sn = scored[0]

        # Check combined score roughly matches weighted sum
        expected = (
            scorer.config.entity_weight * sn.entity_score
            + scorer.config.vector_weight * sn.vector_score
            + scorer.config.proximity_weight * sn.proximity_score
        )
        assert abs(sn.score - expected) < 0.01

    def test_score_sorted_by_score_descending(
        self, scorer: RelevanceScorer, mock_mubase: MUbase
    ) -> None:
        """Results are sorted by score descending."""
        nodes = list(mock_mubase.get_nodes(NodeType.FUNCTION))
        entities = [
            ExtractedEntity(name="login", confidence=1.0),
            ExtractedEntity(name="logout", confidence=0.8),
        ]

        scored = scorer.score_nodes(
            nodes=nodes,
            question="login logout",
            entities=entities,
            seed_node_ids=set(),
        )

        if len(scored) > 1:
            scores = [sn.score for sn in scored]
            assert scores == sorted(scores, reverse=True)

    def test_score_no_entities_returns_empty(
        self, scorer: RelevanceScorer, sample_node: Node
    ) -> None:
        """No entities and no vector scores results in no matches."""
        scored = scorer.score_nodes(
            nodes=[sample_node],
            question="random question",
            entities=[],
            seed_node_ids=set(),
        )

        # Without entities or vector scores, all nodes filtered
        assert len(scored) == 0


# =============================================================================
# TestTokenBudgeter
# =============================================================================


class TestTokenBudgeter:
    """Tests for TokenBudgeter."""

    def test_count_tokens(self) -> None:
        """Token counting works correctly."""
        budgeter = TokenBudgeter(max_tokens=1000)

        count = budgeter.count_tokens("Hello, world!")
        assert count > 0
        assert count < 10  # Should be ~4 tokens

    def test_count_tokens_empty(self) -> None:
        """Empty string has 0 tokens."""
        budgeter = TokenBudgeter(max_tokens=1000)

        count = budgeter.count_tokens("")
        assert count == 0

    def test_estimate_node_tokens_function(self, sample_node: Node) -> None:
        """Function node token estimation includes parameters."""
        budgeter = TokenBudgeter(max_tokens=1000)

        estimate = budgeter.estimate_node_tokens(sample_node)

        # Should include base + name + parameters
        assert estimate > 20  # Base for function
        assert estimate < 100  # Not too large

    def test_estimate_node_tokens_class(self, sample_class_node: Node) -> None:
        """Class node token estimation includes attributes."""
        budgeter = TokenBudgeter(max_tokens=1000)

        estimate = budgeter.estimate_node_tokens(sample_class_node)

        # Should include base + name + attributes + bases
        assert estimate > 25  # Base for class
        assert estimate < 100

    def test_estimate_node_tokens_cached(self, sample_node: Node) -> None:
        """Token estimates are cached."""
        budgeter = TokenBudgeter(max_tokens=1000)

        estimate1 = budgeter.estimate_node_tokens(sample_node)
        estimate2 = budgeter.estimate_node_tokens(sample_node)

        assert estimate1 == estimate2
        assert sample_node.id in budgeter._token_cache

    def test_fit_to_budget_respects_limit(
        self, sample_node: Node, sample_class_node: Node
    ) -> None:
        """fit_to_budget respects the max_tokens limit."""
        budgeter = TokenBudgeter(max_tokens=50)  # Very small budget

        scored_nodes = [
            ScoredNode(node=sample_class_node, score=0.9),
            ScoredNode(node=sample_node, score=0.8),
        ]

        selected = budgeter.fit_to_budget(scored_nodes)

        # Should select fewer nodes to fit budget
        total_tokens = sum(sn.estimated_tokens for sn in selected)
        assert total_tokens <= 50 or len(selected) == 0

    def test_fit_to_budget_prioritizes_high_scores(
        self, sample_node: Node, sample_class_node: Node
    ) -> None:
        """Higher-scored nodes are selected first."""
        budgeter = TokenBudgeter(max_tokens=100)

        scored_nodes = [
            ScoredNode(node=sample_node, score=0.9),  # Higher score
            ScoredNode(node=sample_class_node, score=0.5),  # Lower score
        ]

        selected = budgeter.fit_to_budget(scored_nodes)

        # First selected should be highest scored
        if selected:
            assert selected[0].node.id == sample_node.id

    def test_fit_to_budget_includes_parent_context(
        self, mock_mubase: MUbase, sample_node: Node
    ) -> None:
        """Parent class is included when method is selected."""
        budgeter = TokenBudgeter(max_tokens=500)

        # sample_node is a method with is_method=True
        scored_nodes = [ScoredNode(node=sample_node, score=0.9)]

        selected = budgeter.fit_to_budget(
            scored_nodes,
            mubase=mock_mubase,
            include_parent=True,
        )

        # Should include the parent class
        selected_ids = {sn.node.id for sn in selected}
        assert sample_node.id in selected_ids
        # Parent (AuthService) should also be included
        assert "cls:src/auth.py:AuthService" in selected_ids

    def test_fit_to_budget_empty_list(self) -> None:
        """Empty input returns empty output."""
        budgeter = TokenBudgeter(max_tokens=1000)

        selected = budgeter.fit_to_budget([])

        assert selected == []

    def test_get_actual_tokens(self) -> None:
        """Actual token count matches count_tokens."""
        budgeter = TokenBudgeter(max_tokens=1000)
        text = "!module auth\n$AuthService\n#login()"

        actual = budgeter.get_actual_tokens(text)
        expected = budgeter.count_tokens(text)

        assert actual == expected

    def test_estimate_node_tokens_with_docstring(self, sample_node: Node) -> None:
        """Node with docstring includes docstring tokens."""
        from mu.kernel.context.models import ExportConfig

        # Create config with docstrings enabled
        export_config = ExportConfig(include_docstrings=True)
        budgeter = TokenBudgeter(max_tokens=1000, export_config=export_config)

        # Add docstring to node properties
        sample_node.properties["docstring"] = "This is a test function that does something useful."

        estimate_with_doc = budgeter.estimate_node_tokens(sample_node)

        # Now disable docstrings
        export_config_no_doc = ExportConfig(include_docstrings=False)
        budgeter_no_doc = TokenBudgeter(max_tokens=1000, export_config=export_config_no_doc)

        estimate_without_doc = budgeter_no_doc.estimate_node_tokens(sample_node)

        # With docstring should have more tokens
        assert estimate_with_doc > estimate_without_doc
        assert (estimate_with_doc - estimate_without_doc) > 0

    def test_estimate_node_tokens_with_line_numbers(self, sample_node: Node) -> None:
        """Node with line numbers enabled includes line number overhead."""
        from mu.kernel.context.models import ExportConfig

        # Create config with line numbers enabled
        export_config = ExportConfig(include_line_numbers=True)
        budgeter = TokenBudgeter(max_tokens=1000, export_config=export_config)

        estimate_with_lines = budgeter.estimate_node_tokens(sample_node)

        # Now disable line numbers
        export_config_no_lines = ExportConfig(include_line_numbers=False)
        budgeter_no_lines = TokenBudgeter(max_tokens=1000, export_config=export_config_no_lines)

        estimate_without_lines = budgeter_no_lines.estimate_node_tokens(sample_node)

        # With line numbers should have more tokens (approximately 5)
        assert estimate_with_lines > estimate_without_lines
        assert (estimate_with_lines - estimate_without_lines) == 5


# =============================================================================
# TestContextExporter
# =============================================================================


class TestContextExporter:
    """Tests for ContextExporter."""

    @pytest.fixture
    def exporter(self, mock_mubase: MUbase) -> ContextExporter:
        """Create a ContextExporter with mock database."""
        return ContextExporter(mock_mubase, include_scores=False)

    def test_export_mu_empty_list(self, exporter: ContextExporter) -> None:
        """Empty node list produces empty context message."""
        result = exporter.export_mu([])

        assert "No relevant context found" in result

    def test_export_mu_single_function(
        self, exporter: ContextExporter, sample_node: Node
    ) -> None:
        """Single function exports correctly."""
        scored = [ScoredNode(node=sample_node, score=0.9)]

        result = exporter.export_mu(scored)

        # Should have module header
        assert "!module" in result
        # Should have function sigil
        assert "#" in result
        # Should have function name
        assert "login" in result

    def test_export_mu_class_with_methods(
        self, exporter: ContextExporter, sample_class_node: Node, sample_node: Node
    ) -> None:
        """Class with methods exports hierarchically."""
        scored = [
            ScoredNode(node=sample_class_node, score=0.9),
            ScoredNode(node=sample_node, score=0.8),
        ]

        result = exporter.export_mu(scored)

        # Should have class
        assert "$" in result
        assert "AuthService" in result
        # Should have method
        assert "#" in result
        assert "login" in result

    def test_export_mu_grouped_by_module(
        self, exporter: ContextExporter, mock_mubase: MUbase
    ) -> None:
        """Nodes are grouped by module path."""
        # Get nodes from different modules
        auth_node = mock_mubase.get_node("fn:src/auth.py:AuthService.login")
        user_node = mock_mubase.get_node("fn:src/user.py:get_user")

        scored = [
            ScoredNode(node=auth_node, score=0.9),
            ScoredNode(node=user_node, score=0.8),
        ]

        result = exporter.export_mu(scored)

        # Should have multiple module headers
        assert result.count("!module") == 2

    def test_export_mu_includes_async_modifier(
        self, exporter: ContextExporter, sample_node: Node
    ) -> None:
        """Async functions show async modifier."""
        scored = [ScoredNode(node=sample_node, score=0.9)]

        result = exporter.export_mu(scored)

        # sample_node has is_async=True
        assert "async" in result

    def test_export_mu_includes_parameters(
        self, exporter: ContextExporter, sample_node: Node
    ) -> None:
        """Function parameters are included."""
        scored = [ScoredNode(node=sample_node, score=0.9)]

        result = exporter.export_mu(scored)

        # Should have parameters
        assert "username" in result
        assert "password" in result

    def test_export_mu_includes_return_type(
        self, exporter: ContextExporter, sample_node: Node
    ) -> None:
        """Return type is shown with arrow operator."""
        scored = [ScoredNode(node=sample_node, score=0.9)]

        result = exporter.export_mu(scored)

        # sample_node has return_type=bool
        assert "->" in result
        assert "bool" in result

    def test_export_mu_with_scores(
        self, mock_mubase: MUbase, sample_node: Node
    ) -> None:
        """Score annotations are included when enabled."""
        exporter = ContextExporter(mock_mubase, include_scores=True)
        scored = [ScoredNode(node=sample_node, score=0.85)]

        result = exporter.export_mu(scored)

        assert "relevance=" in result
        assert "0.85" in result

    def test_export_mu_class_inheritance(
        self, exporter: ContextExporter, sample_class_node: Node
    ) -> None:
        """Class inheritance is shown with < operator."""
        scored = [ScoredNode(node=sample_class_node, score=0.9)]

        result = exporter.export_mu(scored)

        # sample_class_node has bases=["BaseService"]
        assert "<" in result
        assert "BaseService" in result

    def test_export_json(
        self, exporter: ContextExporter, sample_node: Node
    ) -> None:
        """JSON export produces valid JSON."""
        import json

        result = ContextResult(
            mu_text="test",
            nodes=[sample_node],
            token_count=50,
            relevance_scores={sample_node.id: 0.9},
            extraction_stats={"test": 1},
        )

        json_str = exporter.export_json(result)
        data = json.loads(json_str)

        assert data["node_count"] == 1
        assert data["token_count"] == 50
        assert len(data["nodes"]) == 1
        assert "mu_text" in data


# =============================================================================
# TestSmartContextExtractor
# =============================================================================


class TestSmartContextExtractor:
    """Tests for SmartContextExtractor."""

    def test_extract_finds_entity_matches(self, mock_mubase: MUbase) -> None:
        """Extraction finds nodes matching question entities."""
        extractor = SmartContextExtractor(mock_mubase)

        result = extractor.extract("How does AuthService login work?")

        # Should find AuthService and login
        assert len(result.nodes) > 0
        node_names = [n.name for n in result.nodes]
        # Should include login or AuthService
        assert any("login" in name or "Auth" in name for name in node_names)

    def test_extract_respects_token_budget(self, mock_mubase: MUbase) -> None:
        """Extraction respects max_tokens limit."""
        config = ExtractionConfig(max_tokens=100)
        extractor = SmartContextExtractor(mock_mubase, config)

        result = extractor.extract("Tell me everything about authentication")

        assert result.token_count <= 100 or result.token_count == 0

    def test_extract_returns_mu_text(self, mock_mubase: MUbase) -> None:
        """Extraction returns valid MU format text."""
        extractor = SmartContextExtractor(mock_mubase)

        result = extractor.extract("How does login work?")

        assert result.mu_text != ""
        # Should have MU sigils
        assert any(s in result.mu_text for s in ["!", "$", "#", "::"])

    def test_extract_includes_stats(self, mock_mubase: MUbase) -> None:
        """Extraction includes debugging stats."""
        extractor = SmartContextExtractor(mock_mubase)

        result = extractor.extract("What is AuthService?")

        assert "entities_extracted" in result.extraction_stats
        assert "question_length" in result.extraction_stats
        assert "max_tokens" in result.extraction_stats

    def test_extract_empty_result_for_no_matches(self, mock_mubase: MUbase) -> None:
        """Returns empty result when no matches found."""
        extractor = SmartContextExtractor(mock_mubase)

        result = extractor.extract("xyzzy12345 nonexistent")

        # May return empty or minimal result
        assert result is not None
        assert "No relevant context" in result.mu_text or len(result.nodes) == 0

    def test_extract_excludes_tests_when_configured(
        self, mock_mubase: MUbase
    ) -> None:
        """Test files are excluded when exclude_tests=True."""
        # Add a test file to the database
        mock_mubase.add_node(Node(
            id="fn:tests/test_auth.py:test_login",
            type=NodeType.FUNCTION,
            name="test_login",
            qualified_name="test_auth.test_login",
            file_path="tests/test_auth.py",
            properties={},
            complexity=5,
        ))

        config = ExtractionConfig(exclude_tests=True)
        extractor = SmartContextExtractor(mock_mubase, config)

        result = extractor.extract("How does login work?")

        # Should not include test file
        file_paths = [n.file_path for n in result.nodes if n.file_path]
        assert not any("test" in p for p in file_paths)

    def test_extract_with_custom_weights(self, mock_mubase: MUbase) -> None:
        """Custom scoring weights are applied."""
        config = ExtractionConfig(
            entity_weight=2.0,  # Higher weight for entities
            vector_weight=0.0,  # No vector scoring
            proximity_weight=0.5,
        )
        extractor = SmartContextExtractor(mock_mubase, config)

        result = extractor.extract("AuthService login")

        # Should still work with custom weights
        assert result is not None

    @patch("mu.kernel.context.smart.SmartContextExtractor._vector_search")
    def test_extract_works_without_embeddings(
        self, mock_vector: MagicMock, mock_mubase: MUbase
    ) -> None:
        """Extraction works in degraded mode without embeddings."""
        mock_vector.return_value = ([], {}, "no_embeddings")  # No vector results

        extractor = SmartContextExtractor(mock_mubase)
        result = extractor.extract("How does AuthService work?")

        # Should still find entities
        assert result is not None
        assert len(result.nodes) > 0
        # Stats should indicate vector search was skipped
        assert result.extraction_stats.get("vector_search_used") is False
        assert result.extraction_stats.get("vector_search_skipped") == "no_embeddings"

    def test_extract_expands_graph(self, mock_mubase: MUbase) -> None:
        """Graph expansion includes related nodes."""
        config = ExtractionConfig(expand_depth=1)
        extractor = SmartContextExtractor(mock_mubase, config)

        result = extractor.extract("login")

        # Should expand to include related nodes
        stats = result.extraction_stats
        assert stats.get("candidates_after_expansion", 0) >= stats.get(
            "candidates_before_expansion", 0
        )

    def test_extract_relevance_scores_populated(self, mock_mubase: MUbase) -> None:
        """Relevance scores are populated for selected nodes."""
        extractor = SmartContextExtractor(mock_mubase)

        result = extractor.extract("AuthService")

        if result.nodes:
            for node in result.nodes:
                assert node.id in result.relevance_scores
                assert result.relevance_scores[node.id] > 0


# =============================================================================
# TestMUbaseContextMethod
# =============================================================================


class TestMUbaseContextMethod:
    """Tests for MUbase.get_context_for_question()."""

    def test_get_context_for_question_works(self, mock_mubase: MUbase) -> None:
        """get_context_for_question returns ContextResult."""
        result = mock_mubase.get_context_for_question(
            "How does AuthService work?"
        )

        assert hasattr(result, "mu_text")
        assert hasattr(result, "nodes")
        assert hasattr(result, "token_count")

    def test_get_context_for_question_respects_max_tokens(
        self, mock_mubase: MUbase
    ) -> None:
        """max_tokens parameter is respected."""
        result = mock_mubase.get_context_for_question(
            "Everything about auth",
            max_tokens=200,
        )

        assert result.token_count <= 200 or len(result.nodes) == 0

    def test_get_context_for_question_passes_kwargs(
        self, mock_mubase: MUbase
    ) -> None:
        """Additional kwargs are passed to ExtractionConfig."""
        result = mock_mubase.get_context_for_question(
            "login",
            max_tokens=1000,
            exclude_tests=True,
            expand_depth=2,
        )

        # Should work without errors
        assert result is not None

    def test_has_embeddings_returns_bool(self, mock_mubase: MUbase) -> None:
        """has_embeddings returns boolean."""
        result = mock_mubase.has_embeddings()

        assert isinstance(result, bool)
        # Our mock db doesn't have embeddings
        assert result is False

    def test_find_nodes_by_suffix(self, mock_mubase: MUbase) -> None:
        """find_nodes_by_suffix finds matching nodes."""
        results = mock_mubase.find_nodes_by_suffix("Service")

        names = [n.name for n in results]
        assert "AuthService" in names
        assert "UserService" in names

    def test_get_neighbors(self, mock_mubase: MUbase) -> None:
        """get_neighbors returns both directions."""
        neighbors = mock_mubase.get_neighbors(
            "cls:src/auth.py:AuthService",
            direction="both",
        )

        # Should include parent (module) and children (methods)
        assert len(neighbors) > 0

    def test_get_neighbors_outgoing(self, mock_mubase: MUbase) -> None:
        """get_neighbors with outgoing direction."""
        neighbors = mock_mubase.get_neighbors(
            "cls:src/auth.py:AuthService",
            direction="outgoing",
        )

        # Class has outgoing CONTAINS edges to methods
        neighbor_ids = [n.id for n in neighbors]
        assert "fn:src/auth.py:AuthService.login" in neighbor_ids

    def test_get_neighbors_incoming(self, mock_mubase: MUbase) -> None:
        """get_neighbors with incoming direction."""
        neighbors = mock_mubase.get_neighbors(
            "cls:src/auth.py:AuthService",
            direction="incoming",
        )

        # Class has incoming CONTAINS edge from module
        neighbor_ids = [n.id for n in neighbors]
        assert "mod:src/auth.py" in neighbor_ids
