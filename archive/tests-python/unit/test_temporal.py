"""Tests for the temporal layer - git-linked snapshots and time-travel queries."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mu.kernel import MUbase
from mu.kernel.models import Edge, Node
from mu.kernel.schema import NodeType
from mu.kernel.temporal import (
    ChangeType,
    CommitInfo,
    EdgeChange,
    EdgeDiff,
    GitError,
    GitIntegration,
    GraphDiff,
    HistoryTracker,
    MUbaseSnapshot,
    NodeChange,
    NodeDiff,
    Snapshot,
    SnapshotManager,
    TemporalDiffer,
)


# =============================================================================
# Snapshot Model Tests
# =============================================================================


class TestSnapshot:
    """Tests for Snapshot dataclass."""

    def test_snapshot_creation(self) -> None:
        """Test creating a Snapshot instance."""
        snapshot = Snapshot(
            id="test-id",
            commit_hash="abc123def456",
            commit_message="Test commit",
            commit_author="Test Author",
            commit_date=datetime(2024, 1, 15, 10, 30),
            node_count=100,
            edge_count=50,
        )

        assert snapshot.id == "test-id"
        assert snapshot.commit_hash == "abc123def456"
        assert snapshot.commit_message == "Test commit"
        assert snapshot.node_count == 100

    def test_snapshot_short_hash(self) -> None:
        """Test short_hash property."""
        snapshot = Snapshot(id="test", commit_hash="abc123def456789")
        assert snapshot.short_hash == "abc123de"

    def test_snapshot_total_changes(self) -> None:
        """Test total_changes property."""
        snapshot = Snapshot(
            id="test",
            commit_hash="abc123",
            nodes_added=10,
            nodes_removed=5,
            nodes_modified=3,
        )
        assert snapshot.total_changes == 18

    def test_snapshot_to_dict(self) -> None:
        """Test to_dict serialization."""
        snapshot = Snapshot(
            id="test-id",
            commit_hash="abc123",
            node_count=50,
        )
        d = snapshot.to_dict()

        assert d["id"] == "test-id"
        assert d["commit_hash"] == "abc123"
        assert d["node_count"] == 50

    def test_snapshot_from_row(self) -> None:
        """Test creating Snapshot from database row."""
        row = (
            "uuid-1",  # id
            "abc123",  # commit_hash
            "Test message",  # commit_message
            "Author",  # commit_author
            "2024-01-15T10:30:00",  # commit_date
            None,  # parent_id
            100,  # node_count
            50,  # edge_count
            10,  # nodes_added
            5,  # nodes_removed
            3,  # nodes_modified
            8,  # edges_added
            2,  # edges_removed
            "2024-01-15T10:30:00",  # created_at
        )

        snapshot = Snapshot.from_row(row)
        assert snapshot.id == "uuid-1"
        assert snapshot.commit_hash == "abc123"
        assert snapshot.commit_message == "Test message"
        assert snapshot.node_count == 100


# =============================================================================
# NodeChange Model Tests
# =============================================================================


class TestNodeChange:
    """Tests for NodeChange dataclass."""

    def test_node_change_creation(self) -> None:
        """Test creating a NodeChange instance."""
        change = NodeChange(
            id="change-1",
            snapshot_id="snap-1",
            node_id="node-1",
            change_type=ChangeType.ADDED,
            body_hash="hash123",
            properties={"name": "test"},
        )

        assert change.id == "change-1"
        assert change.change_type == ChangeType.ADDED
        assert change.properties["name"] == "test"

    def test_node_change_to_dict(self) -> None:
        """Test to_dict serialization."""
        change = NodeChange(
            id="change-1",
            snapshot_id="snap-1",
            node_id="node-1",
            change_type=ChangeType.MODIFIED,
        )
        d = change.to_dict()

        assert d["id"] == "change-1"
        assert d["change_type"] == "modified"

    def test_node_change_to_tuple(self) -> None:
        """Test to_tuple for database insertion."""
        change = NodeChange(
            id="change-1",
            snapshot_id="snap-1",
            node_id="node-1",
            change_type=ChangeType.ADDED,
            body_hash="hash",
            properties={"foo": "bar"},
        )
        t = change.to_tuple()

        assert t[0] == "change-1"
        assert t[1] == "snap-1"
        assert t[2] == "node-1"
        assert t[3] == "added"


# =============================================================================
# GraphDiff Model Tests
# =============================================================================


class TestGraphDiff:
    """Tests for GraphDiff dataclass."""

    def test_graph_diff_creation(self) -> None:
        """Test creating a GraphDiff instance."""
        from_snap = Snapshot(id="s1", commit_hash="abc")
        to_snap = Snapshot(id="s2", commit_hash="def")

        diff = GraphDiff(from_snapshot=from_snap, to_snapshot=to_snap)

        assert diff.from_snapshot.id == "s1"
        assert diff.to_snapshot.id == "s2"
        assert diff.nodes_added == []
        assert diff.nodes_removed == []

    def test_graph_diff_stats(self) -> None:
        """Test stats property."""
        from_snap = Snapshot(id="s1", commit_hash="abc")
        to_snap = Snapshot(id="s2", commit_hash="def")

        diff = GraphDiff(
            from_snapshot=from_snap,
            to_snapshot=to_snap,
            nodes_added=[NodeDiff("n1", "name", "function", ChangeType.ADDED)],
            nodes_removed=[NodeDiff("n2", "name", "class", ChangeType.REMOVED)],
            nodes_modified=[NodeDiff("n3", "name", "module", ChangeType.MODIFIED)],
        )

        stats = diff.stats
        assert stats["nodes_added"] == 1
        assert stats["nodes_removed"] == 1
        assert stats["nodes_modified"] == 1
        assert stats["total_changes"] == 3

    def test_graph_diff_has_changes(self) -> None:
        """Test has_changes property."""
        from_snap = Snapshot(id="s1", commit_hash="abc")
        to_snap = Snapshot(id="s2", commit_hash="def")

        # No changes
        diff1 = GraphDiff(from_snapshot=from_snap, to_snapshot=to_snap)
        assert not diff1.has_changes

        # With changes
        diff2 = GraphDiff(
            from_snapshot=from_snap,
            to_snapshot=to_snap,
            nodes_added=[NodeDiff("n1", "name", "function", ChangeType.ADDED)],
        )
        assert diff2.has_changes


# =============================================================================
# GitIntegration Tests
# =============================================================================


class TestGitIntegration:
    """Tests for GitIntegration class."""

    def test_commit_info_short_hash(self) -> None:
        """Test CommitInfo short_hash property."""
        info = CommitInfo(
            hash="abc123def456789",
            message="Test",
            author="Author",
            date=datetime.now(),
        )
        assert info.short_hash == "abc123de"

    def test_commit_info_to_dict(self) -> None:
        """Test CommitInfo to_dict serialization."""
        info = CommitInfo(
            hash="abc123",
            message="Test commit",
            author="Test Author",
            date=datetime(2024, 1, 15),
        )
        d = info.to_dict()

        assert d["hash"] == "abc123"
        assert d["message"] == "Test commit"
        assert d["author"] == "Test Author"

    @patch("subprocess.run")
    def test_git_integration_not_a_repo(self, mock_run: MagicMock) -> None:
        """Test error when path is not in a git repository."""
        import subprocess
        # Simulate git command failure (non-git directory)
        mock_run.side_effect = subprocess.CalledProcessError(
            128, ["git", "rev-parse", "--show-toplevel"], stderr="Not a git repo"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(GitError):
                GitIntegration(Path(tmpdir))


# =============================================================================
# SnapshotManager Tests
# =============================================================================


class TestSnapshotManager:
    """Tests for SnapshotManager class."""

    @pytest.fixture
    def db_with_data(self) -> MUbase:
        """Create a MUbase with test data."""
        db = MUbase(":memory:")

        # Add some test nodes
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
        )
        node2 = Node(
            id="cls:test.py:MyClass",
            type=NodeType.CLASS,
            name="MyClass",
            file_path="test.py",
        )
        db.add_node(node1)
        db.add_node(node2)

        return db

    def test_manager_creation(self, db_with_data: MUbase) -> None:
        """Test creating SnapshotManager."""
        with patch.object(GitIntegration, "__init__", return_value=None):
            manager = SnapshotManager(db_with_data)
            assert manager._db is db_with_data

    def test_list_snapshots_empty(self, db_with_data: MUbase) -> None:
        """Test listing snapshots when none exist."""
        with patch.object(GitIntegration, "__init__", return_value=None):
            manager = SnapshotManager(db_with_data)
            manager._git = None  # type: ignore
            snapshots = manager.list_snapshots()
            assert snapshots == []

    def test_get_snapshot_not_found(self, db_with_data: MUbase) -> None:
        """Test getting non-existent snapshot."""
        with patch.object(GitIntegration, "__init__", return_value=None):
            manager = SnapshotManager(db_with_data)
            manager._git = None  # type: ignore
            snapshot = manager.get_snapshot("nonexistent")
            assert snapshot is None


# =============================================================================
# HistoryTracker Tests
# =============================================================================


class TestHistoryTracker:
    """Tests for HistoryTracker class."""

    @pytest.fixture
    def db_with_history(self) -> MUbase:
        """Create a MUbase with temporal history data."""
        db = MUbase(":memory:")

        # Initialize temporal schema
        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL
        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add a test node
        node = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
        )
        db.add_node(node)

        # Add a snapshot
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, commit_message, commit_author,
                commit_date, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap-1",
                "abc123",
                "Test commit",
                "Author",
                "2024-01-15T10:00:00",
                1,
                0,
                "2024-01-15T10:00:00",
            ),
        )

        # Add node history
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "hist-1",
                "snap-1",
                "fn:test.py:func1",
                "added",
                "hash123",
                "{}",
            ),
        )

        return db

    def test_history_returns_changes(self, db_with_history: MUbase) -> None:
        """Test getting history for a node."""
        tracker = HistoryTracker(db_with_history)
        changes = tracker.history("fn:test.py:func1")

        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.ADDED

    def test_history_with_limit(self, db_with_history: MUbase) -> None:
        """Test history respects limit."""
        tracker = HistoryTracker(db_with_history)
        changes = tracker.history("fn:test.py:func1", limit=1)

        assert len(changes) <= 1

    def test_first_appearance(self, db_with_history: MUbase) -> None:
        """Test finding first appearance of a node."""
        tracker = HistoryTracker(db_with_history)
        first = tracker.first_appearance("fn:test.py:func1")

        assert first is not None
        assert first.change_type == ChangeType.ADDED

    def test_node_exists_at(self, db_with_history: MUbase) -> None:
        """Test checking if node exists at snapshot."""
        tracker = HistoryTracker(db_with_history)

        # Node exists
        exists = tracker.node_exists_at("fn:test.py:func1", "snap-1")
        assert exists is True

        # Node doesn't exist
        not_exists = tracker.node_exists_at("nonexistent", "snap-1")
        assert not_exists is False


# =============================================================================
# MUbaseSnapshot Tests
# =============================================================================


class TestMUbaseSnapshot:
    """Tests for MUbaseSnapshot class."""

    @pytest.fixture
    def temporal_db(self) -> MUbase:
        """Create a MUbase with temporal data."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL
        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add node
        node = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
            complexity=10,
        )
        db.add_node(node)

        # Add snapshot
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("snap-1", "abc123", 1, 0, "2024-01-15T10:00:00"),
        )

        # Add node history for snapshot
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, properties)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("hist-1", "snap-1", "fn:test.py:func1", "added", "{}"),
        )

        return db

    def test_snapshot_stats(self, temporal_db: MUbase) -> None:
        """Test getting stats from temporal snapshot."""
        snapshot = Snapshot(
            id="snap-1",
            commit_hash="abc123",
            node_count=1,
            edge_count=0,
        )
        view = MUbaseSnapshot(temporal_db, snapshot)

        stats = view.stats()
        assert stats["node_count"] == 1
        assert stats["commit_hash"] == "abc123"


