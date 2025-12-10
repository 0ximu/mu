# Epic 4: Temporal Layer

**Priority**: P2 - Enables history and evolution tracking
**Dependencies**: Kernel (complete)
**Estimated Complexity**: High
**PRD Reference**: Section 0.3

---

## Overview

Add git-linked temporal snapshots to MUbase, enabling time-travel queries and code evolution analysis. Track when dependencies appeared, how complexity changed, and who modified what.

## Goals

1. Create snapshots linked to git commits
2. Track node and edge changes over time
3. Enable temporal MUQL queries (`AT`, `BETWEEN`, `HISTORY`)
4. Provide blame and diff capabilities

---

## User Stories

### Story 4.1: Snapshot Schema
**As a** developer
**I want** historical state stored efficiently
**So that** I can query past states without full rebuilds

**Acceptance Criteria**:
- [ ] `snapshots` table with commit metadata
- [ ] `node_history` table with per-snapshot state
- [ ] `edge_history` table with per-snapshot edges
- [ ] Efficient delta storage (only store changes)

### Story 4.2: Snapshot Creation
**As a** developer
**I want** snapshots created on demand or automatically
**So that** history is captured accurately

**Acceptance Criteria**:
- [ ] `mu kernel snapshot` CLI command
- [ ] `--from-git` flag to snapshot from commit
- [ ] Delta calculation from previous snapshot
- [ ] Commit metadata extraction (author, date, message)

### Story 4.3: Historical Build
**As a** developer
**I want** to build from git history
**So that** I can analyze evolution from the start

**Acceptance Criteria**:
- [ ] `mu kernel build --with-history` flag
- [ ] Process specified commit range
- [ ] Incremental: only rebuild changed files
- [ ] Handle deleted files and renames

### Story 4.4: Time-Travel Queries
**As a** developer
**I want** to query past states
**So that** I can understand evolution

**Acceptance Criteria**:
- [ ] `AT <commit>` clause in MUQL
- [ ] `BETWEEN <commit1> AND <commit2>` clause
- [ ] Return state as it was at that commit
- [ ] Handle nodes that didn't exist

### Story 4.5: History Command
**As a** developer
**I want** to see evolution of a node
**So that** I can understand how code changed

**Acceptance Criteria**:
- [ ] `HISTORY OF <node>` MUQL query
- [ ] `mu kernel history <node>` CLI command
- [ ] Show: commit, date, author, change type
- [ ] Filter by date range

### Story 4.6: Blame Command
**As a** developer
**I want** git-blame-like information
**So that** I know who last modified code

**Acceptance Criteria**:
- [ ] `BLAME <node>` MUQL query
- [ ] `mu kernel blame <node>` CLI command
- [ ] Show last commit for each attribute
- [ ] Integrate with git for line-level blame

### Story 4.7: Semantic Diff
**As a** developer
**I want** semantic diff between commits
**So that** I understand what actually changed

**Acceptance Criteria**:
- [ ] `mu kernel diff <commit1> <commit2>` command
- [ ] Show: added/removed/modified nodes and edges
- [ ] Highlight dependency changes
- [ ] Integration with existing `mu diff` command

---

## Technical Design

### Schema Addition

```sql
-- Snapshots table
CREATE TABLE snapshots (
    id VARCHAR PRIMARY KEY,
    commit_hash VARCHAR NOT NULL UNIQUE,
    commit_message VARCHAR,
    commit_author VARCHAR,
    commit_date TIMESTAMP,
    parent_snapshot_id VARCHAR REFERENCES snapshots(id),

    -- Stats
    node_count INTEGER,
    edge_count INTEGER,

    -- Delta from parent
    nodes_added INTEGER DEFAULT 0,
    nodes_removed INTEGER DEFAULT 0,
    nodes_modified INTEGER DEFAULT 0,
    edges_added INTEGER DEFAULT 0,
    edges_removed INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_snapshots_commit ON snapshots(commit_hash);
CREATE INDEX idx_snapshots_date ON snapshots(commit_date);

-- Node history (state at each snapshot)
CREATE TABLE node_history (
    node_id VARCHAR,
    snapshot_id VARCHAR REFERENCES snapshots(id),

    -- State at this snapshot
    properties JSON,
    complexity INTEGER,
    body_hash VARCHAR,  -- For change detection

    -- Change type
    change_type VARCHAR,  -- 'added', 'modified', 'unchanged', 'removed'

    PRIMARY KEY (node_id, snapshot_id)
);

CREATE INDEX idx_node_history_snapshot ON node_history(snapshot_id);
CREATE INDEX idx_node_history_change ON node_history(change_type);

-- Edge history
CREATE TABLE edge_history (
    edge_id VARCHAR,
    snapshot_id VARCHAR REFERENCES snapshots(id),
    change_type VARCHAR,

    PRIMARY KEY (edge_id, snapshot_id)
);

CREATE INDEX idx_edge_history_snapshot ON edge_history(snapshot_id);
```

