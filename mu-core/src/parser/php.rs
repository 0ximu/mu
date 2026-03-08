//! PHP AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse PHP source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_php::LANGUAGE_PHP.into())
        .map_err(|e| format!("Failed to set PHP language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse PHP source")?;
    let root = tree.root_node();

    let name = extract_namespace(&root, source).unwrap_or_else(|| {
        Path::new(file_path)
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("unknown")
            .to_string()
    });

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "php".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    process_node(&root, source, &mut module);

    Ok(module)
}

/// Process nodes recursively.
fn process_node(node: &Node, source: &str, module: &mut ModuleDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "namespace_use_declaration" => {
                extract_use_declarations(&child, source, &mut module.imports);
            }
            "function_definition" => {
                module.functions.push(extract_function(&child, source));
            }
            "class_declaration" => {
                module.classes.push(extract_class(&child, source));
            }
            "interface_declaration" => {
                module.classes.push(extract_interface(&child, source));
            }
            "trait_declaration" => {
                module.classes.push(extract_trait(&child, source));
            }
            "enum_declaration" => {
                module.classes.push(extract_enum(&child, source));
            }
            "namespace_definition" => {
                if module.namespace.is_none() {
                    if let Some(ns_name) = find_child_by_type(&child, "namespace_name") {
                        module.namespace = Some(get_node_text(&ns_name, source).to_string());
                    }
                }
                // Process contents inside namespace
                process_node(&child, source, module);
            }
            "compound_statement" | "declaration_list" | "program" => {
                process_node(&child, source, module);
            }
            _ => {}
        }
    }
}

/// Extract namespace name.
fn extract_namespace(root: &Node, source: &str) -> Option<String> {
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        if child.kind() == "namespace_definition" {
            if let Some(ns_name) = find_child_by_type(&child, "namespace_name") {
                return Some(get_node_text(&ns_name, source).to_string());
            }
        }
        // Recurse into program node
        if child.kind() == "program" {
            if let Some(ns) = extract_namespace(&child, source) {
                return Some(ns);
            }
        }
    }
    None
}

/// Extract use declarations.
fn extract_use_declarations(node: &Node, source: &str, imports: &mut Vec<ImportDef>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "namespace_use_clause" => {
                // namespace_use_clause -> qualified_name
                if let Some(qn) = find_child_by_type(&child, "qualified_name") {
                    imports.push(ImportDef {
                        module: get_node_text(&qn, source).to_string(),
                        ..Default::default()
                    });
                } else if let Some(ns) = find_child_by_type(&child, "namespace_name") {
                    imports.push(ImportDef {
                        module: get_node_text(&ns, source).to_string(),
                        ..Default::default()
                    });
                }
            }
            "namespace_name" | "qualified_name" => {
                let module = get_node_text(&child, source).to_string();
                imports.push(ImportDef {
                    module,
                    ..Default::default()
                });
            }
            "namespace_use_group" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "namespace_use_group_clause" {
                        if let Some(name) = find_child_by_type(&inner, "namespace_name") {
                            imports.push(ImportDef {
                                module: get_node_text(&name, source).to_string(),
                                ..Default::default()
                            });
                        }
                    }
                }
            }
            _ => {}
        }
    }
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
            "name" => {
                func_def.name = get_node_text(&child, source).to_string();
            }
            "formal_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "union_type" | "named_type" | "optional_type" | "primitive_type" => {
                func_def.return_type = Some(get_node_text(&child, source).to_string());
            }
            "compound_statement" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "php");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);
            }
            _ => {}
        }
    }

    func_def
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
            "name" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "base_clause" => {
                extract_base_clause(&child, source, &mut class_def.bases);
            }
            "class_interface_clause" => {
                extract_base_clause(&child, source, &mut class_def.bases);
            }
            "declaration_list" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types = extract_referenced_types(
        type_strings.iter().map(|s| s.as_str()),
        &class_def.name,
        "php",
    );

    class_def
}

