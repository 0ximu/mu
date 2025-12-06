"""MUbase - Graph database for code analysis.

DuckDB-based storage for the codebase graph with support for
recursive dependency queries.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.builder import GraphBuilder
from mu.kernel.models import Edge, Node
from mu.kernel.schema import SCHEMA_SQL, EdgeType, NodeType

if TYPE_CHECKING:
    from mu.parser.models import ModuleDef


class MUbase:
    """Graph database for code analysis.

    Stores the codebase as nodes (modules, classes, functions) and
    edges (contains, imports, inherits) in a DuckDB database file.
    """

    VERSION = "1.0.0"

    def __init__(self, path: Path | str = ".mubase") -> None:
        """Initialize MUbase.

        Args:
            path: Path to the .mubase file (created if doesn't exist)
        """
        self.path = Path(path)
        self.conn = duckdb.connect(str(self.path))
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema if needed."""
        try:
            result = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'version'"
            ).fetchone()
            if result:
                version = result[0]
                if version != self.VERSION:
                    self._migrate(version)
        except duckdb.CatalogException:
            # Tables don't exist yet, create them
            self._create_schema()

    def _create_schema(self) -> None:
        """Create all tables and indexes."""
        self.conn.execute(SCHEMA_SQL)
        self.conn.execute(
            "INSERT INTO metadata VALUES ('version', ?)",
            [self.VERSION],
        )
        self.conn.execute(
            "INSERT INTO metadata VALUES ('created_at', CURRENT_TIMESTAMP)",
        )

    def _migrate(self, from_version: str) -> None:
        """Migrate schema from older version.

        For now, just recreate the schema. Future versions may need
        actual migration logic.
        """
        self.conn.execute("DROP TABLE IF EXISTS edges")
        self.conn.execute("DROP TABLE IF EXISTS nodes")
        self.conn.execute("DROP TABLE IF EXISTS metadata")
        self._create_schema()

    def build(self, modules: list[ModuleDef], root_path: Path) -> None:
        """Build graph from parsed modules.

        Clears existing data and populates with new graph.

        Args:
            modules: List of parsed ModuleDef objects
            root_path: Root path of the codebase
        """
        nodes, edges = GraphBuilder.from_module_defs(modules, root_path)

        # Clear existing data
        self.conn.execute("DELETE FROM edges")
        self.conn.execute("DELETE FROM nodes")

        # Update build timestamp
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata VALUES ('built_at', CURRENT_TIMESTAMP)"
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata VALUES ('root_path', ?)",
            [str(root_path)],
        )

        # Insert nodes
        for node in nodes:
            self.add_node(node)

        # Insert edges
        for edge in edges:
            self.add_edge(edge)

    def add_node(self, node: Node) -> None:
        """Add or update a node in the graph."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO nodes
            (id, type, name, qualified_name, file_path,
             line_start, line_end, properties, complexity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            node.to_tuple(),
        )

    def add_edge(self, edge: Edge) -> None:
        """Add or update an edge in the graph."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO edges
            (id, source_id, target_id, type, properties)
            VALUES (?, ?, ?, ?, ?)
            """,
            edge.to_tuple(),
        )

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID.

        Args:
            node_id: The node ID

        Returns:
            Node if found, None otherwise
        """
        row = self.conn.execute(
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
            node_type: Filter by node type
            file_path: Filter by file path

        Returns:
            List of matching nodes
        """
        conditions = []
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

        rows = self.conn.execute(query, params).fetchall()
        return [Node.from_row(r) for r in rows]

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        edge_type: EdgeType | None = None,
    ) -> list[Edge]:
        """Get edges with optional filtering.

        Args:
            source_id: Filter by source node ID
            target_id: Filter by target node ID
            edge_type: Filter by edge type

        Returns:
            List of matching edges
        """
        conditions = []
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

        rows = self.conn.execute(query, params).fetchall()
        return [Edge.from_row(r) for r in rows]

    def get_dependencies(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Node]:
        """Get nodes that this node depends on (outgoing edges).

        Args:
            node_id: The source node ID
            depth: How many levels of dependencies to traverse (1 = direct only)
            edge_types: Filter by edge types (default: all types)

        Returns:
            List of dependent nodes
        """
        type_filter = ""
        if edge_types:
            types = ", ".join(f"'{t.value}'" for t in edge_types)
            type_filter = f"AND type IN ({types})"

        if depth == 1:
            rows = self.conn.execute(
                f"""
                SELECT n.* FROM nodes n
                JOIN edges e ON n.id = e.target_id
                WHERE e.source_id = ? {type_filter}
                """,
                [node_id],
            ).fetchall()
        else:
            # Recursive CTE for multi-level traversal
            rows = self.conn.execute(
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
                [node_id, depth],
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
            node_id: The target node ID
            depth: How many levels to traverse (1 = direct only)
            edge_types: Filter by edge types (default: all types)

        Returns:
            List of nodes that depend on this node
        """
        type_filter = ""
        if edge_types:
            types = ", ".join(f"'{t.value}'" for t in edge_types)
            type_filter = f"AND type IN ({types})"

        if depth == 1:
            rows = self.conn.execute(
                f"""
                SELECT n.* FROM nodes n
                JOIN edges e ON n.id = e.source_id
                WHERE e.target_id = ? {type_filter}
                """,
                [node_id],
            ).fetchall()
        else:
            # Recursive CTE for multi-level traversal
            rows = self.conn.execute(
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
                [node_id, depth],
            ).fetchall()

        return [Node.from_row(r) for r in rows]

    def get_children(self, node_id: str) -> list[Node]:
        """Get nodes contained by this node (CONTAINS edges).

        Args:
            node_id: The parent node ID

        Returns:
            List of child nodes
        """
        return self.get_dependencies(node_id, depth=1, edge_types=[EdgeType.CONTAINS])

    def get_parent(self, node_id: str) -> Node | None:
        """Get the node that contains this node.

        Args:
            node_id: The child node ID

        Returns:
            Parent node if found, None otherwise
        """
        parents = self.get_dependents(node_id, depth=1, edge_types=[EdgeType.CONTAINS])
        return parents[0] if parents else None

    def find_by_name(self, name: str, node_type: NodeType | None = None) -> list[Node]:
        """Find nodes by name (exact or pattern match).

        Args:
            name: The name to search for (supports SQL LIKE patterns with %)
            node_type: Optional filter by node type

        Returns:
            List of matching nodes
        """
        conditions = []
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
        rows = self.conn.execute(query, params).fetchall()
        return [Node.from_row(r) for r in rows]

    def find_by_complexity(
        self,
        min_complexity: int,
        max_complexity: int | None = None,
    ) -> list[Node]:
        """Find nodes with complexity in range.

        Args:
            min_complexity: Minimum complexity (inclusive)
            max_complexity: Maximum complexity (inclusive, optional)

        Returns:
            List of nodes ordered by complexity descending
        """
        if max_complexity:
            rows = self.conn.execute(
                """
                SELECT * FROM nodes
                WHERE complexity >= ? AND complexity <= ?
                ORDER BY complexity DESC
                """,
                [min_complexity, max_complexity],
            ).fetchall()
        else:
            rows = self.conn.execute(
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
            from_id: Starting node ID
            to_id: Target node ID
            max_depth: Maximum path length to search

        Returns:
            List of node IDs in the path, or None if no path exists
        """
        result = self.conn.execute(
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

    def stats(self) -> dict[str, Any]:
        """Get database statistics.

        Returns:
            Dictionary with node/edge counts and other stats
        """
        node_count = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        by_type: dict[str, int] = {}
        for row in self.conn.execute(
            "SELECT type, COUNT(*) FROM nodes GROUP BY type"
        ).fetchall():
            by_type[row[0]] = row[1]

        edges_by_type: dict[str, int] = {}
        for row in self.conn.execute(
            "SELECT type, COUNT(*) FROM edges GROUP BY type"
        ).fetchall():
            edges_by_type[row[0]] = row[1]

        # Get metadata
        metadata: dict[str, str] = {}
        for row in self.conn.execute("SELECT key, value FROM metadata").fetchall():
            metadata[row[0]] = row[1]

        file_size = self.path.stat().st_size if self.path.exists() else 0

        return {
            "nodes": node_count,
            "edges": edge_count,
            "nodes_by_type": by_type,
            "edges_by_type": edges_by_type,
            "file_size_kb": file_size / 1024,
            "version": metadata.get("version", self.VERSION),
            "built_at": metadata.get("built_at"),
            "root_path": metadata.get("root_path"),
        }

    def execute(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        """Execute raw SQL query.

        For advanced queries not covered by convenience methods.

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            List of result rows as tuples
        """
        if params:
            return self.conn.execute(sql, params).fetchall()
        return self.conn.execute(sql).fetchall()

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    def __enter__(self) -> MUbase:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()


__all__ = [
    "MUbase",
]