# =============================================================================
# TemporalDiffer Tests
# =============================================================================


class TestTemporalDiffer:
    """Tests for TemporalDiffer class."""

    def test_node_diff_creation(self) -> None:
        """Test creating NodeDiff."""
        diff = NodeDiff(
            node_id="n1",
            name="test",
            node_type="function",
            change_type=ChangeType.ADDED,
        )

        assert diff.node_id == "n1"
        assert diff.change_type == ChangeType.ADDED

    def test_node_diff_to_dict(self) -> None:
        """Test NodeDiff serialization."""
        diff = NodeDiff(
            node_id="n1",
            name="test",
            node_type="function",
            change_type=ChangeType.MODIFIED,
            old_properties={"complexity": 5},
            new_properties={"complexity": 10},
        )

        d = diff.to_dict()
        assert d["node_id"] == "n1"
        assert d["change_type"] == "modified"

    def test_edge_diff_creation(self) -> None:
        """Test creating EdgeDiff."""
        diff = EdgeDiff(
            edge_id="e1",
            source_id="n1",
            target_id="n2",
            edge_type="contains",
            change_type=ChangeType.ADDED,
        )

        assert diff.edge_id == "e1"
        assert diff.change_type == ChangeType.ADDED


# =============================================================================
# ChangeType Tests
# =============================================================================


class TestChangeType:
    """Tests for ChangeType enum."""

    def test_change_types_defined(self) -> None:
        """Test all change types are defined."""
        assert ChangeType.ADDED.value == "added"
        assert ChangeType.MODIFIED.value == "modified"
        assert ChangeType.UNCHANGED.value == "unchanged"
        assert ChangeType.REMOVED.value == "removed"

    def test_change_type_from_value(self) -> None:
        """Test creating ChangeType from string value."""
        assert ChangeType("added") == ChangeType.ADDED
        assert ChangeType("modified") == ChangeType.MODIFIED


# =============================================================================
# MUQL Temporal Tests
# =============================================================================


