"""File system watcher for daemon mode.

Watches for file changes using watchfiles and filters to supported languages.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from watchfiles import Change, awatch

from mu.paths import MU_DIR

logger = logging.getLogger(__name__)

# Supported file extensions for MU transformation
# Based on scanner/__init__.py SUPPORTED_LANGUAGES
SUPPORTED_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs"}

# Directories to skip during file watching
SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".env",
    "dist",
    "build",
    MU_DIR,  # .mu/ directory (contains mubase, cache, etc.)
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "target",  # Rust
    "bin",  # Go, C#
    "obj",  # C#
}


def _change_type_to_str(change: Change) -> str:
    """Convert watchfiles Change enum to string.

    Args:
        change: The watchfiles Change type

    Returns:
        String representation: 'added', 'modified', or 'deleted'
    """
    if change == Change.added:
        return "added"
    elif change == Change.modified:
        return "modified"
    elif change == Change.deleted:
        return "deleted"
    return "modified"  # Default fallback


class FileWatcher:
    """Async filesystem watcher with filtering.

    Watches specified paths for file changes and invokes a callback
    for supported file types, filtering out hidden and build directories.

    Attributes:
        paths: List of paths to watch
        callback: Async callback function invoked on file changes
    """

    def __init__(
        self,
        paths: list[Path],
        callback: Callable[[str, Path], Awaitable[None]],
    ) -> None:
        """Initialize the file watcher.

        Args:
            paths: List of paths to watch for changes
            callback: Async callback(change_type, path) invoked on changes
        """
        self.paths = [p.resolve() for p in paths]
        self.callback = callback
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start watching for file changes.

        Creates a background task that monitors the filesystem.
        """
        if self._task is not None:
            logger.warning("FileWatcher already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._watch())
        logger.info(f"FileWatcher started, watching {len(self.paths)} paths")

    async def stop(self) -> None:
        """Stop watching for file changes.

        Cancels the background task and waits for it to complete.
        """
        if self._task is None:
            return

        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("FileWatcher stopped")

    async def _watch(self) -> None:
        """Main watch loop - monitors filesystem and invokes callback."""
        try:
            async for changes in awatch(
                *self.paths,
                stop_event=self._stop_event,
                watch_filter=self._watch_filter,
            ):
                for change_type, path_str in changes:
                    path = Path(path_str)
                    if self._should_process(path):
                        change_str = _change_type_to_str(change_type)
                        try:
                            await self.callback(change_str, path)
                        except Exception as e:
                            logger.error(f"Error processing {path}: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"FileWatcher error: {e}")
            raise

    def _watch_filter(self, change: Change, path: str) -> bool:
        """Filter function for watchfiles.

        Args:
            change: Type of change
            path: Path to the changed file

        Returns:
            True if the change should be reported
        """
        return self._should_process(Path(path))

    def _should_process(self, path: Path) -> bool:
        """Check if a file should be processed.

        Filters to supported languages and skips hidden/build directories.

        Args:
            path: Path to check

        Returns:
            True if the file should be processed
        """
        # Skip directories
        if path.is_dir():
            return False

        # Check extension
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return False

        # Skip files in hidden/build directories
        for part in path.parts:
            if part in SKIP_DIRECTORIES:
                return False
            # Skip hidden directories (starting with .)
            if part.startswith(".") and part not in {".", ".."}:
                return False

        return True

    @property
    def is_running(self) -> bool:
        """Check if the watcher is currently running.

        Returns:
            True if the watcher is running
        """
        return self._task is not None and not self._task.done()


__all__ = [
    "FileWatcher",
    "SUPPORTED_EXTENSIONS",
    "SKIP_DIRECTORIES",
]
