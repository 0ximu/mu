"""MU Kernel - Graph-based code analysis storage.

The kernel provides a queryable graph database (.mubase) for storing
and analyzing codebase structure, including vector embeddings for
semantic search.

Example:
    >>> from mu.kernel import MUbase, NodeType, EdgeType
    >>> from mu.parser.base import parse_file
    >>>
    >>> # Build graph from parsed modules
    >>> db = MUbase(".mubase")
    >>> db.build(modules, root_path)
    >>>
    >>> # Query the graph
    >>> functions = db.get_nodes(NodeType.FUNCTION)
    >>> complex_funcs = db.find_by_complexity(min_complexity=20)
    >>> deps = db.get_dependencies("mod:src/cli.py", depth=2)
    >>>
    >>> # Semantic search (after embedding)
    >>> from mu.kernel.embeddings import EmbeddingService
    >>> service = EmbeddingService()
    >>> results = db.vector_search(query_embedding, limit=10)
    >>>
    >>> db.close()
"""

from mu.kernel.builder import GraphBuilder

# Re-export key embeddings classes for convenience
from mu.kernel.embeddings import (
    EmbeddingService,
    EmbeddingStats,
    NodeEmbedding,
)
from mu.kernel.models import Edge, Node
from mu.kernel.mubase import MUbase
from mu.kernel.schema import EMBEDDINGS_SCHEMA_SQL, SCHEMA_SQL, EdgeType, NodeType

__all__ = [
    # Main class
    "MUbase",
    # Models
    "Node",
    "Edge",
    # Enums
    "NodeType",
    "EdgeType",
    # Builder
    "GraphBuilder",
    # Schema
    "SCHEMA_SQL",
    "EMBEDDINGS_SCHEMA_SQL",
    # Embeddings (convenience re-exports)
    "EmbeddingService",
    "NodeEmbedding",
    "EmbeddingStats",
]
