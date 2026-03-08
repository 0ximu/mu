//! C AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    count_lines, find_child_by_type, get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse C source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_c::LANGUAGE.into())
        .map_err(|e| format!("Failed to set C language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse C source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "c".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match child.kind() {
            "preproc_include" => {
                if let Some(import) = extract_include(&child, source) {
                    module.imports.push(import);
                }
            }
            "function_definition" => {
                module.functions.push(extract_function(&child, source));
            }
            "declaration" => {
                // Could be a function prototype or variable declaration
                if has_function_declarator(&child) {
                    module
                        .functions
                        .push(extract_function_prototype(&child, source));
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
            "type_definition" => {
                // typedef struct/enum
                if let Some(class) = extract_typedef(&child, source) {
                    module.classes.push(class);
                }
            }
            _ => {}
        }
    }

    Ok(module)
}

/// Check if a declaration node contains a function declarator.
fn has_function_declarator(node: &Node<'_>) -> bool {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "function_declarator" {
            return true;
        }
        if has_function_declarator(&child) {
            return true;
        }
    }
    false
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
            "primitive_type" | "type_identifier" | "sized_type_specifier" => {
                if func_def.return_type.is_none() {
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            "pointer_declarator" => {
                // Return type is a pointer
                if let Some(fd) = find_function_declarator_recursive(&child) {
                    extract_function_declarator(&fd, source, &mut func_def);
                }
                if func_def.return_type.is_some() {
                    func_def.return_type = Some(format!(
                        "{}*",
                        func_def.return_type.as_deref().unwrap_or("")
                    ));
                }
            }
            "compound_statement" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "c");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);
            }
            _ => {}
        }
    }

    func_def
}

/// Find function_declarator recursively (e.g. inside pointer_declarator).
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
            "identifier" => {
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

/// Extract a function prototype from a declaration.
fn extract_function_prototype(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };
    func_def.decorators.push("prototype".to_string());

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "function_declarator" => {
                extract_function_declarator(&child, source, &mut func_def);
            }
            "primitive_type" | "type_identifier" | "sized_type_specifier" => {
                if func_def.return_type.is_none() {
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            _ => {}
        }
    }

    func_def
}

/// Extract parameters from parameter list.
fn extract_parameters(node: &Node, source: &str) -> Vec<ParameterDef> {
    let mut params = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "parameter_declaration" {
            let mut param = ParameterDef::default();
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "identifier" => {
                        param.name = get_node_text(&inner, source).to_string();
                    }
                    "primitive_type" | "type_identifier" | "sized_type_specifier" => {
                        param.type_annotation = Some(get_node_text(&inner, source).to_string());
                    }
                    "pointer_declarator" => {
                        if let Some(id) = find_child_by_type(&inner, "identifier") {
                            param.name = get_node_text(&id, source).to_string();
                        }
                        if let Some(ref ta) = param.type_annotation {
                            param.type_annotation = Some(format!("{}*", ta));
                        }
                    }
                    _ => {}
                }
            }
            if !param.name.is_empty() || param.type_annotation.is_some() {
                params.push(param);
            }
        }
    }

    params
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
            "type_identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "field_declaration_list" => {
                extract_fields(&child, source, &mut class_def.attributes);
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
            "type_identifier" => {
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

/// Extract typedef struct/enum.
fn extract_typedef(node: &Node, source: &str) -> Option<ClassDef> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "struct_specifier" => {
                let mut class = extract_struct(&child, source).unwrap_or_else(|| ClassDef {
                    start_line: get_start_line(node),
                    end_line: get_end_line(node),
                    ..Default::default()
                });
                class.decorators.push("typedef".to_string());
                if !class.decorators.contains(&"struct".to_string()) {
                    class.decorators.push("struct".to_string());
                }
                // Get typedef name from type_identifier after the struct
                if class.name.is_empty() {
                    if let Some(id) = find_typedef_name(node, source) {
                        class.name = id;
                    }
                }
                if !class.name.is_empty() {
                    return Some(class);
                }
            }
            "enum_specifier" => {
                let mut class = extract_enum(&child, source).unwrap_or_else(|| ClassDef {
                    start_line: get_start_line(node),
                    end_line: get_end_line(node),
                    ..Default::default()
                });
                class.decorators.push("typedef".to_string());
                if class.name.is_empty() {
                    if let Some(id) = find_typedef_name(node, source) {
                        class.name = id;
                    }
                }
                if !class.name.is_empty() {
                    return Some(class);
                }
            }
            _ => {}
        }
    }
    None
}

/// Find the typedef alias name.
fn find_typedef_name(node: &Node, source: &str) -> Option<String> {
    let mut cursor = node.walk();
    let children: Vec<_> = node.children(&mut cursor).collect();
    // The typedef name is typically the last type_identifier
    for child in children.iter().rev() {
        if child.kind() == "type_identifier" {
            return Some(get_node_text(child, source).to_string());
        }
    }
    None
}

/// Extract struct fields.
fn extract_fields(node: &Node, source: &str, attributes: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "field_declaration" {
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                if inner.kind() == "field_identifier" {
                    attributes.push(get_node_text(&inner, source).to_string());
                }
            }
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
        "identifier" => {
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
#include <stdio.h>

int add(int a, int b) {
    return a + b;
}
"#;
        let result = parse(source, "math.c").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "add");
        assert_eq!(result.functions[0].parameters.len(), 2);
    }

    #[test]
    fn test_parse_struct() {
        let source = r#"
struct Point {
    int x;
    int y;
};
"#;
        let result = parse(source, "point.c").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "Point");
        assert!(result.classes[0].decorators.contains(&"struct".to_string()));
    }

    #[test]
    fn test_parse_include() {
        let source = r#"
#include <stdio.h>
#include "myheader.h"
"#;
        let result = parse(source, "main.c").unwrap();
        assert_eq!(result.imports.len(), 2);
        assert_eq!(result.imports[0].module, "stdio.h");
        assert_eq!(result.imports[1].module, "myheader.h");
    }

    #[test]
    fn test_parse_empty() {
        let source = "";
        let result = parse(source, "empty.c").unwrap();
        assert!(result.functions.is_empty());
        assert!(result.classes.is_empty());
    }

    #[test]
    fn test_parse_call_sites() {
        let source = r#"
void process(void) {
    int x = calculate(10);
    printf("result: %d\n", x);
}
"#;
        let result = parse(source, "test.c").unwrap();
        assert_eq!(result.functions.len(), 1);
        let func = &result.functions[0];
        assert!(func.call_sites.len() >= 2);
        assert!(func.call_sites.iter().any(|c| c.callee == "calculate"));
        assert!(func.call_sites.iter().any(|c| c.callee == "printf"));
    }
}
