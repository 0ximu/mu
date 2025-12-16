//! Database schema definitions for MU.
//!
//! Defines node types, edge types, and the DuckDB schema.

use serde::{Deserialize, Serialize};
use std::fmt;

/// Types of nodes in the code graph.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum NodeType {
    /// File/module level
    Module,
    /// Class/struct/interface
    Class,
    /// Function/method
    Function,
    /// External dependency (package)
    External,
}

impl NodeType {
    pub fn as_str(&self) -> &'static str {
        match self {
            NodeType::Module => "module",
            NodeType::Class => "class",
            NodeType::Function => "function",
            NodeType::External => "external",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "module" => Some(NodeType::Module),
            "class" => Some(NodeType::Class),
            "function" => Some(NodeType::Function),
            "external" => Some(NodeType::External),
            _ => None,
        }
    }
}

impl fmt::Display for NodeType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// Types of relationships between nodes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum EdgeType {
    /// Module→Class, Class→Function, Module→Function
    Contains,
    /// Module→Module (internal dependencies)
    Imports,
    /// Class→Class (inheritance)
    Inherits,
    /// Function→Function (call relationships)
    Calls,
    /// Function→Variable (usage)
    Uses,
}

impl EdgeType {
    pub fn as_str(&self) -> &'static str {
        match self {
            EdgeType::Contains => "contains",
            EdgeType::Imports => "imports",
            EdgeType::Inherits => "inherits",
            EdgeType::Calls => "calls",
            EdgeType::Uses => "uses",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "contains" => Some(EdgeType::Contains),
            "imports" => Some(EdgeType::Imports),
            "inherits" => Some(EdgeType::Inherits),
            "calls" => Some(EdgeType::Calls),
            "uses" => Some(EdgeType::Uses),
            _ => None,
        }
    }
}

impl fmt::Display for EdgeType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// SQL schema for creating the MU database tables.
pub const SCHEMA_SQL: &str = r#"
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

-- Embeddings table for vector storage
-- Note: embedding stored as JSON array string since DuckDB Rust API has limited FLOAT[] support
CREATE TABLE IF NOT EXISTS embeddings (
    node_id VARCHAR PRIMARY KEY,
    embedding VARCHAR NOT NULL,
    model VARCHAR NOT NULL DEFAULT 'mu-sigma-v2',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- File hashes for incremental embedding updates
CREATE TABLE IF NOT EXISTS file_hashes (
    file_path VARCHAR PRIMARY KEY,
    content_hash VARCHAR NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model);
"#;

/// Schema version for migrations
pub const SCHEMA_VERSION: &str = "1.0.0";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_node_type_roundtrip() {
        for nt in [
            NodeType::Module,
            NodeType::Class,
            NodeType::Function,
            NodeType::External,
        ] {
            let s = nt.as_str();
            let parsed = NodeType::parse(s);
            assert_eq!(parsed, Some(nt));
        }
    }

    #[test]
    fn test_edge_type_roundtrip() {
        for et in [
            EdgeType::Contains,
            EdgeType::Imports,
            EdgeType::Inherits,
            EdgeType::Calls,
            EdgeType::Uses,
        ] {
            let s = et.as_str();
            let parsed = EdgeType::parse(s);
            assert_eq!(parsed, Some(et));
        }
    }
}
