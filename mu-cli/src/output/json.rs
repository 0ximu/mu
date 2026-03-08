//! JSON output formatting for machine-readable output.

use super::OutputConfig;
use serde::Serialize;

/// JSON output formatter
pub struct JsonOutput;

impl JsonOutput {
    /// Format data as JSON string
    pub fn format<T: Serialize + ?Sized>(data: &T, config: &OutputConfig) -> String {
        if config.compact {
            serde_json::to_string(data).unwrap_or_else(|e| format!("{{\"error\": \"{}\"}}", e))
        } else {
            serde_json::to_string_pretty(data)
                .unwrap_or_else(|e| format!("{{\n  \"error\": \"{}\"\n}}", e))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Serialize;

    #[derive(Serialize)]
    struct TestData {
        name: String,
        value: i32,
    }

    #[test]
    fn test_format_pretty() {
        let data = TestData {
            name: "test".to_string(),
            value: 42,
        };
        let config = OutputConfig::auto_detect(super::super::OutputFormat::Json);
        let output = JsonOutput::format(&data, &config);

        assert!(output.contains("\"name\""));
        assert!(output.contains("\"test\""));
        assert!(output.contains("42"));
        assert!(output.contains("\n"));
    }

    #[test]
    fn test_format_compact() {
        let data = TestData {
            name: "test".to_string(),
            value: 42,
        };
        let mut config = OutputConfig::auto_detect(super::super::OutputFormat::Json);
        config.compact = true;
        let output = JsonOutput::format(&data, &config);

        assert!(output.contains("\"name\""));
        assert!(!output.contains("\n"));
    }
}
