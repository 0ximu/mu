"""Data models for the MU Kernel temporal layer.

Defines Snapshot, NodeChange, EdgeChange, and GraphDiff dataclasses
that map to temporal tables in DuckDB.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mu.kernel.schema import ChangeType


@dataclass
class Snapshot:
    """A point-in-time capture of the code graph.

    Represents the state of the codebase at a specific git commit,
    including metadata about what changed since the parent snapshot.
    """

    id: str
    commit_hash: str
    commit_message: str | None = None
    commit_author: str | None = None
    commit_date: datetime | None = None
    parent_id: str | None = None
    node_count: int = 0
    edge_count: int = 0
    nodes_added: int = 0
    nodes_removed: int = 0
    nodes_modified: int = 0
    edges_added: int = 0
    edges_removed: int = 0
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "commit_hash": self.commit_hash,
            "commit_message": self.commit_message,
            "commit_author": self.commit_author,
            "commit_date": self.commit_date.isoformat() if self.commit_date else None,
            "parent_id": self.parent_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "nodes_added": self.nodes_added,
            "nodes_removed": self.nodes_removed,
            "nodes_modified": self.nodes_modified,
            "edges_added": self.edges_added,
            "edges_removed": self.edges_removed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_tuple(
        self,
    ) -> tuple[
        str,
        str,
        str | None,
        str | None,
        str | None,
        str | None,
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        str,
    ]:
        """Convert to tuple for DuckDB insertion."""
        return (
            self.id,
            self.commit_hash,
            self.commit_message,
            self.commit_author,
            self.commit_date.isoformat() if self.commit_date else None,
            self.parent_id,
            self.node_count,
            self.edge_count,
            self.nodes_added,
            self.nodes_removed,
            self.nodes_modified,
            self.edges_added,
            self.edges_removed,
            self.created_at.isoformat() if self.created_at else datetime.now().isoformat(),
        )

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Snapshot:
        """Create Snapshot from DuckDB row.

        Expected row format:
        (id, commit_hash, commit_message, commit_author, commit_date,
         parent_id, node_count, edge_count, nodes_added, nodes_removed,
         nodes_modified, edges_added, edges_removed, created_at)
        """
        commit_date = None
        if row[4]:
            try:
                commit_date = datetime.fromisoformat(row[4])
            except (ValueError, TypeError):
                pass

        created_at = None
        if row[13]:
            try:
                created_at = datetime.fromisoformat(row[13])
            except (ValueError, TypeError):
                pass

        return cls(
            id=row[0],
            commit_hash=row[1],
            commit_message=row[2],
            commit_author=row[3],
            commit_date=commit_date,
            parent_id=row[5],
            node_count=row[6] or 0,
            edge_count=row[7] or 0,
            nodes_added=row[8] or 0,
            nodes_removed=row[9] or 0,
            nodes_modified=row[10] or 0,
            edges_added=row[11] or 0,
            edges_removed=row[12] or 0,
            created_at=created_at,
        )

    @property
    def short_hash(self) -> str:
        """Get abbreviated commit hash."""
        return self.commit_hash[:8] if self.commit_hash else ""

    @property
    def total_changes(self) -> int:
        """Get total number of node changes."""
        return self.nodes_added + self.nodes_removed + self.nodes_modified


@dataclass
class NodeChange:
    """A change to a node in the code graph.

    Tracks what happened to a specific node at a specific snapshot.
    """

    id: str
    snapshot_id: str
    node_id: str
    change_type: ChangeType
    body_hash: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    # Optional: populated when joined with snapshot
    commit_hash: str | None = None
    commit_message: str | None = None
    commit_author: str | None = None
    commit_date: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "snapshot_id": self.snapshot_id,
            "node_id": self.node_id,
            "change_type": self.change_type.value,
            "body_hash": self.body_hash,
            "properties": self.properties,
            "commit_hash": self.commit_hash,
            "commit_message": self.commit_message,
            "commit_author": self.commit_author,
            "commit_date": self.commit_date.isoformat() if self.commit_date else None,
        }

    def to_tuple(self) -> tuple[str, str, str, str, str | None, str]:
        """Convert to tuple for DuckDB insertion."""
        return (
            self.id,
            self.snapshot_id,
            self.node_id,
            self.change_type.value,
            self.body_hash,
            json.dumps(self.properties) if self.properties else "{}",
        )

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> NodeChange:
        """Create NodeChange from DuckDB row.

        Expected row format:
        (id, snapshot_id, node_id, change_type, body_hash, properties)

        Extended format (with JOIN):
        (..., commit_hash, commit_message, commit_author, commit_date)
        """
        properties = row[5]
        if isinstance(properties, str):
            properties = json.loads(properties)
        elif properties is None:
            properties = {}

        change = cls(
            id=row[0],
            snapshot_id=row[1],
            node_id=row[2],
            change_type=ChangeType(row[3]),
            body_hash=row[4],
            properties=properties,
        )

        # Handle extended row with commit info
        if len(row) > 6:
            change.commit_hash = row[6] if len(row) > 6 else None
            change.commit_message = row[7] if len(row) > 7 else None
            change.commit_author = row[8] if len(row) > 8 else None
            if len(row) > 9 and row[9]:
                try:
                    change.commit_date = datetime.fromisoformat(row[9])
                except (ValueError, TypeError):
                    pass

        return change


@dataclass
class EdgeChange:
    """A change to an edge in the code graph.

    Tracks what happened to a specific edge at a specific snapshot.
    """

    id: str
    snapshot_id: str
    edge_id: str
    change_type: ChangeType
    source_id: str
    target_id: str
    edge_type: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "snapshot_id": self.snapshot_id,
            "edge_id": self.edge_id,
            "change_type": self.change_type.value,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "properties": self.properties,
        }

    def to_tuple(self) -> tuple[str, str, str, str, str, str, str, str]:
        """Convert to tuple for DuckDB insertion."""
        return (
            self.id,
            self.snapshot_id,
            self.edge_id,
            self.change_type.value,
            self.source_id,
            self.target_id,
            self.edge_type,
            json.dumps(self.properties) if self.properties else "{}",
        )

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> EdgeChange:
        """Create EdgeChange from DuckDB row.

        Expected row format:
        (id, snapshot_id, edge_id, change_type, source_id, target_id, edge_type, properties)
        """
        properties = row[7]
        if isinstance(properties, str):
            properties = json.loads(properties)
        elif properties is None:
            properties = {}

        return cls(
            id=row[0],
            snapshot_id=row[1],
            edge_id=row[2],
            change_type=ChangeType(row[3]),
            source_id=row[4],
            target_id=row[5],
            edge_type=row[6],
            properties=properties,
        )


@dataclass
class NodeDiff:
    """Difference for a single node between two snapshots."""

    node_id: str
    name: str
    node_type: str
    change_type: ChangeType
    file_path: str | None = None
    old_properties: dict[str, Any] = field(default_factory=dict)
    new_properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "node_id": self.node_id,
            "name": self.name,
            "node_type": self.node_type,
            "change_type": self.change_type.value,
            "file_path": self.file_path,
            "old_properties": self.old_properties,
            "new_properties": self.new_properties,
        }


@dataclass
class EdgeDiff:
    """Difference for a single edge between two snapshots."""

    edge_id: str
    source_id: str
    target_id: str
    edge_type: str
    change_type: ChangeType

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "change_type": self.change_type.value,
        }


@dataclass
class GraphDiff:
    """Semantic diff between two snapshots.

    Contains lists of added, removed, and modified nodes/edges
    between a base and target snapshot.
    """

    from_snapshot: Snapshot
    to_snapshot: Snapshot

    # Node changes
    nodes_added: list[NodeDiff] = field(default_factory=list)
    nodes_removed: list[NodeDiff] = field(default_factory=list)
    nodes_modified: list[NodeDiff] = field(default_factory=list)

    # Edge changes
    edges_added: list[EdgeDiff] = field(default_factory=list)
    edges_removed: list[EdgeDiff] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "from_snapshot": self.from_snapshot.to_dict(),
            "to_snapshot": self.to_snapshot.to_dict(),
            "nodes_added": [n.to_dict() for n in self.nodes_added],
            "nodes_removed": [n.to_dict() for n in self.nodes_removed],
            "nodes_modified": [n.to_dict() for n in self.nodes_modified],
            "edges_added": [e.to_dict() for e in self.edges_added],
            "edges_removed": [e.to_dict() for e in self.edges_removed],
            "stats": self.stats,
        }

    @property
    def stats(self) -> dict[str, int]:
        """Get summary statistics."""
        return {
            "nodes_added": len(self.nodes_added),
            "nodes_removed": len(self.nodes_removed),
            "nodes_modified": len(self.nodes_modified),
            "edges_added": len(self.edges_added),
            "edges_removed": len(self.edges_removed),
            "total_changes": (
                len(self.nodes_added)
                + len(self.nodes_removed)
                + len(self.nodes_modified)
                + len(self.edges_added)
                + len(self.edges_removed)
            ),
        }

    @property
    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return self.stats["total_changes"] > 0


__all__ = [
    "ChangeType",
    "Snapshot",
    "NodeChange",
    "EdgeChange",
    "NodeDiff",
    "EdgeDiff",
    "GraphDiff",
]
