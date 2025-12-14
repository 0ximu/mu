"""Smart routing: daemon if available, local otherwise.

This module provides a centralized helper for routing database operations
through the daemon when it's running (avoiding lock conflicts) or falling
back to direct database access when it's not.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mu.client import DaemonClient
    from mu.kernel import MUbase


@dataclass
class RoutingResult:
    """Result of get_client_or_db() call.

    Either client or db will be set, never both.
    Use `using_daemon` to check which one is active.
    """

    client: DaemonClient | None = None
    db: MUbase | None = None

    @property
    def using_daemon(self) -> bool:
        """True if using daemon client, False if using direct DB."""
        return self.client is not None


@contextmanager
def get_client_or_db(
    path: Path | None = None,
    prefer_daemon: bool = True,
    read_only: bool = True,
) -> Generator[RoutingResult, None, None]:
    """Get a daemon client or database connection, with auto-cleanup.

    This helper tries the daemon first (if prefer_daemon=True) to avoid
    database locking issues. Falls back to direct database access if the
    daemon isn't running.

    Args:
        path: Path to find .mu/mubase in. Defaults to cwd.
        prefer_daemon: If True, try daemon first. If False, always use local DB.
        read_only: If using local DB, open in read-only mode.

    Yields:
        RoutingResult with either client or db set.

    Raises:
        MUbaseLockError: If database is locked and daemon isn't available.
        FileNotFoundError: If .mu/mubase doesn't exist.

    Example:
        with get_client_or_db() as route:
            if route.using_daemon:
                result = route.client.query(muql)
            else:
                result = route.db.query(muql)
    """
    from mu.client import DaemonClient
    from mu.kernel import MUbase

    path = path or Path.cwd()

    # Try daemon first if preferred
    if prefer_daemon:
        client = DaemonClient()
        if client.is_running():
            try:
                yield RoutingResult(client=client)
                return
            finally:
                client.close()

    # Find mubase path
    from mu.commands.core import find_mubase_path

    mubase_path = find_mubase_path(path)
    if not mubase_path:
        raise FileNotFoundError(
            f"No .mu/mubase found in {path}. Run 'mu bootstrap' first."
        )

    # Open database
    db = MUbase(mubase_path, read_only=read_only)
    try:
        yield RoutingResult(db=db)
    finally:
        db.close()


def smart_route(
    path: Path | None = None,
    prefer_daemon: bool = True,
) -> tuple[DaemonClient | None, Path | None]:
    """Non-context-manager version for simple routing decisions.

    Returns (client, None) if daemon is running, else (None, mubase_path).
    Caller is responsible for cleanup.

    Args:
        path: Path to find .mu/mubase in. Defaults to cwd.
        prefer_daemon: If True, check daemon first.

    Returns:
        Tuple of (client, mubase_path). One will be None.

    Example:
        client, mubase_path = smart_route()
        if client:
            result = client.query(muql)
            client.close()
        else:
            db = MUbase(mubase_path, read_only=True)
            result = db.query(muql)
            db.close()
    """
    from mu.client import DaemonClient
    from mu.commands.core import find_mubase_path

    path = path or Path.cwd()

    if prefer_daemon:
        client = DaemonClient()
        if client.is_running():
            return client, None

    mubase_path = find_mubase_path(path)
    return None, mubase_path
