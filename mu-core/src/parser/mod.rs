//! Multi-language AST parsing module.
//!
//! Provides parallel parsing of source files using tree-sitter grammars.
//! Each language has its own extractor that converts tree-sitter AST
//! to the common `ModuleDef` structure.

use rayon::prelude::*;

use crate::types::{FileInfo, ParseResult};

pub mod csharp;
pub mod go;
pub mod java;
pub mod python;
pub mod rust_lang;
pub mod typescript;

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
        Some(n) if n > 0 => rayon::ThreadPoolBuilder::new().num_threads(n).build().ok(),
        _ => None,
    };

    let parse_fn =
        |info: &FileInfo| -> ParseResult { parse_source(&info.source, &info.path, &info.language) };

    match pool {
        Some(pool) => pool.install(|| file_infos.par_iter().map(parse_fn).collect()),
        None => file_infos.par_iter().map(parse_fn).collect(),
    }
}

/// Parse source code for a specific language.
pub fn parse_source(source: &str, path: &str, language: &str) -> ParseResult {
    let result = match language.to_lowercase().as_str() {
        "python" | "py" => python::parse(source, path),
        "typescript" | "ts" => typescript::parse(source, path, typescript::Dialect::TypeScript),
        "tsx" => typescript::parse(source, path, typescript::Dialect::Tsx),
        "javascript" | "js" | "jsx" => {
            typescript::parse(source, path, typescript::Dialect::JavaScript)
        }
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
        "python",
        "py",
        "typescript",
        "ts",
        "tsx",
        "javascript",
        "js",
        "jsx",
        "go",
        "java",
        "rust",
        "rs",
        "csharp",
        "cs",
        "c#",
    ]
}

#[cfg(test)]
mod grammar_contract {
    /// Every grammar we ship must load into the pinned tree-sitter core.
    /// A grammar built for a newer ABI fails `set_language`, and bootstrap
    /// would otherwise index that language as empty without a word.
    #[test]
    fn every_grammar_loads_into_the_pinned_tree_sitter_core() {
        let grammars: Vec<(&str, tree_sitter::Language)> = vec![
            ("python", tree_sitter_python::LANGUAGE.into()),
            (
                "typescript",
                tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
            ),
            ("tsx", tree_sitter_typescript::LANGUAGE_TSX.into()),
            ("javascript", tree_sitter_javascript::LANGUAGE.into()),
            ("go", tree_sitter_go::LANGUAGE.into()),
            ("java", tree_sitter_java::LANGUAGE.into()),
            ("rust", tree_sitter_rust::LANGUAGE.into()),
            ("csharp", tree_sitter_c_sharp::LANGUAGE.into()),
        ];
        let mut parser = tree_sitter::Parser::new();
        for (name, lang) in grammars {
            parser.set_language(&lang).unwrap_or_else(|e| {
                panic!("{name} grammar does not load into this tree-sitter core: {e}")
            });
        }
    }

    /// The C# walker must extract a class from the smallest real-world shape
    /// gateway uses: file-scoped namespace, primary constructor, expression body.
    #[test]
    fn csharp_file_scoped_namespace_with_primary_ctor_is_not_empty() {
        let src = "namespace A;\npublic class C(int x)\n{\n    public int F() => x + 1;\n}\n";
        let r = super::parse_source(src, "C.cs", "csharp");
        assert!(r.success, "parse failed: {:?}", r.error);
        let m = r.module.expect("module");
        assert_eq!(
            m.classes.len(),
            1,
            "expected one class, got {:?}",
            m.classes
        );
        assert_eq!(m.classes[0].methods.len(), 1);
    }
}
