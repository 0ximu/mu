//! TypeScript/JavaScript AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    count_lines, find_child_by_type, get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse TypeScript/JavaScript source code.
///
/// # Arguments
/// * `source` - Source code
/// * `file_path` - Path to the file
/// * `is_javascript` - True for JavaScript, false for TypeScript
pub fn parse(source: &str, file_path: &str, is_javascript: bool) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();

    let language = if is_javascript {
        tree_sitter_javascript::LANGUAGE.into()
    } else {
        tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into()
    };

    parser
        .set_language(&language)
        .map_err(|e| format!("Failed to set language: {}", e))?;

    let tree = parser.parse(source, None).ok_or("Failed to parse source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let lang = if is_javascript {
        "javascript"
    } else {
        "typescript"
    };

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: lang.to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    // Process top-level statements
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match child.kind() {
            "import_statement" => {
                if let Some(import) = extract_import(&child, source) {
                    module.imports.push(import);
                }
            }
            "class_declaration" => {
                module.classes.push(extract_class(&child, source));
            }
            "function_declaration" => {
                module
                    .functions
                    .push(extract_function(&child, source, false));
            }
            "lexical_declaration" | "variable_declaration" => {
                // Check for arrow functions or function expressions
                extract_variable_functions(&child, source, &mut module.functions);
            }
            "export_statement" => {
                extract_export(&child, source, &mut module);
            }
            "interface_declaration" => {
                module.classes.push(extract_interface(&child, source));
            }
            _ => {}
        }
    }

    // Detect dynamic imports
    let dynamic_imports = extract_dynamic_imports(&root, source);
    module.imports.extend(dynamic_imports);

    Ok(module)
}

/// Extract import statement.
fn extract_import(node: &Node, source: &str) -> Option<ImportDef> {
    let mut module = String::new();
    let mut names = Vec::new();
    let mut alias = None;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "string" => {
                module = get_node_text(&child, source)
                    .trim_matches('"')
                    .trim_matches('\'')
                    .to_string();
            }
            "import_clause" => {
                extract_import_clause(&child, source, &mut names, &mut alias);
            }
            _ => {}
        }
    }

    if module.is_empty() {
        return None;
    }

    Some(ImportDef {
        module,
        names,
        alias,
        is_from: true,
        ..Default::default()
    })
}

/// Extract import clause (named imports, default import, namespace import).
fn extract_import_clause(
    node: &Node,
    source: &str,
    names: &mut Vec<String>,
    alias: &mut Option<String>,
) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                // Default import
                names.push(get_node_text(&child, source).to_string());
            }
            "named_imports" => {
                let mut inner_cursor = child.walk();
                for spec in child.children(&mut inner_cursor) {
                    if spec.kind() == "import_specifier" {
                        if let Some(name) = find_child_by_type(&spec, "identifier") {
                            names.push(get_node_text(&name, source).to_string());
                        }
                    }
                }
            }
            "namespace_import" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    *alias = Some(get_node_text(&id, source).to_string());
                }
            }
            _ => {}
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

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "class_heritage" => {
                extract_heritage(&child, source, &mut class_def.bases);
            }
            "class_body" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    class_def
}

/// Extract class heritage (extends/implements).
fn extract_heritage(node: &Node, source: &str, bases: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "extends_clause" || child.kind() == "implements_clause" {
            let mut inner_cursor = child.walk();
            for inner in child.children(&mut inner_cursor) {
                if inner.kind() == "type_identifier" || inner.kind() == "identifier" {
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
            "method_definition" => {
                class_def.methods.push(extract_method(&child, source));
            }
            "public_field_definition" | "field_definition" => {
                if let Some(name) = find_child_by_type(&child, "property_identifier") {
                    class_def
                        .attributes
                        .push(get_node_text(&name, source).to_string());
                }
            }
            _ => {}
        }
    }
}

/// Extract method definition.
fn extract_method(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        is_method: true,
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "property_identifier" | "identifier" => {
                if func_def.name.is_empty() {
                    func_def.name = get_node_text(&child, source).to_string();
                }
            }
            "formal_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "statement_block" => {
                func_def.body_complexity =
                    complexity::calculate_for_node(&child, source, "typescript");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            "async" => {
                func_def.is_async = true;
            }
            "static" => {
                func_def.is_static = true;
            }
            _ => {}
        }
    }

    func_def
}

