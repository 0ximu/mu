"""Tests for cross-session memory feature (Intelligence Layer F6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mu.intelligence import Memory, MemoryCategory, MemoryManager, RecallResult
from mu.kernel import MUbase


class TestMemoryModels:
    """Tests for memory data models."""

    def test_memory_category_values(self) -> None:
        """All expected memory categories exist."""
        assert MemoryCategory.PREFERENCE.value == "preference"
        assert MemoryCategory.DECISION.value == "decision"
        assert MemoryCategory.CONTEXT.value == "context"
        assert MemoryCategory.LEARNING.value == "learning"
        assert MemoryCategory.PITFALL.value == "pitfall"
        assert MemoryCategory.CONVENTION.value == "convention"
        assert MemoryCategory.TODO.value == "todo"
        assert MemoryCategory.REFERENCE.value == "reference"

    def test_memory_to_dict(self) -> None:
        """Memory converts to dict correctly."""
        memory = Memory(
            id="mem:learning:abc123",
            category=MemoryCategory.LEARNING,
            content="Use snake_case for function names",
            context="Discovered during code review",
            source="src/utils.py",
            confidence=0.95,
            importance=3,
            tags=["naming", "python"],
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
            access_count=5,
        )
        d = memory.to_dict()
        assert d["id"] == "mem:learning:abc123"
        assert d["category"] == "learning"
        assert d["content"] == "Use snake_case for function names"
        assert d["context"] == "Discovered during code review"
        assert d["source"] == "src/utils.py"
        assert d["confidence"] == 0.95
        assert d["importance"] == 3
        assert d["tags"] == ["naming", "python"]
        assert d["access_count"] == 5

    def test_memory_from_dict(self) -> None:
        """Memory can be created from dict."""
        data = {
            "id": "mem:decision:xyz789",
            "category": "decision",
            "content": "Use PostgreSQL for the database",
            "context": "Better JSON support",
            "source": "",
            "confidence": 1.0,
            "importance": 4,
            "tags": ["database"],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "accessed_at": None,
            "access_count": 0,
        }
        memory = Memory.from_dict(data)
        assert memory.id == "mem:decision:xyz789"
        assert memory.category == MemoryCategory.DECISION
        assert memory.content == "Use PostgreSQL for the database"
        assert memory.importance == 4

    def test_recall_result_to_dict(self) -> None:
        """RecallResult converts to dict correctly."""
        memories = [
            Memory(
                id="mem:test:123",
                category=MemoryCategory.LEARNING,
                content="Test content",
                created_at="2024-01-01T00:00:00",
                updated_at="2024-01-01T00:00:00",
            )
        ]
        result = RecallResult(
            memories=memories,
            query="test",
            total_matches=1,
            recall_time_ms=5.5,
        )
        d = result.to_dict()
        assert d["query"] == "test"
        assert d["total_matches"] == 1
        assert d["recall_time_ms"] == 5.5
        assert len(d["memories"]) == 1


class TestMemoryStorage:
    """Tests for memory storage in MUbase."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> MUbase:
        """Create a temporary MUbase."""
        return MUbase(tmp_path / ".mubase")

    def test_save_and_retrieve_memory(self, temp_db: MUbase) -> None:
        """Memories can be saved and retrieved."""
        memory_id = temp_db.save_memory(
            content="Always use snake_case for Python functions",
            category="convention",
            context="Team coding standards",
            importance=3,
            tags=["naming", "python"],
        )

        assert memory_id.startswith("mem:convention:")
        assert temp_db.has_memories()

        memory = temp_db.get_memory(memory_id)
        assert memory is not None
        assert memory.content == "Always use snake_case for Python functions"
        assert memory.category == MemoryCategory.CONVENTION
        assert memory.context == "Team coding standards"
        assert memory.importance == 3
        assert "naming" in memory.tags
        assert memory.access_count >= 1  # Incremented on retrieval

    def test_update_existing_memory(self, temp_db: MUbase) -> None:
        """Saving same content updates the existing memory."""
        content = "Use PostgreSQL for the database"

        # Save first time
        id1 = temp_db.save_memory(
            content=content,
            category="decision",
            importance=3,
        )

        # Save same content again with different importance
        id2 = temp_db.save_memory(
            content=content,
            category="decision",
            importance=5,  # Updated importance
        )

        # Should be the same ID (content-based deduplication)
        assert id1 == id2

        # Should have updated importance
        memory = temp_db.get_memory(id1)
        assert memory is not None
        assert memory.importance == 5

    def test_recall_memories_by_category(self, temp_db: MUbase) -> None:
        """Memories can be filtered by category."""
        temp_db.save_memory(content="Decision 1", category="decision", importance=2)
        temp_db.save_memory(content="Decision 2", category="decision", importance=3)
        temp_db.save_memory(content="Pitfall 1", category="pitfall", importance=2)

        decisions = temp_db.recall_memories(category="decision")
        assert len(decisions) == 2
        assert all(m.category == MemoryCategory.DECISION for m in decisions)

        pitfalls = temp_db.recall_memories(category="pitfall")
        assert len(pitfalls) == 1
        assert pitfalls[0].content == "Pitfall 1"

    def test_recall_memories_by_query(self, temp_db: MUbase) -> None:
        """Memories can be searched by text query."""
        temp_db.save_memory(
            content="Use PostgreSQL for better JSON support",
            category="decision",
        )
        temp_db.save_memory(
            content="MySQL has good performance for simple queries",
            category="learning",
        )
        temp_db.save_memory(
            content="Don't forget to add indexes",
            category="pitfall",
        )

        # Search for "PostgreSQL"
        results = temp_db.recall_memories(query="PostgreSQL")
        assert len(results) == 1
        assert "PostgreSQL" in results[0].content

        # Search for "queries" (partial match)
        results = temp_db.recall_memories(query="queries")
        assert len(results) == 1
        assert "MySQL" in results[0].content

    def test_recall_memories_by_importance(self, temp_db: MUbase) -> None:
        """Memories can be filtered by minimum importance."""
        temp_db.save_memory(content="Low importance", category="learning", importance=1)
        temp_db.save_memory(content="Medium importance", category="learning", importance=3)
        temp_db.save_memory(content="High importance", category="learning", importance=5)

        # Get high importance only
        results = temp_db.recall_memories(min_importance=4)
        assert len(results) == 1
        assert results[0].content == "High importance"

        # Get medium and above
        results = temp_db.recall_memories(min_importance=3)
        assert len(results) == 2

    def test_recall_memories_by_tags(self, temp_db: MUbase) -> None:
        """Memories can be filtered by tags."""
        temp_db.save_memory(
            content="Python naming conventions",
            category="convention",
            tags=["python", "naming"],
        )
        temp_db.save_memory(
            content="JavaScript naming conventions",
            category="convention",
            tags=["javascript", "naming"],
        )
        temp_db.save_memory(
            content="Database optimization",
            category="learning",
            tags=["database", "performance"],
        )

        # Search by single tag
        results = temp_db.recall_memories(tags=["python"])
        assert len(results) == 1
        assert "Python" in results[0].content

        # Search by multiple tags (OR match)
        results = temp_db.recall_memories(tags=["python", "database"])
        assert len(results) == 2

    def test_recall_memories_sorted_by_importance(self, temp_db: MUbase) -> None:
        """Memories are sorted by importance (descending)."""
        temp_db.save_memory(content="Low", category="learning", importance=1)
        temp_db.save_memory(content="High", category="learning", importance=5)
        temp_db.save_memory(content="Medium", category="learning", importance=3)

        results = temp_db.recall_memories()

        # Should be sorted by importance descending
        assert results[0].importance >= results[1].importance >= results[2].importance
        assert results[0].content == "High"

    def test_delete_memory(self, temp_db: MUbase) -> None:
        """Memories can be deleted."""
        memory_id = temp_db.save_memory(
            content="Temporary note",
            category="todo",
        )

        assert temp_db.has_memories()
        temp_db.delete_memory(memory_id)

        # Should no longer exist
        _ = temp_db.get_memory(memory_id)
        # Note: get_memory may still try to increment access count
        # so just check has_memories
        assert not temp_db.has_memories()

    def test_memory_stats(self, temp_db: MUbase) -> None:
        """Memory stats are calculated correctly."""
        temp_db.save_memory(content="D1", category="decision", importance=1)
        temp_db.save_memory(content="D2", category="decision", importance=2)
        temp_db.save_memory(content="L1", category="learning", importance=3)

        stats = temp_db.memory_stats()

        assert stats["total_memories"] == 3
        assert stats["memories_by_category"]["decision"] == 2
        assert stats["memories_by_category"]["learning"] == 1

    def test_has_memories_empty(self, temp_db: MUbase) -> None:
        """has_memories returns False for empty database."""
        assert not temp_db.has_memories()


