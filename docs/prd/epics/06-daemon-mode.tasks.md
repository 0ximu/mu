# Daemon Mode - Task Breakdown

## Business Context

**Problem**: Developers need real-time code graph updates without manual rebuilds. Currently, `mu kernel build` must be run after every code change, creating friction for IDE integration and interactive exploration workflows.

**Outcome**: A long-running daemon that:
- Watches filesystem for code changes and updates the graph incrementally
- Serves HTTP API for queries (status, nodes, MUQL, context, export)
- Provides WebSocket for real-time change notifications
- Enables IDE integration with always-current graph state

**Users**:
- IDE plugin developers (real-time code intelligence)
- Developers using MU for exploration (instant feedback)
- Teams building custom tooling on MU data (REST API consumers)

---

## Discovered Patterns

| Pattern | File | Relevance |
|---------|------|-----------|
| Pydantic config model | `/Users/imu/Dev/work/mu/src/mu/config.py:13-231` | `DaemonConfig` should follow same nested config pattern with defaults |
| Protocol with runtime_checkable | `/Users/imu/Dev/work/mu/src/mu/kernel/export/base.py:90-127` | Event handler protocols should follow `Exporter` pattern |
| Dataclass with to_dict() | `/Users/imu/Dev/work/mu/src/mu/kernel/models.py:15-86` | Event models (FileChange, GraphEvent) follow Node pattern |
| Async pool pattern | `/Users/imu/Dev/work/mu/src/mu/llm/pool.py:34-77` | Worker should follow LLMPool async task management |
| Semaphore concurrency | `/Users/imu/Dev/work/mu/src/mu/llm/pool.py:257` | Use asyncio.Semaphore for client connection limits |
| Click command group | `/Users/imu/Dev/work/mu/src/mu/cli.py:729-732` | `daemon` command group follows `cache` and `kernel` patterns |
| CLI subcommands | `/Users/imu/Dev/work/mu/src/mu/cli.py:846-886` | `daemon start/stop/status` follows `kernel init/build/stats` pattern |
| MUbase context manager | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:853-858` | Daemon lifecycle should support `async with` |
| GraphBuilder usage | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:78-106` | Incremental updates reuse `GraphBuilder.from_module_defs()` |
| Parser integration | `/Users/imu/Dev/work/mu/src/mu/cli.py:927-943` | File parsing follows `parse_file()` pattern from kernel build |
| Error as data | `/Users/imu/Dev/work/mu/src/mu/kernel/export/base.py:50-87` | `ExportResult.error` pattern for daemon responses |
| Test fixtures | `/Users/imu/Dev/work/mu/tests/unit/test_export.py:29-43` | Test database fixtures follow `db_path` and `populated_db` pattern |
| Async test pattern | `/Users/imu/Dev/work/mu/tests/unit/test_llm.py` (referenced) | Use `@pytest.mark.asyncio` for async tests |
| Module __init__ exports | `/Users/imu/Dev/work/mu/src/mu/kernel/export/__init__.py:35-65` | Public API follows `__all__` pattern with docstring examples |

---

## Task Breakdown

### Story 6.1: File Watcher

#### Task 1.1: Create Daemon Module Structure

**Priority**: P0 (Foundation)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/__init__.py` (new)
- `/Users/imu/Dev/work/mu/src/mu/daemon/config.py` (new)

**Pattern**: Follow `src/mu/kernel/export/__init__.py` and `src/mu/config.py`

**Description**: Create the daemon module structure with public API exports and configuration model.

**Implementation Notes**:
```python
# config.py - Follow Pydantic config pattern from config.py:13-231
from pydantic import BaseModel, Field
from pathlib import Path

class DaemonConfig(BaseModel):
    """Daemon configuration."""
    host: str = Field(default="127.0.0.1", description="Server host")
    port: int = Field(default=8765, description="Server port")
    watch_paths: list[Path] = Field(default_factory=list, description="Paths to watch")
    debounce_ms: int = Field(default=100, description="Debounce delay in ms")
    pid_file: Path = Field(default=Path(".mu.pid"), description="PID file path")
    max_connections: int = Field(default=100, description="Max WebSocket connections")

