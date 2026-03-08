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
}
