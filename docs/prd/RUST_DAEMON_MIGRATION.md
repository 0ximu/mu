# PRD: Rust Daemon Migration & Registry Implementation

**Version:** 1.0
**Date:** 2025-12-08
**Author:** Claude (Opus 4.5)
**Status:** Draft

## Executive Summary

Migrate MU from the Python FastAPI daemon (port 8765) to the Rust Axum daemon (port 9120), then implement the daemon discovery registry in Rust. This consolidates the codebase, improves performance, and solves BUG-001 (orphan daemon process causing data leakage).

## Current State

### Two Daemons Exist

| Aspect | Python Daemon | Rust Daemon |
|--------|---------------|-------------|
| Location | `src/mu/daemon/` | `mu-daemon/` |
| Port | 8765 | 9120 |
| Framework | FastAPI | Axum |
| Status | **Active** (CLI uses this) | **Dormant** (not integrated) |
| Features | Full MCP routing | HTTP + MCP modes |

### Problem

- CLI/MCP tools hardcoded to port 8765 (Python daemon)
- Rust daemon exists but isn't wired up
- BUG-001 affects Python daemon - no point fixing it if we're migrating
- Maintaining two daemons is technical debt

## Goals

1. **Single daemon** - Rust only, remove Python daemon
2. **Full feature parity** - All Python daemon features in Rust
3. **Registry implementation** - Solve BUG-001 in Rust
4. **Zero regression** - All existing tests pass

## Non-Goals

- Rewriting MCP server (stays in Python, calls Rust daemon)
- Changing CLI interface (same commands, different backend)
- Performance optimization beyond parity

---

## Phase 1: Rust Daemon Feature Audit

**Duration:** 1 day
**Goal:** Identify gaps between Python and Rust daemons

### Tasks

#### 1.1 Audit Python Daemon Endpoints

Document all endpoints in `src/mu/daemon/server.py`:

```
GET  /status              - Daemon status + stats
GET  /nodes/{id}          - Node lookup
GET  /nodes/{id}/neighbors - Neighbor traversal
POST /query               - MUQL execution
POST /context             - Smart context extraction
POST /impact              - Downstream impact analysis
POST /ancestors           - Upstream dependency analysis
POST /cycles              - Circular dependency detection
GET  /export              - Graph export (multiple formats)
POST /contracts/verify    - Architecture contract verification
WS   /live                - Real-time updates
```

#### 1.2 Audit Rust Daemon Endpoints

Check `mu-daemon/src/server/` for existing endpoints:

```bash
grep -r "get\|post\|route" mu-daemon/src/server/
```

#### 1.3 Create Gap Analysis

| Endpoint | Python | Rust | Action |
|----------|--------|------|--------|
| `/status` | ✅ | ? | Verify/Add |
| `/query` | ✅ | ? | Verify/Add |
| `/context` | ✅ | ? | Verify/Add |
| `/impact` | ✅ | ? | Verify/Add |
| `/ancestors` | ✅ | ? | Verify/Add |
| `/cycles` | ✅ | ? | Verify/Add |
| `/export` | ✅ | ? | Verify/Add |
| `/contracts/verify` | ✅ | ? | Verify/Add |
| `/live` (WS) | ✅ | ? | Verify/Add |

### Deliverables

- [ ] Gap analysis document
- [ ] List of endpoints to implement in Rust
- [ ] Estimated effort for Phase 2

---

## Phase 2: Rust Daemon Feature Parity

**Duration:** 3-5 days
**Goal:** Implement missing endpoints in Rust daemon

### Tasks

#### 2.1 Implement Missing Endpoints

For each missing endpoint from gap analysis:

```rust
// mu-daemon/src/server/routes.rs

// Example: Add /impact endpoint
async fn impact_handler(
    State(state): State<AppState>,
    Json(req): Json<ImpactRequest>,
) -> Result<Json<ImpactResponse>, AppError> {
    let graph = state.graph.read().await;
    let impacted = graph.impact(&req.node_id, req.edge_types.as_deref())?;
    Ok(Json(ImpactResponse {
        node_id: req.node_id,
        impacted_nodes: impacted,
        count: impacted.len(),
    }))
}
```

