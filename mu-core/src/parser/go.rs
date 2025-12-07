//! Go AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    count_lines, find_child_by_type, get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse Go source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_go::LANGUAGE.into())
        .map_err(|e| format!("Failed to set Go language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse Go source")?;
    let root = tree.root_node();

    // Get module name from package clause or file name
    let name = extract_package_name(&root, source).unwrap_or_else(|| {
        Path::new(file_path)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("unknown")
            .to_string()
    });

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "go".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    // Process top-level declarations
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match child.kind() {
            "import_declaration" => {
                extract_imports(&child, source, &mut module.imports);
            }
            "function_declaration" => {
                module.functions.push(extract_function(&child, source));
            }
            "method_declaration" => {
                // Methods are associated with types
                module.functions.push(extract_method(&child, source));
            }
            "type_declaration" => {
                extract_type_declarations(&child, source, &mut module.classes);
            }
            _ => {}
        }
    }

    Ok(module)
}

/// Extract package name from package clause.
fn extract_package_name(root: &Node, source: &str) -> Option<String> {
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        if child.kind() == "package_clause" {
            if let Some(id) = find_child_by_type(&child, "package_identifier") {
                return Some(get_node_text(&id, source).to_string());
            }
        }
    }
    None
}

/// Extract imports from import declaration.
fn extract_imports(node: &Node, source: &str, imports: &mut Vec<ImportDef>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "import_spec" => {
                if let Some(import) = extract_import_spec(&child, source) {
                    imports.push(import);
                }
            }
            "import_spec_list" => {
                let mut inner_cursor = child.walk();
                for spec in child.children(&mut inner_cursor) {
                    if spec.kind() == "import_spec" {
                        if let Some(import) = extract_import_spec(&spec, source) {
                            imports.push(import);
                        }
                    }
                }
            }
            "interpreted_string_literal" | "raw_string_literal" => {
                // Single import without spec list
                let module = get_node_text(&child, source)
                    .trim_matches('"')
                    .trim_matches('`')
                    .to_string();
                imports.push(ImportDef {
                    module,
                    ..Default::default()
                });
            }
            _ => {}
        }
    }
}

/// Extract a single import spec.
fn extract_import_spec(node: &Node, source: &str) -> Option<ImportDef> {
    let mut module = String::new();
    let mut alias = None;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "interpreted_string_literal" | "raw_string_literal" => {
                module = get_node_text(&child, source)
                    .trim_matches('"')
                    .trim_matches('`')
                    .to_string();
            }
            "package_identifier" | "blank_identifier" | "dot" => {
                alias = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    if module.is_empty() {
        return None;
    }

    Some(ImportDef {
        module,
        alias,
        ..Default::default()
    })
}

/// Extract function declaration.
fn extract_function(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut found_params = false;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if func_def.name.is_empty() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "parameter_list" => {
                if !found_params {
                    func_def.parameters = extract_parameters(&child, source);
                    found_params = true;
                } else {
                    // Second parameter_list is multiple return values
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            // Simple return type (single value)
            "type_identifier" | "pointer_type" | "slice_type" | "array_type" | "map_type"
            | "channel_type" | "qualified_type" | "interface_type" | "struct_type"
            | "function_type" => {
                func_def.return_type = Some(get_node_text(&child, source).to_string());
            }
            "block" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "go");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    // Check if exported (starts with uppercase)
    if !func_def.name.is_empty() {
        let first_char = func_def.name.chars().next().unwrap_or('a');
        if first_char.is_uppercase() {
            func_def.decorators.push("exported".to_string());
        }
    }

    func_def
}

/// Extract method declaration (with receiver).
fn extract_method(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        is_method: true,
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut receiver_type = String::new();
    let mut param_list_count = 0;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "parameter_list" => {
                if param_list_count == 0 {
                    // First parameter_list is the receiver
                    receiver_type = extract_receiver_type(&child, source);
                } else if param_list_count == 1 {
                    // Second parameter_list is the actual parameters
                    func_def.parameters = extract_parameters(&child, source);
                } else {
                    // Third parameter_list is multiple return values
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
                param_list_count += 1;
            }
            "field_identifier" => {
                func_def.name = get_node_text(&child, source).to_string();
            }
            // Simple return type (single value)
            "type_identifier" | "pointer_type" | "slice_type" | "array_type" | "map_type"
            | "channel_type" | "qualified_type" | "interface_type" | "struct_type"
            | "function_type" => {
                func_def.return_type = Some(get_node_text(&child, source).to_string());
            }
            "block" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "go");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    // Add receiver as decorator for clarity
    if !receiver_type.is_empty() {
        func_def
            .decorators
            .push(format!("receiver:{}", receiver_type));
    }

    func_def
}

/// Extract receiver type from parameter list.
fn extract_receiver_type(node: &Node, source: &str) -> String {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "parameter_declaration" {
            // Look for type in the parameter
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "pointer_type" | "type_identifier" => {
                        return get_node_text(&inner, source).to_string();
                    }
                    _ => {}
                }
            }
        }
    }
    String::new()
}

