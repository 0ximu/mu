//! Cyclomatic complexity calculation.
//!
//! Calculates McCabe cyclomatic complexity by counting decision points
//! in the AST. Each language has its own set of decision point node types.

use once_cell::sync::Lazy;
use std::collections::{HashMap, HashSet};
use tree_sitter::Node;

/// Decision point node types by language (tree-sitter node names).
static DECISION_POINTS: Lazy<HashMap<&str, HashSet<&str>>> = Lazy::new(|| {
    let mut m = HashMap::new();

    m.insert("python", HashSet::from([
        "if_statement",
        "for_statement",
        "while_statement",
        "except_clause",
        "with_statement",
        "assert_statement",
        "boolean_operator",  // 'and', 'or' wrapped by tree-sitter
        "conditional_expression",  // ternary
        "match_statement",
        "case_clause",
        // Comprehension clauses (count each loop/condition inside)
        "for_in_clause",
        "if_clause",
    ]));

    m.insert("typescript", HashSet::from([
        "if_statement",
        "for_statement",
        "while_statement",
        "for_in_statement",
        "do_statement",
        "switch_case",
        "catch_clause",
        "ternary_expression",
        "binary_expression",  // SPECIAL: check operator
    ]));

    m.insert("javascript", HashSet::from([
        "if_statement",
        "for_statement",
        "while_statement",
        "for_in_statement",
        "do_statement",
        "switch_case",
        "catch_clause",
        "ternary_expression",
        "binary_expression",  // SPECIAL: check operator
    ]));

    m.insert("go", HashSet::from([
        "if_statement",
        "for_statement",
        "expression_case",
        "type_case",
        "communication_case",
        "binary_expression",  // SPECIAL: check operator
    ]));

    m.insert("java", HashSet::from([
        "if_statement",
        "for_statement",
        "while_statement",
        "do_statement",
        "enhanced_for_statement",
        "switch_block_statement_group",
        "catch_clause",
        "ternary_expression",
        "binary_expression",  // SPECIAL: check operator
    ]));

    m.insert("rust", HashSet::from([
        "if_expression",
        "for_expression",
        "while_expression",
        "loop_expression",
        "match_expression",
        "match_arm",
        "binary_expression",  // SPECIAL: check operator
    ]));

    m.insert("csharp", HashSet::from([
        "if_statement",
        "for_statement",
        "while_statement",
        "do_statement",
        "foreach_statement",
        "switch_section",
        "catch_clause",
        "conditional_expression",
        "binary_expression",  // SPECIAL: check operator
        "switch_expression",
        "switch_expression_arm",
        "conditional_access_expression",
    ]));

    m
});

/// Binary operators that count as decision points.
static DECISION_OPERATORS: Lazy<HashSet<&str>> = Lazy::new(|| {
    HashSet::from(["&&", "||", "and", "or", "??"])
});

/// Calculate cyclomatic complexity for a code snippet.
///
/// Base complexity is 1. Each decision point adds 1.
/// Decision points: if, for, while, case, catch, &&, ||, ternary, etc.
pub fn calculate(source: &str, language: &str) -> u32 {
    // This is a simplified version - for full accuracy, we'd need to parse
    // the source and walk the AST. For now, we'll use heuristics.
    let decision_types = DECISION_POINTS.get(language).cloned().unwrap_or_default();
    let mut complexity = 1u32;

    // Simple keyword counting as fallback
    for keyword in &["if ", "for ", "while ", "catch ", "case ", "elif ", "else if "] {
        complexity += source.matches(keyword).count() as u32;
    }

    for op in DECISION_OPERATORS.iter() {
        complexity += source.matches(op).count() as u32;
    }

    complexity
}

/// Calculate cyclomatic complexity for a tree-sitter node.
///
/// This is the accurate version that walks the AST.
pub fn calculate_for_node(node: &Node, source: &str, language: &str) -> u32 {
    let decision_types = DECISION_POINTS.get(language).cloned().unwrap_or_default();
    let mut complexity = 1u32;

    fn is_decision_operator(node: &Node, source: &str) -> bool {
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            let start = child.start_byte();
            let end = child.end_byte();
            if start < source.len() && end <= source.len() {
                let text = &source[start..end];
                if DECISION_OPERATORS.contains(text) {
                    return true;
                }
            }
        }
        false
    }

    fn traverse(node: &Node, source: &str, decision_types: &HashSet<&str>, complexity: &mut u32) {
        if decision_types.contains(node.kind()) {
            if node.kind() == "binary_expression" {
                // Only count if operator is && || or ??
                if is_decision_operator(node, source) {
                    *complexity += 1;
                }
            } else {
                *complexity += 1;
            }
        }

        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            traverse(&child, source, decision_types, complexity);
        }
    }

    traverse(node, source, &decision_types, &mut complexity);
    complexity
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_complexity() {
        let source = "def foo(): pass";
        assert_eq!(calculate(source, "python"), 1);
    }

    #[test]
    fn test_if_complexity() {
        let source = "if x: pass";
        assert_eq!(calculate(source, "python"), 2);
    }

    #[test]
    fn test_multiple_conditions() {
        let source = "if x and y or z: pass";
        // 1 (base) + 1 (if) + 1 (and) + 1 (or) = 4
        assert_eq!(calculate(source, "python"), 4);
    }
}