class TestMUQLTemporal:
    """Tests for MUQL temporal query parsing."""

    def test_parse_history_query(self) -> None:
        """Test parsing HISTORY query."""
        from mu.kernel.muql.parser import parse

        query = parse("HISTORY OF MUbase")
        assert query.query_type.value == "history"
        assert query.target.name == "MUbase"

    def test_parse_history_with_limit(self) -> None:
        """Test parsing HISTORY query with LIMIT."""
        from mu.kernel.muql.parser import parse

        query = parse("HISTORY OF MUbase LIMIT 10")
        assert query.query_type.value == "history"
        assert query.limit == 10

    def test_parse_blame_query(self) -> None:
        """Test parsing BLAME query."""
        from mu.kernel.muql.parser import parse

        query = parse("BLAME MUbase")
        assert query.query_type.value == "blame"
        assert query.target.name == "MUbase"

    def test_parse_select_at(self) -> None:
        """Test parsing SELECT with AT clause."""
        from mu.kernel.muql.parser import parse

        query = parse('SELECT * FROM functions AT "abc123"')
        assert query.query_type.value == "select"
        assert query.temporal is not None
        assert query.temporal.clause_type == "at"
        assert query.temporal.commit1 == "abc123"

    def test_parse_select_between(self) -> None:
        """Test parsing SELECT with BETWEEN clause."""
        from mu.kernel.muql.parser import parse

        query = parse('SELECT * FROM functions BETWEEN "abc123" AND "def456"')
        assert query.query_type.value == "select"
        assert query.temporal is not None
        assert query.temporal.clause_type == "between"
        assert query.temporal.commit1 == "abc123"
        assert query.temporal.commit2 == "def456"


class TestMUQLTemporalPlanner:
    """Tests for MUQL temporal query planning."""

    def test_plan_history_query(self) -> None:
        """Test planning HISTORY query."""
        from mu.kernel.muql.parser import parse
        from mu.kernel.muql.planner import plan_query

        query = parse("HISTORY OF MUbase LIMIT 20")
        plan = plan_query(query)

        assert plan.plan_type.value == "temporal"
        assert plan.operation == "history"
        assert plan.target_node == "MUbase"
        assert plan.limit == 20

    def test_plan_blame_query(self) -> None:
        """Test planning BLAME query."""
        from mu.kernel.muql.parser import parse
        from mu.kernel.muql.planner import plan_query

        query = parse("BLAME MUbase")
        plan = plan_query(query)

        assert plan.plan_type.value == "temporal"
        assert plan.operation == "blame"
        assert plan.target_node == "MUbase"

    def test_plan_select_at(self) -> None:
        """Test planning SELECT with AT clause."""
        from mu.kernel.muql.parser import parse
        from mu.kernel.muql.planner import plan_query

        query = parse('SELECT * FROM functions AT "abc123"')
        plan = plan_query(query)

        assert plan.plan_type.value == "temporal"
        assert plan.operation == "at"
        assert plan.commit == "abc123"

    def test_plan_select_between(self) -> None:
        """Test planning SELECT with BETWEEN clause."""
        from mu.kernel.muql.parser import parse
        from mu.kernel.muql.planner import plan_query

        query = parse('SELECT * FROM functions BETWEEN "abc123" AND "def456"')
        plan = plan_query(query)

        assert plan.plan_type.value == "temporal"
        assert plan.operation == "between"
        assert plan.commit == "abc123"
        assert plan.commit2 == "def456"


# =============================================================================
# Additional EdgeChange Model Tests
# =============================================================================


class TestEdgeChange:
    """Tests for EdgeChange dataclass."""

    def test_edge_change_creation(self) -> None:
        """Test creating an EdgeChange instance."""
        change = EdgeChange(
            id="edge-change-1",
            snapshot_id="snap-1",
            edge_id="edge-1",
            change_type=ChangeType.ADDED,
            source_id="node-1",
            target_id="node-2",
            edge_type="imports",
            properties={"weight": 1},
        )

        assert change.id == "edge-change-1"
        assert change.change_type == ChangeType.ADDED
        assert change.edge_type == "imports"

    def test_edge_change_to_dict(self) -> None:
        """Test EdgeChange to_dict serialization."""
        change = EdgeChange(
            id="ec-1",
            snapshot_id="snap-1",
            edge_id="edge-1",
            change_type=ChangeType.REMOVED,
            source_id="n1",
            target_id="n2",
            edge_type="contains",
        )
        d = change.to_dict()

        assert d["id"] == "ec-1"
        assert d["change_type"] == "removed"
        assert d["edge_type"] == "contains"

    def test_edge_change_to_tuple(self) -> None:
        """Test EdgeChange to_tuple for database insertion."""
        change = EdgeChange(
            id="ec-1",
            snapshot_id="snap-1",
            edge_id="edge-1",
            change_type=ChangeType.ADDED,
            source_id="n1",
            target_id="n2",
            edge_type="imports",
            properties={"key": "value"},
        )
        t = change.to_tuple()

        assert t[0] == "ec-1"
        assert t[1] == "snap-1"
        assert t[2] == "edge-1"
        assert t[3] == "added"

    def test_edge_change_from_row(self) -> None:
        """Test creating EdgeChange from database row."""
        row = (
            "ec-id",  # id
            "snap-id",  # snapshot_id
            "edge-id",  # edge_id
            "modified",  # change_type
            "source",  # source_id
            "target",  # target_id
            "inherits",  # edge_type
            '{"prop": 1}',  # properties (JSON string)
        )
        change = EdgeChange.from_row(row)

        assert change.id == "ec-id"
        assert change.change_type == ChangeType.MODIFIED
        assert change.edge_type == "inherits"
        assert change.properties == {"prop": 1}

    def test_edge_change_from_row_with_none_properties(self) -> None:
        """Test EdgeChange.from_row handles None properties."""
        row = ("ec-id", "snap-id", "edge-id", "added", "src", "tgt", "imports", None)
        change = EdgeChange.from_row(row)

        assert change.properties == {}


# =============================================================================
# Additional Snapshot Model Tests
# =============================================================================


class TestSnapshotAdditional:
    """Additional tests for Snapshot dataclass."""

    def test_snapshot_to_tuple(self) -> None:
        """Test Snapshot to_tuple for database insertion."""
        snapshot = Snapshot(
            id="snap-1",
            commit_hash="abc123",
            commit_message="Test",
            commit_author="Author",
            commit_date=datetime(2024, 1, 15, 10, 30),
            node_count=100,
            edge_count=50,
        )
        t = snapshot.to_tuple()

        assert t[0] == "snap-1"
        assert t[1] == "abc123"
        assert t[2] == "Test"

    def test_snapshot_from_row_with_invalid_dates(self) -> None:
        """Test Snapshot.from_row handles invalid dates gracefully."""
        row = (
            "uuid-1",
            "abc123",
            "Test message",
            "Author",
            "not-a-date",  # Invalid date
            None,
            100,
            50,
            10,
            5,
            3,
            8,
            2,
            "also-not-a-date",  # Invalid date
        )

        snapshot = Snapshot.from_row(row)
        assert snapshot.commit_date is None
        assert snapshot.created_at is None

    def test_snapshot_short_hash_empty(self) -> None:
        """Test short_hash with empty commit hash."""
        snapshot = Snapshot(id="test", commit_hash="")
        assert snapshot.short_hash == ""


# =============================================================================
# Additional NodeChange Model Tests
# =============================================================================


