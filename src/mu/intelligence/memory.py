"""Cross-session memory management for AI assistants.

Provides persistent storage of learnings, decisions, preferences, and context
that should persist across agent sessions. This enables agents to:

- Remember user preferences (coding style, tool choices)
- Store architectural decisions and their rationale
- Track pitfalls and gotchas discovered during development
- Maintain project context across sessions
- Build up knowledge about the codebase over time

Usage:
    from mu.intelligence.memory import MemoryManager, MemoryCategory
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    manager = MemoryManager(db)

    # Store a memory
    memory_id = manager.remember(
        "Always use snake_case for function names in this project",
        category=MemoryCategory.CONVENTION,
        importance=3,
        tags=["naming", "python"],
    )

    # Recall memories
    result = manager.recall(query="naming conventions")
    for memory in result.memories:
        print(f"[{memory.category.value}] {memory.content}")

    # Recall by category
    result = manager.recall(category=MemoryCategory.PITFALL)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from mu.intelligence.models import Memory, MemoryCategory, RecallResult

if TYPE_CHECKING:
    from mu.kernel import MUbase


class MemoryManager:
    """Manager for cross-session memory operations.

    Provides a high-level interface for storing and retrieving memories
    that persist across agent sessions.
    """

    # Default importance levels
    IMPORTANCE_LOW = 1
    IMPORTANCE_NORMAL = 2
    IMPORTANCE_HIGH = 3
    IMPORTANCE_CRITICAL = 4
    IMPORTANCE_ESSENTIAL = 5

    def __init__(self, mubase: MUbase) -> None:
        """Initialize the memory manager.

        Args:
            mubase: The MUbase database for storage.
        """
        self.db = mubase

    def remember(
        self,
        content: str,
        category: MemoryCategory | str = MemoryCategory.LEARNING,
        context: str = "",
        source: str = "",
        importance: int = 2,
        tags: list[str] | None = None,
        confidence: float = 1.0,
    ) -> str:
        """Store a memory for future recall.

        Args:
            content: The memory content to store.
            category: Category of the memory.
            context: Optional context about when/why this was learned.
            source: Optional source (file path, conversation, etc.).
            importance: Importance level (1-5, default 2).
            tags: Optional tags for categorization.
            confidence: Confidence level (0.0-1.0, default 1.0).

        Returns:
            The memory ID.

        Examples:
            # Store a preference
            manager.remember(
                "User prefers TypeScript over JavaScript",
                category=MemoryCategory.PREFERENCE,
                importance=3,
            )

            # Store a decision with context
            manager.remember(
                "Using PostgreSQL for the database",
                category=MemoryCategory.DECISION,
                context="Chosen over MySQL for better JSON support",
                source="architecture-discussion-2024-01",
                importance=4,
            )

            # Store a pitfall
            manager.remember(
                "Don't use datetime.now() in tests - use freezegun",
                category=MemoryCategory.PITFALL,
                tags=["testing", "datetime"],
                importance=3,
            )
        """
        # Normalize category to string
        category_str = category.value if isinstance(category, MemoryCategory) else category

        # Validate importance
        importance = max(1, min(5, importance))

        # Validate confidence
        confidence = max(0.0, min(1.0, confidence))

        return self.db.save_memory(
            content=content,
            category=category_str,
            context=context,
            source=source,
            confidence=confidence,
            importance=importance,
            tags=tags,
        )

    def recall(
        self,
        query: str | None = None,
        category: MemoryCategory | str | None = None,
        tags: list[str] | None = None,
        min_importance: int = 0,
        limit: int = 10,
    ) -> RecallResult:
        """Recall memories based on search criteria.

        Args:
            query: Optional text search in content/context.
            category: Optional category filter.
            tags: Optional tags filter (matches any).
            min_importance: Minimum importance level (0 = all).
            limit: Maximum number of results.

        Returns:
            RecallResult with matching memories.

        Examples:
            # Recall all high-importance memories
            result = manager.recall(min_importance=4)

            # Search for specific content
            result = manager.recall(query="database")

            # Get all decisions
            result = manager.recall(category=MemoryCategory.DECISION)

            # Search by tags
            result = manager.recall(tags=["testing", "pytest"])
        """
        start_time = time.time()

        # Normalize category to string
        category_str = None
        if category:
            category_str = category.value if isinstance(category, MemoryCategory) else category

        memories = self.db.recall_memories(
            query=query,
            category=category_str,
            tags=tags,
            min_importance=min_importance,
            limit=limit,
        )

        elapsed_ms = (time.time() - start_time) * 1000

        return RecallResult(
            memories=memories,
            query=query or "",
            total_matches=len(memories),
            recall_time_ms=elapsed_ms,
        )

    def get(self, memory_id: str) -> Memory | None:
        """Get a specific memory by ID.

        Args:
            memory_id: The memory ID.

        Returns:
            Memory object if found, None otherwise.
        """
        return self.db.get_memory(memory_id)

    def forget(self, memory_id: str) -> bool:
        """Delete a memory.

        Args:
            memory_id: The memory ID to delete.

        Returns:
            True if deleted.
        """
        return self.db.delete_memory(memory_id)

    def stats(self) -> dict[str, Any]:
        """Get memory statistics.

        Returns:
            Dictionary with memory counts by category.
        """
        return self.db.memory_stats()

    def has_memories(self) -> bool:
        """Check if any memories exist.

        Returns:
            True if memories exist.
        """
        return self.db.has_memories()

    def recall_context(self, task_description: str, limit: int = 5) -> list[Memory]:
        """Recall memories relevant to a task.

        Convenience method that searches across all categories
        for memories relevant to a given task description.

        Args:
            task_description: Description of the task.
            limit: Maximum memories to return.

        Returns:
            List of relevant memories.
        """
        # Extract keywords from task description
        keywords = _extract_keywords(task_description)

        all_memories: list[Memory] = []

        # Search by keywords
        for keyword in keywords[:3]:  # Limit to top 3 keywords
            result = self.recall(query=keyword, limit=limit)
            all_memories.extend(result.memories)

        # Deduplicate by ID
        seen_ids: set[str] = set()
        unique_memories: list[Memory] = []
        for mem in all_memories:
            if mem.id not in seen_ids:
                seen_ids.add(mem.id)
                unique_memories.append(mem)

        # Sort by importance and return top N
        unique_memories.sort(key=lambda m: (m.importance, m.access_count), reverse=True)
        return unique_memories[:limit]


def _extract_keywords(text: str) -> list[str]:
    """Extract keywords from text for memory search.

    Simple keyword extraction - removes common words and
    returns significant terms.
    """
    # Common words to filter out
    stop_words = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "and",
        "but",
        "if",
        "or",
        "because",
        "until",
        "while",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "it",
        "its",
        "they",
        "them",
    }

    # Tokenize and filter
    words = text.lower().split()
    keywords = [w.strip(".,!?;:\"'()[]{}") for w in words]
    keywords = [w for w in keywords if len(w) > 2 and w not in stop_words]

    # Return unique keywords preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    return unique


__all__ = [
    "MemoryManager",
]
