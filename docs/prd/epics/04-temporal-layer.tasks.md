# Temporal Layer - Task Breakdown

## Business Context

**Problem**: Developers need to understand how their codebase evolves over time - when dependencies appeared, how complexity changed, and who modified critical code paths. Current MUbase provides only a static snapshot.

**Outcome**: Enable time-travel queries on the code graph, git blame-like information for code entities, and semantic diff between commits. This transforms MUbase from a static analysis tool into a temporal code evolution tracker.

**Users**:
- Developers investigating "when did this dependency appear?"
- Tech leads reviewing complexity trends
- Teams doing code archaeology on legacy codebases

---

## Discovered Patterns

| Pattern | File | Relevance |
|---------|------|-----------|
| Dataclass with `to_dict()` | `/Users/imu/Dev/work/mu/src/mu/kernel/models.py:16-86` | All new models (Snapshot, NodeChange, GraphDiff) should follow Node/Edge pattern |
| Enum definitions | `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:12-28` | ChangeType enum should follow NodeType/EdgeType pattern |
| Schema SQL pattern | `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:32-76` | Temporal tables follow same CREATE TABLE pattern |
| MUbase class structure | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:23-862` | SnapshotManager should follow similar DuckDB wrapper pattern |
| CLI command groups | `/Users/imu/Dev/work/mu/src/mu/cli.py:834-840` | `kernel` command group pattern for new temporal commands |
| CLI subcommands | `/Users/imu/Dev/work/mu/src/mu/cli.py:876-951` | `kernel_build` pattern for new `kernel snapshot`, `kernel history`, etc. |
| MUQL grammar extension | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/grammar.lark:1-261` | Add temporal keywords (AT, BETWEEN, HISTORY, BLAME) |
| AST query types | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/ast.py:237-378` | New temporal query AST nodes |
| Parser transformer | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/parser.py:57-711` | Temporal clause transformer methods |
| Diff models | `/Users/imu/Dev/work/mu/src/mu/diff/models.py:10-265` | GraphDiff should follow DiffResult pattern |
| Test organization | `/Users/imu/Dev/work/mu/tests/CLAUDE.md` | Class-based test grouping pattern |

---

## Task Breakdown

### Task 1: Create Temporal Schema and Enums

**Priority**: P0 (Foundation - blocks everything)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py`
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/__init__.py` (new)

**Pattern**: Follow existing `SCHEMA_SQL` and `NodeType`/`EdgeType` enum patterns in `schema.py:12-76`

**Description**: Add temporal tables schema and ChangeType enum to the kernel module. Create the `temporal/` subpackage structure.

**Implementation**:
```python
# Add to schema.py or new temporal/schema.py
class ChangeType(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    REMOVED = "removed"

TEMPORAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id VARCHAR PRIMARY KEY,
    commit_hash VARCHAR NOT NULL UNIQUE,
    ...
);

CREATE TABLE IF NOT EXISTS node_history (...);
CREATE TABLE IF NOT EXISTS edge_history (...);
"""
```

**Acceptance Criteria**:
- [ ] `ChangeType` enum in `schema.py` or `temporal/models.py`
- [ ] `TEMPORAL_SCHEMA_SQL` constant with all temporal tables
- [ ] Indexes for `commit_hash`, `commit_date`, `snapshot_id`
- [ ] `temporal/__init__.py` exports public API
- [ ] Unit tests for enum values

---

### Task 2: Create Temporal Data Models

**Priority**: P0 (Foundation - blocks everything)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/models.py` (new)

**Pattern**: Follow `Node` and `Edge` dataclass patterns in `models.py:15-140`, especially `to_dict()`, `to_tuple()`, and `from_row()` methods

**Description**: Create dataclasses for Snapshot, NodeChange, and GraphDiff with full serialization support.

**Implementation**:
```python
@dataclass
class Snapshot:
    id: str
    commit_hash: str
    commit_message: str | None
    commit_author: str | None
    commit_date: datetime | None
    parent_id: str | None
    node_count: int
    edge_count: int
    nodes_added: int = 0
    nodes_removed: int = 0
    nodes_modified: int = 0
    edges_added: int = 0
    edges_removed: int = 0

    def to_dict(self) -> dict[str, Any]: ...
    def to_tuple(self) -> tuple: ...
    @classmethod
    def from_row(cls, row: tuple) -> Snapshot: ...
