//! C++ AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse C++ source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_cpp::LANGUAGE.into())
        .map_err(|e| format!("Failed to set C++ language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse C++ source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "cpp".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    process_node(&root, source, &mut module);

    Ok(module)
}

/// Process a node recursively (handles namespaces).
fn process_node(node: &Node, source: &str, module: &mut ModuleDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "preproc_include" => {
                if let Some(import) = extract_include(&child, source) {
                    module.imports.push(import);
                }
            }
            "function_definition" => {
                module.functions.push(extract_function(&child, source));
            }
            "class_specifier" => {
                if let Some(class) = extract_class(&child, source) {
                    module.classes.push(class);
                }
            }
            "struct_specifier" => {
                if let Some(class) = extract_struct(&child, source) {
                    module.classes.push(class);
                }
            }
            "enum_specifier" => {
                if let Some(class) = extract_enum(&child, source) {
                    module.classes.push(class);
                }
            }
            "namespace_definition" => {
                // Extract namespace name
                if module.namespace.is_none() {
                    if let Some(id) = find_child_by_type(&child, "namespace_identifier") {
                        module.namespace = Some(get_node_text(&id, source).to_string());
                    } else if let Some(id) = find_child_by_type(&child, "identifier") {
                        module.namespace = Some(get_node_text(&id, source).to_string());
                    }
                }
                // Process contents inside namespace
                if let Some(body) = find_child_by_type(&child, "declaration_list") {
                    process_node(&body, source, module);
                }
            }
            "template_declaration" => {
                // Process the inner declaration
                process_template(&child, source, module);
            }
            _ => {}
        }
    }
}

/// Process template declaration to extract the inner class/function.
fn process_template(node: &Node, source: &str, module: &mut ModuleDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "class_specifier" => {
                if let Some(mut class) = extract_class(&child, source) {
                    class.decorators.push("template".to_string());
                    module.classes.push(class);
                }
            }
            "struct_specifier" => {
                if let Some(mut class) = extract_struct(&child, source) {
                    class.decorators.push("template".to_string());
                    module.classes.push(class);
                }
            }
            "function_definition" => {
                let mut func = extract_function(&child, source);
                func.decorators.push("template".to_string());
                module.functions.push(func);
            }
            _ => {}
        }
    }
}

/// Extract #include directive.
fn extract_include(node: &Node, source: &str) -> Option<ImportDef> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "string_literal" | "system_lib_string" => {
                let module = get_node_text(&child, source)
                    .trim_matches('"')
                    .trim_matches('<')
                    .trim_matches('>')
                    .to_string();
                return Some(ImportDef {
                    module,
                    ..Default::default()
                });
            }
            _ => {}
        }
    }
    None
}

/// Extract function definition.
fn extract_function(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "function_declarator" => {
                extract_function_declarator(&child, source, &mut func_def);
            }
            "primitive_type"
            | "type_identifier"
            | "sized_type_specifier"
            | "qualified_identifier"
            | "template_type" => {
                if func_def.return_type.is_none() {
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            "pointer_declarator" | "reference_declarator" => {
                if let Some(fd) = find_function_declarator_recursive(&child) {
                    extract_function_declarator(&fd, source, &mut func_def);
                }
            }
            "compound_statement" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "cpp");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);
            }
            "storage_class_specifier" => {
                let spec = get_node_text(&child, source);
                if spec == "static" {
                    func_def.is_static = true;
                }
                func_def.decorators.push(spec.to_string());
            }
            "virtual" => {
                func_def.decorators.push("virtual".to_string());
            }
            _ => {}
        }
    }

    func_def
}

/// Find function_declarator recursively.
fn find_function_declarator_recursive<'a>(node: &Node<'a>) -> Option<Node<'a>> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "function_declarator" {
            return Some(child);
        }
        if let Some(found) = find_function_declarator_recursive(&child) {
            return Some(found);
        }
    }
    None
}

/// Extract function name and parameters from function_declarator.
fn extract_function_declarator(node: &Node, source: &str, func_def: &mut FunctionDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" | "field_identifier" | "destructor_name" => {
                if func_def.name.is_empty() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "qualified_identifier" => {
                if func_def.name.is_empty() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "parameter_list" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            _ => {}
        }
    }
}

/// Extract parameters from parameter list.
fn extract_parameters(node: &Node, source: &str) -> Vec<ParameterDef> {
    let mut params = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "parameter_declaration" => {
                let mut param = ParameterDef::default();
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    match inner.kind() {
                        "identifier" => {
                            param.name = get_node_text(&inner, source).to_string();
                        }
                        "primitive_type"
                        | "type_identifier"
                        | "sized_type_specifier"
                        | "qualified_identifier"
                        | "template_type" => {
                            param.type_annotation = Some(get_node_text(&inner, source).to_string());
                        }
                        "reference_declarator" | "pointer_declarator" => {
                            if let Some(id) = find_child_by_type(&inner, "identifier") {
                                param.name = get_node_text(&id, source).to_string();
                            }
                            if let Some(ref ta) = param.type_annotation {
                                let suffix = if inner.kind() == "reference_declarator" {
                                    "&"
                                } else {
                                    "*"
                                };
                                param.type_annotation = Some(format!("{}{}", ta, suffix));
                            }
                        }
                        _ => {}
                    }
                }
                if !param.name.is_empty() || param.type_annotation.is_some() {
                    params.push(param);
                }
            }
            "optional_parameter_declaration" => {
                let mut param = ParameterDef::default();
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    match inner.kind() {
                        "identifier" => {
                            param.name = get_node_text(&inner, source).to_string();
                        }
                        "primitive_type" | "type_identifier" => {
                            param.type_annotation = Some(get_node_text(&inner, source).to_string());
                        }
                        _ => {}
                    }
                }
                if !param.name.is_empty() || param.type_annotation.is_some() {
                    params.push(param);
                }
            }
            _ => {}
        }
    }

    params
}

