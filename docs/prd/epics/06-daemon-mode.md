# Epic 6: Daemon Mode

**Priority**: P3 - Real-time updates and IDE integration
**Dependencies**: Kernel, Export Formats
**Estimated Complexity**: High
**PRD Reference**: Daemon Layer

---

## Overview

Implement a long-running daemon that watches for file changes, incrementally updates the graph, and serves queries via HTTP/WebSocket. This enables real-time IDE integration and always-current graph state.

## Goals

1. Watch filesystem for code changes
2. Incrementally update graph without full rebuild
3. Serve HTTP API for queries and exports
4. Provide WebSocket for live updates
5. Support multiple concurrent clients

---

## User Stories

### Story 6.1: File Watcher
**As a** developer
**I want** automatic graph updates on file save
**So that** my graph stays current without manual rebuilds

**Acceptance Criteria**:
- [ ] Detect file create, modify, delete events
- [ ] Filter to supported language files
- [ ] Debounce rapid changes
- [ ] Handle file renames

### Story 6.2: Incremental Updates
**As a** developer
**I want** fast incremental updates
**So that** changes reflect in < 1 second

**Acceptance Criteria**:
- [ ] Only reparse changed files
- [ ] Update affected nodes/edges
- [ ] Remove stale nodes from deleted files
- [ ] Handle dependency graph updates

### Story 6.3: HTTP API
**As a** developer
**I want** HTTP endpoints for queries
**So that** I can integrate with tools

**Acceptance Criteria**:
- [ ] GET /status - Graph stats
- [ ] GET /nodes/{id} - Node details
- [ ] POST /query - Execute MUQL
- [ ] POST /context - Smart context
- [ ] GET /export - Export formats

### Story 6.4: WebSocket Live Updates
**As a** developer
**I want** real-time change notifications
**So that** my IDE updates instantly

**Acceptance Criteria**:
- [ ] Connect via WebSocket
- [ ] Receive node change events
- [ ] Subscribe to specific nodes/paths
- [ ] Handle reconnection

### Story 6.5: Daemon Lifecycle
**As a** developer
**I want** reliable daemon management
**So that** I can start/stop/monitor easily

**Acceptance Criteria**:
- [ ] `mu daemon start` - Start daemon
- [ ] `mu daemon stop` - Stop daemon
- [ ] `mu daemon status` - Check status
- [ ] PID file for process management
- [ ] Graceful shutdown

---

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        MU DAEMON                             │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ File Watcher │───→│ Update Queue │───→│ Graph Worker │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                                       │            │
│         │                                       ↓            │
│         │                              ┌──────────────┐     │
│         │                              │   MUbase     │     │
│         │                              │  (DuckDB)    │     │
│         │                              └──────────────┘     │
│         │                                       ↑            │
│         ↓                                       │            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    HTTP Server                        │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐ │   │
│  │  │ /status │  │ /query  │  │/context │  │/export  │ │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘ │   │
│  │                                                       │   │
│  │  ┌─────────────────────────────────────────────────┐ │   │
│  │  │              WebSocket /live                     │ │   │
│  │  └─────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### File Structure

```
src/mu/daemon/
├── __init__.py          # Public API
├── server.py            # HTTP/WS server (FastAPI)
├── watcher.py           # File system watcher
├── worker.py            # Graph update worker
├── events.py            # Event types and queue
├── lifecycle.py         # Start/stop/status
└── config.py            # Daemon configuration
```

### Core Components