# __init__.py - Public API with __all__
```

**Acceptance Criteria**:
- [ ] `DaemonConfig` dataclass with host, port, watch_paths, debounce_ms, pid_file
- [ ] Config defaults match epic specification (127.0.0.1:8765, 100ms debounce)
- [ ] `__init__.py` exports public API with `__all__`
- [ ] Type annotations pass mypy
- [ ] Follows Pydantic config model pattern from `config.py`

---

#### Task 1.2: Implement FileWatcher Class

**Priority**: P0 (Core functionality)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/watcher.py` (new)

**Pattern**: Follow async task pattern from `llm/pool.py:257-273`

**Dependencies**: Task 1.1 (config)

**Description**: Implement file watcher using `watchfiles` library for async filesystem monitoring with language filtering.

**Implementation Notes**:
```python
# Follow async pattern from llm/pool.py
import asyncio
from pathlib import Path
from watchfiles import awatch

# Supported extensions from scanner/__init__.py
SUPPORTED_EXTENSIONS = {'.py', '.ts', '.js', '.go', '.java', '.rs', '.cs'}

class FileWatcher:
    """Async filesystem watcher with filtering."""

    def __init__(self, paths: list[Path], callback: Callable[[str, Path], Awaitable[None]]):
        self.paths = paths
        self.callback = callback
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            # Handle CancelledError gracefully

    async def _watch(self) -> None:
        async for changes in awatch(*self.paths):
            for change_type, path in changes:
                if self._should_process(path):
                    await self.callback(str(change_type), Path(path))

    def _should_process(self, path: str) -> bool:
        """Filter to supported languages, skip hidden/build dirs."""
        # Check extension in SUPPORTED_EXTENSIONS
        # Skip .git, node_modules, __pycache__, .venv
```

**Acceptance Criteria**:
- [ ] Detects file create, modify, delete events via `watchfiles`
- [ ] Filters to supported language files (.py, .ts, .js, .go, .java, .rs, .cs)
- [ ] Skips hidden directories (.git, .venv) and build directories (node_modules, __pycache__)
- [ ] Async start/stop methods with proper task cancellation
- [ ] Callback receives change type and Path
- [ ] Unit tests with `tmp_path` fixture

---

#### Task 1.3: Implement Event Models and UpdateQueue

**Priority**: P0 (Required for worker)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/events.py` (new)

**Pattern**: Follow `kernel/models.py:15-86` dataclass pattern with `to_dict()`

**Dependencies**: Task 1.1 (config)

**Description**: Define event types for file changes and graph updates with debouncing queue.

**Implementation Notes**:
```python
# Follow dataclass pattern from kernel/models.py
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

@dataclass
class FileChange:
    """A file change event."""
    change_type: str  # 'added', 'modified', 'deleted'
    path: Path
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_type": self.change_type,
            "path": str(self.path),
            "timestamp": self.timestamp,
        }

@dataclass
class GraphEvent:
    """A graph change event for WebSocket broadcast."""
    event_type: str  # 'node_added', 'node_modified', 'node_removed'
    node_id: str
    node_type: str
    file_path: str | None = None

    def to_dict(self) -> dict[str, Any]: ...

class UpdateQueue:
    """Debouncing queue for file changes."""
    # Use asyncio.Queue with pending dict for debounce
```

**Acceptance Criteria**:
- [ ] `FileChange` dataclass with change_type, path, timestamp
- [ ] `GraphEvent` dataclass with event_type, node_id, node_type, file_path
- [ ] Both implement `to_dict()` for JSON serialization
- [ ] `UpdateQueue` with debouncing logic (configurable delay)
- [ ] Debounce collapses rapid changes to same file
- [ ] Unit tests for event serialization and debounce behavior

---

### Story 6.2: Incremental Updates

#### Task 2.1: Implement GraphWorker for Incremental Updates

**Priority**: P0 (Core functionality)
**Complexity**: Large
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/worker.py` (new)

**Pattern**: Follow `llm/pool.py:34-77` async worker pattern, use `GraphBuilder` from `kernel/builder.py`

**Dependencies**: Task 1.2 (watcher), Task 1.3 (events)

**Description**: Process file changes and incrementally update the MUbase graph. Handle add, modify, delete operations with proper dependency graph updates.

