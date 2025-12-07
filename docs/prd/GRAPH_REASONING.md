# PRD: Graph Reasoning Engine (petgraph)

## Overview

**Project:** MU Graph Reasoning - High-performance graph algorithms for dependency analysis
**Status:** Phase 1 Complete
**Module:** `mu-core/src/graph.rs` + `src/mu/kernel/graph.py`
**Dependencies:** petgraph 0.6, Rust Core (mu-core)

## Problem Statement

DuckDB excels at storing and querying the code graph (nodes, edges, properties), but SQL is fundamentally limited for **graph traversals**:

- Finding circular imports requires recursive CTEs (slow, complex, depth-limited)
- Impact analysis ("what breaks if I change X?") needs transitive closure
- Path finding between modules is O(n²) in SQL

**Solution:** Load the graph topology into `petgraph::DiGraph` in Rust, expose O(V+E) algorithms to Python via PyO3.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Python Layer                          │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────┐   │
│  │   MUQL      │───▶│ GraphManager │───▶│ MCP Tools     │   │
│  │  Queries    │    │  (kernel/)   │    │ (mu_deps etc) │   │
│  └─────────────┘    └──────┬───────┘    └───────────────┘   │
│                            │                                 │
├────────────────────────────┼────────────────────────────────┤
│                        Rust Layer (mu-core)                  │
│                            ▼                                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                   GraphEngine                        │    │
│  │  ┌───────────┐  ┌───────────┐  ┌─────────────────┐  │    │
│  │  │ DiGraph   │  │ node_map  │  │  Algorithms     │  │    │
│  │  │ <String,  │  │ String -> │  │  - shortest_path│  │    │
│  │  │  String>  │  │ NodeIndex │  │  - find_cycles  │  │    │
│  │  └───────────┘  └───────────┘  │  - impact       │  │    │
│  │                                │  - ancestors    │  │    │
│  │                                └─────────────────┘  │    │
│  └─────────────────────────────────────────────────────┘    │
│                            ▲                                 │
├────────────────────────────┼────────────────────────────────┤
│                      Storage Layer                           │
│                            │                                 │
│  ┌─────────────────────────┴───────────────────────────┐    │
│  │                     DuckDB                           │    │
│  │            nodes table  │  edges table               │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## API Contract

### Rust: `GraphEngine` (PyO3 class)

```rust
#[pyclass]
pub struct GraphEngine { /* internal state */ }

#[pymethods]
impl GraphEngine {
    /// Construct from node IDs and edge tuples
    #[new]
    fn new(nodes: Vec<String>, edges: Vec<(String, String, String)>) -> Self;

    /// All strongly connected components with >1 node (cycles)
    /// edge_types: Optional filter (e.g., ["imports"] for import cycles only)
    fn find_cycles(&self, edge_types: Option<Vec<String>>) -> Vec<Vec<String>>;

    /// All nodes reachable FROM this node (downstream impact)
    /// "If I change X, what might break?"
    fn impact(&self, node_id: &str, edge_types: Option<Vec<String>>) -> Vec<String>;

    /// All nodes that can REACH this node (upstream ancestors)
    /// "What does X depend on?"
    fn ancestors(&self, node_id: &str, edge_types: Option<Vec<String>>) -> Vec<String>;

    /// Shortest path between two nodes (None if unreachable)
    fn shortest_path(&self, from_id: &str, to_id: &str, edge_types: Option<Vec<String>>) -> Option<Vec<String>>;

    /// Direct neighbors with direction and depth control
    fn neighbors(&self, node_id: &str, direction: &str, depth: usize, edge_types: Option<Vec<String>>) -> Vec<String>;

    /// Utility methods
    fn node_count(&self) -> usize;
    fn edge_count(&self) -> usize;
    fn has_node(&self, node_id: &str) -> bool;
    fn edge_types(&self) -> Vec<String>;
}
```

### Python: `GraphManager`

