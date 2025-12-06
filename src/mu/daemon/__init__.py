"""MU Daemon - Real-time file watching and HTTP/WebSocket API.

Provides a long-running daemon that:
- Watches filesystem for code changes and updates the graph incrementally
- Serves HTTP API for queries (status, nodes, MUQL, context, export)
- Provides WebSocket for real-time change notifications
- Enables IDE integration with always-current graph state

Example:
    Start the daemon from CLI:

        $ mu daemon start .
        MU daemon started on http://127.0.0.1:8765
        PID: 12345

        $ mu daemon status
        Status: running
        Uptime: 1h 23m
        Nodes: 1234
        Connections: 2

        $ mu daemon stop
        MU daemon stopped

    Or use the Python API:

        >>> from mu.daemon import DaemonConfig, DaemonLifecycle
        >>> from pathlib import Path
        >>>
        >>> config = DaemonConfig(port=8765, watch_paths=[Path(".")])
        >>> lifecycle = DaemonLifecycle()
        >>> lifecycle.start_foreground(config, Path(".mubase"))

API Endpoints:
    GET /status           - Daemon status and statistics
    GET /nodes/{id}       - Get node by ID
    GET /nodes/{id}/neighbors - Get neighboring nodes
    POST /query           - Execute MUQL query
    POST /context         - Extract smart context for question
    GET /export           - Export graph in various formats
    WS /live              - WebSocket for real-time updates
"""

from mu.daemon.config import DaemonConfig
from mu.daemon.events import FileChange, GraphEvent, UpdateQueue
from mu.daemon.lifecycle import DaemonLifecycle
from mu.daemon.server import ConnectionManager, create_app
from mu.daemon.watcher import FileWatcher
from mu.daemon.worker import GraphWorker

__all__ = [
    # Configuration
    "DaemonConfig",
    # Events
    "FileChange",
    "GraphEvent",
    "UpdateQueue",
    # Lifecycle
    "DaemonLifecycle",
    # Server
    "create_app",
    "ConnectionManager",
    # Watcher
    "FileWatcher",
    # Worker
    "GraphWorker",
]