**Implementation Notes**:
```python
# Follow async task pattern from llm/pool.py
from mu.kernel import MUbase
from mu.kernel.builder import GraphBuilder
from mu.parser.base import parse_file
from mu.scanner import detect_language

class GraphWorker:
    """Process file changes and update graph."""

    def __init__(self, mubase: MUbase, queue: UpdateQueue):
        self.mubase = mubase
        self.queue = queue
        self._task: asyncio.Task | None = None
        self._subscribers: list[Callable[[list[GraphEvent]], Awaitable[None]]] = []

    async def start(self) -> None:
        self._task = asyncio.create_task(self._process_loop())

    async def _process_change(self, change: FileChange) -> list[GraphEvent]:
        """Process single file change, return graph events."""
        events = []

        if change.change_type == 'deleted':
            # Get nodes for this file, remove them, generate 'node_removed' events
            # Pattern: mubase.get_nodes(file_path=str(change.path))
            pass
        else:
            # Parse file following cli.py:927-943 pattern
            language = detect_language(change.path)
            parsed = parse_file(change.path, language)
            if not parsed.success:
                return events

            # Build nodes/edges using GraphBuilder
            # Compare with existing nodes, generate add/modify/remove events
            # Update mubase incrementally (not full rebuild)

        return events

    def subscribe(self, callback: Callable[[list[GraphEvent]], Awaitable[None]]) -> None:
        """Subscribe to graph change events."""
        self._subscribers.append(callback)
```

