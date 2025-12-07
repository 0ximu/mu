//! Multi-language AST parsing module.
//!
//! Provides parallel parsing of source files using tree-sitter grammars.
//! Each language has its own extractor that converts tree-sitter AST
//! to the common `ModuleDef` structure.

use rayon::prelude::*;

use crate::types::{FileInfo, ParseResult};

pub mod python;
pub mod typescript;
pub mod go;
pub mod java;
pub mod rust_lang;
pub mod csharp;

mod helpers;

/// Parse multiple files in parallel using rayon.
///
/// Files are processed concurrently, with the number of threads controlled
/// by the thread pool configuration. Source code is provided in FileInfo,
/// allowing the caller to handle file reading.
pub fn parse_files_parallel(
    file_infos: Vec<FileInfo>,
    num_threads: Option<usize>,
) -> Vec<ParseResult> {
    // Configure thread pool if specified
    let pool = match num_threads {
        Some(n) if n > 0 => {
            rayon::ThreadPoolBuilder::new()
                .num_threads(n)
                .build()
                .ok()
        }
        _ => None,
    };

    let parse_fn = |info: &FileInfo| -> ParseResult {
        parse_source(&info.source, &info.path, &info.language)
    };

    match pool {
        Some(pool) => pool.install(|| file_infos.par_iter().map(parse_fn).collect()),
        None => file_infos.par_iter().map(parse_fn).collect(),
    }
}

/// Parse source code for a specific language.
pub fn parse_source(source: &str, path: &str, language: &str) -> ParseResult {
    let result = match language.to_lowercase().as_str() {
        "python" | "py" => python::parse(source, path),
        "typescript" | "ts" | "tsx" => typescript::parse(source, path, false),
        "javascript" | "js" | "jsx" => typescript::parse(source, path, true),
        "go" => go::parse(source, path),
        "java" => java::parse(source, path),
        "rust" | "rs" => rust_lang::parse(source, path),
        "csharp" | "cs" | "c#" => csharp::parse(source, path),
        _ => Err(format!("Unsupported language: {}", language)),
    };

    match result {
        Ok(module) => ParseResult::ok(module),
        Err(e) => ParseResult::err(e),
    }
}

/// Get supported languages.
pub fn supported_languages() -> &'static [&'static str] {
    &[
        "python", "py",
        "typescript", "ts", "tsx",
        "javascript", "js", "jsx",
        "go",
        "java",
        "rust", "rs",
        "csharp", "cs", "c#",
    ]
}
