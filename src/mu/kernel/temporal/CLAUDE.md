# Temporal Module - Git-Linked Snapshots and Time-Travel Queries

The temporal module provides time-travel capabilities for MUbase, enabling git-linked snapshots, history tracking, and semantic diffs between points in time.

## Architecture

```
MUbase + Git Repository
        |
        v
SnapshotManager ----> Create/Query Snapshots
        |
        +-- GitIntegration (git operations)
        |
        +-- HistoryTracker (node history)
        |
        +-- TemporalDiffer (semantic diffs)
        |
        +-- MUbaseSnapshot (read-only temporal views)
```

### Files

| File | Purpose |
|------|---------|
| `models.py` | Snapshot, NodeChange, EdgeChange, GraphDiff dataclasses |
| `git.py` | GitIntegration class for git operations |
| `snapshot.py` | SnapshotManager and MUbaseSnapshot classes |
| `history.py` | HistoryTracker for node history queries |
| `diff.py` | TemporalDiffer for semantic diffs |

## Data Models

### Snapshot

Represents a point-in-time capture of the code graph:

```python
@dataclass
class Snapshot:
    id: str                        # UUID
    commit_hash: str               # Git commit
    commit_message: str | None
    commit_author: str | None
    commit_date: datetime | None
    parent_id: str | None          # Previous snapshot
    node_count: int
    edge_count: int
    nodes_added: int               # Delta from parent
    nodes_removed: int
    nodes_modified: int
```

### NodeChange

Tracks a change to a specific node:

```python
@dataclass
class NodeChange:
    id: str
    snapshot_id: str
    node_id: str
    change_type: ChangeType        # ADDED, MODIFIED, REMOVED, UNCHANGED
    body_hash: str | None          # For change detection
    properties: dict[str, Any]
    # Populated when joined with snapshot:
    commit_hash: str | None
    commit_author: str | None
    commit_date: datetime | None
```

### GraphDiff

Semantic diff between two snapshots:

```python
@dataclass
class GraphDiff:
    from_snapshot: Snapshot
    to_snapshot: Snapshot
    nodes_added: list[NodeDiff]
    nodes_removed: list[NodeDiff]
    nodes_modified: list[NodeDiff]
    edges_added: list[EdgeDiff]
    edges_removed: list[EdgeDiff]
```

## Usage

### Creating Snapshots

```python
from mu.kernel import MUbase
from mu.kernel.temporal import SnapshotManager

db = MUbase(Path(".mubase"))
manager = SnapshotManager(db, Path("."))

# Snapshot at current HEAD
snapshot = manager.create_snapshot()

# Snapshot at specific commit
snapshot = manager.create_snapshot("abc123")

# Force overwrite existing
snapshot = manager.create_snapshot("abc123", force=True)
```

### Querying History

```python
from mu.kernel.temporal import HistoryTracker

tracker = HistoryTracker(db)

# Get chronological history of a node
changes = tracker.history(node_id, limit=100)

# Get blame information (who changed what)
blame = tracker.blame(node_id)

# Get first appearance
first = tracker.first_appearance(node_id)

# Get last modification
last = tracker.last_modified(node_id)
```

### Computing Diffs

```python
from mu.kernel.temporal import SnapshotManager, TemporalDiffer

manager = SnapshotManager(db)
differ = TemporalDiffer(manager)

# Diff between two commits
diff = differ.diff("abc123", "def456")

# Access changes
for node_diff in diff.nodes_added:
    print(f"+ {node_diff.name}")

for node_diff in diff.nodes_modified:
    print(f"~ {node_diff.name}")
```

### Temporal Views

```python
from mu.kernel.temporal import MUbaseSnapshot

# Get snapshot for a commit
snapshot = manager.get_snapshot("abc123")

# Create read-only view at that point in time
view = MUbaseSnapshot(db, snapshot)

# Query nodes as they existed then
nodes = view.get_nodes(NodeType.FUNCTION)
```

## CLI Commands

```bash
# Create snapshot at HEAD
mu kernel snapshot .

# Create snapshot at specific commit
mu kernel snapshot . --commit abc123

# List all snapshots
mu kernel snapshots .

# Show history for a node
mu kernel history MUbase .

# Show blame for a node
mu kernel blame MUbase .

# Show diff between snapshots
mu kernel diff abc123 def456 .
```

## MUQL Temporal Queries

```sql
-- Show node history
HISTORY OF MUbase LIMIT 20

-- Show blame
BLAME MUbase

-- Query at specific point in time
SELECT * FROM functions AT "abc123"

-- Compare between commits
SELECT * FROM functions BETWEEN "abc123" AND "def456"
```

## Database Schema

The temporal layer adds three tables to MUbase:

```sql
-- Snapshots table
CREATE TABLE snapshots (
    id VARCHAR PRIMARY KEY,
    commit_hash VARCHAR NOT NULL UNIQUE,
    commit_message VARCHAR,
    commit_author VARCHAR,
    commit_date VARCHAR,
    parent_id VARCHAR,
    node_count INTEGER,
    edge_count INTEGER,
    nodes_added INTEGER,
    nodes_removed INTEGER,
    nodes_modified INTEGER,
    created_at VARCHAR NOT NULL
);

-- Node history table
CREATE TABLE node_history (
    id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL,
    node_id VARCHAR NOT NULL,
    change_type VARCHAR NOT NULL,  -- added, modified, unchanged, removed
    body_hash VARCHAR,
    properties JSON
);

-- Edge history table
CREATE TABLE edge_history (
    id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL,
    edge_id VARCHAR NOT NULL,
    change_type VARCHAR NOT NULL,
    source_id VARCHAR,
    target_id VARCHAR,
    edge_type VARCHAR
);
```

## Change Detection

The system detects changes by:

1. **Body Hash**: Computing a hash of node properties for modification detection
2. **Node ID Tracking**: Comparing node IDs between snapshots for add/remove
3. **Edge Comparison**: Set comparison of edge IDs between snapshots

## Anti-Patterns

1. **Never** create snapshots without building the graph first
2. **Never** modify the temporal tables directly - use SnapshotManager
3. **Never** assume snapshots exist - check with `get_snapshot()` first
4. **Never** bypass GitIntegration for git operations

## Testing

```bash
pytest tests/unit/test_temporal.py -v
```

Test scenarios:
- Snapshot creation at different commits
- History tracking across multiple snapshots
- Blame attribution
- Diff computation
- Temporal MUQL queries
