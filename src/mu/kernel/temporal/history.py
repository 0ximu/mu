"""History tracking for temporal layer.

Provides HistoryTracker for querying node history, blame information,
and tracking changes over time.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.schema import TEMPORAL_SCHEMA_SQL
from mu.kernel.temporal.models import ChangeType, NodeChange

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class HistoryTracker:
    """Track and query node history across snapshots.

    Provides methods for retrieving change history, blame information,
    and first appearance tracking for nodes.
    """

    def __init__(self, mubase: MUbase) -> None:
        """Initialize history tracker.

        Args:
            mubase: The MUbase database to track history for.
        """
        self._db = mubase
        self._temporal_initialized = False

    def _ensure_temporal_schema(self) -> None:
        """Create temporal tables if they don't exist (lazy initialization)."""
        if self._temporal_initialized:
            return

        try:
            self._db.conn.execute("SELECT 1 FROM node_history LIMIT 1")
            self._temporal_initialized = True
        except duckdb.CatalogException:
            # Tables don't exist, create them (if not read-only)
            if self._db.read_only:
                # In read-only mode, we can't create tables
                # Just mark as initialized and let queries fail gracefully
                self._temporal_initialized = True
                return
            self._db.conn.execute(TEMPORAL_SCHEMA_SQL)
            self._temporal_initialized = True

    def history(
        self,
        node_id: str,
        limit: int = 100,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[NodeChange]:
        """Get chronological list of changes to a node.

        Args:
            node_id: The node ID to get history for.
            limit: Maximum number of changes to return.
            since: Only changes after this date.
            until: Only changes before this date.

        Returns:
            List of NodeChange objects in chronological order (oldest first).
        """
        self._ensure_temporal_schema()
        conditions = ["nh.node_id = ?"]
        params: list[Any] = [node_id]

        if since:
            conditions.append("s.commit_date >= ?")
            params.append(since.isoformat())

        if until:
            conditions.append("s.commit_date <= ?")
            params.append(until.isoformat())

        where_clause = " AND ".join(conditions)
        params.append(limit)

        rows = self._db.conn.execute(
            f"""
            SELECT nh.id, nh.snapshot_id, nh.node_id, nh.change_type,
                   nh.body_hash, nh.properties,
                   s.commit_hash, s.commit_message, s.commit_author, s.commit_date
            FROM node_history nh
            JOIN snapshots s ON s.id = nh.snapshot_id
            WHERE {where_clause}
            ORDER BY s.commit_date ASC
            LIMIT ?
            """,
            params,
        ).fetchall()

        return [NodeChange.from_row(row) for row in rows]

    def blame(self, node_id: str) -> dict[str, NodeChange]:
        """Get last change for each property/attribute of a node.

        This is similar to git blame - shows who last modified each aspect
        of the node (name, type, complexity, etc.).

        Args:
            node_id: The node ID to get blame for.

        Returns:
            Dictionary mapping property name to the NodeChange that last modified it.
        """
        self._ensure_temporal_schema()
        # Get all changes to this node, most recent first
        rows = self._db.conn.execute(
            """
            SELECT nh.id, nh.snapshot_id, nh.node_id, nh.change_type,
                   nh.body_hash, nh.properties,
                   s.commit_hash, s.commit_message, s.commit_author, s.commit_date
            FROM node_history nh
            JOIN snapshots s ON s.id = nh.snapshot_id
            WHERE nh.node_id = ? AND nh.change_type IN (?, ?)
            ORDER BY s.commit_date DESC
            """,
            [node_id, ChangeType.ADDED.value, ChangeType.MODIFIED.value],
        ).fetchall()

        if not rows:
            return {}

        changes = [NodeChange.from_row(row) for row in rows]

        # The most recent change is responsible for current state
        blame_info: dict[str, NodeChange] = {}

        # Get current node properties from the most recent change
        if changes:
            most_recent = changes[0]

            # Track which properties were set by which commit
            # Start with most recent and work backwards
            seen_properties: set[str] = set()

            for change in changes:
                props = change.properties or {}

                # For added nodes, all properties are attributed to this change
                if change.change_type == ChangeType.ADDED:
                    for prop_name in props:
                        if prop_name not in seen_properties:
                            blame_info[prop_name] = change
                            seen_properties.add(prop_name)
                    break

                # For modified nodes, track changed properties
                for prop_name in props:
                    if prop_name not in seen_properties:
                        blame_info[prop_name] = change
                        seen_properties.add(prop_name)

            # Add overall "node" blame - when was the node last changed
            blame_info["_node"] = most_recent

        return blame_info

    def first_appearance(self, node_id: str) -> NodeChange | None:
        """Get the first time a node appeared in the history.

        Args:
            node_id: The node ID to look up.

        Returns:
            NodeChange for when the node was first added, or None if not found.
        """
        self._ensure_temporal_schema()
        row = self._db.conn.execute(
            """
            SELECT nh.id, nh.snapshot_id, nh.node_id, nh.change_type,
                   nh.body_hash, nh.properties,
                   s.commit_hash, s.commit_message, s.commit_author, s.commit_date
            FROM node_history nh
            JOIN snapshots s ON s.id = nh.snapshot_id
            WHERE nh.node_id = ? AND nh.change_type = ?
            ORDER BY s.commit_date ASC
            LIMIT 1
            """,
            [node_id, ChangeType.ADDED.value],
        ).fetchone()

        return NodeChange.from_row(row) if row else None

    def last_modified(self, node_id: str) -> NodeChange | None:
        """Get the most recent modification to a node.

        Args:
            node_id: The node ID to look up.

        Returns:
            Most recent NodeChange, or None if node has no history.
        """
        self._ensure_temporal_schema()
        row = self._db.conn.execute(
            """
            SELECT nh.id, nh.snapshot_id, nh.node_id, nh.change_type,
                   nh.body_hash, nh.properties,
                   s.commit_hash, s.commit_message, s.commit_author, s.commit_date
            FROM node_history nh
            JOIN snapshots s ON s.id = nh.snapshot_id
            WHERE nh.node_id = ? AND nh.change_type IN (?, ?)
            ORDER BY s.commit_date DESC
            LIMIT 1
            """,
            [node_id, ChangeType.ADDED.value, ChangeType.MODIFIED.value],
        ).fetchone()

        return NodeChange.from_row(row) if row else None

    def changes_in_snapshot(
        self,
        snapshot_id: str,
        change_type: ChangeType | None = None,
    ) -> list[NodeChange]:
        """Get all node changes in a specific snapshot.

        Args:
            snapshot_id: The snapshot ID to query.
            change_type: Optional filter for change type.

        Returns:
            List of NodeChange objects in the snapshot.
        """
        self._ensure_temporal_schema()
        conditions = ["nh.snapshot_id = ?"]
        params: list[Any] = [snapshot_id]

        if change_type:
            conditions.append("nh.change_type = ?")
            params.append(change_type.value)

        where_clause = " AND ".join(conditions)

        rows = self._db.conn.execute(
            f"""
            SELECT nh.id, nh.snapshot_id, nh.node_id, nh.change_type,
                   nh.body_hash, nh.properties,
                   s.commit_hash, s.commit_message, s.commit_author, s.commit_date
            FROM node_history nh
            JOIN snapshots s ON s.id = nh.snapshot_id
            WHERE {where_clause}
            ORDER BY nh.node_id
            """,
            params,
        ).fetchall()

        return [NodeChange.from_row(row) for row in rows]

    def nodes_changed_by_author(
        self,
        author: str,
        limit: int = 100,
    ) -> list[NodeChange]:
        """Get nodes changed by a specific author.

        Args:
            author: Author name or email to search for.
            limit: Maximum number of changes to return.

        Returns:
            List of NodeChange objects by this author.
        """
        self._ensure_temporal_schema()
        rows = self._db.conn.execute(
            """
            SELECT nh.id, nh.snapshot_id, nh.node_id, nh.change_type,
                   nh.body_hash, nh.properties,
                   s.commit_hash, s.commit_message, s.commit_author, s.commit_date
            FROM node_history nh
            JOIN snapshots s ON s.id = nh.snapshot_id
            WHERE s.commit_author LIKE ? AND nh.change_type IN (?, ?)
            ORDER BY s.commit_date DESC
            LIMIT ?
            """,
            [f"%{author}%", ChangeType.ADDED.value, ChangeType.MODIFIED.value, limit],
        ).fetchall()

        return [NodeChange.from_row(row) for row in rows]

    def node_exists_at(
        self,
        node_id: str,
        snapshot_id: str,
    ) -> bool:
        """Check if a node existed at a specific snapshot.

        Args:
            node_id: The node ID to check.
            snapshot_id: The snapshot to check at.

        Returns:
            True if node existed (and wasn't removed), False otherwise.
        """
        self._ensure_temporal_schema()
        row = self._db.conn.execute(
            """
            SELECT change_type FROM node_history
            WHERE snapshot_id = ? AND node_id = ?
            """,
            [snapshot_id, node_id],
        ).fetchone()

        if not row:
            return False

        return bool(row[0] != ChangeType.REMOVED.value)


__all__ = [
    "HistoryTracker",
]
