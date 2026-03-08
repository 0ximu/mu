//! Adaptive token budgets for compress output.
//!
//! Provides token estimation, automatic detail level selection,
//! module scoring, and budget enforcement.

use super::models::DetailLevel;

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

#[cfg(test)]
mod tests {
    use super::*;

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
}
