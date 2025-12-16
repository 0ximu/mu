//! MU format exporter.
//!
//! Exports ModuleDef to the sigil-based MU format.

use crate::types::{ExportConfig, ModuleDef};

// MU Sigils
const SIGIL_MODULE: &str = "!";
const SIGIL_ENTITY: &str = "$";
const SIGIL_FUNCTION: &str = "#";
const SIGIL_METADATA: &str = "@";
const OP_FLOW: &str = "->";
#[allow(dead_code)]
const OP_MUTATION: &str = "=>";

/// Export module to MU format.
pub fn export(module: &ModuleDef) -> String {
    let config = ExportConfig::default();
    export_module(module, &config)
}

/// Export modules to MU format.
pub fn export_all(modules: &[ModuleDef], config: &ExportConfig) -> String {
    let mut output = String::new();

    for module in modules {
        output.push_str(&export_module(module, config));
        output.push('\n');
    }

    output
}

/// Export a single module to MU format.
fn export_module(module: &ModuleDef, config: &ExportConfig) -> String {
    let mut lines = Vec::new();

    // Module header
    let module_line = if config.shell_safe {
        format!("\\{} {} [{}]", SIGIL_MODULE, module.name, module.language)
    } else {
        format!("{} {} [{}]", SIGIL_MODULE, module.name, module.language)
    };
    lines.push(module_line);

    // Docstring
    if let Some(ref doc) = module.module_docstring {
        lines.push(format!("  :: {}", truncate_docstring(doc)));
    }

    // Imports
    if !module.imports.is_empty() {
        let imports: Vec<_> = module
            .imports
            .iter()
            .filter(|i| !i.is_dynamic)
            .map(|i| {
                if i.is_from && !i.names.is_empty() {
                    format!("{}.{{{}}}", i.module, i.names.join(", "))
                } else {
                    i.module.clone()
                }
            })
            .collect();

        if !imports.is_empty() {
            let import_line = if config.shell_safe {
                format!("  \\{} {}", SIGIL_METADATA, imports.join(", "))
            } else {
                format!("  {} {}", SIGIL_METADATA, imports.join(", "))
            };
            lines.push(import_line);
        }
    }

    // Classes
    for class in &module.classes {
        lines.push(export_class(class, config));
    }

    // Functions
    for func in &module.functions {
        lines.push(export_function(func, config, 1));
    }

    lines.join("\n")
}

/// Export a class to MU format.
fn export_class(class: &crate::types::ClassDef, config: &ExportConfig) -> String {
    let mut lines = Vec::new();

    // Class header with bases
    let bases_str = if !class.bases.is_empty() {
        format!(" < {}", class.bases.join(", "))
    } else {
        String::new()
    };

    let class_line = if config.shell_safe {
        format!("  \\{} {}{}", SIGIL_ENTITY, class.name, bases_str)
    } else {
        format!("  {} {}{}", SIGIL_ENTITY, class.name, bases_str)
    };
    lines.push(class_line);

    // Decorators
    for dec in &class.decorators {
        let dec_line = if config.shell_safe {
            format!("    \\{} @{}", SIGIL_METADATA, dec)
        } else {
            format!("    {} @{}", SIGIL_METADATA, dec)
        };
        lines.push(dec_line);
    }

    // Docstring
    if let Some(ref doc) = class.docstring {
        lines.push(format!("    :: {}", truncate_docstring(doc)));
    }

    // Attributes
    if !class.attributes.is_empty() {
        lines.push(format!("    :: attrs: {}", class.attributes.join(", ")));
    }

    // Methods
    for method in &class.methods {
        lines.push(export_function(method, config, 2));
    }

    lines.join("\n")
}

/// Export a function to MU format.
fn export_function(
    func: &crate::types::FunctionDef,
    config: &ExportConfig,
    indent: usize,
) -> String {
    let indent_str = "  ".repeat(indent);
    let mut parts = Vec::new();

    // Function sigil
    let sigil = if config.shell_safe {
        format!("\\{}", SIGIL_FUNCTION)
    } else {
        SIGIL_FUNCTION.to_string()
    };
    parts.push(sigil);

    // Async marker
    if func.is_async {
        parts.push("async".to_string());
    }

    // Function name
    parts.push(func.name.clone());

    // Parameters (filter self/cls)
    let params: Vec<_> = func
        .parameters
        .iter()
        .filter(|p| p.name != "self" && p.name != "cls")
        .map(|p| {
            if let Some(ref t) = p.type_annotation {
                format!("{}: {}", p.name, t)
            } else {
                p.name.clone()
            }
        })
        .collect();

    if !params.is_empty() {
        parts.push(format!("({})", params.join(", ")));
    } else {
        parts.push("()".to_string());
    }

    // Return type
    if let Some(ref ret) = func.return_type {
        parts.push(format!("{} {}", OP_FLOW, ret));
    }

    let main_line = format!("{}{}", indent_str, parts.join(" "));

    let mut lines = vec![main_line];

    // Decorators
    for dec in &func.decorators {
        if dec != "staticmethod" && dec != "classmethod" && dec != "property" {
            let dec_line = if config.shell_safe {
                format!("{}  \\{} @{}", indent_str, SIGIL_METADATA, dec)
            } else {
                format!("{}  {} @{}", indent_str, SIGIL_METADATA, dec)
            };
            lines.push(dec_line);
        }
    }

    // Static/classmethod/property indicators
    if func.is_static {
        lines.push(format!("{}  :: static", indent_str));
    }
    if func.is_classmethod {
        lines.push(format!("{}  :: classmethod", indent_str));
    }
    if func.is_property {
        lines.push(format!("{}  :: property", indent_str));
    }

    // Docstring
    if let Some(ref doc) = func.docstring {
        lines.push(format!("{}  :: {}", indent_str, truncate_docstring(doc)));
    }

    // Complexity indicator
    if func.body_complexity > 10 {
        lines.push(format!(
            "{}  :: complexity: {}",
            indent_str, func.body_complexity
        ));
    }

    lines.join("\n")
}

/// Truncate docstring to first line or 80 chars.
fn truncate_docstring(doc: &str) -> String {
    let first_line = doc.lines().next().unwrap_or("");
    if first_line.len() > 80 {
        format!("{}...", &first_line[..77])
    } else {
        first_line.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{FunctionDef, ParameterDef};

    #[test]
    fn test_export_simple_function() {
        let func = FunctionDef {
            name: "hello".to_string(),
            parameters: vec![ParameterDef {
                name: "name".to_string(),
                type_annotation: Some("str".to_string()),
                ..Default::default()
            }],
            return_type: Some("str".to_string()),
            ..Default::default()
        };

        let config = ExportConfig::default();
        let output = export_function(&func, &config, 0);
        assert!(output.contains("# hello"));
        assert!(output.contains("name: str"));
        assert!(output.contains("-> str"));
    }

    #[test]
    fn test_shell_safe() {
        let module = ModuleDef {
            name: "test".to_string(),
            language: "python".to_string(),
            ..Default::default()
        };

        let config = ExportConfig {
            shell_safe: true,
            ..Default::default()
        };
        let output = export_all(&[module], &config);
        assert!(output.contains("\\!"));
    }
}