### File Structure

```
src/mu/kernel/
├── temporal/
│   ├── __init__.py          # Public API
│   ├── snapshot.py          # Snapshot creation
│   ├── history.py           # History queries
│   ├── diff.py              # Semantic diff
│   ├── git.py               # Git integration
│   └── models.py            # Snapshot, NodeChange, etc.
```

### Core Classes

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Snapshot:
    """A point-in-time snapshot of the graph."""
    id: str
    commit_hash: str
    commit_message: str | None
    commit_author: str | None
    commit_date: datetime | None
    parent_id: str | None

    node_count: int
    edge_count: int

    nodes_added: int
    nodes_removed: int
    nodes_modified: int
    edges_added: int
    edges_removed: int


@dataclass
class NodeChange:
    """Change to a node between snapshots."""
    node_id: str
    node_name: str
    node_type: str
    change_type: str  # added, modified, removed
    old_properties: dict | None
    new_properties: dict | None
    commit_hash: str
    commit_author: str
    commit_date: datetime


@dataclass
class GraphDiff:
    """Semantic diff between two snapshots."""
    from_snapshot: Snapshot
    to_snapshot: Snapshot

    nodes_added: list[Node]
    nodes_removed: list[Node]
    nodes_modified: list[tuple[Node, Node]]  # (old, new)

    edges_added: list[Edge]
    edges_removed: list[Edge]


class SnapshotManager:
    """Manage temporal snapshots."""

    def __init__(self, mubase: MUbase):
        self.mubase = mubase
        self.git = GitIntegration(mubase.path.parent)

    def create_snapshot(
        self,
        commit_hash: str | None = None
    ) -> Snapshot:
        """Create snapshot from current or specified commit."""
        if commit_hash:
            # Checkout commit, rebuild, create snapshot
            return self._snapshot_from_commit(commit_hash)
        else:
            # Snapshot current state
            return self._snapshot_current()

    def build_with_history(
        self,
        commits: list[str] | None = None,
        since: datetime | None = None,
        on_progress: Callable | None = None
    ) -> list[Snapshot]:
        """Build graph history from git commits."""
        if commits is None:
            commits = self.git.get_commits(since=since)

        snapshots = []
        for i, commit in enumerate(commits):
            snapshot = self._snapshot_from_commit(commit)
            snapshots.append(snapshot)

            if on_progress:
                on_progress(i + 1, len(commits))

        return snapshots

    def get_state_at(self, commit_hash: str) -> 'MUbaseSnapshot':
        """Get graph state at a specific commit."""
        snapshot = self._find_snapshot(commit_hash)
        if not snapshot:
            raise ValueError(f"No snapshot for commit {commit_hash}")
        return MUbaseSnapshot(self.mubase, snapshot)

    def diff(
        self,
        from_commit: str,
        to_commit: str
    ) -> GraphDiff:
        """Get semantic diff between commits."""
        from_snap = self._find_snapshot(from_commit)
        to_snap = self._find_snapshot(to_commit)
        return self._compute_diff(from_snap, to_snap)

    def history(
        self,
        node_id: str,
        limit: int | None = None
    ) -> list[NodeChange]:
        """Get history of changes to a node."""
        rows = self.mubase.conn.execute("""
            SELECT
                nh.node_id,
                n.name,
                n.type,
                nh.change_type,
                nh.properties,
                s.commit_hash,
                s.commit_author,
                s.commit_date
            FROM node_history nh
            JOIN snapshots s ON nh.snapshot_id = s.id
            JOIN nodes n ON nh.node_id = n.id
            WHERE nh.node_id = ?
            ORDER BY s.commit_date DESC
            LIMIT ?
        """, [node_id, limit or 100]).fetchall()

        return [NodeChange.from_row(r) for r in rows]

    def blame(self, node_id: str) -> dict[str, NodeChange]:
        """Get last change for each attribute of a node."""
        # Track when each property last changed
        ...