/// Extract function declaration.
fn extract_function(node: &Node, source: &str, is_method: bool) -> FunctionDef {
    let mut func_def = FunctionDef {
        is_method,
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
            "formal_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "statement_block" => {
                func_def.body_complexity =
                    complexity::calculate_for_node(&child, source, "typescript");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            "type_annotation" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() != ":" {
                        func_def.return_type = Some(get_node_text(&inner, source).to_string());
                        break;
                    }
                }
            }
            "async" => {
                func_def.is_async = true;
            }
            _ => {}
        }
    }

    func_def
}

/// Extract parameters from formal_parameters.
fn extract_parameters(node: &Node, source: &str) -> Vec<ParameterDef> {
    let mut params = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" | "required_parameter" | "optional_parameter" => {
                let mut param = ParameterDef::default();

                if child.kind() == "identifier" {
                    param.name = get_node_text(&child, source).to_string();
                } else {
                    let mut inner_cursor = child.walk();
                    for inner in child.children(&mut inner_cursor) {
                        if inner.kind() == "identifier" {
                            param.name = get_node_text(&inner, source).to_string();
                        } else if inner.kind() == "type_annotation" {
                            let mut type_cursor = inner.walk();
                            for type_child in inner.children(&mut type_cursor) {
                                if type_child.kind() != ":" {
                                    param.type_annotation =
                                        Some(get_node_text(&type_child, source).to_string());
                                    break;
                                }
                            }
                        }
                    }
                }

                if !param.name.is_empty() {
                    params.push(param);
                }
            }
            "rest_pattern" => {
                if let Some(id) = find_child_by_type(&child, "identifier") {
                    params.push(ParameterDef {
                        name: get_node_text(&id, source).to_string(),
                        is_variadic: true,
                        ..Default::default()
                    });
                }
            }
            _ => {}
        }
    }

    params
}

/// Extract functions from variable declarations.
fn extract_variable_functions(node: &Node, source: &str, functions: &mut Vec<FunctionDef>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "variable_declarator" {
            if let Some(arrow) = find_child_by_type(&child, "arrow_function") {
                let mut func = extract_arrow_function(&arrow, source);
                if let Some(name) = find_child_by_type(&child, "identifier") {
                    func.name = get_node_text(&name, source).to_string();
                }
                if !func.name.is_empty() {
                    functions.push(func);
                }
            }
        }
    }
}

/// Extract arrow function.
fn extract_arrow_function(node: &Node, source: &str) -> FunctionDef {
    let mut func_def = FunctionDef {
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "formal_parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "identifier" => {
                // Single parameter arrow function
                if func_def.parameters.is_empty() {
                    func_def.parameters.push(ParameterDef {
                        name: get_node_text(&child, source).to_string(),
                        ..Default::default()
                    });
                }
            }
            "statement_block" => {
                func_def.body_complexity =
                    complexity::calculate_for_node(&child, source, "typescript");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
            }
            "async" => {
                func_def.is_async = true;
            }
            _ => {}
        }
    }

    func_def
}

/// Extract from export statement.
fn extract_export(node: &Node, source: &str, module: &mut ModuleDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "class_declaration" => {
                module.classes.push(extract_class(&child, source));
            }
            "function_declaration" => {
                module
                    .functions
                    .push(extract_function(&child, source, false));
            }
            "interface_declaration" => {
                module.classes.push(extract_interface(&child, source));
            }
            "lexical_declaration" => {
                extract_variable_functions(&child, source, &mut module.functions);
            }
            _ => {}
        }
    }
}

/// Extract interface declaration.
fn extract_interface(node: &Node, source: &str) -> ClassDef {
    let mut class_def = ClassDef {
        decorators: vec!["interface".to_string()],
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "type_identifier" | "identifier" => {
                if class_def.name.is_empty() {
                    class_def.name = get_node_text(&child, source).to_string();
                }
            }
            "extends_type_clause" => {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "type_identifier" {
                        class_def
                            .bases
                            .push(get_node_text(&inner, source).to_string());
                    }
                }
            }
            "object_type" | "interface_body" => {
                extract_interface_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    class_def
}

/// Extract interface body.
fn extract_interface_body(node: &Node, source: &str, class_def: &mut ClassDef) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "method_signature" => {
                let mut method = FunctionDef {
                    is_method: true,
                    start_line: get_start_line(&child),
                    end_line: get_end_line(&child),
                    ..Default::default()
                };

                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "property_identifier" {
                        method.name = get_node_text(&inner, source).to_string();
                    } else if inner.kind() == "formal_parameters" {
                        method.parameters = extract_parameters(&inner, source);
                    }
                }

                if !method.name.is_empty() {
                    class_def.methods.push(method);
                }
            }
            "property_signature" => {
                if let Some(name) = find_child_by_type(&child, "property_identifier") {
                    class_def
                        .attributes
                        .push(get_node_text(&name, source).to_string());
                }
            }
            _ => {}
        }
    }
}