class TestNodeChangeAdditional:
    """Additional tests for NodeChange dataclass."""

    def test_node_change_from_row_basic(self) -> None:
        """Test NodeChange.from_row with basic row."""
        row = (
            "nc-id",
            "snap-id",
            "node-id",
            "added",
            "hash123",
            '{"name": "test"}',
        )
        change = NodeChange.from_row(row)

        assert change.id == "nc-id"
        assert change.change_type == ChangeType.ADDED
        assert change.properties == {"name": "test"}

    def test_node_change_from_row_extended(self) -> None:
        """Test NodeChange.from_row with extended row (includes commit info)."""
        row = (
            "nc-id",
            "snap-id",
            "node-id",
            "modified",
            "hash123",
            '{}',
            "abc123",  # commit_hash
            "Commit msg",  # commit_message
            "Author",  # commit_author
            "2024-01-15T10:30:00",  # commit_date
        )
        change = NodeChange.from_row(row)

        assert change.commit_hash == "abc123"
        assert change.commit_message == "Commit msg"
        assert change.commit_author == "Author"
        assert change.commit_date is not None

    def test_node_change_from_row_with_none_properties(self) -> None:
        """Test NodeChange.from_row handles None properties."""
        row = ("nc-id", "snap-id", "node-id", "added", None, None)
        change = NodeChange.from_row(row)

        assert change.properties == {}
        assert change.body_hash is None

    def test_node_change_from_row_invalid_commit_date(self) -> None:
        """Test NodeChange.from_row handles invalid commit date."""
        row = (
            "nc-id",
            "snap-id",
            "node-id",
            "added",
            "hash",
            "{}",
            "abc",
            "msg",
            "author",
            "invalid-date",
        )
        change = NodeChange.from_row(row)
        assert change.commit_date is None


# =============================================================================
# Additional GraphDiff Model Tests
# =============================================================================


class TestGraphDiffAdditional:
    """Additional tests for GraphDiff dataclass."""

    def test_graph_diff_to_dict(self) -> None:
        """Test GraphDiff to_dict serialization."""
        from_snap = Snapshot(id="s1", commit_hash="abc")
        to_snap = Snapshot(id="s2", commit_hash="def")

        diff = GraphDiff(
            from_snapshot=from_snap,
            to_snapshot=to_snap,
            nodes_added=[NodeDiff("n1", "test", "function", ChangeType.ADDED)],
        )

        d = diff.to_dict()
        assert "from_snapshot" in d
        assert "to_snapshot" in d
        assert len(d["nodes_added"]) == 1
        assert d["stats"]["nodes_added"] == 1

    def test_graph_diff_with_edge_changes(self) -> None:
        """Test GraphDiff with edge changes."""
        from_snap = Snapshot(id="s1", commit_hash="abc")
        to_snap = Snapshot(id="s2", commit_hash="def")

        diff = GraphDiff(
            from_snapshot=from_snap,
            to_snapshot=to_snap,
            edges_added=[EdgeDiff("e1", "n1", "n2", "imports", ChangeType.ADDED)],
            edges_removed=[EdgeDiff("e2", "n3", "n4", "contains", ChangeType.REMOVED)],
        )

        assert diff.has_changes
        assert diff.stats["edges_added"] == 1
        assert diff.stats["edges_removed"] == 1


# =============================================================================
# GitIntegration Tests with Mocking
# =============================================================================


