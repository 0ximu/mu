//! Python-specific AST extractor using tree-sitter.

use std::path::Path;
use tree_sitter::{Node, Parser};

use super::helpers::{
    collect_type_strings_from_methods, count_lines, extract_referenced_types, find_child_by_type,
    get_end_line, get_node_text, get_start_line,
};
use crate::reducer::complexity;
use crate::types::{CallSiteDef, ClassDef, FunctionDef, ImportDef, ModuleDef, ParameterDef};

/// Parse Python source code.
pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_python::LANGUAGE.into())
        .map_err(|e| format!("Failed to set Python language: {}", e))?;

    let tree = parser
        .parse(source, None)
        .ok_or("Failed to parse Python source")?;
    let root = tree.root_node();

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "python".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    // Extract module docstring (first expression if it's a string)
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        if child.kind() == "expression_statement" {
            if let Some(expr) = find_child_by_type(&child, "string") {
                module.module_docstring = Some(extract_string(&expr, source));
            }
            break;
        } else if child.kind() != "comment" {
            break;
        }
    }

    // Process top-level statements
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        match child.kind() {
            "import_statement" => {
                module.imports.push(extract_import(&child, source));
            }
            "import_from_statement" => {
                module.imports.push(extract_from_import(&child, source));
            }
            "class_definition" => {
                module.classes.push(extract_class(&child, source, None));
            }
            "function_definition" => {
                module
                    .functions
                    .push(extract_function(&child, source, false, None));
            }
            "decorated_definition" => match extract_decorated(&child, source, false) {
                Decorated::Class(c) => module.classes.push(c),
                Decorated::Function(f) => module.functions.push(f),
            },
            _ => {}
        }
    }

    // Detect dynamic imports in entire module
    let dynamic_imports = extract_dynamic_imports(&root, source);
    module.imports.extend(dynamic_imports);

    Ok(module)
}

/// Extract regular import statement.
fn extract_import(node: &Node, source: &str) -> ImportDef {
    let mut names = Vec::new();
    let mut alias = None;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "dotted_name" => {
                names.push(get_node_text(&child, source).to_string());
            }
            "aliased_import" => {
                if let Some(name_node) = find_child_by_type(&child, "dotted_name") {
                    names.push(get_node_text(&name_node, source).to_string());
                }
                if let Some(alias_node) = find_child_by_type(&child, "identifier") {
                    alias = Some(get_node_text(&alias_node, source).to_string());
                }
            }
            _ => {}
        }
    }

    ImportDef {
        module: names.first().cloned().unwrap_or_default(),
        names: if names.len() > 1 {
            names[1..].to_vec()
        } else {
            vec![]
        },
        alias,
        is_from: false,
        ..Default::default()
    }
}

/// Extract from...import statement.
fn extract_from_import(node: &Node, source: &str) -> ImportDef {
    let mut module = String::new();
    let mut names = Vec::new();
    let mut alias = None;
    let mut seen_import_keyword = false;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "import" => {
                seen_import_keyword = true;
            }
            "dotted_name" => {
                if !seen_import_keyword {
                    module = get_node_text(&child, source).to_string();
                } else {
                    names.push(get_node_text(&child, source).to_string());
                }
            }
            "relative_import" => {
                module = get_node_text(&child, source).to_string();
            }
            "identifier" if seen_import_keyword => {
                names.push(get_node_text(&child, source).to_string());
            }
            "aliased_import" => {
                let mut inner_cursor = child.walk();
                let children: Vec<_> = child.children(&mut inner_cursor).collect();
                if let Some(first) = children.first() {
                    names.push(get_node_text(first, source).to_string());
                }
                for c in children.iter().skip(1) {
                    if c.kind() == "identifier" {
                        alias = Some(get_node_text(c, source).to_string());
                    }
                }
            }
            "wildcard_import" => {
                names.push("*".to_string());
            }
            _ => {}
        }
    }

    ImportDef {
        module,
        names,
        alias,
        is_from: true,
        ..Default::default()
    }
}