```

**Acceptance Criteria**:
- [ ] `Snapshot` dataclass with all commit metadata fields
- [ ] `NodeChange` dataclass for per-node history entries
- [ ] `GraphDiff` dataclass for diff between snapshots
- [ ] All models have `to_dict()`, `to_tuple()`, `from_row()` methods
- [ ] Type annotations for all fields
- [ ] Unit tests for serialization round-trip

---

### Task 3: Implement GitIntegration Class

**Priority**: P0 (Required for snapshot creation)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/git.py` (new)

**Pattern**: Follow subprocess usage in `diff/git_utils.py` (referenced in epic)

**Description**: Create GitIntegration class to interface with git for history operations. Handle edge cases like shallow clones and detached HEAD.

**Implementation**:
```python
class GitIntegration:
    def __init__(self, repo_path: Path): ...
    def get_current_commit(self) -> str: ...
    def get_commit_info(self, commit_hash: str) -> dict: ...
    def get_commits(self, since: datetime | None = None) -> list[str]: ...
    def get_changed_files(self, from_commit: str, to_commit: str) -> tuple[list, list, list]: ...
```

**Acceptance Criteria**:
- [ ] `get_current_commit()` returns HEAD hash
- [ ] `get_commit_info()` extracts author, date, message
- [ ] `get_commits()` supports since/until/path filters
- [ ] `get_changed_files()` returns (added, modified, deleted) lists
- [ ] Graceful handling of shallow clones (warn, not error)
- [ ] Error handling for non-git directories
- [ ] Unit tests with mock subprocess

---

### Task 4: Implement SnapshotManager Core

**Priority**: P0 (Core temporal functionality)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/snapshot.py` (new)

**Pattern**: Follow `MUbase` class structure in `mubase.py:23-862`, especially schema initialization and query methods

**Description**: Create SnapshotManager class for creating and managing temporal snapshots. Handle delta calculation from previous snapshot.

**Implementation**:
```python
class SnapshotManager:
    def __init__(self, mubase: MUbase): ...
    def _ensure_temporal_schema(self) -> None: ...
    def create_snapshot(self, commit_hash: str | None = None) -> Snapshot: ...
    def _snapshot_current(self) -> Snapshot: ...
    def _calculate_delta(self, parent: Snapshot | None) -> dict: ...
    def get_snapshot(self, commit_hash: str) -> Snapshot | None: ...
    def list_snapshots(self, limit: int = 100) -> list[Snapshot]: ...
```

**Acceptance Criteria**:
- [ ] Lazy temporal schema initialization (like embeddings)
- [ ] `create_snapshot()` creates snapshot from current or specified commit
- [ ] Delta calculation: nodes_added, nodes_removed, nodes_modified
- [ ] Edge delta calculation
- [ ] `node_history` and `edge_history` table population
- [ ] `body_hash` for change detection
- [ ] Unit tests for snapshot creation

---

### Task 5: Implement Historical Build

**Priority**: P1 (Builds on snapshot creation)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/snapshot.py`

**Pattern**: Follow batch processing pattern in `cli.py:276-289` with progress callback

**Description**: Add `build_with_history()` method to process commits chronologically and create snapshots for each.

**Implementation**:
```python
def build_with_history(
    self,
    commits: list[str] | None = None,
    since: datetime | None = None,
    on_progress: Callable[[int, int], None] | None = None
) -> list[Snapshot]:
    """Build graph history from git commits."""
    if commits is None:
        commits = self.git.get_commits(since=since)
    # Process chronologically, use git worktree for safety
    ...
```

**Acceptance Criteria**:
- [ ] Processes commits in chronological order
- [ ] Uses git worktree or temp dir (never checkout in place)
- [ ] Progress callback for CLI integration
- [ ] Incremental: only rebuild changed files per commit
- [ ] Handles deleted files correctly
- [ ] Handles file renames (detect via git rename detection)
- [ ] Integration test with real git repo fixture

---

### Task 6: Implement MUbaseSnapshot (Temporal View)

