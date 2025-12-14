//! Table output formatting using the `tabled` crate
//!
//! Provides sophisticated table formatting with:
//! - Column width management and truncation
//! - Terminal width awareness
//! - Alignment support
//! - Theme customization

use super::{truncate, Alignment, Column, OutputConfig};
use serde::Serialize;
use tabled::{
    builder::Builder,
    settings::{object::Columns, style::Style, Alignment as TabledAlignment, Modify, Width},
};

/// Table output formatter
pub struct TableOutput;

impl TableOutput {
    /// Format data as a table string (simple fallback for single items)
    pub fn format<T: Serialize>(data: &T, config: &OutputConfig) -> String {
        // For single items, format as key-value pairs
        if let Ok(serde_json::Value::Object(map)) = serde_json::to_value(data) {
            // Collect into owned strings for the pairs
            let owned_pairs: Vec<(String, String)> = map
                .iter()
                .map(|(k, v)| (k.clone(), Self::value_to_string(v)))
                .collect();

            let pairs_ref: Vec<(&str, String)> = owned_pairs
                .iter()
                .map(|(k, v)| (k.as_str(), v.clone()))
                .collect();

            return Self::format_key_value(&pairs_ref, config);
        }
        // Fallback to JSON
        serde_json::to_string_pretty(data).unwrap_or_default()
    }

    /// Format data as a table with the given columns
    pub fn format_with_columns<T: Serialize>(
        data: &[T],
        columns: &[Column],
        config: &OutputConfig,
    ) -> String {
        if data.is_empty() {
            return "(no results)".to_string();
        }

        let mut builder = Builder::default();

        // Add header row
        let headers: Vec<&str> = columns.iter().map(|c| c.name.as_str()).collect();
        builder.push_record(headers);

        // Serialize each item and extract values by key
        for item in data {
            let json = serde_json::to_value(item).unwrap_or_default();
            let row: Vec<String> = columns
                .iter()
                .map(|col| {
                    let value = json.get(&col.key).cloned().unwrap_or_default();
                    Self::format_value(&value, col, config)
                })
                .collect();
            builder.push_record(row);
        }

        let mut table = builder.build();

        // Apply style
        if config.compact {
            table.with(Style::blank());
        } else {
            table.with(Style::rounded());
        }

        // Apply column widths and alignments
        let term_width = config.effective_width();
        let col_count = columns.len();
        let available_width = if col_count > 0 {
            (term_width.saturating_sub(col_count * 3)) / col_count
        } else {
            term_width
        };

        for (i, col) in columns.iter().enumerate() {
            let max_width = col.max_width.unwrap_or(available_width);

            if config.should_truncate() && max_width > 0 {
                table.with(Modify::new(Columns::single(i)).with(Width::truncate(max_width)));
            }

            let alignment = match col.align {
                Alignment::Left => TabledAlignment::left(),
                Alignment::Center => TabledAlignment::center(),
                Alignment::Right => TabledAlignment::right(),
            };
            table.with(Modify::new(Columns::single(i)).with(alignment));
        }

        // Limit total table width
        if config.should_truncate() {
            table.with(Width::wrap(term_width));
        }

        table.to_string()
    }

    /// Format a single JSON value for display
    fn format_value(value: &serde_json::Value, col: &Column, config: &OutputConfig) -> String {
        let s = Self::value_to_string(value);

        if config.should_truncate() {
            if let Some(max_width) = col.max_width {
                return truncate(&s, max_width);
            }
        }
        s
    }

    /// Convert a JSON value to a display string
    fn value_to_string(value: &serde_json::Value) -> String {
        match value {
            serde_json::Value::Null => "-".to_string(),
            serde_json::Value::Bool(b) => b.to_string(),
            serde_json::Value::Number(n) => n.to_string(),
            serde_json::Value::String(s) => s.clone(),
            serde_json::Value::Array(arr) => format!("[{} items]", arr.len()),
            serde_json::Value::Object(obj) => format!("{{{} fields}}", obj.len()),
        }
    }

    /// Format a simple key-value table
    pub fn format_key_value(pairs: &[(&str, String)], config: &OutputConfig) -> String {
        let mut builder = Builder::default();

        for (key, value) in pairs {
            builder.push_record([*key, value.as_str()]);
        }

        let mut table = builder.build();

        if config.compact {
            table.with(Style::blank());
        } else {
            table.with(Style::rounded());
        }

        table.with(Modify::new(Columns::first()).with(TabledAlignment::right()));

        if config.should_truncate() {
            let term_width = config.effective_width();
            table.with(Width::wrap(term_width));
        }

        table.to_string()
    }

    /// Create a simple table from rows of strings
    pub fn from_rows(headers: &[&str], rows: &[Vec<String>], config: &OutputConfig) -> String {
        if rows.is_empty() {
            return "(no results)".to_string();
        }

        let mut builder = Builder::default();
        builder.push_record(headers.iter().copied());

        for row in rows {
            builder.push_record(row.iter().map(|s| s.as_str()));
        }

        let mut table = builder.build();

        if config.compact {
            table.with(Style::blank());
        } else {
            table.with(Style::rounded());
        }

        if config.should_truncate() {
            let term_width = config.effective_width();
            table.with(Width::wrap(term_width));
        }

        table.to_string()
    }
}

/// Helper trait for types that can be displayed as a table with columns
pub trait AsTable: Serialize {
    /// Get the column definitions for this type
    fn columns() -> Vec<Column>;
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
            Column::new("Name", "name"),
            Column::new("Value", "value").with_alignment(Alignment::Right),
        ];

        let config = OutputConfig::new(super::super::OutputFormat::Table).without_truncation();
        let output = TableOutput::format_with_columns(&data, &columns, &config);

        assert!(output.contains("Name"));
        assert!(output.contains("Value"));
        assert!(output.contains("foo"));
        assert!(output.contains("42"));
    }

    #[test]
    fn test_empty_data() {
        let data: Vec<TestItem> = vec![];
        let columns = vec![Column::new("Name", "name")];
        let config = OutputConfig::new(super::super::OutputFormat::Table);

        let output = TableOutput::format_with_columns(&data, &columns, &config);
        assert_eq!(output, "(no results)");
    }

    #[test]
    fn test_key_value_table() {
        let pairs = vec![("Name", "Test".to_string()), ("Status", "OK".to_string())];

        let config = OutputConfig::new(super::super::OutputFormat::Table);
        let output = TableOutput::format_key_value(&pairs, &config);

        assert!(output.contains("Name"));
        assert!(output.contains("Test"));
    }

    #[test]
    fn test_from_rows() {
        let headers = vec!["Col1", "Col2"];
        let rows = vec![
            vec!["a".to_string(), "b".to_string()],
            vec!["c".to_string(), "d".to_string()],
        ];

        let config = OutputConfig::new(super::super::OutputFormat::Table);
        let output = TableOutput::from_rows(&headers, &rows, &config);

        assert!(output.contains("Col1"));
        assert!(output.contains("Col2"));
        assert!(output.contains("a"));
        assert!(output.contains("d"));
    }
}