class TestGitIntegrationMocked:
    """Tests for GitIntegration with mocked subprocess calls."""

    @patch("subprocess.run")
    def test_get_current_commit(self, mock_run: MagicMock) -> None:
        """Test get_current_commit returns HEAD hash."""
        mock_run.return_value.stdout = "/test/repo\n"
        mock_run.return_value.returncode = 0

        with tempfile.TemporaryDirectory() as tmpdir:
            # First call is for repo root
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            # Set up mock for get_current_commit
            mock_run.return_value.stdout = "abc123def456\n"
            commit = git.get_current_commit()

            assert commit.strip() == "abc123def456"

    @patch("subprocess.run")
    def test_get_commit_info(self, mock_run: MagicMock) -> None:
        """Test get_commit_info parses commit details."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First call for repo root
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            # Set up mock for get_commit_info
            mock_run.return_value.stdout = (
                "abc123def456\x00Test commit\x00John Doe\x002024-01-15T10:30:00+00:00"
            )
            info = git.get_commit_info("abc123")

            assert info.hash == "abc123def456"
            assert info.message == "Test commit"
            assert info.author == "John Doe"

    @patch("subprocess.run")
    def test_get_commits_with_filters(self, mock_run: MagicMock) -> None:
        """Test get_commits with date filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "abc123\ndef456\nghi789"
            commits = git.get_commits(limit=3)

            assert len(commits) == 3
            assert commits[0] == "abc123"

    @patch("subprocess.run")
    def test_get_commits_empty(self, mock_run: MagicMock) -> None:
        """Test get_commits returns empty list when no commits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = ""
            commits = git.get_commits()

            assert commits == []

    @patch("subprocess.run")
    def test_get_changed_files(self, mock_run: MagicMock) -> None:
        """Test get_changed_files parses diff output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "A\tnew_file.py\nM\tmodified.py\nD\tdeleted.py"
            added, modified, deleted = git.get_changed_files("abc", "def")

            assert "new_file.py" in added
            assert "modified.py" in modified
            assert "deleted.py" in deleted

    @patch("subprocess.run")
    def test_get_changed_files_with_rename(self, mock_run: MagicMock) -> None:
        """Test get_changed_files handles renamed files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "R100\told_name.py\tnew_name.py"
            added, modified, deleted = git.get_changed_files("abc", "def")

            assert "new_name.py" in added
            assert "old_name.py" in deleted

    @patch("subprocess.run")
    def test_is_shallow(self, mock_run: MagicMock) -> None:
        """Test is_shallow property."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "true"
            assert git.is_shallow is True

    @patch("subprocess.run")
    def test_get_file_at_commit(self, mock_run: MagicMock) -> None:
        """Test get_file_at_commit retrieves file content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "def hello():\n    pass"
            content = git.get_file_at_commit("test.py", "abc123")

            assert "def hello()" in content

    @patch("subprocess.run")
    def test_get_file_at_commit_not_found(self, mock_run: MagicMock) -> None:
        """Test get_file_at_commit returns None for missing file."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.side_effect = subprocess.CalledProcessError(1, "git show")
            content = git.get_file_at_commit("nonexistent.py", "abc123")

            assert content is None

    @patch("subprocess.run")
    def test_is_ancestor(self, mock_run: MagicMock) -> None:
        """Test is_ancestor relationship check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            mock_run.return_value.returncode = 0
            git = GitIntegration(Path(tmpdir))

            # is_ancestor returns True when command succeeds
            assert git.is_ancestor("abc", "def") is True

    @patch("subprocess.run")
    def test_get_parent_commit(self, mock_run: MagicMock) -> None:
        """Test get_parent_commit returns parent hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "parent123"
            parent = git.get_parent_commit("child456")

            assert parent == "parent123"

    @patch("subprocess.run")
    def test_get_common_ancestor(self, mock_run: MagicMock) -> None:
        """Test get_common_ancestor finds merge base."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "common123"
            ancestor = git.get_common_ancestor("abc", "def")

            assert ancestor == "common123"

    @patch("subprocess.run")
    def test_resolve_ref(self, mock_run: MagicMock) -> None:
        """Test resolve_ref converts branch/tag to commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "abc123def456"
            commit = git.resolve_ref("main")

            assert commit == "abc123def456"

    @patch("subprocess.run")
    def test_is_valid_repo(self, mock_run: MagicMock) -> None:
        """Test is_valid_repo check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = ".git"
            assert git.is_valid_repo() is True

    @patch("subprocess.run")
    def test_git_not_installed(self, mock_run: MagicMock) -> None:
        """Test error when git is not installed."""
        mock_run.side_effect = FileNotFoundError("git not found")

        with tempfile.TemporaryDirectory() as tmpdir:
            # The error gets wrapped in "Not a git repository" since the inner
            # exception causes the init to fail
            with pytest.raises(GitError):
                GitIntegration(Path(tmpdir))


# =============================================================================
# SnapshotManager Comprehensive Tests
# =============================================================================


class TestSnapshotManagerComprehensive:
    """Comprehensive tests for SnapshotManager."""

    @pytest.fixture
    def db_with_nodes_and_edges(self) -> MUbase:
        """Create a MUbase with nodes and edges for testing."""
        db = MUbase(":memory:")

        # Add nodes
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
            properties={"param_count": 2},
        )
        node2 = Node(
            id="cls:test.py:MyClass",
            type=NodeType.CLASS,
            name="MyClass",
            file_path="test.py",
            properties={"method_count": 3},
        )
        node3 = Node(
            id="mod:test.py",
            type=NodeType.MODULE,
            name="test",
            file_path="test.py",
        )
        db.add_node(node1)
        db.add_node(node2)
        db.add_node(node3)

        # Add edges
        from mu.kernel.schema import EdgeType

        edge1 = Edge(
            id="edge:mod:test.py:contains:cls:test.py:MyClass",
            source_id="mod:test.py",
            target_id="cls:test.py:MyClass",
            type=EdgeType.CONTAINS,
        )
        db.add_edge(edge1)

        return db

    def test_create_snapshot_without_git(self, db_with_nodes_and_edges: MUbase) -> None:
        """Test creating snapshot without git repository."""
        manager = SnapshotManager(db_with_nodes_and_edges)
        manager._git = None  # Simulate no git

        snapshot = manager.create_snapshot()

        assert snapshot.id is not None
        assert "manual-" in snapshot.commit_hash
        assert snapshot.node_count == 3
        assert snapshot.edge_count == 1

    def test_create_snapshot_force_overwrite(self, db_with_nodes_and_edges: MUbase) -> None:
        """Test force overwriting an existing snapshot."""
        manager = SnapshotManager(db_with_nodes_and_edges)
        manager._git = None

        # Create first snapshot
        first = manager.create_snapshot("commit-abc")

        # Force overwrite
        second = manager.create_snapshot("commit-abc", force=True)

        assert first.id != second.id
        assert first.commit_hash == second.commit_hash

    def test_create_snapshot_raises_on_duplicate(
        self, db_with_nodes_and_edges: MUbase
    ) -> None:
        """Test creating duplicate snapshot raises error."""
        manager = SnapshotManager(db_with_nodes_and_edges)
        manager._git = None

        manager.create_snapshot("commit-dup")

        with pytest.raises(ValueError, match="already exists"):
            manager.create_snapshot("commit-dup")

    def test_list_snapshots_ordered(self, db_with_nodes_and_edges: MUbase) -> None:
        """Test list_snapshots returns in chronological order."""
        manager = SnapshotManager(db_with_nodes_and_edges)
        manager._git = None

        manager.create_snapshot("commit-1")
        manager.create_snapshot("commit-2")

        snapshots = manager.list_snapshots()
        assert len(snapshots) == 2

    def test_get_snapshot_by_id(self, db_with_nodes_and_edges: MUbase) -> None:
        """Test getting snapshot by its UUID."""
        manager = SnapshotManager(db_with_nodes_and_edges)
        manager._git = None

        created = manager.create_snapshot("commit-xyz")
        retrieved = manager.get_snapshot_by_id(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id

    def test_get_snapshot_by_id_not_found(self, db_with_nodes_and_edges: MUbase) -> None:
        """Test getting non-existent snapshot by ID."""
        manager = SnapshotManager(db_with_nodes_and_edges)
        manager._git = None

        result = manager.get_snapshot_by_id("nonexistent-uuid")
        assert result is None


# =============================================================================
# MUbaseSnapshot Comprehensive Tests
# =============================================================================


class TestMUbaseSnapshotComprehensive:
    """Comprehensive tests for MUbaseSnapshot."""

    @pytest.fixture
    def temporal_db_with_data(self) -> MUbase:
        """Create a MUbase with temporal data for testing."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL

        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add nodes
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
            complexity=10,
        )
        node2 = Node(
            id="cls:test.py:MyClass",
            type=NodeType.CLASS,
            name="MyClass",
            file_path="test.py",
        )
        db.add_node(node1)
        db.add_node(node2)

        # Add edge
        from mu.kernel.schema import EdgeType

        edge1 = Edge(
            id="edge-1",
            source_id="fn:test.py:func1",
            target_id="cls:test.py:MyClass",
            type=EdgeType.CONTAINS,
        )
        db.add_edge(edge1)

        # Add snapshot
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("snap-1", "abc123", 2, 1, "2024-01-15T10:00:00"),
        )

        # Add node history
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, properties)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("hist-1", "snap-1", "fn:test.py:func1", "added", "{}"),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, properties)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("hist-2", "snap-1", "cls:test.py:MyClass", "added", "{}"),
        )

        # Add edge history
        db.conn.execute(
            """
            INSERT INTO edge_history (id, snapshot_id, edge_id, change_type, source_id, target_id, edge_type, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ehist-1",
                "snap-1",
                "edge-1",
                "added",
                "fn:test.py:func1",
                "cls:test.py:MyClass",
                "contains",
                "{}",
            ),
        )

        return db

    def test_get_node(self, temporal_db_with_data: MUbase) -> None:
        """Test getting a node at snapshot time."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=2, edge_count=1)
        view = MUbaseSnapshot(temporal_db_with_data, snapshot)

        node = view.get_node("fn:test.py:func1")
        assert node is not None
        assert node.name == "func1"

    def test_get_node_not_found(self, temporal_db_with_data: MUbase) -> None:
        """Test getting non-existent node."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=2, edge_count=1)
        view = MUbaseSnapshot(temporal_db_with_data, snapshot)

        node = view.get_node("nonexistent")
        assert node is None

    def test_get_nodes_all(self, temporal_db_with_data: MUbase) -> None:
        """Test getting all nodes at snapshot time."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=2, edge_count=1)
        view = MUbaseSnapshot(temporal_db_with_data, snapshot)

        nodes = view.get_nodes()
        assert len(nodes) == 2

    def test_get_nodes_by_type(self, temporal_db_with_data: MUbase) -> None:
        """Test getting nodes filtered by type."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=2, edge_count=1)
        view = MUbaseSnapshot(temporal_db_with_data, snapshot)

        functions = view.get_nodes(node_type=NodeType.FUNCTION)
        assert len(functions) == 1
        assert functions[0].name == "func1"

    def test_get_nodes_by_file_path(self, temporal_db_with_data: MUbase) -> None:
        """Test getting nodes filtered by file path."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=2, edge_count=1)
        view = MUbaseSnapshot(temporal_db_with_data, snapshot)

        nodes = view.get_nodes(file_path="test.py")
        assert len(nodes) == 2

    def test_get_edges(self, temporal_db_with_data: MUbase) -> None:
        """Test getting edges at snapshot time."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=2, edge_count=1)
        view = MUbaseSnapshot(temporal_db_with_data, snapshot)

        from mu.kernel.schema import EdgeType

        edges = view.get_edges()
        assert len(edges) == 1
        assert edges[0].type == EdgeType.CONTAINS

    def test_get_edges_by_source(self, temporal_db_with_data: MUbase) -> None:
        """Test getting edges filtered by source."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=2, edge_count=1)
        view = MUbaseSnapshot(temporal_db_with_data, snapshot)

        edges = view.get_edges(source_id="fn:test.py:func1")
        assert len(edges) == 1

    def test_snapshot_property(self, temporal_db_with_data: MUbase) -> None:
        """Test snapshot property."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123")
        view = MUbaseSnapshot(temporal_db_with_data, snapshot)

        assert view.snapshot.id == "snap-1"


# =============================================================================
# TemporalDiffer Comprehensive Tests
# =============================================================================


class TestTemporalDifferComprehensive:
    """Comprehensive tests for TemporalDiffer."""

    @pytest.fixture
    def db_with_two_snapshots(self) -> tuple[MUbase, str, str]:
        """Create a MUbase with two snapshots for diff testing."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL

        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add nodes
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
        )
        db.add_node(node1)

        # First snapshot
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, commit_date, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("snap-1", "abc123", "2024-01-15T10:00:00", 1, 0, "2024-01-15T10:00:00"),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("nh-1", "snap-1", "fn:test.py:func1", "added", "hash1", "{}"),
        )

        # Add another node
        node2 = Node(
            id="fn:test.py:func2",
            type=NodeType.FUNCTION,
            name="func2",
            file_path="test.py",
        )
        db.add_node(node2)

        # Second snapshot
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, commit_date, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("snap-2", "def456", "2024-01-16T10:00:00", 2, 0, "2024-01-16T10:00:00"),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("nh-2", "snap-2", "fn:test.py:func1", "unchanged", "hash1", "{}"),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("nh-3", "snap-2", "fn:test.py:func2", "added", "hash2", "{}"),
        )

        return db, "abc123", "def456"

    def test_diff_detects_added_nodes(
        self, db_with_two_snapshots: tuple[MUbase, str, str]
    ) -> None:
        """Test diff detects added nodes."""
        db, commit1, commit2 = db_with_two_snapshots
        manager = SnapshotManager(db)
        manager._git = None
        differ = TemporalDiffer(manager)

        diff = differ.diff(commit1, commit2)

        assert diff.has_changes
        assert len(diff.nodes_added) == 1
        assert diff.nodes_added[0].name == "func2"

    def test_diff_missing_snapshot_raises(
        self, db_with_two_snapshots: tuple[MUbase, str, str]
    ) -> None:
        """Test diff raises error for missing snapshot."""
        db, _, _ = db_with_two_snapshots
        manager = SnapshotManager(db)
        manager._git = None
        differ = TemporalDiffer(manager)

        with pytest.raises(ValueError, match="No snapshot exists"):
            differ.diff("nonexistent", "def456")

    def test_diff_snapshots_directly(
        self, db_with_two_snapshots: tuple[MUbase, str, str]
    ) -> None:
        """Test diff_snapshots method."""
        db, commit1, commit2 = db_with_two_snapshots
        manager = SnapshotManager(db)
        manager._git = None
        differ = TemporalDiffer(manager)

        snap1 = manager.get_snapshot(commit1)
        snap2 = manager.get_snapshot(commit2)

        diff = differ.diff_snapshots(snap1, snap2)

        assert diff.from_snapshot.id == "snap-1"
        assert diff.to_snapshot.id == "snap-2"