```python
import asyncio
from pathlib import Path
from watchfiles import awatch
from fastapi import FastAPI, WebSocket
from contextlib import asynccontextmanager

@dataclass
class DaemonConfig:
    """Daemon configuration."""
    host: str = "127.0.0.1"
    port: int = 8765
    watch_paths: list[Path] = field(default_factory=list)
    debounce_ms: int = 100
    pid_file: Path = Path(".mu.pid")


class FileWatcher:
    """Watch filesystem for changes."""

    def __init__(self, paths: list[Path], callback: Callable):
        self.paths = paths
        self.callback = callback
        self._task: asyncio.Task | None = None

    async def start(self):
        """Start watching for changes."""
        self._task = asyncio.create_task(self._watch())

    async def stop(self):
        """Stop watching."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch(self):
        """Watch loop."""
        async for changes in awatch(*self.paths):
            for change_type, path in changes:
                if self._should_process(path):
                    await self.callback(change_type, Path(path))

    def _should_process(self, path: str) -> bool:
        """Filter to relevant files."""
        p = Path(path)
        # Check extension
        if p.suffix not in ('.py', '.ts', '.js', '.go', '.java', '.rs', '.cs'):
            return False
        # Skip hidden and build directories
        if any(part.startswith('.') or part in ('node_modules', '__pycache__', 'venv')
               for part in p.parts):
            return False
        return True


@dataclass
class FileChange:
    """A file change event."""
    change_type: str  # 'added', 'modified', 'deleted'
    path: Path
    timestamp: float


class UpdateQueue:
    """Queue of pending updates with debouncing."""

    def __init__(self, debounce_ms: int = 100):
        self.debounce_ms = debounce_ms
        self._queue: asyncio.Queue[FileChange] = asyncio.Queue()
        self._pending: dict[Path, FileChange] = {}
        self._lock = asyncio.Lock()

    async def add(self, change: FileChange):
        """Add change to queue with debouncing."""
        async with self._lock:
            self._pending[change.path] = change

        # Debounce: wait before processing
        await asyncio.sleep(self.debounce_ms / 1000)

        async with self._lock:
            if change.path in self._pending:
                await self._queue.put(self._pending.pop(change.path))

    async def get(self) -> FileChange:
        """Get next change from queue."""
        return await self._queue.get()


class GraphWorker:
    """Process file changes and update graph."""

    def __init__(self, mubase: MUbase, queue: UpdateQueue):
        self.mubase = mubase
        self.queue = queue
        self.builder = GraphBuilder()
        self._task: asyncio.Task | None = None
        self._subscribers: list[Callable] = []

    async def start(self):
        """Start processing changes."""
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self):
        """Stop processing."""
        if self._task:
            self._task.cancel()

    def subscribe(self, callback: Callable):
        """Subscribe to graph change events."""
        self._subscribers.append(callback)

    async def _process_loop(self):
        """Main processing loop."""
        while True:
            change = await self.queue.get()
            try:
                events = await self._process_change(change)
                await self._notify_subscribers(events)
            except Exception as e:
                logger.error(f"Error processing {change.path}: {e}")

    async def _process_change(self, change: FileChange) -> list[GraphEvent]:
        """Process a single file change."""
        events = []

        if change.change_type == 'deleted':
            # Remove nodes from this file
            removed = self.mubase.remove_nodes_by_file(str(change.path))
            events.extend(GraphEvent('removed', n) for n in removed)

        else:  # added or modified
            # Parse file
            from mu.parser import Parser
            parser = Parser()
            module_def = parser.parse_file(change.path)

            if module_def.error:
                logger.warning(f"Parse error in {change.path}: {module_def.error}")
                return events

            # Build graph nodes/edges
            old_nodes = set(self.mubase.get_nodes_by_file(str(change.path)))
            new_nodes, new_edges = self.builder.build(module_def)

            # Update database
            for node in new_nodes:
                if node.id in old_nodes:
                    self.mubase.update_node(node)
                    events.append(GraphEvent('modified', node))
                    old_nodes.discard(node.id)
                else:
                    self.mubase.add_node(node)
                    events.append(GraphEvent('added', node))

            # Remove nodes that no longer exist
            for node_id in old_nodes:
                self.mubase.delete_node(node_id)
                events.append(GraphEvent('removed', node_id))

            # Update edges
            for edge in new_edges:
                self.mubase.add_edge(edge)

        return events

    async def _notify_subscribers(self, events: list[GraphEvent]):
        """Notify all subscribers of changes."""
        for callback in self._subscribers:
            try:
                await callback(events)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")


@dataclass
class GraphEvent:
    """A graph change event."""
    event_type: str  # 'added', 'modified', 'removed'
    node: Node | str  # Node object or node_id for removed


class MUDaemon:
    """Main daemon class."""

    def __init__(self, mubase_path: Path, config: DaemonConfig | None = None):
        self.mubase_path = mubase_path
        self.config = config or DaemonConfig()
        self.mubase = MUbase(mubase_path)

        self.queue = UpdateQueue(self.config.debounce_ms)
        self.watcher = FileWatcher(self.config.watch_paths, self._on_file_change)
        self.worker = GraphWorker(self.mubase, self.queue)

        self.app = self._create_app()
        self._server = None

    async def start(self):
        """Start the daemon."""
        # Write PID file
        self.config.pid_file.write_text(str(os.getpid()))

        # Start components
        await self.watcher.start()
        await self.worker.start()

        # Start HTTP server
        import uvicorn
        config = uvicorn.Config(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level="info"
        )
        self._server = uvicorn.Server(config)
        await self._server.serve()

    async def stop(self):
        """Stop the daemon."""
        await self.watcher.stop()
        await self.worker.stop()
        if self._server:
            self._server.should_exit = True
        self.config.pid_file.unlink(missing_ok=True)

    async def _on_file_change(self, change_type: str, path: Path):
        """Handle file change event."""
        change = FileChange(
            change_type=change_type,
            path=path,
            timestamp=time.time()
        )
        await self.queue.add(change)

    def _create_app(self) -> FastAPI:
        """Create FastAPI application."""
        app = FastAPI(title="MU Daemon", version="1.0.0")

        # WebSocket connections
        connections: list[WebSocket] = []

        # Subscribe to graph events
        async def broadcast_events(events: list[GraphEvent]):
            for ws in connections:
                try:
                    await ws.send_json({
                        "type": "graph_update",
                        "events": [e.to_dict() for e in events]
                    })
                except:
                    connections.remove(ws)

        self.worker.subscribe(broadcast_events)

        @app.get("/status")
        async def get_status():
            return {
                "status": "running",
                "mubase": str(self.mubase_path),
                "stats": self.mubase.stats(),
                "connections": len(connections)
            }

        @app.get("/nodes/{node_id}")
        async def get_node(node_id: str):
            node = self.mubase.get_node(node_id)
            if not node:
                raise HTTPException(404, "Node not found")
            return node.to_dict()

        @app.get("/nodes/{node_id}/neighbors")
        async def get_neighbors(
            node_id: str,
            direction: str = "both",
            edge_type: str | None = None
        ):
            neighbors = self.mubase.get_neighbors(
                node_id,
                direction=direction,
                edge_type=EdgeType(edge_type) if edge_type else None
            )
            return [n.to_dict() for n in neighbors]

        @app.post("/query")
        async def execute_query(request: QueryRequest):
            try:
                result = self.mubase.query(request.muql)
                return result.to_dict()
            except Exception as e:
                raise HTTPException(400, str(e))

        @app.post("/context")
        async def get_context(request: ContextRequest):
            result = self.mubase.get_context_for_question(
                request.question,
                max_tokens=request.max_tokens
            )
            return {
                "mu_text": result.mu_text,
                "token_count": result.token_count,
                "nodes": [n.to_dict() for n in result.nodes]
            }

        @app.get("/export")
        async def export_graph(
            format: str = "json",
            nodes: str | None = None,
            types: str | None = None
        ):
            node_ids = nodes.split(",") if nodes else None
            output = self.mubase.export(
                format=format,
                node_ids=node_ids
            )
            return Response(content=output, media_type="application/json")

        @app.websocket("/live")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            connections.append(websocket)

            try:
                while True:
                    # Receive subscription requests
                    data = await websocket.receive_json()
                    if data.get("type") == "subscribe":
                        # Handle subscription (future)
                        pass
            except WebSocketDisconnect:
                connections.remove(websocket)

        return app
```

