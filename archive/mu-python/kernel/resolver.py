"""Node resolution and disambiguation for MU.

Provides centralized, intelligent node resolution with configurable strategies.
Solves the problem of multiple nodes matching a given reference (e.g., source
file vs test file with similar names).

Usage:
    resolver = NodeResolver(mubase, strategy=ResolutionStrategy.PREFER_SOURCE)
    result = resolver.resolve("PayoutService")

    if result.was_ambiguous:
        print(f"Resolved to {result.node.id} (from {len(result.alternatives)} matches)")
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from mu.kernel.models import Node

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class ResolutionStrategy(Enum):
    """Strategy for resolving ambiguous node references.

    INTERACTIVE: Prompt user to choose (requires callback)
    PREFER_SOURCE: Prefer non-test files over test files
    FIRST_MATCH: Return first match (legacy behavior)
    STRICT: Raise error on ambiguity
    """

    INTERACTIVE = "interactive"
    PREFER_SOURCE = "prefer_source"
    FIRST_MATCH = "first_match"
    STRICT = "strict"


class MatchType(Enum):
    """How a candidate matched the reference."""

    EXACT_ID = "exact_id"
    EXACT_NAME = "exact_name"
    SUFFIX_MATCH = "suffix_match"
    FUZZY_MATCH = "fuzzy_match"


@dataclass
class NodeCandidate:
    """A candidate node match with scoring metadata.

    Attributes:
        node: The matched Node object.
        score: Relevance score (higher is better). Scoring:
            - exact_id: 100
            - exact_name: 80
            - suffix_match: 60
            - fuzzy_match: 40
            Additional modifiers:
            - Non-test file: +10
            - Shorter path: +5 per segment difference from longest
        is_test: Whether this node is from a test file.
        is_exact_match: Whether this is an exact (non-fuzzy) match.
        match_type: How the node matched the reference.
    """

    node: Node
    score: int
    is_test: bool
    is_exact_match: bool
    match_type: MatchType

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "node_id": self.node.id,
            "node_name": self.node.name,
            "score": self.score,
            "is_test": self.is_test,
            "is_exact_match": self.is_exact_match,
            "match_type": self.match_type.value,
            "file_path": self.node.file_path,
            "line_start": self.node.line_start,
            "line_end": self.node.line_end,
        }


@dataclass
class ResolvedNode:
    """Result of node resolution.

    Attributes:
        node: The resolved Node object.
        alternatives: Other candidates that were considered.
        resolution_method: Which strategy was used for resolution.
        was_ambiguous: Whether multiple candidates existed.
    """

    node: Node
    alternatives: list[NodeCandidate] = field(default_factory=list)
    resolution_method: str = "exact"
    was_ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "node_id": self.node.id,
            "node_name": self.node.name,
            "resolution_method": self.resolution_method,
            "was_ambiguous": self.was_ambiguous,
            "alternative_count": len(self.alternatives),
            "alternatives": [alt.to_dict() for alt in self.alternatives],
        }


class NodeNotFoundError(Exception):
    """Raised when no node matches the reference."""

    def __init__(self, reference: str, message: str | None = None) -> None:
        self.reference = reference
        msg = message or f"Node not found: {reference}"
        super().__init__(msg)


class AmbiguousNodeError(Exception):
    """Raised when multiple nodes match and STRICT strategy is used."""

    def __init__(self, reference: str, candidates: list[NodeCandidate]) -> None:
        self.reference = reference
        self.candidates = candidates
        candidate_ids = [c.node.id for c in candidates[:5]]
        if len(candidates) > 5:
            candidate_ids.append(f"... and {len(candidates) - 5} more")
        super().__init__(
            f"Ambiguous node reference '{reference}'. Matches: {', '.join(candidate_ids)}"
        )


# Language-agnostic test file detection patterns
# Path patterns that indicate test files across languages
TEST_PATH_PATTERNS = (
    # Directory patterns (case-insensitive check done separately)
    "/test/",
    "/tests/",
    "/spec/",
    "/specs/",
    "/__tests__/",
    "/__test__/",
    "/__mocks__/",
    # .NET patterns
    ".tests/",
    ".test/",
    "/unittests/",
    "/integrationtests/",
    "/functionaltests/",
)

# File name patterns (applied to basename)
TEST_FILE_PATTERNS = (
    # Python
    "test_",
    "_test.py",
    "_tests.py",
    "conftest.py",
    # TypeScript/JavaScript
    ".test.",
    ".spec.",
    ".tests.",
    ".specs.",
    "_test.",
    "_spec.",
    # Go
    "_test.go",
    # Java
    "test",  # Prefix check with capitalization handling
    "tests",
    # Rust
    "_test.rs",
    # C#
    "tests.cs",
    "test.cs",
)

# File suffixes for test files
TEST_SUFFIXES = (
    "_test.py",
    "_tests.py",
    "_test.ts",
    "_test.tsx",
    "_test.js",
    "_test.jsx",
    "_test.go",
    "_test.rs",
    "test.cs",
    "tests.cs",
    ".test.ts",
    ".test.tsx",
    ".test.js",
    ".test.jsx",
    ".spec.ts",
    ".spec.tsx",
    ".spec.js",
    ".spec.jsx",
)

# Node name patterns indicating test entities
TEST_NAME_PATTERNS = (
    "test",
    "tests",
    "mock",
    "mocks",
    "fake",
    "fakes",
    "stub",
    "stubs",
    "fixture",
    "fixtures",
)


def _is_test_node(node: Node) -> bool:
    """Detect if a node is from a test file.

    Uses language-agnostic heuristics that work across:
    - Python: test_*, *_test.py, tests/ directory
    - TypeScript/JavaScript: *.test.ts, *.spec.ts, __tests__/
    - Go: *_test.go
    - Java: *Test.java, src/test/
    - C#: *Tests.cs, *.Tests/ project
    - Rust: *_test.rs, tests/ directory

    Args:
        node: The node to check.

    Returns:
        True if the node appears to be a test file, False otherwise.
    """
    file_path = node.file_path or ""
    file_path_lower = file_path.lower()
    name_lower = node.name.lower()

    # Check path patterns (case-insensitive)
    for pattern in TEST_PATH_PATTERNS:
        if pattern.lower() in file_path_lower:
            return True

    # Check file name patterns
    basename = file_path.split("/")[-1].lower() if "/" in file_path else file_path_lower

    # Prefix check
    if basename.startswith("test_") or basename.startswith("tests_"):
        return True

    # Suffix checks
    for suffix in TEST_SUFFIXES:
        if basename.endswith(suffix):
            return True

    # Java-style: Check if class name ends with Test or Tests
    # But avoid false positives like "Contest", "Attestation"
    if name_lower.endswith("test") or name_lower.endswith("tests"):
        # Make sure it's actually a test class (capital T)
        if node.name.endswith("Test") or node.name.endswith("Tests"):
            return True

    # Check if name starts with test patterns (but not substring matches)
    for pattern in TEST_NAME_PATTERNS:
        if name_lower == pattern:
            return True
        # Check if name starts with pattern followed by non-letter
        # e.g., "TestUser" but not "Testimony"
        if name_lower.startswith(pattern) and len(node.name) > len(pattern):
            next_char = node.name[len(pattern)]
            if not next_char.islower():
                return True

    return False


class NodeResolver:
    """Centralized node resolution with smart disambiguation.

    Resolves node references (names, IDs, file paths) to actual Node objects
    with configurable strategies for handling ambiguous matches.

    Example:
        >>> resolver = NodeResolver(mubase)
        >>> result = resolver.resolve("UserService")
        >>> print(result.node.id)
        'cls:src/services/user.py:UserService'

        >>> # With strict mode
        >>> resolver = NodeResolver(mubase, strategy=ResolutionStrategy.STRICT)
        >>> resolver.resolve("Service")  # Raises AmbiguousNodeError

        >>> # With interactive mode (requires callback)
        >>> def choose(candidates):
        ...     return candidates[0]  # Always choose first
        >>> resolver = NodeResolver(
        ...     mubase,
        ...     strategy=ResolutionStrategy.INTERACTIVE,
        ...     interactive_callback=choose
        ... )
    """

    def __init__(
        self,
        mubase: MUbase,
        strategy: ResolutionStrategy = ResolutionStrategy.PREFER_SOURCE,
        interactive_callback: Callable[[list[NodeCandidate]], NodeCandidate] | None = None,
    ) -> None:
        """Initialize the NodeResolver.

        Args:
            mubase: The MUbase database to resolve nodes from.
            strategy: Resolution strategy to use for ambiguous matches.
            interactive_callback: Callback for INTERACTIVE strategy. Must return
                one of the provided candidates.
        """
        self.mubase = mubase
        self.strategy = strategy
        self.interactive_callback = interactive_callback

    def resolve(self, reference: str) -> ResolvedNode:
        """Resolve a node reference to a Node.

        Tries resolution in order:
        1. Exact ID match (mod:, cls:, fn: prefix)
        2. Exact name match
        3. Suffix match
        4. Fuzzy match

        Args:
            reference: Node reference - can be:
                - Full node ID: "mod:src/auth.py", "cls:src/auth.py:AuthService"
                - Simple name: "AuthService", "login"
                - File path: "src/auth.py"
                - Partial match: "Service", "auth"

        Returns:
            ResolvedNode with the matched node and resolution metadata.

        Raises:
            NodeNotFoundError: If no node matches the reference.
            AmbiguousNodeError: If STRICT strategy and multiple matches.
        """
        # Strip whitespace
        reference = reference.strip()

        if not reference:
            raise NodeNotFoundError(reference, "Empty node reference")

        # Find all candidates
        candidates = self._find_candidates(reference)

        if not candidates:
            raise NodeNotFoundError(reference)

        # Single match - no disambiguation needed
        if len(candidates) == 1:
            return ResolvedNode(
                node=candidates[0].node,
                alternatives=[],
                resolution_method=candidates[0].match_type.value,
                was_ambiguous=False,
            )

        # Multiple matches - apply disambiguation strategy
        return self._disambiguate(reference, candidates)

    def _find_candidates(self, reference: str) -> list[NodeCandidate]:
        """Find all candidate nodes matching the reference.

        Tries in order: exact ID -> file path -> exact name -> suffix -> fuzzy.
        Returns all matches with scores.

        Args:
            reference: The node reference to search for.

        Returns:
            List of NodeCandidate objects, sorted by score descending.
        """
        candidates: list[NodeCandidate] = []

        # 1. Try exact ID match (highest priority)
        if reference.startswith(("mod:", "cls:", "fn:")):
            node = self.mubase.get_node(reference)
            if node:
                candidates.append(
                    NodeCandidate(
                        node=node,
                        score=100,
                        is_test=_is_test_node(node),
                        is_exact_match=True,
                        match_type=MatchType.EXACT_ID,
                    )
                )
                return candidates  # Exact ID is definitive

        # 2. Check if it looks like a file path
        looks_like_path = (
            "/" in reference
            or "\\" in reference
            or reference.endswith(
                (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs")
            )
        )

        if looks_like_path:
            # Normalize path separators
            normalized_path = reference.replace("\\", "/")

            # Try exact file_path match
            try:
                result = self.mubase.execute(
                    "SELECT id FROM nodes WHERE file_path = ? AND type = 'module' LIMIT 1",
                    [normalized_path],
                )
                if result:
                    node = self.mubase.get_node(str(result[0][0]))
                    if node:
                        is_test = _is_test_node(node)
                        candidates.append(
                            NodeCandidate(
                                node=node,
                                score=95,  # High score but below exact ID
                                is_test=is_test,
                                is_exact_match=True,
                                match_type=MatchType.EXACT_ID,
                            )
                        )
                        return candidates  # Exact file path is definitive
            except Exception:
                pass

            # Try matching with path suffix (handles relative vs absolute paths)
            try:
                result = self.mubase.execute(
                    "SELECT id FROM nodes WHERE file_path LIKE ? AND type = 'module' LIMIT 5",
                    [f"%{normalized_path}"],
                )
                for row in result:
                    node = self.mubase.get_node(str(row[0]))
                    if node:
                        is_test = _is_test_node(node)
                        score = 85 if not is_test else 75
                        candidates.append(
                            NodeCandidate(
                                node=node,
                                score=score,
                                is_test=is_test,
                                is_exact_match=True,
                                match_type=MatchType.SUFFIX_MATCH,
                            )
                        )
            except Exception:
                pass

            if candidates:
                return self._apply_path_scoring(candidates)

        # 3. Try exact name match
        # Use parameterized query - name is escaped by DuckDB
        exact_nodes = self.mubase.find_by_name(reference)
        for node in exact_nodes:
            is_test = _is_test_node(node)
            score = 80
            if not is_test:
                score += 10
            candidates.append(
                NodeCandidate(
                    node=node,
                    score=score,
                    is_test=is_test,
                    is_exact_match=True,
                    match_type=MatchType.EXACT_NAME,
                )
            )

        if candidates:
            # Have exact matches, apply path-length scoring and return
            return self._apply_path_scoring(candidates)

        # 4. Try suffix match (name ends with reference)
        suffix_nodes = self.mubase.find_nodes_by_suffix(reference)
        for node in suffix_nodes:
            is_test = _is_test_node(node)
            score = 60
            if not is_test:
                score += 10
            candidates.append(
                NodeCandidate(
                    node=node,
                    score=score,
                    is_test=is_test,
                    is_exact_match=False,
                    match_type=MatchType.SUFFIX_MATCH,
                )
            )

        if candidates:
            return self._apply_path_scoring(candidates)

        # 5. Try fuzzy match (contains reference)
        # Use LIKE with wildcards - DuckDB handles escaping
        fuzzy_pattern = f"%{reference}%"
        fuzzy_nodes = self.mubase.find_by_name(fuzzy_pattern)
        for node in fuzzy_nodes:
            is_test = _is_test_node(node)
            score = 40
            if not is_test:
                score += 10
            candidates.append(
                NodeCandidate(
                    node=node,
                    score=score,
                    is_test=is_test,
                    is_exact_match=False,
                    match_type=MatchType.FUZZY_MATCH,
                )
            )

        return self._apply_path_scoring(candidates)

    def _apply_path_scoring(self, candidates: list[NodeCandidate]) -> list[NodeCandidate]:
        """Apply path-length bonus to candidates.

        Shorter paths get higher scores (prefer src/auth.py over
        src/modules/legacy/auth.py).

        Args:
            candidates: List of candidates to score.

        Returns:
            Same list, sorted by score descending.
        """
        if not candidates:
            return candidates

        # Find longest path (segment count)
        max_segments = 0
        for c in candidates:
            if c.node.file_path:
                segments = c.node.file_path.count("/")
                max_segments = max(max_segments, segments)

        # Apply bonus for shorter paths
        for c in candidates:
            if c.node.file_path:
                segments = c.node.file_path.count("/")
                path_bonus = (max_segments - segments) * 2
                c.score += min(path_bonus, 10)  # Cap at +10

        # Sort by score descending
        candidates.sort(key=lambda c: (-c.score, c.node.id))
        return candidates

    def _disambiguate(
        self,
        reference: str,
        candidates: list[NodeCandidate],
    ) -> ResolvedNode:
        """Apply disambiguation strategy to multiple candidates.

        Args:
            reference: Original reference (for error messages).
            candidates: List of candidates (already sorted by score).

        Returns:
            ResolvedNode with chosen node.

        Raises:
            AmbiguousNodeError: If STRICT strategy.
        """
        if self.strategy == ResolutionStrategy.STRICT:
            raise AmbiguousNodeError(reference, candidates)

        if self.strategy == ResolutionStrategy.FIRST_MATCH:
            # Legacy behavior: just take first match (already sorted)
            return ResolvedNode(
                node=candidates[0].node,
                alternatives=candidates[1:],
                resolution_method="first_match",
                was_ambiguous=True,
            )

        if self.strategy == ResolutionStrategy.INTERACTIVE:
            if not self.interactive_callback:
                # Fall back to prefer_source if no callback
                return self._prefer_source_disambiguation(candidates)

            chosen = self.interactive_callback(candidates)
            # Find index of chosen candidate
            remaining = [c for c in candidates if c.node.id != chosen.node.id]

            return ResolvedNode(
                node=chosen.node,
                alternatives=remaining,
                resolution_method="interactive",
                was_ambiguous=True,
            )

        # Default: PREFER_SOURCE
        return self._prefer_source_disambiguation(candidates)

    def _prefer_source_disambiguation(
        self,
        candidates: list[NodeCandidate],
    ) -> ResolvedNode:
        """Disambiguate by preferring source files over test files.

        Args:
            candidates: List of candidates (already scored).

        Returns:
            ResolvedNode with best non-test candidate (or first if all are tests).
        """
        # Candidates are already sorted by score (which includes is_test bonus)
        # But let's be explicit: prefer non-test, then highest score
        non_test = [c for c in candidates if not c.is_test]

        if non_test:
            best = non_test[0]
            alternatives = [c for c in candidates if c.node.id != best.node.id]
        else:
            # All candidates are test files - just use highest scored
            best = candidates[0]
            alternatives = candidates[1:]

        return ResolvedNode(
            node=best.node,
            alternatives=alternatives,
            resolution_method="prefer_source",
            was_ambiguous=True,
        )


__all__ = [
    "NodeResolver",
    "ResolutionStrategy",
    "MatchType",
    "NodeCandidate",
    "ResolvedNode",
    "NodeNotFoundError",
    "AmbiguousNodeError",
]
