//! Data models for parsed AST elements.
//!
//! These types represent the parsed structure of source code files,
//! providing a language-agnostic representation of modules, classes,
//! functions, and their relationships.

use serde::{Deserialize, Serialize};

/// A function/method parameter.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ParameterDef {
    pub name: String,
    pub type_annotation: Option<String>,
    pub default_value: Option<String>,
    pub is_variadic: bool,
    pub is_keyword: bool,
}

impl ParameterDef {
    pub fn new(
        name: String,
        type_annotation: Option<String>,
        default_value: Option<String>,
        is_variadic: bool,
        is_keyword: bool,
    ) -> Self {
        Self {
            name,
            type_annotation,
            default_value,
            is_variadic,
            is_keyword,
        }
    }
}

/// A function call site within a function body.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CallSiteDef {
    /// The callee name, e.g., "validate_user" or "self.save"
    pub callee: String,
    pub line: u32,
    /// Whether this is a method call (self.x() vs x())
    pub is_method_call: bool,
    /// The receiver, e.g., "self", "user_service"
    pub receiver: Option<String>,
}

impl CallSiteDef {
    pub fn new(callee: String, line: u32, is_method_call: bool, receiver: Option<String>) -> Self {
        Self {
            callee,
            line,
            is_method_call,
            receiver,
        }
    }
}

/// A function or method definition.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct FunctionDef {
    pub name: String,
    pub parameters: Vec<ParameterDef>,
    pub return_type: Option<String>,
    pub decorators: Vec<String>,
    pub is_async: bool,
    pub is_method: bool,
    pub is_static: bool,
    pub is_classmethod: bool,
    pub is_property: bool,
    pub docstring: Option<String>,
    pub body_complexity: u32,
    pub body_source: Option<String>,
    pub call_sites: Vec<CallSiteDef>,
    pub start_line: u32,
    pub end_line: u32,
}

impl FunctionDef {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        name: String,
        parameters: Vec<ParameterDef>,
        return_type: Option<String>,
        decorators: Vec<String>,
        is_async: bool,
        is_method: bool,
        is_static: bool,
        is_classmethod: bool,
        is_property: bool,
        docstring: Option<String>,
        body_complexity: u32,
        body_source: Option<String>,
        call_sites: Vec<CallSiteDef>,
        start_line: u32,
        end_line: u32,
    ) -> Self {
        Self {
            name,
            parameters,
            return_type,
            decorators,
            is_async,
            is_method,
            is_static,
            is_classmethod,
            is_property,
            docstring,
            body_complexity,
            body_source,
            call_sites,
            start_line,
            end_line,
        }
    }
}

/// A class definition.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ClassDef {
    pub name: String,
    pub bases: Vec<String>,
    pub decorators: Vec<String>,
    pub methods: Vec<FunctionDef>,
    pub attributes: Vec<String>,
    pub docstring: Option<String>,
    pub start_line: u32,
    pub end_line: u32,
    pub referenced_types: Vec<String>,
}

impl ClassDef {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        name: String,
        bases: Vec<String>,
        decorators: Vec<String>,
        methods: Vec<FunctionDef>,
        attributes: Vec<String>,
        docstring: Option<String>,
        start_line: u32,
        end_line: u32,
        referenced_types: Vec<String>,
    ) -> Self {
        Self {
            name,
            bases,
            decorators,
            methods,
            attributes,
            docstring,
            start_line,
            end_line,
            referenced_types,
        }
    }
}

/// An import statement.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ImportDef {
    pub module: String,
    pub names: Vec<String>,
    pub alias: Option<String>,
    pub is_from: bool,
    pub is_dynamic: bool,
    pub dynamic_pattern: Option<String>,
    pub dynamic_source: Option<String>,
    pub line_number: u32,
}