```python
from mu.kernel import GraphManager

class GraphManager:
    """Manages petgraph engine lifecycle and provides high-level API."""

    def __init__(self, db: duckdb.DuckDBPyConnection): ...
    def load(self) -> GraphStats: ...  # Hydrate from DuckDB
    def is_loaded(self) -> bool: ...

    # Delegate to Rust engine
    def find_cycles(self, edge_types: list[str] | None = None) -> list[list[str]]: ...
    def impact(self, node_id: str, edge_types: list[str] | None = None) -> list[str]: ...
    def ancestors(self, node_id: str, edge_types: list[str] | None = None) -> list[str]: ...
    def shortest_path(self, from_id: str, to_id: str, edge_types: list[str] | None = None) -> list[str] | None: ...
    def neighbors(self, node_id: str, direction: str = "both", depth: int = 1, edge_types: list[str] | None = None) -> list[str]: ...
```

## Performance Bounds

| Metric | Expected | Notes |
|--------|----------|-------|
| Load time (10k nodes) | <50ms | HashMap construction |
| Load time (100k nodes) | <500ms | Linear scaling |
| Memory (10k nodes) | ~5MB | petgraph overhead minimal |
| Memory (100k nodes) | ~50MB | Acceptable for daemon |
| `find_cycles()` | O(V+E) | Kosaraju's algorithm |
| `impact()` | O(V+E) | BFS traversal |
| `shortest_path()` | O(V+E) | BFS (unweighted) |

**Upper Bound:** Codebases >500k nodes should consider lazy loading or partitioning.

## Implementation Phases

### Phase 1: Foundation ✅ COMPLETE

**Status:** Merged to `refactor/cli-lazy-loading` branch

**Files Created:**
- `mu-core/src/graph.rs` - Full GraphEngine implementation (390 lines)
- `src/mu/kernel/graph.py` - Python GraphManager wrapper
- `tests/unit/test_rust_core.py` - 17 Python tests for GraphEngine

**Files Modified:**
- `mu-core/Cargo.toml` - Added `petgraph = "0.6"`
- `mu-core/src/lib.rs` - Registered `graph` module + `GraphEngine` class
- `src/mu/kernel/__init__.py` - Exported `GraphManager`, `GraphStats`

**Test Results:**
- Rust: 11 unit tests passing (`cargo test graph`)
- Python: 17 integration tests passing (`pytest -k GraphEngine`)

**Key Design Decisions:**
1. **Edge Type Filtering (P0)** - All traversal methods support filtering by relationship type
2. **O(V+E) Algorithms** - Kosaraju for cycles, BFS for traversals
3. **Clean separation** - DuckDB for storage, petgraph for reasoning

---

### Phase 2: MUQL Integration (Planned)

**Status:** Not Started

**Goal:** Add graph algorithm syntax to MUQL query language.

**New Query Types:**
```sql
-- Find all circular dependencies
FIND CYCLES
FIND CYCLES WHERE edge_type = 'imports'

-- Impact analysis
SHOW IMPACT OF "mod:src/auth.py"
SHOW IMPACT OF "mod:src/auth.py" WHERE edge_type IN ('imports', 'calls')

-- Ancestor analysis
SHOW ANCESTORS OF "func:process_payment"
SHOW ANCESTORS OF "func:process_payment" DEPTH 3

-- Path finding
FIND PATH FROM "mod:a.py" TO "mod:z.py"
FIND PATH FROM "mod:a.py" TO "mod:z.py" WHERE edge_type = 'imports'
```

**Files to Modify:**
- `src/mu/muql/parser.py` - Add FIND CYCLES, SHOW IMPACT, SHOW ANCESTORS, FIND PATH syntax
- `src/mu/muql/executor.py` - Route graph queries to GraphManager
- `src/mu/muql/ast.py` - Add AST nodes for graph queries

