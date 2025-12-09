"""Entity extraction from natural language questions.

Identifies code entity names (functions, classes, files) from user questions
using pattern matching and known name lookup.
"""

from __future__ import annotations

import re
from re import Pattern

from mu.kernel.context.models import ExtractedEntity


class EntityExtractor:
    """Extract code entity names from natural language questions.

    Uses multiple strategies to identify potential code identifiers:
    - CamelCase patterns (e.g., AuthService, UserModel)
    - snake_case patterns (e.g., get_user, validate_input)
    - CONSTANT patterns (e.g., MAX_RETRIES, DEFAULT_TIMEOUT)
    - Qualified names (e.g., auth.service.login, mu.parser.models)
    - Quoted strings (e.g., 'config.py', "UserService")
    - Known name matching (exact and suffix match)
    """

    # Pattern definitions with confidence scores
    PATTERNS: list[tuple[str, Pattern[str], float]] = [
        # Quoted strings - highest confidence as explicitly mentioned
        ("quoted", re.compile(r'["\']([^"\']+)["\']'), 1.0),
        # CamelCase - class names, service names
        ("camel_case", re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b"), 0.9),
        # Acronym + CamelCase (e.g., MUbase, HTTPClient, XMLParser, IOError)
        ("acronym_camel", re.compile(r"\b([A-Z]{2,}[a-z][a-z0-9]*(?:[A-Z][a-z0-9]+)*)\b"), 0.85),
        # PascalCase single word (e.g., User, Auth) - only if 4+ chars
        ("pascal_single", re.compile(r"\b([A-Z][a-z]{3,})\b"), 0.7),
        # CONSTANTS - configuration values
        ("constant", re.compile(r"\b([A-Z][A-Z_]{2,}[A-Z])\b"), 0.8),
        # snake_case - function names, variables
        ("snake_case", re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b"), 0.8),
        # Qualified names - module paths
        ("qualified", re.compile(r"\b(\w+(?:\.\w+)+)\b"), 0.85),
        # File paths with extensions
        ("file_path", re.compile(r"\b([\w/]+\.(?:py|ts|js|go|java|rs|cs))\b"), 0.95),
        # Lowercase words (3+ chars) - low confidence fallback for library names like "zustand"
        ("lowercase_word", re.compile(r"\b([a-z]{3,})\b"), 0.4),
    ]

    # Common words to exclude from entity extraction
    STOP_WORDS = frozenset(
        {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "what",
            "how",
            "does",
            "work",
            "about",
            "where",
            "which",
            "when",
            "why",
            "can",
            "could",
            "would",
            "should",
            "have",
            "has",
            "been",
            "being",
            "was",
            "were",
            "are",
            "will",
            "not",
            "all",
            "any",
            "some",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "other",
            "such",
            "only",
            "own",
            "same",
            "than",
            "too",
            "very",
            "just",
            "also",
            "well",
            "back",
            "after",
            "before",
            "between",
            "under",
            "over",
            "through",
            "into",
            "then",
            "here",
            "there",
            "still",
            "however",
            # Additional common words
            "file",
            "files",
            "code",
            "function",
            "class",
            "method",
            "module",
            "like",
            "use",
            "used",
            "using",
            "make",
            "made",
            "get",
            "set",
            "call",
            "called",
        }
    )

    def __init__(self, known_names: set[str] | None = None) -> None:
        """Initialize the entity extractor.

        Args:
            known_names: Set of known entity names from the codebase.
                         If provided, enables higher-confidence matching.
        """
        self.known_names = known_names or set()
        self._name_to_lower: dict[str, str] = {name.lower(): name for name in self.known_names}

    def extract(self, text: str) -> list[ExtractedEntity]:
        """Extract code entities from natural language text.

        Args:
            text: The question or text to analyze.

        Returns:
            List of extracted entities, sorted by confidence.
        """
        entities: dict[str, ExtractedEntity] = {}

        # Apply pattern-based extraction
        for method, pattern, base_confidence in self.PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1)

                # Skip stop words and very short names
                if name.lower() in self.STOP_WORDS or len(name) < 2:
                    continue

                # Check if this is a known name
                is_known = self._is_known_name(name)
                confidence = base_confidence

                # Boost confidence for known names
                if is_known:
                    confidence = min(1.0, confidence + 0.2)

                # Only add if higher confidence than existing
                if name not in entities or entities[name].confidence < confidence:
                    entities[name] = ExtractedEntity(
                        name=name,
                        confidence=confidence,
                        extraction_method=method,
                        is_known=is_known,
                    )

        # Also check for known names that might not match patterns
        for known_name in self._find_known_names_in_text(text):
            if known_name not in entities:
                entities[known_name] = ExtractedEntity(
                    name=known_name,
                    confidence=0.95,
                    extraction_method="known_match",
                    is_known=True,
                )

        # Sort by confidence descending
        result = sorted(entities.values(), key=lambda e: -e.confidence)

        return result

    def _is_known_name(self, name: str) -> bool:
        """Check if a name matches a known entity.

        Checks for exact match and suffix match.
        """
        # Exact match
        if name in self.known_names:
            return True

        # Case-insensitive match
        if name.lower() in self._name_to_lower:
            return True

        # Suffix match (e.g., "UserService" matches "auth.UserService")
        for known in self.known_names:
            if known.endswith("." + name) or known.endswith(":" + name):
                return True

        return False

    def _find_known_names_in_text(self, text: str) -> list[str]:
        """Find known names mentioned in the text.

        Uses case-insensitive substring matching for known names.
        """
        text_lower = text.lower()
        found = []

        for name in self.known_names:
            # Get the simple name (last part after . or :)
            simple_name = name.split(".")[-1].split(":")[-1]
            if len(simple_name) >= 3 and simple_name.lower() in text_lower:
                # Verify it's a word boundary match
                pattern = re.compile(r"\b" + re.escape(simple_name) + r"\b", re.IGNORECASE)
                if pattern.search(text):
                    found.append(name)

        return found


__all__ = ["EntityExtractor"]
