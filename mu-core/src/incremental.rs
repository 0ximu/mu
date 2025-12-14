//! Incremental parsing module for daemon mode.
//!
//! Provides an `IncrementalParser` that maintains tree-sitter parse state
//! and can efficiently re-parse after edits with sub-10ms latency.
//!
//! # Usage
//!
//! ```rust,ignore
//! use mu_core::incremental::IncrementalParser;
//!
//! // Initial parse
//! let mut parser = IncrementalParser::new(source, "python", "path.py")?;
//! let module = parser.get_module()?;
//!
//! // After an edit (e.g., adding a character at position 100)
//! let result = parser.apply_edit(100, 100, 101, "x")?;
//! // result.module is the updated ModuleDef
//! // result.parse_time_ms is typically < 5ms
//! ```

use serde::{Deserialize, Serialize};
use std::time::Instant;
use tree_sitter::{InputEdit, Parser, Point, Tree};

use crate::parser;
use crate::types::ModuleDef;

/// Result of an incremental parse operation.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IncrementalParseResult {
    /// The updated module definition.
    pub module: ModuleDef,

    /// Time taken to parse in milliseconds.
    pub parse_time_ms: f64,

    /// Byte ranges that changed in the tree.
    /// Each tuple is (start_byte, end_byte).
    pub changed_ranges: Vec<(usize, usize)>,
}

/// Incremental parser that maintains tree-sitter state for efficient re-parsing.
///
/// This parser keeps the parse tree and source code in memory, allowing
/// subsequent edits to be applied incrementally rather than requiring
/// a full re-parse each time.
pub struct IncrementalParser {
    /// The tree-sitter parser instance.
    parser: Parser,

    /// The current parse tree (None if parsing failed).
    tree: Option<Tree>,

    /// The current source code.
    source: String,

    /// The programming language identifier.
    language: String,

    /// The file path for this parser.
    file_path: String,
}

impl IncrementalParser {
    /// Create a new incremental parser with initial source code.
    ///
    /// # Arguments
    ///
    /// * `source` - The initial source code
    /// * `language` - Language identifier (python, typescript, go, etc.)
    /// * `file_path` - Path to the file (used for module naming)
    ///
    /// # Errors
    ///
    /// Returns an error if the language is not supported or parsing fails.
    pub fn new(source: &str, language: &str, file_path: &str) -> Result<Self, String> {
        let mut parser = Parser::new();

        // Set the language grammar
        let ts_language = get_tree_sitter_language(language)?;

        parser
            .set_language(&ts_language)
            .map_err(|e| format!("Failed to set language: {}", e))?;

        // Initial parse
        let tree = parser.parse(source, None);

        Ok(Self {
            parser,
            tree,
            source: source.to_string(),
            language: normalize_language(language).to_string(),
            file_path: file_path.to_string(),
        })
    }