/// Extract parameters from parameter list.
fn extract_parameters(node: &Node, source: &str) -> Vec<ParameterDef> {
    let mut params = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "parameter_declaration" => {
                let mut names = Vec::new();
                let mut type_annotation = None;

                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    match inner.kind() {
                        "identifier" => {
                            names.push(get_node_text(&inner, source).to_string());
                        }
                        // Skip commas and other punctuation
                        "," | "(" | ")" => {}
                        _ => {
                            // Assume it's a type (could be type_identifier, slice_type, etc.)
                            type_annotation = Some(get_node_text(&inner, source).to_string());
                        }
                    }
                }

                // If we found names, create params for each
                if !names.is_empty() {
                    for name in names {
                        params.push(ParameterDef {
                            name,
                            type_annotation: type_annotation.clone(),
                            is_variadic: false,
                            ..Default::default()
                        });
                    }
                } else if type_annotation.is_some() {
                    // Type-only parameter (no name, like in return types)
                    params.push(ParameterDef {
                        name: String::new(),
                        type_annotation,
                        is_variadic: false,
                        ..Default::default()
                    });
                }
            }
            "variadic_parameter_declaration" => {
                // Handle variadic parameters like `nums ...int`
                let mut name = String::new();
                let mut type_annotation = None;

                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    match inner.kind() {
                        "identifier" => {
                            name = get_node_text(&inner, source).to_string();
                        }
                        "..." => {
                            // Skip the ellipsis token
                        }
                        _ => {
                            // Type (after the ellipsis)
                            let type_text = get_node_text(&inner, source).to_string();
                            type_annotation = Some(format!("...{}", type_text));
                        }
                    }
                }

                if !name.is_empty() {
                    params.push(ParameterDef {
                        name,
                        type_annotation,
                        is_variadic: true,
                        ..Default::default()
                    });
                }
            }
            _ => {}
        }
    }

    params
}

/// Extract type declarations (struct, interface).
fn extract_type_declarations(node: &Node, source: &str, classes: &mut Vec<ClassDef>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "type_spec" {
            if let Some(class) = extract_type_spec(&child, source) {
                classes.push(class);
            }
        }
    }
}

/// Extract a type specification.
fn extract_type_spec(node: &Node, source: &str) -> Option<ClassDef> {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "struct_type" => {
                class_def.decorators.push("struct".to_string());
                extract_struct_fields(&child, source, &mut class_def);
            }
            "interface_type" => {
                class_def.decorators.push("interface".to_string());
                extract_interface_methods(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    if class_def.name.is_empty() {
        return None;
    }

    // Check if exported
    let first_char = class_def.name.chars().next().unwrap_or('a');
    if first_char.is_uppercase() {
        class_def.decorators.push("exported".to_string());
    }

    Some(class_def)
}

/// Extract struct fields.
fn extract_struct_fields(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "field_declaration_list" {
            let mut inner_cursor = child.walk();
            for field in child.children(&mut inner_cursor) {
                if field.kind() == "field_declaration" {
                    // Look for field identifiers
                    let mut field_cursor = field.walk();
                    for f in field.children(&mut field_cursor) {
                        if f.kind() == "field_identifier" {
                            class_def
                                .attributes
                                .push(get_node_text(&f, source).to_string());
                        } else if f.kind() == "type_identifier" {
                            // Embedded type (acts as base)
                            class_def.bases.push(get_node_text(&f, source).to_string());
                        }
                    }
                }
            }
        }
    }
}

/// Extract interface methods.
fn extract_interface_methods(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        // Handle both old "method_spec" and new "method_elem" node types
        if child.kind() == "method_spec" || child.kind() == "method_elem" {
            let mut method = FunctionDef {
                is_method: true,
                start_line: get_start_line(&child),
                end_line: get_end_line(&child),
                ..Default::default()
            };

            let mut param_list_count = 0;
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "field_identifier" => {
                        method.name = get_node_text(&inner, source).to_string();
                    }
                    "parameter_list" => {
                        if param_list_count == 0 {
                            method.parameters = extract_parameters(&inner, source);
                        } else {
                            // Second parameter_list is multiple return values
                            method.return_type = Some(get_node_text(&inner, source).to_string());
                        }
                        param_list_count += 1;
                    }
                    // Simple return type (single value)
                    "type_identifier" | "pointer_type" | "slice_type" | "array_type"
                    | "map_type" | "channel_type" | "qualified_type" | "interface_type"
                    | "struct_type" | "function_type" => {
                        method.return_type = Some(get_node_text(&inner, source).to_string());
                    }
                    _ => {}
                }
            }

            if !method.name.is_empty() {
                class_def.methods.push(method);
            }
        } else if child.kind() == "type_identifier" {
            // Embedded interface
            class_def
                .bases
                .push(get_node_text(&child, source).to_string());
        } else if child.kind() == "type_elem" {
            // Type element for embedded interfaces (Go 1.18+)
            let mut type_cursor = child.walk();
            for type_child in child.children(&mut type_cursor) {
                if type_child.kind() == "type_identifier" || type_child.kind() == "qualified_type" {
                    class_def
                        .bases
                        .push(get_node_text(&type_child, source).to_string());
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_function() {
        let source = r#"
package main

func Hello(name string) string {
    return "Hello, " + name
}
"#;
        let result = parse(source, "main.go").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "Hello");
    }

    #[test]
    fn test_parse_struct() {
        let source = r#"
package main

type User struct {
    Name string
    Age  int
}
"#;
        let result = parse(source, "main.go").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "User");
        assert!(result.classes[0].decorators.contains(&"struct".to_string()));
    }

    #[test]
    fn test_parse_import() {
        let source = r#"
package main

import (
    "fmt"
    "os"
)
"#;
        let result = parse(source, "main.go").unwrap();
        assert_eq!(result.imports.len(), 2);
    }
}
