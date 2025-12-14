//! Node model and operations.

use super::schema::NodeType;
use serde::{Deserialize, Serialize};

/// A node in the code graph.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Node {
    /// Unique identifier (e.g., "mod:src/cli.py", "fn:src/cli.py:main")
    pub id: String,
    /// Type of node
    pub node_type: NodeType,
    /// Short name (e.g., "main", "MUbase")
    pub name: String,
    /// Fully qualified name (optional)
    pub qualified_name: Option<String>,
    /// File path (relative to project root)
    pub file_path: Option<String>,
    /// Start line number
    pub line_start: Option<u32>,
    /// End line number
    pub line_end: Option<u32>,
    /// Cyclomatic complexity
    pub complexity: u32,
    /// Additional properties (JSON)
    pub properties: Option<serde_json::Value>,
}

impl Node {
    /// Create a new module node.
    pub fn module(file_path: &str) -> Self {
        let name = std::path::Path::new(file_path)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or_else(|| {
                // Fall back to file_path if we can't extract a stem
                // This handles edge cases like paths with invalid UTF-8
                file_path
            })
            .to_string();

        Self {
            id: format!("mod:{}", file_path),
            node_type: NodeType::Module,
            name,
            qualified_name: Some(file_path.to_string()),
            file_path: Some(file_path.to_string()),
            line_start: Some(1),
            line_end: None,
            complexity: 0,
            properties: None,
        }
    }

    /// Create a new class node.
    pub fn class(file_path: &str, name: &str, line_start: u32, line_end: u32) -> Self {
        Self {
            id: format!("cls:{}:{}", file_path, name),
            node_type: NodeType::Class,
            name: name.to_string(),
            qualified_name: Some(format!("{}:{}", file_path, name)),
            file_path: Some(file_path.to_string()),
            line_start: Some(line_start),
            line_end: Some(line_end),
            complexity: 0,
            properties: None,
        }
    }

    /// Create a new function node.
    pub fn function(
        file_path: &str,
        name: &str,
        class_name: Option<&str>,
        line_start: u32,
        line_end: u32,
        complexity: u32,
    ) -> Self {
        let id = match class_name {
            Some(cls) => format!("fn:{}:{}.{}", file_path, cls, name),
            None => format!("fn:{}:{}", file_path, name),
        };

        let qualified_name = match class_name {
            Some(cls) => format!("{}:{}.{}", file_path, cls, name),
            None => format!("{}:{}", file_path, name),
        };

        Self {
            id,
            node_type: NodeType::Function,
            name: name.to_string(),
            qualified_name: Some(qualified_name),
            file_path: Some(file_path.to_string()),
            line_start: Some(line_start),
            line_end: Some(line_end),
            complexity,
            properties: None,
        }
    }

    /// Create an external dependency node.
    pub fn external(module_name: &str) -> Self {
        Self {
            id: format!("ext:{}", module_name),
            node_type: NodeType::External,
            name: module_name.to_string(),
            qualified_name: None,
            file_path: None,
            line_start: None,
            line_end: None,
            complexity: 0,
            properties: None,
        }
    }

    /// Set properties on the node.
    pub fn with_properties(mut self, properties: serde_json::Value) -> Self {
        self.properties = Some(properties);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_module_node() {
        let node = Node::module("src/cli.py");
        assert_eq!(node.id, "mod:src/cli.py");
        assert_eq!(node.name, "cli");
        assert_eq!(node.node_type, NodeType::Module);
    }

    #[test]
    fn test_class_node() {
        let node = Node::class("src/cli.py", "MUbase", 10, 100);
        assert_eq!(node.id, "cls:src/cli.py:MUbase");
        assert_eq!(node.name, "MUbase");
        assert_eq!(node.node_type, NodeType::Class);
    }

    #[test]
    fn test_function_node_standalone() {
        let node = Node::function("src/cli.py", "main", None, 5, 20, 3);
        assert_eq!(node.id, "fn:src/cli.py:main");
        assert_eq!(node.name, "main");
        assert_eq!(node.complexity, 3);
    }

    #[test]
    fn test_function_node_method() {
        let node = Node::function("src/cli.py", "build", Some("MUbase"), 50, 80, 5);
        assert_eq!(node.id, "fn:src/cli.py:MUbase.build");
        assert_eq!(node.name, "build");
    }
}