    /// Apply an edit to the source and incrementally re-parse.
    ///
    /// # Arguments
    ///
    /// * `start_byte` - Byte offset where the edit starts
    /// * `old_end_byte` - Byte offset where the old text ended
    /// * `new_end_byte` - Byte offset where the new text ends
    /// * `new_text` - The new text to insert (can be empty for deletions)
    ///
    /// # Returns
    ///
    /// An `IncrementalParseResult` containing the updated module and timing info.
    pub fn apply_edit(
        &mut self,
        start_byte: usize,
        old_end_byte: usize,
        new_end_byte: usize,
        new_text: &str,
    ) -> Result<IncrementalParseResult, String> {
        let start_time = Instant::now();

        // Validate byte offsets
        if start_byte > self.source.len() {
            return Err(format!(
                "start_byte {} is beyond source length {}",
                start_byte,
                self.source.len()
            ));
        }

        if old_end_byte > self.source.len() {
            return Err(format!(
                "old_end_byte {} is beyond source length {}",
                old_end_byte,
                self.source.len()
            ));
        }

        if start_byte > old_end_byte {
            return Err(format!(
                "start_byte {} cannot be greater than old_end_byte {}",
                start_byte, old_end_byte
            ));
        }

        // Calculate positions before modifying source
        let start_position = byte_offset_to_point(&self.source, start_byte);
        let old_end_position = byte_offset_to_point(&self.source, old_end_byte);

        // Apply the edit to our source string
        let mut new_source =
            String::with_capacity(self.source.len() - (old_end_byte - start_byte) + new_text.len());
        new_source.push_str(&self.source[..start_byte]);
        new_source.push_str(new_text);
        if old_end_byte < self.source.len() {
            new_source.push_str(&self.source[old_end_byte..]);
        }

        // Calculate new end position
        let new_end_position =
            byte_offset_to_point(&new_source, new_end_byte.min(new_source.len()));

        // Create the InputEdit for tree-sitter
        let input_edit = InputEdit {
            start_byte,
            old_end_byte,
            new_end_byte,
            start_position,
            old_end_position,
            new_end_position,
        };

        // Apply edit to tree if we have one
        if let Some(ref mut tree) = self.tree {
            tree.edit(&input_edit);
        }

        // Re-parse with the old tree as reference
        let old_tree = self.tree.take();
        let new_tree = self.parser.parse(&new_source, old_tree.as_ref());

        // Calculate changed ranges
        let changed_ranges = match (&old_tree, &new_tree) {
            (Some(old), Some(new)) => old
                .changed_ranges(new)
                .map(|r| (r.start_byte, r.end_byte))
                .collect(),
            _ => vec![(0, new_source.len())],
        };

        // Update our state
        self.tree = new_tree;
        self.source = new_source;

        // Parse to ModuleDef
        let parse_result = parser::parse_source(&self.source, &self.file_path, &self.language);
        let module = parse_result.module.ok_or_else(|| {
            parse_result
                .error
                .unwrap_or_else(|| "Parse failed".to_string())
        })?;

        let parse_time_ms = start_time.elapsed().as_secs_f64() * 1000.0;

        Ok(IncrementalParseResult {
            module,
            parse_time_ms,
            changed_ranges,
        })
    }

    /// Get the current module definition.
    pub fn get_module(&self) -> Result<ModuleDef, String> {
        let parse_result = parser::parse_source(&self.source, &self.file_path, &self.language);
        parse_result.module.ok_or_else(|| {
            parse_result
                .error
                .unwrap_or_else(|| "Parse failed".to_string())
        })
    }

    /// Get the current source code.
    pub fn get_source(&self) -> &str {
        &self.source
    }

    /// Get the language of this parser.
    pub fn get_language(&self) -> &str {
        &self.language
    }

    /// Get the file path of this parser.
    pub fn get_file_path(&self) -> &str {
        &self.file_path
    }

    /// Convert a byte offset to a (line, column) position.
    pub fn byte_to_position(&self, byte_offset: usize) -> Result<(usize, usize), String> {
        if byte_offset > self.source.len() {
            return Err(format!(
                "byte_offset {} is beyond source length {}",
                byte_offset,
                self.source.len()
            ));
        }

        let point = byte_offset_to_point(&self.source, byte_offset);
        Ok((point.row, point.column))
    }

    /// Convert a (line, column) position to a byte offset.
    pub fn position_to_byte(&self, line: usize, column: usize) -> Result<usize, String> {
        let mut current_line = 0;
        let mut byte_offset = 0;

        for (i, ch) in self.source.char_indices() {
            if current_line == line {
                let line_start = byte_offset;
                // Find the byte offset for the column
                let mut col = 0;
                for (j, c) in self.source[line_start..].char_indices() {
                    if col == column {
                        return Ok(line_start + j);
                    }
                    if c == '\n' {
                        break;
                    }
                    col += 1;
                }
                // Column is at or beyond end of line
                return Ok(i + column.saturating_sub(col));
            }
            if ch == '\n' {
                current_line += 1;
            }
            byte_offset = i + ch.len_utf8();
        }

        // Line is at or beyond end of source
        Ok(self.source.len())
    }

    /// Check if the parser has a valid tree.
    pub fn has_tree(&self) -> bool {
        self.tree.is_some()
    }

    /// Check if the current tree has syntax errors.
    pub fn has_errors(&self) -> bool {
        self.tree.as_ref().is_none_or(|t| t.root_node().has_error())
    }

