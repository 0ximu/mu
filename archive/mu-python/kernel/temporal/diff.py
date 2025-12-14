"""Temporal diff computation for code graphs.

Computes semantic differences between two snapshots, showing what
changed in terms of nodes and edges.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mu.kernel.temporal.models import (
    ChangeType,
    EdgeDiff,
    GraphDiff,
    NodeDiff,
    Snapshot,
)

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase
    from mu.kernel.temporal.snapshot import SnapshotManager


class TemporalDiffer:
    """Compute semantic diffs between snapshots.

    Compares the state of the code graph at two different points in time,
    identifying added, removed, and modified nodes and edges.
    """

    def __init__(self, manager: SnapshotManager) -> None:
        """Initialize temporal differ.

        Args:
            manager: SnapshotManager for retrieving snapshots.
        """
        self._manager = manager
        self._db: MUbase = manager.db

    def diff(
        self,
        from_commit: str,
        to_commit: str,
    ) -> GraphDiff:
        """Compute diff between two commits.

        Args:
            from_commit: Base commit hash (older version).
            to_commit: Target commit hash (newer version).

        Returns:
            GraphDiff with all changes between the commits.

        Raises:
            ValueError: If either snapshot doesn't exist.
        """
        from_snapshot = self._manager.get_snapshot(from_commit)
        if not from_snapshot:
            raise ValueError(f"No snapshot exists for commit: {from_commit}")

        to_snapshot = self._manager.get_snapshot(to_commit)
        if not to_snapshot:
            raise ValueError(f"No snapshot exists for commit: {to_commit}")

        return self.diff_snapshots(from_snapshot, to_snapshot)

    def diff_snapshots(
        self,
        from_snapshot: Snapshot,
        to_snapshot: Snapshot,
    ) -> GraphDiff:
        """Compute diff between two snapshots.

        Args:
            from_snapshot: Base snapshot (older version).
            to_snapshot: Target snapshot (newer version).

        Returns:
            GraphDiff with all changes between the snapshots.
        """
        # Get nodes at each snapshot
        from_nodes = self._get_nodes_at_snapshot(from_snapshot.id)
        to_nodes = self._get_nodes_at_snapshot(to_snapshot.id)

        # Calculate node changes
        nodes_added, nodes_removed, nodes_modified = self._diff_nodes(from_nodes, to_nodes)

        # Get edges at each snapshot
        from_edges = self._get_edges_at_snapshot(from_snapshot.id)
        to_edges = self._get_edges_at_snapshot(to_snapshot.id)

        # Calculate edge changes
        edges_added, edges_removed = self._diff_edges(from_edges, to_edges)

        return GraphDiff(
            from_snapshot=from_snapshot,
            to_snapshot=to_snapshot,
            nodes_added=nodes_added,
            nodes_removed=nodes_removed,
            nodes_modified=nodes_modified,
            edges_added=edges_added,
            edges_removed=edges_removed,
        )

    def _get_nodes_at_snapshot(
        self,
        snapshot_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Get all nodes that existed at a snapshot.

        Returns dict mapping node_id to node info (name, type, path, properties).
        """
        rows = self._db.conn.execute(
            """
            SELECT nh.node_id, n.name, n.type, n.file_path, nh.properties, nh.body_hash
            FROM node_history nh
            JOIN nodes n ON n.id = nh.node_id
            WHERE nh.snapshot_id = ? AND nh.change_type != ?
            """,
            [snapshot_id, ChangeType.REMOVED.value],
        ).fetchall()

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            props = row[4]
            if isinstance(props, str):
                props = json.loads(props)
            elif props is None:
                props = {}

            result[row[0]] = {
                "name": row[1],
                "type": row[2],
                "file_path": row[3],
                "properties": props,
                "body_hash": row[5],
            }

        return result

    def _get_edges_at_snapshot(
        self,
        snapshot_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Get all edges that existed at a snapshot.

        Returns dict mapping edge_id to edge info (source, target, type).
        """
        rows = self._db.conn.execute(
            """
            SELECT edge_id, source_id, target_id, edge_type
            FROM edge_history
            WHERE snapshot_id = ? AND change_type != ?
            """,
            [snapshot_id, ChangeType.REMOVED.value],
        ).fetchall()

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            result[row[0]] = {
                "source_id": row[1],
                "target_id": row[2],
                "edge_type": row[3],
            }

        return result

    def _diff_nodes(
        self,
        from_nodes: dict[str, dict[str, Any]],
        to_nodes: dict[str, dict[str, Any]],
    ) -> tuple[list[NodeDiff], list[NodeDiff], list[NodeDiff]]:
        """Calculate node differences between two states."""
        added: list[NodeDiff] = []
        removed: list[NodeDiff] = []
        modified: list[NodeDiff] = []

        from_ids = set(from_nodes.keys())
        to_ids = set(to_nodes.keys())

        # Added nodes
        for node_id in to_ids - from_ids:
            info = to_nodes[node_id]
            added.append(
                NodeDiff(
                    node_id=node_id,
                    name=info["name"],
                    node_type=info["type"],
                    change_type=ChangeType.ADDED,
                    file_path=info.get("file_path"),
                    new_properties=info.get("properties", {}),
                )
            )

        # Removed nodes
        for node_id in from_ids - to_ids:
            info = from_nodes[node_id]
            removed.append(
                NodeDiff(
                    node_id=node_id,
                    name=info["name"],
                    node_type=info["type"],
                    change_type=ChangeType.REMOVED,
                    file_path=info.get("file_path"),
                    old_properties=info.get("properties", {}),
                )
            )

        # Modified nodes
        for node_id in from_ids & to_ids:
            from_info = from_nodes[node_id]
            to_info = to_nodes[node_id]

            # Compare by body_hash for change detection
            if from_info.get("body_hash") != to_info.get("body_hash"):
                modified.append(
                    NodeDiff(
                        node_id=node_id,
                        name=to_info["name"],
                        node_type=to_info["type"],
                        change_type=ChangeType.MODIFIED,
                        file_path=to_info.get("file_path"),
                        old_properties=from_info.get("properties", {}),
                        new_properties=to_info.get("properties", {}),
                    )
                )

        return added, removed, modified

    def _diff_edges(
        self,
        from_edges: dict[str, dict[str, Any]],
        to_edges: dict[str, dict[str, Any]],
    ) -> tuple[list[EdgeDiff], list[EdgeDiff]]:
        """Calculate edge differences between two states."""
        added: list[EdgeDiff] = []
        removed: list[EdgeDiff] = []

        from_ids = set(from_edges.keys())
        to_ids = set(to_edges.keys())

        # Added edges
        for edge_id in to_ids - from_ids:
            info = to_edges[edge_id]
            added.append(
                EdgeDiff(
                    edge_id=edge_id,
                    source_id=info["source_id"],
                    target_id=info["target_id"],
                    edge_type=info["edge_type"],
                    change_type=ChangeType.ADDED,
                )
            )

        # Removed edges
        for edge_id in from_ids - to_ids:
            info = from_edges[edge_id]
            removed.append(
                EdgeDiff(
                    edge_id=edge_id,
                    source_id=info["source_id"],
                    target_id=info["target_id"],
                    edge_type=info["edge_type"],
                    change_type=ChangeType.REMOVED,
                )
            )

        return added, removed

    def diff_range(
        self,
        from_commit: str,
        to_commit: str,
        include_intermediate: bool = False,
    ) -> GraphDiff | list[GraphDiff]:
        """Compute diff(s) for a range of commits.

        Args:
            from_commit: Start commit (older).
            to_commit: End commit (newer).
            include_intermediate: If True, return diff for each intermediate snapshot.

        Returns:
            Single GraphDiff if include_intermediate=False,
            list of GraphDiffs otherwise.
        """
        if not include_intermediate:
            return self.diff(from_commit, to_commit)

        # Get all snapshots in range
        snapshots = self._manager.list_snapshots(limit=1000)

        # Filter to range
        from_snapshot = self._manager.get_snapshot(from_commit)
        to_snapshot = self._manager.get_snapshot(to_commit)

        if not from_snapshot or not to_snapshot:
            raise ValueError("Both commits must have snapshots")

        # Find snapshots in date range
        from_date = from_snapshot.commit_date
        to_date = to_snapshot.commit_date

        if not from_date or not to_date:
            # Fall back to single diff
            return [self.diff(from_commit, to_commit)]

        in_range = []
        for snap in snapshots:
            if snap.commit_date and from_date <= snap.commit_date <= to_date:
                in_range.append(snap)

        # Sort by date
        in_range.sort(key=lambda s: s.commit_date or from_date)

        if len(in_range) < 2:
            return [self.diff(from_commit, to_commit)]

        # Compute diffs between consecutive snapshots
        diffs: list[GraphDiff] = []
        for i in range(len(in_range) - 1):
            diff = self.diff_snapshots(in_range[i], in_range[i + 1])
            diffs.append(diff)

        return diffs


__all__ = [
    "TemporalDiffer",
]
