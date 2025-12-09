//! TypeScript/JavaScript AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    count_lines, find_child_by_type, get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

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
                func_def.call_sites = extract_call_sites(&child, source);
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
                func_def.call_sites = extract_call_sites(&child, source);
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
                func_def.call_sites = extract_call_sites(&child, source);
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
    if node.kind() == "call_expression" {
        if let Some(import) = check_dynamic_import(node, source) {
            results.push(import);
        }
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

/// Extract all call sites from a function body node.
fn extract_call_sites(body: &Node, source: &str) -> Vec<CallSiteDef> {
    let mut call_sites = Vec::new();
    find_call_sites_recursive(body, source, &mut call_sites);
    call_sites
}

/// Recursively search for call expressions in AST.
fn find_call_sites_recursive(node: &Node, source: &str, results: &mut Vec<CallSiteDef>) {
    // TypeScript/JS uses "call_expression" not "call"
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
    // In TS/JS, the function is the first child (before "arguments")
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
        "member_expression" => {
            // Method call: obj.method() or this.method()
            let full_text = get_node_text(&func_node, source);

            // Get object and property
            let object_node = func_node.child_by_field_name("object");
            let property_node = func_node.child_by_field_name("property");

            let receiver = object_node.map(|n| get_node_text(&n, source).to_string());
            let method_name = property_node
                .map(|n| get_node_text(&n, source).to_string())
                .unwrap_or_else(|| full_text.to_string());

            // Check if it's this.method()
            let is_this_call = receiver.as_ref().map(|r| r == "this").unwrap_or(false);

            Some(CallSiteDef {
                callee: if is_this_call {
                    method_name
                } else {
                    full_text.to_string()
                },
                line,
                is_method_call: true,
                receiver,
            })
        }
        _ => {
            // Other callable patterns (subscript, IIFE, etc.)
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

    #[test]
    fn test_extract_call_sites_ts() {
        let source = r#"
function processData(data: string) {
    const validated = validate(data);
    const result = this.transform(validated);
    return helper.process(result);
}
"#;
        let result = parse(source, "test.ts", false).unwrap();
        assert_eq!(result.functions.len(), 1);
        let func = &result.functions[0];
        assert!(
            func.call_sites.len() >= 2,
            "Expected at least 2 call sites, got {}",
            func.call_sites.len()
        );
        assert!(func.call_sites.iter().any(|c| c.callee == "validate"));
    }

    #[test]
    fn test_method_call_detection_ts() {
        let source = r#"
class MyClass {
    doWork() {
        this.helper();
        other.process();
    }
}
"#;
        let result = parse(source, "test.ts", false).unwrap();
        let method = &result.classes[0].methods[0];

        let this_call = method.call_sites.iter().find(|c| c.callee == "helper");
        assert!(this_call.is_some(), "Should find this.helper() call");
        assert!(this_call.unwrap().is_method_call);
        assert_eq!(this_call.unwrap().receiver, Some("this".to_string()));
    }

    #[test]
    fn test_arrow_function_calls() {
        let source = r#"
const process = (data: string) => {
    validate(data);
    return transform(data);
};
"#;
        let result = parse(source, "test.ts", false).unwrap();
        // Arrow functions are extracted as functions
        assert!(
            result.functions.len() >= 1,
            "Expected at least 1 function, got {}",
            result.functions.len()
        );
        let func = &result.functions[0];
        assert!(
            func.call_sites.len() >= 2,
            "Expected at least 2 call sites in arrow function, got {}",
            func.call_sites.len()
        );
        assert!(func.call_sites.iter().any(|c| c.callee == "validate"));
        assert!(func.call_sites.iter().any(|c| c.callee == "transform"));
    }
}