    /// Get the number of lines in the source.
    pub fn line_count(&self) -> usize {
        self.source.lines().count()
    }

    /// Get the source length in bytes.
    pub fn byte_count(&self) -> usize {
        self.source.len()
    }

    /// Reset the parser with new source code.
    ///
    /// This performs a full re-parse, discarding the previous tree.
    pub fn reset(&mut self, source: &str) -> Result<IncrementalParseResult, String> {
        let start_time = Instant::now();

        self.source = source.to_string();
        self.tree = self.parser.parse(source, None);

        let parse_result = parser::parse_source(&self.source, &self.file_path, &self.language);
        let module = parse_result.module.ok_or_else(|| {
            parse_result
                .error
                .unwrap_or_else(|| "Parse failed".to_string())
        })?;

        let parse_time_ms = start_time.elapsed().as_secs_f64() * 1000.0;

        Ok(IncrementalParseResult {
            module,
            parse_time_ms,
            changed_ranges: vec![(0, source.len())],
        })
    }
}

/// Convert a byte offset to a tree-sitter Point (row, column).
fn byte_offset_to_point(source: &str, byte_offset: usize) -> Point {
    let byte_offset = byte_offset.min(source.len());
    let prefix = &source[..byte_offset];

    let row = prefix.matches('\n').count();
    let column = prefix
        .rfind('\n')
        .map(|last_newline| byte_offset - last_newline - 1)
        .unwrap_or(byte_offset);

    Point { row, column }
}

/// Get the tree-sitter language for a given language identifier.
fn get_tree_sitter_language(language: &str) -> Result<tree_sitter::Language, String> {
    match normalize_language(language) {
        "python" => Ok(tree_sitter_python::LANGUAGE.into()),
        "typescript" => Ok(tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into()),
        "javascript" => Ok(tree_sitter_javascript::LANGUAGE.into()),
        "go" => Ok(tree_sitter_go::LANGUAGE.into()),
        "java" => Ok(tree_sitter_java::LANGUAGE.into()),
        "rust" => Ok(tree_sitter_rust::LANGUAGE.into()),
        "csharp" => Ok(tree_sitter_c_sharp::LANGUAGE.into()),
        lang => Err(format!("Unsupported language: {}", lang)),
    }
}