### Lifecycle Management

```python
class DaemonLifecycle:
    """Manage daemon start/stop/status."""

    def __init__(self, pid_file: Path = Path(".mu.pid")):
        self.pid_file = pid_file

    def is_running(self) -> tuple[bool, int | None]:
        """Check if daemon is running."""
        if not self.pid_file.exists():
            return False, None

        pid = int(self.pid_file.read_text().strip())

        # Check if process exists
        try:
            os.kill(pid, 0)
            return True, pid
        except OSError:
            # Stale PID file
            self.pid_file.unlink()
            return False, None

    def start(self, config: DaemonConfig) -> int:
        """Start daemon in background."""
        running, pid = self.is_running()
        if running:
            raise RuntimeError(f"Daemon already running (PID {pid})")

        # Fork to background
        pid = os.fork()
        if pid > 0:
            # Parent process
            return pid

        # Child process - become daemon
        os.setsid()
        os.umask(0)

        # Close file descriptors
        sys.stdin.close()
        sys.stdout = open('/dev/null', 'w')
        sys.stderr = open('/dev/null', 'w')

        # Run daemon
        daemon = MUDaemon(Path(".mubase"), config)
        asyncio.run(daemon.start())

    def stop(self) -> bool:
        """Stop running daemon."""
        running, pid = self.is_running()
        if not running:
            return False

        os.kill(pid, signal.SIGTERM)

        # Wait for shutdown
        for _ in range(50):  # 5 seconds
            time.sleep(0.1)
            if not self.is_running()[0]:
                return True

        # Force kill
        os.kill(pid, signal.SIGKILL)
        return True

    def status(self) -> dict:
        """Get daemon status."""
        running, pid = self.is_running()

        if not running:
            return {"status": "stopped"}

        # Query daemon for status
        try:
            response = requests.get(f"http://127.0.0.1:8765/status", timeout=1)
            return response.json()
        except:
            return {"status": "running", "pid": pid, "healthy": False}
```

