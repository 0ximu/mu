//! CSV output formatting for data export.
//!
//! Provides CSV formatting with:
//! - Proper escaping of special characters
//! - Support for arrays of objects
//! - Configurable column selection

use super::{Column, OutputConfig};
use serde::Serialize;

/// CSV output formatter
pub struct CsvOutput;

impl CsvOutput {
    /// Format data as CSV string
    ///
    /// For single objects, outputs a two-row CSV (header + values).
    /// For arrays, outputs headers followed by one row per item.
    pub fn format<T: Serialize>(data: &T, _config: &OutputConfig) -> String {
        if let Ok(json) = serde_json::to_value(data) {
            match json {
                serde_json::Value::Array(arr) => Self::format_array_value(&arr),
                serde_json::Value::Object(obj) => Self::format_object_value(&obj),
                _ => Self::escape_value(&json.to_string()),
            }
        } else {
            String::new()
        }
    }

    /// Format an array of items as CSV with specified columns
    pub fn format_with_columns<T: Serialize>(
        data: &[T],
        columns: &[Column],
        _config: &OutputConfig,
    ) -> String {
        if data.is_empty() {
            return columns
                .iter()
                .map(|c| &c.name)
                .cloned()
                .collect::<Vec<_>>()
                .join(",");
        }

        let mut output = String::new();

        // Header row
        let headers: Vec<&str> = columns.iter().map(|c| c.name.as_str()).collect();
        output.push_str(&headers.join(","));
        output.push('\n');

        // Data rows
        for item in data {
            if let Ok(json) = serde_json::to_value(item) {
                let row: Vec<String> = columns
                    .iter()
                    .map(|col| {
                        json.get(&col.key)
                            .map(Self::value_to_csv)
                            .unwrap_or_default()
                    })
                    .collect();
                output.push_str(&row.join(","));
                output.push('\n');
            }
        }

        output.trim_end().to_string()
    }

    /// Format a JSON array as CSV
    fn format_array_value(arr: &[serde_json::Value]) -> String {
        if arr.is_empty() {
            return String::new();
        }

        // Get headers from first object
        let headers: Vec<String> = if let Some(serde_json::Value::Object(first)) = arr.first() {
            first.keys().cloned().collect()
        } else {
            return arr
                .iter()
                .map(Self::value_to_csv)
                .collect::<Vec<_>>()
                .join("\n");
        };

        let mut output = headers.join(",");
        output.push('\n');

        // Data rows
        for item in arr {
            if let serde_json::Value::Object(obj) = item {
                let row: Vec<String> = headers
                    .iter()
                    .map(|h| obj.get(h).map(Self::value_to_csv).unwrap_or_default())
                    .collect();
                output.push_str(&row.join(","));
                output.push('\n');
            }
        }

        output.trim_end().to_string()
    }

    /// Format a single JSON object as CSV
    fn format_object_value(obj: &serde_json::Map<String, serde_json::Value>) -> String {
        let headers: Vec<&str> = obj.keys().map(|s| s.as_str()).collect();
        let values: Vec<String> = obj.values().map(Self::value_to_csv).collect();

        format!("{}\n{}", headers.join(","), values.join(","))
    }

    /// Convert a JSON value to a CSV cell
    fn value_to_csv(value: &serde_json::Value) -> String {
        match value {
            serde_json::Value::Null => String::new(),
            serde_json::Value::Bool(b) => b.to_string(),
            serde_json::Value::Number(n) => n.to_string(),
            serde_json::Value::String(s) => Self::escape_value(s),
            serde_json::Value::Array(arr) => Self::escape_value(&format!("[{} items]", arr.len())),
            serde_json::Value::Object(obj) => {
                Self::escape_value(&format!("{{{} fields}}", obj.len()))
            }
        }
    }

    /// Escape a string value for CSV
    ///
    /// Wraps in quotes if the value contains comma, newline, or quote.
    /// Doubles any existing quotes.
    fn escape_value(s: &str) -> String {
        if s.contains(',') || s.contains('\n') || s.contains('\r') || s.contains('"') {
            format!("\"{}\"", s.replace('"', "\"\""))
        } else {
            s.to_string()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Serialize;

    #[derive(Serialize)]
    struct TestItem {
        name: String,
        value: i32,
    }

    #[test]
    fn test_format_array() {
        let data = vec![
            TestItem {
                name: "foo".to_string(),
                value: 42,
            },
            TestItem {
                name: "bar".to_string(),
                value: 100,
            },
        ];
        let config = OutputConfig::new(super::super::OutputFormat::Csv);
        let output = CsvOutput::format(&data, &config);

        let lines: Vec<_> = output.lines().collect();
        assert_eq!(lines.len(), 3); // header + 2 data rows
        assert!(lines[0].contains("name"));
        assert!(lines[0].contains("value"));
        assert!(lines[1].contains("foo"));
        assert!(lines[2].contains("bar"));
    }

    #[test]
    fn test_format_single_object() {
        let data = TestItem {
            name: "test".to_string(),
            value: 42,
        };
        let config = OutputConfig::new(super::super::OutputFormat::Csv);
        let output = CsvOutput::format(&data, &config);

        let lines: Vec<_> = output.lines().collect();
        assert_eq!(lines.len(), 2); // header + 1 data row
    }

    #[test]
    fn test_escape_special_chars() {
        assert_eq!(CsvOutput::escape_value("hello"), "hello");
        assert_eq!(CsvOutput::escape_value("hello,world"), "\"hello,world\"");
        assert_eq!(CsvOutput::escape_value("hello\nworld"), "\"hello\nworld\"");
        assert_eq!(CsvOutput::escape_value("say \"hi\""), "\"say \"\"hi\"\"\"");
    }

    #[test]
    fn test_format_with_columns() {
        let data = vec![
            TestItem {
                name: "foo".to_string(),
                value: 42,
            },
            TestItem {
                name: "bar".to_string(),
                value: 100,
            },
        ];
        let columns = vec![
            Column::new("Item Name", "name"),
            Column::new("Item Value", "value"),
        ];
        let config = OutputConfig::new(super::super::OutputFormat::Csv);
        let output = CsvOutput::format_with_columns(&data, &columns, &config);

        let lines: Vec<_> = output.lines().collect();
        assert_eq!(lines[0], "Item Name,Item Value");
        assert!(lines[1].contains("foo"));
    }

    #[test]
    fn test_empty_array() {
        let data: Vec<TestItem> = vec![];
        let columns = vec![Column::new("Name", "name")];
        let config = OutputConfig::new(super::super::OutputFormat::Csv);
        let output = CsvOutput::format_with_columns(&data, &columns, &config);

        assert_eq!(output, "Name");
    }
}
