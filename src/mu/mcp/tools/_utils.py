"""Shared utilities for MCP tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mu.client import DEFAULT_DAEMON_URL, DaemonClient, DaemonError
from mu.paths import find_mubase_path

logger = logging.getLogger(__name__)


def get_client() -> DaemonClient:
    """Get a daemon client, raising if daemon not running."""
    client = DaemonClient(base_url=DEFAULT_DAEMON_URL)
    if not client.is_running():
        client.close()
        raise DaemonError("MU daemon is not running. Start it with: mu daemon start .")
    return client


def find_mubase() -> Path | None:
    """Find mubase file in current directory or parents."""
    return find_mubase_path(Path.cwd())


def resolve_node_id(db: Any, node_ref: str, root_path: Path | None = None) -> str:
    """Resolve a node reference to a full node ID.

    Handles:
    - Full node IDs: mod:src/cli.py, cls:src/file.py:ClassName
    - Simple names: MUbase, AuthService
    - File paths: src/hooks/useTransactions.ts -> mod:...
    - Absolute paths: /Users/.../src/auth.py -> mod:...

    Args:
        db: MUbase instance
        node_ref: Node reference (ID, name, or file path)
        root_path: Project root path for resolving relative paths

    Returns:
        Resolved node ID or original string if not found
    """
    # If it already looks like a full node ID, return it
    if node_ref.startswith(("mod:", "cls:", "fn:")):
        return node_ref

    # Try exact name match first
    nodes = db.find_by_name(node_ref)
    if nodes:
        return str(nodes[0].id)

    # Check if it looks like a file path
    looks_like_path = (
        "/" in node_ref
        or "\\" in node_ref
        or node_ref.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs"))
    )

    if looks_like_path:
        # Try to resolve as file path
        ref_path = Path(node_ref)

        # If absolute path, try to make it relative to root
        if ref_path.is_absolute() and root_path:
            try:
                ref_path = ref_path.relative_to(root_path)
            except ValueError:
                pass

        # Normalize path separators
        normalized_path = str(ref_path).replace("\\", "/")

        # Try exact file_path match via SQL
        result = db.execute(
            "SELECT id FROM nodes WHERE file_path = ? AND type = 'module' LIMIT 1",
            [normalized_path],
        )
        if result:
            return str(result[0][0])

        # Try matching with path suffix
        result = db.execute(
            "SELECT id FROM nodes WHERE file_path LIKE ? AND type = 'module' LIMIT 1",
            [f"%{normalized_path}"],
        )
        if result:
            return str(result[0][0])

        # Try constructing the node ID directly
        possible_id = f"mod:{normalized_path}"
        if db.get_node(possible_id):
            return possible_id

    # Try pattern match on name
    nodes = db.find_by_name(f"%{node_ref}%")
    if nodes:
        for node in nodes:
            if node.name == node_ref:
                return str(node.id)
        return str(nodes[0].id)

    return node_ref
