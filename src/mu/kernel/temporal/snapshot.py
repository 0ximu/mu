"""Snapshot management for temporal layer.

Provides SnapshotManager for creating and managing temporal snapshots,
and MUbaseSnapshot for read-only views at specific points in time.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.models import Edge, Node
from mu.kernel.schema import TEMPORAL_SCHEMA_SQL, EdgeType, NodeType
from mu.kernel.temporal.git import GitIntegration
from mu.kernel.temporal.models import (
    ChangeType,
    EdgeChange,
    NodeChange,
    Snapshot,
)

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


def _compute_body_hash(properties: dict[str, Any]) -> str:
    """Compute a hash of node properties for change detection."""
    # Sort keys for consistent hashing
    serialized = json.dumps(properties, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


class SnapshotManager:
    """Manages temporal snapshots for a MUbase database.

    Creates point-in-time captures of the code graph linked to git commits,
    tracking changes (added/removed/modified nodes and edges) between snapshots.
    """

    def __init__(self, mubase: MUbase, repo_path: Path | None = None) -> None:
        """Initialize snapshot manager.

        Args:
            mubase: The MUbase database to manage snapshots for.
            repo_path: Path to git repository. If None, uses mubase.path parent.
        """
        self._db = mubase
        self._temporal_initialized = False

        # Initialize git integration
        if repo_path is None:
            repo_path = mubase.path.parent
        try:
            self._git = GitIntegration(repo_path)
        except Exception:
            self._git = None  # type: ignore[assignment]

    @property
    def git(self) -> GitIntegration | None:
        """Get git integration (may be None if not in a git repo)."""
        return self._git

    @property
    def db(self) -> MUbase:
        """Get the underlying MUbase database."""
        return self._db

    def _ensure_temporal_schema(self) -> None:
        """Create temporal tables if they don't exist (lazy initialization)."""
        if self._temporal_initialized:
            return

        try:
            self._db.conn.execute("SELECT 1 FROM snapshots LIMIT 1")
            self._temporal_initialized = True
        except duckdb.CatalogException:
            # Tables don't exist, create them
            self._db.conn.execute(TEMPORAL_SCHEMA_SQL)
            self._temporal_initialized = True

    def create_snapshot(
        self,
        commit_hash: str | None = None,
        force: bool = False,
    ) -> Snapshot:
        """Create a snapshot of the current graph state.

        Args:
            commit_hash: Git commit to link this snapshot to.
                        If None, uses current HEAD.
            force: If True, recreate snapshot even if one exists for this commit.

        Returns:
            The created Snapshot.

        Raises:
            ValueError: If snapshot already exists for commit and force=False.
        """
        self._ensure_temporal_schema()

        # Get commit info
        if commit_hash is None and self._git:
            commit_hash = self._git.get_current_commit()
        elif commit_hash is None:
            commit_hash = f"manual-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Check if snapshot already exists
        existing = self.get_snapshot(commit_hash)
        if existing and not force:
            raise ValueError(f"Snapshot already exists for commit {commit_hash}")

        if existing and force:
            # Delete existing snapshot and its history
            self._delete_snapshot(existing.id)

        # Get commit metadata
        commit_message = None
        commit_author = None
        commit_date = None

        if self._git:
            try:
                info = self._git.get_commit_info(commit_hash)
                commit_message = info.message
                commit_author = info.author
                commit_date = info.date
            except Exception:
                pass  # Use defaults if git info unavailable

        # Get current graph stats
        node_result = self._db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
        node_count = node_result[0] if node_result else 0

        edge_result = self._db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()
        edge_count = edge_result[0] if edge_result else 0

        # Find parent snapshot
        parent_id = self._find_parent_snapshot(commit_hash)

        # Calculate delta if there's a parent
        delta = self._calculate_delta(parent_id)

        # Create snapshot
        snapshot = Snapshot(
            id=str(uuid.uuid4()),
            commit_hash=commit_hash,
            commit_message=commit_message,
            commit_author=commit_author,
            commit_date=commit_date,
            parent_id=parent_id,
            node_count=node_count,
            edge_count=edge_count,
            nodes_added=delta.get("nodes_added", node_count if not parent_id else 0),
            nodes_removed=delta.get("nodes_removed", 0),
            nodes_modified=delta.get("nodes_modified", 0),
            edges_added=delta.get("edges_added", edge_count if not parent_id else 0),
            edges_removed=delta.get("edges_removed", 0),
            created_at=datetime.now(),
        )

        # Insert snapshot
        self._db.conn.execute(
            """
            INSERT INTO snapshots
            (id, commit_hash, commit_message, commit_author, commit_date,
             parent_id, node_count, edge_count, nodes_added, nodes_removed,
             nodes_modified, edges_added, edges_removed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            snapshot.to_tuple(),
        )

        # Record node and edge history
        self._record_history(snapshot, delta)

        return snapshot

    def _find_parent_snapshot(self, commit_hash: str) -> str | None:
        """Find the parent snapshot for a commit."""
        if not self._git:
            # Without git, use the most recent snapshot
            row = self._db.conn.execute(
                "SELECT id FROM snapshots ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None

        # Get parent commit and look for its snapshot
        parent_commit = self._git.get_parent_commit(commit_hash)
        if not parent_commit:
            return None

        row = self._db.conn.execute(
            "SELECT id FROM snapshots WHERE commit_hash = ?",
            [parent_commit],
        ).fetchone()

        if row:
            return str(row[0])

        # If no direct parent snapshot, find nearest ancestor
        # Get all snapshots ordered by date
        rows = self._db.conn.execute(
            "SELECT id, commit_hash FROM snapshots ORDER BY commit_date DESC"
        ).fetchall()

        for snapshot_id, snapshot_commit in rows:
            if self._git.is_ancestor(snapshot_commit, commit_hash):
                return str(snapshot_id)

        return None

    def _calculate_delta(self, parent_id: str | None) -> dict[str, Any]:
        """Calculate changes since parent snapshot."""
        if not parent_id:
            return {
                "nodes_added": 0,
                "nodes_removed": 0,
                "nodes_modified": 0,
                "edges_added": 0,
                "edges_removed": 0,
                "node_changes": [],
                "edge_changes": [],
            }

        # Get parent node states from history
        parent_nodes: dict[str, str] = {}  # node_id -> body_hash
        for row in self._db.conn.execute(
            """
            SELECT node_id, body_hash FROM node_history
            WHERE snapshot_id = ? AND change_type != ?
            """,
            [parent_id, ChangeType.REMOVED.value],
        ).fetchall():
            parent_nodes[row[0]] = row[1] or ""

        # Get current nodes
        current_nodes: dict[str, tuple[str, dict[str, Any]]] = {}  # node_id -> (hash, props)
        for row in self._db.conn.execute("SELECT id, properties FROM nodes").fetchall():
            props = row[1]
            if isinstance(props, str):
                props = json.loads(props)
            elif props is None:
                props = {}
            body_hash = _compute_body_hash(props)
            current_nodes[row[0]] = (body_hash, props)

        # Calculate node changes
        node_changes: list[dict[str, Any]] = []
        nodes_added = 0
        nodes_modified = 0
        nodes_removed = 0

        # Check for added and modified
        for node_id, (body_hash, props) in current_nodes.items():
            if node_id not in parent_nodes:
                node_changes.append(
                    {
                        "node_id": node_id,
                        "change_type": ChangeType.ADDED,
                        "body_hash": body_hash,
                        "properties": props,
                    }
                )
                nodes_added += 1
            elif parent_nodes[node_id] != body_hash:
                node_changes.append(
                    {
                        "node_id": node_id,
                        "change_type": ChangeType.MODIFIED,
                        "body_hash": body_hash,
                        "properties": props,
                    }
                )
                nodes_modified += 1
            else:
                # Unchanged - still record for history
                node_changes.append(
                    {
                        "node_id": node_id,
                        "change_type": ChangeType.UNCHANGED,
                        "body_hash": body_hash,
                        "properties": props,
                    }
                )

        # Check for removed
        for node_id in parent_nodes:
            if node_id not in current_nodes:
                node_changes.append(
                    {
                        "node_id": node_id,
                        "change_type": ChangeType.REMOVED,
                        "body_hash": None,
                        "properties": {},
                    }
                )
                nodes_removed += 1

        # Get parent edge states
        parent_edges: set[str] = set()
        for row in self._db.conn.execute(
            """
            SELECT edge_id FROM edge_history
            WHERE snapshot_id = ? AND change_type != ?
            """,
            [parent_id, ChangeType.REMOVED.value],
        ).fetchall():
            parent_edges.add(row[0])

        # Get current edges
        current_edges: dict[str, tuple[str, str, str, dict[str, Any]]] = {}
        for row in self._db.conn.execute(
            "SELECT id, source_id, target_id, type, properties FROM edges"
        ).fetchall():
            props = row[4]
            if isinstance(props, str):
                props = json.loads(props)
            elif props is None:
                props = {}
            current_edges[row[0]] = (row[1], row[2], row[3], props)

        # Calculate edge changes
        edge_changes: list[dict[str, Any]] = []
        edges_added = 0
        edges_removed = 0

        for edge_id, (source_id, target_id, edge_type, props) in current_edges.items():
            if edge_id not in parent_edges:
                edge_changes.append(
                    {
                        "edge_id": edge_id,
                        "change_type": ChangeType.ADDED,
                        "source_id": source_id,
                        "target_id": target_id,
                        "edge_type": edge_type,
                        "properties": props,
                    }
                )
                edges_added += 1
            else:
                edge_changes.append(
                    {
                        "edge_id": edge_id,
                        "change_type": ChangeType.UNCHANGED,
                        "source_id": source_id,
                        "target_id": target_id,
                        "edge_type": edge_type,
                        "properties": props,
                    }
                )

        for edge_id in parent_edges:
            if edge_id not in current_edges:
                edge_changes.append(
                    {
                        "edge_id": edge_id,
                        "change_type": ChangeType.REMOVED,
                        "source_id": "",
                        "target_id": "",
                        "edge_type": "",
                        "properties": {},
                    }
                )
                edges_removed += 1

        return {
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "nodes_modified": nodes_modified,
            "edges_added": edges_added,
            "edges_removed": edges_removed,
            "node_changes": node_changes,
            "edge_changes": edge_changes,
        }

    def _record_history(self, snapshot: Snapshot, delta: dict[str, Any]) -> None:
        """Record node and edge changes in history tables."""
        # Record node history
        node_changes = delta.get("node_changes", [])
        if not node_changes:
            # First snapshot - record all current nodes as added
            for row in self._db.conn.execute("SELECT id, properties FROM nodes").fetchall():
                props = row[1]
                if isinstance(props, str):
                    props = json.loads(props)
                elif props is None:
                    props = {}

                change = NodeChange(
                    id=str(uuid.uuid4()),
                    snapshot_id=snapshot.id,
                    node_id=row[0],
                    change_type=ChangeType.ADDED,
                    body_hash=_compute_body_hash(props),
                    properties=props,
                )
                self._db.conn.execute(
                    """
                    INSERT INTO node_history
                    (id, snapshot_id, node_id, change_type, body_hash, properties)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    change.to_tuple(),
                )
        else:
            for change_data in node_changes:
                change = NodeChange(
                    id=str(uuid.uuid4()),
                    snapshot_id=snapshot.id,
                    node_id=change_data["node_id"],
                    change_type=change_data["change_type"],
                    body_hash=change_data.get("body_hash"),
                    properties=change_data.get("properties", {}),
                )
                self._db.conn.execute(
                    """
                    INSERT INTO node_history
                    (id, snapshot_id, node_id, change_type, body_hash, properties)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    change.to_tuple(),
                )

        # Record edge history
        edge_changes = delta.get("edge_changes", [])
        if not edge_changes:
            # First snapshot - record all current edges as added
            for row in self._db.conn.execute(
                "SELECT id, source_id, target_id, type, properties FROM edges"
            ).fetchall():
                props = row[4]
                if isinstance(props, str):
                    props = json.loads(props)
                elif props is None:
                    props = {}

                edge_change = EdgeChange(
                    id=str(uuid.uuid4()),
                    snapshot_id=snapshot.id,
                    edge_id=row[0],
                    change_type=ChangeType.ADDED,
                    source_id=row[1],
                    target_id=row[2],
                    edge_type=row[3],
                    properties=props,
                )
                self._db.conn.execute(
                    """
                    INSERT INTO edge_history
                    (id, snapshot_id, edge_id, change_type, source_id, target_id, edge_type, properties)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    edge_change.to_tuple(),
                )
        else:
            for change_data in edge_changes:
                edge_change = EdgeChange(
                    id=str(uuid.uuid4()),
                    snapshot_id=snapshot.id,
                    edge_id=change_data["edge_id"],
                    change_type=change_data["change_type"],
                    source_id=change_data["source_id"],
                    target_id=change_data["target_id"],
                    edge_type=change_data["edge_type"],
                    properties=change_data.get("properties", {}),
                )
                self._db.conn.execute(
                    """
                    INSERT INTO edge_history
                    (id, snapshot_id, edge_id, change_type, source_id, target_id, edge_type, properties)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    edge_change.to_tuple(),
                )

    def _delete_snapshot(self, snapshot_id: str) -> None:
        """Delete a snapshot and its history."""
        self._db.conn.execute(
            "DELETE FROM node_history WHERE snapshot_id = ?",
            [snapshot_id],
        )
        self._db.conn.execute(
            "DELETE FROM edge_history WHERE snapshot_id = ?",
            [snapshot_id],
        )
        self._db.conn.execute(
            "DELETE FROM snapshots WHERE id = ?",
            [snapshot_id],
        )

    def get_snapshot(self, commit_hash: str) -> Snapshot | None:
        """Get a snapshot by commit hash.

        Args:
            commit_hash: Git commit hash to look up.

        Returns:
            Snapshot if found, None otherwise.
        """
        self._ensure_temporal_schema()

        row = self._db.conn.execute(
            "SELECT * FROM snapshots WHERE commit_hash = ?",
            [commit_hash],
        ).fetchone()

        return Snapshot.from_row(row) if row else None

    def get_snapshot_by_id(self, snapshot_id: str) -> Snapshot | None:
        """Get a snapshot by its ID.

        Args:
            snapshot_id: Snapshot UUID.

        Returns:
            Snapshot if found, None otherwise.
        """
        self._ensure_temporal_schema()

        row = self._db.conn.execute(
            "SELECT * FROM snapshots WHERE id = ?",
            [snapshot_id],
        ).fetchone()

        return Snapshot.from_row(row) if row else None

    def list_snapshots(self, limit: int = 100) -> list[Snapshot]:
        """List all snapshots in reverse chronological order.

        Args:
            limit: Maximum number of snapshots to return.

        Returns:
            List of Snapshots.
        """
        self._ensure_temporal_schema()

        rows = self._db.conn.execute(
            "SELECT * FROM snapshots ORDER BY commit_date DESC LIMIT ?",
            [limit],
        ).fetchall()

        return [Snapshot.from_row(row) for row in rows]

    def build_with_history(
        self,
        commits: list[str] | None = None,
        since: datetime | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[Snapshot]:
        """Build graph history from git commits.

        Processes commits chronologically, creating a snapshot for each.
        Uses git worktree to safely checkout each commit.

        Args:
            commits: List of commit hashes to process. If None, auto-discovers.
            since: Only process commits after this date.
            on_progress: Callback (current, total) for progress reporting.

        Returns:
            List of created Snapshots.

        Note:
            This is a complex operation that requires importing and parsing
            at each commit. Consider using for initial history build only.
        """
        if not self._git:
            raise ValueError("Git integration required for build_with_history")

        self._ensure_temporal_schema()

        # Get commits to process
        if commits is None:
            commits = self._git.get_commits(since=since, limit=100)
            # Reverse to chronological order
            commits = list(reversed(commits))

        if not commits:
            return []

        snapshots: list[Snapshot] = []
        total = len(commits)

        # Import here to avoid circular import
        from mu.config import MUConfig
        from mu.diff.git_utils import GitWorktreeManager
        from mu.parser.base import parse_file
        from mu.scanner import SUPPORTED_LANGUAGES, scan_codebase

        config = MUConfig()

        with GitWorktreeManager(self._git.repo_root) as manager:
            for i, commit_hash in enumerate(commits):
                if on_progress:
                    on_progress(i + 1, total)

                # Skip if snapshot already exists
                existing = self.get_snapshot(commit_hash)
                if existing:
                    snapshots.append(existing)
                    continue

                try:
                    with manager.checkout(commit_hash) as worktree_path:
                        # Scan and parse codebase at this commit
                        scan_result = scan_codebase(worktree_path, config)

                        modules = []
                        for file_info in scan_result.files:
                            if file_info.language not in SUPPORTED_LANGUAGES:
                                continue

                            parsed = parse_file(
                                Path(worktree_path / file_info.path),
                                file_info.language,
                            )
                            if parsed.success and parsed.module:
                                modules.append(parsed.module)

                        # Rebuild graph for this commit
                        self._db.build(modules, worktree_path)

                        # Create snapshot
                        snapshot = self.create_snapshot(commit_hash)
                        snapshots.append(snapshot)

                except Exception as e:
                    # Log error but continue with other commits
                    import warnings

                    warnings.warn(
                        f"Failed to process commit {commit_hash}: {e}",
                        UserWarning,
                        stacklevel=2,
                    )

        return snapshots


class MUbaseSnapshot:
    """Read-only view of MUbase at a specific point in time.

    Provides query methods that return the state of the graph
    as it existed at a particular snapshot.
    """

    def __init__(self, mubase: MUbase, snapshot: Snapshot) -> None:
        """Initialize temporal view.

        Args:
            mubase: The MUbase database.
            snapshot: The snapshot representing the point in time.
        """
        self._db = mubase
        self._snapshot = snapshot

    @property
    def snapshot(self) -> Snapshot:
        """Get the underlying snapshot."""
        return self._snapshot

    def get_node(self, node_id: str) -> Node | None:
        """Get a node as it existed at snapshot time.

        Args:
            node_id: The node ID to retrieve.

        Returns:
            Node if it existed at snapshot time, None otherwise.
        """
        row = self._db.conn.execute(
            """
            SELECT n.id, n.type, n.name, n.qualified_name, n.file_path,
                   n.line_start, n.line_end, nh.properties, n.complexity
            FROM node_history nh
            JOIN nodes n ON n.id = nh.node_id
            WHERE nh.snapshot_id = ? AND nh.node_id = ? AND nh.change_type != ?
            """,
            [self._snapshot.id, node_id, ChangeType.REMOVED.value],
        ).fetchone()

        return Node.from_row(row) if row else None

    def get_nodes(
        self,
        node_type: NodeType | None = None,
        file_path: str | None = None,
    ) -> list[Node]:
        """Get nodes as they existed at snapshot time.

        Args:
            node_type: Filter by node type.
            file_path: Filter by file path.

        Returns:
            List of nodes that existed at snapshot time.
        """
        conditions = ["nh.snapshot_id = ?", "nh.change_type != ?"]
        params: list[Any] = [self._snapshot.id, ChangeType.REMOVED.value]

        if node_type:
            conditions.append("n.type = ?")
            params.append(node_type.value)

        if file_path:
            conditions.append("n.file_path = ?")
            params.append(file_path)

        where_clause = " AND ".join(conditions)

        rows = self._db.conn.execute(
            f"""
            SELECT n.id, n.type, n.name, n.qualified_name, n.file_path,
                   n.line_start, n.line_end, nh.properties, n.complexity
            FROM node_history nh
            JOIN nodes n ON n.id = nh.node_id
            WHERE {where_clause}
            """,
            params,
        ).fetchall()

        return [Node.from_row(row) for row in rows]

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        edge_type: EdgeType | None = None,
    ) -> list[Edge]:
        """Get edges as they existed at snapshot time.

        Args:
            source_id: Filter by source node ID.
            target_id: Filter by target node ID.
            edge_type: Filter by edge type.

        Returns:
            List of edges that existed at snapshot time.
        """
        conditions = ["eh.snapshot_id = ?", "eh.change_type != ?"]
        params: list[Any] = [self._snapshot.id, ChangeType.REMOVED.value]

        if source_id:
            conditions.append("eh.source_id = ?")
            params.append(source_id)

        if target_id:
            conditions.append("eh.target_id = ?")
            params.append(target_id)

        if edge_type:
            conditions.append("eh.edge_type = ?")
            params.append(edge_type.value)

        where_clause = " AND ".join(conditions)

        rows = self._db.conn.execute(
            f"""
            SELECT eh.edge_id, eh.source_id, eh.target_id, eh.edge_type, eh.properties
            FROM edge_history eh
            WHERE {where_clause}
            """,
            params,
        ).fetchall()

        return [Edge.from_row(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        """Get statistics for this snapshot.

        Returns:
            Dictionary with node/edge counts and metadata.
        """
        return {
            "snapshot_id": self._snapshot.id,
            "commit_hash": self._snapshot.commit_hash,
            "commit_date": (
                self._snapshot.commit_date.isoformat() if self._snapshot.commit_date else None
            ),
            "node_count": self._snapshot.node_count,
            "edge_count": self._snapshot.edge_count,
            "nodes_added": self._snapshot.nodes_added,
            "nodes_removed": self._snapshot.nodes_removed,
            "nodes_modified": self._snapshot.nodes_modified,
            "edges_added": self._snapshot.edges_added,
            "edges_removed": self._snapshot.edges_removed,
        }


__all__ = [
    "SnapshotManager",
    "MUbaseSnapshot",
]