class MUbaseSnapshot:
    """Read-only view of MUbase at a point in time."""

    def __init__(self, mubase: MUbase, snapshot: Snapshot):
        self.mubase = mubase
        self.snapshot = snapshot

    def get_node(self, node_id: str) -> Node | None:
        """Get node as it was at this snapshot."""
        row = self.mubase.conn.execute("""
            SELECT n.*, nh.properties, nh.complexity
            FROM nodes n
            JOIN node_history nh ON n.id = nh.node_id
            WHERE nh.snapshot_id = ? AND nh.node_id = ?
        """, [self.snapshot.id, node_id]).fetchone()

        return Node.from_row(row) if row else None

    def get_all_nodes(self) -> list[Node]:
        """Get all nodes as they were at this snapshot."""
        ...

    def get_edges(self) -> list[Edge]:
        """Get edges that existed at this snapshot."""
        ...
```

### Git Integration

```python
import subprocess
from pathlib import Path

class GitIntegration:
    """Interface with git for history."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def get_current_commit(self) -> str:
        """Get current HEAD commit hash."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )
        return result.stdout.strip()

    def get_commit_info(self, commit_hash: str) -> dict:
        """Get commit metadata."""
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H|%s|%an|%ai", commit_hash],
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )
        parts = result.stdout.strip().split("|")
        return {
            "hash": parts[0],
            "message": parts[1],
            "author": parts[2],
            "date": parts[3],
        }

    def get_commits(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        path: str | None = None
    ) -> list[str]:
        """Get commit hashes in range."""
        cmd = ["git", "log", "--format=%H", "--reverse"]
        if since:
            cmd.extend(["--since", since.isoformat()])
        if until:
            cmd.extend(["--until", until.isoformat()])
        if path:
            cmd.extend(["--", path])

        result = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )
        return result.stdout.strip().split("\n")

    def get_changed_files(
        self,
        from_commit: str,
        to_commit: str
    ) -> tuple[list[str], list[str], list[str]]:
        """Get added, modified, deleted files between commits."""
        result = subprocess.run(
            ["git", "diff", "--name-status", from_commit, to_commit],
            cwd=self.repo_path,
            capture_output=True,
            text=True
        )

        added, modified, deleted = [], [], []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            status, path = line.split("\t", 1)
            if status == "A":
                added.append(path)
            elif status == "M":
                modified.append(path)
            elif status == "D":
                deleted.append(path)

        return added, modified, deleted

    def checkout_commit(self, commit_hash: str):
        """Checkout a specific commit (for rebuilding)."""
        subprocess.run(
            ["git", "checkout", commit_hash],
            cwd=self.repo_path,
            capture_output=True
        )

    def checkout_back(self):
        """Return to previous HEAD."""
        subprocess.run(
            ["git", "checkout", "-"],
            cwd=self.repo_path,
            capture_output=True
        )
```

---

## Implementation Plan

### Phase 1: Schema & Models (Day 1)
1. Add temporal tables to `schema.py`
2. Update migration logic
3. Create `Snapshot`, `NodeChange` dataclasses
4. Add snapshot CRUD methods to MUbase

### Phase 2: Git Integration (Day 1-2)
1. Implement `GitIntegration` class
2. Add commit info extraction
3. Add file change detection
4. Handle edge cases (shallow clones, etc.)

### Phase 3: Snapshot Creation (Day 2)
1. Implement `SnapshotManager.create_snapshot()`
2. Calculate deltas from previous snapshot
3. Record node_history and edge_history
4. Add `mu kernel snapshot` CLI command

### Phase 4: Historical Build (Day 2-3)
1. Implement `build_with_history()`
2. Process commits chronologically
3. Incremental rebuild (only changed files)
4. Add progress callbacks
5. Add `mu kernel build --with-history` flag

### Phase 5: Time-Travel View (Day 3)
1. Implement `MUbaseSnapshot` class
2. Query methods that filter by snapshot
3. Ensure read-only behavior
4. Test historical queries

### Phase 6: MUQL Integration (Day 3-4)
1. Add `AT <commit>` clause to grammar
2. Add `BETWEEN <commit1> AND <commit2>` clause
3. Modify executor to use temporal views
4. Add `HISTORY OF <node>` query

### Phase 7: History & Blame CLI (Day 4)
1. Implement `mu kernel history <node>`
2. Implement `mu kernel blame <node>`
3. Format output nicely (timeline, table)
4. Add filtering options

### Phase 8: Semantic Diff (Day 4-5)
1. Implement `SnapshotManager.diff()`
2. Compare nodes, edges, properties
3. Generate human-readable diff
4. Integrate with `mu diff` command

### Phase 9: Testing (Day 5)
1. Unit tests with mock git
2. Integration tests with real git repo
3. Test incremental snapshots
4. Test historical queries

---

## CLI Interface

```bash
# Create snapshot from current state
$ mu kernel snapshot
Snapshot created: snap_abc123
  Commit: abc123 (Fix authentication bug)
  Nodes: 342 (+2, -0, ~5)
  Edges: 891 (+3, -1)

