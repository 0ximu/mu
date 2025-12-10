//! Rust AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

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
        class.referenced_types = extract_referenced_types(
            type_strings.iter().map(|s| s.as_str()),
            &class.name,
            "rust",
        );
    }

    // Add remaining impl methods as standalone (for trait impls on external types)
    for (type_name, methods) in impl_methods {
        let type_strings = collect_type_strings_from_methods(&methods);
        let referenced_types = extract_referenced_types(
            type_strings.iter().map(|s| s.as_str()),
            &type_name,
            "rust",
        );
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
}
