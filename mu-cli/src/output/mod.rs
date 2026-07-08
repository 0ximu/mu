//! Output formatting module for MU CLI
//!
//! Provides unified output formatting across all commands with support for
//! table (human-readable) and json (machine-readable) formats.

use clap::ValueEnum;
use serde::Serialize;
use std::str::FromStr;

mod json;

pub use self::json::JsonOutput;

/// Output format for CLI results
#[derive(Debug, Clone, Copy, Default, ValueEnum, PartialEq, Eq)]
pub enum OutputFormat {
    /// Human-readable table format (default)
    #[default]
    Table,
    /// JSON format for machine consumption
    Json,
}

impl FromStr for OutputFormat {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "table" => Ok(OutputFormat::Table),
            "json" => Ok(OutputFormat::Json),
            _ => Err(format!("Unknown output format: '{}'", s)),
        }
    }
}

/// Configuration for output rendering
#[derive(Debug, Clone)]
pub struct OutputConfig {
    pub format: OutputFormat,
    pub compact: bool,
}

impl OutputConfig {
    /// Create an OutputConfig with automatic TTY detection
    pub fn auto_detect(format: OutputFormat) -> Self {
        Self {
            format,
            compact: false,
        }
    }
}

impl Default for OutputConfig {
    fn default() -> Self {
        Self::auto_detect(OutputFormat::Table)
    }
}

/// Trait for types that can be formatted as output
pub trait Outputter: Serialize + Sized {
    /// Render as table format
    fn to_table(&self, config: &OutputConfig) -> String;

    /// Render as JSON format
    fn to_json(&self, config: &OutputConfig) -> String {
        JsonOutput::format(self, config)
    }

    /// Render using the format specified in config
    fn render(&self, config: &OutputConfig) -> String {
        match config.format {
            OutputFormat::Table => self.to_table(config),
            OutputFormat::Json => self.to_json(config),
        }
    }

    /// Render and print to stdout
    fn output(&self, config: &OutputConfig) {
        println!("{}", self.render(config));
    }
}

/// Result wrapper for formatted output with automatic format selection
pub struct Output<T> {
    data: T,
    config: OutputConfig,
}

impl<T: Outputter> Output<T> {
    /// Create a new output wrapper with specified format
    pub fn new(data: T, format: OutputFormat) -> Self {
        Self {
            data,
            config: OutputConfig::auto_detect(format),
        }
    }

    /// Render the output to stdout
    pub fn render(&self) -> anyhow::Result<()> {
        self.data.output(&self.config);
        Ok(())
    }
}

/// Trait for types that can be displayed as a table
pub trait TableDisplay: Serialize {
    fn to_table(&self) -> String;
}

/// Truncate a string to at most `max` bytes, respecting UTF-8 char boundaries,
/// appending "..." when truncation happens.
///
/// Byte slicing (`&s[..max]`) panics when `max` lands inside a multibyte
/// character; this backs off to the previous char boundary instead.
pub fn truncate_str(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        let mut end = max;
        while !s.is_char_boundary(end) {
            end -= 1;
        }
        format!("{}...", &s[..end])
    }
}

/// Blanket implementation of Outputter for TableDisplay types
impl<T: TableDisplay + Serialize> Outputter for T {
    fn to_table(&self, _config: &OutputConfig) -> String {
        TableDisplay::to_table(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_output_config_auto_detect() {
        let config = OutputConfig::auto_detect(OutputFormat::Table);
        assert_eq!(config.format, OutputFormat::Table);
    }

    #[test]
    fn test_truncate_str_short_string_unchanged() {
        assert_eq!(truncate_str("hello", 10), "hello");
        assert_eq!(truncate_str("hello", 5), "hello");
    }

    #[test]
    fn test_truncate_str_ascii_truncation() {
        assert_eq!(truncate_str("hello world", 5), "hello...");
    }

    #[test]
    fn test_truncate_str_multibyte_boundary_no_panic() {
        // 199 ASCII chars then a 3-byte arrow: byte 200 lands mid-character.
        // The old byte-slicing version panicked here.
        let s = format!("{}→", "a".repeat(199));
        assert_eq!(s.len(), 202);
        let out = truncate_str(&s, 200);
        assert_eq!(out, format!("{}...", "a".repeat(199)));
    }

    #[test]
    fn test_truncate_str_multibyte_content() {
        // Truncating inside a run of multibyte chars backs off cleanly.
        let s = "→→→→"; // 12 bytes
        let out = truncate_str(s, 7);
        assert_eq!(out, "→→...");
    }
}
