"""Intent classification for natural language questions.

Classifies user questions into predefined intent categories to enable
specialized context extraction strategies.

Example:
    >>> from mu.kernel.context.intent import IntentClassifier
    >>>
    >>> classifier = IntentClassifier()
    >>> result = classifier.classify("How does authentication work?")
    >>> print(result.intent)  # Intent.EXPLAIN
    >>> print(result.confidence)  # 0.9
    >>> print(result.entities)  # ["authentication"]

Intent Taxonomy:
    - EXPLAIN: Follow calls, include docstrings, order by flow
    - IMPACT: Run impact analysis, follow dependents, show risk
    - LOCATE: Return single node, minimal expansion
    - LIST: Pattern query, return collection
    - COMPARE: Fetch both, side-by-side
    - TEMPORAL: Query snapshots, node_history
    - DEBUG: Include tests, error handlers, related issues
    - NAVIGATE: Direct graph query, structured result
    - UNKNOWN: Fallback to default SmartContextExtractor
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intent(Enum):
    """Classification of user question intent.

    Each intent maps to a specialized extraction strategy that optimizes
    context selection for that type of question.
    """

    EXPLAIN = "explain"
    """Follow calls, include docstrings, order by flow."""

    IMPACT = "impact"
    """Run impact analysis, follow dependents, show risk."""

    LOCATE = "locate"
    """Return single node, minimal expansion."""

    LIST = "list"
    """Pattern query, return collection."""

    COMPARE = "compare"
    """Fetch both entities, side-by-side comparison."""

    TEMPORAL = "temporal"
    """Query snapshots, node_history, blame info."""

    DEBUG = "debug"
    """Include tests, error handlers, related issues."""

    NAVIGATE = "navigate"
    """Direct graph query, structured result."""

    UNKNOWN = "unknown"
    """Fallback to default SmartContextExtractor."""


@dataclass
class ClassifiedIntent:
    """Result of intent classification.

    Contains the classified intent, confidence score, and extracted
    entities and modifiers from the question.
    """

    intent: Intent
    """The classified intent type."""

    confidence: float
    """Confidence score from 0.0 to 1.0."""

    entities: list[str] = field(default_factory=list)
    """Code entities extracted from the question."""

    modifiers: dict[str, Any] = field(default_factory=dict)
    """Additional modifiers extracted from the question (e.g., depth, time range)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "intent": self.intent.value,
            "confidence": round(self.confidence, 4),
            "entities": self.entities,
            "modifiers": self.modifiers,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClassifiedIntent:
        """Create a ClassifiedIntent from a dictionary.

        Args:
            data: Dictionary with intent data.

        Returns:
            ClassifiedIntent instance.
        """
        intent_str = data.get("intent", "unknown")
        try:
            intent = Intent(intent_str)
        except ValueError:
            intent = Intent.UNKNOWN

        return cls(
            intent=intent,
            confidence=data.get("confidence", 0.0),
            entities=data.get("entities", []),
            modifiers=data.get("modifiers", {}),
        )

    @property
    def is_high_confidence(self) -> bool:
        """Check if confidence is HIGH (>0.8)."""
        return self.confidence > 0.8

    @property
    def is_medium_confidence(self) -> bool:
        """Check if confidence is MEDIUM (0.5-0.8)."""
        return 0.5 <= self.confidence <= 0.8

    @property
    def is_low_confidence(self) -> bool:
        """Check if confidence is LOW (<0.5)."""
        return self.confidence < 0.5