**Priority**: P1 (Required for time-travel queries)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/snapshot.py`

**Pattern**: Follow `MUbase` query methods pattern in `mubase.py:133-178`

**Description**: Create read-only view of MUbase at a specific point in time, using node_history and edge_history tables.

**Implementation**:
```python
class MUbaseSnapshot:
    """Read-only view of MUbase at a point in time."""

    def __init__(self, mubase: MUbase, snapshot: Snapshot): ...
    def get_node(self, node_id: str) -> Node | None: ...
    def get_nodes(self, node_type: NodeType | None = None) -> list[Node]: ...
    def get_edges(self) -> list[Edge]: ...
    def stats(self) -> dict[str, Any]: ...
```

**Acceptance Criteria**:
- [ ] All queries filter by `snapshot_id`
- [ ] Returns Node/Edge objects (not raw tuples)
- [ ] Properties reconstructed from `node_history.properties`
- [ ] Handles nodes that didn't exist at snapshot time
- [ ] Read-only (no mutation methods)
- [ ] Unit tests comparing current vs historical state

---

### Task 7: Implement History and Blame Methods

**Priority**: P1 (Core temporal queries)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/history.py` (new)

**Pattern**: Follow query patterns in `mubase.py:218-271` with JOIN statements

**Description**: Implement node history and blame functionality to track changes over time.

**Implementation**:
```python
class HistoryTracker:
    def __init__(self, mubase: MUbase): ...

    def history(self, node_id: str, limit: int = 100) -> list[NodeChange]: ...
    def blame(self, node_id: str) -> dict[str, NodeChange]: ...
    def first_appearance(self, node_id: str) -> NodeChange | None: ...
```

**Acceptance Criteria**:
- [ ] `history()` returns chronological list of changes
- [ ] Each NodeChange includes commit metadata
- [ ] `blame()` returns last change for each property/attribute
- [ ] Filter by date range supported
- [ ] Efficient queries using indexes
- [ ] Unit tests with multi-commit history

---

### Task 8: Implement GraphDiff (Temporal Diff)

**Priority**: P1 (Required for diff commands)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/diff.py` (new)

**Pattern**: Follow `SemanticDiffer` pattern in `diff/differ.py` and `DiffResult` model in `diff/models.py`

**Description**: Compute semantic diff between two snapshots, showing added/removed/modified nodes and edges.

**Implementation**:
```python
class TemporalDiffer:
    def __init__(self, manager: SnapshotManager): ...

    def diff(self, from_commit: str, to_commit: str) -> GraphDiff: ...
    def _diff_nodes(self, from_snap: Snapshot, to_snap: Snapshot) -> ...: ...
    def _diff_edges(self, from_snap: Snapshot, to_snap: Snapshot) -> ...: ...
```

**Acceptance Criteria**:
- [ ] `GraphDiff` contains added/removed/modified nodes and edges
- [ ] Modified nodes show old vs new properties
- [ ] Integrates with existing `diff` module types where possible
- [ ] Handles snapshots that don't exist gracefully
- [ ] Unit tests comparing two known snapshots

---

### Task 9: Add MUQL Temporal Keywords to Grammar

**Priority**: P1 (Required for temporal queries)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/grammar.lark`

**Pattern**: Follow existing keyword pattern in `grammar.lark:154-238` and query type pattern in lines 1-148

**Description**: Extend MUQL grammar with AT, BETWEEN, HISTORY, and BLAME clauses.

**Implementation**:
```lark
// Add to grammar.lark

// Temporal keywords
AT_KW: /at/i
BETWEEN_KW: /between/i
HISTORY_KW: /history/i
BLAME_KW: /blame/i
FIRST_KW: /first/i

// Temporal clauses
at_clause: AT_KW (STRING | IDENTIFIER)
between_clause: BETWEEN_KW (STRING | IDENTIFIER) AND_KW (STRING | IDENTIFIER)

// New query types
history_query: HISTORY_KW OF_KW node_ref [limit_clause]
blame_query: BLAME_KW node_ref

// Modify select_query to accept temporal clauses
select_query: SELECT_KW select_list FROM_KW node_type [where_clause] [at_clause | between_clause] [order_by_clause] [limit_clause]
```

**Acceptance Criteria**:
- [ ] `AT "commit"` clause parses without errors
- [ ] `BETWEEN "commit1" AND "commit2"` clause parses
- [ ] `HISTORY OF NodeName` query type added
- [ ] `BLAME NodeName` query type added
- [ ] No conflicts with existing grammar
- [ ] Unit tests for parsing each new construct

---

### Task 10: Add MUQL Temporal AST Nodes

