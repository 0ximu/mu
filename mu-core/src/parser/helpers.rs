//! Helper functions for tree-sitter AST navigation.

use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashSet;
use tree_sitter::Node;

/// Regex pattern for extracting capitalized type identifiers from type annotations.
static TYPE_PATTERN: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"\b([A-Z][a-zA-Z0-9_]*)\b").expect("Invalid regex pattern"));

/// Python built-in types to filter out from referenced_types.
static PYTHON_BUILTINS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    HashSet::from([
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "None",
        "Any",
        "Self",
        "List",
        "Dict",
        "Set",
        "Tuple",
        "Optional",
        "Union",
        "Callable",
        "Iterable",
        "Iterator",
        "Generator",
        "Sequence",
        "Mapping",
        "Type",
        "ClassVar",
        "Final",
        "Literal",
        "TypeVar",
        "Generic",
        "Protocol",
        "Awaitable",
        "Coroutine",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncGenerator",
    ])
});

/// TypeScript/JavaScript built-in types to filter out from referenced_types.
static TYPESCRIPT_BUILTINS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    HashSet::from([
        "string",
        "number",
        "boolean",
        "void",
        "null",
        "undefined",
        "any",
        "never",
        "unknown",
        "object",
        "symbol",
        "bigint",
        "Array",
        "Object",
        "String",
        "Number",
        "Boolean",
        "Symbol",
        "Promise",
        "Map",
        "Set",
        "WeakMap",
        "WeakSet",
        "Record",
        "Partial",
        "Required",
        "Readonly",
        "Pick",
        "Omit",
        "Exclude",
        "Extract",
        "NonNullable",
        "ReturnType",
        "Parameters",
        "ConstructorParameters",
        "InstanceType",
        "ThisType",
        "Awaited",
    ])
});

/// Go built-in types to filter out from referenced_types.
static GO_BUILTINS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    HashSet::from([
        "string",
        "int",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "uintptr",
        "byte",
        "rune",
        "float32",
        "float64",
        "complex64",
        "complex128",
        "bool",
        "error",
        "Error",
    ])
});

/// Java built-in types to filter out from referenced_types.
static JAVA_BUILTINS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    HashSet::from([
        "String",
        "Integer",
        "Long",
        "Double",
        "Float",
        "Boolean",
        "Character",
        "Byte",
        "Short",
        "Object",
        "Class",
        "Void",
        "Number",
        "Enum",
        "Throwable",
        "Exception",
        "RuntimeException",
        "List",
        "ArrayList",
        "LinkedList",
        "Map",
        "HashMap",
        "TreeMap",
        "Set",
        "HashSet",
        "TreeSet",
        "Collection",
        "Iterable",
        "Iterator",
        "Optional",
        "Stream",
        "Future",
        "CompletableFuture",
        "Callable",
        "Runnable",
        "Comparable",
        "Comparator",
    ])
});

/// Rust built-in types to filter out from referenced_types.
static RUST_BUILTINS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    HashSet::from([
        "String",
        "Vec",
        "Box",
        "Rc",
        "Arc",
        "Cell",
        "RefCell",
        "Option",
        "Result",
        "Ok",
        "Err",
        "Some",
        "None",
        "HashMap",
        "HashSet",
        "BTreeMap",
        "BTreeSet",
        "VecDeque",
        "LinkedList",
        "BinaryHeap",
        "Cow",
        "Pin",
        "PhantomData",
        "Self",
    ])
});

/// C# built-in types to filter out from referenced_types.
static CSHARP_BUILTINS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    HashSet::from([
        "String",
        "Int32",
        "Int64",
        "Double",
        "Single",
        "Boolean",
        "Byte",
        "Char",
        "Decimal",
        "Object",
        "Type",
        "Void",
        "Array",
        "List",
        "Dictionary",
        "HashSet",
        "Queue",
        "Stack",
        "IEnumerable",
        "IEnumerator",
        "IList",
        "IDictionary",
        "ICollection",
        "Task",
        "ValueTask",
        "Action",
        "Func",
        "Predicate",
        "Nullable",
        "Exception",
        "EventHandler",
    ])
});

