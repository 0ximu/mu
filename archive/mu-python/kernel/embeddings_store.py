"""Embeddings storage operations for MUbase.

This module provides methods for storing and querying vector embeddings
in the code graph database. Supports semantic search via cosine similarity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.models import Node
from mu.kernel.schema import EMBEDDINGS_SCHEMA_SQL, NodeType

if TYPE_CHECKING:
    from mu.extras.embeddings.models import NodeEmbedding
    from mu.kernel.queries import ConnectionProtocol


class EmbeddingsStore:
    """Embeddings storage and retrieval operations.

    Provides methods for storing node embeddings and performing
    vector similarity search. Operates on an existing database connection.
    """

    def __init__(self, conn: ConnectionProtocol, read_only: bool = False) -> None:
        """Initialize with a database connection.

        Args:
            conn: DuckDB connection object.
            read_only: Whether the database is opened in read-only mode.
        """
        self._conn = conn
        self._read_only = read_only

    def _ensure_schema(self) -> None:
        """Create embeddings table if it doesn't exist.

        In read-only mode, just checks if table exists without creating.

        Raises:
            duckdb.CatalogException: If table doesn't exist in read-only mode.
        """
        try:
            self._conn.execute("SELECT 1 FROM embeddings LIMIT 1")
        except duckdb.CatalogException:
            if self._read_only:
                # In read-only mode, we can't create the table
                raise
            # Table doesn't exist, create it
            self._conn.execute(EMBEDDINGS_SCHEMA_SQL)

    def add_embedding(self, embedding: NodeEmbedding) -> None:
        """Add or update an embedding for a node.

        Args:
            embedding: The NodeEmbedding to store.
        """
        self._ensure_schema()
        self._conn.execute("DELETE FROM embeddings WHERE node_id = ?", [embedding.node_id])
        self._conn.execute(
            """
            INSERT INTO embeddings
            (node_id, code_embedding, docstring_embedding, name_embedding,
             model_name, model_version, dimensions, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            embedding.to_tuple(),
        )

    def add_embeddings_batch(self, embeddings: list[NodeEmbedding]) -> None:
        """Add multiple embeddings in a batch.

        Args:
            embeddings: List of NodeEmbedding objects to store.
        """
        if not embeddings:
            return

        self._ensure_schema()

        # Delete existing embeddings for these nodes
        node_ids = [e.node_id for e in embeddings]
        placeholders = ", ".join(["?"] * len(node_ids))
        self._conn.execute(
            f"DELETE FROM embeddings WHERE node_id IN ({placeholders})",
            node_ids,
        )

        # Insert all embeddings
        for embedding in embeddings:
            self._conn.execute(
                """
                INSERT INTO embeddings
                (node_id, code_embedding, docstring_embedding, name_embedding,
                 model_name, model_version, dimensions, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                embedding.to_tuple(),
            )

    def get_embedding(self, node_id: str) -> NodeEmbedding | None:
        """Get embedding for a node.

        Args:
            node_id: The node ID.

        Returns:
            NodeEmbedding if found, None otherwise.
        """
        from mu.extras.embeddings.models import NodeEmbedding

        self._ensure_schema()
        row = self._conn.execute(
            "SELECT * FROM embeddings WHERE node_id = ?",
            [node_id],
        ).fetchone()
        return NodeEmbedding.from_row(row) if row else None

    def vector_search(
        self,
        query_embedding: list[float],
        embedding_type: str = "code",
        limit: int = 10,
        node_type: NodeType | None = None,
    ) -> list[tuple[Node, float]]:
        """Find similar nodes by cosine similarity.

        Args:
            query_embedding: The query embedding vector.
            embedding_type: Which embedding to search ('code', 'docstring', 'name').
            limit: Maximum number of results.
            node_type: Optional filter by node type.

        Returns:
            List of (Node, similarity_score) tuples, sorted by similarity descending.

        Raises:
            ValueError: If embedding_type is invalid.
        """
        self._ensure_schema()

        # Map embedding type to column
        column_map = {
            "code": "code_embedding",
            "docstring": "docstring_embedding",
            "name": "name_embedding",
        }
        if embedding_type not in column_map:
            raise ValueError(f"Invalid embedding_type: {embedding_type}")

        column = column_map[embedding_type]

        # Build type filter
        type_filter = ""
        params: list[Any] = [query_embedding]
        if node_type:
            type_filter = "AND n.type = ?"
            params.append(node_type.value)

        params.append(limit)

        # DuckDB cosine similarity using list functions
        rows = self._conn.execute(
            f"""
            WITH query_vec AS (
                SELECT ?::FLOAT[] as vec
            ),
            similarities AS (
                SELECT
                    n.*,
                    list_cosine_similarity(e.{column}, q.vec) as similarity
                FROM nodes n
                JOIN embeddings e ON n.id = e.node_id
                CROSS JOIN query_vec q
                WHERE e.{column} IS NOT NULL
                {type_filter}
            )
            SELECT * FROM similarities
            WHERE similarity IS NOT NULL
            ORDER BY similarity DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        results: list[tuple[Node, float]] = []
        for row in rows:
            # Last column is similarity, rest are node columns
            similarity = row[-1]
            node_row = row[:-1]
            node = Node.from_row(node_row)
            results.append((node, float(similarity)))

        return results

    def has_embeddings(self) -> bool:
        """Check if the database has any embeddings.

        Returns:
            True if embeddings exist, False otherwise.
        """
        try:
            self._ensure_schema()
            result = self._conn.execute("SELECT COUNT(*) FROM embeddings LIMIT 1").fetchone()
            return result is not None and result[0] > 0
        except Exception:
            return False

    def stats(self) -> dict[str, Any]:
        """Get embedding statistics.

        Returns:
            Dictionary with embedding coverage and model info.
            Returns empty stats if embeddings table doesn't exist.
        """
        try:
            self._ensure_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            node_result = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
            total_nodes = node_result[0] if node_result else 0
            return {
                "total_nodes": total_nodes,
                "nodes_with_embeddings": 0,
                "nodes_without_embeddings": total_nodes,
                "coverage_percent": 0.0,
                "coverage_by_type": {},
                "model_distribution": {},
                "dimensions": [],
            }

        # Total nodes
        node_result = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
        total_nodes = node_result[0] if node_result else 0

        # Nodes with embeddings
        embed_result = self._conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
        nodes_with_embeddings = embed_result[0] if embed_result else 0

        # Nodes without embeddings
        nodes_without = total_nodes - nodes_with_embeddings

        # Coverage by node type
        coverage_by_type: dict[str, dict[str, int]] = {}
        type_rows = self._conn.execute(
            """
            SELECT
                n.type,
                COUNT(n.id) as total,
                COUNT(e.node_id) as with_embedding
            FROM nodes n
            LEFT JOIN embeddings e ON n.id = e.node_id
            GROUP BY n.type
            """
        ).fetchall()
        for row in type_rows:
            coverage_by_type[row[0]] = {
                "total": row[1],
                "with_embedding": row[2],
                "without_embedding": row[1] - row[2],
            }

        # Model distribution
        model_dist: dict[str, int] = {}
        model_rows = self._conn.execute(
            """
            SELECT model_name, model_version, COUNT(*)
            FROM embeddings
            GROUP BY model_name, model_version
            """
        ).fetchall()
        for row in model_rows:
            key = f"{row[0]}:{row[1]}"
            model_dist[key] = row[2]

        # Dimensions (should be consistent)
        dim_result = self._conn.execute("SELECT DISTINCT dimensions FROM embeddings").fetchall()
        dimensions = [r[0] for r in dim_result]

        return {
            "total_nodes": total_nodes,
            "nodes_with_embeddings": nodes_with_embeddings,
            "nodes_without_embeddings": nodes_without,
            "coverage_percent": (
                (nodes_with_embeddings / total_nodes * 100) if total_nodes > 0 else 0
            ),
            "coverage_by_type": coverage_by_type,
            "model_distribution": model_dist,
            "dimensions": dimensions,
        }


__all__ = [
    "EmbeddingsStore",
]
