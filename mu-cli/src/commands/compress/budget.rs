//! Adaptive token budgets for compress output.
//!
//! Provides token estimation, automatic detail level selection,
//! module scoring, and budget enforcement.

use super::models::{CompressedModule, DetailLevel};

/// Estimate token count for a text string.
/// Uses a heuristic of ~1.3 tokens per whitespace-delimited word,
/// which approximates typical LLM tokenizer behavior.
pub fn estimate_tokens(text: &str) -> usize {
    (text.split_whitespace().count() as f64 * 1.3) as usize
}

/// Automatically select a detail level based on the total node count
/// (modules + classes + functions). Larger codebases get less detail
/// to stay within reasonable token budgets.
pub fn auto_detail_level(node_count: usize) -> DetailLevel {
    if node_count < 100 {
        DetailLevel::High
    } else if node_count < 500 {
        DetailLevel::Medium
    } else {
        DetailLevel::Low
    }
}

/// Score a module by aggregating function complexity and call frequency.
/// Higher scores mean more "important" modules that should be prioritized
/// when trimming output to fit a budget.
pub fn score_module(module: &CompressedModule) -> u32 {
    let mut score: u32 = 0;

    for class in &module.classes {
        for method in &class.methods {
            score += method.complexity * 2 + method.call_count;
        }
    }

    for func in &module.functions {
        score += func.complexity * 2 + func.call_count;
    }

    score
}

/// Enforce a token budget on compressed output.
///
/// Scores each module, sorts by score descending (most important first),
/// then includes modules until the budget is exhausted. Returns the
/// concatenated content with an optional truncation notice.
pub fn enforce_budget(
    modules: &mut [CompressedModule],
    max_tokens: usize,
) -> Vec<CompressedModule> {
    // Score and sort: highest-scoring modules first
    let mut scored: Vec<(u32, usize)> = modules
        .iter()
        .enumerate()
        .map(|(i, m)| (score_module(m), i))
        .collect();
    scored.sort_by(|a, b| b.0.cmp(&a.0));

    let mut kept = Vec::new();
    let mut token_budget_remaining = max_tokens;
    let mut dropped = 0usize;

    for (_score, idx) in &scored {
        let module = &modules[*idx];

        // Rough estimate: module path + all function signatures
        let mut module_text = module.path.clone();
        for class in &module.classes {
            module_text.push(' ');
            module_text.push_str(&class.name);
            for method in &class.methods {
                module_text.push(' ');
                module_text.push_str(&method.name);
                module_text.push_str(&method.signature);
            }
        }
        for func in &module.functions {
            module_text.push(' ');
            module_text.push_str(&func.name);
            module_text.push_str(&func.signature);
        }

        let estimated = estimate_tokens(&module_text);
        if estimated <= token_budget_remaining {
            token_budget_remaining -= estimated;
            kept.push(module.clone());
        } else {
            dropped += 1;
        }
    }

    if dropped > 0 {
        // Add a sentinel module to signal truncation
        kept.push(CompressedModule {
            name: String::new(),
            path: format!("... {} modules omitted (token budget reached)", dropped),
            classes: Vec::new(),
            functions: Vec::new(),
        });
    }

    kept
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::compress::models::{CompressedClass, CompressedFunction};

    fn make_func(name: &str, complexity: u32, call_count: u32) -> CompressedFunction {
        CompressedFunction {
            name: name.to_string(),
            qualified_name: name.to_string(),
            signature: "()".to_string(),
            complexity,
            call_count,
            is_hot: false,
            docstring: None,
        }
    }

    #[test]
    fn test_estimate_tokens_basic() {
        let text = "fn foo() { let x = 1; }";
        let est = estimate_tokens(text);
        // 8 whitespace-delimited tokens * 1.3 = 10.4 -> 10
        assert_eq!(est, 10);
    }

    #[test]
    fn test_estimate_tokens_empty() {
        assert_eq!(estimate_tokens(""), 0);
    }

    #[test]
    fn test_auto_detail_small_codebase() {
        assert_eq!(auto_detail_level(50), DetailLevel::High);
    }

    #[test]
    fn test_auto_detail_medium_codebase() {
        assert_eq!(auto_detail_level(250), DetailLevel::Medium);
    }

    #[test]
    fn test_auto_detail_large_codebase() {
        assert_eq!(auto_detail_level(1000), DetailLevel::Low);
    }

    #[test]
    fn test_auto_detail_boundary_low() {
        assert_eq!(auto_detail_level(99), DetailLevel::High);
        assert_eq!(auto_detail_level(100), DetailLevel::Medium);
    }

    #[test]
    fn test_auto_detail_boundary_high() {
        assert_eq!(auto_detail_level(499), DetailLevel::Medium);
        assert_eq!(auto_detail_level(500), DetailLevel::Low);
    }

    #[test]
    fn test_score_module_with_functions() {
        let module = CompressedModule {
            name: "test_mod".to_string(),
            path: "test.py".to_string(),
            classes: vec![],
            functions: vec![make_func("simple", 5, 2), make_func("complex", 30, 10)],
        };

        // (5*2 + 2) + (30*2 + 10) = 12 + 70 = 82
        assert_eq!(score_module(&module), 82);
    }

    #[test]
    fn test_score_module_with_class_methods() {
        let module = CompressedModule {
            name: "test_mod".to_string(),
            path: "test.py".to_string(),
            classes: vec![CompressedClass {
                name: "MyClass".to_string(),
                bases: vec![],
                uses: vec![],
                used_by: vec![],
                methods: vec![make_func("method_a", 10, 3)],
                attributes: vec![],
            }],
            functions: vec![],
        };

        // 10*2 + 3 = 23
        assert_eq!(score_module(&module), 23);
    }

    #[test]
    fn test_score_module_empty() {
        let module = CompressedModule {
            name: "empty".to_string(),
            path: "empty.py".to_string(),
            classes: vec![],
            functions: vec![],
        };

        assert_eq!(score_module(&module), 0);
    }

    #[test]
    fn test_enforce_budget_includes_all_when_room() {
        let mut modules = vec![
            CompressedModule {
                name: "a".to_string(),
                path: "a.py".to_string(),
                classes: vec![],
                functions: vec![make_func("f", 1, 0)],
            },
            CompressedModule {
                name: "b".to_string(),
                path: "b.py".to_string(),
                classes: vec![],
                functions: vec![make_func("g", 1, 0)],
            },
        ];

        let result = enforce_budget(&mut modules, 100_000);
        // Both should fit, no truncation sentinel
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_enforce_budget_drops_low_priority() {
        let mut modules = vec![
            CompressedModule {
                name: "important".to_string(),
                path: "important.py".to_string(),
                classes: vec![],
                functions: vec![make_func("hot_fn", 50, 20)],
            },
            CompressedModule {
                name: "boring".to_string(),
                path: "boring.py".to_string(),
                classes: vec![],
                functions: vec![make_func("trivial", 1, 0)],
            },
        ];

        // Budget enough for one module but not both.
        // "important.py hot_fn()" -> 2 whitespace tokens * 1.3 = 2.6 -> 2
        // "boring.py trivial()" -> 2 whitespace tokens * 1.3 = 2.6 -> 2
        // Budget of 3 fits the important one (scored higher) but not the boring one
        let result = enforce_budget(&mut modules, 3);
        // Should have: important module + truncation sentinel
        assert_eq!(result.len(), 2);
        assert_eq!(result[0].name, "important");
        assert!(result[1].path.contains("omitted"));
    }
}