/// Extract interface declaration.
fn extract_interface(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };
    class_def.decorators.push("interface".to_string());

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "name" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "base_clause" => {
                extract_base_clause(&child, source, &mut class_def.bases);
            }
            "declaration_list" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types = extract_referenced_types(
        type_strings.iter().map(|s| s.as_str()),
        &class_def.name,
        "php",
    );

    class_def
}

/// Extract trait declaration.
fn extract_trait(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };
    class_def.decorators.push("trait".to_string());

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "name" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "declaration_list" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

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

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "name" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "enum_declaration_list" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "enum_case" {
                        if let Some(name) = find_child_by_type(&inner, "name") {
                            class_def
                                .attributes
                                .push(get_node_text(&name, source).to_string());
                        }
                    }
                }
            }
            _ => {}
        }
    }

    class_def
}

/// Extract modifiers.
fn extract_modifiers(node: &Node, source: &str, decorators: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "abstract_modifier" | "final_modifier" | "readonly_modifier" => {
                decorators.push(get_node_text(&child, source).to_string());
            }
            "visibility_modifier" => {
                decorators.push(get_node_text(&child, source).to_string());
            }
            "static_modifier" => {
                decorators.push("static".to_string());
            }
            _ => {}
        }
    }
}

/// Extract base clause (extends/implements).
fn extract_base_clause(node: &Node, source: &str, bases: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "name" | "qualified_name" | "namespace_name" => {
                bases.push(get_node_text(&child, source).to_string());
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
            "method_declaration" => {
                let mut method = extract_method(&child, source);
                method.is_method = true;
                class_def.methods.push(method);
            }
            "property_declaration" => {
                extract_property(&child, source, &mut class_def.attributes);
            }
            "use_declaration" => {
                // Trait usage
                if let Some(name) = find_child_by_type(&child, "name") {
                    class_def
                        .bases
                        .push(format!("use:{}", get_node_text(&name, source)));
                }
            }
            _ => {}
        }
    }
}

/// Extract method declaration.
fn extract_method(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    extract_modifiers(node, source, &mut func_def.decorators);

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "name" => {
                func_def.name = get_node_text(&child, source).to_string();
            }
            "formal_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "union_type" | "named_type" | "optional_type" | "primitive_type" => {
                func_def.return_type = Some(get_node_text(&child, source).to_string());
            }
            "compound_statement" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "php");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);
            }
            "static_modifier" => {
                func_def.is_static = true;
            }
            _ => {}
        }
    }

    if func_def.name == "__construct" {
        func_def.decorators.push("constructor".to_string());
    }

    func_def
}

/// Extract property declaration.
fn extract_property(node: &Node, source: &str, attributes: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "property_element" {
            if let Some(var) = find_child_by_type(&child, "variable_name") {
                let name = get_node_text(&var, source).to_string();
                // Strip the $ prefix
                let name = name.strip_prefix('$').unwrap_or(&name).to_string();
                attributes.push(name);
            }
        }
    }
}