/// Extract class definition.
fn extract_class(node: &Node, source: &str, decorators: Option<Vec<String>>) -> ClassDef {
    let mut class_def = ClassDef {
        decorators: decorators.unwrap_or_default(),
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                class_def.name = get_node_text(&child, source).to_string();
            }
            "argument_list" => {
                // Base classes
                let mut arg_cursor = child.walk();
                for arg in child.children(&mut arg_cursor) {
                    if arg.kind() == "identifier" || arg.kind() == "attribute" {
                        class_def
                            .bases
                            .push(get_node_text(&arg, source).to_string());
                    }
                }
            }
            "block" => {
                extract_class_body(&child, source, &mut class_def);
            }
            _ => {}
        }
    }

    // Collect type annotations from all methods and extract referenced types
    let type_strings = collect_type_strings_from_methods(&class_def.methods);
    class_def.referenced_types =
        extract_referenced_types(type_strings.iter().map(|s| s.as_str()), &class_def.name, "python");

    class_def
}

/// Extract class body contents.
fn extract_class_body(block: &Node, source: &str, class_def: &mut ClassDef) {
    let mut first_statement = true;

    let mut cursor = block.walk();
    for child in block.children(&mut cursor) {
        match child.kind() {
            "expression_statement" if first_statement => {
                // Check for docstring
                if let Some(expr) = find_child_by_type(&child, "string") {
                    class_def.docstring = Some(extract_string(&expr, source));
                }
                first_statement = false;
            }
            "function_definition" => {
                class_def
                    .methods
                    .push(extract_function(&child, source, true, None));
                first_statement = false;
            }
            "decorated_definition" => {
                if let Decorated::Function(f) = extract_decorated(&child, source, true) {
                    class_def.methods.push(f);
                }
                first_statement = false;
            }
            "expression_statement" => {
                // Look for class attributes
                if let Some(assignment) = find_child_by_type(&child, "assignment") {
                    if let Some(left) = find_child_by_type(&assignment, "identifier") {
                        class_def
                            .attributes
                            .push(get_node_text(&left, source).to_string());
                    }
                }
                first_statement = false;
            }
            _ => {
                first_statement = false;
            }
        }
    }
}

/// Extract function/method definition.
fn extract_function(
    node: &Node,
    source: &str,
    is_method: bool,
    decorators: Option<Vec<String>>,
) -> FunctionDef {
    let decorators = decorators.unwrap_or_default();

    let mut func_def = FunctionDef {
        is_method,
        decorators: decorators.clone(),
        start_line: get_start_line(node),
        end_line: get_end_line(node),
        ..Default::default()
    };

    // Check for async
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "async" {
            func_def.is_async = true;
            break;
        }
    }

    // Check decorators for special methods
    for dec in &func_def.decorators {
        match dec.as_str() {
            "staticmethod" => func_def.is_static = true,
            "classmethod" => func_def.is_classmethod = true,
            "property" => func_def.is_property = true,
            _ => {}
        }
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                func_def.name = get_node_text(&child, source).to_string();
            }
            "parameters" => {
                func_def.parameters = extract_parameters(&child, source);
            }
            "type" => {
                func_def.return_type = Some(get_node_text(&child, source).to_string());
            }
            "block" => {
                func_def.body_complexity = complexity::calculate_for_node(&child, source, "python");
                func_def.body_source = Some(get_node_text(&child, source).to_string());
                func_def.call_sites = extract_call_sites(&child, source);

                // Check for docstring
                let mut block_cursor = child.walk();
                for stmt in child.children(&mut block_cursor) {
                    if stmt.kind() == "expression_statement" {
                        if let Some(expr) = find_child_by_type(&stmt, "string") {
                            func_def.docstring = Some(extract_string(&expr, source));
                        }
                        break;
                    } else if stmt.kind() != "comment" {
                        break;
                    }
                }
            }
            _ => {}
        }
    }

    func_def
}

/// Extract function parameters.
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
            "typed_parameter" => {
                params.push(extract_typed_parameter(&child, source));
            }
            "default_parameter" => {
                params.push(extract_default_parameter(&child, source));
            }
            "typed_default_parameter" => {
                params.push(extract_typed_default_parameter(&child, source));
            }
            "list_splat_pattern" => {
                // *args
                let name = find_child_by_type(&child, "identifier")
                    .map(|n| get_node_text(&n, source).to_string())
                    .unwrap_or_else(|| "args".to_string());
                params.push(ParameterDef {
                    name,
                    is_variadic: true,
                    ..Default::default()
                });
            }
            "dictionary_splat_pattern" => {
                // **kwargs
                let name = find_child_by_type(&child, "identifier")
                    .map(|n| get_node_text(&n, source).to_string())
                    .unwrap_or_else(|| "kwargs".to_string());
                params.push(ParameterDef {
                    name,
                    is_keyword: true,
                    ..Default::default()
                });
            }
            _ => {}
        }
    }

    params
}

