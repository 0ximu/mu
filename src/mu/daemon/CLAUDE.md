# Daemon Module - Rust Daemon Lifecycle Management

The daemon module provides lifecycle management for the Rust mu-daemon binary, which handles real-time file watching, incremental graph updates, and HTTP/WebSocket APIs.

## Architecture

```
Python CLI (mu daemon start/stop/status)
       |
       v
DaemonLifecycle (process management)
       |
       v
mu-daemon (Rust binary)
       |
       +---> File Watcher (watchfiles in Rust)
       +---> Graph Storage (petgraph + SQLite)
       +---> HTTP API (Axum)
       +---> WebSocket (real-time updates)
```

### Files

| File | Purpose |
|------|---------|
| `config.py` | `DaemonConfig` - host, port, watch paths, debounce |
| `lifecycle.py` | `DaemonLifecycle` - start/stop/status, binary discovery |
| `__init__.py` | Public exports |

## Data Models

### DaemonConfig

```python
from mu.daemon import DaemonConfig

config = DaemonConfig(
    host="127.0.0.1",      # Bind to localhost only (security)
    port=9120,              # Default port (Rust daemon)
    watch_paths=[Path(".")], # Paths to monitor
    debounce_ms=100,        # Debounce delay for file changes
    max_connections=100,    # WebSocket connection limit
    pid_file=Path(".mu/daemon.pid"), # PID file location
)
```

## CLI Commands

```bash
# Start daemon in background
mu daemon start .
mu daemon start . --port 9000

# Check daemon status
mu daemon status
mu daemon status --json

# Stop daemon
mu daemon stop

# Run in foreground (for debugging)
mu daemon run .
```

## HTTP API (Rust Daemon on Port 9120)

### GET /status

Returns daemon status and statistics.

```json
{
  "status": "running",
  "mubase_path": "/path/to/.mu/mubase",
  "stats": {"nodes": 1234, "edges": 5678},
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

Execute a MUQL query and return results as a JSON object.

**Request body:**
```json
{
  "muql": "FIND CLASS WHERE name LIKE '%Service%'"
}
```

**Response:**
```json
{
  "columns": ["id", "name", "type"],
  "rows": [
    ["class:AuthService", "AuthService", "class"],
    ["class:UserService", "UserService", "class"]
  ]
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

### POST /impact

Downstream impact analysis - "if I change X, what might break?"

### POST /ancestors

Upstream dependency analysis - "what does X depend on?"

### POST /cycles

Circular dependency detection.

### GET /export

Export graph in various formats. Query params:
- `format`: mu, json, mermaid, d2, cytoscape
- `nodes`: Comma-separated node IDs
- `types`: Comma-separated node types
- `max_nodes`: Maximum nodes

### WS /ws

WebSocket endpoint for real-time graph updates.

## Python API

### Starting Daemon Programmatically

```python
from pathlib import Path
from mu.daemon import DaemonConfig, DaemonLifecycle

config = DaemonConfig(port=9120)
lifecycle = DaemonLifecycle(config=config)

# Check if already running
running, pid = lifecycle.is_running()
if not running:
    # Start in background (uses Rust daemon)
    pid = lifecycle.start_background(Path(".mu/mubase"))
    print(f"Started with PID {pid}")

    # Or run in foreground (blocks)
    lifecycle.start_foreground(Path(".mu/mubase"))
```

### Finding the Rust Binary

```python
from mu.daemon import find_rust_daemon_binary

binary = find_rust_daemon_binary()
if binary:
    print(f"Found: {binary}")
else:
    print("Build with: cd mu-daemon && cargo build --release")
```

## Rust Daemon Binary

The Rust daemon (`mu-daemon`) is the production backend. Build it with:

```bash
cd mu-daemon
cargo build --release
```

Binary search order:
1. `mu-daemon` in PATH (installed via `cargo install`)
2. `mu-daemon/target/release/mu-daemon` (dev release build)
3. `mu-daemon/target/debug/mu-daemon` (dev debug build)

### Rust Daemon CLI

```bash
# Start with graph build
mu-daemon /path/to/project --build --port 9120

# Enable verbose logging
mu-daemon . -v

# MCP mode (for Claude Code integration)
mu-daemon . --mcp
```

## Security Considerations

1. **Localhost binding**: Default host is `127.0.0.1` (not `0.0.0.0`)
2. **PID file permissions**: Created with mode 0600
3. **No authentication**: Designed for local development use

## Migration from Python Daemon

The Python daemon (FastAPI on port 8765) has been replaced by the Rust daemon (Axum on port 9120). Key changes:

- Default port changed from 8765 to 9120
- Python daemon code removed (`server.py`, `worker.py`, `watcher.py`, `events.py`)
- `lifecycle.py` now exclusively uses Rust binary
- All MCP tools work with Rust daemon via `client.py`

## Testing

```bash
# Run daemon lifecycle tests
pytest tests/unit/test_daemon.py -v

# Test Rust daemon integration
pytest tests/unit/test_daemon.py::TestDaemonLifecycle -v
```

Test classes:
- `TestDaemonConfig` - Configuration validation
- `TestDaemonLifecycle` - PID file management, start/stop
- `TestFindRustDaemonBinary` - Binary discovery
- `TestDaemonLifecycleStartBackground` - Background start
- `TestDaemonLifecycleStartForeground` - Foreground start