**Priority**: P1 (Required for temporal queries)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/ast.py`

**Pattern**: Follow existing query type patterns in `ast.py:237-378`

**Description**: Add AST node dataclasses for temporal query constructs.

**Implementation**:
```python
@dataclass
class TemporalClause:
    """Temporal modifier for queries."""
    clause_type: str  # "at" or "between"
    commit1: str
    commit2: str | None = None  # Only for BETWEEN

@dataclass
class HistoryQuery:
    query_type: QueryType = field(default=QueryType.HISTORY, init=False)
    target: NodeRef
    limit: int | None = None

@dataclass
class BlameQuery:
    query_type: QueryType = field(default=QueryType.BLAME, init=False)
    target: NodeRef
```

**Acceptance Criteria**:
- [ ] `TemporalClause` dataclass with commit references
- [ ] `HistoryQuery` dataclass with target and limit
- [ ] `BlameQuery` dataclass with target
- [ ] Add `HISTORY` and `BLAME` to `QueryType` enum
- [ ] All have `to_dict()` methods
- [ ] Update `Query` union type

---

### Task 11: Add MUQL Temporal Transformer

**Priority**: P1 (Required for temporal queries)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/parser.py`

**Pattern**: Follow transformer method patterns in `parser.py:57-622`

**Description**: Add transformer methods to convert temporal grammar rules to AST nodes.

**Implementation**:
```python
# Add to MUQLTransformer class

def at_clause(self, items: list[Any]) -> TemporalClause:
    commit = self._extract_string_or_identifier(items)
    return TemporalClause(clause_type="at", commit1=commit)

def between_clause(self, items: list[Any]) -> TemporalClause:
    commits = [self._extract_string_or_identifier(item) for item in items if ...]
    return TemporalClause(clause_type="between", commit1=commits[0], commit2=commits[1])

def history_query(self, items: list[Any]) -> HistoryQuery:
    ...

def blame_query(self, items: list[Any]) -> BlameQuery:
    ...
```

**Acceptance Criteria**:
- [ ] `at_clause` transformer extracts commit reference
- [ ] `between_clause` transformer extracts both commits
- [ ] `history_query` transformer creates HistoryQuery
- [ ] `blame_query` transformer creates BlameQuery
- [ ] SelectQuery modified to include optional temporal clause
- [ ] Unit tests for each transformer

---

### Task 12: Add MUQL Temporal Executor

**Priority**: P1 (Required for temporal queries)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/muql/executor.py`

**Pattern**: Follow `_execute_sql()` and `_execute_graph()` patterns in existing executor

**Description**: Add executor logic for temporal queries, including AT clause filtering and HISTORY/BLAME queries.

**Implementation**:
```python
# Modify QueryExecutor class

def _execute_temporal_select(self, query: SelectQuery, temporal: TemporalClause) -> QueryResult:
    """Execute SELECT with AT or BETWEEN clause."""
    snapshot = self._get_snapshot(temporal.commit1)
    view = MUbaseSnapshot(self.mubase, snapshot)
    # Execute query against temporal view
    ...

def _execute_history(self, query: HistoryQuery) -> QueryResult:
    """Execute HISTORY OF query."""
    tracker = HistoryTracker(self.mubase)
    changes = tracker.history(query.target.name, query.limit)
    ...

def _execute_blame(self, query: BlameQuery) -> QueryResult:
    """Execute BLAME query."""
    tracker = HistoryTracker(self.mubase)
    blame_info = tracker.blame(query.target.name)
    ...
```

**Acceptance Criteria**:
- [ ] AT clause routes query through MUbaseSnapshot
- [ ] BETWEEN clause shows changes in range
- [ ] HISTORY query returns formatted change list
- [ ] BLAME query returns property attribution
- [ ] Proper error messages for missing snapshots
- [ ] Integration tests with temporal queries

---

### Task 13: Add CLI Temporal Commands

**Priority**: P2 (User-facing commands)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py`

**Pattern**: Follow `kernel_build` and `kernel_stats` patterns in `cli.py:876-1007`

**Description**: Add CLI commands for snapshot management, history, and blame.