/// Get the appropriate builtin set for a language.
fn get_builtins_for_language(language: &str) -> &'static HashSet<&'static str> {
    match language {
        "python" | "py" => &PYTHON_BUILTINS,
        "typescript" | "ts" | "tsx" | "javascript" | "js" | "jsx" => &TYPESCRIPT_BUILTINS,
        "go" => &GO_BUILTINS,
        "java" => &JAVA_BUILTINS,
        "rust" | "rs" => &RUST_BUILTINS,
        "csharp" | "cs" | "c#" => &CSHARP_BUILTINS,
        _ => &PYTHON_BUILTINS, // Default fallback
    }
}

/// Extract referenced type names from type annotation strings.
///
/// Scans type annotation strings for capitalized identifiers (e.g., `Node`, `MyClass`, `HTTPClient`)
/// and returns a sorted, deduplicated list of custom types, filtering out:
/// - The class's own name (self-references)
/// - Language-specific built-in types
///
/// # Arguments
/// * `type_strings` - Iterator of type annotation strings to scan
/// * `class_name` - The name of the class (to filter out self-references)
/// * `language` - The programming language (for built-in type filtering)
///
/// # Returns
/// Sorted, deduplicated `Vec<String>` of referenced type names
pub fn extract_referenced_types<'a, I>(
    type_strings: I,
    class_name: &str,
    language: &str,
) -> Vec<String>
where
    I: Iterator<Item = &'a str>,
{
    let builtins = get_builtins_for_language(language);
    let mut types: HashSet<String> = HashSet::new();

    for type_str in type_strings {
        for cap in TYPE_PATTERN.captures_iter(type_str) {
            if let Some(matched) = cap.get(1) {
                let type_name = matched.as_str();
                // Filter out:
                // 1. The class's own name
                // 2. Language-specific built-ins
                if type_name != class_name && !builtins.contains(type_name) {
                    types.insert(type_name.to_string());
                }
            }
        }
    }

    let mut result: Vec<String> = types.into_iter().collect();
    result.sort();
    result
}

/// Collect all type annotation strings from a ClassDef's methods.
///
/// This helper gathers:
/// - Return types from all methods
/// - Parameter type annotations from all methods
///
/// Used in conjunction with `extract_referenced_types` to populate
/// the `referenced_types` field on ClassDef.
pub fn collect_type_strings_from_methods(methods: &[crate::types::FunctionDef]) -> Vec<String> {
    methods
        .iter()
        .flat_map(|method| {
            let mut types = Vec::new();
            // Collect return type
            if let Some(ref rt) = method.return_type {
                types.push(rt.clone());
            }
            // Collect parameter types
            for param in &method.parameters {
                if let Some(ref ta) = param.type_annotation {
                    types.push(ta.clone());
                }
            }
            types
        })
        .collect()
}

/// Get the text content of a node.
pub fn get_node_text<'a>(node: &Node, source: &'a str) -> &'a str {
    let start = node.start_byte();
    let end = node.end_byte();
    if start < source.len() && end <= source.len() && start < end {
        &source[start..end]
    } else {
        ""
    }
}

/// Find the first child of a specific type.
#[allow(clippy::manual_find)]
pub fn find_child_by_type<'a>(node: &Node<'a>, type_name: &str) -> Option<Node<'a>> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == type_name {
            return Some(child);
        }
    }
    None
}

/// Find all children of a specific type.
#[allow(dead_code)]
pub fn find_children_by_type<'a>(node: &Node<'a>, type_name: &str) -> Vec<Node<'a>> {
    let mut results = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == type_name {
            results.push(child);
        }
    }
    results
}

/// Find the first child with a specific field name.
#[allow(dead_code)]
pub fn get_child_by_field<'a>(node: &Node<'a>, field_name: &str) -> Option<Node<'a>> {
    node.child_by_field_name(field_name)
}

/// Count the number of nodes in a subtree (for complexity).
#[allow(dead_code)]
pub fn count_nodes(node: &Node) -> u32 {
    let mut count = 1u32;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        count = count.saturating_add(count_nodes(&child));
    }
    count
}

