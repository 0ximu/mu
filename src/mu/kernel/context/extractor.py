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
    - Domain term mapping (e.g., "services" -> *Service classes)
    """

    # Domain terms that map to code naming patterns
    # Maps common domain words to (suffix_pattern, type_hint)
    DOMAIN_TERM_PATTERNS: dict[str, tuple[str, str]] = {
        # Plural domain terms -> class suffix patterns
        "services": ("Service", "class"),
        "service": ("Service", "class"),
        "controllers": ("Controller", "class"),
        "controller": ("Controller", "class"),
        "handlers": ("Handler", "class"),
        "handler": ("Handler", "class"),
        "managers": ("Manager", "class"),
        "manager": ("Manager", "class"),
        "repositories": ("Repository", "class"),
        "repository": ("Repository", "class"),
        "factories": ("Factory", "class"),
        "factory": ("Factory", "class"),
        "providers": ("Provider", "class"),
        "provider": ("Provider", "class"),
        "adapters": ("Adapter", "class"),
        "adapter": ("Adapter", "class"),
        "validators": ("Validator", "class"),
        "validator": ("Validator", "class"),
        "models": ("Model", "class"),
        "model": ("Model", "class"),
        "entities": ("Entity", "class"),
        "entity": ("Entity", "class"),
        "components": ("Component", "class"),
        "component": ("Component", "class"),
        "middleware": ("Middleware", "class"),
        "middlewares": ("Middleware", "class"),
        "helpers": ("Helper", "class"),
        "helper": ("Helper", "class"),
        "utils": ("Utils", "class"),
        "utilities": ("Utility", "class"),
        "tests": ("Test", "class"),
        "test": ("Test", "class"),
        # Domain concepts -> function patterns
        "authentication": ("auth", "function"),
        "authorization": ("auth", "function"),
        "auth": ("auth", "function"),
        "login": ("login", "function"),
        "logout": ("logout", "function"),
        "validation": ("validate", "function"),
        "parsing": ("parse", "function"),
        "parser": ("Parser", "class"),
        "parsers": ("Parser", "class"),
    }

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

        # Extract domain terms and map to code patterns
        domain_entities = self._extract_domain_terms(text)
        for entity in domain_entities:
            # Only add if not already found with higher confidence
            if entity.name not in entities or entities[entity.name].confidence < entity.confidence:
                entities[entity.name] = entity

        # Sort by confidence descending
        result = sorted(entities.values(), key=lambda e: -e.confidence)

        return result

    def _extract_domain_terms(self, text: str) -> list[ExtractedEntity]:
        """Extract domain terms and map them to code naming patterns.

        For example, "services" maps to entities with "Service" suffix.

        Args:
            text: The question or text to analyze.

        Returns:
            List of extracted entities from domain term mapping.
        """
        entities = []
        text_lower = text.lower()
        words = set(re.findall(r"\b(\w+)\b", text_lower))

        for term, (suffix_pattern, _type_hint) in self.DOMAIN_TERM_PATTERNS.items():
            if term in words:
                # Find known names that match this domain pattern
                matching_names = self._find_names_by_suffix(suffix_pattern)
                for name in matching_names:
                    entities.append(
                        ExtractedEntity(
                            name=name,
                            confidence=0.75,  # Moderate confidence for domain mapping
                            extraction_method="domain_term",
                            is_known=True,
                        )
                    )

                # If no known names match, create a pattern-based entity
                # that can be used for suffix search
                if not matching_names:
                    entities.append(
                        ExtractedEntity(
                            name=f"*{suffix_pattern}",  # Wildcard pattern
                            confidence=0.6,
                            extraction_method="domain_pattern",
                            is_known=False,
                        )
                    )

        return entities

    def _find_names_by_suffix(self, suffix: str) -> list[str]:
        """Find known names that end with the given suffix.

        Args:
            suffix: The suffix to search for (e.g., "Service").

        Returns:
            List of matching known names.
        """
        matches = []
        for name in self.known_names:
            # Get the simple name (last part after . or :)
            simple_name = name.split(".")[-1].split(":")[-1]
            if simple_name.endswith(suffix):
                matches.append(name)
        return matches

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
