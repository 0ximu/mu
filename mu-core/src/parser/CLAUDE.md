# Parser Module - Claude Code Instructions

Multi-language AST extraction using tree-sitter. Converts language-specific syntax trees to the common `ModuleDef` structure.

## Module Structure

```
parser/
├── mod.rs          # Dispatcher + parallel parsing
├── helpers.rs      # Shared tree-sitter utilities
├── python.rs       # Python extractor
├── typescript.rs   # TypeScript/JavaScript extractor
├── go.rs           # Go extractor
├── java.rs         # Java extractor
├── rust_lang.rs    # Rust extractor (named to avoid keyword)
└── csharp.rs       # C# extractor
```

## Supported Languages

| Language | Aliases | Grammar Crate |
|----------|---------|---------------|
| Python | `python`, `py` | `tree-sitter-python` |
| TypeScript | `typescript`, `ts`, `tsx` | `tree-sitter-typescript` |
| JavaScript | `javascript`, `js`, `jsx` | `tree-sitter-javascript` |
| Go | `go` | `tree-sitter-go` |
| Java | `java` | `tree-sitter-java` |
| Rust | `rust`, `rs` | `tree-sitter-rust` |
| C# | `csharp`, `cs`, `c#` | `tree-sitter-c-sharp` |

## Adding a New Language

### 1. Add Grammar Dependency

In `Cargo.toml`:
```toml
tree-sitter-newlang = "0.23"
```

### 2. Create Extractor Module

Create `src/parser/newlang.rs`:

```rust
//! NewLang-specific AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Parser, Node};

use crate::types::{ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};
use crate::reducer::complexity;
use super::helpers::{
    get_node_text, find_child_by_type,
    get_start_line, get_end_line, count_lines,
};

pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser.set_language(&tree_sitter_newlang::LANGUAGE.into())
        .map_err(|e| format!("Failed to set NewLang language: {}", e))?;

    let tree = parser.parse(source, None)
        .ok_or("Failed to parse NewLang source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "newlang".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    // Extract imports, classes, functions from AST
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match child.kind() {
            "import_declaration" => { /* ... */ }
            "class_declaration" => { /* ... */ }
            "function_declaration" => { /* ... */ }
            _ => {}
        }
    }

    Ok(module)
}

// Private extraction helpers follow the same pattern...
```

### 3. Register in Dispatcher

In `mod.rs`:
```rust
pub mod newlang;

// In parse_source():
"newlang" | "nl" => newlang::parse(source, path),
```

### 4. Add Complexity Decision Points

In `src/reducer/complexity.rs`, add to `DECISION_POINTS`:
```rust
("newlang", hashset![
    "if_statement",
    "for_statement",
    "while_statement",
    // ... language-specific branching constructs
])
```

## Tree-Sitter Patterns

### Finding Node Types

Use `tree-sitter` CLI or playground to explore node types:
```bash
# Install tree-sitter CLI
cargo install tree-sitter-cli

# Parse and show tree
tree-sitter parse example.py
```

Or use the tree-sitter playground: https://tree-sitter.github.io/tree-sitter/playground

### Common Node Kinds by Language

**Python:**
- `import_statement`, `import_from_statement`
- `class_definition`, `function_definition`
- `decorated_definition` (wraps classes/functions with decorators)
- `parameters`, `identifier`, `type`, `return_type`
- `expression_statement` (for docstrings)

**TypeScript/JavaScript:**
- `import_statement`, `export_statement`
- `class_declaration`, `function_declaration`
- `interface_declaration` (TS only)
- `arrow_function`, `method_definition`
- `formal_parameters`, `type_annotation`

**Go:**
- `import_spec`, `import_declaration`
- `type_declaration`, `type_spec`
- `function_declaration`, `method_declaration`
- `parameter_list`, `result` (return type)

**Java:**
- `import_declaration`
- `class_declaration`, `interface_declaration`
- `method_declaration`, `constructor_declaration`
- `formal_parameters`, `annotation`

**Rust:**
- `use_declaration`
- `struct_item`, `enum_item`, `impl_item`
- `function_item`, `trait_item`
- `parameters`, `type_identifier`

**C#:**
- `using_directive`
- `class_declaration`, `interface_declaration`
- `method_declaration`, `property_declaration`
- `parameter_list`, `attribute`

### Helper Functions

Use `helpers.rs` utilities instead of raw tree-sitter:

