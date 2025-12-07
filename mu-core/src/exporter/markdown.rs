//! Markdown format exporter.

use crate::types::{ClassDef, ExportConfig, FunctionDef, ModuleDef};

/// Export module to Markdown format.
pub fn export(module: &ModuleDef) -> String {
    export_module(module)
}

/// Export modules to Markdown format.
pub fn export_all(modules: &[ModuleDef], _config: &ExportConfig) -> String {
    let mut output = String::new();

    for module in modules {
        output.push_str(&export_module(module));
        output.push_str("\n---\n\n");
    }

    output
}

/// Export a single module to Markdown.
fn export_module(module: &ModuleDef) -> String {
    let mut lines = Vec::new();

    // Module header
    lines.push(format!("# {} ({})", module.name, module.language));
    lines.push(String::new());

    if let Some(ref doc) = module.module_docstring {
        lines.push(format!("> {}", doc));
        lines.push(String::new());
    }

    // Imports
    if !module.imports.is_empty() {
        lines.push("## Imports".to_string());
        lines.push(String::new());
        for import in &module.imports {
            if import.is_from && !import.names.is_empty() {
                lines.push(format!(
                    "- `from {} import {}`",
                    import.module,
                    import.names.join(", ")
                ));
            } else {
                lines.push(format!("- `import {}`", import.module));
            }
        }
        lines.push(String::new());
    }

    // Classes
    if !module.classes.is_empty() {
        lines.push("## Classes".to_string());
        lines.push(String::new());
        for class in &module.classes {
            lines.push(export_class(class));
        }
    }

    // Functions
    if !module.functions.is_empty() {
        lines.push("## Functions".to_string());
        lines.push(String::new());
        for func in &module.functions {
            lines.push(export_function(func));
        }
    }

    lines.join("\n")
}

/// Export a class to Markdown.
fn export_class(class: &ClassDef) -> String {
    let mut lines = Vec::new();

    // Class header
    let bases = if !class.bases.is_empty() {
        format!("({})", class.bases.join(", "))
    } else {
        String::new()
    };
    lines.push(format!("### `class {}{}`", class.name, bases));
    lines.push(String::new());

    if let Some(ref doc) = class.docstring {
        lines.push(format!("> {}", doc));
        lines.push(String::new());
    }

    // Methods
    if !class.methods.is_empty() {
        lines.push("**Methods:**".to_string());
        lines.push(String::new());
        for method in &class.methods {
            let params: Vec<_> = method
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

            let ret = method
                .return_type
                .as_ref()
                .map(|r| format!(" -> {}", r))
                .unwrap_or_default();

            let async_prefix = if method.is_async { "async " } else { "" };
            lines.push(format!(
                "- `{}{}({}){}`",
                async_prefix,
                method.name,
                params.join(", "),
                ret
            ));
        }
        lines.push(String::new());
    }

    lines.join("\n")
}

/// Export a function to Markdown.
fn export_function(func: &FunctionDef) -> String {
    let mut lines = Vec::new();

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

    let ret = func
        .return_type
        .as_ref()
        .map(|r| format!(" -> {}", r))
        .unwrap_or_default();

    let async_prefix = if func.is_async { "async " } else { "" };

    lines.push(format!(
        "### `{}{}({}){}`",
        async_prefix,
        func.name,
        params.join(", "),
        ret
    ));
    lines.push(String::new());

    if let Some(ref doc) = func.docstring {
        lines.push(format!("> {}", doc));
        lines.push(String::new());
    }

    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_export_markdown() {
        let modules = vec![ModuleDef {
            name: "test".to_string(),
            language: "python".to_string(),
            ..Default::default()
        }];

        let config = ExportConfig::default();
        let output = export_all(&modules, &config);
        assert!(output.contains("# test (python)"));
    }
}
