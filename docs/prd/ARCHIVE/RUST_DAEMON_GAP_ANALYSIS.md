# Rust Daemon Migration - Phase 1 Gap Analysis

**Date:** 2025-12-08
**Status:** Complete

## Executive Summary

The Rust daemon has **more features than expected**. Most core endpoints exist and work. The gaps are primarily around:
1. Multi-project support (ProjectManager)
2. Export endpoint
3. Contract verification
4. Neighbor traversal endpoint
5. Minor response format differences

**Estimated Phase 2 effort: 2-3 days** (reduced from 3-5 days)

---

## Python Daemon Endpoints (port 8765)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/status` | GET | Daemon status + stats + language stats |
| `/nodes/{id}` | GET | Node lookup by ID |
| `/nodes/{id}/neighbors` | GET | Neighbor traversal (direction param) |
| `/query` | POST | MUQL execution |
| `/context` | POST | Smart context extraction |
| `/impact` | POST | Downstream impact analysis |
| `/ancestors` | POST | Upstream dependency analysis |
| `/cycles` | POST | Circular dependency detection |
| `/export` | GET | Multi-format graph export |
| `/contracts/verify` | POST | Architecture contract verification |
| `/live` | WS | Real-time graph updates |

**Multi-project support:** All endpoints accept `cwd` parameter to route to correct .mubase

---

## Rust Daemon Endpoints (port 9120)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Simple health check |
| `/status` | GET | Node/edge count, root path |
| `/node/:id` | GET | Node lookup by ID |
| `/nodes` | POST | Batch node lookup (extra!) |
| `/query` | POST | MUQL execution |
| `/context` | POST | Smart context extraction |
| `/deps` | POST | Dependency analysis (extra!) |
| `/impact` | POST | Downstream impact analysis |
| `/ancestors` | POST | Upstream dependency analysis |
| `/cycles` | POST | Circular dependency detection |
| `/build` | POST | Trigger graph rebuild (extra!) |
| `/scan` | POST | Scan directory (extra!) |
| `/ws` | WS | Real-time graph updates |

**MCP mode:** Rust daemon also supports `--mcp` flag for stdio MCP protocol

---

## Gap Analysis

### ✅ Already Implemented in Rust

| Feature | Python | Rust | Notes |
|---------|--------|------|-------|
| Health/status | ✅ | ✅ | Rust has simpler response |
| Node lookup | ✅ | ✅ | Same functionality |
| MUQL query | ✅ | ✅ | Same functionality |
| Context extraction | ✅ | ✅ | Same functionality |
| Impact analysis | ✅ | ✅ | Same functionality |
| Ancestors analysis | ✅ | ✅ | Same functionality |
| Cycle detection | ✅ | ✅ | Same functionality |
| WebSocket live updates | ✅ | ✅ | Rust uses `/ws`, Python uses `/live` |
| MCP stdio mode | ✅ | ✅ | Both support it |

### 🔶 Minor Differences (Easy Fix)

| Feature | Gap | Effort |
|---------|-----|--------|
| Status response | Rust missing `language_stats`, `uptime_seconds`, `connections`, `active_projects` | 1 hour |
| WebSocket path | Rust: `/ws`, Python: `/live` | 5 min (add alias) |
| Node path | Rust: `/node/:id`, Python: `/nodes/{id}` | 5 min (add alias) |

### ❌ Missing in Rust (Need Implementation)

| Feature | Description | Effort | Priority |
|---------|-------------|--------|----------|
| **Multi-project support** | `ProjectManager` - route requests to correct .mubase based on `cwd` | 4-6 hours | HIGH |
| **Neighbors endpoint** | `GET /nodes/{id}/neighbors` with direction param | 1-2 hours | MEDIUM |
| **Export endpoint** | `GET /export` - MU, JSON, Mermaid, D2, Cytoscape formats | 2-3 hours | MEDIUM |
| **Contract verification** | `POST /contracts/verify` - check architectural rules | 3-4 hours | LOW |

### ✨ Rust Has Extra Features

| Feature | Description |
|---------|-------------|
| `/nodes` batch | Get multiple nodes in one request |
| `/build` | Trigger graph rebuild via HTTP |
| `/scan` | Scan directory without building |
| `/deps` | Explicit dependency endpoint (Python uses MUQL) |

---

## Detailed Implementation Tasks

### Task 1: Multi-Project Support (HIGH PRIORITY)

**Files to modify:** `mu-daemon/src/server/state.rs`, `mu-daemon/src/server/http.rs`

