//! Adaptive token budgets for compress output.
//!
//! Provides token estimation, automatic detail level selection,
//! importance percentiles, and budget-driven graceful degradation.
//!
//! Degradation levels (0 = most detail, 3 = least):
//! - 0: current full output at the selected detail level
//! - 1: full detail only for functions at or above median importance;
//!   below-median functions keep their names in compact lists
//! - 2: per module, only the top-5 symbols by importance plus a count
//!   of what was omitted
//! - 3: directory skeleton with per-directory counts and top-3 symbols
//!
//! The renderer picks the most detailed level whose estimated size fits
//! the budget and ALWAYS appends an explicit budget footer. Silent
//! truncation is a bug, not a feature.

use super::models::{CompressedCodebase, CompressedModule, DetailLevel, FolderNode};

/// Estimate token count for a text string.
/// Uses a heuristic of ~1.3 tokens per whitespace-delimited word,
/// which approximates typical LLM tokenizer behavior.
pub fn estimate_tokens(text: &str) -> usize {
    (text.split_whitespace().count() as f64 * 1.3) as usize
}

/// Estimate token count from character length: chars / 4.
/// LLM tokenizers average roughly 4 characters per token on source-like
/// text; that is accurate enough for budget enforcement.
pub fn estimate_tokens_chars(text: &str) -> usize {
    text.chars().count().div_ceil(4)
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

// ============================================================================
// Importance percentiles
// ============================================================================

/// Sorted importance scores for O(log n) percentile-rank lookups.
///
/// Raw importance scores are normalized over the whole graph, so on large
/// codebases almost every score rounds to 0.00. Percentile rank ("p87")
/// is the readable form.
pub struct PercentileTable {
    sorted: Vec<f32>,
}

impl PercentileTable {
    pub fn new(mut scores: Vec<f32>) -> Self {
        scores.retain(|s| s.is_finite());
        scores.sort_by(f32::total_cmp);
        Self { sorted: scores }
    }

    /// Percentile rank of `score`: the percentage of scores <= `score`,
    /// clamped to 0-100. An empty table returns 0; a single-entry table
    /// ranks its own score at 100.
    pub fn rank(&self, score: f32) -> u8 {
        if self.sorted.is_empty() {
            return 0;
        }
        let at_or_below = self.sorted.partition_point(|s| *s <= score);
        ((at_or_below * 100) / self.sorted.len()).min(100) as u8
    }
}

// ============================================================================
// Tree walking helpers
// ============================================================================

pub(super) fn for_each_module<'a>(node: &'a FolderNode, f: &mut dyn FnMut(&'a CompressedModule)) {
    for module in &node.modules {
        f(module);
    }
    for child in node.children.values() {
        for_each_module(child, f);
    }
}

/// Median importance across all functions (methods + free functions).
pub(super) fn median_function_importance(cb: &CompressedCodebase) -> f32 {
    let mut scores: Vec<f32> = Vec::new();
    for_each_module(&cb.tree, &mut |m| {
        for c in &m.classes {
            for func in &c.methods {
                scores.push(func.importance);
            }
        }
        for func in &m.functions {
            scores.push(func.importance);
        }
    });
    if scores.is_empty() {
        return 0.0;
    }
    scores.sort_by(f32::total_cmp);
    scores[scores.len() / 2]
}

/// All symbol (class + function) importances, for percentile display.
pub(super) fn symbol_importances(cb: &CompressedCodebase) -> Vec<f32> {
    let mut scores: Vec<f32> = Vec::new();
    for_each_module(&cb.tree, &mut |m| {
        for c in &m.classes {
            scores.push(c.importance);
            for func in &c.methods {
                scores.push(func.importance);
            }
        }
        for func in &m.functions {
            scores.push(func.importance);
        }
    });
    scores
}

// ============================================================================
// Budget enforcement
// ============================================================================

/// What a budgeted render actually did. `omitted` counts symbols whose
/// names do not appear in the output at all.
#[derive(Debug, Clone, Copy)]
pub struct BudgetReport {
    pub level: u8,
    pub omitted: usize,
    pub used_tokens: usize,
}

/// Per-level output size estimates in characters.
///
/// Computed arithmetically from symbol counts and name/signature lengths
/// so the full output never has to be rendered just to measure it. The
/// small fixed sections (header, domain overview, hot paths) ARE rendered
/// because they are bounded in size. Estimates are heuristic; the footer
/// reports actual usage.
fn estimate_levels(cb: &CompressedCodebase, detail: DetailLevel) -> [usize; 4] {
    let median = median_function_importance(cb);
    let fixed_base = cb.fixed_sections(detail, false).len();
    let fixed_hot = cb.fixed_sections(detail, true).len();
    let clusters = if detail == DetailLevel::High {
        cb.clusters_section_len()
    } else {
        0
    };

    // [level0, level1, level2, level3]
    let mut est = [fixed_hot + clusters, fixed_hot, fixed_base, fixed_base];

    for_each_module(&cb.tree, &mut |m| {
        let module_line = m.path.len() + 8;
        est[0] += module_line;
        est[1] += module_line;
        est[2] += module_line;

        let mut sym_count = 0usize;
        let mut sym_char_sum = 0usize;

        for c in &m.classes {
            // class header + inheritance + uses/used_by relationship lines
            let bases: usize = c.bases.iter().map(|b| b.len() + 2).sum();
            let class_full = c.name.len() + bases + 70;
            est[0] += class_full;
            est[1] += class_full;
            sym_count += 1;
            sym_char_sum += c.name.len() + 20;

            for func in &c.methods {
                let full = func.name.len() + func.signature.len() + 26;
                est[0] += full;
                est[1] += if func.importance >= median {
                    full
                } else {
                    func.name.len() + 2
                };
                sym_count += 1;
                sym_char_sum += c.name.len() + func.name.len() + func.signature.len() + 16;
            }
        }
        for func in &m.functions {
            let full = func.name.len() + func.signature.len() + 26;
            est[0] += full;
            est[1] += if func.importance >= median {
                full
            } else {
                func.name.len() + 2
            };
            sym_count += 1;
            sym_char_sum += func.name.len() + func.signature.len() + 16;
        }

        if sym_count > 0 {
            let shown = sym_count.min(5);
            est[2] += (sym_char_sum / sym_count) * shown;
            if sym_count > 5 {
                est[2] += 20; // "+ N more symbols" line
            }
        }
    });

    // Level 3: one line per directory that directly contains modules.
    fn walk_dirs(node: &FolderNode, est3: &mut usize) {
        if !node.modules.is_empty() {
            // path + counts + up to 3 symbol names (~12 chars each)
            *est3 += node.path.len().max(1) + 50 + 36;
        }
        for child in node.children.values() {
            walk_dirs(child, est3);
        }
    }
    walk_dirs(&cb.tree, &mut est[3]);

    est
}

/// Render the codebase within a token budget, degrading detail by
/// importance rather than truncating by position. Picks the most
/// detailed level whose estimated size fits, then appends an explicit
/// budget footer stating what was used and what was omitted.
pub fn render_with_budget(
    cb: &CompressedCodebase,
    detail: DetailLevel,
    budget_tokens: usize,
) -> (String, BudgetReport) {
    // Resolve Auto defensively so level rendering sees a concrete detail.
    let detail = if detail == DetailLevel::Auto {
        let node_count = cb.stats.total_modules + cb.stats.total_classes + cb.stats.total_functions;
        auto_detail_level(node_count)
    } else {
        detail
    };

    let estimates = estimate_levels(cb, detail);
    let budget_chars = budget_tokens.saturating_mul(4);
    let level = estimates
        .iter()
        .position(|&chars| chars <= budget_chars)
        .unwrap_or(3) as u8;

    let (mut content, mut omitted) = cb.to_mu_format_level(detail, level);
    if !content.ends_with('\n') {
        content.push('\n');
    }

    // Even the deepest level can exceed the budget on very large codebases
    // (thousands of modules make the directory skeleton itself huge). The
    // budget is a contract: hard-cut at a line boundary and say so, rather
    // than deliver 5x the asked-for tokens.
    let mut truncated_lines = 0usize;
    if estimate_tokens_chars(&content) > budget_tokens {
        // Reserve room for the footer + truncation notice.
        let keep_chars = budget_tokens.saturating_mul(4).saturating_sub(200);
        let mut kept = String::with_capacity(keep_chars);
        for line in content.lines() {
            if kept.len() + line.len() + 1 > keep_chars {
                truncated_lines += 1;
                continue;
            }
            kept.push_str(line);
            kept.push('\n');
        }
        if truncated_lines > 0 {
            omitted += truncated_lines;
            kept.push_str(&format!(
                "# ... hard-truncated {} more lines to fit the budget; raise budget for more\n",
                truncated_lines
            ));
        }
        content = kept;
    }

    let used_tokens = estimate_tokens_chars(&content);
    content.push_str(&format!(
        "\n# budget: ~{} tokens used of {} | detail level {} | omitted: {} symbols\n",
        used_tokens, budget_tokens, level, omitted
    ));

    (
        content,
        BudgetReport {
            level,
            omitted,
            used_tokens,
        },
    )
}

#[cfg(test)]
mod tests {
    use super::super::loader::build_folder_tree;
    use super::super::models::*;
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
    fn test_estimate_tokens_chars() {
        assert_eq!(estimate_tokens_chars(""), 0);
        assert_eq!(estimate_tokens_chars("abcd"), 1);
        assert_eq!(estimate_tokens_chars("abcde"), 2);
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

    // ------------------------------------------------------------------
    // Percentile helper
    // ------------------------------------------------------------------

    #[test]
    fn test_percentile_empty() {
        let table = PercentileTable::new(vec![]);
        assert_eq!(table.rank(0.5), 0);
    }

    #[test]
    fn test_percentile_single_node() {
        let table = PercentileTable::new(vec![0.7]);
        assert_eq!(table.rank(0.7), 100);
        assert_eq!(table.rank(0.1), 0);
        assert_eq!(table.rank(0.9), 100);
    }

    #[test]
    fn test_percentile_uniform_distribution() {
        let scores: Vec<f32> = (1..=100).map(|i| i as f32 / 100.0).collect();
        let table = PercentileTable::new(scores);
        assert_eq!(table.rank(0.50), 50);
        assert_eq!(table.rank(1.0), 100);
        assert_eq!(table.rank(0.005), 0);
        assert_eq!(table.rank(0.25), 25);
    }

    // ------------------------------------------------------------------
    // Budget degradation
    // ------------------------------------------------------------------

    fn func(name: &str, importance: f32, complexity: u32) -> CompressedFunction {
        CompressedFunction {
            name: name.to_string(),
            qualified_name: name.to_string(),
            signature: "(a: i32, b: i32) -> i32".to_string(),
            complexity,
            call_count: complexity / 2,
            is_hot: complexity > 20,
            docstring: None,
            importance,
        }
    }

    /// 3 modules x 15 functions with spread importances, plus a class.
    /// High-importance functions get names late in the alphabet so that
    /// alphabetical-order survivorship would be detectable.
    fn synthetic_codebase() -> CompressedCodebase {
        let mut modules = Vec::new();
        for (mi, dir) in ["src/api", "src/core", "src/util"].iter().enumerate() {
            let mut functions = Vec::new();
            for fi in 0..14 {
                // aaa_* names carry the LOWEST importance
                functions.push(func(
                    &format!("aaa_minor_{}_{:02}", mi, fi),
                    0.0001 * (fi as f32 + 1.0),
                    2,
                ));
            }
            // z* names carry the HIGHEST importance
            functions.push(func(&format!("zeta_core_{}", mi), 0.9, 25));

            let class = CompressedClass {
                name: format!("Widget{}", mi),
                bases: vec![],
                uses: vec![],
                used_by: vec![],
                methods: vec![func(&format!("yankee_run_{}", mi), 0.5, 10)],
                attributes: vec![],
                importance: 0.4,
            };

            modules.push(CompressedModule {
                name: format!("mod{}", mi),
                path: format!("{}/mod{}.rs", dir, mi),
                classes: vec![class],
                functions,
            });
        }

        let tree = build_folder_tree(&modules);
        CompressedCodebase {
            source: "test".to_string(),
            stats: CodebaseStats {
                total_modules: 3,
                total_classes: 3,
                total_functions: 48,
                total_edges: 0,
                has_graph: true,
            },
            domain: None,
            tree,
            hot_paths: vec![],
            relationship_clusters: vec![],
        }
    }

    #[test]
    fn test_budget_levels_monotonically_smaller() {
        let cb = synthetic_codebase();
        let sizes: Vec<usize> = (0u8..=3)
            .map(|level| cb.to_mu_format_level(DetailLevel::Medium, level).0.len())
            .collect();
        for w in sizes.windows(2) {
            assert!(
                w[1] < w[0],
                "level output sizes must shrink: got {:?}",
                sizes
            );
        }
    }

    #[test]
    fn test_budget_footer_always_present_and_honest() {
        let cb = synthetic_codebase();

        // Huge budget: full output, nothing omitted, footer still present.
        let (content, report) = render_with_budget(&cb, DetailLevel::Medium, 1_000_000);
        assert_eq!(report.level, 0);
        assert_eq!(report.omitted, 0);
        assert!(content.contains("# budget: ~"));
        assert!(content.contains("of 1000000 | detail level 0 | omitted: 0 symbols"));
        // No omission markers when nothing was omitted.
        assert!(!content.contains("more symbols"));

        // Tiny budget: degraded output, omissions reported, never silent.
        let (content, report) = render_with_budget(&cb, DetailLevel::Medium, 100);
        assert!(
            report.level >= 2,
            "tiny budget must degrade, got level {}",
            report.level
        );
        assert!(report.omitted > 0);
        assert!(content.contains(&format!(
            "detail level {} | omitted: {} symbols",
            report.level, report.omitted
        )));
    }

    #[test]
    fn test_budget_respects_budget_when_degrading() {
        let cb = synthetic_codebase();
        let (_, report) = render_with_budget(&cb, DetailLevel::Medium, 400);
        assert!(
            report.level > 0,
            "400-token budget must not fit full output"
        );
        assert!(
            report.used_tokens <= 400 || report.level == 3,
            "used {} tokens with budget 400 at level {}",
            report.used_tokens,
            report.level
        );
    }

    #[test]
    fn test_level2_keeps_top_importance_not_alphabetical() {
        let cb = synthetic_codebase();
        let (content, omitted) = cb.to_mu_format_level(DetailLevel::Medium, 2);

        // Highest-importance symbols survive despite sorting last alphabetically.
        assert!(
            content.contains("zeta_core_0"),
            "top-importance function missing:\n{}",
            content
        );
        assert!(
            content.contains("yankee_run_0"),
            "high-importance method missing:\n{}",
            content
        );
        // Low-importance alphabetically-first functions are cut and counted.
        assert!(!content.contains("aaa_minor_0_00"));
        assert!(omitted > 0);
        assert!(content.contains("more symbols"));
    }

    #[test]
    fn test_level3_directory_skeleton_has_counts_and_top_symbols() {
        let cb = synthetic_codebase();
        let (content, omitted) = cb.to_mu_format_level(DetailLevel::Medium, 3);
        assert!(content.contains("src/api"));
        assert!(content.contains("1 modules"));
        assert!(content.contains("zeta_core_0"));
        assert!(!content.contains("aaa_minor_0_00"));
        assert!(omitted > 0);
    }

    #[test]
    fn test_level1_keeps_all_names() {
        let cb = synthetic_codebase();
        let (content, omitted) = cb.to_mu_format_level(DetailLevel::Medium, 1);
        // Level 1 drops detail for below-median functions but keeps names.
        assert!(content.contains("aaa_minor_0_00"));
        assert!(content.contains("zeta_core_0"));
        assert_eq!(omitted, 0);
    }

    #[test]
    fn test_budget_is_a_hard_ceiling() {
        // A tiny budget against a codebase whose deepest level still exceeds
        // it must hard-truncate, not deliver 5x the asked-for tokens.
        let cb = synthetic_codebase();
        let (content, report) = render_with_budget(&cb, DetailLevel::High, 50);
        assert!(
            report.used_tokens <= 60,
            "used {} tokens against a budget of 50",
            report.used_tokens
        );
        assert!(content.contains("hard-truncated"));
        assert!(content.contains("# budget:"));
    }
}
