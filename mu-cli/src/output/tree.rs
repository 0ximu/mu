//! Tree output formatting for hierarchical display.
//!
//! Provides tree-style formatting similar to the `tree` command,
//! with Unicode box-drawing characters for visual hierarchy.

use super::OutputConfig;
use colored::Colorize;
use serde::Serialize;

/// Tree output formatter
pub struct TreeOutput;

/// Tree branch characters
struct TreeChars {
    /// Vertical line for continuing branches (|)
    pipe: &'static str,
    /// Branch for non-last items (|-)
    branch: &'static str,
    /// Branch for last item in a level (L-)
    last: &'static str,
    /// Spacing for items under last branch
    space: &'static str,
}

impl TreeChars {
    /// Unicode box-drawing characters
    const UNICODE: TreeChars = TreeChars {
        pipe: "\u{2502}   ",                 // |
        branch: "\u{251c}\u{2500}\u{2500} ", // |--
        last: "\u{2514}\u{2500}\u{2500} ",   // L--
        space: "    ",
    };

    /// ASCII fallback characters
    const ASCII: TreeChars = TreeChars {
        pipe: "|   ",
        branch: "|-- ",
        last: "`-- ",
        space: "    ",
    };

    /// Get appropriate characters based on config
    fn get(_config: &OutputConfig) -> &'static TreeChars {
        // Always use Unicode for now (could add ASCII fallback option)
        &Self::UNICODE
    }
}

impl TreeOutput {
    /// Format data as a tree string
    pub fn format<T: Serialize>(data: &T, config: &OutputConfig) -> String {
        if let Ok(json) = serde_json::to_value(data) {
            Self::format_value(&json, config, "", true)
        } else {
            "(error serializing data)".to_string()
        }
    }

    /// Format a JSON value as tree output
    fn format_value(
        value: &serde_json::Value,
        config: &OutputConfig,
        prefix: &str,
        is_last: bool,
    ) -> String {
        let _chars = TreeChars::get(config);
        let use_colors = config.use_colors();

        match value {
            serde_json::Value::Object(obj) => Self::format_object(obj, config, prefix, is_last),
            serde_json::Value::Array(arr) => Self::format_array(arr, config, prefix, is_last),
            serde_json::Value::String(s) => {
                if use_colors {
                    s.yellow().to_string()
                } else {
                    s.clone()
                }
            }
            serde_json::Value::Number(n) => {
                if use_colors {
                    n.to_string().cyan().to_string()
                } else {
                    n.to_string()
                }
            }
            serde_json::Value::Bool(b) => {
                if use_colors {
                    if *b {
                        "true".green().to_string()
                    } else {
                        "false".red().to_string()
                    }
                } else {
                    b.to_string()
                }
            }
            serde_json::Value::Null => {
                if use_colors {
                    "null".dimmed().to_string()
                } else {
                    "null".to_string()
                }
            }
        }
    }

    /// Format a JSON object as tree
    fn format_object(
        obj: &serde_json::Map<String, serde_json::Value>,
        config: &OutputConfig,
        prefix: &str,
        _is_last: bool,
    ) -> String {
        let chars = TreeChars::get(config);
        let use_colors = config.use_colors();
        let mut lines = Vec::new();

        let entries: Vec<_> = obj.iter().collect();
        let len = entries.len();

        for (i, (key, value)) in entries.iter().enumerate() {
            let is_last_item = i == len - 1;
            let connector = if is_last_item {
                chars.last
            } else {
                chars.branch
            };
            let child_prefix = format!(
                "{}{}",
                prefix,
                if is_last_item {
                    chars.space
                } else {
                    chars.pipe
                }
            );

            let key_str = if use_colors {
                key.bold().to_string()
            } else {
                (*key).clone()
            };

            match value {
                serde_json::Value::Object(nested) if !nested.is_empty() => {
                    lines.push(format!("{}{}{}", prefix, connector, key_str));
                    let nested_str =
                        Self::format_object(nested, config, &child_prefix, is_last_item);
                    lines.push(nested_str);
                }
                serde_json::Value::Array(arr) if !arr.is_empty() => {
                    let count_str = if use_colors {
                        format!("[{}]", arr.len()).dimmed().to_string()
                    } else {
                        format!("[{}]", arr.len())
                    };
                    lines.push(format!("{}{}{} {}", prefix, connector, key_str, count_str));
                    let arr_str = Self::format_array(arr, config, &child_prefix, is_last_item);
                    lines.push(arr_str);
                }
                _ => {
                    let value_str = Self::format_value(value, config, &child_prefix, is_last_item);
                    lines.push(format!("{}{}{}: {}", prefix, connector, key_str, value_str));
                }
            }
        }

        lines.join("\n")
    }

    /// Format a JSON array as tree
    fn format_array(
        arr: &[serde_json::Value],
        config: &OutputConfig,
        prefix: &str,
        _is_last: bool,
    ) -> String {
        let chars = TreeChars::get(config);
        let use_colors = config.use_colors();
        let mut lines = Vec::new();

        let len = arr.len();
        for (i, item) in arr.iter().enumerate() {
            let is_last_item = i == len - 1;
            let connector = if is_last_item {
                chars.last
            } else {
                chars.branch
            };
            let child_prefix = format!(
                "{}{}",
                prefix,
                if is_last_item {
                    chars.space
                } else {
                    chars.pipe
                }
            );

            let index_str = if use_colors {
                format!("[{}]", i).dimmed().to_string()
            } else {
                format!("[{}]", i)
            };

            match item {
                serde_json::Value::Object(obj) if !obj.is_empty() => {
                    lines.push(format!("{}{}{}", prefix, connector, index_str));
                    let obj_str = Self::format_object(obj, config, &child_prefix, is_last_item);
                    lines.push(obj_str);
                }
                serde_json::Value::Array(nested) if !nested.is_empty() => {
                    let count_str = if use_colors {
                        format!("[{}]", nested.len()).dimmed().to_string()
                    } else {
                        format!("[{}]", nested.len())
                    };
                    lines.push(format!(
                        "{}{}{} {}",
                        prefix, connector, index_str, count_str
                    ));
                    let nested_str =
                        Self::format_array(nested, config, &child_prefix, is_last_item);
                    lines.push(nested_str);
                }
                _ => {
                    let value_str = Self::format_value(item, config, &child_prefix, is_last_item);
                    lines.push(format!(
                        "{}{}{} {}",
                        prefix, connector, index_str, value_str
                    ));
                }
            }
        }

        lines.join("\n")
    }