/// Extract parameters.
fn extract_parameters(node: &Node, source: &str) -> Vec<ParameterDef> {
    let mut params = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "simple_parameter" || child.kind() == "variadic_parameter" {
            let mut param = ParameterDef {
                is_variadic: child.kind() == "variadic_parameter",
                ..Default::default()
            };

            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "variable_name" => {
                        let name = get_node_text(&inner, source).to_string();
                        param.name = name.strip_prefix('$').unwrap_or(&name).to_string();
                    }
                    "named_type" | "optional_type" | "union_type" | "primitive_type" => {
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
    match node.kind() {
        "function_call_expression" => {
            if let Some(call_site) = extract_function_call(node, source) {
                results.push(call_site);
            }
        }
        "member_call_expression" => {
            if let Some(call_site) = extract_member_call(node, source) {
                results.push(call_site);
            }
        }
        "scoped_call_expression" => {
            if let Some(call_site) = extract_scoped_call(node, source) {
                results.push(call_site);
            }
        }
        "object_creation_expression" => {
            if let Some(call_site) = extract_object_creation(node, source) {
                results.push(call_site);
            }
        }
        _ => {}
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        find_call_sites_recursive(&child, source, results);
    }
}

/// Extract function call.
fn extract_function_call(node: &Node, source: &str) -> Option<CallSiteDef> {
    let func_node = node.child(0)?;
    let callee = get_node_text(&func_node, source).to_string();
    Some(CallSiteDef {
        callee,
        line: get_start_line(node),
        is_method_call: false,
        receiver: None,
    })
}

/// Extract member call (->method()).
fn extract_member_call(node: &Node, source: &str) -> Option<CallSiteDef> {
    let line = get_start_line(node);
    let mut receiver = None;
    let mut method_name = None;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "variable_name" | "member_access_expression" | "scoped_property_access_expression" => {
                if receiver.is_none() {
                    receiver = Some(get_node_text(&child, source).to_string());
                }
            }
            "name" => {
                method_name = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    let method_name = method_name?;
    let callee = if let Some(ref recv) = receiver {
        format!("{}->{}", recv, method_name)
    } else {
        method_name
    };

    Some(CallSiteDef {
        callee,
        line,
        is_method_call: true,
        receiver,
    })
}

/// Extract scoped call (ClassName::method()).
fn extract_scoped_call(node: &Node, source: &str) -> Option<CallSiteDef> {
    let full_text = get_node_text(node, source);
    // Remove the arguments portion
    let callee = if let Some(paren_pos) = full_text.find('(') {
        full_text[..paren_pos].to_string()
    } else {
        full_text.to_string()
    };

    Some(CallSiteDef {
        callee,
        line: get_start_line(node),
        is_method_call: true,
        receiver: None,
    })
}

/// Extract object creation (new ClassName()).
fn extract_object_creation(node: &Node, source: &str) -> Option<CallSiteDef> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "name" || child.kind() == "qualified_name" {
            let class_name = get_node_text(&child, source).to_string();
            return Some(CallSiteDef {
                callee: format!("new {}", class_name),
                line: get_start_line(node),
                is_method_call: false,
                receiver: None,
            });
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_function() {
        let source = r#"<?php
function greet(string $name): string {
    return "Hello, " . $name;
}
"#;
        let result = parse(source, "greet.php").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "greet");
        assert_eq!(result.functions[0].parameters.len(), 1);
        assert_eq!(result.functions[0].parameters[0].name, "name");
    }

    #[test]
    fn test_parse_class() {
        let source = r#"<?php
class User {
    private string $name;

    public function __construct(string $name) {
        $this->name = $name;
    }

    public function getName(): string {
        return $this->name;
    }
}
"#;
        let result = parse(source, "User.php").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "User");
        assert!(!result.classes[0].methods.is_empty());
    }

    #[test]
    fn test_parse_interface() {
        let source = r#"<?php
interface Printable {
    public function toString(): string;
}
"#;
        let result = parse(source, "Printable.php").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert!(result.classes[0]
            .decorators
            .contains(&"interface".to_string()));
    }

    #[test]
    fn test_parse_empty() {
        let source = "<?php\n";
        let result = parse(source, "empty.php").unwrap();
        assert!(result.functions.is_empty());
        assert!(result.classes.is_empty());
    }

    #[test]
    fn test_parse_use() {
        let source = r#"<?php
use App\Models\User;
use App\Services\Auth;
"#;
        let result = parse(source, "Controller.php").unwrap();
        assert_eq!(result.imports.len(), 2);
    }

    #[test]
    fn test_parse_call_sites() {
        let source = r#"<?php
function process() {
    $x = calculate(10);
    $obj->doWork();
    echo strlen("test");
}
"#;
        let result = parse(source, "test.php").unwrap();
        assert_eq!(result.functions.len(), 1);
        let func = &result.functions[0];
        assert!(!func.call_sites.is_empty());
    }
}
