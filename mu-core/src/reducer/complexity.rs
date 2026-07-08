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

    m.insert(
        "python",
        HashSet::from([
            "if_statement",
            "elif_clause",
            "for_statement",
            "while_statement",
            "except_clause",
            "boolean_operator",       // 'and', 'or' wrapped by tree-sitter
            "conditional_expression", // ternary
            // Comprehension clauses (count each loop/condition inside)
            "for_in_clause",
            "if_clause",
        ]),
    );

    m.insert(
        "typescript",
        HashSet::from([
            "if_statement",
            "for_statement",
            "while_statement",
            "for_in_statement",
            "do_statement",
            "switch_case",
            "catch_clause",
            "ternary_expression",
            "binary_expression", // SPECIAL: check operator
        ]),
    );

    m.insert(
        "javascript",
        HashSet::from([
            "if_statement",
            "for_statement",
            "while_statement",
            "for_in_statement",
            "do_statement",
            "switch_case",
            "catch_clause",
            "ternary_expression",
            "binary_expression", // SPECIAL: check operator
        ]),
    );

    m.insert(
        "go",
        HashSet::from([
            "if_statement",
            "for_statement",
            "expression_case",
            "type_case",
            "communication_case",
            "binary_expression", // SPECIAL: check operator
        ]),
    );

    m.insert(
        "java",
        HashSet::from([
            "if_statement",
            "for_statement",
            "while_statement",
            "do_statement",
            "enhanced_for_statement",
            "switch_block_statement_group",
            "switch_rule", // Java 14 arrow switches: case 1 -> ...
            "catch_clause",
            "ternary_expression",
            "binary_expression", // SPECIAL: check operator
        ]),
    );

    m.insert(
        "rust",
        HashSet::from([
            "if_expression",
            "for_expression",
            "while_expression",
            "loop_expression",
            "binary_expression", // SPECIAL: check operator
        ]),
    );

    m.insert(
        "csharp",
        HashSet::from([
            "if_statement",
            "for_statement",
            "while_statement",
            "do_statement",
            "foreach_statement",
            "switch_section",
            "catch_clause",
            "conditional_expression",
            "binary_expression", // SPECIAL: check operator
            "conditional_access_expression",
        ]),
    );

    m
});

/// Branching containers counted as `max(arm_count - 1, 0)` instead of one
/// point per node. Counting both the container and every arm double-counts:
/// a 4-arm rust match would score 6 instead of 4.
///
/// Maps language -> (container node kind, arm node kind).
static BRANCHING_CONTAINERS: Lazy<HashMap<&str, HashMap<&str, &str>>> = Lazy::new(|| {
    let mut m = HashMap::new();

    let mut rust = HashMap::new();
    rust.insert("match_expression", "match_arm");
    m.insert("rust", rust);

    let mut python = HashMap::new();
    python.insert("match_statement", "case_clause");
    m.insert("python", python);

    let mut csharp = HashMap::new();
    csharp.insert("switch_expression", "switch_expression_arm");
    m.insert("csharp", csharp);

    m
});

/// Binary operators that count as decision points.
static DECISION_OPERATORS: Lazy<HashSet<&str>> =
    Lazy::new(|| HashSet::from(["&&", "||", "and", "or", "??"]));

/// Calculate cyclomatic complexity for a code snippet.
///
/// Base complexity is 1. Each decision point adds 1.
/// Decision points: if, for, while, case, catch, &&, ||, ternary, etc.
pub fn calculate(source: &str, language: &str) -> u32 {
    // This is a simplified version - for full accuracy, we'd need to parse
    // the source and walk the AST. For now, we'll use heuristics.
    let _decision_types = DECISION_POINTS.get(language).cloned().unwrap_or_default();
    let mut complexity = 1u32;

    // Simple keyword counting as fallback
    for keyword in &[
        "if ", "for ", "while ", "catch ", "case ", "elif ", "else if ",
    ] {
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
    let containers = BRANCHING_CONTAINERS.get(language).cloned().unwrap_or_default();
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

    /// Count arm nodes belonging to this container, without descending into
    /// nested containers of the same kind (their arms count for themselves).
    fn count_arms(node: &Node, container_kind: &str, arm_kind: &str) -> u32 {
        let mut count = 0;
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            if child.kind() == arm_kind {
                count += 1;
            }
            if child.kind() != container_kind {
                count += count_arms(&child, container_kind, arm_kind);
            }
        }
        count
    }

    fn traverse(
        node: &Node,
        source: &str,
        decision_types: &HashSet<&str>,
        containers: &HashMap<&str, &str>,
        complexity: &mut u32,
    ) {
        if let Some(arm_kind) = containers.get(node.kind()) {
            // An N-arm match/switch expression is N paths: N - 1 decision points.
            let arms = count_arms(node, node.kind(), arm_kind);
            *complexity += arms.saturating_sub(1);
        } else if decision_types.contains(node.kind()) {
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
            traverse(&child, source, decision_types, containers, complexity);
        }
    }

    traverse(node, source, &decision_types, &containers, &mut complexity);
    complexity
}

