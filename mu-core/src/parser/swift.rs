//! Swift AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse Swift source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_swift::LANGUAGE.into())
        .map_err(|e| format!("Failed to set Swift language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse Swift source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "swift".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    process_node(&root, source, &mut module);

    Ok(module)
}

/// Process a node recursively.
fn process_node(node: &Node, source: &str, module: &mut ModuleDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "import_declaration" => {
                if let Some(import) = extract_import(&child, source) {
                    module.imports.push(import);
                }
            }
            "class_declaration" => {
                // In tree-sitter-swift, struct/class/enum all use class_declaration
                let kind = detect_swift_declaration_kind(&child);
                module.classes.push(extract_class(&child, source, &kind));
            }
            "protocol_declaration" => {
                module
                    .classes
                    .push(extract_class(&child, source, "protocol"));
            }
            "function_declaration" => {
                module.functions.push(extract_function(&child, source));
            }
            _ => {}
        }
    }
}

/// Detect whether a class_declaration is actually a class, struct, or enum.
fn detect_swift_declaration_kind(node: &Node) -> String {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "struct" => return "struct".to_string(),
            "enum" => return "enum".to_string(),
            "class" => return "class".to_string(),
            "actor" => return "actor".to_string(),
            _ => {}
        }
    }
    "class".to_string()
}

/// Extract import declaration.
fn extract_import(node: &Node, source: &str) -> Option<ImportDef> {
    // In Swift, import declaration has an identifier child
    let text = get_node_text(node, source);
    let module_name = text.strip_prefix("import ")?.trim().to_string();
    if module_name.is_empty() {
        return None;
    }
    Some(ImportDef {
        module: module_name,
        ..Default::default()
    })
}

/// Extract class/struct/enum/protocol declaration.
fn extract_class(node: &Node, source: &str, kind: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };
    class_def.decorators.push(kind.to_string());

    // Extract modifiers
    extract_modifiers(node, source, &mut class_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "simple_identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "inheritance_specifier" => {
                extract_inheritance(&child, source, &mut class_def.bases);
            }
            "class_body" | "protocol_body" | "struct_body" | "enum_class_body" => {
                extract_class_body(&child, source, &mut class_def);
            }
            "type_parameters" => {
                let generics = get_node_text(&child, source);
                class_def.decorators.push(format!("generic:{}", generics));
            }
            _ => {}
        }
    }

    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types = extract_referenced_types(
        type_strings.iter().map(|s| s.as_str()),
        &class_def.name,
        "swift",
    );

    class_def
}

/// Extract modifiers.
fn extract_modifiers(node: &Node, source: &str, decorators: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "modifiers" {
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "access_control_modifier"
                    | "mutation_modifier"
                    | "declaration_modifier"
                    | "attribute" => {
                        decorators.push(get_node_text(&inner, source).to_string());
                    }
                    _ => {}
                }
            }
        }
    }
}

/// Extract inheritance specifiers.
fn extract_inheritance(node: &Node, source: &str, bases: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "user_type" => {
                bases.push(get_node_text(&child, source).to_string());
            }
            "inheritance_specifier" => {
                extract_inheritance(&child, source, bases);
            }
            _ => {}
        }
    }
}

/// Extract class body.
fn extract_class_body(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "function_declaration" => {
                let mut method = extract_function(&child, source);
                method.is_method = true;
                class_def.methods.push(method);
            }
            "property_declaration" => {
                extract_property(&child, source, &mut class_def.attributes);
            }
            "class_declaration" => {
                if let Some(id) = find_child_by_type(&child, "type_identifier") {
                    class_def
                        .attributes
                        .push(format!("class:{}", get_node_text(&id, source)));
                }
            }
            "init_declaration" => {
                let mut init_func = FunctionDef {
                    name: "init".to_string(),
                    is_method: true,
                    start_line: get_start_line(&child),
                    end_line: get_end_line(&child),
                    ..Default::default()
                };
                init_func.decorators.push("constructor".to_string());

                // Extract parameters
                if let Some(params) = find_child_by_type(&child, "parameter") {
                    init_func.parameters = extract_function_params_from_node(&params, source);
                }

                // Extract body
                if let Some(body) = find_child_by_type(&child, "function_body") {
                    init_func.body_complexity =
                        complexity::calculate_for_node(&body, source, "swift");
                    init_func.body_source = Some(get_node_text(&body, source).to_string());
                    init_func.call_sites = extract_call_sites(&body, source);
                }

                class_def.methods.push(init_func);
            }
            _ => {}
        }
    }
}