#### 2.2 Add Multi-Project Support

Port `ProjectManager` logic from Python:

```rust
// mu-daemon/src/server/projects.rs

pub struct ProjectManager {
    default_mubase: Arc<RwLock<MUbase>>,
    default_path: PathBuf,
    cache: DashMap<PathBuf, Arc<RwLock<MUbase>>>,
}

impl ProjectManager {
    pub async fn get_mubase(&self, cwd: Option<&str>) -> Result<Arc<RwLock<MUbase>>> {
        // Find nearest .mu/mubase for cwd
        // Cache and return
    }
}
```

#### 2.3 Add Contract Verification

Port from `src/mu/contracts/`:

```rust
// mu-daemon/src/contracts/mod.rs

pub struct ContractVerifier {
    mubase: Arc<RwLock<MUbase>>,
}

impl ContractVerifier {
    pub fn verify(&self, contracts: &[Contract]) -> VerificationResult {
        // Verify architectural rules against graph
    }
}
```

#### 2.4 Add WebSocket Support

```rust
// mu-daemon/src/server/websocket.rs

async fn websocket_handler(
    ws: WebSocketUpgrade,
    State(state): State<AppState>,
) -> impl IntoResponse {
    ws.on_upgrade(|socket| handle_socket(socket, state))
}

async fn handle_socket(mut socket: WebSocket, state: AppState) {
    // Subscribe to watcher events
    // Broadcast graph updates to client
}
```

### Deliverables

- [ ] All Python endpoints ported to Rust
- [ ] Multi-project support working
- [ ] WebSocket live updates working
- [ ] Contract verification working

---

## Phase 3: CLI Integration

**Duration:** 1-2 days
**Goal:** Wire CLI to use Rust daemon

### Tasks

#### 3.1 Update Default Port

```python
# src/mu/client.py
DEFAULT_DAEMON_URL = "http://localhost:9120"  # Was 8765
```

#### 3.2 Update Daemon Commands

```python
# src/mu/commands/daemon/start.py
@click.option("--port", "-p", type=int, default=9120, help="Server port")

# src/mu/commands/daemon/run.py
@click.option("--port", "-p", type=int, default=9120, help="Server port")
```

#### 3.3 Update DaemonClient

Ensure client works with Rust daemon's response format:

```python
# src/mu/client.py

class DaemonClient:
    def query(self, muql: str, cwd: str | None = None) -> dict[str, Any]:
        # Verify response format matches Rust daemon
        pass
```

#### 3.4 Add Rust Daemon Binary Management

```python
# src/mu/daemon/lifecycle.py

def _get_daemon_binary() -> Path:
    """Find mu-daemon binary."""
    # Check: installed via cargo
    # Check: bundled with package
    # Check: development build
    return Path("mu-daemon")

def start_background(self, root: Path) -> int:
    binary = _get_daemon_binary()
    proc = subprocess.Popen(
        [str(binary), str(root), "--port", str(self.config.port)],
        ...
    )
    return proc.pid
```

### Deliverables

- [ ] CLI uses port 9120 by default
- [ ] `mu daemon start` launches Rust binary
- [ ] `mu daemon stop` kills Rust process
- [ ] All MCP tools work with Rust daemon

---

## Phase 4: Daemon Registry (BUG-001 Fix)

**Duration:** 2-3 days
**Goal:** Implement global daemon registry in Rust

### Design

#### Registry Location

```
~/.mu/daemons.json
```

#### Registry Schema

```json
{
  "version": 1,
  "daemons": [
    {
      "project_path": "/Users/imu/Dev/work/mu",
      "pid": 12345,
      "port": 9120,
      "mubase_path": "/Users/imu/Dev/work/mu/.mu/mubase",
      "started_at": "2025-12-08T10:30:00Z",
      "last_heartbeat": "2025-12-08T11:30:00Z"
    }
  ]
}
```

