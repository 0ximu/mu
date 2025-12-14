//! Rust AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse Rust source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_rust::LANGUAGE.into())
        .map_err(|e| format!("Failed to set Rust language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse Rust source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "rust".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    // Collect impl blocks to associate with types
    let mut impl_methods: std::collections::HashMap<String, Vec<FunctionDef>> =
        std::collections::HashMap::new();

    // First pass: collect all declarations
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match child.kind() {
            "use_declaration" => {
                if let Some(import) = extract_use(&child, source) {
                    module.imports.push(import);
                }
            }
            "function_item" => {
                module.functions.push(extract_function(&child, source));
            }
            "struct_item" => {
                module.classes.push(extract_struct(&child, source));
            }
            "enum_item" => {
                module.classes.push(extract_enum(&child, source));
            }
            "trait_item" => {
                module.classes.push(extract_trait(&child, source));
            }
            "impl_item" => {
                extract_impl(&child, source, &mut impl_methods);
            }
            "mod_item" => {
                // Module declaration - treat as import
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    module.imports.push(ImportDef {
                        module: get_node_text(&id, source).to_string(),
                        ..Default::default()
                    });
                }
            }
            _ => {}
        }
    }

    // Second pass: associate impl methods with structs
    for class in &mut module.classes {
        if let Some(methods) = impl_methods.remove(&class.name) {
            class.methods.extend(methods);
        }
        // Collect type annotations from all methods and extract referenced types
        let type_strings = collect_type_strings_from_methods(&class.methods);
        class.referenced_types =
            extract_referenced_types(type_strings.iter().map(|s| s.as_str()), &class.name, "rust");
    }

    // Add remaining impl methods as standalone (for trait impls on external types)
    for (type_name, methods) in impl_methods {
        let type_strings = collect_type_strings_from_methods(&methods);
        let referenced_types =
            extract_referenced_types(type_strings.iter().map(|s| s.as_str()), &type_name, "rust");
        let class = ClassDef {
            name: type_name,
            decorators: vec!["impl".to_string()],
            methods,
            referenced_types,
            ..Default::default()
        };
        if !class.methods.is_empty() {
            module.classes.push(class);
        }
    }

    Ok(module)
}

/// Extract use declaration.
fn extract_use(node: &Node, source: &str) -> Option<ImportDef> {
    let mut module = String::new();
    let mut names = Vec::new();
    let mut alias = None;
    let mut is_pub = false;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "visibility_modifier" => {
                is_pub = true;
            }
            "scoped_identifier" | "identifier" => {
                module = get_node_text(&child, source).replace("::", ".").to_string();
            }
            "scoped_use_list" => {
                // Handle `use foo::bar::{a, b, c}` pattern
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    match inner.kind() {
                        "scoped_identifier" | "identifier" => {
                            module = get_node_text(&inner, source).replace("::", ".").to_string();
                        }
                        "use_list" => {
                            extract_use_list(&inner, source, &mut names);
                        }
                        _ => {}
                    }
                }
            }
            "use_as_clause" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    match inner.kind() {
                        "scoped_identifier" => {
                            if module.is_empty() {
                                module =
                                    get_node_text(&inner, source).replace("::", ".").to_string();
                            }
                        }
                        "identifier" => {
                            if module.is_empty() {
                                module =
                                    get_node_text(&inner, source).replace("::", ".").to_string();
                            } else {
                                alias = Some(get_node_text(&inner, source).to_string());
                            }
                        }
                        _ => {}
                    }
                }
            }
            "use_list" => {
                extract_use_list(&child, source, &mut names);
            }
            "use_wildcard" => {
                names.push("*".to_string());
            }
            _ => {}
        }
    }

    if module.is_empty() && names.is_empty() {
        return None;
    }

    let is_from = !names.is_empty();
    let import = ImportDef {
        module,
        names,
        alias,
        is_from,
        ..Default::default()
    };

    if is_pub {
        // Mark as re-export
    }

    Some(import)
}

/// Extract use list (use foo::{bar, baz}).
fn extract_use_list(node: &Node, source: &str, names: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" | "scoped_identifier" => {
                names.push(get_node_text(&child, source).replace("::", ".").to_string());
            }
            "use_as_clause" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    names.push(get_node_text(&id, source).to_string());
                }
            }
            "self" => {
                names.push("self".to_string());
            }
            _ => {}
        }
    }
}

