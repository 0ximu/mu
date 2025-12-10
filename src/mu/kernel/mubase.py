"""MUbase - Graph database for code analysis.

DuckDB-based storage for the codebase graph with support for
recursive dependency queries.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.builder import GraphBuilder
from mu.kernel.models import Edge, Node
from mu.kernel.schema import (
    EMBEDDINGS_SCHEMA_SQL,
    PATTERNS_SCHEMA_SQL,
    SCHEMA_SQL,
    TEMPORAL_SCHEMA_SQL,
    EdgeType,
    NodeType,
)
from mu.paths import MUBASE_FILE, get_mu_dir

if TYPE_CHECKING:
    from mu.kernel.embeddings.models import NodeEmbedding
    from mu.parser.models import ModuleDef


class MUbaseCorruptionError(Exception):
    """Raised when the .mubase database is corrupted.

    This typically happens when the WAL file is corrupted due to
    an unclean shutdown. The fix is to remove the .mubase* files
    and rebuild with `mu build`.
    """

    pass


class MUbaseLockError(Exception):
    """Raised when the database is locked by another process.

    This typically happens when the daemon is running and holding
    a write lock on the database.
    """

    pass


class MUbase:
    """Graph database for code analysis.

    Stores the codebase as nodes (modules, classes, functions) and
    edges (contains, imports, inherits) in a DuckDB database file.
    """

    VERSION = "1.0.0"

    def __init__(self, path: Path | str | None = None, read_only: bool = False) -> None:
        """Initialize MUbase.

        Args:
            path: Path to the mubase file. If None, uses .mu/mubase in cwd.
                  Can be a full path or just a directory (mubase file inferred).
            read_only: If True, open in read-only mode (avoids lock conflicts)

        Raises:
            MUbaseCorruptionError: If the database or WAL file is corrupted
            MUbaseLockError: If the database is locked and read_only=False
        """
        # Handle special :memory: case for in-memory DuckDB (used in tests)
        if path is not None and str(path) == ":memory:":
            self.path = Path(":memory:")
        elif path is None:
            # Default: .mu/mubase in current directory
            self.path = get_mu_dir() / MUBASE_FILE
        else:
            path = Path(path)
            if path.is_dir():
                # Directory provided - use .mu/mubase within it
                self.path = get_mu_dir(path) / MUBASE_FILE
            elif path.name == MUBASE_FILE or path.suffix == ".mubase":
                # Full path to mubase file provided
                self.path = path
            else:
                # Assume it's a project root, use .mu/mubase
                self.path = get_mu_dir(path) / MUBASE_FILE
        self.read_only = read_only

        # Ensure parent directory exists (create .mu/ if needed)
        # Skip for :memory: (in-memory DuckDB) to avoid creating literal ":memory:" directory
        if not read_only and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self.conn = duckdb.connect(str(self.path), read_only=read_only)
            self._init_schema()
        except duckdb.Error as e:
            error_msg = str(e).lower()
            if "lock" in error_msg or "locked" in error_msg:
                raise MUbaseLockError(
                    f"Database is locked by another process.\n\n"
                    f"This usually means the daemon is running. Options:\n"
                    f"  1. Use 'mu daemon start' and let commands route through daemon\n"
                    f"  2. Stop the daemon with 'mu daemon stop'\n"
                    f"  3. Use read-only mode for query commands\n\n"
                    f"Original error: {e}"
                ) from e
            if "wal" in error_msg or "corrupt" in error_msg or "internal" in error_msg:
                wal_file = self.path.parent / f"{self.path.name}.wal"
                raise MUbaseCorruptionError(
                    f"Database appears corrupted: {e}\n\n"
                    f"To fix, remove the database files and rebuild:\n"
                    f"  rm {self.path}*\n"
                    f"  mu build .\n\n"
                    f"WAL file exists: {wal_file.exists()}"
                ) from e
            raise

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
            # Ensure temporal and patterns tables exist (may be missing from older versions)
            self._ensure_optional_schemas()
        except duckdb.CatalogException:
            # Tables don't exist yet, create them
            self._create_schema()

    def _ensure_optional_schemas(self) -> None:
        """Ensure optional schemas exist (temporal, patterns).

        These may be missing from databases created before these features
        were added. Safe to run multiple times (CREATE TABLE IF NOT EXISTS).
        """
        if self.read_only:
            return
        try:
            self.conn.execute(TEMPORAL_SCHEMA_SQL)
            self.conn.execute(PATTERNS_SCHEMA_SQL)
        except Exception:
            # Ignore errors - tables may already exist or db may be read-only
            pass

    def _create_schema(self) -> None:
        """Create all tables and indexes."""
        self.conn.execute(SCHEMA_SQL)
        # Create temporal schema (snapshots, node_history, edge_history)
        self.conn.execute(TEMPORAL_SCHEMA_SQL)
        # Create patterns schema
        self.conn.execute(PATTERNS_SCHEMA_SQL)
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
        self.conn.execute("INSERT OR REPLACE INTO metadata VALUES ('built_at', CURRENT_TIMESTAMP)")
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

        # Compute and store language statistics
        self._compute_and_store_language_stats(modules)

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
        # Delete existing edge with same ID first, then insert
        self.conn.execute("DELETE FROM edges WHERE id = ?", [edge.id])
        self.conn.execute(
            """
            INSERT INTO edges
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
            type_filter = f"AND e.type IN ({types})"

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
            type_filter = f"AND e.type IN ({types})"

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
        node_result = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
        node_count = node_result[0] if node_result else 0

        edge_result = self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()
        edge_count = edge_result[0] if edge_result else 0

        by_type: dict[str, int] = {}
        for row in self.conn.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type").fetchall():
            by_type[row[0]] = row[1]

        edges_by_type: dict[str, int] = {}
        for row in self.conn.execute("SELECT type, COUNT(*) FROM edges GROUP BY type").fetchall():
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

    # =========================================================================
    # Embeddings Methods
    # =========================================================================

    def _ensure_embeddings_schema(self) -> None:
        """Create embeddings table if it doesn't exist.

        In read-only mode, just checks if table exists without creating.
        """
        try:
            self.conn.execute("SELECT 1 FROM embeddings LIMIT 1")
        except duckdb.CatalogException:
            if self.read_only:
                # In read-only mode, we can't create the table
                # Just let the caller handle the missing table
                raise
            # Table doesn't exist, create it
            self.conn.execute(EMBEDDINGS_SCHEMA_SQL)

    def add_embedding(self, embedding: NodeEmbedding) -> None:
        """Add or update an embedding for a node.

        Args:
            embedding: The NodeEmbedding to store
        """
        self._ensure_embeddings_schema()
        self.conn.execute("DELETE FROM embeddings WHERE node_id = ?", [embedding.node_id])
        self.conn.execute(
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
            embeddings: List of NodeEmbedding objects to store
        """
        if not embeddings:
            return

        self._ensure_embeddings_schema()

        # Delete existing embeddings for these nodes
        node_ids = [e.node_id for e in embeddings]
        placeholders = ", ".join(["?"] * len(node_ids))
        self.conn.execute(
            f"DELETE FROM embeddings WHERE node_id IN ({placeholders})",
            node_ids,
        )

        # Insert all embeddings
        for embedding in embeddings:
            self.conn.execute(
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
            node_id: The node ID

        Returns:
            NodeEmbedding if found, None otherwise
        """
        from mu.kernel.embeddings.models import NodeEmbedding

        self._ensure_embeddings_schema()
        row = self.conn.execute(
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
            query_embedding: The query embedding vector
            embedding_type: Which embedding to search ('code', 'docstring', 'name')
            limit: Maximum number of results
            node_type: Optional filter by node type

        Returns:
            List of (Node, similarity_score) tuples, sorted by similarity descending
        """
        self._ensure_embeddings_schema()

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
        # cosine_similarity = dot(a, b) / (norm(a) * norm(b))
        rows = self.conn.execute(
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

    def embedding_stats(self) -> dict[str, Any]:
        """Get embedding statistics.

        Returns:
            Dictionary with embedding coverage and model info.
            Returns empty stats if embeddings table doesn't exist.
        """
        try:
            self._ensure_embeddings_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            node_result = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
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
        node_result = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
        total_nodes = node_result[0] if node_result else 0

        # Nodes with embeddings
        embed_result = self.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
        nodes_with_embeddings = embed_result[0] if embed_result else 0

        # Nodes without embeddings
        nodes_without = total_nodes - nodes_with_embeddings

        # Coverage by node type
        coverage_by_type: dict[str, dict[str, int]] = {}
        type_rows = self.conn.execute(
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
        model_rows = self.conn.execute(
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
        dim_result = self.conn.execute("SELECT DISTINCT dimensions FROM embeddings").fetchall()
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

    # =========================================================================
    # Smart Context Methods
    # =========================================================================

    def get_context_for_question(
        self,
        question: str,
        max_tokens: int = 8000,
        **kwargs: Any,
    ) -> Any:
        """Extract optimal context for answering a question.

        Uses smart context extraction to identify the most relevant code
        entities for a given natural language question, fitting within
        a token budget.

        Args:
            question: Natural language question about the code.
            max_tokens: Maximum tokens in output (default: 8000).
            **kwargs: Additional ExtractionConfig options:
                - include_imports: bool (default: True)
                - include_parent: bool (default: True)
                - expand_depth: int (default: 1)
                - entity_weight: float (default: 1.0)
                - vector_weight: float (default: 0.7)
                - proximity_weight: float (default: 0.3)
                - min_relevance: float (default: 0.1)
                - exclude_tests: bool (default: False)

        Returns:
            ContextResult with MU format context, selected nodes,
            token count, relevance scores, and extraction stats.

        Example:
            >>> db = MUbase(".mubase")
            >>> result = db.get_context_for_question(
            ...     "How does authentication work?",
            ...     max_tokens=4000,
            ...     exclude_tests=True,
            ... )
            >>> print(result.mu_text)
            >>> print(f"Tokens: {result.token_count}")
        """
        from mu.kernel.context import ExtractionConfig, SmartContextExtractor

        config = ExtractionConfig(max_tokens=max_tokens, **kwargs)
        extractor = SmartContextExtractor(self, config)
        return extractor.extract(question)

    def has_embeddings(self) -> bool:
        """Check if the database has any embeddings.

        Returns:
            True if embeddings exist, False otherwise.
        """
        try:
            self._ensure_embeddings_schema()
            result = self.conn.execute("SELECT COUNT(*) FROM embeddings LIMIT 1").fetchone()
            return result is not None and result[0] > 0
        except Exception:
            return False

    def find_nodes_by_suffix(
        self,
        suffix: str,
        node_type: NodeType | None = None,
    ) -> list[Node]:
        """Find nodes whose name ends with the given suffix.

        Useful for fuzzy matching when the full qualified name is not known.

        Args:
            suffix: The suffix to match (e.g., "Service", "login")
            node_type: Optional filter by node type

        Returns:
            List of matching nodes
        """
        return self.find_by_name(f"%{suffix}", node_type)

    def get_neighbors(
        self,
        node_id: str,
        direction: str = "both",
    ) -> list[Node]:
        """Get neighboring nodes in the graph.

        Args:
            node_id: The node to find neighbors for
            direction: "outgoing" (dependencies), "incoming" (dependents),
                      or "both" (default)

        Returns:
            List of neighboring nodes
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
    # Pattern Storage Methods
    # =========================================================================

    def _ensure_patterns_schema(self) -> None:
        """Create patterns table if it doesn't exist.

        In read-only mode, just checks if table exists without creating.
        """
        from mu.kernel.schema import PATTERNS_SCHEMA_SQL

        try:
            self.conn.execute("SELECT 1 FROM patterns LIMIT 1")
        except duckdb.CatalogException:
            if self.read_only:
                # In read-only mode, we can't create the table
                # Just let the caller handle the missing table
                raise
            self.conn.execute(PATTERNS_SCHEMA_SQL)

    def save_patterns(self, patterns: list[Any]) -> None:
        """Save patterns to the database.

        Args:
            patterns: List of Pattern objects to save.
        """
        from datetime import datetime

        self._ensure_patterns_schema()

        # Clear existing patterns
        self.conn.execute("DELETE FROM patterns")

        now = datetime.now(UTC).isoformat()
        for pattern in patterns:
            import json

            self.conn.execute(
                """
                INSERT INTO patterns
                (id, category, name, description, frequency, confidence,
                 examples, anti_patterns, related_patterns, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    f"pat:{pattern.category.value}:{pattern.name}",
                    pattern.category.value,
                    pattern.name,
                    pattern.description,
                    pattern.frequency,
                    pattern.confidence,
                    json.dumps([e.to_dict() for e in pattern.examples]),
                    json.dumps(pattern.anti_patterns),
                    json.dumps(getattr(pattern, "related_patterns", [])),
                    now,
                    now,
                ],
            )

    def get_patterns(self, category: str | None = None) -> list[Any]:
        """Get stored patterns.

        Args:
            category: Optional category filter.

        Returns:
            List of Pattern objects.
        """
        import json

        from mu.intelligence.models import Pattern, PatternCategory, PatternExample

        self._ensure_patterns_schema()

        if category:
            rows = self.conn.execute(
                "SELECT * FROM patterns WHERE category = ? ORDER BY frequency DESC",
                [category],
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM patterns ORDER BY frequency DESC").fetchall()

        patterns = []
        for row in rows:
            # row: id, category, name, description, frequency, confidence,
            #      examples, anti_patterns, related_patterns, created_at, updated_at
            examples_data = json.loads(row[6]) if row[6] else []
            examples = [
                PatternExample(
                    file_path=e.get("file_path", ""),
                    line_start=e.get("line_start", 0),
                    line_end=e.get("line_end", 0),
                    code_snippet=e.get("code_snippet", ""),
                    annotation=e.get("annotation", ""),
                )
                for e in examples_data
            ]
            patterns.append(
                Pattern(
                    name=row[2],
                    category=PatternCategory(row[1]),
                    description=row[3] or "",
                    frequency=row[4] or 0,
                    confidence=row[5] or 0.0,
                    examples=examples,
                    anti_patterns=json.loads(row[7]) if row[7] else [],
                    related_patterns=json.loads(row[8]) if row[8] else [],
                )
            )
        return patterns

    def has_patterns(self) -> bool:
        """Check if patterns are stored in the database.

        Returns:
            True if patterns exist, False otherwise.
        """
        try:
            self._ensure_patterns_schema()
            result = self.conn.execute("SELECT COUNT(*) FROM patterns").fetchone()
            return result is not None and result[0] > 0
        except Exception:
            return False

    def patterns_stats(self) -> dict[str, Any]:
        """Get pattern statistics.

        Returns:
            Dictionary with pattern counts and categories.
            Returns empty stats if patterns table doesn't exist.
        """
        try:
            self._ensure_patterns_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            return {
                "total_patterns": 0,
                "patterns_by_category": {},
            }

        result = self.conn.execute("SELECT COUNT(*) FROM patterns").fetchone()
        total = result[0] if result else 0

        by_category: dict[str, int] = {}
        rows = self.conn.execute(
            "SELECT category, COUNT(*) FROM patterns GROUP BY category"
        ).fetchall()
        for row in rows:
            by_category[row[0]] = row[1]

        return {
            "total_patterns": total,
            "patterns_by_category": by_category,
        }

    # =========================================================================
    # Memory Storage Methods (Cross-Session Learnings)
    # =========================================================================

    def _ensure_memory_schema(self) -> None:
        """Create memory table if it doesn't exist.

        In read-only mode, just checks if table exists without creating.
        """
        from mu.kernel.schema import MEMORY_SCHEMA_SQL

        try:
            self.conn.execute("SELECT 1 FROM memories LIMIT 1")
        except duckdb.CatalogException:
            if self.read_only:
                # In read-only mode, we can't create the table
                # Just let the caller handle the missing table
                raise
            self.conn.execute(MEMORY_SCHEMA_SQL)

    def save_memory(
        self,
        content: str,
        category: str,
        context: str = "",
        source: str = "",
        confidence: float = 1.0,
        importance: int = 1,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        """Save a memory to the database.

        Args:
            content: The memory content.
            category: Memory category (preference, decision, context, etc.).
            context: Optional additional context.
            source: Where this memory came from.
            confidence: Confidence level (0.0 - 1.0).
            importance: Importance level (1-5).
            tags: Optional list of tags.
            embedding: Optional vector embedding.

        Returns:
            The memory ID.
        """
        import hashlib
        import json
        from datetime import datetime

        self._ensure_memory_schema()

        # Generate ID from content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        memory_id = f"mem:{category}:{content_hash}"

        now = datetime.now(UTC).isoformat()

        # Check if memory already exists (update if so)
        existing = self.conn.execute(
            "SELECT id, access_count FROM memories WHERE id = ?", [memory_id]
        ).fetchone()

        if existing:
            # Update existing memory
            self.conn.execute(
                """
                UPDATE memories SET
                    content = ?, context = ?, source = ?,
                    confidence = ?, importance = ?, tags = ?,
                    embedding = ?, updated_at = ?
                WHERE id = ?
                """,
                [
                    content,
                    context,
                    source,
                    confidence,
                    importance,
                    json.dumps(tags or []),
                    embedding,
                    now,
                    memory_id,
                ],
            )
        else:
            # Insert new memory
            self.conn.execute(
                """
                INSERT INTO memories
                (id, category, content, context, source, confidence,
                 importance, tags, embedding, created_at, updated_at,
                 accessed_at, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)
                """,
                [
                    memory_id,
                    category,
                    content,
                    context,
                    source,
                    confidence,
                    importance,
                    json.dumps(tags or []),
                    embedding,
                    now,
                    now,
                ],
            )

        return memory_id

    def get_memory(self, memory_id: str) -> Any | None:
        """Get a memory by ID.

        Args:
            memory_id: The memory ID.

        Returns:
            Memory object if found, None otherwise.
        """
        import json
        from datetime import datetime

        from mu.intelligence.models import Memory, MemoryCategory

        self._ensure_memory_schema()

        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", [memory_id]).fetchone()

        if not row:
            return None

        # Update access tracking
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
            [now, memory_id],
        )

        # row: id, category, content, context, source, confidence,
        #      importance, tags, embedding, created_at, updated_at,
        #      accessed_at, access_count
        # Note: Return incremented access_count (row[12] + 1) since we just updated it
        return Memory(
            id=row[0],
            category=MemoryCategory(row[1]),
            content=row[2],
            context=row[3] or "",
            source=row[4] or "",
            confidence=row[5] or 1.0,
            importance=row[6] or 1,
            tags=json.loads(row[7]) if row[7] else [],
            embedding=row[8],
            created_at=row[9] or "",
            updated_at=row[10] or "",
            accessed_at=now,  # Use the current timestamp we just set
            access_count=(row[12] or 0) + 1,  # Reflect the increment
        )

    def recall_memories(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: int = 0,
        limit: int = 10,
    ) -> list[Any]:
        """Recall memories based on search criteria.

        Args:
            query: Optional text search in content/context.
            category: Optional category filter.
            tags: Optional tags filter (any match).
            min_importance: Minimum importance level.
            limit: Maximum number of results.

        Returns:
            List of Memory objects.
        """
        import json
        from datetime import datetime

        from mu.intelligence.models import Memory, MemoryCategory

        self._ensure_memory_schema()

        conditions: list[str] = []
        params: list[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if min_importance > 0:
            conditions.append("importance >= ?")
            params.append(min_importance)

        if query:
            conditions.append("(content LIKE ? OR context LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])

        if tags:
            # Check if any tag matches
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
            conditions.append(f"({' OR '.join(tag_conditions)})")

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""
            SELECT * FROM memories
            WHERE {where_clause}
            ORDER BY importance DESC, access_count DESC, updated_at DESC
            LIMIT ?
        """
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()

        # Update access tracking for retrieved memories (skip in read-only mode)
        if not self.read_only:
            now = datetime.now(UTC).isoformat()
            memory_ids = [row[0] for row in rows]
            if memory_ids:
                placeholders = ", ".join(["?"] * len(memory_ids))
                self.conn.execute(
                    f"UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id IN ({placeholders})",
                    [now, *memory_ids],
                )

        memories = []
        for row in rows:
            memories.append(
                Memory(
                    id=row[0],
                    category=MemoryCategory(row[1]),
                    content=row[2],
                    context=row[3] or "",
                    source=row[4] or "",
                    confidence=row[5] or 1.0,
                    importance=row[6] or 1,
                    tags=json.loads(row[7]) if row[7] else [],
                    embedding=row[8],
                    created_at=row[9] or "",
                    updated_at=row[10] or "",
                    accessed_at=row[11],
                    access_count=row[12] or 0,
                )
            )

        return memories

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory.

        Args:
            memory_id: The memory ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        self._ensure_memory_schema()
        self.conn.execute("DELETE FROM memories WHERE id = ?", [memory_id])
        return True

    def memory_stats(self) -> dict[str, Any]:
        """Get memory statistics.

        Returns:
            Dictionary with memory counts and categories.
            Returns empty stats if memories table doesn't exist.
        """
        try:
            self._ensure_memory_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            return {
                "total_memories": 0,
                "memories_by_category": {},
            }

        result = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        total = result[0] if result else 0

        by_category: dict[str, int] = {}
        rows = self.conn.execute(
            "SELECT category, COUNT(*) FROM memories GROUP BY category"
        ).fetchall()
        for row in rows:
            by_category[row[0]] = row[1]

        return {
            "total_memories": total,
            "memories_by_category": by_category,
        }

    def has_memories(self) -> bool:
        """Check if any memories exist.

        Returns:
            True if memories exist, False otherwise.
        """
        try:
            self._ensure_memory_schema()
            result = self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()
            return result is not None and result[0] > 0
        except Exception:
            return False

    # =========================================================================
    # Incremental Update Methods (for daemon mode)
    # =========================================================================

    def get_nodes_by_file(self, file_path: str) -> list[Node]:
        """Get all nodes from a specific file.

        Args:
            file_path: The file path to match

        Returns:
            List of nodes from the specified file
        """
        return self.get_nodes(file_path=file_path)

    def remove_nodes_by_file(self, file_path: str) -> list[str]:
        """Remove all nodes from a file and their edges.

        Args:
            file_path: The file path whose nodes should be removed

        Returns:
            List of removed node IDs
        """
        nodes = self.get_nodes_by_file(file_path)
        removed_ids = [n.id for n in nodes]

        if not removed_ids:
            return []

        # Remove edges first (to avoid foreign key issues if constraints exist)
        placeholders = ", ".join(["?"] * len(removed_ids))
        self.conn.execute(
            f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
            removed_ids + removed_ids,
        )

        # Remove nodes
        self.conn.execute(
            f"DELETE FROM nodes WHERE id IN ({placeholders})",
            removed_ids,
        )

        return removed_ids

    def update_node(self, node: Node) -> None:
        """Update an existing node (upsert pattern).

        Uses the existing add_node which implements INSERT OR REPLACE.

        Args:
            node: The node to update
        """
        self.add_node(node)

    def remove_node(self, node_id: str) -> bool:
        """Remove a single node and its edges.

        Args:
            node_id: The ID of the node to remove

        Returns:
            True if the node was removed, False if it didn't exist
        """
        # Check if node exists
        node = self.get_node(node_id)
        if node is None:
            return False

        # Remove edges first
        self.conn.execute(
            "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
            [node_id, node_id],
        )

        # Remove node
        self.conn.execute("DELETE FROM nodes WHERE id = ?", [node_id])
        return True

    def remove_edge(self, edge_id: str) -> bool:
        """Remove a single edge.

        Args:
            edge_id: The ID of the edge to remove

        Returns:
            True if the edge was removed, False if it didn't exist
        """
        result = self.conn.execute("DELETE FROM edges WHERE id = ?", [edge_id])
        return result.rowcount > 0 if hasattr(result, "rowcount") else True

    # =========================================================================
    # Codebase Statistics Methods
    # =========================================================================

    def _ensure_codebase_stats_schema(self) -> None:
        """Create codebase_stats table if it doesn't exist.

        In read-only mode, just checks if table exists without creating.
        """
        from mu.kernel.schema import CODEBASE_STATS_SCHEMA_SQL

        try:
            self.conn.execute("SELECT 1 FROM codebase_stats LIMIT 1")
        except duckdb.CatalogException:
            if self.read_only:
                # In read-only mode, we can't create the table
                # Just let the caller handle the missing table
                raise
            self.conn.execute(CODEBASE_STATS_SCHEMA_SQL)

    def _compute_and_store_language_stats(self, modules: list[ModuleDef]) -> None:
        """Compute language statistics from modules and store in database.

        Args:
            modules: List of parsed ModuleDef objects.
        """
        import json
        from collections import Counter
        from datetime import datetime

        # Count files by language
        languages: Counter[str] = Counter()
        ext_map = {
            ".py": "Python",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".cs": "C#",
            ".rb": "Ruby",
            ".php": "PHP",
            ".swift": "Swift",
            ".kt": "Kotlin",
            ".scala": "Scala",
            ".cpp": "C++",
            ".c": "C",
            ".h": "C/C++ Header",
            ".hpp": "C++ Header",
        }

        for module in modules:
            # Get extension from file path
            if module.path:
                ext = "." + module.path.rsplit(".", 1)[-1] if "." in module.path else ""
                lang = ext_map.get(ext.lower())
                if lang:
                    languages[lang] += 1

        # Calculate percentages
        total = sum(languages.values())
        percentages: dict[str, float] = {}
        if total > 0:
            for lang, count in languages.items():
                percentages[lang] = round(count / total * 100, 2)

        # Determine primary language
        primary_language = languages.most_common(1)[0][0] if languages else None

        # Store in database
        self._ensure_codebase_stats_schema()
        now = datetime.now(UTC).isoformat()

        stats_data = {
            "languages": dict(languages),
            "percentages": percentages,
            "primary_language": primary_language,
            "total_files": total,
        }

        # Delete existing and insert new
        self.conn.execute("DELETE FROM codebase_stats WHERE key = 'languages'")
        self.conn.execute(
            "INSERT INTO codebase_stats (key, value, updated_at) VALUES (?, ?, ?)",
            ["languages", json.dumps(stats_data), now],
        )

    def get_language_stats(self) -> dict[str, Any]:
        """Get stored language statistics.

        Returns:
            Dictionary with language distribution:
            {
                "languages": {"Python": 100, "C#": 784, ...},
                "percentages": {"Python": 11.3, "C#": 88.7, ...},
                "primary_language": "C#",
                "total_files": 884
            }
            Returns empty stats if codebase_stats table doesn't exist.
        """
        import json

        try:
            self._ensure_codebase_stats_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            return {
                "languages": {},
                "percentages": {},
                "primary_language": None,
                "total_files": 0,
            }

        row = self.conn.execute(
            "SELECT value FROM codebase_stats WHERE key = 'languages'"
        ).fetchone()

        if row:
            result: dict[str, Any] = json.loads(row[0])
            return result

        return {
            "languages": {},
            "percentages": {},
            "primary_language": None,
            "total_files": 0,
        }

    def set_codebase_stat(self, key: str, value: Any) -> None:
        """Store a codebase statistic.

        Args:
            key: Statistic key.
            value: Value (must be JSON-serializable).
        """
        import json
        from datetime import datetime

        self._ensure_codebase_stats_schema()
        now = datetime.now(UTC).isoformat()

        self.conn.execute("DELETE FROM codebase_stats WHERE key = ?", [key])
        self.conn.execute(
            "INSERT INTO codebase_stats (key, value, updated_at) VALUES (?, ?, ?)",
            [key, json.dumps(value), now],
        )

    def get_codebase_stat(self, key: str) -> Any | None:
        """Get a stored codebase statistic.

        Args:
            key: Statistic key.

        Returns:
            The stored value, or None if not found.
        """
        import json

        try:
            self._ensure_codebase_stats_schema()
        except duckdb.CatalogException:
            # Table doesn't exist (possibly in read-only mode)
            return None

        row = self.conn.execute("SELECT value FROM codebase_stats WHERE key = ?", [key]).fetchone()

        return json.loads(row[0]) if row else None

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
    "MUbaseCorruptionError",
    "MUbaseLockError",
]
