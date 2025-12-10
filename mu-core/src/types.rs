//! Data models for parsed AST elements.
//!
//! These types mirror the Python dataclasses in `mu.parser.models` exactly,
//! enabling seamless interoperability between Rust and Python via PyO3.

use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::{Deserialize, Serialize};

/// A function/method parameter.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ParameterDef {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub type_annotation: Option<String>,
    #[pyo3(get, set)]
    pub default_value: Option<String>,
    #[pyo3(get, set)]
    pub is_variadic: bool,
    #[pyo3(get, set)]
    pub is_keyword: bool,
}

#[pymethods]
impl ParameterDef {
    #[new]
    #[pyo3(signature = (name, type_annotation=None, default_value=None, is_variadic=false, is_keyword=false))]
    fn new(
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

    /// Convert to Python dict matching Python's to_dict() output.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        dict.set_item("name", &self.name)?;
        dict.set_item("type", &self.type_annotation)?;
        dict.set_item("default", &self.default_value)?;
        dict.set_item("variadic", self.is_variadic)?;
        dict.set_item("keyword", self.is_keyword)?;
        Ok(dict.into())
    }
}

/// A function call site within a function body.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CallSiteDef {
    #[pyo3(get, set)]
    pub callee: String, // "validate_user" or "self.save"
    #[pyo3(get, set)]
    pub line: u32,
    #[pyo3(get, set)]
    pub is_method_call: bool, // self.x() vs x()
    #[pyo3(get, set)]
    pub receiver: Option<String>, // "self", "user_service", etc.
}

#[pymethods]
impl CallSiteDef {
    #[new]
    #[pyo3(signature = (callee, line=0, is_method_call=false, receiver=None))]
    fn new(callee: String, line: u32, is_method_call: bool, receiver: Option<String>) -> Self {
        Self {
            callee,
            line,
            is_method_call,
            receiver,
        }
    }

    /// Convert to Python dict matching Python's to_dict() output.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        dict.set_item("callee", &self.callee)?;
        dict.set_item("line", self.line)?;
        dict.set_item("is_method_call", self.is_method_call)?;
        dict.set_item("receiver", &self.receiver)?;
        Ok(dict.into())
    }
}

/// A function or method definition.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct FunctionDef {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub parameters: Vec<ParameterDef>,
    #[pyo3(get, set)]
    pub return_type: Option<String>,
    #[pyo3(get, set)]
    pub decorators: Vec<String>,
    #[pyo3(get, set)]
    pub is_async: bool,
    #[pyo3(get, set)]
    pub is_method: bool,
    #[pyo3(get, set)]
    pub is_static: bool,
    #[pyo3(get, set)]
    pub is_classmethod: bool,
    #[pyo3(get, set)]
    pub is_property: bool,
    #[pyo3(get, set)]
    pub docstring: Option<String>,
    #[pyo3(get, set)]
    pub body_complexity: u32,
    #[pyo3(get, set)]
    pub body_source: Option<String>,
    #[pyo3(get, set)]
    pub call_sites: Vec<CallSiteDef>,
    #[pyo3(get, set)]
    pub start_line: u32,
    #[pyo3(get, set)]
    pub end_line: u32,
}

#[pymethods]
impl FunctionDef {
    #[new]
    #[pyo3(signature = (name, parameters=vec![], return_type=None, decorators=vec![], is_async=false, is_method=false, is_static=false, is_classmethod=false, is_property=false, docstring=None, body_complexity=0, body_source=None, call_sites=vec![], start_line=0, end_line=0))]
    #[allow(clippy::too_many_arguments)]
    fn new(
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

    /// Convert to Python dict matching Python's to_dict() output.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        dict.set_item("name", &self.name)?;

        let params: Vec<PyObject> = self
            .parameters
            .iter()
            .map(|p| p.to_dict(py))
            .collect::<PyResult<Vec<_>>>()?;
        dict.set_item("parameters", params)?;
        dict.set_item("return_type", &self.return_type)?;
        dict.set_item("decorators", &self.decorators)?;
        dict.set_item("is_async", self.is_async)?;
        dict.set_item("is_method", self.is_method)?;
        dict.set_item("is_static", self.is_static)?;
        dict.set_item("is_classmethod", self.is_classmethod)?;
        dict.set_item("is_property", self.is_property)?;
        dict.set_item("docstring", &self.docstring)?;
        dict.set_item("body_complexity", self.body_complexity)?;
        dict.set_item("lines", (self.start_line, self.end_line))?;

        // Only include body_source if present (avoid bloating JSON output)
        if self.body_source.is_some() {
            dict.set_item("body_source", &self.body_source)?;
        }

        // Only include call_sites if non-empty (avoid bloating JSON output)
        if !self.call_sites.is_empty() {
            let call_sites: Vec<PyObject> = self
                .call_sites
                .iter()
                .map(|c| c.to_dict(py))
                .collect::<PyResult<Vec<_>>>()?;
            dict.set_item("call_sites", call_sites)?;
        }

        Ok(dict.into())
    }
}