/// Extract function item.
fn extract_function(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "visibility_modifier" => {
                func_def.decorators.push("pub".to_string());
            }
            "function_modifiers" => {
                // Check for async, const, unsafe, etc.
                let mods_text = get_node_text(&child, source);
                if mods_text.contains("async") {
                    func_def.is_async = true;
                }
                if mods_text.contains("const") {
                    func_def.decorators.push("const".to_string());
                }
                if mods_text.contains("unsafe") {
                    func_def.decorators.push("unsafe".to_string());
                }
            }
            "identifier" => {
                if func_def.name.is_empty() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "type_parameters" => {
                // Generic parameters like <T, U>
                func_def
                    .decorators
                    .push(format!("generic:{}", get_node_text(&child, source)));
            }
            "parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "type_identifier"
            | "generic_type"
            | "reference_type"
            | "tuple_type"
            | "primitive_type"
            | "scoped_type_identifier"
            | "unit_type"
            | "pointer_type"
            | "array_type" => {
                if func_def.return_type.is_none() {
                    func_def.return_type = Some(get_node_text(&child, source).to_string());
                }
            }
            "block" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "rust");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);
            }
            "async" => {
                // Direct async keyword (older tree-sitter versions)
                func_def.is_async = true;
            }
            "where_clause" => {
                func_def
                    .decorators
                    .push(format!("where:{}", get_node_text(&child, source)));
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
                        if param.name.is_empty() {
                            param.name = get_node_text(&inner, source).to_string();
                        }
                    }
                    "mutable_specifier" => {
                        param.name = format!("mut {}", param.name);
                    }
                    "type_identifier" | "generic_type" | "reference_type" | "primitive_type" => {
                        param.type_annotation = Some(get_node_text(&inner, source).to_string());
                    }
                    _ => {}
                }
            }

            if !param.name.is_empty() {
                // Filter self parameter
                if param.name != "self" && param.name != "&self" && param.name != "&mut self" {
                    params.push(param);
                }
            }
        } else if child.kind() == "self_parameter" {
            // Skip self parameter
        }
    }

    params
}

/// Extract struct item.
fn extract_struct(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    class_def.decorators.push("struct".to_string());

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "visibility_modifier" => {
                class_def.decorators.push("pub".to_string());
            }
            "type_identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "field_declaration_list" => {
                extract_struct_fields(&child, source, &mut class_def.attributes);
            }
            _ => {}
        }
    }

    class_def
}

/// Extract struct fields.
fn extract_struct_fields(node: &Node, source: &str, attributes: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "field_declaration" {
            if let Some(id) = find_child_by_type(&child, "field_identifier") {
                attributes.push(get_node_text(&id, source).to_string());
            }
        }
    }
}

/// Extract enum item.
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
            "visibility_modifier" => {
                class_def.decorators.push("pub".to_string());
            }
            "type_identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "enum_variant_list" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "enum_variant" {
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

/// Extract trait item.
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
            "visibility_modifier" => {
                class_def.decorators.push("pub".to_string());
            }
            "type_identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "trait_bounds" => {
                // Supertraits
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "type_identifier" {
                        class_def
                            .bases
                            .push(get_node_text(&inner, source).to_string());
                    }
                }
            }
            "declaration_list" => {
                extract_trait_methods(&child, source, &mut class_def.methods);
            }
            _ => {}
        }
    }

    class_def
}

/// Extract trait methods.
fn extract_trait_methods(node: &Node, source: &str, methods: &mut Vec<FunctionDef>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "function_signature_item" || child.kind() == "function_item" {
            methods.push(extract_function(&child, source));
        }
    }
}

/// Extract impl block.
fn extract_impl(
    node: &Node,
    source: &str,
    impl_methods: &mut std::collections::HashMap<String, Vec<FunctionDef>>,
) {
    let mut type_name = String::new();
    let mut trait_name: Option<String> = None;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "generic_type" => {
                if type_name.is_empty() {
                    type_name = get_node_text(&child, source).to_string();
                    // Clean up generic parameters for matching
                    if let Some(idx) = type_name.find('<') {
                        type_name = type_name[..idx].to_string();
                    }
                }
            }
            "trait" => {
                // This is a trait impl
                trait_name = Some(get_node_text(&child, source).to_string());
            }
            "declaration_list" => {
                let methods = extract_impl_methods(&child, source, trait_name.as_deref());
                impl_methods
                    .entry(type_name.clone())
                    .or_default()
                    .extend(methods);
            }
            _ => {}
        }
    }
}