**Implementation**:
```python
@kernel.command("snapshot")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--from-git", help="Create snapshot from specific commit")
def kernel_snapshot(path: Path, from_git: str | None) -> None:
    """Create a temporal snapshot of the current graph state."""
    ...

@kernel.command("history")
@click.argument("node_name", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--limit", "-l", type=int, default=20)
def kernel_history(node_name: str, path: Path, limit: int) -> None:
    """Show history of changes to a node."""
    ...

@kernel.command("blame")
@click.argument("node_name", type=str)
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
def kernel_blame(node_name: str, path: Path) -> None:
    """Show last commit for each attribute of a node."""
    ...
```

**Acceptance Criteria**:
- [ ] `mu kernel snapshot` creates snapshot from current state
- [ ] `mu kernel snapshot --from-git <commit>` snapshots specific commit
- [ ] `mu kernel build --with-history` flag added
- [ ] `mu kernel build --with-history --since 2024-01-01` works
- [ ] `mu kernel history <node>` shows timeline
- [ ] `mu kernel blame <node>` shows attribution table
- [ ] `mu kernel diff <commit1> <commit2>` shows semantic diff
- [ ] Progress bars for long operations
- [ ] JSON output option for all commands

---

### Task 14: Integrate Temporal Diff with Existing Diff Module

**Priority**: P2 (Integration with existing features)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/diff.py`
- `/Users/imu/Dev/work/mu/src/mu/cli.py`

**Pattern**: Follow `mu diff` command pattern in `cli.py:564-714`

**Description**: Integrate temporal diff with existing `mu diff` command or provide kernel-specific diff that uses snapshots.

**Implementation**:
```python
# Option 1: Add --kernel flag to existing diff
@cli.command()
@click.option("--kernel", is_flag=True, help="Use kernel snapshots for diff")
def diff(..., kernel: bool) -> None:
    if kernel:
        # Use temporal snapshots instead of parsing both refs
        manager = SnapshotManager(mubase)
        result = manager.diff(base_ref, target_ref)
        ...

# Option 2: Separate kernel diff command
@kernel.command("diff")
def kernel_diff(commit1: str, commit2: str, path: Path) -> None:
    ...
```

**Acceptance Criteria**:
- [ ] `mu kernel diff <commit1> <commit2>` works with snapshots
- [ ] Output format matches existing `mu diff` where possible
- [ ] Shows: added/removed/modified nodes and edges
- [ ] Highlights dependency changes
- [ ] JSON/markdown/table output formats
- [ ] Falls back gracefully if snapshots don't exist

---

### Task 15: Add AT Clause to MUQL Query Command

**Priority**: P2 (User-facing temporal queries)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py`

**Pattern**: Follow `kernel_muql` command pattern in `cli.py:1116-1207`

**Description**: Extend MUQL CLI to support temporal queries with --at flag as alternative to AT clause.

**Implementation**:
```python
@kernel.command("muql")
@click.option("--at", "at_commit", help="Query state at specific commit")
def kernel_muql(..., at_commit: str | None) -> None:
    # If --at provided, wrap query with temporal context
    if at_commit:
        # Either modify query or use MUbaseSnapshot directly
        ...
```

**Acceptance Criteria**:
- [ ] `mu kernel muql . "SELECT * FROM functions" --at abc123` works
- [ ] Temporal clause in query itself also works
- [ ] Error message if no snapshot exists for commit
- [ ] Interactive REPL supports temporal context switch

---

### Task 16: Write Comprehensive Tests

**Priority**: P1 (Quality assurance)
**Files**:
- `/Users/imu/Dev/work/mu/tests/unit/test_temporal.py` (new)
- `/Users/imu/Dev/work/mu/tests/fixtures/temporal_repo/` (new)

**Pattern**: Follow test class organization in `tests/CLAUDE.md` and existing `tests/unit/test_kernel.py`

**Description**: Create comprehensive test suite for all temporal functionality.

**Implementation**:
```python
class TestSnapshot:
    def test_create_snapshot_current_state(self, mubase_with_graph): ...
    def test_create_snapshot_from_commit(self, git_repo_with_commits): ...
    def test_delta_calculation(self): ...

class TestMUbaseSnapshot:
    def test_get_node_at_snapshot(self): ...
    def test_node_not_exists_at_old_snapshot(self): ...

class TestHistory:
    def test_node_history(self): ...
    def test_blame(self): ...

class TestTemporalMUQL:
    def test_parse_at_clause(self): ...
    def test_parse_history_query(self): ...
    def test_execute_select_at_commit(self): ...
```

