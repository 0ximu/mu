//! MU Rust Core - High-performance parsing and transformation engine.
//!
//! This crate provides the core functionality for MU (Machine Understanding),
//! a semantic compression tool for codebases. It exposes Python bindings via PyO3.
//!
//! # Features
//!
//! - **Parallel parsing**: Parse multiple files concurrently using Rayon
//! - **Multi-language support**: Python, TypeScript, JavaScript, Go, Java, Rust, C#
//! - **Cyclomatic complexity**: Calculate code complexity metrics
//! - **Secret redaction**: Detect and redact sensitive information
//! - **Multiple export formats**: MU, JSON, Markdown
//!
//! # Usage from Python
//!
//! ```python
//! from mu import _core
//!
//! # Parse files in parallel
//! results = _core.parse_files(file_infos, num_threads=4)
//!
//! # Export to MU format
//! mu_output = _core.export_mu(modules, config)
//! ```

use pyo3::prelude::*;

pub mod differ;
pub mod exporter;
pub mod graph;
pub mod incremental;
pub mod parser;
pub mod reducer;
pub mod scanner;
pub mod security;
pub mod types;

use types::*;

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
#[pyfunction]
#[pyo3(signature = (file_infos, num_threads=None))]
fn parse_files(
    py: Python<'_>,
    file_infos: Vec<FileInfo>,
    num_threads: Option<usize>,
) -> PyResult<Vec<ParseResult>> {
    // Release GIL for parallel execution
    Ok(py.allow_threads(|| parser::parse_files_parallel(file_infos, num_threads)))
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
#[pyfunction]
#[pyo3(signature = (source, file_path, language))]
fn parse_file(source: &str, file_path: &str, language: &str) -> PyResult<ParseResult> {
    Ok(parser::parse_source(source, file_path, language))
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
#[pyfunction]
fn calculate_complexity(source: &str, language: &str) -> PyResult<u32> {
    Ok(reducer::complexity::calculate(source, language))
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
#[pyfunction]
fn find_secrets(text: &str) -> PyResult<Vec<SecretMatch>> {
    Ok(security::patterns::find_secrets(text)
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
        .collect())
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
#[pyfunction]
fn redact_secrets(text: &str) -> PyResult<String> {
    Ok(security::redact::redact(text))
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
#[pyfunction]
fn export_mu(module: &ModuleDef) -> PyResult<String> {
    Ok(exporter::mu_format::export(module))
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
/// JSON string.
#[pyfunction]
#[pyo3(signature = (module, pretty=false))]
fn export_json(module: &ModuleDef, pretty: bool) -> PyResult<String> {
    let json = if pretty {
        serde_json::to_string_pretty(module)
    } else {
        serde_json::to_string(module)
    };
    json.map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
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
#[pyfunction]
fn export_markdown(module: &ModuleDef) -> PyResult<String> {
    Ok(exporter::markdown::export(module))
}

/// Get the version of mu-core.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// Python module definition.
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Types
    m.add_class::<ParameterDef>()?;
    m.add_class::<FunctionDef>()?;
    m.add_class::<ClassDef>()?;
    m.add_class::<ImportDef>()?;
    m.add_class::<ModuleDef>()?;
    m.add_class::<FileInfo>()?;
    m.add_class::<ParseResult>()?;
    m.add_class::<ExportConfig>()?;
    m.add_class::<RedactedSecret>()?;
    m.add_class::<SecretMatch>()?;
    m.add_class::<graph::GraphEngine>()?;

    // Scanner types
    m.add_class::<scanner::ScannedFile>()?;
    m.add_class::<scanner::ScanResult>()?;

    // Differ types
    m.add_class::<differ::EntityChange>()?;
    m.add_class::<differ::DiffSummary>()?;
    m.add_class::<differ::SemanticDiffResult>()?;

    // Incremental parser types
    m.add_class::<incremental::IncrementalParser>()?;
    m.add_class::<incremental::IncrementalParseResult>()?;

    // Functions
    m.add_function(wrap_pyfunction!(parse_files, m)?)?;
    m.add_function(wrap_pyfunction!(parse_file, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_complexity, m)?)?;
    m.add_function(wrap_pyfunction!(find_secrets, m)?)?;
    m.add_function(wrap_pyfunction!(redact_secrets, m)?)?;
    m.add_function(wrap_pyfunction!(export_mu, m)?)?;
    m.add_function(wrap_pyfunction!(export_json, m)?)?;
    m.add_function(wrap_pyfunction!(export_markdown, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;

    // Scanner function
    m.add_function(wrap_pyfunction!(scanner::scan_directory, m)?)?;

    // Differ functions
    m.add_function(wrap_pyfunction!(differ::semantic_diff, m)?)?;
    m.add_function(wrap_pyfunction!(differ::semantic_diff_files, m)?)?;

    Ok(())
}
