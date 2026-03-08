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

/// Run the compress command
pub async fn run(
    path: &str,
    output: Option<&str>,
    detail: &str,
    max_tokens: Option<usize>,
    format: OutputFormat,
) -> Result<()> {
    let detail_level = DetailLevel::from_str(detail).unwrap_or(DetailLevel::Medium);

    let source_path = Path::new(path)
        .canonicalize()
        .with_context(|| format!("Path not found: {}", path))?;

    // Try to load from database first
    let mut codebase = if let Some(db_path) = loader::find_mubase(path) {
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

    // Apply token budget if specified
    if let Some(budget) = max_tokens {
        // Collect all modules from the folder tree
        let mut all_modules = collect_modules(&codebase.tree);
        let prioritized = budget::enforce_budget(&mut all_modules, budget);

        // Rebuild tree from prioritized modules
        codebase.tree = loader::build_folder_tree(&prioritized);
        eprintln!(
            "{} Token budget: {} max, kept {} of {} modules",
            "INFO:".cyan(),
            budget,
            prioritized.len(),
            all_modules.len()
        );
    }

    // Generate output
    let content = codebase.to_mu_format(resolved_detail);
    let estimated_tokens = Some(budget::estimate_tokens(&content));

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

/// Recursively collect all modules from a folder tree
fn collect_modules(node: &models::FolderNode) -> Vec<models::CompressedModule> {
    let mut modules = node.modules.clone();
    for child in node.children.values() {
        modules.extend(collect_modules(child));
    }
    modules
}
