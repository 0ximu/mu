//! MU sigil format output for compact code representation.
//!
//! The MU format uses sigils to represent different code elements:
//! - `!` - Module/namespace
//! - `$` - Function
//! - `@` - Type/class/struct
//! - `#` - Constant
//! - `%` - Variable
//! - `&` - Reference/import
//! - `^` - Export
//! - `~` - Dependency
//! - `::` - Section marker
//! - `|` - Continuation/detail
//! - `->` - Relationship/flow

use super::OutputConfig;
use colored::Colorize;
use serde::Serialize;

/// MU sigil format output formatter
pub struct MuOutput;

/// Sigil types for MU format
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Sigil {
    /// Module or namespace (!)
    Module,
    /// Function ($)
    Function,
    /// Type, class, or struct (@)
    Type,
    /// Constant (#)
    Constant,
    /// Variable (%)
    Variable,
    /// Reference or import (&)
    Reference,
    /// Export (^)
    Export,
    /// Dependency (~)
    Dependency,
    /// Section marker (::)
    Section,
    /// Continuation or detail (|)
    Continuation,
    /// Relationship or flow (->)
    Flow,
}

impl Sigil {
    /// Get the sigil character(s)
    pub fn char(&self) -> &'static str {
        match self {
            Sigil::Module => "!",
            Sigil::Function => "$",
            Sigil::Type => "@",
            Sigil::Constant => "#",
            Sigil::Variable => "%",
            Sigil::Reference => "&",
            Sigil::Export => "^",
            Sigil::Dependency => "~",
            Sigil::Section => "::",
            Sigil::Continuation => "|",
            Sigil::Flow => "->",
        }
    }

    /// Format a sigil with optional color
    pub fn format(&self, use_colors: bool) -> String {
        let s = self.char();
        if use_colors {
            match self {
                Sigil::Module => s.bright_blue().to_string(),
                Sigil::Function => s.bright_green().to_string(),
                Sigil::Type => s.bright_yellow().to_string(),
                Sigil::Constant => s.bright_magenta().to_string(),
                Sigil::Variable => s.cyan().to_string(),
                Sigil::Reference => s.blue().to_string(),
                Sigil::Export => s.green().to_string(),
                Sigil::Dependency => s.red().to_string(),
                Sigil::Section => s.white().bold().to_string(),
                Sigil::Continuation => s.dimmed().to_string(),
                Sigil::Flow => s.yellow().to_string(),
            }
        } else {
            s.to_string()
        }
    }
}

impl MuOutput {
    /// Format data as MU sigil format string
    ///
    /// For types without custom MU representation, falls back to a
    /// structured format based on JSON serialization.
    pub fn format<T: Serialize>(data: &T, config: &OutputConfig) -> String {
        if let Ok(json) = serde_json::to_value(data) {
            Self::format_value(&json, config, 0)
        } else {
            ":: error\n| Failed to serialize data".to_string()
        }
    }

    /// Format a JSON value as MU format
    fn format_value(value: &serde_json::Value, config: &OutputConfig, depth: usize) -> String {
        let indent = "  ".repeat(depth);
        let use_colors = config.use_colors();

        match value {
            serde_json::Value::Null => format!("{}{}", indent, "-".dimmed()),
            serde_json::Value::Bool(b) => {
                if use_colors {
                    format!(
                        "{}{}",
                        indent,
                        if *b { "true".green() } else { "false".red() }
                    )
                } else {
                    format!("{}{}", indent, b)
                }
            }
            serde_json::Value::Number(n) => {
                if use_colors {
                    format!("{}{}", indent, n.to_string().cyan())
                } else {
                    format!("{}{}", indent, n)
                }
            }
            serde_json::Value::String(s) => {
                if use_colors {
                    format!("{}{}", indent, s.yellow())
                } else {
                    format!("{}{}", indent, s)
                }
            }
            serde_json::Value::Array(arr) => {
                if arr.is_empty() {
                    format!("{}[]", indent)
                } else {
                    let items: Vec<String> = arr
                        .iter()
                        .map(|v| Self::format_value(v, config, depth + 1))
                        .collect();
                    format!("{}[\n{}\n{}]", indent, items.join("\n"), indent)
                }
            }
            serde_json::Value::Object(obj) => Self::format_object(obj, config, depth),
        }
    }

