"""Event models for daemon file watching and graph updates.

Defines event types for file changes and graph updates, plus a debouncing
queue for file changes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FileChange:
    """A file change event from the filesystem watcher.

    Attributes:
        change_type: Type of change - 'added', 'modified', or 'deleted'
        path: Path to the changed file
        timestamp: Unix timestamp when the change was detected
    """

    change_type: str  # 'added', 'modified', 'deleted'
    path: Path
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "change_type": self.change_type,
            "path": str(self.path),
            "timestamp": self.timestamp,
        }


@dataclass
class GraphEvent:
    """A graph change event for WebSocket broadcast.

    Represents a change to the code graph that should be broadcast
    to connected WebSocket clients.

    Attributes:
        event_type: Type of graph change - 'node_added', 'node_modified', 'node_removed'
        node_id: ID of the affected node
        node_type: Type of the node (module, class, function, external)
        file_path: Path to the file containing the node (optional)
    """

    event_type: str  # 'node_added', 'node_modified', 'node_removed'
    node_id: str
    node_type: str
    file_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "file_path": self.file_path,
        }


class UpdateQueue:
    """Debouncing queue for file changes.

    Collects file change events and debounces rapid changes to the same file,
    emitting batched updates after the debounce delay.

    Attributes:
        debounce_ms: Debounce delay in milliseconds
    """

    def __init__(self, debounce_ms: int = 100) -> None:
        """Initialize the update queue.

        Args:
            debounce_ms: Debounce delay in milliseconds (default: 100)
        """
        self.debounce_ms = debounce_ms
        self._pending: dict[str, FileChange] = {}
        self._queue: asyncio.Queue[FileChange] = asyncio.Queue()
        self._debounce_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def put(self, change: FileChange) -> None:
        """Add a file change to the queue.

        If a change for the same file is already pending, it will be
        replaced with the new change (debouncing).

        Args:
            change: The file change event to queue
        """
        async with self._lock:
            path_key = str(change.path)
            self._pending[path_key] = change

            # Start or restart the debounce timer
            if self._debounce_task is not None:
                self._debounce_task.cancel()
                try:
                    await self._debounce_task
                except asyncio.CancelledError:
                    pass

            self._debounce_task = asyncio.create_task(self._flush_after_delay())

    async def _flush_after_delay(self) -> None:
        """Wait for debounce delay then flush pending changes to queue."""
        await asyncio.sleep(self.debounce_ms / 1000.0)

        async with self._lock:
            for change in self._pending.values():
                await self._queue.put(change)
            self._pending.clear()
            self._debounce_task = None

    async def get(self) -> FileChange:
        """Get the next file change from the queue.

        Blocks until a change is available.

        Returns:
            The next file change event
        """
        return await self._queue.get()

    def task_done(self) -> None:
        """Mark the current task as done."""
        self._queue.task_done()

    def empty(self) -> bool:
        """Check if the queue is empty.

        Note: This doesn't account for pending debounced changes.

        Returns:
            True if no changes are waiting in the output queue
        """
        return self._queue.empty()

    async def flush(self) -> None:
        """Immediately flush all pending changes to the queue.

        Useful for shutdown or testing.
        """
        async with self._lock:
            if self._debounce_task is not None:
                self._debounce_task.cancel()
                try:
                    await self._debounce_task
                except asyncio.CancelledError:
                    pass
                self._debounce_task = None

            for change in self._pending.values():
                await self._queue.put(change)
            self._pending.clear()

    def pending_count(self) -> int:
        """Get count of pending (debouncing) changes.

        Returns:
            Number of changes waiting for debounce to complete
        """
        return len(self._pending)

    def queued_count(self) -> int:
        """Get count of queued (ready) changes.

        Returns:
            Number of changes ready to be processed
        """
        return self._queue.qsize()


__all__ = [
    "FileChange",
    "GraphEvent",
    "UpdateQueue",
]
