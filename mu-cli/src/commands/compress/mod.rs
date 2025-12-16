//! MU compress command - Compress codebase into hierarchical MU sigil format
//!
//! Produces a well-structured, relationship-rich representation of the codebase
//! optimized for LLM comprehension.

mod formatter;
mod loader;
mod models;

pub use models::{CompressResult, DetailLevel};

use crate::output::{Output, OutputFormat};
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

/// Run the compress command
pub async fn run(
    path: &str,
    output: Option<&str>,
    detail: &str,
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

    // Generate output
    let content = codebase.to_mu_format(detail_level);

    // Write to file or stdout
    if let Some(output_path) = output {
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
        content: if output.is_some() {
            format!(
                "Compressed {} modules, {} classes, {} functions",
                codebase.stats.total_modules,
                codebase.stats.total_classes,
                codebase.stats.total_functions
            )
        } else {
            content
        },
        detail_level: format!("{:?}", detail_level),
    };

    Output::new(result, format).render()
}
