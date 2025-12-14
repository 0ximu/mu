"""MU Kernel database schema definitions.

Defines node types, edge types, and the DuckDB schema for storing
the codebase as a graph.
"""

from __future__ import annotations

from enum import Enum


class ChangeType(Enum):
    """Type of change in temporal history."""

    ADDED = "added"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    REMOVED = "removed"


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
    CALLS = "calls"  # Function→Function (call graph)
    USES = "uses"  # Class→Class (type reference, instantiation)

    # Future: MUTATES, IMPLEMENTS, ANNOTATED_WITH


# DuckDB schema for the .mubase file
SCHEMA_SQL = """
-- Node types enum (for documentation, DuckDB uses VARCHAR)
-- MODULE, CLASS, FUNCTION, EXTERNAL

-- Edge types enum
-- CONTAINS, IMPORTS, INHERITS, CALLS, USES

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

# Temporal schema - separate to allow lazy loading
TEMPORAL_SCHEMA_SQL = """
-- Snapshots table: point-in-time captures of the graph state
CREATE TABLE IF NOT EXISTS snapshots (
    id VARCHAR PRIMARY KEY,
    commit_hash VARCHAR NOT NULL UNIQUE,
    commit_message VARCHAR,
    commit_author VARCHAR,
    commit_date VARCHAR,
    parent_id VARCHAR,
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    nodes_added INTEGER DEFAULT 0,
    nodes_removed INTEGER DEFAULT 0,
    nodes_modified INTEGER DEFAULT 0,
    edges_added INTEGER DEFAULT 0,
    edges_removed INTEGER DEFAULT 0,
    created_at VARCHAR NOT NULL
);

-- Node history table: track changes to nodes across snapshots
CREATE TABLE IF NOT EXISTS node_history (
    id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL,
    node_id VARCHAR NOT NULL,
    change_type VARCHAR NOT NULL,
    body_hash VARCHAR,
    properties JSON,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

-- Edge history table: track changes to edges across snapshots
CREATE TABLE IF NOT EXISTS edge_history (
    id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL,
    edge_id VARCHAR NOT NULL,
    change_type VARCHAR NOT NULL,
    source_id VARCHAR NOT NULL,
    target_id VARCHAR NOT NULL,
    edge_type VARCHAR NOT NULL,
    properties JSON,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

-- Indexes for temporal queries
CREATE INDEX IF NOT EXISTS idx_snapshots_commit ON snapshots(commit_hash);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(commit_date);
CREATE INDEX IF NOT EXISTS idx_snapshots_parent ON snapshots(parent_id);
CREATE INDEX IF NOT EXISTS idx_node_history_snapshot ON node_history(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_node_history_node ON node_history(node_id);
CREATE INDEX IF NOT EXISTS idx_node_history_change ON node_history(change_type);
CREATE INDEX IF NOT EXISTS idx_edge_history_snapshot ON edge_history(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_edge_history_edge ON edge_history(edge_id);
CREATE INDEX IF NOT EXISTS idx_edge_history_change ON edge_history(change_type);
"""


# Memory schema - persistent cross-session learnings
MEMORY_SCHEMA_SQL = """
-- Memories table: persistent learnings across sessions
CREATE TABLE IF NOT EXISTS memories (
    id VARCHAR PRIMARY KEY,
    category VARCHAR NOT NULL,
    content TEXT NOT NULL,
    context TEXT,
    source VARCHAR,
    confidence REAL DEFAULT 1.0,
    importance INTEGER DEFAULT 1,
    tags JSON,
    embedding FLOAT[],
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL,
    accessed_at VARCHAR,
    access_count INTEGER DEFAULT 0
);

-- Indexes for efficient memory retrieval
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_accessed ON memories(accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_access_count ON memories(access_count DESC);
"""


# Patterns schema - detected codebase patterns
PATTERNS_SCHEMA_SQL = """
-- Patterns table: detected codebase patterns
CREATE TABLE IF NOT EXISTS patterns (
    id VARCHAR PRIMARY KEY,
    category VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    description TEXT,
    frequency INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.0,
    examples JSON,
    anti_patterns JSON,
    related_patterns JSON,
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL
);

-- Indexes for pattern queries
CREATE INDEX IF NOT EXISTS idx_patterns_category ON patterns(category);
CREATE INDEX IF NOT EXISTS idx_patterns_name ON patterns(name);
CREATE INDEX IF NOT EXISTS idx_patterns_frequency ON patterns(frequency DESC);
"""


# Codebase stats schema - language distribution and metrics
CODEBASE_STATS_SCHEMA_SQL = """
-- Codebase statistics computed during build
CREATE TABLE IF NOT EXISTS codebase_stats (
    key VARCHAR PRIMARY KEY,
    value JSON NOT NULL,
    updated_at VARCHAR NOT NULL
);
"""


__all__ = [
    "ChangeType",
    "NodeType",
    "EdgeType",
    "SCHEMA_SQL",
    "EMBEDDINGS_SCHEMA_SQL",
    "TEMPORAL_SCHEMA_SQL",
    "MEMORY_SCHEMA_SQL",
    "PATTERNS_SCHEMA_SQL",
    "CODEBASE_STATS_SCHEMA_SQL",
]