### Tasks

#### 4.1 Create Registry Module (Rust)

```rust
// mu-daemon/src/registry.rs

use std::path::PathBuf;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct DaemonEntry {
    pub project_path: PathBuf,
    pub pid: u32,
    pub port: u16,
    pub mubase_path: PathBuf,
    pub started_at: chrono::DateTime<chrono::Utc>,
    pub last_heartbeat: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DaemonRegistry {
    pub version: u32,
    pub daemons: Vec<DaemonEntry>,
}

impl DaemonRegistry {
    pub fn path() -> PathBuf {
        dirs::home_dir().unwrap().join(".mu").join("daemons.json")
    }

    pub fn load() -> Result<Self> {
        // Load from file, create if missing
    }

    pub fn save(&self) -> Result<()> {
        // Atomic write with file locking
    }

    pub fn register(&mut self, entry: DaemonEntry) -> Result<()> {
        // Add entry, save
    }

    pub fn deregister(&mut self, project_path: &Path) -> Result<()> {
        // Remove entry, save
    }

    pub fn find_by_project(&self, project_path: &Path) -> Option<&DaemonEntry> {
        self.daemons.iter().find(|e| e.project_path == project_path)
    }

    pub fn find_by_port(&self, port: u16) -> Option<&DaemonEntry> {
        self.daemons.iter().find(|e| e.port == port)
    }

    pub fn cleanup_stale(&mut self) -> Vec<DaemonEntry> {
        // Check each PID, remove if dead
    }
}
```

#### 4.2 Register on Startup

```rust
// mu-daemon/src/main.rs

#[tokio::main]
async fn main() -> Result<()> {
    // ... existing setup ...

    // Register in global registry
    let mut registry = DaemonRegistry::load()?;
    registry.cleanup_stale();

    // Check for port conflict
    if let Some(existing) = registry.find_by_port(cli.port) {
        if existing.project_path != root {
            anyhow::bail!(
                "Port {} already in use by daemon for {:?}. \
                 Use --port to specify a different port.",
                cli.port,
                existing.project_path
            );
        }
    }

    registry.register(DaemonEntry {
        project_path: root.clone(),
        pid: std::process::id(),
        port: cli.port,
        mubase_path: mubase_path.clone(),
        started_at: chrono::Utc::now(),
        last_heartbeat: chrono::Utc::now(),
    })?;

    // Deregister on shutdown
    let registry_cleanup = registry.clone();
    let root_cleanup = root.clone();
    tokio::spawn(async move {
        tokio::signal::ctrl_c().await.ok();
        registry_cleanup.deregister(&root_cleanup).ok();
    });

    // ... start server ...
}
```

#### 4.3 Add Heartbeat

```rust
// mu-daemon/src/registry.rs

impl DaemonRegistry {
    pub fn update_heartbeat(&mut self, project_path: &Path) -> Result<()> {
        if let Some(entry) = self.daemons.iter_mut()
            .find(|e| e.project_path == project_path)
        {
            entry.last_heartbeat = chrono::Utc::now();
            self.save()?;
        }
        Ok(())
    }
}

// In main.rs - periodic heartbeat
tokio::spawn(async move {
    let mut interval = tokio::time::interval(Duration::from_secs(30));
    loop {
        interval.tick().await;
        if let Ok(mut registry) = DaemonRegistry::load() {
            registry.update_heartbeat(&root).ok();
        }
    }
});
```

#### 4.4 Update Python Lifecycle

