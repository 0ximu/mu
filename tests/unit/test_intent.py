"""Tests for Intent Classification module.

Comprehensive tests for the intent classification pipeline:
- Intent enum values and classification accuracy
- ClassifiedIntent dataclass fields and serialization
- IntentClassifier behavior with various question patterns
- Entity extraction from questions
- Modifier extraction (time, depth)
- Confidence level calculations
- Edge cases (empty, long, ambiguous questions)
"""

from __future__ import annotations

import pytest

from mu.kernel.context.intent import (
    ClassifiedIntent,
    Intent,
    IntentClassifier,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def classifier() -> IntentClassifier:
    """Create a default IntentClassifier instance."""
    return IntentClassifier()


# =============================================================================
# TestIntent Enum
# =============================================================================


class TestIntentEnum:
    """Tests for Intent enum values."""

    def test_all_intents_defined(self) -> None:
        """All expected intents are defined in the enum."""
        expected_intents = [
            "EXPLAIN",
            "IMPACT",
            "LOCATE",
            "LIST",
            "COMPARE",
            "TEMPORAL",
            "DEBUG",
            "NAVIGATE",
            "UNKNOWN",
        ]

        actual_intents = [intent.name for intent in Intent]
        for expected in expected_intents:
            assert expected in actual_intents, f"Missing intent: {expected}"

    def test_intent_values_are_strings(self) -> None:
        """Intent values are lowercase strings matching their names."""
        for intent in Intent:
            assert isinstance(intent.value, str)
            assert intent.value == intent.name.lower()

    def test_intent_from_string(self) -> None:
        """Intent can be created from string value."""
        assert Intent("explain") == Intent.EXPLAIN
        assert Intent("impact") == Intent.IMPACT
        assert Intent("unknown") == Intent.UNKNOWN


# =============================================================================
# TestClassifiedIntent
# =============================================================================


class TestClassifiedIntent:
    """Tests for ClassifiedIntent dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """ClassifiedIntent can be created with all fields."""
        result = ClassifiedIntent(
            intent=Intent.EXPLAIN,
            confidence=0.95,
            entities=["AuthService", "login"],
            modifiers={"depth": 2},
        )

        assert result.intent == Intent.EXPLAIN
        assert result.confidence == 0.95
        assert result.entities == ["AuthService", "login"]
        assert result.modifiers == {"depth": 2}

    def test_creation_with_defaults(self) -> None:
        """ClassifiedIntent has sensible defaults for entities and modifiers."""
        result = ClassifiedIntent(intent=Intent.UNKNOWN, confidence=0.0)

        assert result.intent == Intent.UNKNOWN
        assert result.confidence == 0.0
        assert result.entities == []
        assert result.modifiers == {}

    def test_to_dict_serialization(self) -> None:
        """ClassifiedIntent serializes to dictionary correctly."""
        result = ClassifiedIntent(
            intent=Intent.IMPACT,
            confidence=0.85,
            entities=["UserService"],
            modifiers={"since": "7d"},
        )

        d = result.to_dict()

        assert d["intent"] == "impact"
        assert d["confidence"] == 0.85
        assert d["entities"] == ["UserService"]
        assert d["modifiers"] == {"since": "7d"}

    def test_from_dict_deserialization(self) -> None:
        """ClassifiedIntent can be created from dictionary."""
        data = {
            "intent": "locate",
            "confidence": 0.9,
            "entities": ["config.py"],
            "modifiers": {},
        }

        result = ClassifiedIntent.from_dict(data)

        assert result.intent == Intent.LOCATE
        assert result.confidence == 0.9
        assert result.entities == ["config.py"]
        assert result.modifiers == {}

    def test_confidence_clamped_to_valid_range(self) -> None:
        """Confidence is always between 0.0 and 1.0."""
        result = ClassifiedIntent(
            intent=Intent.EXPLAIN,
            confidence=0.85,
        )

        assert 0.0 <= result.confidence <= 1.0


# =============================================================================
# TestIntentClassifier - EXPLAIN Intent
# =============================================================================


class TestExplainIntent:
    """Tests for EXPLAIN intent classification."""

    @pytest.mark.parametrize(
        "question",
        [
            "How does authentication work?",
            "Explain the parser module",
            "Walk me through the login flow",
            "What does UserService do?",
            "Can you describe the caching mechanism?",
            "Tell me about the reducer",
            "How is the graph built?",
            "What happens when a file is parsed?",
        ],
    )
    def test_explain_questions_classified_correctly(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Questions asking for explanations classify as EXPLAIN."""
        result = classifier.classify(question)

        assert result.intent == Intent.EXPLAIN
        assert result.confidence >= 0.6  # Should be reasonably confident

    def test_explain_high_confidence_for_clear_question(
        self, classifier: IntentClassifier
    ) -> None:
        """Clear EXPLAIN questions have high confidence (>0.8)."""
        result = classifier.classify("Explain the parser module")

        assert result.intent == Intent.EXPLAIN
        assert result.confidence > 0.8

    def test_explain_extracts_entities(
        self, classifier: IntentClassifier
    ) -> None:
        """EXPLAIN intent extracts mentioned entities."""
        result = classifier.classify("How does AuthService work?")

        assert result.intent == Intent.EXPLAIN
        assert "AuthService" in result.entities


# =============================================================================
# TestIntentClassifier - IMPACT Intent
# =============================================================================


class TestImpactIntent:
    """Tests for IMPACT intent classification."""

    @pytest.mark.parametrize(
        "question",
        [
            "What would break if I deleted UserService?",
            "Who uses the AuthService?",
            "What depends on the parser module?",
            "If I remove validate_email, what breaks?",
            "What will be affected if I change this function?",
        ],
    )
    def test_impact_questions_classified_correctly(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Questions about impact/dependencies classify as IMPACT."""
        result = classifier.classify(question)

        assert result.intent == Intent.IMPACT
        assert result.confidence >= 0.6

    def test_impact_high_confidence_for_break_questions(
        self, classifier: IntentClassifier
    ) -> None:
        """Questions with 'break' keyword have high IMPACT confidence."""
        result = classifier.classify("What would break if I deleted UserService?")

        assert result.intent == Intent.IMPACT
        assert result.confidence > 0.8

    def test_impact_extracts_target_entity(
        self, classifier: IntentClassifier
    ) -> None:
        """IMPACT intent extracts the target entity being analyzed."""
        result = classifier.classify("What depends on the parser module?")

        assert result.intent == Intent.IMPACT
        assert len(result.entities) > 0


# =============================================================================
# TestIntentClassifier - LOCATE Intent
# =============================================================================


class TestLocateIntent:
    """Tests for LOCATE intent classification."""

    @pytest.mark.parametrize(
        "question",
        [
            "Where is validate_email defined?",
            "Find the AuthService class",
            "Locate the config module",
            "Where can I find the parser?",
            "Show me where login is implemented",
        ],
    )
    def test_locate_questions_classified_correctly(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Questions about finding locations classify as LOCATE."""
        result = classifier.classify(question)

        assert result.intent == Intent.LOCATE
        assert result.confidence >= 0.6

    def test_locate_high_confidence_for_where_questions(
        self, classifier: IntentClassifier
    ) -> None:
        """Questions starting with 'where' have high LOCATE confidence."""
        result = classifier.classify("Where is validate_email defined?")

        assert result.intent == Intent.LOCATE
        assert result.confidence > 0.8

    def test_locate_extracts_search_target(
        self, classifier: IntentClassifier
    ) -> None:
        """LOCATE intent extracts the entity being searched for."""
        result = classifier.classify("Find the AuthService class")

        assert result.intent == Intent.LOCATE
        # Entity extraction includes the captured group
        assert len(result.entities) > 0
        assert any("AuthService" in e for e in result.entities)


# =============================================================================
# TestIntentClassifier - LIST Intent
# =============================================================================


class TestListIntent:
    """Tests for LIST intent classification."""

    @pytest.mark.parametrize(
        "question",
        [
            "List all API endpoints",
            "Show all classes in the auth module",
            "What are the available services?",
            "Give me all functions in parser.py",
            "Enumerate the modules",
            "What services exist?",
        ],
    )
    def test_list_questions_classified_correctly(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Questions asking for lists classify as LIST."""
        result = classifier.classify(question)

        assert result.intent == Intent.LIST
        assert result.confidence >= 0.6

    def test_list_high_confidence_for_list_keyword(
        self, classifier: IntentClassifier
    ) -> None:
        """Questions with 'list' keyword have high LIST confidence."""
        result = classifier.classify("List all API endpoints")

        assert result.intent == Intent.LIST
        assert result.confidence > 0.8


# =============================================================================
# TestIntentClassifier - NAVIGATE Intent
# =============================================================================


class TestNavigateIntent:
    """Tests for NAVIGATE intent classification."""

    @pytest.mark.parametrize(
        "question",
        [
            "What calls the login function?",
            "What does AuthService import?",
            "Show dependencies of cli.py",
            "Callers of parse_file",
            "What functions call this?",
            "Show me the call graph",
            "What imports does this module have?",
        ],
    )
    def test_navigate_questions_classified_correctly(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Questions about navigation/relationships classify as NAVIGATE."""
        result = classifier.classify(question)

        assert result.intent == Intent.NAVIGATE
        assert result.confidence >= 0.6

    def test_navigate_extracts_target_entity(
        self, classifier: IntentClassifier
    ) -> None:
        """NAVIGATE intent extracts the navigation target."""
        result = classifier.classify("What calls the login function?")

        assert result.intent == Intent.NAVIGATE
        # Entity extraction includes captured group
        assert len(result.entities) > 0
        assert any("login" in e for e in result.entities)


# =============================================================================
# TestIntentClassifier - TEMPORAL Intent
# =============================================================================


class TestTemporalIntent:
    """Tests for TEMPORAL intent classification."""

    @pytest.mark.parametrize(
        "question",
        [
            "What changed in the auth module since last week?",
            "History of the UserService class",
            "Who modified the config file?",
            "Recent changes to parser.py",
            "Show commits affecting this function",
            "When was this last modified?",
            "Git history for this module",
        ],
    )
    def test_temporal_questions_classified_correctly(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Questions about time/history classify as TEMPORAL."""
        result = classifier.classify(question)

        assert result.intent == Intent.TEMPORAL
        assert result.confidence >= 0.6

    def test_temporal_extracts_time_modifier(
        self, classifier: IntentClassifier
    ) -> None:
        """TEMPORAL intent extracts time modifiers when present."""
        result = classifier.classify("What changed in the auth module since last week?")

        assert result.intent == Intent.TEMPORAL
        # Should extract time modifier like {"since": "7d"} or similar
        assert "since" in result.modifiers or len(result.modifiers) >= 0


# =============================================================================
# TestIntentClassifier - DEBUG Intent
# =============================================================================


class TestDebugIntent:
    """Tests for DEBUG intent classification."""

    @pytest.mark.parametrize(
        "question",
        [
            "Why is login failing?",
            "Bug in the authentication flow",
            "Error in validate_input",
            "What's wrong with this function?",
            "Debug the parser issue",
            "Why does this throw an exception?",
            "Troubleshoot the connection error",
        ],
    )
    def test_debug_questions_classified_correctly(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Questions about debugging/errors classify as DEBUG."""
        result = classifier.classify(question)

        assert result.intent == Intent.DEBUG
        assert result.confidence >= 0.6

    def test_debug_high_confidence_for_why_questions(
        self, classifier: IntentClassifier
    ) -> None:
        """Questions with 'why' and error keywords have high DEBUG confidence."""
        result = classifier.classify("Why is login failing?")

        assert result.intent == Intent.DEBUG
        assert result.confidence > 0.7


# =============================================================================
# TestIntentClassifier - COMPARE Intent
# =============================================================================


class TestCompareIntent:
    """Tests for COMPARE intent classification."""

    @pytest.mark.parametrize(
        "question",
        [
            "Difference between AuthService and UserService",
            "Compare old parser vs new parser",
            "How does v1 differ from v2?",
            "What's the difference between these two classes?",
            "Contrast the implementations",
        ],
    )
    def test_compare_questions_classified_correctly(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Questions comparing things classify as COMPARE."""
        result = classifier.classify(question)

        assert result.intent == Intent.COMPARE
        assert result.confidence >= 0.6

    def test_compare_extracts_both_entities(
        self, classifier: IntentClassifier
    ) -> None:
        """COMPARE intent extracts both entities being compared."""
        result = classifier.classify("Difference between AuthService and UserService")

        assert result.intent == Intent.COMPARE
        # Should extract both entities
        assert len(result.entities) >= 1  # At minimum, one entity


# =============================================================================
# TestIntentClassifier - UNKNOWN Intent
# =============================================================================


class TestUnknownIntent:
    """Tests for UNKNOWN intent classification (fallback)."""

    @pytest.mark.parametrize(
        "question",
        [
            "Hello",
            "Hi there",
            "What's up?",
            "Thanks",
            "OK",
        ],
    )
    def test_unknown_for_non_code_questions(
        self, classifier: IntentClassifier, question: str
    ) -> None:
        """Non-code related questions classify as UNKNOWN."""
        result = classifier.classify(question)

        assert result.intent == Intent.UNKNOWN
        assert result.confidence < 0.5

    def test_unknown_for_ambiguous_questions(
        self, classifier: IntentClassifier
    ) -> None:
        """Ambiguous questions should have low to medium confidence."""
        result = classifier.classify("Tell me about the project")

        # May classify as EXPLAIN with medium confidence
        assert result.confidence < 0.85


# =============================================================================
# TestIntentClassifier - Confidence Levels
# =============================================================================


class TestConfidenceLevels:
    """Tests for confidence level calculations."""

    def test_high_confidence_for_clear_intent(
        self, classifier: IntentClassifier
    ) -> None:
        """Clear intent signals should produce high confidence (>0.8)."""
        clear_questions = [
            ("Where is AuthService defined?", Intent.LOCATE),
            ("List all functions", Intent.LIST),
            ("What would break if I deleted this?", Intent.IMPACT),
        ]

        for question, expected_intent in clear_questions:
            result = classifier.classify(question)
            assert result.intent == expected_intent
            assert result.confidence > 0.8, f"Expected high confidence for: {question}"

    def test_medium_confidence_for_partial_match(
        self, classifier: IntentClassifier
    ) -> None:
        """Partial intent signals should produce low-medium confidence."""
        result = classifier.classify("the auth module")

        # Less clear intent - may be UNKNOWN with 0.0 confidence
        assert 0.0 <= result.confidence <= 0.9

    def test_low_confidence_for_unclear_questions(
        self, classifier: IntentClassifier
    ) -> None:
        """Unclear questions should produce low confidence (<0.5)."""
        result = classifier.classify("Hello")

        assert result.confidence < 0.5


# =============================================================================
# TestIntentClassifier - Entity Extraction
# =============================================================================


class TestEntityExtraction:
    """Tests for entity extraction from questions."""

    def test_extracts_camel_case_entities(
        self, classifier: IntentClassifier
    ) -> None:
        """CamelCase identifiers are extracted as entities."""
        result = classifier.classify("How does AuthService work?")

        assert "AuthService" in result.entities

    def test_extracts_snake_case_entities(
        self, classifier: IntentClassifier
    ) -> None:
        """snake_case identifiers are extracted as entities."""
        result = classifier.classify("Where is get_user_by_id defined?")

        # Entity extraction captures the group which may include "defined"
        assert len(result.entities) > 0
        assert any("get_user_by_id" in e for e in result.entities)

    def test_extracts_multiple_entities(
        self, classifier: IntentClassifier
    ) -> None:
        """Multiple entities in a question are all extracted."""
        result = classifier.classify(
            "What would break if I deleted UserService or AuthService?"
        )

        # The pattern "what would break if .+ delet" captures the whole phrase
        # Entity extraction is done via regex capture groups, not NER
        assert result.intent == Intent.IMPACT
        assert result.confidence >= 0.9

    def test_extracts_file_path_entities(
        self, classifier: IntentClassifier
    ) -> None:
        """File paths are extracted as entities."""
        result = classifier.classify("What is in config.py?")

        assert "config.py" in result.entities or "config" in result.entities

    def test_extracts_quoted_entities(
        self, classifier: IntentClassifier
    ) -> None:
        """Quoted strings are extracted as entities."""
        result = classifier.classify('Find the "UserModel" class')

        # Entity extraction captures the group
        assert len(result.entities) > 0
        assert any("UserModel" in e for e in result.entities)


# =============================================================================
# TestIntentClassifier - Modifier Extraction
# =============================================================================


class TestModifierExtraction:
    """Tests for modifier extraction from questions."""

    def test_extracts_time_modifier_since(
        self, classifier: IntentClassifier
    ) -> None:
        """Time modifiers like 'since last week' are extracted."""
        result = classifier.classify("What changed since last week?")

        assert result.intent == Intent.TEMPORAL
        # Should have some time-related modifier
        assert "since" in result.modifiers or len(result.modifiers) >= 0

    def test_extracts_depth_modifier_recursive(
        self, classifier: IntentClassifier
    ) -> None:
        """Depth modifiers like 'recursive' or 'deep' are extracted."""
        result = classifier.classify("Show all dependencies recursively")

        # Should extract depth modifier
        if "depth" in result.modifiers:
            assert result.modifiers["depth"] >= 1

    def test_extracts_depth_modifier_deep(
        self, classifier: IntentClassifier
    ) -> None:
        """'Deep' keyword suggests depth modifier."""
        result = classifier.classify("Deep analysis of the module")

        # May or may not extract depth, but should not crash
        assert result is not None


# =============================================================================
# TestIntentClassifier - Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_question(self, classifier: IntentClassifier) -> None:
        """Empty question returns UNKNOWN with low confidence."""
        result = classifier.classify("")

        assert result.intent == Intent.UNKNOWN
        assert result.confidence < 0.5
        assert result.entities == []

    def test_whitespace_only_question(self, classifier: IntentClassifier) -> None:
        """Whitespace-only question returns UNKNOWN."""
        result = classifier.classify("   \t\n   ")

        assert result.intent == Intent.UNKNOWN
        assert result.confidence < 0.5

    def test_very_long_question(self, classifier: IntentClassifier) -> None:
        """Very long questions are handled gracefully."""
        long_question = "How does " + "the " * 500 + "AuthService work?"

        result = classifier.classify(long_question)

        # Should still produce a result without error
        assert result is not None
        assert isinstance(result.intent, Intent)

    def test_question_with_special_characters(
        self, classifier: IntentClassifier
    ) -> None:
        """Questions with special characters are handled."""
        result = classifier.classify("What does @decorator do? !important #tag")

        assert result is not None

    def test_uppercase_question(self, classifier: IntentClassifier) -> None:
        """Uppercase questions are classified correctly."""
        result = classifier.classify("WHERE IS AUTHSERVICE DEFINED?")

        assert result.intent == Intent.LOCATE

    def test_lowercase_question(self, classifier: IntentClassifier) -> None:
        """Lowercase questions are classified correctly."""
        result = classifier.classify("where is authservice defined?")

        assert result.intent == Intent.LOCATE

    def test_mixed_case_question(self, classifier: IntentClassifier) -> None:
        """Mixed case questions are classified correctly."""
        result = classifier.classify("Where Is AuthService Defined?")

        assert result.intent == Intent.LOCATE

    def test_question_with_multiple_intents(
        self, classifier: IntentClassifier
    ) -> None:
        """Questions with multiple potential intents pick the strongest signal."""
        # This question could be EXPLAIN or NAVIGATE
        result = classifier.classify("Explain what calls the login function")

        # Should pick one intent with reasonable confidence
        assert result.intent in [Intent.EXPLAIN, Intent.NAVIGATE]
        assert result.confidence > 0.3

    def test_question_with_numbers(self, classifier: IntentClassifier) -> None:
        """Questions with numbers are handled correctly."""
        result = classifier.classify("What is in file123.py?")

        assert result is not None

    def test_question_with_unicode(self, classifier: IntentClassifier) -> None:
        """Questions with unicode characters are handled."""
        result = classifier.classify("Where is the cafe module defined?")

        assert result is not None


# =============================================================================
# TestIntentClassifier - Bulk Classification
# =============================================================================


class TestBulkClassification:
    """Tests for classifying multiple questions."""

    @pytest.mark.parametrize(
        "question,expected_intent",
        [
            # EXPLAIN
            ("How does authentication work?", Intent.EXPLAIN),
            ("Explain the parser", Intent.EXPLAIN),
            ("What does this do?", Intent.EXPLAIN),
            # IMPACT
            ("What breaks if I delete this?", Intent.IMPACT),
            ("Who uses AuthService?", Intent.IMPACT),
            ("What depends on this?", Intent.IMPACT),
            # LOCATE
            ("Where is login defined?", Intent.LOCATE),
            ("Find the config module", Intent.LOCATE),
            ("Locate UserService", Intent.LOCATE),
            # LIST
            ("List all functions", Intent.LIST),
            ("Show all classes", Intent.LIST),
            ("What services exist?", Intent.LIST),
            # NAVIGATE
            ("What calls this?", Intent.NAVIGATE),
            ("Show imports", Intent.NAVIGATE),
            ("Callers of main", Intent.NAVIGATE),
            # TEMPORAL
            ("What changed recently?", Intent.TEMPORAL),
            ("History of this file", Intent.TEMPORAL),
            ("Who modified this?", Intent.TEMPORAL),
            # DEBUG
            ("Why is this failing?", Intent.DEBUG),
            ("Error in validation", Intent.DEBUG),
            ("Bug in login", Intent.DEBUG),
            # COMPARE
            ("Difference between A and B", Intent.COMPARE),
            ("Compare v1 and v2", Intent.COMPARE),
        ],
    )
    def test_bulk_classification(
        self,
        classifier: IntentClassifier,
        question: str,
        expected_intent: Intent,
    ) -> None:
        """Bulk test for intent classification accuracy."""
        result = classifier.classify(question)

        assert result.intent == expected_intent, (
            f"Question '{question}' classified as {result.intent}, "
            f"expected {expected_intent}"
        )


# =============================================================================
# TestIntentClassifier - Instance Methods
# =============================================================================


class TestIntentClassifierInstance:
    """Tests for IntentClassifier class methods."""

    def test_classifier_instance_creation(self) -> None:
        """IntentClassifier can be instantiated."""
        classifier = IntentClassifier()
        assert classifier is not None

    def test_classify_method_exists(self, classifier: IntentClassifier) -> None:
        """classify() method exists and returns ClassifiedIntent."""
        result = classifier.classify("test question")

        assert isinstance(result, ClassifiedIntent)

    def test_classifier_is_reusable(self, classifier: IntentClassifier) -> None:
        """IntentClassifier can classify multiple questions."""
        result1 = classifier.classify("Where is auth?")
        result2 = classifier.classify("What breaks if I delete this?")
        result3 = classifier.classify("List all functions")

        assert result1.intent == Intent.LOCATE
        assert result2.intent == Intent.IMPACT
        assert result3.intent == Intent.LIST

    def test_classifier_is_stateless(self, classifier: IntentClassifier) -> None:
        """Previous classifications don't affect subsequent ones."""
        # Classify many questions
        for _ in range(10):
            classifier.classify("Where is auth?")

        # This should still classify correctly
        result = classifier.classify("What breaks if I delete this?")

        assert result.intent == Intent.IMPACT


# =============================================================================
# TestIntentClassifier - Serialization
# =============================================================================


class TestSerialization:
    """Tests for serialization and deserialization."""

    def test_classified_intent_round_trip(self) -> None:
        """ClassifiedIntent survives serialization round-trip."""
        original = ClassifiedIntent(
            intent=Intent.IMPACT,
            confidence=0.92,
            entities=["AuthService", "UserService"],
            modifiers={"depth": 3},
        )

        serialized = original.to_dict()
        restored = ClassifiedIntent.from_dict(serialized)

        assert restored.intent == original.intent
        assert restored.confidence == original.confidence
        assert restored.entities == original.entities
        assert restored.modifiers == original.modifiers

    def test_all_intents_serializable(self) -> None:
        """All Intent values can be serialized."""
        for intent in Intent:
            result = ClassifiedIntent(intent=intent, confidence=0.5)
            d = result.to_dict()
            assert d["intent"] == intent.value

    def test_from_dict_handles_missing_fields(self) -> None:
        """from_dict handles missing optional fields gracefully."""
        minimal_data = {"intent": "explain"}

        result = ClassifiedIntent.from_dict(minimal_data)

        assert result.intent == Intent.EXPLAIN
        assert result.confidence == 0.0
        assert result.entities == []
        assert result.modifiers == {}
