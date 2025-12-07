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

use pyo3::prelude::*;
use pyo3::types::PyList;
use serde::{Deserialize, Serialize};
use std::time::Instant;
use tree_sitter::{InputEdit, Parser, Point, Tree};

use crate::parser;
use crate::types::ModuleDef;

/// Result of an incremental parse operation.
#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IncrementalParseResult {
    /// The updated module definition.
    #[pyo3(get)]
    pub module: ModuleDef,

    /// Time taken to parse in milliseconds.
    #[pyo3(get)]
    pub parse_time_ms: f64,

    /// Byte ranges that changed in the tree.
    /// Each tuple is (start_byte, end_byte).
    pub changed_ranges: Vec<(usize, usize)>,
}

#[pymethods]
impl IncrementalParseResult {
    /// Get changed ranges as a Python list of tuples.
    #[getter]
    fn get_changed_ranges(&self, py: Python<'_>) -> PyResult<PyObject> {
        let list = PyList::empty_bound(py);
        for (start, end) in &self.changed_ranges {
            list.append((*start, *end))?;
        }
        Ok(list.into())
    }

    /// Convert to Python dict.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = pyo3::types::PyDict::new_bound(py);
        // Serialize module to JSON and back to get a Python dict
        let module_json = serde_json::to_string(&self.module)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let json_module = py.import_bound("json")?;
        let module_dict = json_module.call_method1("loads", (module_json,))?;
        dict.set_item("module", module_dict)?;
        dict.set_item("parse_time_ms", self.parse_time_ms)?;
        dict.set_item("changed_ranges", self.get_changed_ranges(py)?)?;
        Ok(dict.into())
    }
}

/// Incremental parser that maintains tree-sitter state for efficient re-parsing.
///
/// This parser keeps the parse tree and source code in memory, allowing
/// subsequent edits to be applied incrementally rather than requiring
/// a full re-parse each time.
#[pyclass]
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

