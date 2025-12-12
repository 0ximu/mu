"""Pattern storage operations for MUbase.

This module provides methods for storing and retrieving codebase patterns
detected by the intelligence module.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.schema import PATTERNS_SCHEMA_SQL

if TYPE_CHECKING:
    from mu.extras.intelligence.models import Pattern
    from mu.kernel.queries import ConnectionProtocol


class PatternsStore:
    """Pattern storage and retrieval operations.

    Provides methods for storing detected codebase patterns and
    retrieving them for analysis. Operates on an existing database connection.
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
        """Create patterns table if it doesn't exist.

        In read-only mode, just checks if table exists without creating.

        Raises:
            duckdb.CatalogException: If table doesn't exist in read-only mode.
        """
        try:
            self._conn.execute("SELECT 1 FROM patterns LIMIT 1")
        except duckdb.CatalogException:
            if self._read_only:
                # In read-only mode, we can't create the table
                raise
            self._conn.execute(PATTERNS_SCHEMA_SQL)

    def save_patterns(self, patterns: list[Pattern]) -> None:
        """Save patterns to the database.

        Replaces all existing patterns with the new list.

        Args:
            patterns: List of Pattern objects to save.
        """
        self._ensure_schema()

        # Clear existing patterns
        self._conn.execute("DELETE FROM patterns")

        now = datetime.now(UTC).isoformat()
        for pattern in patterns:
            self._conn.execute(
                """
                INSERT INTO patterns
                (id, category, name, description, frequency, confidence,
                 examples, anti_patterns, related_patterns, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    f"pat:{pattern.category.value}:{pattern.name}",
                    pattern.category.value,
                    pattern.name,
                    pattern.description,
                    pattern.frequency,
                    pattern.confidence,
                    json.dumps([e.to_dict() for e in pattern.examples]),
                    json.dumps(pattern.anti_patterns),
                    json.dumps(getattr(pattern, "related_patterns", [])),
                    now,
                    now,
                ],
            )

    def get_patterns(self, category: str | None = None) -> list[Pattern]:
        """Get stored patterns.

        Args:
            category: Optional category filter.

        Returns:
            List of Pattern objects.
        """
        from mu.extras.intelligence.models import Pattern, PatternCategory, PatternExample

        self._ensure_schema()

        if category:
            rows = self._conn.execute(
                "SELECT * FROM patterns WHERE category = ? ORDER BY frequency DESC",
                [category],
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM patterns ORDER BY frequency DESC").fetchall()

        patterns: list[Pattern] = []
        for row in rows:
            # row: id, category, name, description, frequency, confidence,
            #      examples, anti_patterns, related_patterns, created_at, updated_at
            examples_data = json.loads(row[6]) if row[6] else []
            examples = [
                PatternExample(
                    file_path=e.get("file_path", ""),
                    line_start=e.get("line_start", 0),
                    line_end=e.get("line_end", 0),
                    code_snippet=e.get("code_snippet", ""),
                    annotation=e.get("annotation", ""),
                )
                for e in examples_data
            ]
            patterns.append(
                Pattern(
                    name=row[2],
                    category=PatternCategory(row[1]),
                    description=row[3] or "",
                    frequency=row[4] or 0,
                    confidence=row[5] or 0.0,
                    examples=examples,
                    anti_patterns=json.loads(row[7]) if row[7] else [],
                    related_patterns=json.loads(row[8]) if row[8] else [],
                )
            )
        return patterns

    def has_patterns(self) -> bool:
        """Check if patterns are stored in the database.

        Returns:
            True if patterns exist, False otherwise.
        """
        try:
            self._ensure_schema()
            result = self._conn.execute("SELECT COUNT(*) FROM patterns").fetchone()
            return result is not None and result[0] > 0
        except Exception:
            return False

    def stats(self) -> dict[str, Any]:
        """Get pattern statistics.

        Returns:
            Dictionary with pattern counts and categories.
            Returns empty stats if patterns table doesn't exist.
        """
        try:
            self._ensure_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            return {
                "total_patterns": 0,
                "patterns_by_category": {},
            }

        result = self._conn.execute("SELECT COUNT(*) FROM patterns").fetchone()
        total = result[0] if result else 0

        by_category: dict[str, int] = {}
        rows = self._conn.execute(
            "SELECT category, COUNT(*) FROM patterns GROUP BY category"
        ).fetchall()
        for row in rows:
            by_category[row[0]] = row[1]

        return {
            "total_patterns": total,
            "patterns_by_category": by_category,
        }


__all__ = [
    "PatternsStore",
]