# =============================================================================
# HistoryTracker Comprehensive Tests
# =============================================================================


class TestHistoryTrackerComprehensive:
    """Comprehensive tests for HistoryTracker."""

    @pytest.fixture
    def db_with_rich_history(self) -> MUbase:
        """Create a MUbase with rich history data."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL

        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add nodes
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
            properties={"complexity": 5},
        )
        db.add_node(node1)

        # Add multiple snapshots with history
        for i, (snap_id, commit, author, date) in enumerate(
            [
                ("snap-1", "abc111", "Alice", "2024-01-10T10:00:00"),
                ("snap-2", "abc222", "Bob", "2024-01-15T10:00:00"),
                ("snap-3", "abc333", "Alice", "2024-01-20T10:00:00"),
            ]
        ):
            db.conn.execute(
                """
                INSERT INTO snapshots (id, commit_hash, commit_author, commit_date, commit_message, node_count, edge_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (snap_id, commit, author, date, f"Commit {i + 1}", 1, 0, date),
            )

        # Add node history entries
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("nh-1", "snap-1", "fn:test.py:func1", "added", "hash1", '{"complexity": 5}'),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "nh-2",
                "snap-2",
                "fn:test.py:func1",
                "modified",
                "hash2",
                '{"complexity": 10}',
            ),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "nh-3",
                "snap-3",
                "fn:test.py:func1",
                "modified",
                "hash3",
                '{"complexity": 15}',
            ),
        )

        return db

    def test_last_modified(self, db_with_rich_history: MUbase) -> None:
        """Test getting last modification."""
        tracker = HistoryTracker(db_with_rich_history)

        last = tracker.last_modified("fn:test.py:func1")

        assert last is not None
        assert last.commit_author == "Alice"
        assert last.change_type == ChangeType.MODIFIED

    def test_history_with_date_filters(self, db_with_rich_history: MUbase) -> None:
        """Test history with date range filters."""
        tracker = HistoryTracker(db_with_rich_history)

        since = datetime(2024, 1, 12)
        until = datetime(2024, 1, 18)
        changes = tracker.history("fn:test.py:func1", since=since, until=until)

        assert len(changes) == 1
        assert changes[0].commit_author == "Bob"

    def test_blame(self, db_with_rich_history: MUbase) -> None:
        """Test blame attribution."""
        tracker = HistoryTracker(db_with_rich_history)

        blame = tracker.blame("fn:test.py:func1")

        assert "_node" in blame
        assert blame["_node"].commit_author == "Alice"

    def test_changes_in_snapshot(self, db_with_rich_history: MUbase) -> None:
        """Test getting all changes in a snapshot."""
        tracker = HistoryTracker(db_with_rich_history)

        changes = tracker.changes_in_snapshot("snap-1")

        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.ADDED

    def test_changes_in_snapshot_with_filter(self, db_with_rich_history: MUbase) -> None:
        """Test getting filtered changes in a snapshot."""
        tracker = HistoryTracker(db_with_rich_history)

        changes = tracker.changes_in_snapshot("snap-2", change_type=ChangeType.MODIFIED)

        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.MODIFIED

    def test_nodes_changed_by_author(self, db_with_rich_history: MUbase) -> None:
        """Test finding nodes changed by a specific author."""
        tracker = HistoryTracker(db_with_rich_history)

        changes = tracker.nodes_changed_by_author("Alice")

        assert len(changes) == 2  # Added and last modified

    def test_first_appearance_not_found(self, db_with_rich_history: MUbase) -> None:
        """Test first_appearance returns None for unknown node."""
        tracker = HistoryTracker(db_with_rich_history)

        first = tracker.first_appearance("nonexistent")

        assert first is None

    def test_node_exists_at_removed(self, db_with_rich_history: MUbase) -> None:
        """Test node_exists_at returns False for removed nodes."""
        db = db_with_rich_history

        # Add a snapshot with a removed node
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, commit_date, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("snap-removed", "removed123", "2024-01-25T10:00:00", 0, 0, "2024-01-25T10:00:00"),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, properties)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("nh-removed", "snap-removed", "fn:test.py:func1", "removed", "{}"),
        )

        tracker = HistoryTracker(db)
        exists = tracker.node_exists_at("fn:test.py:func1", "snap-removed")

        assert exists is False


# =============================================================================
# Edge Diff Tests
# =============================================================================