    /// Create a simple tree from a root and children
    pub fn from_nodes(root: &str, children: &[TreeNode], config: &OutputConfig) -> String {
        let use_colors = config.use_colors();
        let root_str = if use_colors {
            root.bold().to_string()
        } else {
            root.to_string()
        };

        let mut lines = vec![root_str];
        Self::format_nodes(children, config, "", &mut lines);
        lines.join("\n")
    }

    /// Format tree nodes recursively
    fn format_nodes(
        nodes: &[TreeNode],
        config: &OutputConfig,
        prefix: &str,
        lines: &mut Vec<String>,
    ) {
        let chars = TreeChars::get(config);
        let use_colors = config.use_colors();
        let len = nodes.len();

        for (i, node) in nodes.iter().enumerate() {
            let is_last = i == len - 1;
            let connector = if is_last { chars.last } else { chars.branch };
            let child_prefix = format!(
                "{}{}",
                prefix,
                if is_last { chars.space } else { chars.pipe }
            );

            let name_str = if use_colors {
                match node.kind {
                    NodeKind::Directory => node.name.blue().bold().to_string(),
                    NodeKind::File => node.name.clone(),
                    NodeKind::Module => node.name.bright_blue().to_string(),
                    NodeKind::Function => node.name.bright_green().to_string(),
                    NodeKind::Type => node.name.bright_yellow().to_string(),
                    NodeKind::Other => node.name.clone(),
                }
            } else {
                node.name.clone()
            };

            let suffix = node
                .suffix
                .as_ref()
                .map(|s| {
                    if use_colors {
                        format!(" {}", s.dimmed())
                    } else {
                        format!(" {}", s)
                    }
                })
                .unwrap_or_default();

            lines.push(format!("{}{}{}{}", prefix, connector, name_str, suffix));

            if !node.children.is_empty() {
                Self::format_nodes(&node.children, config, &child_prefix, lines);
            }
        }
    }
}

/// A node in the tree structure
#[derive(Debug, Clone)]
pub struct TreeNode {
    /// Name of the node
    pub name: String,
    /// Kind of node (for coloring)
    pub kind: NodeKind,
    /// Optional suffix (e.g., file size, count)
    pub suffix: Option<String>,
    /// Child nodes
    pub children: Vec<TreeNode>,
}

impl TreeNode {
    /// Create a new tree node
    pub fn new(name: impl Into<String>, kind: NodeKind) -> Self {
        Self {
            name: name.into(),
            kind,
            suffix: None,
            children: Vec::new(),
        }
    }

    /// Builder: add a suffix
    pub fn with_suffix(mut self, suffix: impl Into<String>) -> Self {
        self.suffix = Some(suffix.into());
        self
    }

    /// Builder: add children
    pub fn with_children(mut self, children: Vec<TreeNode>) -> Self {
        self.children = children;
        self
    }

    /// Add a child node
    pub fn add_child(&mut self, child: TreeNode) {
        self.children.push(child);
    }
}

/// Kind of tree node for styling
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum NodeKind {
    /// Directory/folder
    Directory,
    /// Regular file
    File,
    /// Code module
    Module,
    /// Function
    Function,
    /// Type definition
    Type,
    /// Other/generic
    #[default]
    Other,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Serialize;

    #[derive(Serialize)]
    struct TestData {
        name: String,
        items: Vec<String>,
    }

    #[test]
    fn test_format_simple_object() {
        let data = TestData {
            name: "test".to_string(),
            items: vec!["a".to_string(), "b".to_string()],
        };
        let config = OutputConfig::new(super::super::OutputFormat::Tree).without_colors();
        let output = TreeOutput::format(&data, &config);

        assert!(output.contains("name"));
        assert!(output.contains("test"));
        assert!(output.contains("items"));
    }

    #[test]
    fn test_from_nodes() {
        let children = vec![
            TreeNode::new("src", NodeKind::Directory).with_children(vec![
                TreeNode::new("main.rs", NodeKind::File),
                TreeNode::new("lib.rs", NodeKind::File),
            ]),
            TreeNode::new("Cargo.toml", NodeKind::File),
        ];

        let config = OutputConfig::new(super::super::OutputFormat::Tree).without_colors();
        let output = TreeOutput::from_nodes("my-project", &children, &config);

        assert!(output.contains("my-project"));
        assert!(output.contains("src"));
        assert!(output.contains("main.rs"));
        assert!(output.contains("Cargo.toml"));
    }

    #[test]
    fn test_tree_node_builder() {
        let node = TreeNode::new("test", NodeKind::Module)
            .with_suffix("(5 functions)")
            .with_children(vec![TreeNode::new("child", NodeKind::Function)]);

        assert_eq!(node.name, "test");
        assert_eq!(node.kind, NodeKind::Module);
        assert_eq!(node.suffix, Some("(5 functions)".to_string()));
        assert_eq!(node.children.len(), 1);
    }
}