---

## Implementation Plan

### Phase 1: File Watcher (Day 1)
1. Implement `FileWatcher` using watchfiles
2. Add file filtering logic
3. Implement debouncing
4. Test with rapid file changes

### Phase 2: Update Queue (Day 1)
1. Implement `UpdateQueue` with debouncing
2. Add async processing
3. Handle batching of rapid changes
4. Test queue behavior

### Phase 3: Graph Worker (Day 2)
1. Implement `GraphWorker`
2. Add incremental node/edge updates
3. Handle deleted files
4. Implement change event generation

### Phase 4: HTTP Server (Day 2-3)
1. Create FastAPI app
2. Implement /status endpoint
3. Implement /nodes endpoints
4. Implement /query endpoint
5. Implement /context endpoint
6. Implement /export endpoint

### Phase 5: WebSocket (Day 3)
1. Add WebSocket endpoint
2. Implement connection management
3. Add event broadcasting
4. Handle reconnection

### Phase 6: Lifecycle (Day 3-4)
1. Implement `DaemonLifecycle`
2. Add PID file management
3. Implement daemonization
4. Add graceful shutdown

### Phase 7: CLI Integration (Day 4)
1. Add `mu daemon start` command
2. Add `mu daemon stop` command
3. Add `mu daemon status` command
4. Add `--port` and `--host` options

### Phase 8: Testing (Day 4-5)
1. Unit tests for each component
2. Integration tests with real files
3. WebSocket connection tests
4. Stress tests with rapid changes

---

## CLI Interface