    /// Format a JSON object as MU format with sigil detection
    fn format_object(
        obj: &serde_json::Map<String, serde_json::Value>,
        config: &OutputConfig,
        depth: usize,
    ) -> String {
        let indent = "  ".repeat(depth);
        let use_colors = config.use_colors();

        let mut lines = Vec::new();

        for (key, value) in obj {
            let sigil = Self::infer_sigil(key);
            let sigil_str = sigil.format(use_colors);

            let key_str = if use_colors {
                key.bold().to_string()
            } else {
                key.clone()
            };

            match value {
                serde_json::Value::Object(nested) if !nested.is_empty() => {
                    lines.push(format!("{}{} {}", indent, sigil_str, key_str));
                    let nested_str = Self::format_object(nested, config, depth + 1);
                    lines.push(nested_str);
                }
                serde_json::Value::Array(arr) if !arr.is_empty() => {
                    lines.push(format!(
                        "{}{} {} [{} items]",
                        indent,
                        sigil_str,
                        key_str,
                        arr.len()
                    ));
                    for item in arr {
                        let item_str = Self::format_value(item, config, depth + 1);
                        lines.push(format!(
                            "{}  {} {}",
                            indent,
                            Sigil::Continuation.format(use_colors),
                            item_str.trim()
                        ));
                    }
                }
                _ => {
                    let value_str = Self::format_simple_value(value, use_colors);
                    lines.push(format!(
                        "{}{} {} {} {}",
                        indent,
                        sigil_str,
                        key_str,
                        Sigil::Flow.format(use_colors),
                        value_str
                    ));
                }
            }
        }

        lines.join("\n")
    }

    /// Format a simple (non-nested) JSON value
    fn format_simple_value(value: &serde_json::Value, use_colors: bool) -> String {
        match value {
            serde_json::Value::Null => {
                if use_colors {
                    "-".dimmed().to_string()
                } else {
                    "-".to_string()
                }
            }
            serde_json::Value::Bool(b) => {
                if use_colors {
                    if *b {
                        "true".green().to_string()
                    } else {
                        "false".red().to_string()
                    }
                } else {
                    b.to_string()
                }
            }
            serde_json::Value::Number(n) => {
                if use_colors {
                    n.to_string().cyan().to_string()
                } else {
                    n.to_string()
                }
            }
            serde_json::Value::String(s) => {
                if use_colors {
                    s.yellow().to_string()
                } else {
                    s.clone()
                }
            }
            serde_json::Value::Array(arr) => format!("[{} items]", arr.len()),
            serde_json::Value::Object(obj) => format!("{{{} fields}}", obj.len()),
        }
    }

    /// Infer the appropriate sigil based on key name
    fn infer_sigil(key: &str) -> Sigil {
        let key_lower = key.to_lowercase();

        if key_lower.contains("module")
            || key_lower.contains("namespace")
            || key_lower.contains("package")
        {
            Sigil::Module
        } else if key_lower.contains("function")
            || key_lower.contains("method")
            || key_lower.contains("fn")
        {
            Sigil::Function
        } else if key_lower.contains("type")
            || key_lower.contains("class")
            || key_lower.contains("struct")
            || key_lower.contains("interface")
        {
            Sigil::Type
        } else if key_lower.contains("const") || key_lower == "name" || key_lower == "id" {
            Sigil::Constant
        } else if key_lower.contains("var")
            || key_lower.contains("value")
            || key_lower.contains("data")
        {
            Sigil::Variable
        } else if key_lower.contains("import")
            || key_lower.contains("use")
            || key_lower.contains("ref")
        {
            Sigil::Reference
        } else if key_lower.contains("export") || key_lower.contains("public") {
            Sigil::Export
        } else if key_lower.contains("dep") || key_lower.contains("require") {
            Sigil::Dependency
        } else {
            Sigil::Variable // Default
        }
    }

