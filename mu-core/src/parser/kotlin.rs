//! Kotlin AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse Kotlin source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_kotlin_ng::LANGUAGE.into())
        .map_err(|e| format!("Failed to set Kotlin language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse Kotlin source")?;
    let root = tree.root_node();

    let package_name = extract_package_name(&root, source);
    let file_name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let name = package_name.unwrap_or(file_name);

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "kotlin".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match child.kind() {
            "import" | "import_header" | "import_list" => {
                extract_imports(&child, source, &mut module.imports);
            }
            "class_declaration" => {
                module.classes.push(extract_class(&child, source));
            }
            "object_declaration" => {
                module.classes.push(extract_object(&child, source));
            }
            "function_declaration" => {
                module.functions.push(extract_function(&child, source));
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
        if child.kind() == "package_header" || child.kind() == "package" {
            if let Some(id) = find_child_by_type(&child, "qualified_identifier") {
                return Some(get_node_text(&id, source).to_string());
            }
            if let Some(id) = find_child_by_type(&child, "identifier") {
                return Some(get_node_text(&id, source).to_string());
            }
        }
    }
    None
}

/// Extract imports.
fn extract_imports(node: &Node, source: &str, imports: &mut Vec<ImportDef>) {
    // tree-sitter-kotlin-ng uses "import" with "qualified_identifier" inside
    if node.kind() == "import" || node.kind() == "import_header" {
        if let Some(id) = find_child_by_type(node, "qualified_identifier") {
            let module = get_node_text(&id, source).to_string();
            imports.push(ImportDef {
                module,
                ..Default::default()
            });
        } else if let Some(id) = find_child_by_type(node, "identifier") {
            let module = get_node_text(&id, source).to_string();
            imports.push(ImportDef {
                module,
                ..Default::default()
            });
        }
        return;
    }

    // import_list contains multiple import children
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "import" || child.kind() == "import_header" {
            extract_imports(&child, source, imports);
        }
    }
}

/// Extract class declaration.
fn extract_class(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    extract_modifiers(node, source, &mut class_def.decorators);

    let mut found_class_keyword = false;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "class" => {
                found_class_keyword = true;
            }
            "identifier" | "type_identifier" => {
                // Only take the identifier after the "class" keyword as the name
                if class_def.name.is_empty() && found_class_keyword {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "delegation_specifier" | "delegation_specifiers" => {
                extract_delegation_specifiers(&child, source, &mut class_def.bases);
            }
            "class_body" => {
                extract_class_body(&child, source, &mut class_def);
            }
            "primary_constructor" => {
                extract_primary_constructor(&child, source, &mut class_def);
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
        "kotlin",
    );

    class_def
}

/// Extract object declaration (companion/singleton).
fn extract_object(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };
    class_def.decorators.push("object".to_string());

    let mut found_object_keyword = false;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "object" => {
                found_object_keyword = true;
            }
            "identifier" | "type_identifier" => {
                if class_def.name.is_empty() && found_object_keyword {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "class_body" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    class_def
}

/// Extract modifiers (visibility, abstract, data, etc.).
fn extract_modifiers(node: &Node, source: &str, decorators: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "modifiers" {
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "visibility_modifier"
                    | "inheritance_modifier"
                    | "class_modifier"
                    | "member_modifier"
                    | "function_modifier" => {
                        decorators.push(get_node_text(&inner, source).to_string());
                    }
                    "annotation" => {
                        decorators.push(get_node_text(&inner, source).to_string());
                    }
                    _ => {}
                }
            }
        }
    }
}

