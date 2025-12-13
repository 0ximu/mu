//! C# AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

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

    // Collect type annotations from all methods and extract referenced types
    // Strip generic parameters from name for filtering (e.g., "MyClass<T>" -> "MyClass")
    let base_name = class_def.name.split('<').next().unwrap_or(&class_def.name);
    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types =
        extract_referenced_types(type_strings.iter().map(|s| s.as_str()), base_name, "csharp");

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
                func_def.call_sites = extract_call_sites(&child, source);
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
                func_def.call_sites = extract_call_sites(&child, source);
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

    // Collect type annotations from all methods and extract referenced types
    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types = extract_referenced_types(
        type_strings.iter().map(|s| s.as_str()),
        &class_def.name,
        "csharp",
    );

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

/// Extract all call sites from a function body node.
fn extract_call_sites(body: &Node, source: &str) -> Vec<CallSiteDef> {
    let mut call_sites = Vec::new();
    find_call_sites_recursive(body, source, &mut call_sites);
    call_sites
}

/// Recursively search for call expressions in AST.
fn find_call_sites_recursive(node: &Node, source: &str, results: &mut Vec<CallSiteDef>) {
    match node.kind() {
        "invocation_expression" => {
            // Method calls: foo.Bar(), this.Method(), SomeMethod()
            if let Some(call_site) = extract_invocation_call_site(node, source) {
                results.push(call_site);
            }
        }
        "object_creation_expression" => {
            // Constructor calls: new Foo()
            if let Some(call_site) = extract_object_creation_call_site(node, source) {
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

/// Extract a call site from an invocation_expression node.
/// Handles patterns like: foo.Bar(), this.Method(), SomeMethod(), obj?.Method()
fn extract_invocation_call_site(node: &Node, source: &str) -> Option<CallSiteDef> {
    // The function being called is the first child (before argument_list)
    let func_node = node.child(0)?;
    let line = get_start_line(node);

    match func_node.kind() {
        "identifier" => {
            // Simple function call: SomeMethod()
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        "member_access_expression" | "member_binding_expression" => {
            // Method call: obj.Method(), this.Method(), obj?.Method()
            // Structure: child(0)=object, child(1)=".", child(2)=name
            let full_text = get_node_text(&func_node, source);

            // Get the object (receiver) - first child
            let object_node = func_node.child(0);
            let receiver = object_node.map(|n| get_node_text(&n, source).to_string());

            // Get the method name - last child (the member name after the dot)
            // We need to find the last identifier, not the first
            let mut method_name = full_text.to_string();
            let mut cursor = func_node.walk();
            for child in func_node.children(&mut cursor) {
                if child.kind() == "identifier" || child.kind() == "simple_name" || child.kind() == "name" {
                    method_name = get_node_text(&child, source).to_string();
                    // Keep iterating to get the LAST identifier
                }
            }

            // Always use just the method name as callee for better resolution
            // The receiver field captures the object (this, _service, etc.)
            Some(CallSiteDef {
                callee: method_name,
                line,
                is_method_call: true,
                receiver,
            })
        }
        "conditional_access_expression" => {
            // Null-conditional: obj?.Method()
            let full_text = get_node_text(&func_node, source);
            let object_node = func_node.child(0);
            let receiver = object_node.map(|n| get_node_text(&n, source).to_string());

            // Extract just the method name - find the last identifier
            let mut method_name = full_text.to_string();
            let mut cursor = func_node.walk();
            for child in func_node.children(&mut cursor) {
                if child.kind() == "identifier" || child.kind() == "simple_name" || child.kind() == "name" {
                    method_name = get_node_text(&child, source).to_string();
                }
            }

            Some(CallSiteDef {
                callee: method_name,
                line,
                is_method_call: true,
                receiver,
            })
        }
        "generic_name" => {
            // Generic method call: SomeMethod<T>()
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        _ => {
            // Other callable patterns
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

/// Extract a call site from an object_creation_expression node.
/// Handles patterns like: new Foo(), new Foo<T>(), new Foo { ... }
fn extract_object_creation_call_site(node: &Node, source: &str) -> Option<CallSiteDef> {
    let line = get_start_line(node);

    // Find the type being constructed
    let type_node = find_child_by_type(node, "identifier")
        .or_else(|| find_child_by_type(node, "generic_name"))
        .or_else(|| find_child_by_type(node, "qualified_name"));

    let type_name = type_node.map(|n| get_node_text(&n, source).to_string())?;

    Some(CallSiteDef {
        callee: format!("new {}", type_name),
        line,
        is_method_call: false,
        receiver: None,
    })
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

    #[test]
    fn test_extract_call_sites() {
        let source = r#"
public class DataProcessor {
    public void ProcessData(string data) {
        var validated = Validate(data);
        var result = this.Transform(validated);
        helper.Process(result);
        Save(result);
    }
}
"#;
        let result = parse(source, "DataProcessor.cs").unwrap();
        assert_eq!(result.classes.len(), 1);
        let method = &result.classes[0].methods[0];
        assert!(
            method.call_sites.len() >= 3,
            "Expected at least 3 call sites, got {}",
            method.call_sites.len()
        );

        // Check we captured Validate() call
        assert!(method.call_sites.iter().any(|c| c.callee == "Validate"));
        // Check we captured Save() call
        assert!(method.call_sites.iter().any(|c| c.callee == "Save"));
    }

    #[test]
    fn test_method_call_detection() {
        let source = r#"
public class MyClass {
    public void DoWork() {
        this.Helper();
        other.Process();
    }
}
"#;
        let result = parse(source, "MyClass.cs").unwrap();
        let method = &result.classes[0].methods[0];

        // this.Helper() should be detected as method call with callee = "Helper"
        let this_call = method.call_sites.iter().find(|c| c.callee == "Helper");
        assert!(this_call.is_some(), "Should find this.Helper() call");
        assert!(this_call.unwrap().is_method_call);
        assert_eq!(this_call.unwrap().receiver, Some("this".to_string()));

        // other.Process() should have callee = "Process", receiver = "other"
        let other_call = method
            .call_sites
            .iter()
            .find(|c| c.callee == "Process");
        assert!(other_call.is_some(), "Should find other.Process() call");
        assert!(other_call.unwrap().is_method_call);
        assert_eq!(other_call.unwrap().receiver, Some("other".to_string()));
    }

    #[test]
    fn test_constructor_call_sites() {
        let source = r#"
public class Factory {
    public Factory() {
        var service = new DataService();
        Initialize();
    }
}
"#;
        let result = parse(source, "Factory.cs").unwrap();
        let constructor = &result.classes[0].methods[0];

        // Should find new DataService() call
        let new_call = constructor
            .call_sites
            .iter()
            .find(|c| c.callee == "new DataService");
        assert!(
            new_call.is_some(),
            "Should find new DataService() constructor call"
        );

        // Should find Initialize() call
        assert!(constructor
            .call_sites
            .iter()
            .any(|c| c.callee == "Initialize"));
    }

    #[test]
    fn test_object_creation_expression() {
        let source = r#"
public class Builder {
    public void Build() {
        var list = new List<string>();
        var config = new AppConfig { Name = "test" };
        var handler = new EventHandler<Args>();
    }
}
"#;
        let result = parse(source, "Builder.cs").unwrap();
        let method = &result.classes[0].methods[0];

        // Should find generic constructor calls
        assert!(
            method
                .call_sites
                .iter()
                .any(|c| c.callee.starts_with("new List")),
            "Should find new List<string>() call"
        );
        assert!(
            method
                .call_sites
                .iter()
                .any(|c| c.callee.starts_with("new AppConfig")),
            "Should find new AppConfig call"
        );
    }

    #[test]
    fn test_base_method_call() {
        let source = r#"
public class Derived : Base {
    public override void DoWork() {
        base.DoWork();
        this.Helper();
    }
}
"#;
        let result = parse(source, "Derived.cs").unwrap();
        let method = &result.classes[0].methods[0];

        // base.DoWork() should have callee = "DoWork" and receiver = "base"
        let base_call = method
            .call_sites
            .iter()
            .find(|c| c.callee == "DoWork" && c.receiver == Some("base".to_string()));
        assert!(base_call.is_some(), "Should find base.DoWork() call");
    }
}