```rust
use super::helpers::{
    get_node_text,       // Extract text from node
    find_child_by_type,  // Find first child by kind
    find_children_by_type, // Find all children by kind
    get_start_line,      // 1-indexed start line
    get_end_line,        // 1-indexed end line
    count_lines,         // Total lines in source
};

// Example usage
let name = find_child_by_type(&node, "identifier")
    .map(|n| get_node_text(&n, source).to_string())
    .unwrap_or_default();
```

### Field-Based Access

Some nodes have named fields (better than positional access):

```rust
// Preferred: field access
let name = node.child_by_field_name("name")
    .map(|n| get_node_text(&n, source));

// Fallback: type-based search
let name = find_child_by_type(&node, "identifier")
    .map(|n| get_node_text(&n, source));
```

### Cursor-Based Iteration

Always use cursor for child iteration:

```rust
let mut cursor = node.walk();
for child in node.children(&mut cursor) {
    match child.kind() {
        "identifier" => { /* ... */ }
        _ => {}
    }
}

// For named children only (skip punctuation, keywords):
for child in node.named_children(&mut cursor) {
    // ...
}
```

## Extraction Patterns

### Functions

```rust
fn extract_function(node: &Node, source: &str) -> FunctionDef {
    let name = node.child_by_field_name("name")
        .map(|n| get_node_text(&n, source).to_string())
        .unwrap_or_default();

    let parameters = extract_parameters(
        &node.child_by_field_name("parameters"),
        source
    );

    let return_type = node.child_by_field_name("return_type")
        .map(|n| get_node_text(&n, source).to_string());

    let body = node.child_by_field_name("body");
    let body_complexity = body
        .map(|b| complexity::calculate_from_node(&b, "language"))
        .unwrap_or(1);

    FunctionDef {
        name,
        parameters,
        return_type,
        body_complexity,
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        // ... other fields
        ..Default::default()
    }
}
```

### Classes

```rust
fn extract_class(node: &Node, source: &str) -> ClassDef {
    let name = node.child_by_field_name("name")
        .map(|n| get_node_text(&n, source).to_string())
        .unwrap_or_default();

    let mut methods = Vec::new();
    let mut cursor = node.walk();

    // Find body/block containing methods
    if let Some(body) = node.child_by_field_name("body") {
        for child in body.children(&mut cursor) {
            if child.kind() == "function_definition" {
                methods.push(extract_function(&child, source));
            }
        }
    }

    ClassDef {
        name,
        methods,
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    }
}
```

### Imports

```rust
fn extract_import(node: &Node, source: &str) -> ImportDef {
    // Structure varies by language
    // Python: `import foo` vs `from foo import bar`
    // TypeScript: `import { foo } from 'bar'`
    // Go: `import "path/to/pkg"`
    // Java: `import com.example.Foo;`

    ImportDef {
        module: extracted_module,
        names: extracted_names,
        alias: extracted_alias,
        is_from: is_from_style,
        line_number: get_start_line(node),
        ..Default::default()
    }
}
```

### Dynamic Import Detection

Scan for runtime imports that can't be statically resolved:

```rust
fn extract_dynamic_imports(root: &Node, source: &str) -> Vec<ImportDef> {
    let mut imports = Vec::new();
    // Python: __import__("module"), importlib.import_module("module")
    // JavaScript: import("module"), require(variable)
    // ...
    imports
}
```

## Error Handling

Return `Result<ModuleDef, String>` - the dispatcher wraps in `ParseResult`:

```rust
pub fn parse(source: &str, path: &str) -> Result<ModuleDef, String> {
    // Use ? for propagation
    let tree = parser.parse(source, None)
        .ok_or("Failed to parse source")?;

    // Return descriptive errors
    if root.has_error() {
        return Err(format!("Syntax errors in {}", path));
    }

    Ok(module)
}
```

## Testing

Each extractor should have tests for:
1. Basic imports/classes/functions extraction
2. Edge cases (empty files, syntax errors)
3. Language-specific features (decorators, generics, etc.)

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_function() {
        let source = "def hello(name: str) -> str:\n    return f'Hello {name}'";
        let result = parse(source, "test.py").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "hello");
    }
}
```

## Performance Notes

- **Parallel parsing** via `parse_files_parallel()` uses Rayon
- **GIL release**: Called from Python with `py.allow_threads()`
- **Parser reuse**: Each call creates a new parser (tree-sitter parsers are cheap)
- **No allocations in hot path**: Use `&str` slices from source where possible