/// Extract delegation specifiers (base classes/interfaces).
fn extract_delegation_specifiers(node: &Node, source: &str, bases: &mut Vec<String>) {
    if node.kind() == "delegation_specifier" {
        // Direct specifier - get the type
        if let Some(user_type) = find_child_by_type(node, "user_type") {
            bases.push(get_node_text(&user_type, source).to_string());
        } else if let Some(constructor) = find_child_by_type(node, "constructor_invocation") {
            if let Some(user_type) = find_child_by_type(&constructor, "user_type") {
                bases.push(get_node_text(&user_type, source).to_string());
            }
        }
        return;
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "delegation_specifier" {
            if let Some(user_type) = find_child_by_type(&child, "user_type") {
                bases.push(get_node_text(&user_type, source).to_string());
            } else if let Some(constructor) = find_child_by_type(&child, "constructor_invocation") {
                if let Some(user_type) = find_child_by_type(&constructor, "user_type") {
                    bases.push(get_node_text(&user_type, source).to_string());
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
            "function_declaration" => {
                let mut method = extract_function(&child, source);
                method.is_method = true;
                class_def.methods.push(method);
            }
            "property_declaration" => {
                if let Some(id) = find_child_by_type(&child, "variable_declaration") {
                    if let Some(name_node) = find_child_by_type(&id, "identifier") {
                        class_def
                            .attributes
                            .push(get_node_text(&name_node, source).to_string());
                    }
                } else if let Some(name_node) = find_child_by_type(&child, "identifier") {
                    class_def
                        .attributes
                        .push(get_node_text(&name_node, source).to_string());
                }
            }
            "class_declaration" => {
                // Nested class - add as attribute
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    class_def
                        .attributes
                        .push(format!("class:{}", get_node_text(&id, source)));
                }
            }
            "companion_object" => {
                class_def.decorators.push("has_companion".to_string());
            }
            _ => {}
        }
    }
}

/// Extract primary constructor parameters as class attributes.
fn extract_primary_constructor(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "class_parameter" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    class_def
                        .attributes
                        .push(get_node_text(&id, source).to_string());
                }
            }
            "class_parameters" => {
                // tree-sitter-kotlin-ng nests class_parameter inside class_parameters
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "class_parameter" {
                        if let Some(id) = find_child_by_type(&inner, "identifier") {
                            class_def
                                .attributes
                                .push(get_node_text(&id, source).to_string());
                        }
                    }
                }
            }
            _ => {}
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

    let mut found_fun_keyword = false;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "fun" => {
                found_fun_keyword = true;
            }
            "identifier" | "simple_identifier" => {
                if func_def.name.is_empty() && found_fun_keyword {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "function_value_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "user_type" | "nullable_type" => {
                func_def.return_type = Some(get_node_text(&child, source).to_string());
            }
            "function_body" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "kotlin");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);
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
        if child.kind() == "parameter" {
            let mut param = ParameterDef::default();
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "identifier" | "simple_identifier" => {
                        if param.name.is_empty() {
                            param.name = get_node_text(&inner, source).to_string();
                        }
                    }
                    "user_type" | "nullable_type" => {
                        param.type_annotation = Some(get_node_text(&inner, source).to_string());
                    }
                    _ => {}
                }
            }
            if !param.name.is_empty() {
                params.push(param);
            }
        }
    }

    params
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
        "identifier" | "simple_identifier" => {
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
package com.example

fun greet(name: String): String {
    return "Hello, $name"
}
"#;
        let result = parse(source, "Main.kt").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "greet");
        assert_eq!(result.functions[0].parameters.len(), 1);
    }

    #[test]
    fn test_parse_class() {
        let source = r#"
class User(val name: String, val age: Int) {
    fun display() {
        println(name)
    }
}
"#;
        let result = parse(source, "User.kt").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "User");
        assert!(!result.classes[0].methods.is_empty());
    }

    #[test]
    fn test_parse_import() {
        let source = r#"
import kotlin.collections.List
import java.io.File
"#;
        let result = parse(source, "Test.kt").unwrap();
        assert_eq!(result.imports.len(), 2);
    }

    #[test]
    fn test_parse_empty() {
        let source = "";
        let result = parse(source, "empty.kt").unwrap();
        assert!(result.functions.is_empty());
        assert!(result.classes.is_empty());
    }

    #[test]
    fn test_parse_object() {
        let source = r#"
object Singleton {
    fun doSomething() {}
}
"#;
        let result = parse(source, "Singleton.kt").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert!(result.classes[0].decorators.contains(&"object".to_string()));
    }
}
