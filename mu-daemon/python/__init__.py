"""MU Daemon - Real-time code intelligence daemon.

Provides a long-running Rust daemon (mu-daemon) that:
- Watches filesystem for code changes and updates the graph incrementally
- Serves HTTP API for queries (status, nodes, MUQL, context, export)
- Provides WebSocket for real-time change notifications
- Enables IDE integration with always-current graph state

Example:
    Start the daemon from CLI:

        $ mu daemon start .
        MU daemon started on http://127.0.0.1:9120
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
        >>> config = DaemonConfig(port=9120)
        >>> lifecycle = DaemonLifecycle(config=config)
        >>> lifecycle.start_background(Path(".mu/mubase"))

API Endpoints (Rust daemon on port 9120):
    GET /status           - Daemon status and statistics
    GET /nodes/{id}       - Get node by ID
    GET /nodes/{id}/neighbors - Get neighboring nodes
    POST /query           - Execute MUQL query
    POST /context         - Extract smart context for question
    POST /impact          - Downstream impact analysis
    POST /ancestors       - Upstream dependency analysis
    POST /cycles          - Circular dependency detection
    GET /export           - Export graph in various formats
    WS /ws                - WebSocket for real-time updates
"""

from mu.daemon.config import DaemonConfig
from mu.daemon.lifecycle import DaemonLifecycle, find_rust_daemon_binary

__all__ = [
    # Configuration
    "DaemonConfig",
    # Lifecycle
    "DaemonLifecycle",
    "find_rust_daemon_binary",
]