/// Extract dynamic imports (import() and require()).
fn extract_dynamic_imports(root: &Node, source: &str) -> Vec<ImportDef> {
    let mut imports = Vec::new();
    find_dynamic_imports_recursive(root, source, &mut imports);
    imports
}

fn find_dynamic_imports_recursive(node: &Node, source: &str, results: &mut Vec<ImportDef>) {
    match node.kind() {
        "call_expression" => {
            if let Some(import) = check_dynamic_import(node, source) {
                results.push(import);
            }
        }
        _ => {}
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        find_dynamic_imports_recursive(&child, source, results);
    }
}

fn check_dynamic_import(node: &Node, source: &str) -> Option<ImportDef> {
    let func_node =
        find_child_by_type(node, "import").or_else(|| find_child_by_type(node, "identifier"))?;

    let func_text = get_node_text(&func_node, source);

    if func_text == "import" {
        // Dynamic import() - look for argument
        let args = find_child_by_type(node, "arguments")?;
        let mut cursor = args.walk();

        for child in args.children(&mut cursor) {
            match child.kind() {
                "string" => {
                    // Static string: import("./module")
                    let module = get_node_text(&child, source)
                        .trim_matches('"')
                        .trim_matches('\'')
                        .to_string();
                    return Some(ImportDef {
                        module,
                        is_dynamic: true,
                        dynamic_source: Some("import()".to_string()),
                        line_number: get_start_line(node),
                        ..Default::default()
                    });
                }
                "template_string" => {
                    // Template literal: import(`./handlers/${type}.js`)
                    let pattern = get_node_text(&child, source);
                    return Some(ImportDef {
                        module: "<dynamic>".to_string(),
                        is_dynamic: true,
                        dynamic_pattern: Some(pattern.to_string()),
                        dynamic_source: Some("import()".to_string()),
                        line_number: get_start_line(node),
                        ..Default::default()
                    });
                }
                "identifier" | "member_expression" | "binary_expression" => {
                    // Variable or expression: import(modulePath)
                    let pattern = get_node_text(&child, source);
                    return Some(ImportDef {
                        module: "<dynamic>".to_string(),
                        is_dynamic: true,
                        dynamic_pattern: Some(pattern.to_string()),
                        dynamic_source: Some("import()".to_string()),
                        line_number: get_start_line(node),
                        ..Default::default()
                    });
                }
                _ => {}
            }
        }
    } else if func_text == "require" {
        // require() - check if argument is dynamic
        let args = find_child_by_type(node, "arguments")?;
        let mut cursor = args.walk();

        for child in args.children(&mut cursor) {
            match child.kind() {
                "string" => {
                    // Static require - skip (handled elsewhere as regular import)
                    return None;
                }
                "template_string" | "identifier" | "member_expression" | "binary_expression"
                | "call_expression" => {
                    // Dynamic require: require(modulePath), require(`./x/${y}`), require(getModule())
                    let pattern = get_node_text(&child, source);
                    return Some(ImportDef {
                        module: "<dynamic>".to_string(),
                        is_dynamic: true,
                        dynamic_pattern: Some(pattern.to_string()),
                        dynamic_source: Some("require()".to_string()),
                        line_number: get_start_line(node),
                        ..Default::default()
                    });
                }
                _ => {}
            }
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_function() {
        let source = r#"
function hello(name: string): string {
    return `Hello, ${name}!`;
}
"#;
        let result = parse(source, "test.ts", false).unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "hello");
    }

    #[test]
    fn test_parse_class() {
        let source = r#"
class MyClass extends BaseClass {
    method() {
        return 42;
    }
}
"#;
        let result = parse(source, "test.ts", false).unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "MyClass");
    }

    #[test]
    fn test_parse_import() {
        let source = r#"
import { foo, bar } from './module';
"#;
        let result = parse(source, "test.ts", false).unwrap();
        assert_eq!(result.imports.len(), 1);
        assert_eq!(result.imports[0].module, "./module");
    }
}
