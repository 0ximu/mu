//! Java AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Parser, Node};

use crate::types::{ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};
use crate::reducer::complexity;
use super::helpers::{
    get_node_text, find_child_by_type, get_start_line, get_end_line, count_lines,
};

/// Parse Java source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser.set_language(&tree_sitter_java::LANGUAGE.into())
        .map_err(|e| format!("Failed to set Java language: {}", e))?;

    let tree = parser.parse(source, None)
        .ok_or("Failed to parse Java source")?;
    let root = tree.root_node();

    // Get module name from package or filename
    let package_name = extract_package_name(&root, source);
    let class_name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let name = if let Some(pkg) = &package_name {
        format!("{}.{}", pkg, class_name)
    } else {
        class_name
    };

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "java".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    // Process top-level declarations
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match child.kind() {
            "import_declaration" => {
                if let Some(import) = extract_import(&child, source) {
                    module.imports.push(import);
                }
            }
            "class_declaration" => {
                module.classes.push(extract_class(&child, source));
            }
            "interface_declaration" => {
                module.classes.push(extract_interface(&child, source));
            }
            "enum_declaration" => {
                module.classes.push(extract_enum(&child, source));
            }
            _ => {}
        }
    }

    Ok(module)
}

/// Extract package name.
fn extract_package_name(root: &Node, source: &str) -> Option<String> {
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        if child.kind() == "package_declaration" {
            if let Some(id) = find_child_by_type(&child, "scoped_identifier") {
                return Some(get_node_text(&id, source).to_string());
            }
            if let Some(id) = find_child_by_type(&child, "identifier") {
                return Some(get_node_text(&id, source).to_string());
            }
        }
    }
    None
}

/// Extract import declaration.
fn extract_import(node: &Node, source: &str) -> Option<ImportDef> {
    let mut module = String::new();
    let mut is_static = false;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "scoped_identifier" | "identifier" => {
                module = get_node_text(&child, source).to_string();
            }
            "asterisk" => {
                module.push_str(".*");
            }
            "static" => {
                is_static = true;
            }
            _ => {}
        }
    }

    if module.is_empty() {
        return None;
    }

    let mut import = ImportDef {
        module,
        ..Default::default()
    };

    if is_static {
        import.names.push("static".to_string());
    }

    Some(import)
}

/// Extract class declaration.
fn extract_class(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    // Extract modifiers and annotations
    extract_modifiers(node, source, &mut class_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "type_parameters" => {
                // Generic type parameters
                let generics = get_node_text(&child, source);
                if !generics.is_empty() {
                    class_def.name.push_str(&generics);
                }
            }
            "superclass" => {
                if let Some(type_node) = find_child_by_type(&child, "type_identifier") {
                    class_def.bases.push(get_node_text(&type_node, source).to_string());
                }
            }
            "super_interfaces" => {
                extract_interfaces(&child, source, &mut class_def.bases);
            }
            "class_body" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    class_def
}

/// Extract modifiers and annotations.
fn extract_modifiers(node: &Node, source: &str, decorators: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "modifiers" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    match inner.kind() {
                        "marker_annotation" | "annotation" => {
                            let text = get_node_text(&inner, source);
                            decorators.push(text.trim_start_matches('@').to_string());
                        }
                        "public" | "private" | "protected" | "static" | "final" | "abstract" => {
                            decorators.push(get_node_text(&inner, source).to_string());
                        }
                        _ => {}
                    }
                }
            }
            "marker_annotation" | "annotation" => {
                let text = get_node_text(&child, source);
                decorators.push(text.trim_start_matches('@').to_string());
            }
            _ => {}
        }
    }
}

/// Extract implemented interfaces.
fn extract_interfaces(node: &Node, source: &str, bases: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "type_list" {
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                if inner.kind() == "type_identifier" || inner.kind() == "generic_type" {
                    bases.push(get_node_text(&inner, source).to_string());
                }
            }
        }
    }
}

