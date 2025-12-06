"""Graph worker for incremental updates.

Processes file changes from the UpdateQueue and incrementally updates
the MUbase graph.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from mu.daemon.events import FileChange, GraphEvent, UpdateQueue
from mu.kernel.builder import GraphBuilder
from mu.kernel.models import Node
from mu.parser.base import parse_file
from mu.scanner import detect_language

if TYPE_CHECKING:
    from mu.kernel import MUbase

logger = logging.getLogger(__name__)


class GraphWorker:
    """Process file changes and update the graph incrementally.

    Takes file change events from an UpdateQueue, parses the changed files,
    and updates the MUbase graph accordingly. Notifies subscribers of
    graph changes for WebSocket broadcast.

    Attributes:
        mubase: The MUbase database to update
        queue: The UpdateQueue to read file changes from
        root_path: Root path of the codebase
    """

    def __init__(
        self,
        mubase: MUbase,
        queue: UpdateQueue,
        root_path: Path,
    ) -> None:
        """Initialize the graph worker.

        Args:
            mubase: The MUbase database to update
            queue: The UpdateQueue to read file changes from
            root_path: Root path of the codebase
        """
        self.mubase = mubase
        self.queue = queue
        self.root_path = root_path.resolve()
        self._task: asyncio.Task[None] | None = None
        self._subscribers: list[Callable[[list[GraphEvent]], Awaitable[None]]] = []
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the worker processing loop."""
        if self._task is not None:
            logger.warning("GraphWorker already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._process_loop())
        logger.info("GraphWorker started")

    async def stop(self) -> None:
        """Stop the worker processing loop."""
        if self._task is None:
            return

        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("GraphWorker stopped")

    def subscribe(
        self,
        callback: Callable[[list[GraphEvent]], Awaitable[None]],
    ) -> None:
        """Subscribe to graph change events.

        Args:
            callback: Async callback invoked with list of GraphEvents
        """
        self._subscribers.append(callback)

    def unsubscribe(
        self,
        callback: Callable[[list[GraphEvent]], Awaitable[None]],
    ) -> None:
        """Unsubscribe from graph change events.

        Args:
            callback: The callback to remove
        """
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def _process_loop(self) -> None:
        """Main processing loop - reads from queue and updates graph."""
        try:
            while not self._stop_event.is_set():
                try:
                    # Use wait_for to allow periodic checking of stop event
                    change = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=1.0,
                    )
                except TimeoutError:
                    continue

                try:
                    events = await self._process_change(change)
                    if events:
                        await self._notify_subscribers(events)
                except Exception as e:
                    logger.error(f"Error processing change {change.path}: {e}")
                finally:
                    self.queue.task_done()

        except asyncio.CancelledError:
            raise

    async def _process_change(self, change: FileChange) -> list[GraphEvent]:
        """Process a single file change.

        Args:
            change: The file change to process

        Returns:
            List of GraphEvents describing what changed in the graph
        """
        events: list[GraphEvent] = []
        file_path = change.path
        rel_path = self._get_relative_path(file_path)

        logger.debug(f"Processing {change.change_type}: {rel_path}")

        if change.change_type == "deleted":
            events = await self._handle_file_deleted(rel_path)
        else:
            # 'added' or 'modified' - parse and update
            events = await self._handle_file_changed(file_path, rel_path)

        return events

    async def _handle_file_deleted(self, rel_path: str) -> list[GraphEvent]:
        """Handle a deleted file by removing its nodes from the graph.

        Args:
            rel_path: Relative path of the deleted file

        Returns:
            List of node_removed events
        """
        events: list[GraphEvent] = []

        # Get existing nodes for this file
        existing_nodes = self.mubase.get_nodes_by_file(rel_path)
        if not existing_nodes:
            return events

        # Generate removal events
        for node in existing_nodes:
            events.append(
                GraphEvent(
                    event_type="node_removed",
                    node_id=node.id,
                    node_type=node.type.value,
                    file_path=rel_path,
                )
            )

        # Remove nodes from database
        self.mubase.remove_nodes_by_file(rel_path)
        logger.info(f"Removed {len(events)} nodes for deleted file: {rel_path}")

        return events

    async def _handle_file_changed(
        self,
        abs_path: Path,
        rel_path: str,
    ) -> list[GraphEvent]:
        """Handle an added or modified file by parsing and updating the graph.

        Args:
            abs_path: Absolute path to the file
            rel_path: Relative path of the file

        Returns:
            List of node_added, node_modified, or node_removed events
        """
        events: list[GraphEvent] = []

        # Detect language
        language = detect_language(abs_path)
        if language is None:
            logger.debug(f"Skipping unsupported file: {rel_path}")
            return events

        # Parse the file
        parsed = parse_file(abs_path, language)
        if not parsed.success or parsed.module is None:
            logger.warning(f"Parse failed for {rel_path}: {parsed.error}")
            return events

        # Get existing nodes for this file
        existing_nodes = self.mubase.get_nodes_by_file(rel_path)
        existing_ids = {n.id for n in existing_nodes}

        # Build new nodes and edges
        builder = GraphBuilder(self.root_path)
        new_nodes, new_edges = builder.build([parsed.module])

        new_ids = {n.id for n in new_nodes}

        # Determine what changed
        added_ids = new_ids - existing_ids
        removed_ids = existing_ids - new_ids
        potentially_modified_ids = new_ids & existing_ids

        # Remove old nodes that are no longer present
        for node_id in removed_ids:
            self.mubase.remove_node(node_id)
            old_node = next((n for n in existing_nodes if n.id == node_id), None)
            if old_node:
                events.append(
                    GraphEvent(
                        event_type="node_removed",
                        node_id=node_id,
                        node_type=old_node.type.value,
                        file_path=rel_path,
                    )
                )

        # Add/update nodes
        for node in new_nodes:
            if node.id in added_ids:
                self.mubase.add_node(node)
                events.append(
                    GraphEvent(
                        event_type="node_added",
                        node_id=node.id,
                        node_type=node.type.value,
                        file_path=rel_path,
                    )
                )
            elif node.id in potentially_modified_ids:
                # Check if node actually changed
                old_node = next((n for n in existing_nodes if n.id == node.id), None)
                if old_node and self._node_changed(old_node, node):
                    self.mubase.update_node(node)
                    events.append(
                        GraphEvent(
                            event_type="node_modified",
                            node_id=node.id,
                            node_type=node.type.value,
                            file_path=rel_path,
                        )
                    )

        # Update edges (remove old, add new)
        # First remove all edges for nodes in this file
        for node_id in existing_ids:
            self.mubase.conn.execute(
                "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
                [node_id, node_id],
            )

        # Add new edges
        for edge in new_edges:
            self.mubase.add_edge(edge)

        if events:
            logger.info(
                f"Updated {rel_path}: "
                f"{len([e for e in events if e.event_type == 'node_added'])} added, "
                f"{len([e for e in events if e.event_type == 'node_modified'])} modified, "
                f"{len([e for e in events if e.event_type == 'node_removed'])} removed"
            )

        return events

    def _node_changed(self, old: Node, new: Node) -> bool:
        """Check if a node has meaningfully changed.

        Args:
            old: The old node
            new: The new node

        Returns:
            True if the node has changed
        """
        # Compare key fields
        if old.name != new.name:
            return True
        if old.qualified_name != new.qualified_name:
            return True
        if old.line_start != new.line_start or old.line_end != new.line_end:
            return True
        if old.complexity != new.complexity:
            return True

        # Compare properties (simplified)
        if old.properties != new.properties:
            return True

        return False

    def _get_relative_path(self, path: Path) -> str:
        """Get the relative path from the root.

        Args:
            path: Absolute path

        Returns:
            Relative path string
        """
        try:
            return str(path.relative_to(self.root_path))
        except ValueError:
            # Path is not under root, use absolute path
            return str(path)

    async def _notify_subscribers(self, events: list[GraphEvent]) -> None:
        """Notify all subscribers of graph events.

        Args:
            events: List of graph events to broadcast
        """
        for callback in self._subscribers:
            try:
                await callback(events)
            except Exception as e:
                logger.error(f"Error notifying subscriber: {e}")

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running.

        Returns:
            True if the worker is running
        """
        return self._task is not None and not self._task.done()


__all__ = [
    "GraphWorker",
]