/// Extract a typed parameter (name: type).
fn extract_typed_parameter(node: &Node, source: &str) -> ParameterDef {
    let mut name = String::new();
    let mut type_annotation = None;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                name = get_node_text(&child, source).to_string();
            }
            "type" => {
                type_annotation = Some(get_node_text(&child, source).to_string());
            }
            _ => {}
        }
    }

    ParameterDef {
        name,
        type_annotation,
        ..Default::default()
    }
}

/// Extract a parameter with default value (name=value).
fn extract_default_parameter(node: &Node, source: &str) -> ParameterDef {
    let mut name = String::new();
    let mut default = None;

    let mut cursor = node.walk();
    let children: Vec<_> = node.children(&mut cursor).collect();

    for (i, child) in children.iter().enumerate() {
        if child.kind() == "identifier" && name.is_empty() {
            name = get_node_text(child, source).to_string();
        } else if child.kind() == "=" && i + 1 < children.len() {
            default = Some(get_node_text(&children[i + 1], source).to_string());
        }
    }

    ParameterDef {
        name,
        default_value: default,
        ..Default::default()
    }
}

/// Extract a typed parameter with default value (name: type = value).
fn extract_typed_default_parameter(node: &Node, source: &str) -> ParameterDef {
    let mut name = String::new();
    let mut type_annotation = None;
    let mut default = None;

    let mut cursor = node.walk();
    let children: Vec<_> = node.children(&mut cursor).collect();

    for (i, child) in children.iter().enumerate() {
        match child.kind() {
            "identifier" if name.is_empty() => {
                name = get_node_text(child, source).to_string();
            }
            "type" => {
                type_annotation = Some(get_node_text(child, source).to_string());
            }
            "=" => {
                if i + 1 < children.len() {
                    default = Some(get_node_text(&children[i + 1], source).to_string());
                }
            }
            _ => {}
        }
    }

    ParameterDef {
        name,
        type_annotation,
        default_value: default,
        ..Default::default()
    }
}

/// Result of extracting a decorated definition.
enum Decorated {
    Class(ClassDef),
    Function(FunctionDef),
}

/// Extract decorated class or function.
fn extract_decorated(node: &Node, source: &str, is_method: bool) -> Decorated {
    let mut decorators = Vec::new();

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "decorator" => {
                let mut dec_text = get_node_text(&child, source).to_string();
                // Remove @ prefix
                if dec_text.starts_with('@') {
                    dec_text = dec_text[1..].to_string();
                }
                // Get just the decorator name (not arguments)
                if let Some(paren_idx) = dec_text.find('(') {
                    dec_text = dec_text[..paren_idx].to_string();
                }
                decorators.push(dec_text);
            }
            "class_definition" => {
                return Decorated::Class(extract_class(&child, source, Some(decorators)));
            }
            "function_definition" => {
                return Decorated::Function(extract_function(
                    &child,
                    source,
                    is_method,
                    Some(decorators),
                ));
            }
            _ => {}
        }
    }

    // Fallback - shouldn't reach here
    Decorated::Function(FunctionDef {
        name: "unknown".to_string(),
        decorators,
        ..Default::default()
    })
}

/// Extract string content, removing quotes.
fn extract_string(node: &Node, source: &str) -> String {
    let text = get_node_text(node, source);

    // Handle triple-quoted strings
    if text.starts_with("\"\"\"") || text.starts_with("'''") {
        return text[3..text.len().saturating_sub(3)].trim().to_string();
    }
    // Handle regular strings
    if text.starts_with('"') || text.starts_with('\'') {
        return text[1..text.len().saturating_sub(1)].to_string();
    }
    // Handle f-strings and other prefixed strings
    if text.len() > 1 && (text.chars().nth(1) == Some('"') || text.chars().nth(1) == Some('\'')) {
        let inner = &text[2..];
        if inner.starts_with("\"\"") || inner.starts_with("''") {
            return inner[2..inner.len().saturating_sub(3)].trim().to_string();
        }
        return inner[..inner.len().saturating_sub(1)].to_string();
    }

    text.to_string()
}