#[pymethods]
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
    #[new]
    #[pyo3(signature = (source, language, file_path))]
    fn new(source: &str, language: &str, file_path: &str) -> PyResult<Self> {
        let mut parser = Parser::new();

        // Set the language grammar
        let ts_language = get_tree_sitter_language(language).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!(
                "Unsupported language '{}': {}",
                language, e
            ))
        })?;

        parser.set_language(&ts_language).map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to set language: {}", e))
        })?;

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
    ///
    /// # Example
    ///
    /// ```python
    /// # Insert 'x' at position 100
    /// result = parser.apply_edit(100, 100, 101, "x")
    ///
    /// # Delete 5 characters starting at position 50
    /// result = parser.apply_edit(50, 55, 50, "")
    ///
    /// # Replace "foo" with "bar" at position 200
    /// result = parser.apply_edit(200, 203, 203, "bar")
    /// ```
    #[pyo3(signature = (start_byte, old_end_byte, new_end_byte, new_text))]
    fn apply_edit(
        &mut self,
        start_byte: usize,
        old_end_byte: usize,
        new_end_byte: usize,
        new_text: &str,
    ) -> PyResult<IncrementalParseResult> {
        let start_time = Instant::now();

        // Validate byte offsets
        if start_byte > self.source.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "start_byte {} is beyond source length {}",
                start_byte,
                self.source.len()
            )));
        }

        if old_end_byte > self.source.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "old_end_byte {} is beyond source length {}",
                old_end_byte,
                self.source.len()
            )));
        }

        if start_byte > old_end_byte {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "start_byte {} cannot be greater than old_end_byte {}",
                start_byte, old_end_byte
            )));
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
            pyo3::exceptions::PyRuntimeError::new_err(
                parse_result
                    .error
                    .unwrap_or_else(|| "Parse failed".to_string()),
            )
        })?;

        let parse_time_ms = start_time.elapsed().as_secs_f64() * 1000.0;

        Ok(IncrementalParseResult {
            module,
            parse_time_ms,
            changed_ranges,
        })
    }

    /// Get the current module definition.
    ///
    /// # Returns
    ///
    /// The `ModuleDef` for the current source state.
    fn get_module(&self) -> PyResult<ModuleDef> {
        let parse_result = parser::parse_source(&self.source, &self.file_path, &self.language);
        parse_result.module.ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err(
                parse_result
                    .error
                    .unwrap_or_else(|| "Parse failed".to_string()),
            )
        })
    }

    /// Get the current source code.
    fn get_source(&self) -> String {
        self.source.clone()
    }

    /// Get the language of this parser.
    fn get_language(&self) -> &str {
        &self.language
    }

    /// Get the file path of this parser.
    fn get_file_path(&self) -> &str {
        &self.file_path
    }

    /// Convert a byte offset to a (line, column) position.
    ///
    /// # Arguments
    ///
    /// * `byte_offset` - The byte offset in the source
    ///
    /// # Returns
    ///
    /// A tuple of (line, column), both 0-indexed.
    fn byte_to_position(&self, byte_offset: usize) -> PyResult<(usize, usize)> {
        if byte_offset > self.source.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "byte_offset {} is beyond source length {}",
                byte_offset,
                self.source.len()
            )));
        }

        let point = byte_offset_to_point(&self.source, byte_offset);
        Ok((point.row, point.column))
    }

    /// Convert a (line, column) position to a byte offset.
    ///
    /// # Arguments
    ///
    /// * `line` - The line number (0-indexed)
    /// * `column` - The column number (0-indexed)
    ///
    /// # Returns
    ///
    /// The byte offset in the source.
    #[pyo3(signature = (line, column))]
    fn position_to_byte(&self, line: usize, column: usize) -> PyResult<usize> {
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
    fn has_tree(&self) -> bool {
        self.tree.is_some()
    }

    /// Check if the current tree has syntax errors.
    fn has_errors(&self) -> bool {
        self.tree
            .as_ref()
            .map_or(true, |t| t.root_node().has_error())
    }

    /// Get the number of lines in the source.
    fn line_count(&self) -> usize {
        self.source.lines().count()
    }

    /// Get the source length in bytes.
    fn byte_count(&self) -> usize {
        self.source.len()
    }

    /// Reset the parser with new source code.
    ///
    /// This performs a full re-parse, discarding the previous tree.
    #[pyo3(signature = (source))]
    fn reset(&mut self, source: &str) -> PyResult<IncrementalParseResult> {
        let start_time = Instant::now();

        self.source = source.to_string();
        self.tree = self.parser.parse(source, None);

        let parse_result = parser::parse_source(&self.source, &self.file_path, &self.language);
        let module = parse_result.module.ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err(
                parse_result
                    .error
                    .unwrap_or_else(|| "Parse failed".to_string()),
            )
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

    // Helper to create an incremental parser for testing (bypasses PyO3)
    fn create_test_parser(
        source: &str,
        language: &str,
        file_path: &str,
    ) -> Result<IncrementalParser, String> {
        let mut parser = Parser::new();
        let ts_language = get_tree_sitter_language(language)?;
        parser
            .set_language(&ts_language)
            .map_err(|e| e.to_string())?;
        let tree = parser.parse(source, None);
        Ok(IncrementalParser {
            parser,
            tree,
            source: source.to_string(),
            language: normalize_language(language).to_string(),
            file_path: file_path.to_string(),
        })
    }

    // Helper to apply an edit for testing (bypasses PyO3)
    fn test_apply_edit(
        parser: &mut IncrementalParser,
        start_byte: usize,
        old_end_byte: usize,
        new_end_byte: usize,
        new_text: &str,
    ) -> Result<IncrementalParseResult, String> {
        if start_byte > parser.source.len() {
            return Err(format!(
                "start_byte {} beyond source length {}",
                start_byte,
                parser.source.len()
            ));
        }
        if old_end_byte > parser.source.len() {
            return Err(format!(
                "old_end_byte {} beyond source length {}",
                old_end_byte,
                parser.source.len()
            ));
        }
        if start_byte > old_end_byte {
            return Err(format!(
                "start_byte {} > old_end_byte {}",
                start_byte, old_end_byte
            ));
        }

        let start_time = Instant::now();
        let start_position = byte_offset_to_point(&parser.source, start_byte);
        let old_end_position = byte_offset_to_point(&parser.source, old_end_byte);

        let mut new_source = String::with_capacity(
            parser.source.len() - (old_end_byte - start_byte) + new_text.len(),
        );
        new_source.push_str(&parser.source[..start_byte]);
        new_source.push_str(new_text);
        if old_end_byte < parser.source.len() {
            new_source.push_str(&parser.source[old_end_byte..]);
        }

        let new_end_position =
            byte_offset_to_point(&new_source, new_end_byte.min(new_source.len()));

        let input_edit = InputEdit {
            start_byte,
            old_end_byte,
            new_end_byte,
            start_position,
            old_end_position,
            new_end_position,
        };

        if let Some(ref mut tree) = parser.tree {
            tree.edit(&input_edit);
        }

        let old_tree = parser.tree.take();
        let new_tree = parser.parser.parse(&new_source, old_tree.as_ref());

        let changed_ranges = match (&old_tree, &new_tree) {
            (Some(old), Some(new)) => old
                .changed_ranges(new)
                .map(|r| (r.start_byte, r.end_byte))
                .collect(),
            _ => vec![(0, new_source.len())],
        };

        parser.tree = new_tree;
        parser.source = new_source;

        let parse_result =
            crate::parser::parse_source(&parser.source, &parser.file_path, &parser.language);
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

    // Helper to get module for testing
    fn test_get_module(parser: &IncrementalParser) -> Result<ModuleDef, String> {
        let parse_result =
            crate::parser::parse_source(&parser.source, &parser.file_path, &parser.language);
        parse_result.module.ok_or_else(|| {
            parse_result
                .error
                .unwrap_or_else(|| "Parse failed".to_string())
        })
    }

    // Helper to reset parser for testing
    fn test_reset(
        parser: &mut IncrementalParser,
        source: &str,
    ) -> Result<IncrementalParseResult, String> {
        let start_time = Instant::now();
        parser.source = source.to_string();
        parser.tree = parser.parser.parse(source, None);

        let parse_result =
            crate::parser::parse_source(&parser.source, &parser.file_path, &parser.language);
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

    #[test]
    fn test_incremental_parser_creation() {
        let source = "def hello():\n    pass";
        let parser = create_test_parser(source, "python", "test.py");
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
        let result = create_test_parser("code", "brainfuck", "test.bf");
        assert!(result.is_err());
    }

    #[test]
    fn test_apply_edit_insert() {
        let source = "def hello():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // Insert 'world' into the function name: hello -> helloworld
        // 'hello' starts at byte 4, ends at byte 9
        // We insert 'world' at byte 9, so start=9, old_end=9, new_end=14
        let result = test_apply_edit(&mut parser, 9, 9, 14, "world").unwrap();

        assert!(result.parse_time_ms > 0.0);
        assert_eq!(parser.source, "def helloworld():\n    pass");

        // Verify the module was updated
        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.functions.len(), 1);
        assert_eq!(module.functions[0].name, "helloworld");
    }

    #[test]
    fn test_apply_edit_delete() {
        let source = "def helloworld():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // Delete 'world' from the function name: helloworld -> hello
        // 'world' is at bytes 9-14
        let result = test_apply_edit(&mut parser, 9, 14, 9, "").unwrap();

        assert!(result.parse_time_ms > 0.0);
        assert_eq!(parser.source, "def hello():\n    pass");

        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.functions[0].name, "hello");
    }

    #[test]
    fn test_apply_edit_replace() {
        let source = "def foo():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // Replace 'foo' with 'bar': foo at bytes 4-7
        let _result = test_apply_edit(&mut parser, 4, 7, 7, "bar").unwrap();

        assert_eq!(parser.source, "def bar():\n    pass");

        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.functions[0].name, "bar");
    }

    #[test]
    fn test_apply_edit_multiline() {
        let source = "def hello():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // Replace the entire body with a return statement
        // "    pass" is at bytes 13-21
        let new_body = "    return 42";
        let _result = test_apply_edit(&mut parser, 13, 21, 13 + new_body.len(), new_body).unwrap();

        assert_eq!(parser.source, "def hello():\n    return 42");
    }

    #[test]
    fn test_apply_edit_add_function() {
        let source = "def foo():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // Add a new function at the end
        let addition = "\n\ndef bar():\n    pass";
        let end = source.len();
        let _result =
            test_apply_edit(&mut parser, end, end, end + addition.len(), addition).unwrap();

        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.functions.len(), 2);
        assert_eq!(module.functions[0].name, "foo");
        assert_eq!(module.functions[1].name, "bar");
    }

    #[test]
    fn test_apply_edit_remove_function() {
        let source = "def foo():\n    pass\n\ndef bar():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // Remove the second function (including the preceding newlines)
        // "\n\ndef bar():\n    pass" starts at byte 18
        let _result = test_apply_edit(&mut parser, 18, source.len(), 18, "").unwrap();

        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.functions.len(), 1);
        assert_eq!(module.functions[0].name, "foo");
    }

    #[test]
    fn test_byte_to_position_internal() {
        let source = "def hello():\n    pass";

        // Start of file
        let point = byte_offset_to_point(source, 0);
        assert_eq!((point.row, point.column), (0, 0));

        // 'h' in 'hello'
        let point = byte_offset_to_point(source, 4);
        assert_eq!((point.row, point.column), (0, 4));

        // Start of second line (after newline)
        let point = byte_offset_to_point(source, 13);
        assert_eq!((point.row, point.column), (1, 0));
    }

    #[test]
    fn test_reset_parser() {
        let source = "def foo():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // Apply some edits
        test_apply_edit(&mut parser, 4, 7, 7, "bar").unwrap();

        // Reset with completely new source
        let new_source = "class MyClass:\n    pass";
        let _result = test_reset(&mut parser, new_source).unwrap();

        assert_eq!(parser.source, new_source);
        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.classes.len(), 1);
        assert_eq!(module.classes[0].name, "MyClass");
        assert_eq!(module.functions.len(), 0);
    }

    #[test]
    fn test_typescript_parser() {
        let source = "function hello(): string {\n    return 'hello';\n}";
        let parser = create_test_parser(source, "typescript", "test.ts").unwrap();

        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.functions.len(), 1);
        assert_eq!(module.functions[0].name, "hello");
    }

    #[test]
    fn test_go_parser() {
        let source = "package main\n\nfunc hello() string {\n    return \"hello\"\n}";
        let parser = create_test_parser(source, "go", "test.go").unwrap();

        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.functions.len(), 1);
        assert_eq!(module.functions[0].name, "hello");
    }

    #[test]
    fn test_sequential_edits() {
        let source = "def f():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // Make several sequential edits
        test_apply_edit(&mut parser, 4, 5, 5, "foo").unwrap(); // f -> foo
        assert_eq!(parser.source, "def foo():\n    pass");

        test_apply_edit(&mut parser, 4, 7, 7, "bar").unwrap(); // foo -> bar
        assert_eq!(parser.source, "def bar():\n    pass");

        test_apply_edit(&mut parser, 4, 7, 7, "baz").unwrap(); // bar -> baz
        assert_eq!(parser.source, "def baz():\n    pass");

        let module = test_get_module(&parser).unwrap();
        assert_eq!(module.functions[0].name, "baz");
    }

    #[test]
    fn test_invalid_byte_offset() {
        let source = "def hello():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        // start_byte beyond source length
        let result = test_apply_edit(&mut parser, 1000, 1000, 1001, "x");
        assert!(result.is_err());

        // old_end_byte beyond source length
        let result = test_apply_edit(&mut parser, 0, 1000, 0, "");
        assert!(result.is_err());

        // start_byte > old_end_byte
        let result = test_apply_edit(&mut parser, 10, 5, 10, "x");
        assert!(result.is_err());
    }

    #[test]
    fn test_has_errors() {
        // Valid syntax
        let parser = create_test_parser("def hello():\n    pass", "python", "test.py").unwrap();
        assert!(!parser.tree.as_ref().unwrap().root_node().has_error());

        // Invalid syntax
        let parser = create_test_parser("def hello(\n    pass", "python", "test.py").unwrap();
        assert!(parser.tree.as_ref().unwrap().root_node().has_error());
    }

    #[test]
    fn test_changed_ranges() {
        let source = "def hello():\n    pass";
        let mut parser = create_test_parser(source, "python", "test.py").unwrap();

        let result = test_apply_edit(&mut parser, 4, 9, 12, "goodbye").unwrap();

        // Should have detected changed ranges
        assert!(!result.changed_ranges.is_empty());
    }
}