```bash
# Start daemon
$ mu daemon start
MU daemon started on http://127.0.0.1:8765
Watching: /Users/dev/project/src

# Start with options
$ mu daemon start --port 9000 --watch ./src ./lib

# Check status
$ mu daemon status
MU Daemon Status:
  Status: running
  PID: 12345
  Uptime: 2h 15m
  Port: 8765

  Graph Stats:
    Nodes: 342
    Edges: 891

  Connections: 2 WebSocket clients

# Stop daemon
$ mu daemon stop
MU daemon stopped

# Foreground mode (for debugging)
$ mu daemon run
INFO:     Started server process [12345]
INFO:     Uvicorn running on http://127.0.0.1:8765
INFO:     File changed: src/auth.py (modified)
INFO:     Updated 3 nodes, 5 edges
```

---

## HTTP API Reference

### GET /status
```json
{
  "status": "running",
  "mubase": "/path/to/.mubase",
  "uptime_seconds": 3600,
  "stats": {
    "nodes": 342,
    "edges": 891,
    "by_type": {"FUNCTION": 200, "CLASS": 50, "MODULE": 42}
  },
  "connections": 2
}
```

### GET /nodes/{id}
```json
{
  "id": "auth_service_login",
  "type": "FUNCTION",
  "name": "login",
  "qualified_name": "auth.service.AuthService.login",
  "file_path": "src/auth/service.py",
  "line_start": 45,
  "line_end": 67,
  "properties": {
    "parameters": [...],
    "return_type": "Result[User]"
  }
}
```

### POST /query
Request:
```json
{
  "muql": "SELECT * FROM functions WHERE complexity > 500"
}
```

Response:
```json
{
  "columns": ["id", "name", "complexity"],
  "rows": [...],
  "total": 5,
  "execution_time_ms": 12
}
```

### POST /context
Request:
```json
{
  "question": "How does authentication work?",
  "max_tokens": 4000
}
```

Response:
```json
{
  "mu_text": "! auth.service\n  $ AuthService...",
  "token_count": 2341,
  "nodes": [...]
}
```

### WebSocket /live
```json
// Server → Client
{
  "type": "graph_update",
  "events": [
    {"event_type": "modified", "node": {...}},
    {"event_type": "added", "node": {...}}
  ]
}

// Client → Server (future)
{
  "type": "subscribe",
  "paths": ["src/auth/*"]
}
```

---

## Testing Strategy

### Unit Tests
```python
@pytest.mark.asyncio
async def test_file_watcher_detects_changes(tmp_path):
    changes = []
    watcher = FileWatcher([tmp_path], lambda t, p: changes.append((t, p)))
    await watcher.start()

    # Create file
    (tmp_path / "test.py").write_text("# test")
    await asyncio.sleep(0.5)

    assert len(changes) == 1
    assert changes[0][0] == "added"

@pytest.mark.asyncio
async def test_update_queue_debounces():
    queue = UpdateQueue(debounce_ms=100)
    # Add 10 changes for same file rapidly
    for i in range(10):
        await queue.add(FileChange("modified", Path("test.py"), time.time()))

    # Should only get 1 change after debounce
    await asyncio.sleep(0.2)
    assert queue._queue.qsize() == 1
```

---

## Success Criteria

- [ ] File changes reflected in < 1 second
- [ ] HTTP API responds in < 50ms
- [ ] WebSocket broadcasts events to all clients
- [ ] Daemon handles 100+ file changes per minute
- [ ] Clean shutdown with no data loss
- [ ] Memory usage stable over time

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| File watcher misses events | High | Use robust library (watchfiles), add polling fallback |
| Concurrent update conflicts | High | Use queue with single worker |
| Memory leak in long run | Medium | Profile and test extended runs |
| Port conflicts | Low | Configurable port, auto-increment |

---

## Future Enhancements

1. **Multiple watch paths**: Watch src, lib, tests separately
2. **Subscription filters**: Subscribe to specific paths/types
3. **Metrics endpoint**: Prometheus-compatible metrics
4. **Health checks**: Kubernetes-compatible health endpoint
5. **TLS support**: HTTPS for secure connections
6. **Authentication**: API key or JWT for access control
