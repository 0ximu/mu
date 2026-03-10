//! Edge model and operations.

use super::schema::EdgeType;
use serde::{Deserialize, Serialize};

/// An edge (relationship) in the code graph.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edge {
    /// Unique identifier
    pub id: String,
    /// Source node ID
    pub source_id: String,
    /// Target node ID
    pub target_id: String,
    /// Type of relationship
    pub edge_type: EdgeType,
    /// Additional properties (JSON)
    pub properties: Option<serde_json::Value>,
}

impl Edge {
    /// Create a new edge.
    pub fn new(source_id: &str, target_id: &str, edge_type: EdgeType) -> Self {
        let id = format!("edge:{}:{}:{}", source_id, edge_type.as_str(), target_id);
        Self {
            id,
            source_id: source_id.to_string(),
            target_id: target_id.to_string(),
            edge_type,
            properties: None,
        }
    }

    /// Create a CONTAINS edge (parent contains child).
    pub fn contains(parent_id: &str, child_id: &str) -> Self {
        Self::new(parent_id, child_id, EdgeType::Contains)
    }

    /// Create an IMPORTS edge (module imports another module).
    pub fn imports(from_module: &str, to_module: &str) -> Self {
        Self::new(from_module, to_module, EdgeType::Imports)
    }

    /// Create an INHERITS edge (class inherits from another class).
    pub fn inherits(child_class: &str, parent_class: &str) -> Self {
        Self::new(child_class, parent_class, EdgeType::Inherits)
    }

    /// Create a CALLS edge (function calls another function).
    pub fn calls(caller: &str, callee: &str) -> Self {
        Self::new(caller, callee, EdgeType::Calls)
    }

    /// Create a USES edge (class/method references a type).
    pub fn uses(from: &str, type_ref: &str) -> Self {
        Self::new(from, type_ref, EdgeType::Uses)
    }

    /// Create a PUBLISHES edge (class/method publishes a message type).
    pub fn publishes(from: &str, message_node: &str) -> Self {
        Self::new(from, message_node, EdgeType::Publishes)
    }

    /// Create a SUBSCRIBES edge (consumer class subscribes to a message type).
    pub fn subscribes(from: &str, message_node: &str) -> Self {
        Self::new(from, message_node, EdgeType::Subscribes)
    }

    /// Create a CALLS_HTTP edge (method makes HTTP calls).
    pub fn calls_http(from: &str, target: &str) -> Self {
        Self::new(from, target, EdgeType::CallsHttp)
    }

    /// Create a USES_CONTRACT edge (class references a shared contract type).
    pub fn uses_contract(from: &str, contract_type: &str) -> Self {
        Self::new(from, contract_type, EdgeType::UsesContract)
    }

    /// Create a MACRO_DISPATCH soft edge (proc macro wiring, e.g. #[tool]).
    pub fn macro_dispatch(caller: &str, callee: &str) -> Self {
        Self::new(caller, callee, EdgeType::MacroDispatch)
    }

    /// Create a TRAIT_IMPL soft edge (trait method implementation).
    pub fn trait_impl(impl_fn: &str, trait_fn: &str) -> Self {
        Self::new(impl_fn, trait_fn, EdgeType::TraitImpl)
    }

    /// Create a DI_REGISTRATION soft edge (dependency injection wiring).
    pub fn di_registration(registrar: &str, service: &str) -> Self {
        Self::new(registrar, service, EdgeType::DiRegistration)
    }

    /// Create a DECORATOR_DISPATCH soft edge (Python/JS decorator wiring).
    pub fn decorator_dispatch(decorator: &str, target: &str) -> Self {
        Self::new(decorator, target, EdgeType::DecoratorDispatch)
    }

    /// Set properties on the edge.
    pub fn with_properties(mut self, properties: serde_json::Value) -> Self {
        self.properties = Some(properties);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_edge_creation() {
        let edge = Edge::new("mod:a.py", "mod:b.py", EdgeType::Imports);
        assert_eq!(edge.source_id, "mod:a.py");
        assert_eq!(edge.target_id, "mod:b.py");
        assert_eq!(edge.edge_type, EdgeType::Imports);
        assert!(edge.id.contains("imports"));
    }

    #[test]
    fn test_contains_edge() {
        let edge = Edge::contains("mod:src/cli.py", "cls:src/cli.py:MUbase");
        assert_eq!(edge.edge_type, EdgeType::Contains);
    }

    #[test]
    fn test_inherits_edge() {
        let edge = Edge::inherits("cls:models.py:User", "cls:models.py:BaseModel");
        assert_eq!(edge.edge_type, EdgeType::Inherits);
    }

    #[test]
    fn test_uses_edge() {
        // Test internal type reference
        let edge = Edge::uses("cls:service.cs:AuthService", "cls:models.cs:User");
        assert_eq!(edge.edge_type, EdgeType::Uses);
        assert_eq!(edge.source_id, "cls:service.cs:AuthService");
        assert_eq!(edge.target_id, "cls:models.cs:User");
        assert!(edge.id.contains("uses"));
    }

    #[test]
    fn test_uses_edge_external() {
        // Test external type reference
        let edge = Edge::uses("cls:service.cs:AuthService", "ext:HttpClient");
        assert_eq!(edge.edge_type, EdgeType::Uses);
        assert_eq!(edge.target_id, "ext:HttpClient");
    }
}