/// A class definition.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ClassDef {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub bases: Vec<String>,
    #[pyo3(get, set)]
    pub decorators: Vec<String>,
    #[pyo3(get, set)]
    pub methods: Vec<FunctionDef>,
    #[pyo3(get, set)]
    pub attributes: Vec<String>,
    #[pyo3(get, set)]
    pub docstring: Option<String>,
    #[pyo3(get, set)]
    pub start_line: u32,
    #[pyo3(get, set)]
    pub end_line: u32,
    #[pyo3(get, set)]
    pub referenced_types: Vec<String>,
}

#[pymethods]
impl ClassDef {
    #[new]
    #[pyo3(signature = (name, bases=vec![], decorators=vec![], methods=vec![], attributes=vec![], docstring=None, start_line=0, end_line=0, referenced_types=vec![]))]
    #[allow(clippy::too_many_arguments)]
    fn new(
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

    /// Convert to Python dict matching Python's to_dict() output.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        dict.set_item("name", &self.name)?;
        dict.set_item("bases", &self.bases)?;
        dict.set_item("decorators", &self.decorators)?;

        let methods: Vec<PyObject> = self
            .methods
            .iter()
            .map(|m| m.to_dict(py))
            .collect::<PyResult<Vec<_>>>()?;
        dict.set_item("methods", methods)?;
        dict.set_item("attributes", &self.attributes)?;
        dict.set_item("docstring", &self.docstring)?;
        dict.set_item("lines", (self.start_line, self.end_line))?;

        // Only include referenced_types if non-empty (avoid bloating JSON output)
        if !self.referenced_types.is_empty() {
            dict.set_item("referenced_types", &self.referenced_types)?;
        }

        Ok(dict.into())
    }
}

/// An import statement.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ImportDef {
    #[pyo3(get, set)]
    pub module: String,
    #[pyo3(get, set)]
    pub names: Vec<String>,
    #[pyo3(get, set)]
    pub alias: Option<String>,
    #[pyo3(get, set)]
    pub is_from: bool,
    #[pyo3(get, set)]
    pub is_dynamic: bool,
    #[pyo3(get, set)]
    pub dynamic_pattern: Option<String>,
    #[pyo3(get, set)]
    pub dynamic_source: Option<String>,
    #[pyo3(get, set)]
    pub line_number: u32,
}

#[pymethods]
impl ImportDef {
    #[new]
    #[pyo3(signature = (module, names=vec![], alias=None, is_from=false, is_dynamic=false, dynamic_pattern=None, dynamic_source=None, line_number=0))]
    fn new(
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

    /// Convert to Python dict matching Python's to_dict() output.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        dict.set_item("module", &self.module)?;
        dict.set_item("names", &self.names)?;
        dict.set_item("alias", &self.alias)?;
        dict.set_item("is_from", self.is_from)?;

        // Only include dynamic fields if is_dynamic is true
        if self.is_dynamic {
            dict.set_item("is_dynamic", true)?;
            if self.dynamic_pattern.is_some() {
                dict.set_item("dynamic_pattern", &self.dynamic_pattern)?;
            }
            if self.dynamic_source.is_some() {
                dict.set_item("dynamic_source", &self.dynamic_source)?;
            }
            if self.line_number > 0 {
                dict.set_item("line", self.line_number)?;
            }
        }

        Ok(dict.into())
    }
}

/// A module/file definition.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ModuleDef {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub path: String,
    #[pyo3(get, set)]
    pub language: String,
    #[pyo3(get, set)]
    pub imports: Vec<ImportDef>,
    #[pyo3(get, set)]
    pub classes: Vec<ClassDef>,
    #[pyo3(get, set)]
    pub functions: Vec<FunctionDef>,
    #[pyo3(get, set)]
    pub module_docstring: Option<String>,
    #[pyo3(get, set)]
    pub total_lines: u32,
}