/// Extract a docstring from a node (if it's a string literal).
#[allow(dead_code)]
pub fn extract_docstring(node: Option<Node>, source: &str) -> Option<String> {
    let node = node?;
    let text = get_node_text(&node, source);

    // Python: """docstring""" or '''docstring'''
    // Also handles regular strings
    let trimmed = text
        .trim_start_matches("\"\"\"")
        .trim_start_matches("'''")
        .trim_start_matches("\"")
        .trim_start_matches("'")
        .trim_end_matches("\"\"\"")
        .trim_end_matches("'''")
        .trim_end_matches("\"")
        .trim_end_matches("'")
        .trim();

    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

/// Check if a node has a child of a specific type.
#[allow(dead_code)]
pub fn has_child_of_type(node: &Node, type_name: &str) -> bool {
    find_child_by_type(node, type_name).is_some()
}

/// Get line number (1-indexed) from a node.
pub fn get_start_line(node: &Node) -> u32 {
    node.start_position().row as u32 + 1
}

/// Get end line number (1-indexed) from a node.
pub fn get_end_line(node: &Node) -> u32 {
    node.end_position().row as u32 + 1
}

/// Count total lines in source.
pub fn count_lines(source: &str) -> u32 {
    source.lines().count() as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_count_lines() {
        assert_eq!(count_lines("line1\nline2\nline3"), 3);
        assert_eq!(count_lines("single"), 1);
        assert_eq!(count_lines(""), 0);
    }

    #[test]
    fn test_extract_docstring() {
        assert_eq!(
            extract_docstring_from_text("\"\"\"Hello world\"\"\""),
            Some("Hello world".to_string())
        );
        assert_eq!(
            extract_docstring_from_text("'''Hello'''"),
            Some("Hello".to_string())
        );
        assert_eq!(
            extract_docstring_from_text("\"test\""),
            Some("test".to_string())
        );
    }

    fn extract_docstring_from_text(text: &str) -> Option<String> {
        let trimmed = text
            .trim_start_matches("\"\"\"")
            .trim_start_matches("'''")
            .trim_start_matches("\"")
            .trim_start_matches("'")
            .trim_end_matches("\"\"\"")
            .trim_end_matches("'''")
            .trim_end_matches("\"")
            .trim_end_matches("'")
            .trim();

        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    }

    #[test]
    fn test_extract_referenced_types_python() {
        // Test Python type extraction
        let type_strings = vec!["Node | None", "list[Edge]", "str", "MyClass"];
        let result = extract_referenced_types(type_strings.iter().map(|s| *s), "MUbase", "python");
        assert_eq!(result, vec!["Edge", "MyClass", "Node"]);
    }

    #[test]
    fn test_extract_referenced_types_filters_class_name() {
        // Should filter out the class's own name
        let type_strings = vec!["MUbase", "Node"];
        let result = extract_referenced_types(type_strings.iter().map(|s| *s), "MUbase", "python");
        assert_eq!(result, vec!["Node"]);
    }

    #[test]
    fn test_extract_referenced_types_filters_builtins() {
        // Should filter out Python builtins
        let type_strings = vec!["Optional[Node]", "List[str]", "Dict[str, Edge]", "Any"];
        let result =
            extract_referenced_types(type_strings.iter().map(|s| *s), "TestClass", "python");
        assert_eq!(result, vec!["Edge", "Node"]);
    }

    #[test]
    fn test_extract_referenced_types_typescript() {
        // Test TypeScript type extraction
        let type_strings = vec![
            "Node | null",
            "Array<Edge>",
            "string",
            "MyClass",
            "Promise<void>",
        ];
        let result =
            extract_referenced_types(type_strings.iter().map(|s| *s), "Service", "typescript");
        assert_eq!(result, vec!["Edge", "MyClass", "Node"]);
    }

    #[test]
    fn test_extract_referenced_types_deduplicates() {
        // Should deduplicate types
        let type_strings = vec!["Node", "Edge", "Node", "Edge", "Node"];
        let result =
            extract_referenced_types(type_strings.iter().map(|s| *s), "TestClass", "python");
        assert_eq!(result, vec!["Edge", "Node"]);
    }

    #[test]
    fn test_extract_referenced_types_complex_annotations() {
        // Should handle complex type annotations
        let type_strings = vec![
            "Callable[[Request, Response], Handler]",
            "dict[str, list[ConfigItem]]",
        ];
        let result =
            extract_referenced_types(type_strings.iter().map(|s| *s), "TestClass", "python");
        assert_eq!(result, vec!["ConfigItem", "Handler", "Request", "Response"]);
    }

    #[test]
    fn test_extract_referenced_types_http_style() {
        // Should handle HTTP-style type names
        let type_strings = vec!["HTTPClient", "URLParser", "JSONResponse"];
        let result =
            extract_referenced_types(type_strings.iter().map(|s| *s), "TestClass", "python");
        assert_eq!(result, vec!["HTTPClient", "JSONResponse", "URLParser"]);
    }
}