class TestEdgeDiff:
    """Tests for EdgeDiff dataclass."""

    def test_edge_diff_to_dict(self) -> None:
        """Test EdgeDiff serialization."""
        diff = EdgeDiff(
            edge_id="e1",
            source_id="n1",
            target_id="n2",
            edge_type="imports",
            change_type=ChangeType.ADDED,
        )

        d = diff.to_dict()
        assert d["edge_id"] == "e1"
        assert d["change_type"] == "added"


# =============================================================================
# NodeDiff Tests
# =============================================================================


class TestNodeDiffAdditional:
    """Additional tests for NodeDiff."""

    def test_node_diff_with_properties(self) -> None:
        """Test NodeDiff with property changes."""
        diff = NodeDiff(
            node_id="n1",
            name="test",
            node_type="function",
            change_type=ChangeType.MODIFIED,
            file_path="test.py",
            old_properties={"complexity": 5},
            new_properties={"complexity": 10},
        )

        d = diff.to_dict()
        assert d["old_properties"]["complexity"] == 5
        assert d["new_properties"]["complexity"] == 10


# =============================================================================
# Additional TemporalDiffer Tests
# =============================================================================


class TestTemporalDifferDiffRange:
    """Tests for TemporalDiffer.diff_range method."""

    @pytest.fixture
    def db_with_three_snapshots(self) -> tuple[MUbase, str, str, str]:
        """Create a MUbase with three snapshots for range diff testing."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL

        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add nodes
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
        )
        db.add_node(node1)

        # Three snapshots with dates
        snapshots_data = [
            ("snap-1", "abc111", "2024-01-10T10:00:00"),
            ("snap-2", "abc222", "2024-01-15T10:00:00"),
            ("snap-3", "abc333", "2024-01-20T10:00:00"),
        ]

        for snap_id, commit, date in snapshots_data:
            db.conn.execute(
                """
                INSERT INTO snapshots (id, commit_hash, commit_date, node_count, edge_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (snap_id, commit, date, 1, 0, date),
            )
            db.conn.execute(
                """
                INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"nh-{snap_id}", snap_id, "fn:test.py:func1", "unchanged", "hash1", "{}"),
            )

        return db, "abc111", "abc222", "abc333"

    def test_diff_range_without_intermediate(
        self, db_with_three_snapshots: tuple[MUbase, str, str, str]
    ) -> None:
        """Test diff_range without intermediate snapshots returns single diff."""
        db, commit1, _, commit3 = db_with_three_snapshots
        manager = SnapshotManager(db)
        manager._git = None
        differ = TemporalDiffer(manager)

        result = differ.diff_range(commit1, commit3, include_intermediate=False)

        # Should return a single GraphDiff
        assert isinstance(result, GraphDiff)

    def test_diff_range_with_intermediate(
        self, db_with_three_snapshots: tuple[MUbase, str, str, str]
    ) -> None:
        """Test diff_range with intermediate snapshots returns list."""
        db, commit1, _, commit3 = db_with_three_snapshots
        manager = SnapshotManager(db)
        manager._git = None
        differ = TemporalDiffer(manager)

        result = differ.diff_range(commit1, commit3, include_intermediate=True)

        # Should return a list of GraphDiffs
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_diff_range_missing_snapshot_raises(
        self, db_with_three_snapshots: tuple[MUbase, str, str, str]
    ) -> None:
        """Test diff_range raises for missing snapshot."""
        db, _, _, _ = db_with_three_snapshots
        manager = SnapshotManager(db)
        manager._git = None
        differ = TemporalDiffer(manager)

        with pytest.raises(ValueError):
            differ.diff_range("nonexistent1", "nonexistent2", include_intermediate=True)


# =============================================================================
# Additional SnapshotManager Delta Tests
# =============================================================================


class TestSnapshotManagerDelta:
    """Tests for SnapshotManager delta calculation."""

    @pytest.fixture
    def db_with_parent_snapshot(self) -> MUbase:
        """Create a MUbase with an existing parent snapshot."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL

        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add initial node
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
            properties={"complexity": 5},
        )
        db.add_node(node1)

        # Create parent snapshot with history
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, commit_date, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("parent-snap", "parent123", "2024-01-10T10:00:00", 1, 0, "2024-01-10T10:00:00"),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "nh-parent",
                "parent-snap",
                "fn:test.py:func1",
                "added",
                "hash1",
                '{"complexity": 5}',
            ),
        )

        return db

    def test_delta_detects_added_node(self, db_with_parent_snapshot: MUbase) -> None:
        """Test delta calculation detects added nodes."""
        db = db_with_parent_snapshot

        # Add a new node
        node2 = Node(
            id="fn:test.py:func2",
            type=NodeType.FUNCTION,
            name="func2",
            file_path="test.py",
        )
        db.add_node(node2)

        manager = SnapshotManager(db)
        manager._git = None

        # Create new snapshot - it should detect the added node
        snapshot = manager.create_snapshot("child123")

        assert snapshot.nodes_added == 1  # New node was added

    def test_delta_detects_removed_node(self, db_with_parent_snapshot: MUbase) -> None:
        """Test delta calculation detects removed nodes."""
        db = db_with_parent_snapshot

        # Remove the existing node
        db.conn.execute("DELETE FROM nodes WHERE id = ?", ["fn:test.py:func1"])

        manager = SnapshotManager(db)
        manager._git = None

        # Create new snapshot - it should detect the removed node
        snapshot = manager.create_snapshot("child-removed")

        assert snapshot.nodes_removed == 1  # Node was removed

    def test_delta_detects_modified_node(self, db_with_parent_snapshot: MUbase) -> None:
        """Test delta calculation detects modified nodes."""
        db = db_with_parent_snapshot

        # Modify the existing node's properties
        db.conn.execute(
            "UPDATE nodes SET properties = ? WHERE id = ?",
            ['{"complexity": 10}', "fn:test.py:func1"],
        )

        manager = SnapshotManager(db)
        manager._git = None

        # Create new snapshot - it should detect the modified node
        snapshot = manager.create_snapshot("child-modified")

        assert snapshot.nodes_modified == 1  # Node was modified


# =============================================================================
# Additional GitIntegration Tests
# =============================================================================


class TestGitIntegrationDateFilters:
    """Tests for GitIntegration with date filters."""

    @patch("subprocess.run")
    def test_get_commits_with_since(self, mock_run: MagicMock) -> None:
        """Test get_commits with since date filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "abc123\ndef456"
            since = datetime(2024, 1, 1)
            commits = git.get_commits(since=since)

            assert len(commits) == 2

    @patch("subprocess.run")
    def test_get_commits_with_until(self, mock_run: MagicMock) -> None:
        """Test get_commits with until date filter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "abc123"
            until = datetime(2024, 12, 31)
            commits = git.get_commits(until=until)

            assert len(commits) == 1

    @patch("subprocess.run")
    def test_get_commits_with_path(self, mock_run: MagicMock) -> None:
        """Test get_commits filtered by path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = "abc123"
            commits = git.get_commits(path="src/test.py")

            assert len(commits) == 1

    @patch("subprocess.run")
    def test_get_changed_files_empty(self, mock_run: MagicMock) -> None:
        """Test get_changed_files returns empty lists for no changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.return_value.stdout = ""
            added, modified, deleted = git.get_changed_files("abc", "def")

            assert added == []
            assert modified == []
            assert deleted == []

    @patch("subprocess.run")
    def test_get_commit_info_invalid_format(self, mock_run: MagicMock) -> None:
        """Test get_commit_info handles invalid output gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            # Return incomplete output (missing parts)
            mock_run.return_value.stdout = "abc123\x00message"

            with pytest.raises(GitError, match="Failed to parse commit info"):
                git.get_commit_info("abc123")

    @patch("subprocess.run")
    def test_resolve_ref_invalid(self, mock_run: MagicMock) -> None:
        """Test resolve_ref raises for invalid reference."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            mock_run.side_effect = subprocess.CalledProcessError(128, "git rev-parse")

            with pytest.raises(GitError, match="Cannot resolve git reference"):
                git.resolve_ref("invalid-ref")