```python
# src/mu/daemon/lifecycle.py

from pathlib import Path
import json

REGISTRY_PATH = Path.home() / ".mu" / "daemons.json"

def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {"version": 1, "daemons": []}
    return json.loads(REGISTRY_PATH.read_text())

def _find_daemon_for_project(project_path: Path) -> dict | None:
    registry = _load_registry()
    project_str = str(project_path.resolve())
    for entry in registry.get("daemons", []):
        if entry["project_path"] == project_str:
            return entry
    return None

def _find_daemon_on_port(port: int) -> dict | None:
    registry = _load_registry()
    for entry in registry.get("daemons", []):
        if entry["port"] == port:
            return entry
    return None

class DaemonLifecycle:
    def stop(self, port: int | None = None) -> bool:
        # First check registry
        if port:
            entry = _find_daemon_on_port(port)
        else:
            entry = _find_daemon_for_project(Path.cwd())

        if entry:
            pid = entry["pid"]
            # Kill process
            os.kill(pid, signal.SIGTERM)
            return True

        # Fallback to PID file
        return self._stop_via_pidfile()
```

#### 4.5 Add `daemon list` Command

```python
# src/mu/commands/daemon/list.py

import click
from mu.daemon.lifecycle import _load_registry
from mu.utils.output import print_table

@click.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def daemon_list(as_json: bool):
    """List all running MU daemons."""
    registry = _load_registry()
    daemons = registry.get("daemons", [])

    if as_json:
        click.echo(json.dumps(daemons, indent=2))
        return

    if not daemons:
        click.echo("No running daemons found.")
        return

    headers = ["Project", "PID", "Port", "Started"]
    rows = [
        [d["project_path"], d["pid"], d["port"], d["started_at"]]
        for d in daemons
    ]
    print_table(headers, rows)
```

#### 4.6 Add `daemon stop --all`

```python
# src/mu/commands/daemon/stop.py

@click.command("stop")
@click.option("--all", "stop_all", is_flag=True, help="Stop all daemons")
@click.option("--port", type=int, help="Stop daemon on specific port")
def daemon_stop(stop_all: bool, port: int | None):
    """Stop the MU daemon."""
    if stop_all:
        registry = _load_registry()
        for entry in registry.get("daemons", []):
            try:
                os.kill(entry["pid"], signal.SIGTERM)
                click.echo(f"Stopped daemon for {entry['project_path']}")
            except ProcessLookupError:
                click.echo(f"Daemon for {entry['project_path']} already stopped")
        return

    # ... existing stop logic with registry lookup ...
```

### Deliverables

- [ ] `~/.mu/daemons.json` registry working
- [ ] Rust daemon registers on startup
- [ ] Rust daemon deregisters on shutdown
- [ ] Port conflict detection
- [ ] Stale entry cleanup
- [ ] `mu daemon list` command
- [ ] `mu daemon stop --all` command
- [ ] Heartbeat mechanism

---

## Phase 5: Cleanup & Testing

**Duration:** 1-2 days
**Goal:** Remove Python daemon, comprehensive testing

### Tasks

#### 5.1 Remove Python Daemon

```bash
# Files to delete
rm -rf src/mu/daemon/server.py
rm -rf src/mu/daemon/worker.py
rm -rf src/mu/daemon/watcher.py
rm -rf src/mu/daemon/events.py

# Keep
# - src/mu/daemon/config.py (CLI config)
# - src/mu/daemon/lifecycle.py (process management)
# - src/mu/daemon/__init__.py (exports)
```

#### 5.2 Update Tests

```python
# tests/unit/test_daemon.py

# Remove Python daemon unit tests
# Add Rust daemon integration tests

def test_rust_daemon_starts():
    """Test mu daemon start launches Rust binary."""
    pass

def test_registry_created():
    """Test daemon registers in ~/.mu/daemons.json."""
    pass

def test_port_conflict_detected():
    """Test starting second daemon on same port fails."""
    pass

def test_daemon_stop_uses_registry():
    """Test stop finds daemon via registry."""
    pass
```

#### 5.3 Integration Tests

```python
# tests/integration/test_daemon_registry.py

def test_multi_project_isolation():
    """
    1. Start daemon in project A
    2. Switch to project B
    3. Verify mu daemon status shows warning
    4. Verify mu daemon list shows project A
    5. Verify mu daemon stop offers to stop A
    """
    pass

def test_stale_cleanup():
    """
    1. Create fake registry entry with dead PID
    2. Start new daemon
    3. Verify stale entry removed
    """
    pass
```

