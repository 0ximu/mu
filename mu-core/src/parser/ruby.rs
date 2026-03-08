//! Ruby AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse Ruby source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_ruby::LANGUAGE.into())
        .map_err(|e| format!("Failed to set Ruby language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse Ruby source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "ruby".to_string(),
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
            "call" => {
                // Check for require/require_relative
                if let Some(import) = extract_require(&child, source) {
                    module.imports.push(import);
                }
            }
            "class" => {
                module.classes.push(extract_class(&child, source));
            }
            "module" => {
                // Extract module name and process its body
                if module.namespace.is_none() {
                    if let Some(name_node) = find_child_by_type(&child, "constant") {
                        module.namespace = Some(get_node_text(&name_node, source).to_string());
                    } else if let Some(name_node) = find_child_by_type(&child, "scope_resolution") {
                        module.namespace = Some(get_node_text(&name_node, source).to_string());
                    }
                }
                if let Some(body) = find_child_by_type(&child, "body_statement") {
                    process_node(&body, source, module);
                }
            }
            "method" => {
                module.functions.push(extract_method(&child, source));
            }
            "singleton_method" => {
                let mut func = extract_method(&child, source);
                func.is_static = true;
                func.decorators.push("self".to_string());
                module.functions.push(func);
            }
            _ => {}
        }
    }
}

/// Extract require/require_relative as imports.
fn extract_require(node: &Node, source: &str) -> Option<ImportDef> {
    let method_node = node.child(0)?;
    let method_name = get_node_text(&method_node, source);

    if method_name != "require" && method_name != "require_relative" {
        return None;
    }

    // Get the argument (the required module name)
    if let Some(args) = find_child_by_type(node, "argument_list") {
        let mut cursor = args.walk();
        for child in args.children(&mut cursor) {
            if child.kind() == "string" || child.kind() == "string_content" {
                let module = get_node_text(&child, source)
                    .trim_matches('"')
                    .trim_matches('\'')
                    .to_string();
                if !module.is_empty() {
                    let mut import = ImportDef {
                        module,
                        ..Default::default()
                    };
                    if method_name == "require_relative" {
                        import.alias = Some("relative".to_string());
                    }
                    return Some(import);
                }
            }
        }
    }

    None
}

/// Extract class definition.
fn extract_class(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "constant" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "scope_resolution" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "superclass" => {
                // The superclass node contains the parent class
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "constant" || inner.kind() == "scope_resolution" {
                        class_def
                            .bases
                            .push(get_node_text(&inner, source).to_string());
                    }
                }
            }
            "body_statement" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types = extract_referenced_types(
        type_strings.iter().map(|s| s.as_str()),
        &class_def.name,
        "ruby",
    );

    class_def
}

/// Extract class body.
fn extract_class_body(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "method" => {
                let mut method = extract_method(&child, source);
                method.is_method = true;
                class_def.methods.push(method);
            }
            "singleton_method" => {
                let mut method = extract_method(&child, source);
                method.is_method = true;
                method.is_static = true;
                method.decorators.push("self".to_string());
                class_def.methods.push(method);
            }
            "call" => {
                // Check for attr_accessor, attr_reader, attr_writer, include, extend
                let method_text = child
                    .child(0)
                    .map(|n| get_node_text(&n, source))
                    .unwrap_or("");
                match method_text {
                    "attr_accessor" | "attr_reader" | "attr_writer" => {
                        extract_attr_symbols(&child, source, &mut class_def.attributes);
                    }
                    "include" | "extend" | "prepend" => {
                        extract_mixin_modules(&child, source, &mut class_def.bases);
                    }
                    _ => {}
                }
            }
            "assignment" => {
                // Class-level instance variable assignments (like @@var)
                if let Some(left) = child.child(0) {
                    let text = get_node_text(&left, source);
                    if text.starts_with('@') {
                        class_def.attributes.push(text.to_string());
                    }
                }
            }
            _ => {}
        }
    }
}

/// Extract attr_* symbols as attributes.
fn extract_attr_symbols(node: &Node, source: &str, attributes: &mut Vec<String>) {
    if let Some(args) = find_child_by_type(node, "argument_list") {
        let mut cursor = args.walk();
        for child in args.children(&mut cursor) {
            if child.kind() == "simple_symbol" {
                let sym = get_node_text(&child, source)
                    .trim_start_matches(':')
                    .to_string();
                attributes.push(sym);
            }
        }
    }
}

/// Extract include/extend module references.
fn extract_mixin_modules(node: &Node, source: &str, bases: &mut Vec<String>) {
    if let Some(args) = find_child_by_type(node, "argument_list") {
        let mut cursor = args.walk();
        for child in args.children(&mut cursor) {
            if child.kind() == "constant" || child.kind() == "scope_resolution" {
                let method_text = node
                    .child(0)
                    .map(|n| get_node_text(&n, source))
                    .unwrap_or("");
                bases.push(format!("{}:{}", method_text, get_node_text(&child, source)));
            }
        }
    }
}

