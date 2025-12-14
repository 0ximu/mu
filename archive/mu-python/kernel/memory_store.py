"""Memory storage operations for MUbase.

This module provides methods for storing and retrieving cross-session
learnings and memories in the code graph database.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.schema import MEMORY_SCHEMA_SQL

if TYPE_CHECKING:
    from mu.extras.intelligence.models import Memory
    from mu.kernel.queries import ConnectionProtocol


class MemoryStore:
    """Memory storage and retrieval operations.

    Provides methods for storing cross-session learnings and memories.
    Supports access tracking and importance-based retrieval.
    """

    def __init__(self, conn: ConnectionProtocol, read_only: bool = False) -> None:
        """Initialize with a database connection.

        Args:
            conn: DuckDB connection object.
            read_only: Whether the database is opened in read-only mode.
        """
        self._conn = conn
        self._read_only = read_only

    def _ensure_schema(self) -> None:
        """Create memory table if it doesn't exist.

        In read-only mode, just checks if table exists without creating.

        Raises:
            duckdb.CatalogException: If table doesn't exist in read-only mode.
        """
        try:
            self._conn.execute("SELECT 1 FROM memories LIMIT 1")
        except duckdb.CatalogException:
            if self._read_only:
                # In read-only mode, we can't create the table
                raise
            self._conn.execute(MEMORY_SCHEMA_SQL)

    def save_memory(
        self,
        content: str,
        category: str,
        context: str = "",
        source: str = "",
        confidence: float = 1.0,
        importance: int = 1,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        """Save a memory to the database.

        Args:
            content: The memory content.
            category: Memory category (preference, decision, context, etc.).
            context: Optional additional context.
            source: Where this memory came from.
            confidence: Confidence level (0.0 - 1.0).
            importance: Importance level (1-5).
            tags: Optional list of tags.
            embedding: Optional vector embedding.

        Returns:
            The memory ID.
        """
        self._ensure_schema()

        # Generate ID from content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        memory_id = f"mem:{category}:{content_hash}"

        now = datetime.now(UTC).isoformat()

        # Check if memory already exists (update if so)
        existing = self._conn.execute(
            "SELECT id, access_count FROM memories WHERE id = ?", [memory_id]
        ).fetchone()

        if existing:
            # Update existing memory
            self._conn.execute(
                """
                UPDATE memories SET
                    content = ?, context = ?, source = ?,
                    confidence = ?, importance = ?, tags = ?,
                    embedding = ?, updated_at = ?
                WHERE id = ?
                """,
                [
                    content,
                    context,
                    source,
                    confidence,
                    importance,
                    json.dumps(tags or []),
                    embedding,
                    now,
                    memory_id,
                ],
            )
        else:
            # Insert new memory
            self._conn.execute(
                """
                INSERT INTO memories
                (id, category, content, context, source, confidence,
                 importance, tags, embedding, created_at, updated_at,
                 accessed_at, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
                """,
                [
                    memory_id,
                    category,
                    content,
                    context,
                    source,
                    confidence,
                    importance,
                    json.dumps(tags or []),
                    embedding,
                    now,
                    now,
                ],
            )

        return memory_id

    def get_memory(self, memory_id: str) -> Memory | None:
        """Get a memory by ID.

        Updates access tracking on retrieval.

        Args:
            memory_id: The memory ID.

        Returns:
            Memory object if found, None otherwise.
        """
        from mu.extras.intelligence.models import Memory, MemoryCategory

        self._ensure_schema()

        row = self._conn.execute("SELECT * FROM memories WHERE id = ?", [memory_id]).fetchone()

        if not row:
            return None

        # Update access tracking (skip in read-only mode)
        now = datetime.now(UTC).isoformat()
        if not self._read_only:
            self._conn.execute(
                "UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                [now, memory_id],
            )

        # row: id, category, content, context, source, confidence,
        #      importance, tags, embedding, created_at, updated_at,
        #      accessed_at, access_count
        return Memory(
            id=row[0],
            category=MemoryCategory(row[1]),
            content=row[2],
            context=row[3] or "",
            source=row[4] or "",
            confidence=row[5] or 1.0,
            importance=row[6] or 1,
            tags=json.loads(row[7]) if row[7] else [],
            embedding=row[8],
            created_at=row[9] or "",
            updated_at=row[10] or "",
            accessed_at=now if not self._read_only else row[11],
            access_count=(row[12] or 0) + (0 if self._read_only else 1),
        )

    def recall_memories(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: int = 0,
        limit: int = 10,
    ) -> list[Memory]:
        """Recall memories based on search criteria.

        Args:
            query: Optional text search in content/context.
            category: Optional category filter.
            tags: Optional tags filter (any match).
            min_importance: Minimum importance level.
            limit: Maximum number of results.

        Returns:
            List of Memory objects.
        """
        from mu.extras.intelligence.models import Memory, MemoryCategory

        self._ensure_schema()

        conditions: list[str] = []
        params: list[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if min_importance > 0:
            conditions.append("importance >= ?")
            params.append(min_importance)

        if query:
            conditions.append("(content LIKE ? OR context LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        if tags:
            # Check if any tag matches
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
            conditions.append(f"({' OR '.join(tag_conditions)})")

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM memories
            WHERE {where_clause}
            ORDER BY importance DESC, access_count DESC, updated_at DESC
            LIMIT ?
        """
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()

        # Update access tracking for retrieved memories (skip in read-only mode)
        if not self._read_only:
            now = datetime.now(UTC).isoformat()
            memory_ids = [row[0] for row in rows]
            if memory_ids:
                placeholders = ", ".join(["?"] * len(memory_ids))
                self._conn.execute(
                    f"UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id IN ({placeholders})",
                    [now, *memory_ids],
                )

        memories: list[Memory] = []
        for row in rows:
            memories.append(
                Memory(
                    id=row[0],
                    category=MemoryCategory(row[1]),
                    content=row[2],
                    context=row[3] or "",
                    source=row[4] or "",
                    confidence=row[5] or 1.0,
                    importance=row[6] or 1,
                    tags=json.loads(row[7]) if row[7] else [],
                    embedding=row[8],
                    created_at=row[9] or "",
                    updated_at=row[10] or "",
                    accessed_at=row[11],
                    access_count=row[12] or 0,
                )
            )

        return memories

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory.

        Args:
            memory_id: The memory ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        self._ensure_schema()
        self._conn.execute("DELETE FROM memories WHERE id = ?", [memory_id])
        return True

    def has_memories(self) -> bool:
        """Check if any memories exist.

        Returns:
            True if memories exist, False otherwise.
        """
        try:
            self._ensure_schema()
            result = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return result is not None and result[0] > 0
        except Exception:
            return False

    def stats(self) -> dict[str, Any]:
        """Get memory statistics.

        Returns:
            Dictionary with memory counts and categories.
            Returns empty stats if memories table doesn't exist.
        """
        try:
            self._ensure_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            return {
                "total_memories": 0,
                "memories_by_category": {},
            }

        result = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        total = result[0] if result else 0

        by_category: dict[str, int] = {}
        rows = self._conn.execute(
            "SELECT category, COUNT(*) FROM memories GROUP BY category"
        ).fetchall()
        for row in rows:
            by_category[row[0]] = row[1]

        return {
            "total_memories": total,
            "memories_by_category": by_category,
        }


__all__ = [
    "MemoryStore",
]