**Acceptance Criteria**:
- [ ] Unit tests for all temporal models
- [ ] Unit tests for GitIntegration with mock subprocess
- [ ] Unit tests for SnapshotManager
- [ ] Unit tests for MUbaseSnapshot
- [ ] Unit tests for HistoryTracker
- [ ] Unit tests for MUQL temporal parsing
- [ ] Unit tests for MUQL temporal execution
- [ ] Integration test with real git repo fixture
- [ ] All tests pass with `pytest tests/unit/test_temporal.py`

---

### Task 17: Add Temporal CLAUDE.md Documentation

**Priority**: P2 (Developer documentation)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/temporal/CLAUDE.md` (new)

**Pattern**: Follow existing CLAUDE.md files in `src/mu/kernel/CLAUDE.md` and `src/mu/kernel/muql/CLAUDE.md`

**Description**: Create comprehensive documentation for the temporal layer module.

**Acceptance Criteria**:
- [ ] Architecture overview diagram
- [ ] File structure table
- [ ] Usage examples for all major features
- [ ] Anti-patterns section
- [ ] Testing instructions

---

## Dependencies

```
Task 1 (Schema) ──┬──> Task 2 (Models) ──┬──> Task 4 (SnapshotManager)
                  │                       │
Task 3 (Git) ─────┴───────────────────────┘
                                          │
                                          ├──> Task 5 (Historical Build)
                                          │
                                          ├──> Task 6 (MUbaseSnapshot)
                                          │         │
                                          │         └──> Task 12 (MUQL Executor)
                                          │
                                          ├──> Task 7 (History/Blame)
                                          │         │
                                          │         └──> Task 12 (MUQL Executor)
                                          │
                                          └──> Task 8 (GraphDiff) ──> Task 14 (Diff Integration)

Task 9 (Grammar) ──> Task 10 (AST) ──> Task 11 (Transformer) ──> Task 12 (MUQL Executor)

Task 4-8, 12 ──> Task 13 (CLI Commands)

Task 13 ──> Task 15 (MUQL AT flag)

All ──> Task 16 (Tests)

Task 16 ──> Task 17 (Documentation)
```

---

## Implementation Order

**Phase 1: Foundation (Tasks 1-4)**
1. Task 1: Schema and Enums
2. Task 2: Data Models
3. Task 3: GitIntegration
4. Task 4: SnapshotManager Core

**Phase 2: Temporal Views (Tasks 5-8)**
5. Task 5: Historical Build
6. Task 6: MUbaseSnapshot
7. Task 7: History and Blame
8. Task 8: GraphDiff

**Phase 3: MUQL Integration (Tasks 9-12)**
9. Task 9: Grammar Extension
10. Task 10: AST Nodes
11. Task 11: Transformer
12. Task 12: Executor

**Phase 4: CLI and Integration (Tasks 13-15)**
13. Task 13: CLI Commands
14. Task 14: Diff Integration
15. Task 15: MUQL AT Flag

**Phase 5: Quality (Tasks 16-17)**
16. Task 16: Comprehensive Tests
17. Task 17: Documentation

---

## Edge Cases

1. **Shallow clone**: Git history may be incomplete - detect and warn user
2. **Detached HEAD**: Handle gracefully, use commit hash instead of branch name
3. **Large history**: Limit default commit range, add `--since` flag
4. **Deleted files**: Mark nodes as removed in snapshot, preserve in history
5. **Renamed files**: Use git rename detection, link old/new node IDs
6. **Merge commits**: Handle multiple parents, show merge context
7. **Force push/rebase**: Warn if commit hashes don't match existing snapshots
8. **Binary files**: Skip gracefully, don't include in graph
9. **No embeddings**: Temporal queries work without embeddings (graceful degradation)
10. **Empty repository**: Error gracefully before any git operations

---

## Security Considerations

1. **Git checkout safety**: Never checkout in place; use worktree or temp directory
2. **Command injection**: All git commands use subprocess with list arguments (not shell=True)
3. **Path traversal**: Validate all paths are within repository root
4. **Large repos**: Set reasonable limits on commit count to prevent resource exhaustion

---

## Performance Considerations

1. **Delta storage**: Only store changes, not full state at each snapshot
2. **Lazy loading**: Don't load temporal schema until first temporal operation
3. **Indexed queries**: All temporal queries use indexed columns
4. **Batch processing**: Historical build processes commits in batches
5. **Progress callbacks**: Long operations report progress for CLI feedback