class IntentClassifier:
    """Classify natural language questions into intent categories.

    Uses regex pattern matching to identify question intent, extract
    relevant entities, and determine confidence scores.

    Confidence Levels:
        - HIGH (>0.8): Strong signal, use specialized strategy
        - MEDIUM (0.5-0.8): Likely correct, use strategy with fallback
        - LOW (<0.5): Uncertain, use default SmartContextExtractor
    """

    # Pattern definitions: Intent -> [(regex_pattern, base_confidence), ...]
    # Patterns are tried in order; first match wins for each intent
    PATTERNS: dict[Intent, list[tuple[str, float]]] = {
        Intent.EXPLAIN: [
            (r"how does (.+) work", 0.9),
            (r"explain (.+)", 0.85),
            (r"walk me through (.+)", 0.9),
            (r"what does (.+) do", 0.8),
            (r"understand (.+)", 0.7),
            (r"describe (.+)", 0.75),
            (r"tell me about (.+)", 0.7),
            (r"how (.+) works", 0.85),
            (r"what is (.+)", 0.75),  # "what is UserService"
            (r"how is (.+)", 0.75),
            (r"what happens when (.+)", 0.8),
        ],
        Intent.IMPACT: [
            (r"what would break if .+(?:delete[ds]?|remov\w*) (.+)", 0.95),
            (r"impact of (?:changing|removing|deleting) (.+)", 0.9),
            (r"who uses (.+)", 0.8),
            (r"what depends on (.+)", 0.85),
            (r"if i (?:delete|remove|change) (.+)", 0.9),
            (r"what (?:calls|uses|imports) (.+)", 0.8),
            (r"dependents of (.+)", 0.85),
            (r"affected by (.+)", 0.8),
            (r"breaking change.* (.+)", 0.75),
        ],
        Intent.LOCATE: [
            (r"where is (.+)", 0.9),
            (r"find (.+)", 0.85),
            (r"show me (.+)", 0.8),
            (r"locate (.+)", 0.9),
            (r"which file (?:contains|has) (.+)", 0.9),
            (r"where (?:can i find|do i find) (.+)", 0.85),
            (r"path to (.+)", 0.85),
            (r"location of (.+)", 0.9),
        ],
        Intent.LIST: [
            (r"list all (.+)", 0.95),
            (r"show all (.+)", 0.9),
            (r"what are (?:all )?the (.+)", 0.85),
            (r"what are all (.+)", 0.9),
            (r"all (.+) that", 0.8),
            (r"how many (.+)", 0.75),
            (r"count (?:of )?(.+)", 0.8),
            (r"enumerate (.+)", 0.85),
            (r"every (.+)", 0.75),
            (r"list (.+)", 0.8),
            (r"what (.+) exist", 0.85),  # "what services exist"
            (r"give me (?:all )?(.+)", 0.8),  # "give me all functions"
        ],
        Intent.COMPARE: [
            (r"difference between (.+) and (.+)", 0.95),
            (r"what'?s the difference between (.+)", 0.9),  # "what's the difference between..."
            (r"compare (.+) (?:to|with|and|vs) (.+)", 0.95),
            (r"compare (?:these|the) (.+)", 0.85),  # "compare these implementations"
            (r"(.+) vs\.? (.+)", 0.9),
            (r"how does (.+) differ from (.+)", 0.9),
            (r"(.+) versus (.+)", 0.9),
            (r"contrast (.+)", 0.8),  # "contrast the implementations"
            (r"similarities between (.+) and (.+)", 0.85),
        ],
        Intent.TEMPORAL: [
            (r"(?:what )?changed (?:in|since) (.+)", 0.9),
            (r"what changed recently", 0.85),  # "what changed recently"
            (r"history of (.+)", 0.9),
            (r"who modified (.+)", 0.85),
            (r"when was (.+) (?:added|changed|modified|created)", 0.9),
            (r"blame for (.+)", 0.85),
            (r"recent changes(?: to (.+))?", 0.9),
            (r"evolution of (.+)", 0.8),
            (r"(?:git )?history for (.+)", 0.85),  # "git history for this module"
            (r"(?:git )?log for (.+)", 0.85),
            (r"commits? (?:to|for|affecting) (.+)", 0.85),
            (r"since (?:last week|yesterday|last month)", 0.8),
        ],
        Intent.DEBUG: [
            (r"why is (.+) (?:failing|broken|not working)", 0.95),
            (r"bug in (.+)", 0.9),
            (r"error (?:in|from|with) (.+)", 0.85),
            (r"(.+) (?:is )?failing", 0.8),
            (r"(.+) (?:is )?broken", 0.85),
            (r"debug (.+)", 0.85),
            (r"fix (.+)", 0.75),
            (r"issue with (.+)", 0.8),
            (r"problem (?:in|with) (.+)", 0.8),
            (r"(.+) throws? (?:an )?(?:error|exception)", 0.85),
            (r"troubleshoot (.+)", 0.9),  # "troubleshoot the error"
            (r"what'?s wrong with (.+)", 0.9),
        ],
        Intent.NAVIGATE: [
            (r"what calls (.+)", 0.9),
            (r"what (?:functions? )?call (?:this|it)", 0.85),  # "what functions call this"
            (r"what imports (.+)", 0.9),
            (r"what does (.+) import", 0.85),  # "what does AuthService import"
            (r"show (?:me )?(?:the )?imports", 0.8),  # "show imports"
            (r"show (?:me )?(?:the )?call graph", 0.9),  # "show me the call graph"
            (r"dependencies of (.+)", 0.9),
            (r"callers of (.+)", 0.9),
            (r"imports? (?:of|for|in) (.+)", 0.85),
            (r"call graph (?:of|for) (.+)", 0.9),
            (r"inheritance (?:tree|hierarchy) (?:of|for) (.+)", 0.85),
            (r"class hierarchy (?:of|for) (.+)", 0.85),
            (r"(.+) inherits from", 0.8),
            (r"children of (.+)", 0.85),
            (r"parent of (.+)", 0.85),
        ],
    }

    # Compiled patterns cache
    _compiled_patterns: dict[Intent, list[tuple[re.Pattern[str], float]]] | None = None

    # Modifier extraction patterns
    MODIFIER_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
        ("depth", "int", re.compile(r"(?:depth|levels?) (?:of )?(\d+)", re.IGNORECASE)),
        ("limit", "int", re.compile(r"(?:limit|top|first) (\d+)", re.IGNORECASE)),
        (
            "time_range",
            "str",
            re.compile(
                r"(?:since|in the last|past) ((?:last )?\w+(?:\s+\w+)?)",
                re.IGNORECASE,
            ),
        ),
        ("recursive", "bool", re.compile(r"\b(recursive(?:ly)?|transitive)\b", re.IGNORECASE)),
        ("include_tests", "bool", re.compile(r"\b(include tests?|with tests?)\b", re.IGNORECASE)),
        (
            "exclude_tests",
            "bool",
            re.compile(r"\b(exclude tests?|without tests?|no tests?)\b", re.IGNORECASE),
        ),
    ]

    def __init__(self) -> None:
        """Initialize the intent classifier."""
        self._ensure_compiled_patterns()

    @classmethod
    def _ensure_compiled_patterns(cls) -> None:
        """Compile regex patterns if not already compiled."""
        if cls._compiled_patterns is not None:
            return

        cls._compiled_patterns = {}
        for intent, patterns in cls.PATTERNS.items():
            cls._compiled_patterns[intent] = [
                (re.compile(pattern, re.IGNORECASE), confidence) for pattern, confidence in patterns
            ]

    def classify(self, question: str) -> ClassifiedIntent:
        """Classify a question into an intent category.

        Args:
            question: The natural language question to classify.

        Returns:
            ClassifiedIntent with intent type, confidence, entities, and modifiers.
        """
        self._ensure_compiled_patterns()

        best_intent = Intent.UNKNOWN
        best_confidence = 0.0
        best_entities: list[str] = []

        # Try all patterns and find the best match
        for intent, patterns in self._compiled_patterns.items():  # type: ignore[union-attr]
            for pattern, base_confidence in patterns:
                match = pattern.search(question)
                if match:
                    # Extract entities from capture groups
                    entities = [g for g in match.groups() if g is not None]

                    # Adjust confidence based on match quality
                    confidence = self._adjust_confidence(base_confidence, match, question)

                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_intent = intent
                        best_entities = entities

        # Extract modifiers
        modifiers = self._extract_modifiers(question)

        # Clean up extracted entities
        cleaned_entities = self._clean_entities(best_entities)

        return ClassifiedIntent(
            intent=best_intent,
            confidence=best_confidence,
            entities=cleaned_entities,
            modifiers=modifiers,
        )

    def _adjust_confidence(
        self,
        base_confidence: float,
        match: re.Match[str],
        question: str,
    ) -> float:
        """Adjust confidence based on match quality.

        Args:
            base_confidence: The base confidence from the pattern.
            match: The regex match object.
            question: The original question.

        Returns:
            Adjusted confidence score.
        """
        confidence = base_confidence

        # Boost if match is at the start of the question
        if match.start() < 5:
            confidence = min(1.0, confidence + 0.05)

        # Boost if question mark present (indicates clear question)
        if "?" in question:
            confidence = min(1.0, confidence + 0.02)

        # Slight penalty for very short questions (may be ambiguous)
        if len(question) < 20:
            confidence = max(0.0, confidence - 0.05)

        return confidence

    def _extract_modifiers(self, question: str) -> dict[str, Any]:
        """Extract modifiers from the question.

        Args:
            question: The question to analyze.

        Returns:
            Dictionary of extracted modifiers.
        """
        modifiers: dict[str, Any] = {}

        for name, type_hint, pattern in self.MODIFIER_PATTERNS:
            match = pattern.search(question)
            if match:
                value = match.group(1)
                if type_hint == "int":
                    try:
                        modifiers[name] = int(value)
                    except ValueError:
                        pass
                elif type_hint == "bool":
                    modifiers[name] = True
                else:
                    modifiers[name] = value.strip()

        return modifiers

    # Common noise words that should be stripped from entities
    _NOISE_WORDS = {
        # Articles and prepositions
        "the",
        "a",
        "an",
        "to",
        "from",
        "in",
        "on",
        "at",
        "by",
        "for",
        "of",
        "with",
        # Code-related noise words that often follow identifiers
        "method",
        "methods",
        "function",
        "functions",
        "class",
        "classes",
        "module",
        "modules",
        "file",
        "files",
        "defined",
        "definition",
        "implementation",
        "implements",
        "interface",
        "type",
        "types",
        "variable",
        "variables",
        "constant",
        "constants",
        "attribute",
        "attributes",
        "property",
        "properties",
        "field",
        "fields",
        "here",
        "there",
    }

    def _clean_entities(self, entities: list[str]) -> list[str]:
        """Clean extracted entity strings.

        Args:
            entities: Raw extracted entity strings.

        Returns:
            Cleaned entity list.
        """
        cleaned = []
        for entity in entities:
            # Strip whitespace and common noise words at boundaries
            entity = entity.strip()

            # Remove leading/trailing articles and prepositions
            entity = re.sub(r"^(?:the|a|an|to|from|in|on)\s+", "", entity, flags=re.IGNORECASE)
            entity = re.sub(r"\s+(?:the|a|an|to|from|in|on)$", "", entity, flags=re.IGNORECASE)

            # Remove trailing punctuation
            entity = entity.rstrip("?.!")

            # Split on whitespace and filter out noise words
            words = entity.split()
            if words:
                # Keep only the first word if it looks like an identifier
                # (CamelCase or snake_case), otherwise keep non-noise words
                first = words[0]
                if re.match(r"^[A-Z][a-z]+[A-Z]|^[a-z]+_[a-z]+", first) or len(words) == 1:
                    # First word is an identifier - use only it
                    entity = first
                else:
                    # Filter out noise words from all words
                    filtered = [w for w in words if w.lower() not in self._NOISE_WORDS]
                    entity = " ".join(filtered) if filtered else words[0]

            if entity and len(entity) >= 2:
                cleaned.append(entity)

        return cleaned


__all__ = [
    "ClassifiedIntent",
    "Intent",
    "IntentClassifier",
]
