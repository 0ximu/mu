//! Java AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse Java source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_java::LANGUAGE.into())
        .map_err(|e| format!("Failed to set Java language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse Java source")?;
    let root = tree.root_node();

    // Get module name from package or filename (prefer package name alone, like Python impl)
    let package_name = extract_package_name(&root, source);
    let class_name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    // Use just the package name if available (consistent with Python parser)
    let name = package_name.unwrap_or(class_name);

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
    let mut is_wildcard = false;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "scoped_identifier" | "identifier" => {
                module = get_node_text(&child, source).to_string();
            }
            "asterisk" => {
                is_wildcard = true;
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

    // Handle wildcard imports
    if is_wildcard {
        module.push_str(".*");
    }

    let mut import = ImportDef {
        module,
        ..Default::default()
    };

    // Mark static imports with alias (consistent with Python parser)
    if is_static {
        import.alias = Some("static".to_string());
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
                // Generic type parameters - add as decorator like "generic:<T>"
                let generics = get_node_text(&child, source);
                if !generics.is_empty() {
                    class_def.decorators.push(format!("generic:{}", generics));
                }
            }
            "superclass" => {
                // Get the full type including generics (e.g., AbstractList<E>)
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    match inner.kind() {
                        "type_identifier" | "generic_type" => {
                            class_def
                                .bases
                                .push(get_node_text(&inner, source).to_string());
                            break;
                        }
                        _ => {}
                    }
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

    // Collect type annotations from all methods and extract referenced types
    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types = extract_referenced_types(
        type_strings.iter().map(|s| s.as_str()),
        &class_def.name,
        "java",
    );

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
                            // Keep the @ prefix for annotations
                            decorators.push(get_node_text(&inner, source).to_string());
                        }
                        "public" | "private" | "protected" | "static" | "final" | "abstract" => {
                            decorators.push(get_node_text(&inner, source).to_string());
                        }
                        _ => {}
                    }
                }
            }
            "marker_annotation" | "annotation" => {
                // Keep the @ prefix for annotations
                decorators.push(get_node_text(&child, source).to_string());
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
                    class_def
                        .attributes
                        .push(format!("class:{}", get_node_text(&id, source)));
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
                func_def.call_sites = extract_call_sites(&child, source);
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
        if child.kind() == "formal_parameter" || child.kind() == "spread_parameter" {
            let mut param = ParameterDef::default();
            let is_variadic = child.kind() == "spread_parameter";

            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                match inner.kind() {
                    "identifier" => {
                        param.name = get_node_text(&inner, source).to_string();
                    }
                    "variable_declarator" => {
                        // For spread parameters, the name is in a variable_declarator
                        if let Some(id) = find_child_by_type(&inner, "identifier") {
                            param.name = get_node_text(&id, source).to_string();
                        } else {
                            // Sometimes the variable_declarator just contains the name directly
                            param.name = get_node_text(&inner, source).to_string();
                        }
                    }
                    "type_identifier" | "generic_type" | "array_type" => {
                        let type_text = get_node_text(&inner, source);
                        if is_variadic {
                            param.type_annotation = Some(format!("{}...", type_text));
                        } else {
                            param.type_annotation = Some(type_text.to_string());
                        }
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

/// Extract all call sites from a method body node.
fn extract_call_sites(body: &Node, source: &str) -> Vec<CallSiteDef> {
    let mut call_sites = Vec::new();
    find_call_sites_recursive(body, source, &mut call_sites);
    call_sites
}

/// Recursively search for call expressions in AST.
fn find_call_sites_recursive(node: &Node, source: &str, results: &mut Vec<CallSiteDef>) {
    match node.kind() {
        "method_invocation" => {
            if let Some(call_site) = extract_method_invocation(node, source) {
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

/// Extract a call site from a method_invocation node.
/// Handles patterns like: foo(), bar.foo(), this.foo(), super.foo()
fn extract_method_invocation(node: &Node, source: &str) -> Option<CallSiteDef> {
    let line = get_start_line(node);

    // Method invocation structure in Java tree-sitter:
    // - Simple call: identifier (method name) + argument_list
    // - Object call: object + "." + identifier (method name) + argument_list
    // - Chained: method_invocation + "." + identifier (method name) + argument_list

    let mut method_name: Option<String> = None;
    let mut receiver: Option<String> = None;

    let mut cursor = node.walk();
    let children: Vec<_> = node.children(&mut cursor).collect();

    // Find the method name - it's typically the last identifier before argument_list
    // and the receiver is what comes before the dot
    for (i, child) in children.iter().enumerate() {
        match child.kind() {
            "identifier" => {
                // Check if this is the method name (followed by argument_list or end)
                let is_method = children
                    .get(i + 1)
                    .map(|next| next.kind() == "argument_list" || next.kind() == "(")
                    .unwrap_or(true);

                if is_method {
                    method_name = Some(get_node_text(child, source).to_string());
                } else {
                    // This is a simple receiver (e.g., "list" in "list.add()")
                    receiver = Some(get_node_text(child, source).to_string());
                }
            }
            "field_access" | "method_invocation" => {
                // Complex receiver like "this.field" or chained call "foo.bar()"
                receiver = Some(get_node_text(child, source).to_string());
            }
            "this" | "super" => {
                receiver = Some(get_node_text(child, source).to_string());
            }
            _ => {}
        }
    }

    let method_name = method_name?;

    // Check if it's a this/super call
    let is_this_call = receiver
        .as_ref()
        .map(|r| r == "this" || r == "super")
        .unwrap_or(false);

    Some(CallSiteDef {
        callee: if is_this_call {
            method_name
        } else if let Some(ref recv) = receiver {
            format!("{}.{}", recv, method_name)
        } else {
            method_name
        },
        line,
        is_method_call: receiver.is_some(),
        receiver,
    })
}

/// Extract a call site from an object_creation_expression node.
/// Handles patterns like: new Foo(), new Bar<T>(), new pkg.Baz()
fn extract_object_creation(node: &Node, source: &str) -> Option<CallSiteDef> {
    let line = get_start_line(node);

    // Find the type being constructed
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" => {
                let class_name = get_node_text(&child, source).to_string();
                return Some(CallSiteDef {
                    callee: format!("new {}", class_name),
                    line,
                    is_method_call: false,
                    receiver: None,
                });
            }
            "generic_type" => {
                // Generic type like List<String> - extract the base type
                if let Some(type_id) = find_child_by_type(&child, "type_identifier") {
                    let class_name = get_node_text(&type_id, source).to_string();
                    return Some(CallSiteDef {
                        callee: format!("new {}", class_name),
                        line,
                        is_method_call: false,
                        receiver: None,
                    });
                }
            }
            "scoped_type_identifier" => {
                // Qualified type like com.example.Foo
                let full_name = get_node_text(&child, source).to_string();
                return Some(CallSiteDef {
                    callee: format!("new {}", full_name),
                    line,
                    is_method_call: false,
                    receiver: None,
                });
            }
            _ => {}
        }
    }

    None
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

    // Collect type annotations from all methods and extract referenced types
    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types = extract_referenced_types(
        type_strings.iter().map(|s| s.as_str()),
        &class_def.name,
        "java",
    );

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
        assert!(result.classes[0]
            .decorators
            .contains(&"interface".to_string()));
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

    #[test]
    fn test_extract_call_sites() {
        let source = r#"
public class Service {
    public void process(Data data) {
        Data validated = validate(data);
        Result result = this.transform(validated);
        helper.save(result);
        return finish(result);
    }
}
"#;
        let result = parse(source, "Service.java").unwrap();
        assert_eq!(result.classes.len(), 1);
        let method = &result.classes[0].methods[0];
        assert!(
            method.call_sites.len() >= 3,
            "Expected at least 3 call sites, got {}",
            method.call_sites.len()
        );

        // Check we captured validate() call
        assert!(
            method.call_sites.iter().any(|c| c.callee == "validate"),
            "Should find validate() call"
        );

        // Check we captured helper.save() call
        assert!(
            method.call_sites.iter().any(|c| c.callee == "helper.save"),
            "Should find helper.save() call"
        );
    }

    #[test]
    fn test_method_call_detection() {
        let source = r#"
public class MyClass {
    public void doWork() {
        this.helper();
        super.init();
        other.process();
    }
}
"#;
        let result = parse(source, "MyClass.java").unwrap();
        let method = &result.classes[0].methods[0];

        // this.helper() should be detected as method call with receiver "this"
        let this_call = method.call_sites.iter().find(|c| c.callee == "helper");
        assert!(this_call.is_some(), "Should find this.helper() call");
        assert!(this_call.unwrap().is_method_call);
        assert_eq!(this_call.unwrap().receiver, Some("this".to_string()));

        // super.init() should be detected as method call with receiver "super"
        let super_call = method.call_sites.iter().find(|c| c.callee == "init");
        assert!(super_call.is_some(), "Should find super.init() call");
        assert_eq!(super_call.unwrap().receiver, Some("super".to_string()));
    }

    #[test]
    fn test_constructor_call_sites() {
        let source = r#"
public class Builder {
    private List<String> items;

    public Builder() {
        this.items = new ArrayList<>();
        initialize();
    }
}
"#;
        let result = parse(source, "Builder.java").unwrap();
        let constructor = result.classes[0]
            .methods
            .iter()
            .find(|m| m.decorators.contains(&"constructor".to_string()));
        assert!(constructor.is_some(), "Should find constructor");

        let call_sites = &constructor.unwrap().call_sites;
        assert!(
            call_sites.len() >= 2,
            "Expected at least 2 call sites in constructor, got {}",
            call_sites.len()
        );

        // Check for new ArrayList<>() call
        assert!(
            call_sites.iter().any(|c| c.callee == "new ArrayList"),
            "Should find new ArrayList<>() call"
        );

        // Check for initialize() call
        assert!(
            call_sites.iter().any(|c| c.callee == "initialize"),
            "Should find initialize() call"
        );
    }

    #[test]
    fn test_object_creation_expression() {
        let source = r#"
public class Factory {
    public Object create(String type) {
        if (type.equals("A")) {
            return new TypeA();
        }
        return new com.example.TypeB();
    }
}
"#;
        let result = parse(source, "Factory.java").unwrap();
        let method = &result.classes[0].methods[0];

        // Check for new TypeA() call
        assert!(
            method.call_sites.iter().any(|c| c.callee == "new TypeA"),
            "Should find new TypeA() call"
        );

        // Check for new com.example.TypeB() call (qualified type)
        assert!(
            method
                .call_sites
                .iter()
                .any(|c| c.callee == "new com.example.TypeB"),
            "Should find new com.example.TypeB() call"
        );
    }

    #[test]
    fn test_chained_method_calls() {
        let source = r#"
public class Stream {
    public List<String> transform(List<String> input) {
        return input.stream()
            .filter(x -> x.length() > 0)
            .map(String::toUpperCase)
            .collect(Collectors.toList());
    }
}
"#;
        let result = parse(source, "Stream.java").unwrap();
        let method = &result.classes[0].methods[0];

        // Should capture multiple calls in the chain
        assert!(
            !method.call_sites.is_empty(),
            "Expected at least 1 call site for stream chain"
        );

        // Should find at least the initial stream() call
        let has_stream_related = method.call_sites.iter().any(|c| {
            c.callee.contains("stream")
                || c.callee.contains("filter")
                || c.callee.contains("collect")
        });
        assert!(has_stream_related, "Should find stream-related call");
    }
}