#### 5.4 Update Documentation

- [ ] Update `src/mu/daemon/CLAUDE.md`
- [ ] Update root `CLAUDE.md`
- [ ] Update CLI help text
- [ ] Add registry documentation

### Deliverables

- [ ] Python daemon code removed
- [ ] All tests passing
- [ ] Documentation updated
- [ ] No regressions

---

## Phase 6: Release

**Duration:** 1 day
**Goal:** Ship the migration

### Tasks

#### 6.1 Build Rust Binary

```bash
cd mu-daemon
cargo build --release
```

#### 6.2 Package Binary

Options:
1. **PyPI wheel** - Include binary in Python package
2. **Separate install** - `cargo install mu-daemon`
3. **Homebrew** - Add to existing formula

#### 6.3 Migration Guide

```markdown
# Migrating to Rust Daemon

## What Changed
- Daemon now runs on port 9120 (was 8765)
- Faster startup and lower memory usage
- Global daemon registry at ~/.mu/daemons.json

## Breaking Changes
- If you have scripts using port 8765, update to 9120
- PID file location unchanged (.mu/daemon.pid)

## New Commands
- `mu daemon list` - Show all running daemons
- `mu daemon stop --all` - Stop all daemons
```

### Deliverables

- [ ] Release binary available
- [ ] Migration guide published
- [ ] Changelog updated

---

## Timeline Summary

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Audit | 1 day | None |
| Phase 2: Feature Parity | 3-5 days | Phase 1 |
| Phase 3: CLI Integration | 1-2 days | Phase 2 |
| Phase 4: Registry | 2-3 days | Phase 3 |
| Phase 5: Cleanup | 1-2 days | Phase 4 |
| Phase 6: Release | 1 day | Phase 5 |
| **Total** | **9-14 days** | |

---

## Risk Mitigation

### Risk: Rust daemon missing critical features

**Mitigation:** Thorough audit in Phase 1. If gaps are large, extend Phase 2.

### Risk: Breaking existing workflows

**Mitigation:** Keep Python daemon available during transition. Feature flag to switch.

### Risk: Binary distribution complexity

**Mitigation:** Start with `cargo install`. Add wheel packaging later.

### Risk: Registry file corruption

**Mitigation:** Atomic writes with file locking. Validate on read.

---

## Success Criteria

1. `mu daemon start` launches Rust daemon
2. All MCP tools work with Rust daemon
3. `mu daemon list` shows all running daemons
4. Starting daemon in project A, switching to B shows warning
5. `mu daemon stop` works from any directory
6. No "Database is locked" errors
7. All 1730+ tests pass
8. Python daemon code removed

---

## Appendix: File Changes Summary

### New Files (Rust)

```
mu-daemon/src/registry.rs          # Daemon registry
mu-daemon/src/server/contracts.rs  # Contract verification (if missing)
mu-daemon/src/server/websocket.rs  # WebSocket support (if missing)
```

### Modified Files (Rust)

```
mu-daemon/src/main.rs              # Registry integration
mu-daemon/src/server/mod.rs        # New routes
mu-daemon/Cargo.toml               # Dependencies (chrono, dirs)
```

### Modified Files (Python)

```
src/mu/client.py                   # Port 9120
src/mu/daemon/lifecycle.py         # Registry lookup, Rust binary
src/mu/daemon/config.py            # Port 9120
src/mu/commands/daemon/start.py    # Launch Rust binary
src/mu/commands/daemon/stop.py     # Registry lookup, --all flag
src/mu/commands/daemon/status.py   # Registry info
```

### New Files (Python)

```
src/mu/commands/daemon/list.py     # New command
```

### Deleted Files (Python)

```
src/mu/daemon/server.py            # Python FastAPI server
src/mu/daemon/worker.py            # Graph update worker
src/mu/daemon/watcher.py           # File watcher
src/mu/daemon/events.py            # Event types
```
