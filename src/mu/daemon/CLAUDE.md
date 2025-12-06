# Daemon Module - Real-time File Watching and HTTP/WebSocket API

The daemon module provides a long-running server that watches for file changes, incrementally updates the code graph, and serves HTTP REST and WebSocket APIs for queries and real-time notifications.

## Architecture

```
FileWatcher (watchfiles)
       |
       v
UpdateQueue (debouncing)
       |
       v
GraphWorker (incremental updates)
       |
       +---> MUbase (graph storage)
       |
       +---> WebSocket broadcast

FastAPI Server
       |
       +---> GET /status        - Daemon status
       +---> GET /nodes/{id}    - Node lookup
       +---> POST /query        - MUQL queries
       +---> POST /context      - Smart context
       +---> GET /export        - Graph export
       +---> WS /live           - Real-time updates
```

### Files

| File | Purpose |
|------|---------|
| `config.py` | `DaemonConfig` - host, port, watch paths, debounce |
| `events.py` | `FileChange`, `GraphEvent`, `UpdateQueue` |
| `watcher.py` | `FileWatcher` - filesystem monitoring with filtering |
| `worker.py` | `GraphWorker` - incremental graph updates |
| `server.py` | FastAPI application, endpoints, `ConnectionManager` |
| `lifecycle.py` | `DaemonLifecycle` - start/stop/status |

## Data Models

### DaemonConfig

```python
from mu.daemon import DaemonConfig

config = DaemonConfig(
    host="127.0.0.1",      # Bind to localhost only (security)
    port=8765,              # Default port
    watch_paths=[Path(".")], # Paths to monitor
    debounce_ms=100,        # Debounce delay for file changes
    max_connections=100,    # WebSocket connection limit
    pid_file=Path(".mu.pid"), # PID file location
)
```

### FileChange

```python
from mu.daemon import FileChange

change = FileChange(
    change_type="modified",  # "added", "modified", "deleted"
    path=Path("/src/test.py"),
    timestamp=time.time(),
)
```

### GraphEvent

```python
from mu.daemon import GraphEvent

event = GraphEvent(
    event_type="node_added",  # "node_added", "node_modified", "node_removed"
    node_id="mod:src/test.py",
    node_type="module",
    file_path="src/test.py",
)
```

## CLI Commands

```bash
# Start daemon in background
mu daemon start .
mu daemon start . --port 9000 --watch ./lib

# Check daemon status
mu daemon status
mu daemon status --json

# Stop daemon
mu daemon stop

# Run in foreground (for debugging)
mu daemon run .
```

## HTTP API

### GET /status

Returns daemon status and statistics.

```json
{
  "status": "running",
  "mubase_path": "/path/to/.mubase",
  "stats": {"nodes": 1234, "edges": 5678},
  "connections": 2,
  "uptime_seconds": 3600.5
}
```

### GET /nodes/{node_id}

Get a node by ID.

```json
{
  "id": "mod:src/test.py",
  "type": "module",
  "name": "test",
  "qualified_name": "test",
  "file_path": "src/test.py",
  "line_start": 1,
  "line_end": 100,
  "properties": {},
  "complexity": 0
}
```

### GET /nodes/{node_id}/neighbors

Get neighboring nodes. Query param: `direction` (outgoing, incoming, both).

### POST /query

Execute a MUQL query.

```json
{
  "muql": "FIND CLASS WHERE name LIKE '%Service%'"
}
```

### POST /context

Extract smart context for a question.

```json
{
  "question": "How does authentication work?",
  "max_tokens": 8000,
  "exclude_tests": false
}
```

### GET /export

Export graph in various formats. Query params:
- `format`: mu, json, mermaid, d2, cytoscape
- `nodes`: Comma-separated node IDs
- `types`: Comma-separated node types
- `max_nodes`: Maximum nodes

### WS /live

WebSocket endpoint for real-time graph updates.

```json
// Connected message
{"type": "connected", "message": "...", "timestamp": 1234567890}

// Graph update
{
  "type": "graph_update",
  "events": [
    {"event_type": "node_modified", "node_id": "...", ...}
  ],
  "timestamp": 1234567890
}
```

## Python API

### Starting Daemon Programmatically

```python
from pathlib import Path
from mu.daemon import DaemonConfig, DaemonLifecycle

config = DaemonConfig(port=8765)
lifecycle = DaemonLifecycle(config=config)

# Check if already running
running, pid = lifecycle.is_running()
if not running:
    # Start in background
    pid = lifecycle.start_background(Path(".mubase"), config)
    print(f"Started with PID {pid}")

    # Or run in foreground (blocks)
    lifecycle.start_foreground(Path(".mubase"), config)
```

### Using Components Directly

```python
import asyncio
from mu.daemon import FileWatcher, UpdateQueue, GraphWorker
from mu.kernel import MUbase

# Create queue and worker
queue = UpdateQueue(debounce_ms=100)
db = MUbase(Path(".mubase"))
worker = GraphWorker(db, queue, Path("."))

# Subscribe to events
async def on_events(events):
    for event in events:
        print(f"{event.event_type}: {event.node_id}")

worker.subscribe(on_events)

# Create watcher
async def on_file_change(change_type, path):
    await queue.put(FileChange(change_type, path, time.time()))

watcher = FileWatcher([Path(".")], on_file_change)

# Start
await watcher.start()
await worker.start()

# ... run until stopped ...

# Cleanup
await watcher.stop()
await worker.stop()
db.close()
```

## File Filtering

The FileWatcher filters files based on:

1. **Supported extensions**: `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.java`, `.rs`, `.cs`
2. **Skip directories**: `.git`, `node_modules`, `__pycache__`, `.venv`, etc.
3. **Skip hidden directories**: Anything starting with `.`

## Debouncing

The UpdateQueue debounces rapid file changes:
- Multiple changes to the same file within `debounce_ms` are collapsed
- Changes to different files are not collapsed
- Use `flush()` to immediately process pending changes

## Incremental Updates

The GraphWorker performs incremental updates:

1. **File deleted**: Remove all nodes with `file_path` matching
2. **File added/modified**:
   - Parse the file
   - Compare new nodes with existing nodes
   - Generate `node_added`, `node_modified`, `node_removed` events
   - Update database

## Connection Management

WebSocket connections are managed with:
- Maximum connection limit (configurable)
- Automatic cleanup of disconnected clients
- Broadcast to all connected clients on graph changes

## Security Considerations

1. **Localhost binding**: Default host is `127.0.0.1` (not `0.0.0.0`)
2. **PID file permissions**: Created with mode 0600
3. **No authentication**: Designed for local development use

## Anti-Patterns

1. **Never** bind to 0.0.0.0 without authentication
2. **Never** expose the daemon to public networks
3. **Never** process files outside watched paths
4. **Never** make synchronous database calls in async handlers

## Testing

```bash
# Run daemon tests
pytest tests/unit/test_daemon.py -v

# Test specific component
pytest tests/unit/test_daemon.py::TestUpdateQueue -v
pytest tests/unit/test_daemon.py::TestGraphWorker -v
pytest tests/unit/test_daemon.py::TestConnectionManager -v
```

Test classes:
- `TestDaemonConfig` - Configuration validation
- `TestFileChange`, `TestGraphEvent` - Event serialization
- `TestUpdateQueue` - Debouncing behavior
- `TestFileWatcher` - File filtering
- `TestMUbaseIncrementalMethods` - Database operations
- `TestGraphWorker` - Incremental update logic
- `TestConnectionManager` - WebSocket management
- `TestDaemonLifecycle` - Process control