**Acceptance Criteria**:
- [ ] Processes changes from UpdateQueue asynchronously
- [ ] Handles 'added' - parses file, creates nodes/edges, adds to MUbase
- [ ] Handles 'modified' - parses file, compares nodes, updates changed ones
- [ ] Handles 'deleted' - removes all nodes/edges for that file
- [ ] Generates GraphEvent for each node change (added/modified/removed)
- [ ] Subscriber pattern for event notification (WebSocket broadcast)
- [ ] Updates dependency edges when files change
- [ ] Error handling with logging (parse errors don't crash worker)
- [ ] Unit tests with mock MUbase

---

#### Task 2.2: Add Incremental Update Methods to MUbase

**Priority**: P0 (Required by worker)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py` (modify)

**Pattern**: Follow existing MUbase methods pattern (`add_node`, `get_nodes`)

**Dependencies**: None (extends existing MUbase)

**Description**: Add methods to MUbase for incremental operations: removing nodes by file, updating individual nodes, getting nodes by file path.

**Implementation Notes**:
```python
# Add to MUbase class

def get_nodes_by_file(self, file_path: str) -> list[Node]:
    """Get all nodes from a specific file."""
    return self.get_nodes(file_path=file_path)

def remove_nodes_by_file(self, file_path: str) -> list[str]:
    """Remove all nodes from a file, return removed node IDs."""
    nodes = self.get_nodes_by_file(file_path)
    removed_ids = [n.id for n in nodes]

    # Remove edges first (foreign key safety)
    for node_id in removed_ids:
        self.conn.execute(
            "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
            [node_id, node_id]
        )

    # Remove nodes
    if removed_ids:
        placeholders = ",".join(["?"] * len(removed_ids))
        self.conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", removed_ids)

    return removed_ids

def update_node(self, node: Node) -> None:
    """Update an existing node (upsert pattern)."""
    # Already implemented via add_node with INSERT OR REPLACE
    self.add_node(node)
```

**Acceptance Criteria**:
- [ ] `get_nodes_by_file(file_path)` returns all nodes for a file
- [ ] `remove_nodes_by_file(file_path)` removes nodes and their edges
- [ ] `update_node(node)` updates existing node in place
- [ ] Edge cleanup when nodes are removed (no orphan edges)
- [ ] Unit tests for each new method

---

### Story 6.3: HTTP API

#### Task 3.1: Create FastAPI Server Structure

**Priority**: P0 (API foundation)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/server.py` (new)
- `/Users/imu/Dev/work/mu/pyproject.toml` (modify - add dependencies)

**Pattern**: Follow standard FastAPI app pattern, reference epic specification

**Dependencies**: Task 1.1 (config), Task 2.1 (worker)

**Description**: Create FastAPI application with lifespan management for daemon components.

**Implementation Notes**:
```python
from fastapi import FastAPI, HTTPException, WebSocket
from contextlib import asynccontextmanager
from mu.kernel import MUbase
from mu.daemon.watcher import FileWatcher
from mu.daemon.worker import GraphWorker, UpdateQueue
from mu.daemon.config import DaemonConfig

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage daemon lifecycle."""
    # Startup: init watcher, worker, queue
    yield
    # Shutdown: stop watcher, worker, close MUbase

def create_app(mubase_path: Path, config: DaemonConfig) -> FastAPI:
    """Create FastAPI app with all endpoints."""
    app = FastAPI(title="MU Daemon", version="1.0.0")

    # Store state in app.state for access in endpoints
    # Register routes
    return app
```

**pyproject.toml additions**:
```toml
dependencies = [
    # ... existing ...
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.25.0",
    "watchfiles>=0.21.0",
]
```

**Acceptance Criteria**:
- [ ] FastAPI app with lifespan context manager
- [ ] Dependencies added to pyproject.toml (fastapi, uvicorn, watchfiles)
- [ ] App state holds MUbase, watcher, worker references
- [ ] Graceful startup/shutdown
- [ ] Version and title set in OpenAPI docs

---

#### Task 3.2: Implement Core REST Endpoints

**Priority**: P0 (Essential API)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/server.py` (modify)

**Pattern**: Follow REST conventions, error-as-data for responses

**Dependencies**: Task 3.1 (server structure)

**Description**: Implement core REST endpoints: /status, /nodes/{id}, /nodes/{id}/neighbors.

**Implementation Notes**:
```python
from pydantic import BaseModel

class StatusResponse(BaseModel):
    status: str
    mubase_path: str
    stats: dict
    connections: int
    uptime_seconds: float

@app.get("/status")
async def get_status() -> StatusResponse:
    stats = app.state.mubase.stats()
    return StatusResponse(
        status="running",
        mubase_path=str(app.state.mubase_path),
        stats=stats,
        connections=len(app.state.ws_connections),
        uptime_seconds=(time.time() - app.state.start_time),
    )

@app.get("/nodes/{node_id}")
async def get_node(node_id: str):
    node = app.state.mubase.get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    return node.to_dict()

@app.get("/nodes/{node_id}/neighbors")
async def get_neighbors(
    node_id: str,
    direction: str = "both",
    edge_type: str | None = None
):
    # Use mubase.get_neighbors() or get_dependencies/get_dependents
    pass
```

**Acceptance Criteria**:
- [ ] `GET /status` returns stats, uptime, connection count
- [ ] `GET /nodes/{id}` returns node details or 404
- [ ] `GET /nodes/{id}/neighbors` returns connected nodes
- [ ] Pydantic models for request/response validation
- [ ] HTTPException for errors (404, 400)
- [ ] Unit tests for each endpoint with TestClient

---

#### Task 3.3: Implement MUQL and Context Endpoints

**Priority**: P1 (Query functionality)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/server.py` (modify)

**Pattern**: Follow `cli.py:1142-1220` for MUQL, `cli.py:1654-1812` for context

**Dependencies**: Task 3.2 (core endpoints)

**Description**: Implement query endpoints for MUQL execution and smart context extraction.

**Implementation Notes**:
```python
from pydantic import BaseModel
from mu.kernel.muql import MUQLEngine
from mu.kernel.context import SmartContextExtractor, ExtractionConfig

class QueryRequest(BaseModel):
    muql: str

class ContextRequest(BaseModel):
    question: str
    max_tokens: int = 8000
    exclude_tests: bool = False

@app.post("/query")
async def execute_query(request: QueryRequest):
    engine = MUQLEngine(app.state.mubase)
    try:
        output = engine.query(request.muql, "json")
        return {"result": output, "success": True}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/context")
async def get_context(request: ContextRequest):
    config = ExtractionConfig(
        max_tokens=request.max_tokens,
        exclude_tests=request.exclude_tests,
    )
    extractor = SmartContextExtractor(app.state.mubase, config)
    result = extractor.extract(request.question)
    return {
        "mu_text": result.mu_text,
        "token_count": result.token_count,
        "nodes": [n.to_dict() for n in result.nodes],
    }
```

**Acceptance Criteria**:
- [ ] `POST /query` executes MUQL query, returns results
- [ ] `POST /context` extracts smart context for question
- [ ] Query errors return 400 with error message
- [ ] Context includes mu_text, token_count, node list
- [ ] Request validation via Pydantic models
- [ ] Unit tests with sample queries

---

#### Task 3.4: Implement Export Endpoint

**Priority**: P1 (Export functionality)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/server.py` (modify)

**Pattern**: Follow `cli.py:2152-2318` and `kernel/export/` patterns

**Dependencies**: Task 3.2 (core endpoints)

**Description**: Implement export endpoint supporting all export formats.

**Implementation Notes**:
```python
from mu.kernel.export import get_default_manager, ExportOptions
from mu.kernel.schema import NodeType

@app.get("/export")
async def export_graph(
    format: str = "json",
    nodes: str | None = None,
    types: str | None = None,
    max_nodes: int | None = None,
):
    manager = get_default_manager()

    # Parse filters
    node_ids = nodes.split(",") if nodes else None
    node_types = [NodeType(t) for t in types.split(",")] if types else None

    options = ExportOptions(
        node_ids=node_ids,
        node_types=node_types,
        max_nodes=max_nodes,
    )

    result = manager.export(app.state.mubase, format, options)
    if not result.success:
        raise HTTPException(400, result.error)

    return Response(
        content=result.output,
        media_type="application/json" if format == "json" else "text/plain"
    )
```

**Acceptance Criteria**:
- [ ] `GET /export` with format query parameter (mu, json, mermaid, d2, cytoscape)
- [ ] Filter by node IDs and types
- [ ] Limit nodes with max_nodes parameter
- [ ] Proper content-type for each format
- [ ] Error handling for unknown formats
- [ ] Unit tests for export endpoint

---

### Story 6.4: WebSocket Live Updates

#### Task 4.1: Implement WebSocket Connection Manager

**Priority**: P1 (Real-time updates)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/server.py` (modify)

**Pattern**: Follow `llm/pool.py:257` semaphore pattern for connection limits

**Dependencies**: Task 3.1 (server), Task 2.1 (worker events)

**Description**: Implement WebSocket endpoint with connection management and event broadcasting.

**Implementation Notes**:
```python
from fastapi import WebSocket, WebSocketDisconnect
import asyncio

class ConnectionManager:
    """Manage WebSocket connections."""

    def __init__(self, max_connections: int = 100):
        self.active: list[WebSocket] = []
        self._semaphore = asyncio.Semaphore(max_connections)

    async def connect(self, websocket: WebSocket) -> bool:
        if not self._semaphore.locked():
            await self._semaphore.acquire()
            await websocket.accept()
            self.active.append(websocket)
            return True
        return False

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.remove(websocket)
        self._semaphore.release()

    async def broadcast(self, events: list[GraphEvent]) -> None:
        """Broadcast graph events to all connected clients."""
        message = {
            "type": "graph_update",
            "events": [e.to_dict() for e in events],
        }
        for ws in self.active.copy():
            try:
                await ws.send_json(message)
            except:
                self.active.remove(ws)

@app.websocket("/live")
async def websocket_endpoint(websocket: WebSocket):
    if not await app.state.manager.connect(websocket):
        await websocket.close(code=1013)  # Try again later
        return

    try:
        while True:
            # Receive subscription requests (future)
            data = await websocket.receive_json()
            # Handle subscriptions
    except WebSocketDisconnect:
        app.state.manager.disconnect(websocket)
```

**Acceptance Criteria**:
- [ ] WebSocket endpoint at `/live`
- [ ] Connection limit via semaphore
- [ ] `ConnectionManager.broadcast()` sends to all clients
- [ ] Graceful disconnect handling
- [ ] Worker events trigger broadcast to all connections
- [ ] Unit tests for connection management

---

#### Task 4.2: Wire Worker Events to WebSocket Broadcast

**Priority**: P1 (Integration)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/server.py` (modify)

**Pattern**: Worker subscribe pattern from Task 2.1

**Dependencies**: Task 4.1 (WebSocket), Task 2.1 (worker)

**Description**: Connect GraphWorker event stream to WebSocket broadcast.

**Implementation Notes**:
```python
# In lifespan or app startup
async def on_graph_events(events: list[GraphEvent]) -> None:
    await app.state.manager.broadcast(events)

app.state.worker.subscribe(on_graph_events)
```

**Acceptance Criteria**:
- [ ] File changes trigger WebSocket broadcast
- [ ] Events include node_id, event_type, file_path
- [ ] Broadcast is non-blocking (fire and forget)
- [ ] Integration test: file change -> WebSocket message

---

### Story 6.5: Daemon Lifecycle

#### Task 5.1: Implement DaemonLifecycle Manager

**Priority**: P0 (Required for CLI)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/lifecycle.py` (new)

**Pattern**: Standard Unix daemon pattern with PID file

**Dependencies**: Task 3.1 (server)

**Description**: Manage daemon start/stop/status with PID file and process control.

**Implementation Notes**:
```python
import os
import signal
from pathlib import Path

class DaemonLifecycle:
    """Manage daemon start/stop/status."""

    def __init__(self, pid_file: Path = Path(".mu.pid")):
        self.pid_file = pid_file

    def is_running(self) -> tuple[bool, int | None]:
        """Check if daemon is running, return (running, pid)."""
        if not self.pid_file.exists():
            return False, None

        pid = int(self.pid_file.read_text().strip())
        try:
            os.kill(pid, 0)  # Check if process exists
            return True, pid
        except OSError:
            self.pid_file.unlink()  # Stale PID file
            return False, None

    def start_foreground(self, config: DaemonConfig, mubase_path: Path) -> None:
        """Run daemon in foreground (for debugging)."""
        import uvicorn
        from mu.daemon.server import create_app

        app = create_app(mubase_path, config)
        self.pid_file.write_text(str(os.getpid()))

        try:
            uvicorn.run(app, host=config.host, port=config.port)
        finally:
            self.pid_file.unlink(missing_ok=True)

    def start_background(self, config: DaemonConfig, mubase_path: Path) -> int:
        """Start daemon in background, return PID."""
        # Fork process, run uvicorn
        # Note: May want to use multiprocessing instead of os.fork for cross-platform
        pass

    def stop(self) -> bool:
        """Stop running daemon, return success."""
        running, pid = self.is_running()
        if not running or pid is None:
            return False

        os.kill(pid, signal.SIGTERM)
        # Wait for shutdown with timeout
        return True

    def status(self) -> dict:
        """Get daemon status."""
        running, pid = self.is_running()
        if not running:
            return {"status": "stopped"}

        # Query daemon /status endpoint
        import httpx
        try:
            response = httpx.get(f"http://127.0.0.1:8765/status", timeout=1)
            return response.json()
        except:
            return {"status": "running", "pid": pid, "healthy": False}
```

**Acceptance Criteria**:
- [ ] `is_running()` checks PID file and process existence
- [ ] `start_foreground()` runs uvicorn in current process
- [ ] `start_background()` forks and runs in background
- [ ] `stop()` sends SIGTERM and waits for shutdown
- [ ] `status()` queries daemon HTTP endpoint
- [ ] PID file cleanup on exit
- [ ] Unit tests for lifecycle methods

---

#### Task 5.2: Add CLI Daemon Commands

**Priority**: P0 (User interface)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py` (modify)

**Pattern**: Follow `cli.py:729-732` (cache group) and `cli.py:846-1019` (kernel commands)

**Dependencies**: Task 5.1 (lifecycle)

**Description**: Add `mu daemon` command group with start/stop/status/run subcommands.

**Implementation Notes**:
```python
# Add after kernel commands

@cli.group()
def daemon() -> None:
    """MU daemon commands (real-time updates).

    Run a long-running daemon that watches for file changes
    and serves HTTP/WebSocket API for queries.
    """
    pass

@daemon.command("start")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--port", "-p", type=int, default=8765, help="Server port")
@click.option("--host", type=str, default="127.0.0.1", help="Server host")
@click.option("--watch", "-w", multiple=True, type=click.Path(exists=True, path_type=Path),
              help="Additional paths to watch")
def daemon_start(path: Path, port: int, host: str, watch: tuple[Path, ...]) -> None:
    """Start MU daemon in background."""
    from mu.daemon.lifecycle import DaemonLifecycle
    from mu.daemon.config import DaemonConfig

    mubase_path = path.resolve() / ".mubase"
    if not mubase_path.exists():
        print_error("No .mubase found. Run 'mu kernel build' first.")
        sys.exit(ExitCode.CONFIG_ERROR)

    lifecycle = DaemonLifecycle()
    running, pid = lifecycle.is_running()
    if running:
        print_warning(f"Daemon already running (PID {pid})")
        return

    config = DaemonConfig(
        host=host,
        port=port,
        watch_paths=list(watch) if watch else [path.resolve()],
    )

    pid = lifecycle.start_background(config, mubase_path)
    print_success(f"MU daemon started on http://{host}:{port}")
    print_info(f"PID: {pid}")

@daemon.command("stop")
def daemon_stop() -> None:
    """Stop running MU daemon."""
    from mu.daemon.lifecycle import DaemonLifecycle

    lifecycle = DaemonLifecycle()
    if lifecycle.stop():
        print_success("MU daemon stopped")
    else:
        print_info("Daemon not running")

@daemon.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def daemon_status(as_json: bool) -> None:
    """Check daemon status."""
    from mu.daemon.lifecycle import DaemonLifecycle

    lifecycle = DaemonLifecycle()
    status = lifecycle.status()

    if as_json:
        console.print(json.dumps(status, indent=2))
    else:
        # Rich table output
        pass

@daemon.command("run")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--port", "-p", type=int, default=8765, help="Server port")
@click.option("--host", type=str, default="127.0.0.1", help="Server host")
def daemon_run(path: Path, port: int, host: str) -> None:
    """Run daemon in foreground (for debugging)."""
    # Run in foreground, Ctrl+C to stop
    pass
```

**Acceptance Criteria**:
- [ ] `mu daemon start` starts daemon in background
- [ ] `mu daemon stop` stops running daemon
- [ ] `mu daemon status` shows daemon status (running, PID, stats)
- [ ] `mu daemon run` runs in foreground for debugging
- [ ] `--port` and `--host` options
- [ ] `--watch` option for additional paths
- [ ] Error if .mubase doesn't exist
- [ ] Warning if daemon already running
- [ ] Integration tests for CLI commands

---

### Story 6.6: Testing and Documentation

#### Task 6.1: Write Unit Tests for Daemon Module

**Priority**: P1 (Quality)
**Complexity**: Large
**Files**:
- `/Users/imu/Dev/work/mu/tests/unit/test_daemon.py` (new)

**Pattern**: Follow `tests/unit/test_export.py` test organization

**Dependencies**: All previous tasks

**Description**: Comprehensive unit tests for all daemon components.

**Implementation Notes**:
```python
import pytest
from pathlib import Path

# Test fixtures
@pytest.fixture
def daemon_config():
    from mu.daemon.config import DaemonConfig
    return DaemonConfig()

@pytest.fixture
def populated_db(tmp_path):
    # Follow test_export.py fixture pattern
    pass

# Test classes
class TestDaemonConfig:
    def test_default_values(self): ...
    def test_custom_port(self): ...

class TestFileWatcher:
    @pytest.mark.asyncio
    async def test_detects_file_creation(self, tmp_path): ...

    @pytest.mark.asyncio
    async def test_filters_unsupported_files(self, tmp_path): ...

    @pytest.mark.asyncio
    async def test_ignores_hidden_directories(self, tmp_path): ...

class TestUpdateQueue:
    @pytest.mark.asyncio
    async def test_debounce_collapses_changes(self): ...

class TestGraphWorker:
    @pytest.mark.asyncio
    async def test_handles_file_added(self, populated_db): ...

    @pytest.mark.asyncio
    async def test_handles_file_deleted(self, populated_db): ...

    @pytest.mark.asyncio
    async def test_notifies_subscribers(self, populated_db): ...

class TestDaemonServer:
    def test_status_endpoint(self, client): ...
    def test_query_endpoint(self, client): ...
    def test_export_endpoint(self, client): ...

class TestDaemonLifecycle:
    def test_is_running_no_pid_file(self): ...
    def test_is_running_stale_pid(self): ...
```

**Acceptance Criteria**:
- [ ] Tests for DaemonConfig defaults and validation
- [ ] Tests for FileWatcher (async tests with `tmp_path`)
- [ ] Tests for UpdateQueue debouncing
- [ ] Tests for GraphWorker incremental updates
- [ ] Tests for HTTP endpoints with FastAPI TestClient
- [ ] Tests for DaemonLifecycle PID management
- [ ] All tests pass with `pytest tests/unit/test_daemon.py`

---

#### Task 6.2: Create Daemon CLAUDE.md Documentation

**Priority**: P2 (Developer docs)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/CLAUDE.md` (new)

**Pattern**: Follow `src/mu/kernel/export/CLAUDE.md`

**Dependencies**: All previous tasks

**Description**: Create comprehensive documentation for the daemon module.

**Acceptance Criteria**:
- [ ] Architecture overview with diagram
- [ ] File structure table with purposes
- [ ] Component documentation (watcher, worker, server, lifecycle)
- [ ] HTTP API reference
- [ ] WebSocket protocol documentation
- [ ] CLI usage examples
- [ ] Configuration options
- [ ] Anti-patterns section
- [ ] Testing instructions

---

## Dependencies

```
Task 1.1 (Module Structure)
    ├─> Task 1.2 (FileWatcher)
    ├─> Task 1.3 (Events/Queue)
    └─> Task 3.1 (Server Structure)

Task 1.2 ──> Task 2.1 (GraphWorker)
Task 1.3 ──> Task 2.1

Task 2.2 (MUbase methods) ──> Task 2.1

Task 2.1 ──> Task 4.1 (WebSocket)
Task 3.1 ──> Task 4.1

Task 3.1 ──> Task 3.2 (Core endpoints) ──> Task 3.3 (MUQL/Context)
                                        └─> Task 3.4 (Export)

Task 4.1 ──> Task 4.2 (Wire events)

Task 3.1 ──> Task 5.1 (Lifecycle)
Task 5.1 ──> Task 5.2 (CLI commands)

All ──> Task 6.1 (Tests)
All ──> Task 6.2 (Documentation)
```

---

## Implementation Order

**Phase 1: Foundation (Tasks 1.1, 1.2, 1.3, 2.2)**
1. Task 1.1: Module structure and config
2. Task 1.3: Event models and queue
3. Task 1.2: FileWatcher implementation
4. Task 2.2: MUbase incremental methods

**Phase 2: Core Processing (Tasks 2.1, 3.1)**
5. Task 2.1: GraphWorker for incremental updates
6. Task 3.1: FastAPI server structure

**Phase 3: HTTP API (Tasks 3.2, 3.3, 3.4)**
7. Task 3.2: Core REST endpoints
8. Task 3.3: MUQL and context endpoints
9. Task 3.4: Export endpoint

**Phase 4: Real-time (Tasks 4.1, 4.2)**
10. Task 4.1: WebSocket connection manager
11. Task 4.2: Wire worker events to broadcast

**Phase 5: Lifecycle (Tasks 5.1, 5.2)**
12. Task 5.1: DaemonLifecycle manager
13. Task 5.2: CLI daemon commands

**Phase 6: Quality (Tasks 6.1, 6.2)**
14. Task 6.1: Comprehensive unit tests
15. Task 6.2: CLAUDE.md documentation

---

## Edge Cases

1. **Rapid file changes**: Debounce prevents overwhelming the worker
2. **Parse errors**: Log warning, don't update graph, don't crash
3. **MUbase not found**: Error message with instructions
4. **Port already in use**: Clear error, suggest different port
5. **PID file stale**: Auto-cleanup on status check
6. **WebSocket disconnect**: Graceful cleanup, no memory leak
7. **Large file changes**: Consider batching or throttling
8. **File rename**: Treat as delete + add
9. **Symlinks**: Follow or ignore based on config
10. **Permission errors**: Log and continue watching other files

---

## Security Considerations

1. **Localhost only by default**: Bind to 127.0.0.1, not 0.0.0.0
2. **No authentication (v1)**: Document as local-only tool
3. **Path traversal**: Validate file paths in API responses
4. **PID file permissions**: Write with 0600 mode
5. **No remote code execution**: Daemon only queries graph, doesn't execute code
6. **Rate limiting**: Consider for future public-facing deployments

---

## Performance Considerations

1. **Debounce delay**: 100ms default prevents thrashing
2. **Incremental updates**: Only reparse changed files, not full rebuild
3. **Connection limit**: Semaphore prevents resource exhaustion
4. **Async I/O**: All file watching and HTTP handling is async
5. **DuckDB efficiency**: Batch operations where possible
6. **Target latency**: File change to WebSocket broadcast < 1 second
7. **Memory**: No caching of parsed modules (reparse on each change)
