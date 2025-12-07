"""Graph Reasoning Engine - High-performance graph algorithms via petgraph.

This module provides a Python interface to the Rust-based GraphEngine for
operations that SQL handles poorly: cycle detection, impact analysis, and
path finding.

Architecture:
    DuckDB (storage) -> GraphManager (loads data) -> GraphEngine (Rust/petgraph)

Usage:
    >>> from mu.kernel.graph import GraphManager
    >>> gm = GraphManager(db)
    >>> gm.load()
    >>> cycles = gm.find_cycles()
    >>> impact = gm.impact_analysis("mod:src/auth.py")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


@dataclass
class GraphStats:
    """Statistics about the loaded graph."""

    node_count: int
    edge_count: int
    edge_types: list[str]


class GraphManager:
    """Manages the petgraph-based GraphEngine lifecycle.

    Loads node/edge data from DuckDB into the Rust GraphEngine and
    provides a high-level Python API for graph algorithms.
    """

    def __init__(self, db: DuckDBPyConnection) -> None:
        """Initialize GraphManager.

        Args:
            db: DuckDB connection (from MUbase.conn)
        """
        self.db = db
        self._engine: object | None = None

    def load(self) -> GraphStats:
        """Load graph data from DuckDB into petgraph.

        Should be called after any DuckDB changes to refresh the in-memory graph.

        Returns:
            GraphStats with node/edge counts and edge types.

        Raises:
            ImportError: If mu._core is not available (Rust extension not built).
        """
        try:
            from mu import _core
        except ImportError as e:
            raise ImportError(
                "mu._core not available. Build the Rust extension with: "
                "cd mu-core && maturin develop --release"
            ) from e

        # Fetch all node IDs
        node_rows = self.db.execute("SELECT id FROM nodes").fetchall()
        nodes = [row[0] for row in node_rows]

        # Fetch all edges as (source, target, type) tuples
        edge_rows = self.db.execute(
            "SELECT source_id, target_id, type FROM edges"
        ).fetchall()
        edges = [(row[0], row[1], row[2]) for row in edge_rows]

        # Create the Rust GraphEngine
        self._engine = _core.GraphEngine(nodes, edges)

        return GraphStats(
            node_count=self._engine.node_count(),
            edge_count=self._engine.edge_count(),
            edge_types=self._engine.edge_types(),
        )

    def is_loaded(self) -> bool:
        """Check if the GraphEngine is loaded.

        Returns:
            True if load() has been called successfully.
        """
        return self._engine is not None

    def _ensure_loaded(self) -> None:
        """Ensure engine is loaded, raise if not."""
        if self._engine is None:
            raise RuntimeError(
                "GraphEngine not loaded. Call load() first to hydrate from DuckDB."
            )

    # =========================================================================
    # Graph Algorithms
    # =========================================================================

    def find_cycles(self, edge_types: list[str] | None = None) -> list[list[str]]:
        """Find all strongly connected components with >1 node (cycles).

        Uses Kosaraju's algorithm: O(V + E)

        Args:
            edge_types: Optional list of edge types to consider.
                       If None, all edges are used.
                       Example: ["imports"] to find only import cycles.

        Returns:
            List of cycles, where each cycle is a list of node IDs.

        Example:
            >>> cycles = gm.find_cycles()
            >>> import_cycles = gm.find_cycles(["imports"])
        """
        self._ensure_loaded()
        return self._engine.find_cycles(edge_types)

    def impact(
        self,
        node_id: str,
        edge_types: list[str] | None = None,
    ) -> list[str]:
        """Find all nodes reachable FROM this node (downstream impact).

        "If I change X, what might break?"

        Uses BFS traversal: O(V + E)

        Args:
            node_id: Starting node ID
            edge_types: Optional list of edge types to follow.
                       Example: ["imports"] for static dependencies.

        Returns:
            List of node IDs that are downstream of the given node.

        Example:
            >>> # What breaks if I change auth.py?
            >>> gm.impact("mod:src/auth.py")
            >>> # Only consider import relationships
            >>> gm.impact("mod:src/auth.py", ["imports"])
        """
        self._ensure_loaded()
        return self._engine.impact(node_id, edge_types)

    def ancestors(
        self,
        node_id: str,
        edge_types: list[str] | None = None,
    ) -> list[str]:
        """Find all nodes that can REACH this node (upstream ancestors).

        "What does X depend on?"

        Uses BFS traversal: O(V + E)

        Args:
            node_id: Starting node ID
            edge_types: Optional list of edge types to follow.

        Returns:
            List of node IDs that are upstream of the given node.

        Example:
            >>> # What does login() depend on?
            >>> gm.ancestors("fn:src/auth.py:login")
        """
        self._ensure_loaded()
        return self._engine.ancestors(node_id, edge_types)

    def shortest_path(
        self,
        from_id: str,
        to_id: str,
        edge_types: list[str] | None = None,
    ) -> list[str] | None:
        """Find shortest path between two nodes.

        Uses BFS (unweighted): O(V + E)

        Args:
            from_id: Source node ID
            to_id: Target node ID
            edge_types: Optional list of edge types to follow.

        Returns:
            List of node IDs forming the path, or None if no path exists.

        Example:
            >>> path = gm.shortest_path("mod:a.py", "mod:z.py")
            >>> if path:
            ...     print(" -> ".join(path))
        """
        self._ensure_loaded()
        return self._engine.shortest_path(from_id, to_id, edge_types)

    def neighbors(
        self,
        node_id: str,
        direction: str = "both",
        depth: int = 1,
        edge_types: list[str] | None = None,
    ) -> list[str]:
        """Find neighbors of a node.

        Args:
            node_id: Node ID to find neighbors of
            direction: "outgoing", "incoming", or "both"
            depth: How many levels to traverse (default 1)
            edge_types: Optional list of edge types to follow.

        Returns:
            List of neighbor node IDs.

        Example:
            >>> # Direct dependencies
            >>> gm.neighbors("mod:src/cli.py", "outgoing", 1)
            >>> # What imports this file (2 levels deep)?
            >>> gm.neighbors("mod:src/auth.py", "incoming", 2, ["imports"])
        """
        self._ensure_loaded()
        return self._engine.neighbors(node_id, direction, depth, edge_types)

    def has_node(self, node_id: str) -> bool:
        """Check if a node exists in the graph.

        Args:
            node_id: The node ID to check.

        Returns:
            True if the node exists.
        """
        self._ensure_loaded()
        return self._engine.has_node(node_id)

    def stats(self) -> GraphStats:
        """Get current graph statistics.

        Returns:
            GraphStats with node/edge counts and edge types.
        """
        self._ensure_loaded()
        return GraphStats(
            node_count=self._engine.node_count(),
            edge_count=self._engine.edge_count(),
            edge_types=self._engine.edge_types(),
        )


__all__ = ["GraphManager", "GraphStats"]
