"""Codebase statistics storage operations for MUbase.

This module provides methods for storing and retrieving codebase statistics
such as language distribution and other metrics.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.schema import CODEBASE_STATS_SCHEMA_SQL

if TYPE_CHECKING:
    from mu.kernel.queries import ConnectionProtocol
    from mu.parser.models import ModuleDef


class StatsStore:
    """Codebase statistics storage and retrieval operations.

    Provides methods for storing computed statistics about the codebase
    such as language distribution and metrics.
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
        """Create codebase_stats table if it doesn't exist.

        In read-only mode, just checks if table exists without creating.

        Raises:
            duckdb.CatalogException: If table doesn't exist in read-only mode.
        """
        try:
            self._conn.execute("SELECT 1 FROM codebase_stats LIMIT 1")
        except duckdb.CatalogException:
            if self._read_only:
                # In read-only mode, we can't create the table
                raise
            self._conn.execute(CODEBASE_STATS_SCHEMA_SQL)

    def compute_and_store_language_stats(self, modules: list[ModuleDef]) -> None:
        """Compute language statistics from modules and store in database.

        Args:
            modules: List of parsed ModuleDef objects.
        """
        # Count files by language
        languages: Counter[str] = Counter()
        ext_map = {
            ".py": "Python",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".cs": "C#",
            ".rb": "Ruby",
            ".php": "PHP",
            ".swift": "Swift",
            ".kt": "Kotlin",
            ".scala": "Scala",
            ".cpp": "C++",
            ".c": "C",
            ".h": "C/C++ Header",
            ".hpp": "C++ Header",
        }

        for module in modules:
            # Get extension from file path
            if module.path:
                ext = "." + module.path.rsplit(".", 1)[-1] if "." in module.path else ""
                lang = ext_map.get(ext.lower())
                if lang:
                    languages[lang] += 1

        # Calculate percentages
        total = sum(languages.values())
        percentages: dict[str, float] = {}
        if total > 0:
            for lang, count in languages.items():
                percentages[lang] = round(count / total * 100, 2)

        # Determine primary language
        primary_language = languages.most_common(1)[0][0] if languages else None

        # Store in database
        self._ensure_schema()
        now = datetime.now(UTC).isoformat()

        stats_data = {
            "languages": dict(languages),
            "percentages": percentages,
            "primary_language": primary_language,
            "total_files": total,
        }

        # Delete existing and insert new
        self._conn.execute("DELETE FROM codebase_stats WHERE key = 'languages'")
        self._conn.execute(
            "INSERT INTO codebase_stats (key, value, updated_at) VALUES (?, ?, ?)",
            ["languages", json.dumps(stats_data), now],
        )

    def get_language_stats(self) -> dict[str, Any]:
        """Get stored language statistics.

        Returns:
            Dictionary with language distribution:
            {
                "languages": {"Python": 100, "C#": 784, ...},
                "percentages": {"Python": 11.3, "C#": 88.7, ...},
                "primary_language": "C#",
                "total_files": 884
            }
            Returns empty stats if codebase_stats table doesn't exist.
        """
        try:
            self._ensure_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            return {
                "languages": {},
                "percentages": {},
                "primary_language": None,
                "total_files": 0,
            }

        row = self._conn.execute(
            "SELECT value FROM codebase_stats WHERE key = 'languages'"
        ).fetchone()

        if row:
            result: dict[str, Any] = json.loads(row[0])
            return result

        return {
            "languages": {},
            "percentages": {},
            "primary_language": None,
            "total_files": 0,
        }

    def set_stat(self, key: str, value: Any) -> None:
        """Store a codebase statistic.

        Args:
            key: Statistic key.
            value: Value (must be JSON-serializable).
        """
        self._ensure_schema()
        now = datetime.now(UTC).isoformat()

        self._conn.execute("DELETE FROM codebase_stats WHERE key = ?", [key])
        self._conn.execute(
            "INSERT INTO codebase_stats (key, value, updated_at) VALUES (?, ?, ?)",
            [key, json.dumps(value), now],
        )

    def get_stat(self, key: str) -> Any | None:
        """Get a stored codebase statistic.

        Args:
            key: Statistic key.

        Returns:
            The stored value, or None if not found.
        """
        try:
            self._ensure_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            return None

        row = self._conn.execute("SELECT value FROM codebase_stats WHERE key = ?", [key]).fetchone()

        return json.loads(row[0]) if row else None


__all__ = [
    "StatsStore",
]