    /// Create a MU section header
    pub fn section(name: &str, use_colors: bool) -> String {
        let sigil = Sigil::Section.format(use_colors);
        if use_colors {
            format!("{} {}", sigil, name.bold())
        } else {
            format!("{} {}", sigil, name)
        }
    }

    /// Create a MU module entry
    pub fn module(name: &str, use_colors: bool) -> String {
        let sigil = Sigil::Module.format(use_colors);
        if use_colors {
            format!("{} {}", sigil, name.bright_blue())
        } else {
            format!("{} {}", sigil, name)
        }
    }

    /// Create a MU function entry
    pub fn function(name: &str, signature: Option<&str>, use_colors: bool) -> String {
        let sigil = Sigil::Function.format(use_colors);
        let name_str = if use_colors {
            name.bright_green().to_string()
        } else {
            name.to_string()
        };

        if let Some(sig) = signature {
            let sig_str = if use_colors {
                sig.dimmed().to_string()
            } else {
                sig.to_string()
            };
            format!("{} {}{}", sigil, name_str, sig_str)
        } else {
            format!("{} {}", sigil, name_str)
        }
    }

    /// Create a MU type entry
    pub fn type_def(name: &str, kind: Option<&str>, use_colors: bool) -> String {
        let sigil = Sigil::Type.format(use_colors);
        let name_str = if use_colors {
            name.bright_yellow().to_string()
        } else {
            name.to_string()
        };

        if let Some(k) = kind {
            let kind_str = if use_colors {
                format!("[{}]", k).dimmed().to_string()
            } else {
                format!("[{}]", k)
            };
            format!("{} {} {}", sigil, name_str, kind_str)
        } else {
            format!("{} {}", sigil, name_str)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Serialize;

    #[derive(Serialize)]
    struct TestModule {
        module_name: String,
        functions: Vec<String>,
        types: Vec<String>,
    }

    #[test]
    fn test_format_object() {
        let data = TestModule {
            module_name: "test".to_string(),
            functions: vec!["foo".to_string(), "bar".to_string()],
            types: vec!["MyStruct".to_string()],
        };
        let config = OutputConfig::new(super::super::OutputFormat::Mu).without_colors();
        let output = MuOutput::format(&data, &config);

        assert!(output.contains("module_name"));
        assert!(output.contains("functions"));
        assert!(output.contains("test"));
    }

    #[test]
    fn test_sigil_chars() {
        assert_eq!(Sigil::Module.char(), "!");
        assert_eq!(Sigil::Function.char(), "$");
        assert_eq!(Sigil::Type.char(), "@");
        assert_eq!(Sigil::Section.char(), "::");
        assert_eq!(Sigil::Flow.char(), "->");
    }

    #[test]
    fn test_infer_sigil() {
        assert_eq!(MuOutput::infer_sigil("module_name"), Sigil::Module);
        assert_eq!(MuOutput::infer_sigil("function_list"), Sigil::Function);
        assert_eq!(MuOutput::infer_sigil("type_info"), Sigil::Type);
        assert_eq!(MuOutput::infer_sigil("imports"), Sigil::Reference);
    }

    #[test]
    fn test_section_helper() {
        let section = MuOutput::section("Overview", false);
        assert_eq!(section, ":: Overview");
    }

    #[test]
    fn test_function_helper() {
        let func = MuOutput::function("calculate", Some("(x: i32) -> i32"), false);
        assert_eq!(func, "$ calculate(x: i32) -> i32");
    }

    #[test]
    fn test_type_helper() {
        let type_def = MuOutput::type_def("MyStruct", Some("struct"), false);
        assert_eq!(type_def, "@ MyStruct [struct]");
    }
}
