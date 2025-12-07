//! C# AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    count_lines, find_child_by_type, get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse C# source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_c_sharp::LANGUAGE.into())
        .map_err(|e| format!("Failed to set C# language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse C# source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "csharp".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    // Process compilation unit
    process_node(&root, source, &mut module);

    Ok(module)
}

/// Process a node recursively.
fn process_node(node: &Node, source: &str, module: &mut ModuleDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "using_directive" => {
                if let Some(import) = extract_using(&child, source) {
                    module.imports.push(import);
                }
            }
            "namespace_declaration" | "file_scoped_namespace_declaration" => {
                // Recursively process namespace contents
                process_node(&child, source, module);
            }
            "class_declaration" => {
                module.classes.push(extract_class(&child, source));
            }
            "interface_declaration" => {
                module.classes.push(extract_interface(&child, source));
            }
            "struct_declaration" => {
                module.classes.push(extract_struct(&child, source));
            }
            "enum_declaration" => {
                module.classes.push(extract_enum(&child, source));
            }
            "record_declaration" => {
                module.classes.push(extract_record(&child, source));
            }
            "declaration_list" => {
                process_node(&child, source, module);
            }
            _ => {}
        }
    }
}

/// Extract using directive.
fn extract_using(node: &Node, source: &str) -> Option<ImportDef> {
    let mut module = String::new();
    let mut alias = None;
    let mut is_static = false;
    let mut is_global = false;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "qualified_name" | "identifier" | "name" => {
                module = get_node_text(&child, source).to_string();
            }
            "name_equals" => {
                // using Alias = Namespace
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    alias = Some(get_node_text(&id, source).to_string());
                }
            }
            "static" => {
                is_static = true;
            }
            "global" => {
                is_global = true;
            }
            _ => {}
        }
    }

    if module.is_empty() {
        return None;
    }

    let mut import = ImportDef {
        module,
        alias,
        ..Default::default()
    };

    if is_static {
        import.names.push("static".to_string());
    }
    if is_global {
        import.names.push("global".to_string());
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

    extract_modifiers(node, source, &mut class_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "type_parameter_list" => {
                // Generic parameters
                let generics = get_node_text(&child, source);
                class_def.name.push_str(generics);
            }
            "base_list" => {
                extract_base_list(&child, source, &mut class_def.bases);
            }
            "declaration_list" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    class_def
}

/// Extract modifiers and attributes.
fn extract_modifiers(node: &Node, source: &str, decorators: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "modifier" => {
                decorators.push(get_node_text(&child, source).to_string());
            }
            "attribute_list" => {
                let mut inner_cursor = child.walk();
                for attr in child.children(&mut inner_cursor) {
                    if attr.kind() == "attribute" {
                        let text = get_node_text(&attr, source);
                        decorators.push(text.to_string());
                    }
                }
            }
            "public" | "private" | "protected" | "internal" | "static" | "abstract" | "sealed"
            | "partial" | "async" | "virtual" | "override" => {
                decorators.push(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }
}

/// Extract base list (inheritance).
fn extract_base_list(node: &Node, source: &str, bases: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "identifier"
            || child.kind() == "generic_name"
            || child.kind() == "qualified_name"
        {
            bases.push(get_node_text(&child, source).to_string());
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
            "property_declaration" => {
                class_def.methods.push(extract_property(&child, source));
            }
            "field_declaration" => {
                extract_fields(&child, source, &mut class_def.attributes);
            }
            "event_declaration" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    class_def
                        .attributes
                        .push(format!("event:{}", get_node_text(&id, source)));
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

    extract_modifiers(node, source, &mut func_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if func_def.name.is_empty() && func_def.return_type.is_some() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "predefined_type" | "nullable_type" | "array_type" | "generic_name"
            | "qualified_name" => {
                if func_def.return_type.is_none() {
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            "parameter_list" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "block" | "arrow_expression_clause" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "csharp");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    // Check for async/static
    if func_def.decorators.contains(&"async".to_string()) {
        func_def.is_async = true;
    }
    if func_def.decorators.contains(&"static".to_string()) {
        func_def.is_static = true;
    }

    func_def
}

/// Extract constructor.
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
            "parameter_list" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "block" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "csharp");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    func_def
}

/// Extract property declaration.
fn extract_property(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        is_method: true,
        is_property: true,
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    extract_modifiers(node, source, &mut func_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if func_def.name.is_empty() && func_def.return_type.is_some() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "predefined_type" | "nullable_type" | "array_type" | "generic_name" => {
                if func_def.return_type.is_none() {
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            "accessor_list" => {
                // Check for get/set
                let text = get_node_text(&child, source);
                if text.contains("get") {
                    func_def.decorators.push("get".to_string());
                }
                if text.contains("set") {
                    func_def.decorators.push("set".to_string());
                }
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
                    "identifier" => {
                        param.name = get_node_text(&inner, source).to_string();
                    }
                    "predefined_type" | "nullable_type" | "array_type" | "generic_name"
                    | "qualified_name" => {
                        param.type_annotation = Some(get_node_text(&inner, source).to_string());
                    }
                    "equals_value_clause" => {
                        param.default_value = Some(get_node_text(&inner, source).to_string());
                    }
                    "params" => {
                        param.is_variadic = true;
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

/// Extract fields.
fn extract_fields(node: &Node, source: &str, attributes: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "variable_declaration" {
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                if inner.kind() == "variable_declarator" {
                    if let Some(id) = find_child_by_type(&inner, "identifier") {
                        attributes.push(get_node_text(&id, source).to_string());
                    }
                }
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
            "base_list" => {
                extract_base_list(&child, source, &mut class_def.bases);
            }
            "declaration_list" => {
                // Interface methods
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "method_declaration" {
                        class_def.methods.push(extract_method(&inner, source));
                    } else if inner.kind() == "property_declaration" {
                        class_def.methods.push(extract_property(&inner, source));
                    }
                }
            }
            _ => {}
        }
    }

    class_def
}

/// Extract struct declaration.
fn extract_struct(node: &Node, source: &str) -> ClassDef {
    let mut class_def = extract_class(node, source);
    class_def.decorators.insert(0, "struct".to_string());
    class_def
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
            "enum_member_declaration_list" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "enum_member_declaration" {
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

    class_def
}

/// Extract record declaration.
fn extract_record(node: &Node, source: &str) -> ClassDef {
    let mut class_def = extract_class(node, source);
    class_def.decorators.insert(0, "record".to_string());
    class_def
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_class() {
        let source = r#"
using System;

public class Hello {
    public string Greet(string name) {
        return $"Hello, {name}!";
    }
}
"#;
        let result = parse(source, "Hello.cs").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "Hello");
        assert_eq!(result.classes[0].methods.len(), 1);
    }

    #[test]
    fn test_parse_interface() {
        let source = r#"
public interface IGreeter {
    string Greet(string name);
}
"#;
        let result = parse(source, "IGreeter.cs").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert!(result.classes[0]
            .decorators
            .contains(&"interface".to_string()));
    }

    #[test]
    fn test_parse_async() {
        let source = r#"
public class Service {
    public async Task<string> FetchAsync() {
        return await Task.FromResult("done");
    }
}
"#;
        let result = parse(source, "Service.cs").unwrap();
        assert!(result.classes[0].methods[0].is_async);
    }
}
