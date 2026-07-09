//! MU compress command - Compress codebase into hierarchical MU sigil format
//!
//! Produces a well-structured, relationship-rich representation of the codebase
//! optimized for LLM comprehension.

pub mod budget;
mod formatter;
mod loader;
mod models;

pub use models::{CompressResult, DetailLevel};

use crate::output::{Output, OutputFormat};
use anyhow::{Context, Result};
use chrono::Local;
use colored::Colorize;
use std::path::Path;

/// Add timestamp to output filename: `foo.mu` → `foo-01082026.mu`
fn stamp_filename(path: &str) -> String {
    let timestamp = Local::now().format("%m%d%Y").to_string();
    if let Some(dot_pos) = path.rfind('.') {
        format!("{}-{}{}", &path[..dot_pos], timestamp, &path[dot_pos..])
    } else {
        format!("{}-{}", path, timestamp)
    }
}

/// Budget-bounded overview for the MCP server: loads from an existing
/// MUbase connection, auto-selects detail from node count, and renders
/// within `budget_tokens` using importance-ordered graceful degradation.
/// The returned content always ends with an explicit budget footer.
pub fn overview_from_mubase(
    mubase: &crate::engine::storage::MUbase,
    source: &str,
    budget_tokens: usize,
) -> Result<String> {
    let codebase = mubase.with_connection(|conn| loader::load_from_connection(conn, source))?;
    let node_count = codebase.stats.total_modules
        + codebase.stats.total_classes
        + codebase.stats.total_functions;
    let detail = budget::auto_detail_level(node_count);
    let (content, _report) = budget::render_with_budget(&codebase, detail, budget_tokens);
    Ok(content)
}

/// Run the compress command
pub async fn run(
    path: &str,
    output: Option<&str>,
    detail: &str,
    budget_tokens: Option<usize>,
    format: OutputFormat,
) -> Result<()> {
    let detail_level = DetailLevel::from_str(detail).unwrap_or(DetailLevel::Medium);

    let source_path = Path::new(path)
        .canonicalize()
        .with_context(|| format!("Path not found: {}", path))?;

    // Try to load from database first
    let codebase = if let Some(db_path) = loader::find_mubase(path) {
        eprintln!(
            "{} Using graph database for rich relationships",
            "INFO:".cyan()
        );
        loader::load_from_database(&db_path, &source_path.to_string_lossy())?
    } else {
        eprintln!(
            "{} No database found, parsing source directly (no call counts/relationships)",
            "INFO:".yellow()
        );
        eprintln!(
            "{} Run `mu bootstrap` first for richer output",
            "HINT:".dimmed()
        );
        loader::load_from_source(&source_path)?
    };

    // Resolve auto detail level based on node count
    let resolved_detail = if detail_level == DetailLevel::Auto {
        let node_count = codebase.stats.total_modules
            + codebase.stats.total_classes
            + codebase.stats.total_functions;
        let auto = budget::auto_detail_level(node_count);
        eprintln!(
            "{} Auto-selected detail level: {:?} ({} nodes)",
            "INFO:".cyan(),
            auto,
            node_count
        );
        auto
    } else {
        detail_level
    };

    // Generate output. With a budget, degrade gracefully by importance
    // (the content then ends with an explicit budget footer).
    let (content, estimated_tokens) = match budget_tokens {
        Some(b) => {
            let (content, report) = budget::render_with_budget(&codebase, resolved_detail, b);
            eprintln!(
                "{} Budget {} tokens: detail level {}, ~{} tokens, {} symbols omitted",
                "INFO:".cyan(),
                b,
                report.level,
                report.used_tokens,
                report.omitted
            );
            (content, Some(report.used_tokens))
        }
        None => {
            let content = codebase.to_mu_format(resolved_detail);
            let est = Some(budget::estimate_tokens(&content));
            (content, est)
        }
    };

    // Write to file or stdout
    let stamped_output = output.map(stamp_filename);
    if let Some(ref output_path) = stamped_output {
        std::fs::write(output_path, &content)
            .with_context(|| format!("Failed to write to: {}", output_path))?;
        eprintln!(
            "{} Written to {}",
            "SUCCESS:".green().bold(),
            output_path.cyan()
        );
    }

    let result = CompressResult {
        source: codebase.source,
        stats: codebase.stats,
        content: if stamped_output.is_some() {
            format!(
                "Compressed {} modules, {} classes, {} functions",
                codebase.stats.total_modules,
                codebase.stats.total_classes,
                codebase.stats.total_functions
            )
        } else {
            content
        },
        detail_level: format!("{:?}", resolved_detail),
        estimated_tokens,
    };

    Output::new(result, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::storage::{Edge, MUbase, Node};

    /// Tempdir MUbase with 20 function nodes of varied importance.
    /// High-importance functions get names late in the alphabet so that
    /// alphabetical selection (the old LIMIT 500 bug) would be caught.
    fn fixture_db() -> MUbase {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("test.mubase");
        std::mem::forget(dir);
        let db = MUbase::open(&db_path).unwrap();

        let mut nodes = vec![Node::module("src/lib.rs")];
        let mut edges = Vec::new();

        for i in 0..18 {
            let mut node = Node::function(
                "src/lib.rs",
                &format!("aaa_util_{:02}", i),
                None,
                1,
                5,
                1,
                None,
            );
            node.importance_score = 0.001 * (i as f32 + 1.0);
            edges.push(Edge::contains("mod:src/lib.rs", &node.id));
            nodes.push(node);
        }
        for (name, importance) in [("zeta_core", 0.95f32), ("yankee_dispatch", 0.85)] {
            let mut node = Node::function("src/lib.rs", name, None, 1, 30, 25, None);
            node.importance_score = importance;
            edges.push(Edge::contains("mod:src/lib.rs", &node.id));
            nodes.push(node);
        }

        db.insert_nodes(&nodes).unwrap();
        db.insert_edges(&edges).unwrap();
        db
    }

    #[test]
    fn test_overview_small_budget_keeps_top_importance_not_alphabetical() {
        let db = fixture_db();
        let content = overview_from_mubase(&db, "test", 150).unwrap();

        // Survivors are the highest-importance symbols, not the
        // alphabetically first ones.
        assert!(
            content.contains("zeta_core"),
            "missing top symbol:\n{}",
            content
        );
        assert!(content.contains("yankee_dispatch"));
        assert!(!content.contains("aaa_util_00"));

        // The budget footer is always present and states the omission.
        assert!(content.contains("# budget: ~"));
        assert!(!content.contains("omitted: 0 symbols"));

        // Importance renders as a percentile, not a raw 0.00 score.
        assert!(
            content.contains("imp=p"),
            "missing percentile display:\n{}",
            content
        );
    }

    #[test]
    fn test_overview_large_budget_keeps_everything_and_says_so() {
        let db = fixture_db();
        let content = overview_from_mubase(&db, "test", 1_000_000).unwrap();

        assert!(content.contains("aaa_util_00"));
        assert!(content.contains("zeta_core"));
        assert!(content.contains("omitted: 0 symbols"));
        assert!(!content.contains("more symbols"));
    }
}