# =============================================================================
# Additional MUbaseSnapshot Edge Tests
# =============================================================================


class TestMUbaseSnapshotEdges:
    """Additional edge case tests for MUbaseSnapshot."""

    @pytest.fixture
    def db_with_edge_filters(self) -> MUbase:
        """Create a MUbase with multiple edge types for filter testing."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL

        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add nodes
        for i in range(3):
            node = Node(
                id=f"fn:test.py:func{i}",
                type=NodeType.FUNCTION,
                name=f"func{i}",
                file_path="test.py",
            )
            db.add_node(node)

        # Add edges
        from mu.kernel.schema import EdgeType

        edges = [
            ("e1", "fn:test.py:func0", "fn:test.py:func1", EdgeType.CONTAINS),
            ("e2", "fn:test.py:func0", "fn:test.py:func2", EdgeType.IMPORTS),
        ]
        for eid, src, tgt, etype in edges:
            edge = Edge(id=eid, source_id=src, target_id=tgt, type=etype)
            db.add_edge(edge)

        # Add snapshot
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("snap-1", "abc123", 3, 2, "2024-01-15T10:00:00"),
        )

        # Add node history
        for i in range(3):
            db.conn.execute(
                """
                INSERT INTO node_history (id, snapshot_id, node_id, change_type, properties)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"nh-{i}", "snap-1", f"fn:test.py:func{i}", "added", "{}"),
            )

        # Add edge history
        db.conn.execute(
            """
            INSERT INTO edge_history (id, snapshot_id, edge_id, change_type, source_id, target_id, edge_type, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("eh-1", "snap-1", "e1", "added", "fn:test.py:func0", "fn:test.py:func1", "contains", "{}"),
        )
        db.conn.execute(
            """
            INSERT INTO edge_history (id, snapshot_id, edge_id, change_type, source_id, target_id, edge_type, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("eh-2", "snap-1", "e2", "added", "fn:test.py:func0", "fn:test.py:func2", "imports", "{}"),
        )

        return db

    def test_get_edges_by_target(self, db_with_edge_filters: MUbase) -> None:
        """Test getting edges filtered by target."""
        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=3, edge_count=2)
        view = MUbaseSnapshot(db_with_edge_filters, snapshot)

        edges = view.get_edges(target_id="fn:test.py:func1")
        assert len(edges) == 1

    def test_get_edges_by_type(self, db_with_edge_filters: MUbase) -> None:
        """Test getting edges filtered by type."""
        from mu.kernel.schema import EdgeType

        snapshot = Snapshot(id="snap-1", commit_hash="abc123", node_count=3, edge_count=2)
        view = MUbaseSnapshot(db_with_edge_filters, snapshot)

        edges = view.get_edges(edge_type=EdgeType.IMPORTS)
        assert len(edges) == 1
        assert edges[0].type == EdgeType.IMPORTS


# =============================================================================
# Additional HistoryTracker Edge Tests
# =============================================================================


class TestHistoryTrackerEdges:
    """Additional edge case tests for HistoryTracker."""

    @pytest.fixture
    def db_with_empty_blame(self) -> MUbase:
        """Create a MUbase with no history for a node."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL

        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Just add the node, no history
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
        )
        db.add_node(node1)

        return db

    def test_blame_empty_history(self, db_with_empty_blame: MUbase) -> None:
        """Test blame returns empty dict for node with no history."""
        tracker = HistoryTracker(db_with_empty_blame)

        blame = tracker.blame("fn:test.py:func1")

        assert blame == {}

    def test_last_modified_not_found(self, db_with_empty_blame: MUbase) -> None:
        """Test last_modified returns None for node with no history."""
        tracker = HistoryTracker(db_with_empty_blame)

        last = tracker.last_modified("nonexistent")

        assert last is None


# =============================================================================
# Additional Diff Edge Tests
# =============================================================================


class TestTemporalDifferEdges:
    """Additional edge case tests for TemporalDiffer."""

    @pytest.fixture
    def db_with_edge_changes(self) -> tuple[MUbase, str, str]:
        """Create a MUbase with edge changes between snapshots."""
        db = MUbase(":memory:")

        from mu.kernel.schema import TEMPORAL_SCHEMA_SQL

        db.conn.execute(TEMPORAL_SCHEMA_SQL)

        # Add nodes
        node1 = Node(
            id="fn:test.py:func1",
            type=NodeType.FUNCTION,
            name="func1",
            file_path="test.py",
        )
        db.add_node(node1)

        # First snapshot with an edge
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, commit_date, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("snap-1", "abc123", "2024-01-15T10:00:00", 1, 1, "2024-01-15T10:00:00"),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("nh-1", "snap-1", "fn:test.py:func1", "added", "hash1", "{}"),
        )
        db.conn.execute(
            """
            INSERT INTO edge_history (id, snapshot_id, edge_id, change_type, source_id, target_id, edge_type, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("eh-1", "snap-1", "e1", "added", "fn:test.py:func1", "external", "imports", "{}"),
        )

        # Second snapshot without the edge (edge removed)
        db.conn.execute(
            """
            INSERT INTO snapshots (id, commit_hash, commit_date, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("snap-2", "def456", "2024-01-16T10:00:00", 1, 0, "2024-01-16T10:00:00"),
        )
        db.conn.execute(
            """
            INSERT INTO node_history (id, snapshot_id, node_id, change_type, body_hash, properties)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("nh-2", "snap-2", "fn:test.py:func1", "unchanged", "hash1", "{}"),
        )
        # No edge history for snap-2 (edge was removed)

        return db, "abc123", "def456"

    def test_diff_detects_edge_changes(
        self, db_with_edge_changes: tuple[MUbase, str, str]
    ) -> None:
        """Test diff detects edge removals."""
        db, commit1, commit2 = db_with_edge_changes
        manager = SnapshotManager(db)
        manager._git = None
        differ = TemporalDiffer(manager)

        diff = differ.diff(commit1, commit2)

        assert diff.has_changes
        # Edge was in snap-1 but not in snap-2
        assert len(diff.edges_removed) == 1


# =============================================================================
# Git Shallow Clone Warning Tests
# =============================================================================


class TestGitShallowWarnings:
    """Tests for shallow clone warning behavior."""

    @patch("subprocess.run")
    def test_get_commits_shallow_warning(self, mock_run: MagicMock) -> None:
        """Test get_commits issues warning for shallow clones."""
        import warnings

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_run.return_value.stdout = tmpdir
            git = GitIntegration(Path(tmpdir))

            # Simulate shallow clone
            mock_run.return_value.stdout = "true"
            _ = git.is_shallow  # Prime the property

            mock_run.return_value.stdout = "abc123"
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                git.get_commits()

                # Should have issued a warning about shallow clone
                assert len(w) >= 1
                assert "shallow" in str(w[0].message).lower()