/// Extract method definition.
fn extract_method(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if func_def.name.is_empty() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "method_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "body_statement" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "ruby");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);
            }
            _ => {}
        }
    }

    if func_def.name == "initialize" {
        func_def.decorators.push("constructor".to_string());
    }

    func_def
}

/// Extract parameters.
fn extract_parameters(node: &Node, source: &str) -> Vec<ParameterDef> {
    let mut params = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                params.push(ParameterDef {
                    name: get_node_text(&child, source).to_string(),
                    ..Default::default()
                });
            }
            "optional_parameter" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    params.push(ParameterDef {
                        name: get_node_text(&id, source).to_string(),
                        ..Default::default()
                    });
                }
            }
            "splat_parameter" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    params.push(ParameterDef {
                        name: get_node_text(&id, source).to_string(),
                        is_variadic: true,
                        ..Default::default()
                    });
                }
            }
            "keyword_parameter" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    params.push(ParameterDef {
                        name: get_node_text(&id, source).to_string(),
                        ..Default::default()
                    });
                }
            }
            "block_parameter" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    params.push(ParameterDef {
                        name: format!("&{}", get_node_text(&id, source)),
                        ..Default::default()
                    });
                }
            }
            _ => {}
        }
    }

    params
}

/// Extract all call sites from a method body.
fn extract_call_sites(body: &Node, source: &str) -> Vec<CallSiteDef> {
    let mut call_sites = Vec::new();
    find_call_sites_recursive(body, source, &mut call_sites);
    call_sites
}

/// Recursively search for call expressions in AST.
fn find_call_sites_recursive(node: &Node, source: &str, results: &mut Vec<CallSiteDef>) {
    if node.kind() == "call" {
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
    let line = get_start_line(node);

    let mut receiver: Option<String> = None;
    let mut method_name: Option<String> = None;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" | "constant" => {
                if receiver.is_none() && method_name.is_none() {
                    method_name = Some(get_node_text(&child, source).to_string());
                }
            }
            "." => {
                // The previous child was receiver, next will be method
                if let Some(mn) = method_name.take() {
                    receiver = Some(mn);
                }
            }
            "scope_resolution" => {
                receiver = Some(get_node_text(&child, source).to_string());
            }
            _ => {
                if method_name.is_none() && child.kind() != "argument_list" {
                    // Could be a complex receiver
                    let text = get_node_text(&child, source);
                    if !text.is_empty()
                        && child.kind() != "("
                        && child.kind() != ")"
                        && receiver.is_none()
                    {
                        receiver = Some(text.to_string());
                    }
                }
            }
        }
    }

    // If we saw a dot, the second identifier is the method name
    // Re-scan for method name after dot
    if receiver.is_some() && method_name.is_none() {
        let mut found_dot = false;
        let mut cursor2 = node.walk();
        for child in node.children(&mut cursor2) {
            if child.kind() == "." {
                found_dot = true;
            } else if found_dot && (child.kind() == "identifier" || child.kind() == "constant") {
                method_name = Some(get_node_text(&child, source).to_string());
                break;
            }
        }
    }

    let method_name = method_name?;

    let callee = if let Some(ref recv) = receiver {
        format!("{}.{}", recv, method_name)
    } else {
        method_name
    };

    Some(CallSiteDef {
        callee,
        line,
        is_method_call: receiver.is_some(),
        receiver,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_method() {
        let source = r#"
def greet(name)
  "Hello, #{name}"
end
"#;
        let result = parse(source, "main.rb").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "greet");
        assert_eq!(result.functions[0].parameters.len(), 1);
    }

    #[test]
    fn test_parse_class() {
        let source = r#"
class User < BaseModel
  attr_accessor :name, :email

  def initialize(name, email)
    @name = name
    @email = email
  end

  def display
    puts @name
  end
end
"#;
        let result = parse(source, "user.rb").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "User");
        assert!(!result.classes[0].bases.is_empty());
        assert!(!result.classes[0].methods.is_empty());
    }

    #[test]
    fn test_parse_require() {
        let source = r#"
require 'json'
require_relative 'helper'
"#;
        let result = parse(source, "app.rb").unwrap();
        assert_eq!(result.imports.len(), 2);
    }

    #[test]
    fn test_parse_module() {
        let source = r#"
module MyApp
  class Config
  end
end
"#;
        let result = parse(source, "config.rb").unwrap();
        assert_eq!(result.namespace.as_deref(), Some("MyApp"));
        assert_eq!(result.classes.len(), 1);
    }

    #[test]
    fn test_parse_empty() {
        let source = "";
        let result = parse(source, "empty.rb").unwrap();
        assert!(result.functions.is_empty());
        assert!(result.classes.is_empty());
    }

    #[test]
    fn test_parse_call_sites() {
        let source = r#"
def process
  x = calculate(10)
  puts x
end
"#;
        let result = parse(source, "test.rb").unwrap();
        assert_eq!(result.functions.len(), 1);
        let func = &result.functions[0];
        assert!(!func.call_sites.is_empty());
    }
}
