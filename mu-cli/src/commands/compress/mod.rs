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
        detail_level: format!("{:?}", detail_level),
    };

    Output::new(result, format).render()
}