#[cfg(test)]
mod tests {
    use super::*;
    use tree_sitter::Parser;

    fn node_complexity(source: &str, language: &str, ts_language: tree_sitter::Language) -> u32 {
        let mut parser = Parser::new();
        parser.set_language(&ts_language).unwrap();
        let tree = parser.parse(source, None).unwrap();
        let root = tree.root_node();
        assert!(!root.has_error(), "test snippet must parse cleanly");
        calculate_for_node(&root, source, language)
    }

    fn python_complexity(source: &str) -> u32 {
        node_complexity(source, "python", tree_sitter_python::LANGUAGE.into())
    }

    #[test]
    fn test_python_elif_chain_counts_each_branch() {
        let source = r#"
def f(x):
    if x == 1:
        pass
    elif x == 2:
        pass
    elif x == 3:
        pass
    else:
        pass
"#;
        // base 1 + if + elif + elif = 4 (else adds no decision point)
        assert_eq!(python_complexity(source), 4);
    }

    #[test]
    fn test_python_with_and_assert_are_not_branches() {
        let source = r#"
def g():
    with open('f') as f:
        assert f
        assert f
"#;
        assert_eq!(python_complexity(source), 1);
    }

    #[test]
    fn test_python_match_counts_arms_minus_one() {
        let source = r#"
def h(x):
    match x:
        case 1:
            pass
        case 2:
            pass
        case 3:
            pass
        case _:
            pass
"#;
        // base 1 + max(4 arms - 1, 0) = 4
        assert_eq!(python_complexity(source), 4);
    }

    #[test]
    fn test_rust_match_counts_arms_minus_one() {
        let source = r#"
fn f(x: u32) -> u32 {
    match x {
        1 => 1,
        2 => 2,
        3 => 3,
        _ => 0,
    }
}
"#;
        // base 1 + max(4 arms - 1, 0) = 4, not 6 (container + every arm)
        assert_eq!(
            node_complexity(source, "rust", tree_sitter_rust::LANGUAGE.into()),
            4
        );
    }

    #[test]
    fn test_rust_if_else_still_counts() {
        let source = r#"
fn f(x: u32) -> u32 {
    if x > 1 {
        1
    } else {
        0
    }
}
"#;
        assert_eq!(
            node_complexity(source, "rust", tree_sitter_rust::LANGUAGE.into()),
            2
        );
    }

    #[test]
    fn test_csharp_switch_expression_counts_arms_minus_one() {
        let source = r#"
public class C {
    public int F(int x) {
        return x switch {
            1 => 1,
            2 => 2,
            3 => 3,
            _ => 0,
        };
    }
}
"#;
        // base 1 + max(4 arms - 1, 0) = 4
        assert_eq!(
            node_complexity(source, "csharp", tree_sitter_c_sharp::LANGUAGE.into()),
            4
        );
    }

    #[test]
    fn test_java_arrow_switch_rules_count() {
        let source = r#"
class C {
    int f(int x) {
        switch (x) {
            case 1 -> System.out.println(1);
            case 2 -> System.out.println(2);
            case 3 -> System.out.println(3);
        }
        return 0;
    }
}
"#;
        // base 1 + 3 switch_rule = 4 (previously arrow switches added zero)
        assert_eq!(
            node_complexity(source, "java", tree_sitter_java::LANGUAGE.into()),
            4
        );
    }

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
