"""Daemon configuration models.

Defines configuration for the MU daemon server including host, port,
file watching settings, and WebSocket connection limits.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DaemonConfig(BaseModel):
    """Configuration for the MU daemon server.

    Attributes:
        host: Server host to bind to (default: localhost only for security)
        port: Server port (default: 8765)
        watch_paths: Paths to watch for file changes
        debounce_ms: Debounce delay in milliseconds for file changes
        pid_file: Path to PID file for daemon management
        max_connections: Maximum WebSocket connections allowed
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    host: str = Field(
        default="127.0.0.1",
        description="Server host to bind to",
    )
    port: int = Field(
        default=8765,
        description="Server port",
    )
    watch_paths: list[Path] = Field(
        default_factory=list,
        description="Paths to watch for file changes",
    )
    debounce_ms: int = Field(
        default=100,
        description="Debounce delay in milliseconds",
    )
    pid_file: Path = Field(
        default=Path(".mu.pid"),
        description="PID file path for daemon management",
    )
    max_connections: int = Field(
        default=100,
        description="Maximum WebSocket connections",
    )


__all__ = ["DaemonConfig"]
