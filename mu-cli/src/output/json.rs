//! JSON output formatting for machine-readable output.
//!
//! Provides JSON formatting with:
//! - Pretty-printing (default) or compact mode
//! - Consistent serialization of all types

use super::OutputConfig;
use serde::Serialize;

/// JSON output formatter
pub struct JsonOutput;

impl JsonOutput {
    /// Format data as JSON string
    ///
    /// Uses pretty-printing by default. When `config.compact` is true,
    /// outputs minified JSON on a single line.
    pub fn format<T: Serialize + ?Sized>(data: &T, config: &OutputConfig) -> String {
        if config.compact {
            serde_json::to_string(data).unwrap_or_else(|e| format!("{{\"error\": \"{}\"}}", e))
        } else {
            serde_json::to_string_pretty(data)
                .unwrap_or_else(|e| format!("{{\n  \"error\": \"{}\"\n}}", e))
        }
    }

    /// Format multiple items as a JSON array
    pub fn format_array<T: Serialize>(data: &[T], config: &OutputConfig) -> String {
        Self::format(&data, config)
    }

    /// Format as JSON Lines (JSONL) - one JSON object per line
    ///
    /// Useful for streaming and log processing.
    pub fn format_lines<T: Serialize>(data: &[T], _config: &OutputConfig) -> String {
        data.iter()
            .filter_map(|item| serde_json::to_string(item).ok())
            .collect::<Vec<_>>()
            .join("\n")
    }

    /// Wrap data in a standard response envelope
    pub fn format_envelope<T: Serialize>(data: &T, success: bool, config: &OutputConfig) -> String {
        #[derive(Serialize)]
        struct Envelope<'a, T: Serialize> {
            success: bool,
            data: &'a T,
        }

        Self::format(&Envelope { success, data }, config)
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
        let config = OutputConfig::new(super::super::OutputFormat::Json);
        let output = JsonOutput::format(&data, &config);

        assert!(output.contains("\"name\""));
        assert!(output.contains("\"test\""));
        assert!(output.contains("42"));
        assert!(output.contains("\n")); // Pretty print has newlines
    }

    #[test]
    fn test_format_compact() {
        let data = TestData {
            name: "test".to_string(),
            value: 42,
        };
        let config = OutputConfig::new(super::super::OutputFormat::Json).compact();
        let output = JsonOutput::format(&data, &config);

        assert!(output.contains("\"name\""));
        assert!(!output.contains("\n")); // Compact has no newlines
    }

    #[test]
    fn test_format_array() {
        let data = vec![
            TestData {
                name: "a".to_string(),
                value: 1,
            },
            TestData {
                name: "b".to_string(),
                value: 2,
            },
        ];
        let config = OutputConfig::new(super::super::OutputFormat::Json);
        let output = JsonOutput::format_array(&data, &config);

        assert!(output.starts_with('['));
        assert!(output.ends_with(']'));
    }

    #[test]
    fn test_format_lines() {
        let data = vec![
            TestData {
                name: "a".to_string(),
                value: 1,
            },
            TestData {
                name: "b".to_string(),
                value: 2,
            },
        ];
        let config = OutputConfig::new(super::super::OutputFormat::Json);
        let output = JsonOutput::format_lines(&data, &config);

        let lines: Vec<_> = output.lines().collect();
        assert_eq!(lines.len(), 2);
        assert!(lines[0].starts_with('{'));
        assert!(lines[1].starts_with('{'));
    }

    #[test]
    fn test_format_envelope() {
        let data = TestData {
            name: "test".to_string(),
            value: 42,
        };
        let config = OutputConfig::new(super::super::OutputFormat::Json);
        let output = JsonOutput::format_envelope(&data, true, &config);

        assert!(output.contains("\"success\": true"));
        assert!(output.contains("\"data\""));
    }
}