#[pymethods]
impl ModuleDef {
    #[new]
    #[pyo3(signature = (name, path, language, imports=vec![], classes=vec![], functions=vec![], module_docstring=None, total_lines=0))]
    fn new(
        name: String,
        path: String,
        language: String,
        imports: Vec<ImportDef>,
        classes: Vec<ClassDef>,
        functions: Vec<FunctionDef>,
        module_docstring: Option<String>,
        total_lines: u32,
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
        }
    }

    /// Convert to Python dict matching Python's to_dict() output.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        dict.set_item("name", &self.name)?;
        dict.set_item("path", &self.path)?;
        dict.set_item("language", &self.language)?;

        let imports: Vec<PyObject> = self
            .imports
            .iter()
            .map(|i| i.to_dict(py))
            .collect::<PyResult<Vec<_>>>()?;
        dict.set_item("imports", imports)?;

        let classes: Vec<PyObject> = self
            .classes
            .iter()
            .map(|c| c.to_dict(py))
            .collect::<PyResult<Vec<_>>>()?;
        dict.set_item("classes", classes)?;

        let functions: Vec<PyObject> = self
            .functions
            .iter()
            .map(|f| f.to_dict(py))
            .collect::<PyResult<Vec<_>>>()?;
        dict.set_item("functions", functions)?;

        dict.set_item("module_docstring", &self.module_docstring)?;
        dict.set_item("total_lines", self.total_lines)?;

        Ok(dict.into())
    }
}

/// File information for parsing.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct FileInfo {
    #[pyo3(get, set)]
    pub path: String,
    #[pyo3(get, set)]
    pub source: String,
    #[pyo3(get, set)]
    pub language: String,
}

#[pymethods]
impl FileInfo {
    #[new]
    #[pyo3(signature = (path, source, language))]
    fn new(path: String, source: String, language: String) -> Self {
        Self {
            path,
            source,
            language,
        }
    }
}

/// Result of parsing a file.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ParseResult {
    #[pyo3(get, set)]
    pub success: bool,
    #[pyo3(get, set)]
    pub module: Option<ModuleDef>,
    #[pyo3(get, set)]
    pub error: Option<String>,
}

#[pymethods]
impl ParseResult {
    #[new]
    #[pyo3(signature = (success, module=None, error=None))]
    fn new(success: bool, module: Option<ModuleDef>, error: Option<String>) -> Self {
        Self {
            success,
            module,
            error,
        }
    }
}

impl ParseResult {
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
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct ExportConfig {
    #[pyo3(get, set)]
    pub shell_safe: bool,
    #[pyo3(get, set)]
    pub include_source: bool,
    #[pyo3(get, set)]
    pub pretty_print: bool,
}

#[pymethods]
impl ExportConfig {
    #[new]
    #[pyo3(signature = (shell_safe=false, include_source=false, pretty_print=false))]
    fn new(shell_safe: bool, include_source: bool, pretty_print: bool) -> Self {
        Self {
            shell_safe,
            include_source,
            pretty_print,
        }
    }
}

/// Information about a redacted secret.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct RedactedSecret {
    #[pyo3(get, set)]
    pub pattern_name: String,
    #[pyo3(get, set)]
    pub line_number: u32,
    #[pyo3(get, set)]
    pub start_col: u32,
    #[pyo3(get, set)]
    pub end_col: u32,
}

#[pymethods]
impl RedactedSecret {
    #[new]
    fn new(pattern_name: String, line_number: u32, start_col: u32, end_col: u32) -> Self {
        Self {
            pattern_name,
            line_number,
            start_col,
            end_col,
        }
    }
}

/// A detected secret in source code.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SecretMatch {
    #[pyo3(get, set)]
    pub pattern_name: String,
    #[pyo3(get, set)]
    pub start: usize,
    #[pyo3(get, set)]
    pub end: usize,
    #[pyo3(get, set)]
    pub line: u32,
    #[pyo3(get, set)]
    pub column: u32,
}

#[pymethods]
impl SecretMatch {
    #[new]
    fn new(pattern_name: String, start: usize, end: usize, line: u32, column: u32) -> Self {
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