**Acceptance Criteria:**
- [ ] `mu q "FIND CYCLES"` returns circular import chains
- [ ] `mu q "SHOW IMPACT OF 'mod:src/auth.py'"` returns downstream nodes
- [ ] `mu q "SHOW ANCESTORS OF 'func:login'"` returns upstream dependencies
- [ ] `mu q "FIND PATH FROM 'mod:a.py' TO 'mod:z.py'"` returns shortest path
- [ ] Edge type filtering works in all graph queries

---

### Phase 3: MCP Enhancement (Planned)

**Status:** Not Started

**Goal:** Enhance MCP tools to use petgraph for deeper traversals.

**Current Limitation:**
`mu_deps` tool uses SQL with recursive CTEs, which becomes slow/impractical beyond depth 2-3.

**Enhancement:**
```python
# Current: SQL-backed (slow beyond depth 2)
def mu_deps(node_name: str, depth: int = 2, direction: str = "outgoing"):
    # Uses recursive CTE in DuckDB
    ...

# New: petgraph-backed (fast to any depth)
def mu_deps(node_name: str, depth: int = 2, direction: str = "outgoing"):
    if depth > 2:
        # Use GraphManager for deep traversals
        gm = GraphManager(db.conn)
        gm.load()
        return gm.neighbors(node_name, direction, depth)
    else:
        # SQL is fine for shallow queries
        ...
```

**New MCP Tools:**
```python
@mcp_tool
def mu_cycles(edge_types: list[str] | None = None) -> list[list[str]]:
    """Find circular dependencies in the codebase."""
    gm = GraphManager(db.conn)
    gm.load()
    return gm.find_cycles(edge_types)

@mcp_tool
def mu_impact(node_id: str, edge_types: list[str] | None = None) -> list[str]:
    """Find all nodes affected by changes to the given node."""
    gm = GraphManager(db.conn)
    gm.load()
    return gm.impact(node_id, edge_types)
```

**Files to Modify:**
- `src/mu/mcp/tools.py` - Add `mu_cycles`, `mu_impact` tools
- `src/mu/mcp/tools.py` - Update `mu_deps` to use petgraph for depth > 2

**Acceptance Criteria:**
- [ ] `mu_deps` with depth > 2 uses petgraph (faster)
- [ ] New `mu_cycles` tool exposed via MCP
- [ ] New `mu_impact` tool exposed via MCP
- [ ] All tools support edge type filtering

---

### Phase 4: Subgraph Extraction (Future)

**Status:** Backlog

**Goal:** Extract minimized subgraphs for context windows.

**Use Case:**
```python
# Query: "Give me the auth subsystem"
# Result: A minimized graph containing only nodes reachable from AuthService

subgraph = gm.extract_subgraph(
    roots=["cls:src/auth/service.py:AuthService"],
    depth=3,
    edge_types=["imports", "contains"]
)
```

**Integration with Smart Context:**
This fits naturally with `mu kernel context "question"` - the context extractor could use subgraph extraction to find relevant code clusters.

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Use `DiGraph<String, String>` | Simple, debuggable, no custom structs needed |
| Kosaraju for cycles | O(V+E), battle-tested, in petgraph stdlib |
| Reload full graph on change | Simpler than incremental updates, fast enough |
| No edge weights initially | YAGNI - add when needed for "importance" ranking |
| Edge type filtering is P0 | Critical for distinguishing imports vs calls vs inherits |

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Memory bloat on large repos | Low | Document bounds, lazy load option in Phase 4 |
| Stale graph after DB update | Medium | Explicit `load()` call, daemon hook |
| Edge type confusion | Low | Use string types, document conventions |

## References

- [petgraph documentation](https://docs.rs/petgraph/latest/petgraph/)
- [Kosaraju's algorithm](https://en.wikipedia.org/wiki/Kosaraju%27s_algorithm)
- RUST_CORE PRD: `docs/prd/RUST_CORE.md`
- Kernel CLAUDE.md: `src/mu/kernel/CLAUDE.md`
