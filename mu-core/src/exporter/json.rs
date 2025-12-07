//! JSON format exporter.

use crate::types::{ModuleDef, ExportConfig};

/// Export modules to JSON format.
pub fn export(modules: &[ModuleDef], config: &ExportConfig) -> Result<String, serde_json::Error> {
    if config.pretty_print {
        serde_json::to_string_pretty(modules)
    } else {
        serde_json::to_string(modules)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_export_json() {
        let modules = vec![ModuleDef {
            name: "test".to_string(),
            path: "/test.py".to_string(),
            language: "python".to_string(),
            ..Default::default()
        }];

        let config = ExportConfig::default();
        let output = export(&modules, &config).unwrap();
        assert!(output.contains("\"name\":\"test\""));
    }

    #[test]
    fn test_export_json_pretty() {
        let modules = vec![ModuleDef {
            name: "test".to_string(),
            ..Default::default()
        }];

        let config = ExportConfig { pretty_print: true, ..Default::default() };
        let output = export(&modules, &config).unwrap();
        assert!(output.contains('\n'));
    }
}