impl ImportDef {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        module: String,
        names: Vec<String>,
        alias: Option<String>,
        is_from: bool,
        is_dynamic: bool,
        dynamic_pattern: Option<String>,
        dynamic_source: Option<String>,
        line_number: u32,
    ) -> Self {
        Self {
            module,
            names,
            alias,
            is_from,
            is_dynamic,
            dynamic_pattern,
            dynamic_source,
            line_number,
        }
    }
}

/// A module/file definition.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ModuleDef {
    pub name: String,
    pub path: String,
    pub language: String,
    pub imports: Vec<ImportDef>,
    pub classes: Vec<ClassDef>,
    pub functions: Vec<FunctionDef>,
    pub module_docstring: Option<String>,
    pub total_lines: u32,
    /// Namespace declaration (for C#, Java, Go packages)
    pub namespace: Option<String>,
}

impl ModuleDef {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        name: String,
        path: String,
        language: String,
        imports: Vec<ImportDef>,
        classes: Vec<ClassDef>,
        functions: Vec<FunctionDef>,
        module_docstring: Option<String>,
        total_lines: u32,
        namespace: Option<String>,
    ) -> Self {
        Self {
            name,
            path,
            language,
            imports,
            classes,
            functions,
            module_docstring,
            total_lines,
            namespace,
        }
    }
}

/// File information for parsing.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct FileInfo {
    pub path: String,
    pub source: String,
    pub language: String,
}

impl FileInfo {
    pub fn new(path: String, source: String, language: String) -> Self {
        Self {
            path,
            source,
            language,
        }
    }
}

/// Result of parsing a file.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ParseResult {
    pub success: bool,
    pub module: Option<ModuleDef>,
    pub error: Option<String>,
}

impl ParseResult {
    pub fn new(success: bool, module: Option<ModuleDef>, error: Option<String>) -> Self {
        Self {
            success,
            module,
            error,
        }
    }

    /// Create a successful parse result.
    pub fn ok(module: ModuleDef) -> Self {
        Self {
            success: true,
            module: Some(module),
            error: None,
        }
    }

    /// Create a failed parse result.
    pub fn err(error: String) -> Self {
        Self {
            success: false,
            module: None,
            error: Some(error),
        }
    }
}

/// Configuration for export operations.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ExportConfig {
    pub shell_safe: bool,
    pub include_source: bool,
    pub pretty_print: bool,
}

impl ExportConfig {
    pub fn new(shell_safe: bool, include_source: bool, pretty_print: bool) -> Self {
        Self {
            shell_safe,
            include_source,
            pretty_print,
        }
    }
}

/// Information about a redacted secret.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct RedactedSecret {
    pub pattern_name: String,
    pub line_number: u32,
    pub start_col: u32,
    pub end_col: u32,
}

impl RedactedSecret {
    pub fn new(pattern_name: String, line_number: u32, start_col: u32, end_col: u32) -> Self {
        Self {
            pattern_name,
            line_number,
            start_col,
            end_col,
        }
    }
}

/// A detected secret in source code.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SecretMatch {
    pub pattern_name: String,
    pub start: usize,
    pub end: usize,
    pub line: u32,
    pub column: u32,
}

impl SecretMatch {
    pub fn new(pattern_name: String, start: usize, end: usize, line: u32, column: u32) -> Self {
        Self {
            pattern_name,
            start,
            end,
            line,
            column,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parameter_def_default() {
        let param = ParameterDef::default();
        assert!(param.name.is_empty());
        assert!(!param.is_variadic);
    }

    #[test]
    fn test_function_def_default() {
        let func = FunctionDef::default();
        assert!(func.name.is_empty());
        assert!(!func.is_async);
        assert_eq!(func.body_complexity, 0);
    }

    #[test]
    fn test_module_def_serialization() {
        let module = ModuleDef {
            name: "test".to_string(),
            path: "/test.py".to_string(),
            language: "python".to_string(),
            ..Default::default()
        };

        let json = serde_json::to_string(&module).unwrap();
        assert!(json.contains("\"name\":\"test\""));
    }
}