/// Extract dynamic import patterns from the AST.
fn extract_dynamic_imports(root: &Node, source: &str) -> Vec<ImportDef> {
    let mut dynamic_imports = Vec::new();
    find_dynamic_imports_recursive(root, source, &mut dynamic_imports);
    dynamic_imports
}

/// Recursively search for dynamic import patterns.
fn find_dynamic_imports_recursive(node: &Node, source: &str, results: &mut Vec<ImportDef>) {
    if node.kind() == "call" {
        if let Some(import) = check_dynamic_import_call(node, source) {
            results.push(import);
        }
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        find_dynamic_imports_recursive(&child, source, results);
    }
}

/// Check if a call node is a dynamic import pattern.
fn check_dynamic_import_call(node: &Node, source: &str) -> Option<ImportDef> {
    let func_node =
        find_child_by_type(node, "attribute").or_else(|| find_child_by_type(node, "identifier"))?;

    let func_text = get_node_text(&func_node, source);
    let line_number = get_start_line(node);

    // Check for importlib.import_module()
    if func_text == "importlib.import_module" || func_text.ends_with(".import_module") {
        return extract_importlib_call(node, source, line_number);
    }

    // Check for __import__()
    if func_text == "__import__" {
        return extract_builtin_import_call(node, source, line_number);
    }

    None
}

/// Extract importlib.import_module() call.
fn extract_importlib_call(node: &Node, source: &str, line_number: u32) -> Option<ImportDef> {
    let args_node = find_child_by_type(node, "argument_list")?;

    let mut cursor = args_node.walk();
    let first_arg = args_node
        .children(&mut cursor)
        .find(|c| c.kind() != "(" && c.kind() != ")" && c.kind() != ",")?;

    let arg_text = get_node_text(&first_arg, source);

    // Determine if it's a static string or dynamic pattern
    if first_arg.kind() == "string"
        && !arg_text.starts_with("f'")
        && !arg_text.starts_with("f\"")
        && !arg_text.starts_with("F'")
        && !arg_text.starts_with("F\"")
    {
        // Static string
        let module_name = extract_string(&first_arg, source);
        Some(ImportDef {
            module: module_name,
            is_dynamic: true,
            dynamic_source: Some("importlib".to_string()),
            line_number,
            ..Default::default()
        })
    } else {
        // Dynamic pattern
        Some(ImportDef {
            module: "<dynamic>".to_string(),
            is_dynamic: true,
            dynamic_pattern: Some(arg_text.to_string()),
            dynamic_source: Some("importlib".to_string()),
            line_number,
            ..Default::default()
        })
    }
}