/// Extract class body.
fn extract_class_body(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "method_declaration" => {
                class_def.methods.push(extract_method(&child, source));
            }
            "constructor_declaration" => {
                class_def.methods.push(extract_constructor(&child, source));
            }
            "field_declaration" => {
                extract_fields(&child, source, &mut class_def.attributes);
            }
            "class_declaration" => {
                // Inner class - add as attribute for reference
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    class_def.attributes.push(format!("class:{}", get_node_text(&id, source)));
                }
            }
            _ => {}
        }
    }
}

/// Extract method declaration.
fn extract_method(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        is_method: true,
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    // Extract modifiers and annotations
    extract_modifiers(node, source, &mut func_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if func_def.name.is_empty() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "type_identifier" | "generic_type" | "array_type" | "void_type" => {
                if func_def.return_type.is_none() && func_def.name.is_empty() {
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            "formal_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "block" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "java");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    // Check for static
    if func_def.decorators.contains(&"static".to_string()) {
        func_def.is_static = true;
    }

    func_def
}

/// Extract constructor declaration.
fn extract_constructor(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        is_method: true,
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    extract_modifiers(node, source, &mut func_def.decorators);
    func_def.decorators.push("constructor".to_string());

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                func_def.name = get_node_text(&child, source).to_string();
            }
            "formal_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "constructor_body" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "java");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    func_def
}

/// Extract parameters.
fn extract_parameters(node: &Node, source: &str) -> Vec<ParameterDef> {
    let mut params = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "formal_parameter" || child.kind() == "spread_parameter" {
            let mut param = ParameterDef::default();
            let is_variadic = child.kind() == "spread_parameter";

            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "identifier" => {
                        param.name = get_node_text(&inner, source).to_string();
                    }
                    "type_identifier" | "generic_type" | "array_type" => {
                        param.type_annotation = Some(get_node_text(&inner, source).to_string());
                    }
                    _ => {}
                }
            }

            if !param.name.is_empty() {
                param.is_variadic = is_variadic;
                params.push(param);
            }
        }
    }

    params
}

/// Extract field declarations.
fn extract_fields(node: &Node, source: &str, attributes: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "variable_declarator" {
            if let Some(id) = find_child_by_type(&child, "identifier") {
                attributes.push(get_node_text(&id, source).to_string());
            }
        }
    }
}

/// Extract interface declaration.
fn extract_interface(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    class_def.decorators.push("interface".to_string());
    extract_modifiers(node, source, &mut class_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "extends_interfaces" => {
                extract_interfaces(&child, source, &mut class_def.bases);
            }
            "interface_body" => {
                extract_interface_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    class_def
}

/// Extract interface body.
fn extract_interface_body(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "method_declaration" {
            class_def.methods.push(extract_method(&child, source));
        }
    }
}

/// Extract enum declaration.
fn extract_enum(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    class_def.decorators.push("enum".to_string());
    extract_modifiers(node, source, &mut class_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "enum_body" => {
                // Extract enum constants as attributes
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "enum_constant" {
                        if let Some(id) = find_child_by_type(&inner, "identifier") {
                            class_def.attributes.push(get_node_text(&id, source).to_string());
                        }
                    }
                }
            }
            _ => {}
        }
    }

    class_def
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_class() {
        let source = r#"
package com.example;

public class Hello {
    public String greet(String name) {
        return "Hello, " + name;
    }
}
"#;
        let result = parse(source, "Hello.java").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "Hello");
        assert_eq!(result.classes[0].methods.len(), 1);
    }

    #[test]
    fn test_parse_interface() {
        let source = r#"
public interface Greeter {
    String greet(String name);
}
"#;
        let result = parse(source, "Greeter.java").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert!(result.classes[0].decorators.contains(&"interface".to_string()));
    }

    #[test]
    fn test_parse_import() {
        let source = r#"
import java.util.List;
import static java.lang.Math.*;
"#;
        let result = parse(source, "Test.java").unwrap();
        assert_eq!(result.imports.len(), 2);
    }
}