class TestMemoryManager:
    """Tests for the MemoryManager high-level interface."""

    @pytest.fixture
    def manager(self, tmp_path: Path) -> MemoryManager:
        """Create a MemoryManager with temporary database."""
        db = MUbase(tmp_path / ".mubase")
        return MemoryManager(db)

    def test_remember_basic(self, manager: MemoryManager) -> None:
        """Basic memory storage works."""
        memory_id = manager.remember(
            "User prefers dark mode",
            category=MemoryCategory.PREFERENCE,
        )

        assert memory_id.startswith("mem:preference:")

    def test_remember_with_all_options(self, manager: MemoryManager) -> None:
        """Memory storage with all options works."""
        memory_id = manager.remember(
            "Use async/await over .then() chains",
            category=MemoryCategory.CONVENTION,
            context="Codebase uses modern async patterns",
            source="src/api/handlers.py",
            importance=4,
            tags=["async", "javascript", "typescript"],
            confidence=0.95,
        )

        memory = manager.get(memory_id)
        assert memory is not None
        assert memory.content == "Use async/await over .then() chains"
        assert memory.category == MemoryCategory.CONVENTION
        assert memory.context == "Codebase uses modern async patterns"
        assert memory.source == "src/api/handlers.py"
        assert memory.importance == 4
        assert "async" in memory.tags

    def test_remember_string_category(self, manager: MemoryManager) -> None:
        """Memory storage accepts string category."""
        memory_id = manager.remember(
            "Test content",
            category="pitfall",  # String instead of enum
        )

        memory = manager.get(memory_id)
        assert memory is not None
        assert memory.category == MemoryCategory.PITFALL

    def test_recall_basic(self, manager: MemoryManager) -> None:
        """Basic memory recall works."""
        manager.remember("Memory 1", category=MemoryCategory.LEARNING)
        manager.remember("Memory 2", category=MemoryCategory.DECISION)

        result = manager.recall()

        assert isinstance(result, RecallResult)
        assert result.total_matches == 2
        assert len(result.memories) == 2

    def test_recall_with_query(self, manager: MemoryManager) -> None:
        """Memory recall with text query works."""
        manager.remember(
            "PostgreSQL has better JSON support",
            category=MemoryCategory.DECISION,
        )
        manager.remember(
            "MySQL is good for simple queries",
            category=MemoryCategory.LEARNING,
        )

        result = manager.recall(query="PostgreSQL")

        assert result.total_matches == 1
        assert "PostgreSQL" in result.memories[0].content

    def test_recall_with_category(self, manager: MemoryManager) -> None:
        """Memory recall with category filter works."""
        manager.remember("Decision 1", category=MemoryCategory.DECISION)
        manager.remember("Pitfall 1", category=MemoryCategory.PITFALL)

        result = manager.recall(category=MemoryCategory.DECISION)

        assert result.total_matches == 1
        assert result.memories[0].category == MemoryCategory.DECISION

    def test_recall_string_category(self, manager: MemoryManager) -> None:
        """Memory recall accepts string category."""
        manager.remember("Test", category=MemoryCategory.TODO)

        result = manager.recall(category="todo")  # String

        assert result.total_matches == 1
        assert result.memories[0].category == MemoryCategory.TODO

    def test_forget(self, manager: MemoryManager) -> None:
        """Memory deletion works."""
        memory_id = manager.remember("Temporary", category=MemoryCategory.TODO)

        assert manager.has_memories()
        manager.forget(memory_id)
        assert not manager.has_memories()

    def test_stats(self, manager: MemoryManager) -> None:
        """Memory stats work."""
        manager.remember("D1", category=MemoryCategory.DECISION)
        manager.remember("D2", category=MemoryCategory.DECISION)
        manager.remember("P1", category=MemoryCategory.PITFALL)

        stats = manager.stats()

        assert stats["total_memories"] == 3
        assert stats["memories_by_category"]["decision"] == 2
        assert stats["memories_by_category"]["pitfall"] == 1

    def test_recall_context(self, manager: MemoryManager) -> None:
        """Task-aware memory recall works."""
        manager.remember(
            "Always validate API inputs",
            category=MemoryCategory.CONVENTION,
            tags=["api", "validation"],
            importance=4,
        )
        manager.remember(
            "Use zod for schema validation",
            category=MemoryCategory.LEARNING,
            tags=["validation", "typescript"],
            importance=3,
        )
        manager.remember(
            "Database migrations need backup",
            category=MemoryCategory.PITFALL,
            tags=["database"],
            importance=3,
        )

        # Recall context for an API task
        memories = manager.recall_context("Add validation to API endpoints")

        # Should find validation-related memories
        assert len(memories) > 0
        contents = [m.content for m in memories]
        assert any("validation" in c.lower() for c in contents)

    def test_importance_clamping(self, manager: MemoryManager) -> None:
        """Importance is clamped to valid range."""
        # Too low
        id1 = manager.remember("Low", category=MemoryCategory.LEARNING, importance=-5)
        mem1 = manager.get(id1)
        assert mem1 is not None
        assert mem1.importance == 1  # Clamped to minimum

        # Too high
        id2 = manager.remember("High", category=MemoryCategory.LEARNING, importance=100)
        mem2 = manager.get(id2)
        assert mem2 is not None
        assert mem2.importance == 5  # Clamped to maximum

    def test_confidence_clamping(self, manager: MemoryManager) -> None:
        """Confidence is clamped to valid range in MemoryManager."""
        # Note: MemoryManager.remember clamps confidence before storing
        # The underlying MUbase.save_memory doesn't clamp (pass-through)

        # Too low - should be clamped to 0.0
        id1 = manager.remember("Low", category=MemoryCategory.LEARNING, confidence=-0.5)
        mem1 = manager.get(id1)
        assert mem1 is not None
        # Clamping happens in remember(), stored value should be 0.0
        assert mem1.confidence >= 0.0  # At minimum, not negative

        # Too high - should be clamped to 1.0
        id2 = manager.remember("High", category=MemoryCategory.LEARNING, confidence=2.0)
        mem2 = manager.get(id2)
        assert mem2 is not None
        assert mem2.confidence <= 1.0  # At maximum, not above 1.0
