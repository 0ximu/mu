"""Graph query operations for MUbase.

This module provides query methods for traversing and searching
the code graph stored in the DuckDB database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from mu.kernel.models import Edge, Node
from mu.kernel.schema import EdgeType, NodeType

if TYPE_CHECKING:
    pass


class ConnectionProtocol(Protocol):
    """Protocol for database connection object."""

    def execute(self, sql: str, params: list[Any] | None = None) -> Any: ...


class GraphQueries:
    """Graph query operations on a DuckDB connection.

    Provides methods for querying nodes, edges, dependencies, and paths
    in the code graph. Operates on an existing database connection.
    """

    def __init__(self, conn: ConnectionProtocol) -> None:
        """Initialize with a database connection.

        Args:
            conn: DuckDB connection object.
        """
        self._conn = conn

    # =========================================================================
    # Basic Node/Edge Queries
    # =========================================================================

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID.

        Args:
            node_id: The node ID.

        Returns:
            Node if found, None otherwise.
        """
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?",
            [node_id],
        ).fetchone()
        return Node.from_row(row) if row else None

    def get_nodes(
        self,
        node_type: NodeType | None = None,
        file_path: str | None = None,
    ) -> list[Node]:
        """Get nodes with optional filtering.

        Args:
            node_type: Filter by node type.
            file_path: Filter by file path.

        Returns:
            List of matching nodes.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if node_type:
            conditions.append("type = ?")
            params.append(node_type.value)

        if file_path:
            conditions.append("file_path = ?")
            params.append(file_path)

        query = "SELECT * FROM nodes"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        rows = self._conn.execute(query, params).fetchall()
        return [Node.from_row(r) for r in rows]

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        edge_type: EdgeType | None = None,
    ) -> list[Edge]:
        """Get edges with optional filtering.

        Args:
            source_id: Filter by source node ID.
            target_id: Filter by target node ID.
            edge_type: Filter by edge type.

        Returns:
            List of matching edges.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)

        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)

        if edge_type:
            conditions.append("type = ?")
            params.append(edge_type.value)

        query = "SELECT * FROM edges"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        rows = self._conn.execute(query, params).fetchall()
        return [Edge.from_row(r) for r in rows]

    # =========================================================================
    # Dependency Traversal
    # =========================================================================

    def get_dependencies(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Node]:
        """Get nodes that this node depends on (outgoing edges).

        Args:
            node_id: The source node ID.
            depth: How many levels of dependencies to traverse (1 = direct only).
            edge_types: Filter by edge types (default: all types).

        Returns:
            List of dependent nodes.
        """
        # Build parameterized edge type filter for defense-in-depth
        type_filter = ""
        type_params: list[Any] = []
        if edge_types:
            placeholders = ", ".join("?" * len(edge_types))
            type_filter = f"AND e.type IN ({placeholders})"
            type_params = [t.value for t in edge_types]

        if depth == 1:
            params = [node_id] + type_params
            rows = self._conn.execute(
                f"""
                SELECT n.* FROM nodes n
                JOIN edges e ON n.id = e.target_id
                WHERE e.source_id = ? {type_filter}
                """,
                params,
            ).fetchall()
        else:
            # Recursive CTE for multi-level traversal
            # Note: type_params needed twice (for initial query and recursive part)
            params = [node_id] + type_params + [depth] + type_params
            rows = self._conn.execute(
                f"""
                WITH RECURSIVE deps AS (
                    SELECT target_id, 1 as depth
                    FROM edges
                    WHERE source_id = ? {type_filter}

                    UNION ALL

                    SELECT e.target_id, d.depth + 1
                    FROM deps d
                    JOIN edges e ON e.source_id = d.target_id
                    WHERE d.depth < ? {type_filter}
                )
                SELECT DISTINCT n.* FROM nodes n
                JOIN deps d ON n.id = d.target_id
                """,
                params,
            ).fetchall()

        return [Node.from_row(r) for r in rows]

    def get_dependents(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Node]:
        """Get nodes that depend on this node (incoming edges).

        Args:
            node_id: The target node ID.
            depth: How many levels to traverse (1 = direct only).
            edge_types: Filter by edge types (default: all types).

        Returns:
            List of nodes that depend on this node.
        """
        # Build parameterized edge type filter for defense-in-depth
        type_filter = ""
        type_params: list[Any] = []
        if edge_types:
            placeholders = ", ".join("?" * len(edge_types))
            type_filter = f"AND e.type IN ({placeholders})"
            type_params = [t.value for t in edge_types]

        if depth == 1:
            params = [node_id] + type_params
            rows = self._conn.execute(
                f"""
                SELECT n.* FROM nodes n
                JOIN edges e ON n.id = e.source_id
                WHERE e.target_id = ? {type_filter}
                """,
                params,
            ).fetchall()
        else:
            # Recursive CTE for multi-level traversal
            # Note: type_params needed twice (for initial query and recursive part)
            params = [node_id] + type_params + [depth] + type_params
            rows = self._conn.execute(
                f"""
                WITH RECURSIVE deps AS (
                    SELECT source_id, 1 as depth
                    FROM edges
                    WHERE target_id = ? {type_filter}

                    UNION ALL

                    SELECT e.source_id, d.depth + 1
                    FROM deps d
                    JOIN edges e ON e.target_id = d.source_id
                    WHERE d.depth < ? {type_filter}
                )
                SELECT DISTINCT n.* FROM nodes n
                JOIN deps d ON n.id = d.source_id
                """,
                params,
            ).fetchall()

        return [Node.from_row(r) for r in rows]

    def get_children(self, node_id: str) -> list[Node]:
        """Get nodes contained by this node (CONTAINS edges).

        Args:
            node_id: The parent node ID.

        Returns:
            List of child nodes.
        """
        return self.get_dependencies(node_id, depth=1, edge_types=[EdgeType.CONTAINS])

    def get_parent(self, node_id: str) -> Node | None:
        """Get the node that contains this node.

        Args:
            node_id: The child node ID.

        Returns:
            Parent node if found, None otherwise.
        """
        parents = self.get_dependents(node_id, depth=1, edge_types=[EdgeType.CONTAINS])
        return parents[0] if parents else None

    def get_neighbors(
        self,
        node_id: str,
        direction: str = "both",
    ) -> list[Node]:
        """Get neighboring nodes in the graph.

        Args:
            node_id: The node to find neighbors for.
            direction: "outgoing" (dependencies), "incoming" (dependents),
                      or "both" (default).

        Returns:
            List of neighboring nodes.
        """
        neighbors: list[Node] = []

        if direction in ("both", "outgoing"):
            neighbors.extend(self.get_dependencies(node_id, depth=1))

        if direction in ("both", "incoming"):
            neighbors.extend(self.get_dependents(node_id, depth=1))

        # Deduplicate
        seen: set[str] = set()
        unique: list[Node] = []
        for node in neighbors:
            if node.id not in seen:
                seen.add(node.id)
                unique.append(node)

        return unique

    # =========================================================================
    # Search Operations
    # =========================================================================

    def find_by_name(self, name: str, node_type: NodeType | None = None) -> list[Node]:
        """Find nodes by name (exact or pattern match).

        Args:
            name: The name to search for (supports SQL LIKE patterns with %).
            node_type: Optional filter by node type.

        Returns:
            List of matching nodes.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if "%" in name:
            conditions.append("name LIKE ?")
        else:
            conditions.append("name = ?")
        params.append(name)

        if node_type:
            conditions.append("type = ?")
            params.append(node_type.value)

        query = "SELECT * FROM nodes WHERE " + " AND ".join(conditions)
        rows = self._conn.execute(query, params).fetchall()
        return [Node.from_row(r) for r in rows]

    def find_nodes_by_suffix(
        self,
        suffix: str,
        node_type: NodeType | None = None,
    ) -> list[Node]:
        """Find nodes whose name ends with the given suffix.

        Useful for fuzzy matching when the full qualified name is not known.

        Args:
            suffix: The suffix to match (e.g., "Service", "login").
            node_type: Optional filter by node type.

        Returns:
            List of matching nodes.
        """
        return self.find_by_name(f"%{suffix}", node_type)

    def find_by_complexity(
        self,
        min_complexity: int,
        max_complexity: int | None = None,
    ) -> list[Node]:
        """Find nodes with complexity in range.

        Args:
            min_complexity: Minimum complexity (inclusive).
            max_complexity: Maximum complexity (inclusive, optional).

        Returns:
            List of nodes ordered by complexity descending.
        """
        if max_complexity:
            rows = self._conn.execute(
                """
                SELECT * FROM nodes
                WHERE complexity >= ? AND complexity <= ?
                ORDER BY complexity DESC
                """,
                [min_complexity, max_complexity],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM nodes
                WHERE complexity >= ?
                ORDER BY complexity DESC
                """,
                [min_complexity],
            ).fetchall()

        return [Node.from_row(r) for r in rows]

    def find_path(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 10,
    ) -> list[str] | None:
        """Find shortest path between two nodes.

        Args:
            from_id: Starting node ID.
            to_id: Target node ID.
            max_depth: Maximum path length to search.

        Returns:
            List of node IDs in the path, or None if no path exists.
        """
        result = self._conn.execute(
            """
            WITH RECURSIVE paths AS (
                SELECT
                    source_id,
                    target_id,
                    [source_id, target_id] as path,
                    1 as depth
                FROM edges
                WHERE source_id = ?

                UNION ALL

                SELECT
                    p.source_id,
                    e.target_id,
                    list_append(p.path, e.target_id),
                    p.depth + 1
                FROM paths p
                JOIN edges e ON p.target_id = e.source_id
                WHERE p.depth < ?
                  AND NOT list_contains(p.path, e.target_id)
            )
            SELECT path FROM paths
            WHERE target_id = ?
            ORDER BY depth
            LIMIT 1
            """,
            [from_id, max_depth, to_id],
        ).fetchone()

        return list(result[0]) if result else None


__all__ = [
    "GraphQueries",
    "ConnectionProtocol",
]