/// Extract __import__() call.
fn extract_builtin_import_call(node: &Node, source: &str, line_number: u32) -> Option<ImportDef> {
    let args_node = find_child_by_type(node, "argument_list")?;

    let mut cursor = args_node.walk();
    let first_arg = args_node
        .children(&mut cursor)
        .find(|c| c.kind() != "(" && c.kind() != ")" && c.kind() != ",")?;

    let arg_text = get_node_text(&first_arg, source);

    if first_arg.kind() == "string" {
        // Static string
        let module_name = extract_string(&first_arg, source);
        Some(ImportDef {
            module: module_name,
            is_dynamic: true,
            dynamic_source: Some("__import__".to_string()),
            line_number,
            ..Default::default()
        })
    } else {
        // Dynamic pattern
        Some(ImportDef {
            module: "<dynamic>".to_string(),
            is_dynamic: true,
            dynamic_pattern: Some(arg_text.to_string()),
            dynamic_source: Some("__import__".to_string()),
            line_number,
            ..Default::default()
        })
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

/// Extract a single call site from a call node.
fn extract_call_site(node: &Node, source: &str) -> Option<CallSiteDef> {
    // The function being called is in the first child (before argument_list)
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
        "attribute" => {
            // Method call: obj.method() or self.method()
            let full_text = get_node_text(&func_node, source);

            // Get the object (receiver) and method name
            let object_node = find_child_by_type(&func_node, "identifier")
                .or_else(|| find_child_by_type(&func_node, "attribute"));
            let method_node = func_node.child_by_field_name("attribute");

            let receiver = object_node.map(|n| get_node_text(&n, source).to_string());
            let method_name = method_node
                .map(|n| get_node_text(&n, source).to_string())
                .unwrap_or_else(|| full_text.to_string());

            // Check if it's self.method() or cls.method()
            let is_self_call = receiver
                .as_ref()
                .map(|r| r == "self" || r == "cls")
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
        _ => {
            // Other callable patterns (subscript, call result, etc.)
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
    fn test_parse_simple_function() {
        let source = r#"
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
"#;
        let result = parse(source, "test.py").unwrap();
        assert_eq!(result.functions.len(), 1);
        assert_eq!(result.functions[0].name, "hello");
        assert_eq!(result.functions[0].return_type, Some("str".to_string()));
    }

    #[test]
    fn test_parse_class() {
        let source = r#"
class MyClass(BaseClass):
    """A test class."""

    def method(self):
        pass
"#;
        let result = parse(source, "test.py").unwrap();
        assert_eq!(result.classes.len(), 1);
        assert_eq!(result.classes[0].name, "MyClass");
        assert_eq!(result.classes[0].bases, vec!["BaseClass"]);
        assert_eq!(result.classes[0].methods.len(), 1);
    }

    #[test]
    fn test_parse_imports() {
        let source = r#"
import os
from pathlib import Path
from typing import Optional, List
"#;
        let result = parse(source, "test.py").unwrap();
        assert_eq!(result.imports.len(), 3);
        assert_eq!(result.imports[0].module, "os");
        assert_eq!(result.imports[1].module, "pathlib");
        assert_eq!(result.imports[1].names, vec!["Path"]);
    }

    #[test]
    fn test_extract_call_sites() {
        let source = r#"
def process_data(data):
    validated = validate(data)
    result = self.transform(validated)
    helper.process(result)
    return save(result)
"#;
        let result = parse(source, "test.py").unwrap();
        assert_eq!(result.functions.len(), 1);
        let func = &result.functions[0];
        assert!(
            func.call_sites.len() >= 3,
            "Expected at least 3 call sites, got {}",
            func.call_sites.len()
        );

        // Check we captured validate() call
        assert!(func.call_sites.iter().any(|c| c.callee == "validate"));
    }

    #[test]
    fn test_method_call_detection() {
        let source = r#"
class MyClass:
    def do_work(self):
        self.helper()
        other.process()
"#;
        let result = parse(source, "test.py").unwrap();
        let method = &result.classes[0].methods[0];

        // self.helper() should be detected as method call
        let self_call = method.call_sites.iter().find(|c| c.callee == "helper");
        assert!(self_call.is_some(), "Should find self.helper() call");
        assert!(self_call.unwrap().is_method_call);
        assert_eq!(self_call.unwrap().receiver, Some("self".to_string()));
    }

    #[test]
    fn test_referenced_types_extraction() {
        let source = r#"
class MUbase:
    def get_node(self, node_id: str) -> Node | None:
        pass

    def get_edges(self, source: Node) -> list[Edge]:
        pass

    def process(self, handler: RequestHandler) -> ResponseData:
        pass
"#;
        let result = parse(source, "test.py").unwrap();
        assert_eq!(result.classes.len(), 1);
        let class = &result.classes[0];
        assert_eq!(class.name, "MUbase");
        // Should extract Node, Edge, RequestHandler, ResponseData
        // But NOT: str, list, None (builtins), MUbase (self-reference)
        assert_eq!(
            class.referenced_types,
            vec!["Edge", "Node", "RequestHandler", "ResponseData"]
        );
    }

    #[test]
    fn test_referenced_types_filters_self() {
        let source = r#"
class TreeNode:
    def get_children(self) -> list[TreeNode]:
        pass

    def find(self, predicate: Callable) -> TreeNode | None:
        pass
"#;
        let result = parse(source, "test.py").unwrap();
        let class = &result.classes[0];
        // TreeNode should be filtered out as self-reference
        assert!(class.referenced_types.is_empty());
    }

    #[test]
    fn test_referenced_types_complex_annotations() {
        let source = r#"
class APIClient:
    def fetch(self, request: HTTPRequest) -> HTTPResponse:
        pass

    def batch(self, items: list[BatchItem]) -> dict[str, ResultData]:
        pass
"#;
        let result = parse(source, "test.py").unwrap();
        let class = &result.classes[0];
        assert_eq!(
            class.referenced_types,
            vec!["BatchItem", "HTTPRequest", "HTTPResponse", "ResultData"]
        );
    }
}
