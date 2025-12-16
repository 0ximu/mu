//! Data models for codebase compression.

use serde::Serialize;
use std::collections::BTreeMap;

/// Level of detail in the output
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum DetailLevel {
    /// Signatures only - minimal output
    Low,
    /// Signatures + relationships summary + hot paths
    Medium,
    /// Full output with relationship clusters
    High,
}

impl DetailLevel {
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "low" | "l" => Some(Self::Low),
            "medium" | "med" | "m" => Some(Self::Medium),
            "high" | "h" => Some(Self::High),
            _ => None,
        }
    }
}

/// Statistics about the codebase
#[derive(Debug, Clone, Copy, Serialize)]
pub struct CodebaseStats {
    pub total_modules: usize,
    pub total_classes: usize,
    pub total_functions: usize,
    pub total_edges: usize,
    pub has_graph: bool,
}

/// A compressed function representation
#[derive(Debug, Clone, Serialize)]
pub struct CompressedFunction {
    pub name: String,
    pub qualified_name: String,
    pub signature: String,
    pub complexity: u32,
    pub call_count: u32,
    pub is_hot: bool,
    pub docstring: Option<String>,
}

/// A compressed class representation
#[derive(Debug, Clone, Serialize)]
pub struct CompressedClass {
    pub name: String,
    pub bases: Vec<String>,
    pub uses: Vec<String>,
    pub used_by: Vec<String>,
    pub methods: Vec<CompressedFunction>,
    pub attributes: Vec<String>,
}

/// A compressed module representation
#[derive(Debug, Clone, Serialize)]
pub struct CompressedModule {
    pub name: String,
    pub path: String,
    pub classes: Vec<CompressedClass>,
    pub functions: Vec<CompressedFunction>,
}

/// A folder node in the hierarchy
#[derive(Debug, Clone, Serialize)]
pub struct FolderNode {
    pub name: String,
    pub path: String,
    pub modules: Vec<CompressedModule>,
    pub children: BTreeMap<String, FolderNode>,
}

impl FolderNode {
    pub fn new(name: &str, path: &str) -> Self {
        Self {
            name: name.to_string(),
            path: path.to_string(),
            modules: Vec::new(),
            children: BTreeMap::new(),
        }
    }
}

/// A hot path entry (high complexity or high call count)
#[derive(Debug, Clone, Serialize)]
pub struct HotPath {
    pub qualified_name: String,
    pub complexity: u32,
    pub call_count: u32,
    pub file_path: String,
}

/// A relationship in a cluster
#[derive(Debug, Clone, Serialize)]
pub struct Relationship {
    pub target: String,
    pub edge_type: String,
}

/// A cluster of relationships around an entity
#[derive(Debug, Clone, Serialize)]
pub struct RelationshipCluster {
    pub entity: String,
    pub entity_type: String,
    pub relationship_count: usize,
    pub outgoing: Vec<Relationship>,
    pub incoming: Vec<Relationship>,
}

/// Entity relationship with inferred semantics
#[derive(Debug, Clone, Serialize)]
pub struct EntityRelationship {
    pub target: String,
    pub rel_type: String, // belongs_to, has_many, has_one, uses, extends
}

/// A domain entity with scored importance
#[derive(Debug, Clone, Serialize)]
pub struct DomainEntity {
    pub name: String,
    pub importance: u8, // 1-3 stars
    pub attributes: Vec<String>,
    pub outgoing_rels: Vec<EntityRelationship>,
    pub incoming_rels: Vec<EntityRelationship>,
}

/// A detected state machine / workflow
#[derive(Debug, Clone, Serialize)]
pub struct StateFlow {
    pub name: String,
    pub states: Vec<String>,
}

/// Domain overview (extracted from patterns)
#[derive(Debug, Clone, Serialize)]
pub struct DomainOverview {
    pub domain_name: Option<String>,
    pub purpose: Option<String>,
    pub entities: Vec<DomainEntity>,
    pub flows: Vec<StateFlow>,
    pub integrations: Vec<String>,
    pub tech_stack: Vec<String>,
}

/// The complete compressed codebase
#[derive(Debug, Clone, Serialize)]
pub struct CompressedCodebase {
    pub source: String,
    pub stats: CodebaseStats,
    pub domain: Option<DomainOverview>,
    pub tree: FolderNode,
    pub hot_paths: Vec<HotPath>,
    pub relationship_clusters: Vec<RelationshipCluster>,
}

/// Result wrapper for output formatting
#[derive(Debug, Serialize)]
pub struct CompressResult {
    pub source: String,
    pub stats: CodebaseStats,
    pub content: String,
    pub detail_level: String,
}
