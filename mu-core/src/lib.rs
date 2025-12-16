//! MU Rust Core - High-performance parsing and transformation engine.
//!
//! This crate provides the core functionality for MU (Machine Understanding),
//! a semantic compression tool for codebases.
//!
//! # Features
//!
//! - **Parallel parsing**: Parse multiple files concurrently using Rayon
//! - **Multi-language support**: Python, TypeScript, JavaScript, Go, Java, Rust, C#
//! - **Cyclomatic complexity**: Calculate code complexity metrics
//! - **Secret redaction**: Detect and redact sensitive information
//! - **Multiple export formats**: MU, JSON, Markdown

pub mod differ;
pub mod exporter;
pub mod graph;
pub mod incremental;
pub mod parser;
pub mod reducer;
pub mod scanner;
pub mod security;
pub mod types;

pub use types::*;

/// Parse multiple files in parallel.
///
/// # Arguments
///
/// * `file_infos` - List of FileInfo objects describing files to parse
/// * `num_threads` - Optional number of threads (defaults to number of CPUs)
///
/// # Returns
///
/// List of ParseResult objects, one per input file.
pub fn parse_files(file_infos: Vec<FileInfo>, num_threads: Option<usize>) -> Vec<ParseResult> {
    parser::parse_files_parallel(file_infos, num_threads)
}

/// Parse a single file from source.
///
/// # Arguments
///
/// * `source` - Source code content
/// * `file_path` - Path to the file (for naming)
/// * `language` - Language identifier (python, typescript, javascript, go, java, rust, csharp)
///
/// # Returns
///
/// ParseResult with the parsed ModuleDef or error.
pub fn parse_file(source: &str, file_path: &str, language: &str) -> ParseResult {
    parser::parse_source(source, file_path, language)
}

/// Calculate cyclomatic complexity for a code snippet.
///
/// # Arguments
///
/// * `source` - Source code
/// * `language` - Language identifier
///
/// # Returns
///
/// Complexity score (minimum 1).
pub fn calculate_complexity(source: &str, language: &str) -> u32 {
    reducer::complexity::calculate(source, language)
}

/// Find secrets in text.
///
/// # Arguments
///
/// * `text` - Text to scan for secrets
///
/// # Returns
///
/// List of SecretMatch objects.
pub fn find_secrets(text: &str) -> Vec<SecretMatch> {
    security::patterns::find_secrets(text)
        .into_iter()
        .map(|(name, start, end)| {
            let (line, column) = security::redact::position_to_line_col(text, start);
            SecretMatch {
                pattern_name: name.to_string(),
                start,
                end,
                line,
                column,
            }
        })
        .collect()
}

/// Redact secrets from source code.
///
/// # Arguments
///
/// * `text` - Text to redact
///
/// # Returns
///
/// Text with secrets replaced by [REDACTED].
pub fn redact_secrets(text: &str) -> String {
    security::redact::redact(text)
}

/// Export module to MU format.
///
/// # Arguments
///
/// * `module` - ModuleDef to export
///
/// # Returns
///
/// MU format string.
pub fn export_mu(module: &ModuleDef) -> String {
    exporter::mu_format::export(module)
}

/// Export module to JSON format.
///
/// # Arguments
///
/// * `module` - ModuleDef to export
/// * `pretty` - Whether to pretty-print
///
/// # Returns
///
/// JSON string or error.
pub fn export_json(module: &ModuleDef, pretty: bool) -> Result<String, serde_json::Error> {
    if pretty {
        serde_json::to_string_pretty(module)
    } else {
        serde_json::to_string(module)
    }
}

/// Export module to Markdown format.
///
/// # Arguments
///
/// * `module` - ModuleDef to export
///
/// # Returns
///
/// Markdown string.
pub fn export_markdown(module: &ModuleDef) -> String {
    exporter::markdown::export(module)
}

/// Get the version of mu-core.
pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}
