//! Transformation rules for code reduction.
//!
//! Mirrors the Python TransformationRules dataclass.

use serde::{Deserialize, Serialize};

/// Rules for transforming/reducing code.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct TransformationRules {
    /// Methods to strip by name pattern.
    pub strip_methods: Vec<String>,
    /// Import modules to strip.
    pub strip_imports: Vec<String>,
    /// Decorator patterns to strip.
    pub strip_decorators: Vec<String>,
    /// Parameter names to filter out.
    pub filter_parameters: Vec<String>,
    /// Minimum complexity to include function body.
    pub min_body_complexity: u32,
    /// Maximum body lines to include inline.
    pub max_body_lines: u32,
}

impl TransformationRules {
    /// Create default transformation rules.
    pub fn new() -> Self {
        Self {
            strip_methods: vec![
                "__repr__".to_string(),
                "__str__".to_string(),
                "__hash__".to_string(),
                "__eq__".to_string(),
                "__ne__".to_string(),
                "__lt__".to_string(),
                "__le__".to_string(),
                "__gt__".to_string(),
                "__ge__".to_string(),
            ],
            strip_imports: vec![
                "typing".to_string(),
                "__future__".to_string(),
            ],
            strip_decorators: vec![],
            filter_parameters: vec![
                "self".to_string(),
                "cls".to_string(),
            ],
            min_body_complexity: 3,
            max_body_lines: 50,
        }
    }

    /// Check if a method should be stripped.
    pub fn should_strip_method(&self, name: &str) -> bool {
        self.strip_methods.iter().any(|pattern| {
            if pattern.contains('*') {
                let pattern = pattern.replace('*', "");
                name.contains(&pattern)
            } else {
                name == pattern
            }
        })
    }

    /// Check if an import should be stripped.
    pub fn should_strip_import(&self, module: &str) -> bool {
        self.strip_imports.iter().any(|pattern| {
            module == pattern || module.starts_with(&format!("{}.", pattern))
        })
    }

    /// Filter out common parameters (self, cls).
    pub fn filter_parameter(&self, name: &str) -> bool {
        !self.filter_parameters.contains(&name.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_should_strip_method() {
        let rules = TransformationRules::new();
        assert!(rules.should_strip_method("__repr__"));
        assert!(rules.should_strip_method("__str__"));
        assert!(!rules.should_strip_method("process"));
    }

    #[test]
    fn test_should_strip_import() {
        let rules = TransformationRules::new();
        assert!(rules.should_strip_import("typing"));
        assert!(rules.should_strip_import("typing.Optional"));
        assert!(!rules.should_strip_import("os"));
    }

    #[test]
    fn test_filter_parameter() {
        let rules = TransformationRules::new();
        assert!(!rules.filter_parameter("self"));
        assert!(!rules.filter_parameter("cls"));
        assert!(rules.filter_parameter("name"));
    }
}