```rust
// New: mu-daemon/src/server/projects.rs

pub struct ProjectManager {
    default_mubase: Arc<RwLock<MUbase>>,
    default_root: PathBuf,
    cache: DashMap<PathBuf, Arc<RwLock<MUbase>>>,
}

impl ProjectManager {
    pub async fn get_mubase(&self, cwd: Option<&str>) -> Result<Arc<RwLock<MUbase>>> {
        // Find nearest .mu/mubase for cwd
        // Cache and return
    }
}
```

**Changes needed:**
1. Add `cwd` parameter to all request structs
2. Create `ProjectManager` struct
3. Modify handlers to use ProjectManager
4. Update AppState to include ProjectManager

### Task 2: Enhanced Status Response

**File:** `mu-daemon/src/server/http.rs`

```rust
#[derive(Serialize)]
struct StatusResponse {
    status: String,           // NEW: "running"
    node_count: usize,
    edge_count: usize,
    root: String,
    mubase_path: String,      // NEW
    language_stats: HashMap<String, usize>,  // NEW
    connections: usize,       // NEW: WebSocket count
    uptime_seconds: f64,      // NEW
    active_projects: usize,   // NEW
    project_paths: Vec<String>, // NEW
}
```

### Task 3: Neighbors Endpoint

**File:** `mu-daemon/src/server/http.rs`

```rust
#[derive(Deserialize)]
struct NeighborsRequest {
    #[serde(default = "default_direction")]
    direction: String,  // "outgoing", "incoming", "both"
}

async fn get_neighbors(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    Query(params): Query<NeighborsRequest>,
) -> impl IntoResponse {
    // Use graph.get_neighbors(id, direction)
}
```

### Task 4: Export Endpoint

**File:** `mu-daemon/src/server/http.rs`

```rust
#[derive(Deserialize)]
struct ExportParams {
    format: String,           // mu, json, mermaid, d2, cytoscape
    nodes: Option<String>,    // Comma-separated node IDs
    types: Option<String>,    // Comma-separated node types
    max_nodes: Option<usize>,
}

async fn export_graph(
    State(state): State<Arc<AppState>>,
    Query(params): Query<ExportParams>,
) -> impl IntoResponse {
    // Call Python mu kernel export or implement in Rust
}
```

**Decision needed:** Port Python export logic to Rust, or call Python via HTTP?

### Task 5: Contract Verification (LOW PRIORITY)

Can defer to Phase 3+ since contracts are rarely used in CLI workflows.

---

## Response Format Alignment

### Query Response

Python:
```json
{
  "result": {"columns": [...], "rows": [...]},
  "success": true,
  "error": null
}
```

Rust:
```json
{
  "success": true,
  "data": {"columns": [...], "rows": [...], "count": 10},
  "error": null,
  "duration_ms": 5
}
```

**Action:** Rust format is better (includes `count` and `duration_ms`). Update Python client to handle both.

### Impact/Ancestors Response

Python returns structured response:
```json
{
  "node_id": "...",
  "impacted_nodes": ["..."],
  "count": 5
}
```

Rust returns array directly:
```json
{
  "success": true,
  "data": ["node1", "node2", ...],
  "duration_ms": 3
}
```

**Action:** Either format works. Document the difference or add wrapper.

---

## Phase 2 Implementation Order

1. **Multi-project support** (4-6h) - Critical for CLI parity
2. **Enhanced status response** (1h) - Quick win
3. **Neighbors endpoint** (2h) - Needed for graph exploration
4. **WebSocket/node path aliases** (10min) - Compatibility
5. **Export endpoint** (3h) - Nice to have
6. **Contract verification** (4h) - Can defer

**Total: 14-18 hours (~2-3 days)**

---

## Files to Create/Modify

### New Files (Rust)
```
mu-daemon/src/server/projects.rs     # Multi-project manager
```

### Modified Files (Rust)
```
mu-daemon/src/server/mod.rs          # Export projects module
mu-daemon/src/server/state.rs        # Add ProjectManager to AppState
mu-daemon/src/server/http.rs         # All endpoint changes
mu-daemon/Cargo.toml                 # Add dashmap dependency
```

---

## Conclusion

The migration is **easier than expected**. The Rust daemon already has 80% of the functionality. The main work is:

1. Multi-project support (~40% of Phase 2 effort)
2. Minor endpoint additions and response format tweaks (~60%)

**Recommendation:** Proceed with Phase 2 implementation, starting with multi-project support.
