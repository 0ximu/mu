"""MU Kernel database schema definitions.

Defines node types, edge types, and the DuckDB schema for storing
the codebase as a graph.
"""

from __future__ import annotations

from enum import Enum


class NodeType(Enum):
    """Types of nodes in the code graph."""

    MODULE = "module"  # File/module level
    CLASS = "class"  # Class/struct/interface
    FUNCTION = "function"  # Function/method
    EXTERNAL = "external"  # External dependency (package)


class EdgeType(Enum):
    """Types of relationships between nodes."""

    # Structural
    CONTAINS = "contains"  # Module→Class, Class→Function, Module→Function
    IMPORTS = "imports"  # Module→Module (internal dependencies)
    INHERITS = "inherits"  # Class→Class (inheritance)

    # Future: CALLS, USES, MUTATES, IMPLEMENTS, ANNOTATED_WITH


# DuckDB schema for the .mubase file
SCHEMA_SQL = """
-- Node types enum (for documentation, DuckDB uses VARCHAR)
-- MODULE, CLASS, FUNCTION, EXTERNAL

-- Edge types enum
-- CONTAINS, IMPORTS, INHERITS

-- Nodes table: all code entities
CREATE TABLE IF NOT EXISTS nodes (
    id VARCHAR PRIMARY KEY,
    type VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    qualified_name VARCHAR,
    file_path VARCHAR,
    line_start INTEGER,
    line_end INTEGER,
    properties JSON,
    complexity INTEGER DEFAULT 0
);

-- Edges table: relationships between nodes
CREATE TABLE IF NOT EXISTS edges (
    id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    target_id VARCHAR NOT NULL,
    type VARCHAR NOT NULL,
    properties JSON
);

-- Metadata table: version, build info
CREATE TABLE IF NOT EXISTS metadata (
    key VARCHAR PRIMARY KEY,
    value VARCHAR
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_complexity ON nodes(complexity);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
"""

# Embeddings table schema - separate to allow optional loading
EMBEDDINGS_SCHEMA_SQL = """
-- Embeddings table: vector embeddings for nodes
CREATE TABLE IF NOT EXISTS embeddings (
    node_id VARCHAR PRIMARY KEY,
    code_embedding FLOAT[],
    docstring_embedding FLOAT[],
    name_embedding FLOAT[],
    model_name VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at VARCHAR NOT NULL
);

-- Index for efficient joins with nodes table
CREATE INDEX IF NOT EXISTS idx_embeddings_node_id ON embeddings(node_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model_name, model_version);
"""


__all__ = [
    "NodeType",
    "EdgeType",
    "SCHEMA_SQL",
    "EMBEDDINGS_SCHEMA_SQL",
]