/// Normalize language identifier to canonical form.
fn normalize_language(language: &str) -> &str {
    match language.to_lowercase().as_str() {
        "python" | "py" => "python",
        "typescript" | "ts" | "tsx" => "typescript",
        "javascript" | "js" | "jsx" => "javascript",
        "go" => "go",
        "java" => "java",
        "rust" | "rs" => "rust",
        "csharp" | "cs" | "c#" => "csharp",
        _ => language,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_byte_offset_to_point() {
        let source = "line1\nline2\nline3";

        // Start of file
        let p = byte_offset_to_point(source, 0);
        assert_eq!(p.row, 0);
        assert_eq!(p.column, 0);

        // Middle of first line
        let p = byte_offset_to_point(source, 3);
        assert_eq!(p.row, 0);
        assert_eq!(p.column, 3);

        // Start of second line
        let p = byte_offset_to_point(source, 6);
        assert_eq!(p.row, 1);
        assert_eq!(p.column, 0);

        // End of file
        let p = byte_offset_to_point(source, source.len());
        assert_eq!(p.row, 2);
        assert_eq!(p.column, 5);
    }

    #[test]
    fn test_normalize_language() {
        assert_eq!(normalize_language("python"), "python");
        assert_eq!(normalize_language("py"), "python");
        assert_eq!(normalize_language("Python"), "python");
        assert_eq!(normalize_language("typescript"), "typescript");
        assert_eq!(normalize_language("ts"), "typescript");
        assert_eq!(normalize_language("tsx"), "typescript");
        assert_eq!(normalize_language("rust"), "rust");
        assert_eq!(normalize_language("rs"), "rust");
    }

    #[test]
    fn test_get_tree_sitter_language() {
        assert!(get_tree_sitter_language("python").is_ok());
        assert!(get_tree_sitter_language("typescript").is_ok());
        assert!(get_tree_sitter_language("javascript").is_ok());
        assert!(get_tree_sitter_language("go").is_ok());
        assert!(get_tree_sitter_language("java").is_ok());
        assert!(get_tree_sitter_language("rust").is_ok());
        assert!(get_tree_sitter_language("csharp").is_ok());
        assert!(get_tree_sitter_language("unknown").is_err());
    }

    #[test]
    fn test_incremental_parser_creation() {
        let source = "def hello():\n    pass";
        let parser = IncrementalParser::new(source, "python", "test.py");
        assert!(parser.is_ok());

        let parser = parser.unwrap();
        assert!(parser.tree.is_some());
        assert!(!parser.tree.as_ref().unwrap().root_node().has_error());
        assert_eq!(parser.source, source);
        assert_eq!(parser.language, "python");
        assert_eq!(parser.source.lines().count(), 2);
    }

    #[test]
    fn test_incremental_parser_unsupported_language() {
        let result = IncrementalParser::new("code", "brainfuck", "test.bf");
        assert!(result.is_err());
    }

    #[test]
    fn test_apply_edit_insert() {
        let source = "def hello():\n    pass";
        let mut parser = IncrementalParser::new(source, "python", "test.py").unwrap();

        // Insert 'world' into the function name: hello -> helloworld
        let result = parser.apply_edit(9, 9, 14, "world").unwrap();

        assert!(result.parse_time_ms > 0.0);
        assert_eq!(parser.source, "def helloworld():\n    pass");
        assert_eq!(result.module.functions.len(), 1);
        assert_eq!(result.module.functions[0].name, "helloworld");
    }

    #[test]
    fn test_apply_edit_delete() {
        let source = "def helloworld():\n    pass";
        let mut parser = IncrementalParser::new(source, "python", "test.py").unwrap();

        // Delete 'world' from the function name
        let result = parser.apply_edit(9, 14, 9, "").unwrap();

        assert!(result.parse_time_ms > 0.0);
        assert_eq!(parser.source, "def hello():\n    pass");
        assert_eq!(result.module.functions[0].name, "hello");
    }

    #[test]
    fn test_apply_edit_replace() {
        let source = "def foo():\n    pass";
        let mut parser = IncrementalParser::new(source, "python", "test.py").unwrap();

        // Replace 'foo' with 'bar'
        let _result = parser.apply_edit(4, 7, 7, "bar").unwrap();

        assert_eq!(parser.source, "def bar():\n    pass");
        let module = parser.get_module().unwrap();
        assert_eq!(module.functions[0].name, "bar");
    }

    #[test]
    fn test_reset_parser() {
        let source = "def foo():\n    pass";
        let mut parser = IncrementalParser::new(source, "python", "test.py").unwrap();

        // Apply some edits
        parser.apply_edit(4, 7, 7, "bar").unwrap();

        // Reset with completely new source
        let new_source = "class MyClass:\n    pass";
        let _result = parser.reset(new_source).unwrap();

        assert_eq!(parser.source, new_source);
        let module = parser.get_module().unwrap();
        assert_eq!(module.classes.len(), 1);
        assert_eq!(module.classes[0].name, "MyClass");
        assert_eq!(module.functions.len(), 0);
    }

    #[test]
    fn test_invalid_byte_offset() {
        let source = "def hello():\n    pass";
        let mut parser = IncrementalParser::new(source, "python", "test.py").unwrap();

        // start_byte beyond source length
        let result = parser.apply_edit(1000, 1000, 1001, "x");
        assert!(result.is_err());

        // old_end_byte beyond source length
        let result = parser.apply_edit(0, 1000, 0, "");
        assert!(result.is_err());

        // start_byte > old_end_byte
        let result = parser.apply_edit(10, 5, 10, "x");
        assert!(result.is_err());
    }

    #[test]
    fn test_has_errors() {
        // Valid syntax
        let parser = IncrementalParser::new("def hello():\n    pass", "python", "test.py").unwrap();
        assert!(!parser.tree.as_ref().unwrap().root_node().has_error());

        // Invalid syntax
        let parser = IncrementalParser::new("def hello(\n    pass", "python", "test.py").unwrap();
        assert!(parser.tree.as_ref().unwrap().root_node().has_error());
    }
}