/// Extract impl methods.
fn extract_impl_methods(node: &Node, source: &str, trait_name: Option<&str>) -> Vec<FunctionDef> {
    let mut methods = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "function_item" {
            let mut method = extract_function(&child, source);
            method.is_method = true;
            if let Some(t) = trait_name {
                method.decorators.push(format!("impl:{}", t));
            }
            methods.push(method);
        }
    }

    methods
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
        // Function calls: foo(), Bar::new(), path::to::func()
        "call_expression" => {
            if let Some(call_site) = extract_call_site(node, source) {
                results.push(call_site);
            }
        }
        // Macro invocations: println!(), vec![], format!()
        "macro_invocation" => {
            if let Some(call_site) = extract_macro_invocation(node, source) {
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

/// Extract a single call site from a call_expression node.
fn extract_call_site(node: &Node, source: &str) -> Option<CallSiteDef> {
    // In Rust, the function being called is the first child (before "arguments")
    let func_node = node.child(0)?;
    let line = get_start_line(node);

    match func_node.kind() {
        "identifier" => {
            // Simple function call: foo()
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        "field_expression" => {
            // Method call: self.method(), obj.method(), or chained like self.data.get()
            let full_text = get_node_text(&func_node, source);

            // Get the value (receiver) and field (method name)
            let value_node = func_node.child_by_field_name("value");
            let field_node = func_node.child_by_field_name("field");

            let receiver = value_node.map(|n| get_node_text(&n, source).to_string());
            let method_name = field_node
                .map(|n| get_node_text(&n, source).to_string())
                .unwrap_or_else(|| full_text.to_string());

            // Check if it's self.method() or Self::method()
            let is_self_call = receiver
                .as_ref()
                .map(|r| r == "self" || r == "Self")
                .unwrap_or(false);

            Some(CallSiteDef {
                callee: if is_self_call {
                    method_name
                } else {
                    full_text.to_string()
                },
                line,
                is_method_call: true,
                receiver,
            })
        }
        "scoped_identifier" => {
            // Scoped/path call: Struct::new(), module::func(), std::mem::take()
            let full_text = get_node_text(&func_node, source).to_string();

            // Extract the path and name parts
            let path_node = func_node.child_by_field_name("path");
            let name_node = func_node.child_by_field_name("name");

            let receiver = path_node.map(|n| get_node_text(&n, source).to_string());
            let _method_name = name_node
                .map(|n| get_node_text(&n, source).to_string())
                .unwrap_or_else(|| full_text.clone());

            Some(CallSiteDef {
                callee: full_text,
                line,
                is_method_call: receiver.is_some(),
                receiver,
            })
        }
        "generic_function" => {
            // Generic function call: foo::<T>(), Vec::<i32>::new()
            let full_text = get_node_text(&func_node, source).to_string();

            // Try to get the function name (first child before type parameters)
            let base_func = find_child_by_type(&func_node, "identifier")
                .or_else(|| find_child_by_type(&func_node, "scoped_identifier"))
                .or_else(|| find_child_by_type(&func_node, "field_expression"));

            if let Some(base) = base_func {
                if base.kind() == "field_expression" {
                    // Method call with generics: self.method::<T>()
                    let value_node = base.child_by_field_name("value");
                    let receiver = value_node.map(|n| get_node_text(&n, source).to_string());
                    let is_self_call = receiver
                        .as_ref()
                        .map(|r| r == "self" || r == "Self")
                        .unwrap_or(false);

                    let field_node = base.child_by_field_name("field");
                    let method_name = field_node
                        .map(|n| get_node_text(&n, source).to_string())
                        .unwrap_or_else(|| full_text.clone());

                    return Some(CallSiteDef {
                        callee: if is_self_call { method_name } else { full_text },
                        line,
                        is_method_call: true,
                        receiver,
                    });
                }
            }

            Some(CallSiteDef {
                callee: full_text,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        "parenthesized_expression" => {
            // Call on parenthesized expression: (get_func())()
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        "call_expression" => {
            // Chained call: foo()() - call on result of another call
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        "index_expression" => {
            // Call on indexed value: handlers[name]()
            let callee = get_node_text(&func_node, source).to_string();
            Some(CallSiteDef {
                callee,
                line,
                is_method_call: false,
                receiver: None,
            })
        }
        _ => {
            // Other callable patterns - capture as generic call
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

/// Extract a call site from a macro invocation node.
fn extract_macro_invocation(node: &Node, source: &str) -> Option<CallSiteDef> {
    // Macro invocations have a "macro" child that contains the macro name
    let macro_node = node.child_by_field_name("macro")?;
    let line = get_start_line(node);
    let macro_name = get_node_text(&macro_node, source).to_string();

    // Add the ! to indicate it's a macro
    let callee = format!("{}!", macro_name);

    // Check if it's a scoped macro like module::macro!
    let is_scoped = macro_node.kind() == "scoped_identifier";
    let receiver = if is_scoped {
        macro_node
            .child_by_field_name("path")
            .map(|n| get_node_text(&n, source).to_string())
    } else {
        None
    };

    Some(CallSiteDef {
        callee,
        line,
        is_method_call: is_scoped,
        receiver,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_function() {
        let source = r#"
pub fn hello(name: &str) -> String {
    format!("Hello, {}!", name)
}
"#;
        let result = parse(source, "lib.rs").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "hello");
    }

    #[test]
    fn test_parse_struct() {
        let source = r#"
pub struct User {
    name: String,
    age: u32,
}
"#;
        let result = parse(source, "lib.rs").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "User");
        assert!(result.classes[0].decorators.contains(&"struct".to_string()));
    }

    #[test]
    fn test_parse_impl() {
        let source = r#"
struct User {
    name: String,
}

impl User {
    fn new(name: String) -> Self {
        Self { name }
    }
}
"#;
        let result = parse(source, "lib.rs").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].methods.len(), 1);
        assert_eq!(result.classes[0].methods[0].name, "new");
    }

    #[test]
    fn test_extract_call_sites() {
        let source = r#"
fn process_data(data: &str) -> String {
    let validated = validate(data);
    let result = helper.transform(validated);
    println!("Result: {}", result);
    save(result)
}
"#;
        let result = parse(source, "lib.rs").unwrap();
        assert_eq!(result.functions.len(), 1);
        let func = &result.functions[0];
        assert!(
            func.call_sites.len() >= 3,
            "Expected at least 3 call sites, got {}",
            func.call_sites.len()
        );

        // Check we captured validate() call
        assert!(
            func.call_sites.iter().any(|c| c.callee == "validate"),
            "Should find validate() call"
        );

        // Check we captured helper.transform() as method call
        let transform_call = func
            .call_sites
            .iter()
            .find(|c| c.callee == "helper.transform");
        assert!(
            transform_call.is_some(),
            "Should find helper.transform() call"
        );
        assert!(transform_call.unwrap().is_method_call);
        assert_eq!(transform_call.unwrap().receiver, Some("helper".to_string()));

        // Check we captured println!() macro
        assert!(
            func.call_sites.iter().any(|c| c.callee == "println!"),
            "Should find println!() macro call"
        );
    }

    #[test]
    fn test_method_call_detection() {
        let source = r#"
impl Service {
    fn do_work(&self) {
        self.helper();
        self.data.get();
        other.process();
    }
}
"#;
        let result = parse(source, "lib.rs").unwrap();
        // The impl without a struct creates a standalone class
        assert!(!result.classes.is_empty());
        let method = &result.classes[0].methods[0];

        // self.helper() should be detected as method call with callee = "helper"
        let self_call = method.call_sites.iter().find(|c| c.callee == "helper");
        assert!(self_call.is_some(), "Should find self.helper() call");
        assert!(self_call.unwrap().is_method_call);
        assert_eq!(self_call.unwrap().receiver, Some("self".to_string()));

        // other.process() should keep the full form
        let other_call = method
            .call_sites
            .iter()
            .find(|c| c.callee == "other.process");
        assert!(other_call.is_some(), "Should find other.process() call");
        assert!(other_call.unwrap().is_method_call);
        assert_eq!(other_call.unwrap().receiver, Some("other".to_string()));
    }

    #[test]
    fn test_scoped_calls() {
        let source = r#"
fn example() {
    let user = User::new();
    let data = std::mem::take(&mut vec);
    module::helper::process();
}
"#;
        let result = parse(source, "lib.rs").unwrap();
        let func = &result.functions[0];

        // Check User::new() is captured
        let new_call = func.call_sites.iter().find(|c| c.callee == "User::new");
        assert!(new_call.is_some(), "Should find User::new() call");
        assert_eq!(new_call.unwrap().receiver, Some("User".to_string()));

        // Check std::mem::take() is captured
        let take_call = func
            .call_sites
            .iter()
            .find(|c| c.callee == "std::mem::take");
        assert!(take_call.is_some(), "Should find std::mem::take() call");
    }

    #[test]
    fn test_macro_invocations() {
        let source = r#"
fn example() {
    let v = vec![1, 2, 3];
    println!("Hello");
    format!("Result: {}", v);
    debug_assert!(true);
}
"#;
        let result = parse(source, "lib.rs").unwrap();
        let func = &result.functions[0];

        // Should capture vec!, println!, format!, debug_assert!
        assert!(
            func.call_sites.iter().any(|c| c.callee == "vec!"),
            "Should find vec![] macro"
        );
        assert!(
            func.call_sites.iter().any(|c| c.callee == "println!"),
            "Should find println!() macro"
        );
        assert!(
            func.call_sites.iter().any(|c| c.callee == "format!"),
            "Should find format!() macro"
        );
        assert!(
            func.call_sites.iter().any(|c| c.callee == "debug_assert!"),
            "Should find debug_assert!() macro"
        );
    }
}