/// Extract class definition.
fn extract_class(node: &Node, source: &str) -> Option<ClassDef> {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };
    class_def.decorators.push("class".to_string());

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "name" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "base_class_clause" => {
                extract_base_classes(&child, source, &mut class_def.bases);
            }
            "field_declaration_list" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    if class_def.name.is_empty() {
        return None;
    }

    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types = extract_referenced_types(
        type_strings.iter().map(|s| s.as_str()),
        &class_def.name,
        "cpp",
    );

    Some(class_def)
}

/// Extract struct definition.
fn extract_struct(node: &Node, source: &str) -> Option<ClassDef> {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };
    class_def.decorators.push("struct".to_string());

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "name" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "base_class_clause" => {
                extract_base_classes(&child, source, &mut class_def.bases);
            }
            "field_declaration_list" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    if class_def.name.is_empty() {
        return None;
    }

    Some(class_def)
}

/// Extract enum definition.
fn extract_enum(node: &Node, source: &str) -> Option<ClassDef> {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };
    class_def.decorators.push("enum".to_string());

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "name" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "enumerator_list" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "enumerator" {
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

    if class_def.name.is_empty() {
        return None;
    }

    Some(class_def)
}

/// Extract base classes from base_class_clause.
fn extract_base_classes(node: &Node, source: &str, bases: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "qualified_identifier" | "template_type" => {
                bases.push(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }
}

/// Extract class body members.
fn extract_class_body(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "function_definition" => {
                let mut method = extract_function(&child, source);
                method.is_method = true;
                class_def.methods.push(method);
            }
            "declaration" => {
                // Could be method declaration or field
                if has_function_declarator_in_node(&child) {
                    let mut method = extract_method_declaration(&child, source);
                    method.is_method = true;
                    class_def.methods.push(method);
                } else {
                    extract_field_declaration(&child, source, &mut class_def.attributes);
                }
            }
            "field_declaration" => {
                extract_field_declaration(&child, source, &mut class_def.attributes);
            }
            _ => {}
        }
    }
}

/// Check if a node contains a function declarator.
fn has_function_declarator_in_node(node: &Node<'_>) -> bool {
    find_function_declarator_recursive(node).is_some()
}

/// Extract a method declaration (no body).
fn extract_method_declaration(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "function_declarator" => {
                extract_function_declarator(&child, source, &mut func_def);
            }
            "primitive_type"
            | "type_identifier"
            | "sized_type_specifier"
            | "qualified_identifier"
            | "template_type" => {
                if func_def.return_type.is_none() {
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            "virtual" => {
                func_def.decorators.push("virtual".to_string());
            }
            _ => {}
        }
    }

    func_def
}

/// Extract field declarations.
fn extract_field_declaration(node: &Node, source: &str, attributes: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "field_identifier" | "identifier" => {
                let name = get_node_text(&child, source);
                // Skip type names
                if !name.is_empty() {
                    attributes.push(name.to_string());
                }
            }
            _ => {}
        }
    }
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

/// Extract a single call site from a call_expression node.
fn extract_call_site(node: &Node, source: &str) -> Option<CallSiteDef> {
    let func_node = node.child(0)?;
    let line = get_start_line(node);

    match func_node.kind() {
        "identifier" | "qualified_identifier" => {
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        "field_expression" => {
            let full_text = get_node_text(&func_node, source);
            let operand = func_node
                .child_by_field_name("argument")
                .map(|n| get_node_text(&n, source).to_string());
            Some(CallSiteDef {
                callee: full_text.to_string(),
                line,
                is_method_call: true,
                receiver: operand,
            })
        }
        "template_function" => {
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
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
#include <iostream>

int add(int a, int b) {
    return a + b;
}
"#;
        let result = parse(source, "math.cpp").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "add");
        assert_eq!(result.functions[0].parameters.len(), 2);
    }

    #[test]
    fn test_parse_class() {
        let source = r#"
class Animal {
public:
    virtual void speak();
    int age;
};
"#;
        let result = parse(source, "animal.cpp").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "Animal");
        assert!(result.classes[0].decorators.contains(&"class".to_string()));
    }

    #[test]
    fn test_parse_class_inheritance() {
        let source = r#"
class Dog : public Animal {
public:
    void speak();
};
"#;
        let result = parse(source, "dog.cpp").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "Dog");
        assert!(!result.classes[0].bases.is_empty());
    }

    #[test]
    fn test_parse_namespace() {
        let source = r#"
namespace myns {
    class Foo {};
}
"#;
        let result = parse(source, "foo.cpp").unwrap();
        assert_eq!(result.namespace.as_deref(), Some("myns"));
        assert_eq!(result.classes.len(), 1);
    }

    #[test]
    fn test_parse_include() {
        let source = r#"
#include <iostream>
#include "myheader.h"
"#;
        let result = parse(source, "main.cpp").unwrap();
        assert_eq!(result.imports.len(), 2);
    }

    #[test]
    fn test_parse_empty() {
        let source = "";
        let result = parse(source, "empty.cpp").unwrap();
        assert!(result.functions.is_empty());
        assert!(result.classes.is_empty());
    }

    #[test]
    fn test_parse_call_sites() {
        let source = r#"
void process() {
    int x = calculate(10);
    std::cout << "hello";
    obj.doWork();
}
"#;
        let result = parse(source, "test.cpp").unwrap();
        assert_eq!(result.functions.len(), 1);
        let func = &result.functions[0];
        assert!(func.call_sites.iter().any(|c| c.callee == "calculate"));
    }
}
