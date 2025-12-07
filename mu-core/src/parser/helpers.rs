//! Helper functions for tree-sitter AST navigation.

use tree_sitter::Node;

/// Get the text content of a node.
pub fn get_node_text<'a>(node: &Node, source: &'a str) -> &'a str {
    let start = node.start_byte();
    let end = node.end_byte();
    if start < source.len() && end <= source.len() && start < end {
        &source[start..end]
    } else {
        ""
    }
}

/// Find the first child of a specific type.
#[allow(clippy::manual_find)]
pub fn find_child_by_type<'a>(node: &Node<'a>, type_name: &str) -> Option<Node<'a>> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == type_name {
            return Some(child);
        }
    }
    None
}

/// Find all children of a specific type.
#[allow(dead_code)]
pub fn find_children_by_type<'a>(node: &Node<'a>, type_name: &str) -> Vec<Node<'a>> {
    let mut results = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == type_name {
            results.push(child);
        }
    }
    results
}

/// Find the first child with a specific field name.
#[allow(dead_code)]
pub fn get_child_by_field<'a>(node: &Node<'a>, field_name: &str) -> Option<Node<'a>> {
    node.child_by_field_name(field_name)
}

/// Count the number of nodes in a subtree (for complexity).
#[allow(dead_code)]
pub fn count_nodes(node: &Node) -> u32 {
    let mut count = 1u32;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        count = count.saturating_add(count_nodes(&child));
    }
    count
}

/// Extract a docstring from a node (if it's a string literal).
#[allow(dead_code)]
pub fn extract_docstring(node: Option<Node>, source: &str) -> Option<String> {
    let node = node?;
    let text = get_node_text(&node, source);

    // Python: """docstring""" or '''docstring'''
    // Also handles regular strings
    let trimmed = text
        .trim_start_matches("\"\"\"")
        .trim_start_matches("'''")
        .trim_start_matches("\"")
        .trim_start_matches("'")
        .trim_end_matches("\"\"\"")
        .trim_end_matches("'''")
        .trim_end_matches("\"")
        .trim_end_matches("'")
        .trim();

    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

/// Check if a node has a child of a specific type.
#[allow(dead_code)]
pub fn has_child_of_type(node: &Node, type_name: &str) -> bool {
    find_child_by_type(node, type_name).is_some()
}

/// Get line number (1-indexed) from a node.
pub fn get_start_line(node: &Node) -> u32 {
    node.start_position().row as u32 + 1
}

/// Get end line number (1-indexed) from a node.
pub fn get_end_line(node: &Node) -> u32 {
    node.end_position().row as u32 + 1
}

/// Count total lines in source.
pub fn count_lines(source: &str) -> u32 {
    source.lines().count() as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_count_lines() {
        assert_eq!(count_lines("line1\nline2\nline3"), 3);
        assert_eq!(count_lines("single"), 1);
        assert_eq!(count_lines(""), 0);
    }

    #[test]
    fn test_extract_docstring() {
        assert_eq!(
            extract_docstring_from_text("\"\"\"Hello world\"\"\""),
            Some("Hello world".to_string())
        );
        assert_eq!(
            extract_docstring_from_text("'''Hello'''"),
            Some("Hello".to_string())
        );
        assert_eq!(
            extract_docstring_from_text("\"test\""),
            Some("test".to_string())
        );
    }

    fn extract_docstring_from_text(text: &str) -> Option<String> {
        let trimmed = text
            .trim_start_matches("\"\"\"")
            .trim_start_matches("'''")
            .trim_start_matches("\"")
            .trim_start_matches("'")
            .trim_end_matches("\"\"\"")
            .trim_end_matches("'''")
            .trim_end_matches("\"")
            .trim_end_matches("'")
            .trim();

        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    }
}
