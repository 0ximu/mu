"""MUbase - Graph database for code analysis.

DuckDB-based storage for the codebase graph with support for
recursive dependency queries.

This module provides the main MUbase class which acts as a facade
over specialized store modules:
- queries.py: Graph traversal and search operations
- embeddings_store.py: Vector embeddings storage and similarity search
- patterns_store.py: Codebase pattern storage
- memory_store.py: Cross-session learning storage
- stats_store.py: Codebase statistics
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from mu.kernel.builder import GraphBuilder
from mu.kernel.embeddings_store import EmbeddingsStore
from mu.kernel.memory_store import MemoryStore
from mu.kernel.models import Edge, Node
from mu.kernel.patterns_store import PatternsStore
from mu.kernel.queries import GraphQueries
from mu.kernel.schema import (
    PATTERNS_SCHEMA_SQL,
    SCHEMA_SQL,
    TEMPORAL_SCHEMA_SQL,
    EdgeType,
    NodeType,
)
from mu.kernel.stats_store import StatsStore
from mu.paths import MUBASE_FILE, get_mu_dir

if TYPE_CHECKING:
    from mu.extras.embeddings.models import NodeEmbedding
    from mu.extras.intelligence.models import Memory, Pattern
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

    This class acts as a facade over specialized store modules,
    providing a unified API for all database operations.
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

        # Initialize specialized stores (delegation pattern)
        self._queries = GraphQueries(self.conn)
        self._embeddings = EmbeddingsStore(self.conn, read_only)
        self._patterns = PatternsStore(self.conn, read_only)
        self._memory = MemoryStore(self.conn, read_only)
        self._stats = StatsStore(self.conn, read_only)

    # =========================================================================
    # Schema Management
    # =========================================================================

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
        self.conn.execute(TEMPORAL_SCHEMA_SQL)
        self.conn.execute(PATTERNS_SCHEMA_SQL)
        self.conn.execute(
            "INSERT INTO metadata VALUES ('version', ?)",
            [self.VERSION],
        )
        self.conn.execute(
            "INSERT INTO metadata VALUES ('created_at', CURRENT_TIMESTAMP)",
        )

    def _migrate(self, from_version: str) -> None:
        """Migrate schema from older version."""
        self.conn.execute("DROP TABLE IF EXISTS edges")
        self.conn.execute("DROP TABLE IF EXISTS nodes")
        self.conn.execute("DROP TABLE IF EXISTS metadata")
        self._create_schema()

    # =========================================================================
    # Build Operations
    # =========================================================================

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

        # Insert nodes and edges
        for node in nodes:
            self.add_node(node)
        for edge in edges:
            self.add_edge(edge)

        # Compute and store language statistics
        self._stats.compute_and_store_language_stats(modules)

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
        self.conn.execute("DELETE FROM edges WHERE id = ?", [edge.id])
        self.conn.execute(
            """
            INSERT INTO edges
            (id, source_id, target_id, type, properties)
            VALUES (?, ?, ?, ?, ?)
            """,
            edge.to_tuple(),
        )

    # =========================================================================
    # Query Operations (delegated to GraphQueries)
    # =========================================================================

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID."""
        return self._queries.get_node(node_id)

    def get_nodes(
        self,
        node_type: NodeType | None = None,
        file_path: str | None = None,
    ) -> list[Node]:
        """Get nodes with optional filtering."""
        return self._queries.get_nodes(node_type, file_path)

    def get_edges(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        edge_type: EdgeType | None = None,
    ) -> list[Edge]:
        """Get edges with optional filtering."""
        return self._queries.get_edges(source_id, target_id, edge_type)

    def get_dependencies(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Node]:
        """Get nodes that this node depends on (outgoing edges)."""
        return self._queries.get_dependencies(node_id, depth, edge_types)

    def get_dependents(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Node]:
        """Get nodes that depend on this node (incoming edges)."""
        return self._queries.get_dependents(node_id, depth, edge_types)

    def get_children(self, node_id: str) -> list[Node]:
        """Get nodes contained by this node (CONTAINS edges)."""
        return self._queries.get_children(node_id)

    def get_parent(self, node_id: str) -> Node | None:
        """Get the node that contains this node."""
        return self._queries.get_parent(node_id)

    def get_neighbors(self, node_id: str, direction: str = "both") -> list[Node]:
        """Get neighboring nodes in the graph."""
        return self._queries.get_neighbors(node_id, direction)

    def find_by_name(self, name: str, node_type: NodeType | None = None) -> list[Node]:
        """Find nodes by name (exact or pattern match)."""
        return self._queries.find_by_name(name, node_type)

    def find_nodes_by_suffix(
        self,
        suffix: str,
        node_type: NodeType | None = None,
    ) -> list[Node]:
        """Find nodes whose name ends with the given suffix."""
        return self._queries.find_nodes_by_suffix(suffix, node_type)

    def find_by_complexity(
        self,
        min_complexity: int,
        max_complexity: int | None = None,
    ) -> list[Node]:
        """Find nodes with complexity in range."""
        return self._queries.find_by_complexity(min_complexity, max_complexity)

    def find_path(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 10,
    ) -> list[str] | None:
        """Find shortest path between two nodes."""
        return self._queries.find_path(from_id, to_id, max_depth)

    # =========================================================================
    # Statistics
    # =========================================================================

    def stats(self) -> dict[str, Any]:
        """Get database statistics."""
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
        """Execute raw SQL query."""
        if params:
            return self.conn.execute(sql, params).fetchall()
        return self.conn.execute(sql).fetchall()

    # =========================================================================
    # Embeddings Operations (delegated to EmbeddingsStore)
    # =========================================================================

    def _ensure_embeddings_schema(self) -> None:
        """Create embeddings table if it doesn't exist."""
        self._embeddings._ensure_schema()

    def add_embedding(self, embedding: NodeEmbedding) -> None:
        """Add or update an embedding for a node."""
        self._embeddings.add_embedding(embedding)

    def add_embeddings_batch(self, embeddings: list[NodeEmbedding]) -> None:
        """Add multiple embeddings in a batch."""
        self._embeddings.add_embeddings_batch(embeddings)

    def get_embedding(self, node_id: str) -> NodeEmbedding | None:
        """Get embedding for a node."""
        return self._embeddings.get_embedding(node_id)

    def vector_search(
        self,
        query_embedding: list[float],
        embedding_type: str = "code",
        limit: int = 10,
        node_type: NodeType | None = None,
    ) -> list[tuple[Node, float]]:
        """Find similar nodes by cosine similarity."""
        return self._embeddings.vector_search(query_embedding, embedding_type, limit, node_type)

    def has_embeddings(self) -> bool:
        """Check if the database has any embeddings."""
        return self._embeddings.has_embeddings()

    def embedding_stats(self) -> dict[str, Any]:
        """Get embedding statistics."""
        return self._embeddings.stats()

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
            **kwargs: Additional ExtractionConfig options.

        Returns:
            ContextResult with MU format context, selected nodes,
            token count, relevance scores, and extraction stats.
        """
        from mu.kernel.context import ExtractionConfig, SmartContextExtractor

        config = ExtractionConfig(max_tokens=max_tokens, **kwargs)
        extractor = SmartContextExtractor(self, config)
        return extractor.extract(question)

    # =========================================================================
    # Pattern Storage (delegated to PatternsStore)
    # =========================================================================

    def _ensure_patterns_schema(self) -> None:
        """Create patterns table if it doesn't exist."""
        self._patterns._ensure_schema()

    def save_patterns(self, patterns: list[Pattern]) -> None:
        """Save patterns to the database."""
        self._patterns.save_patterns(patterns)

    def get_patterns(self, category: str | None = None) -> list[Pattern]:
        """Get stored patterns."""
        return self._patterns.get_patterns(category)

    def has_patterns(self) -> bool:
        """Check if patterns are stored in the database."""
        return self._patterns.has_patterns()

    def patterns_stats(self) -> dict[str, Any]:
        """Get pattern statistics."""
        return self._patterns.stats()

    # =========================================================================
    # Memory Storage (delegated to MemoryStore)
    # =========================================================================

    def _ensure_memory_schema(self) -> None:
        """Create memory table if it doesn't exist."""
        self._memory._ensure_schema()

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
        """Save a memory to the database."""
        return self._memory.save_memory(
            content, category, context, source, confidence, importance, tags, embedding
        )

    def get_memory(self, memory_id: str) -> Memory | None:
        """Get a memory by ID."""
        return self._memory.get_memory(memory_id)

    def recall_memories(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: int = 0,
        limit: int = 10,
    ) -> list[Memory]:
        """Recall memories based on search criteria."""
        return self._memory.recall_memories(query, category, tags, min_importance, limit)

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory."""
        return self._memory.delete_memory(memory_id)

    def memory_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        return self._memory.stats()

    def has_memories(self) -> bool:
        """Check if any memories exist."""
        return self._memory.has_memories()

    # =========================================================================
    # Incremental Update Methods (for daemon mode)
    # =========================================================================

    def get_nodes_by_file(self, file_path: str) -> list[Node]:
        """Get all nodes from a specific file."""
        return self.get_nodes(file_path=file_path)

    def remove_nodes_by_file(self, file_path: str) -> list[str]:
        """Remove all nodes from a file and their edges."""
        nodes = self.get_nodes_by_file(file_path)
        removed_ids = [n.id for n in nodes]

        if not removed_ids:
            return []

        placeholders = ", ".join(["?"] * len(removed_ids))
        self.conn.execute(
            f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
            removed_ids + removed_ids,
        )
        self.conn.execute(
            f"DELETE FROM nodes WHERE id IN ({placeholders})",
            removed_ids,
        )

        return removed_ids

    def update_node(self, node: Node) -> None:
        """Update an existing node (upsert pattern)."""
        self.add_node(node)

    def remove_node(self, node_id: str) -> bool:
        """Remove a single node and its edges."""
        node = self.get_node(node_id)
        if node is None:
            return False

        self.conn.execute(
            "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
            [node_id, node_id],
        )
        self.conn.execute("DELETE FROM nodes WHERE id = ?", [node_id])
        return True

    def remove_edge(self, edge_id: str) -> bool:
        """Remove a single edge."""
        result = self.conn.execute("DELETE FROM edges WHERE id = ?", [edge_id])
        return result.rowcount > 0 if hasattr(result, "rowcount") else True

    # =========================================================================
    # Codebase Statistics (delegated to StatsStore)
    # =========================================================================

    def _ensure_codebase_stats_schema(self) -> None:
        """Create codebase_stats table if it doesn't exist."""
        self._stats._ensure_schema()

    def _compute_and_store_language_stats(self, modules: list[ModuleDef]) -> None:
        """Compute language statistics from modules and store in database."""
        self._stats.compute_and_store_language_stats(modules)

    def get_language_stats(self) -> dict[str, Any]:
        """Get stored language statistics."""
        return self._stats.get_language_stats()

    def set_codebase_stat(self, key: str, value: Any) -> None:
        """Store a codebase statistic."""
        self._stats.set_stat(key, value)

    def get_codebase_stat(self, key: str) -> Any | None:
        """Get a stored codebase statistic."""
        return self._stats.get_stat(key)

    # =========================================================================
    # Connection Management
    # =========================================================================

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