# Build with full history
$ mu kernel build --with-history --since 2024-01-01
Processing 47 commits...
[========================================] 47/47
Created 47 snapshots

# Query at specific commit
$ mu query "SELECT * FROM functions WHERE complexity > 500" --at abc123
(shows state as of that commit)

# Show node history
$ mu kernel history AuthService
┌──────────┬────────────┬─────────────┬──────────┐
│ Commit   │ Date       │ Author      │ Change   │
├──────────┼────────────┼─────────────┼──────────┤
│ abc123   │ 2024-03-15 │ Alice       │ modified │
│ def456   │ 2024-02-20 │ Bob         │ modified │
│ 789xyz   │ 2024-01-10 │ Alice       │ added    │
└──────────┴────────────┴─────────────┴──────────┘

# Blame
$ mu kernel blame AuthService
┌─────────────┬──────────┬────────────┬─────────┐
│ Attribute   │ Commit   │ Date       │ Author  │
├─────────────┼──────────┼────────────┼─────────┤
│ login()     │ abc123   │ 2024-03-15 │ Alice   │
│ logout()    │ def456   │ 2024-02-20 │ Bob     │
│ class def   │ 789xyz   │ 2024-01-10 │ Alice   │
└─────────────┴──────────┴────────────┴─────────┘

# Semantic diff
$ mu kernel diff abc123 HEAD
Nodes Added (2):
  + PaymentValidator (CLASS in payments.py)
  + validate_amount (FUNCTION in payments.py)

Nodes Modified (3):
  ~ AuthService: complexity 45 → 52
  ~ process_payment: added Redis dependency

Edges Added (5):
  + PaymentService → PaymentValidator (CALLS)
  ...

Edges Removed (1):
  - AuthService → OldLogger (CALLS)
```

---

## MUQL Temporal Extensions

```sql
-- Query at specific commit
SELECT * FROM functions WHERE complexity > 500 AT "abc123"

-- Query between commits (show what was added/modified)
SELECT * FROM functions BETWEEN "abc123" AND HEAD WHERE change_type = 'added'

-- Node history
HISTORY OF AuthService
HISTORY OF AuthService LIMIT 10

-- When did dependency appear?
SELECT * FROM edges
WHERE source_id = 'AuthService' AND target_id = 'Redis'
AT FIRST  -- First snapshot where this existed

-- Blame
BLAME AuthService
BLAME process_payment
```

---

## Testing Strategy

### Unit Tests
```python
def test_snapshot_creation(mubase_with_graph):
    manager = SnapshotManager(mubase_with_graph)
    snapshot = manager.create_snapshot()
    assert snapshot.node_count > 0
    assert snapshot.commit_hash is not None

def test_node_history(mubase_with_snapshots):
    history = manager.history("AuthService")
    assert len(history) > 0
    assert history[0].change_type in ("added", "modified")
```

### Integration Tests
```python
def test_build_with_history(git_repo_with_commits):
    mubase = MUbase(git_repo_with_commits / ".mubase")
    manager = SnapshotManager(mubase)
    snapshots = manager.build_with_history()
    assert len(snapshots) == git_repo_with_commits.commit_count

def test_time_travel_query(mubase_with_history):
    # Add node in latest commit
    # Query at old commit, should not exist
    old_view = mubase.at_commit("old_commit")
    assert old_view.get_node("new_node_id") is None
```

---

## Success Criteria

- [ ] Snapshots created in < 5 seconds
- [ ] Historical build processes 100 commits in < 10 minutes
- [ ] Temporal queries return correct state
- [ ] History command shows accurate timeline
- [ ] Diff identifies all changes correctly

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Large history | High | Limit snapshots, compress old data |
| Git edge cases | Medium | Handle shallow clones, detached HEAD |
| Checkout safety | High | Use worktree or temp dir, never checkout in place |
| Performance | Medium | Only store deltas, lazy load history |

---

## Future Enhancements

1. **Automatic snapshots**: Git hook integration
2. **Trends**: Complexity over time charts
3. **Hotspot detection**: Files changed most frequently
4. **Prediction**: Estimate future complexity
5. **Compression**: Archive old snapshots