/// Extract property declaration as attribute.
fn extract_property(node: &Node, source: &str, attributes: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "pattern" || child.kind() == "simple_identifier" {
            attributes.push(get_node_text(&child, source).to_string());
            return;
        }
    }
}

/// Extract function declaration.
fn extract_function(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    extract_modifiers(node, source, &mut func_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "simple_identifier" => {
                if func_def.name.is_empty() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "parameter" => {
                func_def.parameters = extract_function_params_from_node(&child, source);
            }
            "type_annotation" => {
                // Return type
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() != ":" {
                        func_def.return_type = Some(get_node_text(&inner, source).to_string());
                        break;
                    }
                }
            }
            "function_body" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "swift");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);
            }
            _ => {}
        }
    }

    func_def
}

/// Extract parameters from a parameter node.
fn extract_function_params_from_node(node: &Node, source: &str) -> Vec<ParameterDef> {
    let mut params = Vec::new();

    // Could be a single parameter or contain multiple
    if node.kind() == "parameter" {
        if let Some(param) = extract_single_param(node, source) {
            params.push(param);
        }
        return params;
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "parameter" {
            if let Some(param) = extract_single_param(&child, source) {
                params.push(param);
            }
        }
    }

    params
}

/// Extract a single parameter.
fn extract_single_param(node: &Node, source: &str) -> Option<ParameterDef> {
    let mut param = ParameterDef::default();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "simple_identifier" => {
                if param.name.is_empty() {
                    param.name = get_node_text(&child, source).to_string();
                }
            }
            "type_annotation" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() != ":" {
                        param.type_annotation = Some(get_node_text(&inner, source).to_string());
                        break;
                    }
                }
            }
            _ => {}
        }
    }
    if param.name.is_empty() {
        return None;
    }
    Some(param)
}

/// Extract all call sites from a function body node.
fn extract_call_sites(body: &Node, source: &str) -> Vec<CallSiteDef> {
    let mut call_sites = Vec::new();
    find_call_sites_recursive(body, source, &mut call_sites);
    call_sites
}

/// Recursively search for call expressions in AST.
fn find_call_sites_recursive(node: &Node, source: &str, results: &mut Vec<CallSiteDef>) {
    if node.kind() == "call_expression" {
        if let Some(call_site) = extract_call_site(node, source) {
            results.push(call_site);
        }
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        find_call_sites_recursive(&child, source, results);
    }
}

/// Extract a single call site.
fn extract_call_site(node: &Node, source: &str) -> Option<CallSiteDef> {
    let func_node = node.child(0)?;
    let line = get_start_line(node);

    match func_node.kind() {
        "simple_identifier" => {
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        "navigation_expression" => {
            let full_text = get_node_text(&func_node, source);
            let receiver = func_node
                .child(0)
                .map(|n| get_node_text(&n, source).to_string());
            Some(CallSiteDef {
                callee: full_text.to_string(),
                line,
                is_method_call: true,
                receiver,
            })
        }
        _ => {
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_function() {
        let source = r#"
import Foundation

func greet(name: String) -> String {
    return "Hello, \(name)"
}
"#;
        let result = parse(source, "Main.swift").unwrap();
        assert!(!result.functions.is_empty());
        assert!(result.functions.iter().any(|f| f.name == "greet"));
    }

    #[test]
    fn test_parse_class() {
        let source = r#"
class Animal {
    var name: String
    func speak() -> String {
        return "..."
    }
}
"#;
        let result = parse(source, "Animal.swift").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "Animal");
        assert!(result.classes[0].decorators.contains(&"class".to_string()));
    }

    #[test]
    fn test_parse_protocol() {
        let source = r#"
protocol Drawable {
    func draw()
}
"#;
        let result = parse(source, "Drawable.swift").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert!(result.classes[0]
            .decorators
            .contains(&"protocol".to_string()));
    }

    #[test]
    fn test_parse_import() {
        let source = r#"
import Foundation
import UIKit
"#;
        let result = parse(source, "App.swift").unwrap();
        assert_eq!(result.imports.len(), 2);
        assert_eq!(result.imports[0].module, "Foundation");
        assert_eq!(result.imports[1].module, "UIKit");
    }

    #[test]
    fn test_parse_empty() {
        let source = "";
        let result = parse(source, "empty.swift").unwrap();
        assert!(result.functions.is_empty());
        assert!(result.classes.is_empty());
    }

    #[test]
    fn test_parse_struct() {
        let source = r#"
struct Point {
    var x: Double
    var y: Double
}
"#;
        let result = parse(source, "Point.swift").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert!(result.classes[0].decorators.contains(&"struct".to_string()));
    }
}
