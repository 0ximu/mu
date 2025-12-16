//! Output formatting module for MU CLI
//!
//! Provides unified output formatting across all commands with support for
//! multiple formats: table (human-readable), json (machine-readable), csv,
//! mu (sigil format), and tree (hierarchical display).
//!
//! Automatically detects TTY context to adjust colors and truncation behavior.

// Allow dead code in this module - it's an output formatting framework with
// public types and methods intended for use by various commands
#![allow(dead_code)]

use clap::ValueEnum;
use serde::Serialize;
use std::io::IsTerminal;
use std::str::FromStr;

mod csv;
mod json;
mod mu;
mod table;
mod tree;

// Re-exports for public API (currently not all used, but part of the framework)
#[allow(unused_imports)]
pub use self::csv::CsvOutput;
pub use self::json::JsonOutput;
#[allow(unused_imports)]
pub use self::mu::{MuOutput, Sigil};
#[allow(unused_imports)]
pub use self::table::{AsTable, TableOutput};
#[allow(unused_imports)]
pub use self::tree::{NodeKind, TreeNode, TreeOutput};

/// Output format for CLI results
#[derive(Debug, Clone, Copy, Default, ValueEnum, PartialEq, Eq)]
pub enum OutputFormat {
    /// Human-readable table format (default)
    #[default]
    Table,
    /// JSON format for machine consumption
    Json,
    /// CSV format for spreadsheet/data processing
    Csv,
    /// MU sigil format (! modules, $ functions, etc.)
    Mu,
    /// Tree format for hierarchical data
    Tree,
}

impl FromStr for OutputFormat {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "table" => Ok(OutputFormat::Table),
            "json" => Ok(OutputFormat::Json),
            "csv" => Ok(OutputFormat::Csv),
            "mu" => Ok(OutputFormat::Mu),
            "tree" => Ok(OutputFormat::Tree),
            _ => Err(format!("Unknown output format: '{}'", s)),
        }
    }
}

/// Configuration for output rendering
#[derive(Debug, Clone)]
pub struct OutputConfig {
    /// The output format to use
    pub format: OutputFormat,
    /// Disable colored output
    pub no_color: bool,
    /// Disable truncation of long values
    pub no_truncate: bool,
    /// Override terminal width (None = auto-detect)
    pub width: Option<usize>,
    /// Compact mode (less whitespace)
    pub compact: bool,
}

impl OutputConfig {
    /// Create a new OutputConfig with the specified format
    pub fn new(format: OutputFormat) -> Self {
        Self {
            format,
            no_color: false,
            no_truncate: false,
            width: None,
            compact: false,
        }
    }

    /// Create an OutputConfig with automatic TTY detection
    ///
    /// When output is not a TTY (piped or redirected):
    /// - Colors are disabled
    /// - Truncation is disabled
    pub fn auto_detect(format: OutputFormat) -> Self {
        Self::auto_detect_with_color_override(format, None)
    }

    /// Create an OutputConfig with automatic TTY detection and optional color override.
    ///
    /// When output is not a TTY (piped or redirected):
    /// - Colors are disabled (unless `color_override` is `Some(true)`)
    /// - Truncation is disabled
    ///
    /// # Arguments
    ///
    /// * `format` - The output format to use
    /// * `color_override` - If `Some(true)`, force colors on. If `Some(false)`, force colors off.
    ///   If `None`, use auto-detection based on TTY.
    pub fn auto_detect_with_color_override(
        format: OutputFormat,
        color_override: Option<bool>,
    ) -> Self {
        let is_tty = std::io::stdout().is_terminal();
        let use_color = color_override.unwrap_or(is_tty);
        Self {
            format,
            no_color: !use_color,
            no_truncate: !is_tty,
            width: None,
            compact: false,
        }
    }

    /// Get the effective terminal width
    pub fn effective_width(&self) -> usize {
        self.width.unwrap_or_else(|| {
            terminal_size::terminal_size()
                .map(|(w, _)| w.0 as usize)
                .unwrap_or(80)
        })
    }

    /// Check if colors should be used
    pub fn use_colors(&self) -> bool {
        !self.no_color
    }

    /// Check if truncation should be applied
    pub fn should_truncate(&self) -> bool {
        !self.no_truncate
    }

    /// Builder: disable colors
    pub fn without_colors(mut self) -> Self {
        self.no_color = true;
        self
    }

    /// Builder: disable truncation
    pub fn without_truncation(mut self) -> Self {
        self.no_truncate = true;
        self
    }

    /// Builder: set width
    pub fn with_width(mut self, width: usize) -> Self {
        self.width = Some(width);
        self
    }

    /// Builder: enable compact mode
    pub fn compact(mut self) -> Self {
        self.compact = true;
        self
    }
}

impl Default for OutputConfig {
    fn default() -> Self {
        Self::auto_detect(OutputFormat::Table)
    }
}

/// Column definition for table output
#[derive(Debug, Clone)]
pub struct Column {
    /// Display name for the column header
    pub name: String,
    /// Key used to extract data (for maps/structs)
    pub key: String,
    /// Maximum width for this column (None = no limit)
    pub max_width: Option<usize>,
    /// Alignment for the column content
    pub align: Alignment,
}

impl Column {
    /// Create a new column with default settings
    pub fn new(name: impl Into<String>, key: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            key: key.into(),
            max_width: None,
            align: Alignment::Left,
        }
    }

    /// Builder: set maximum width
    pub fn with_max_width(mut self, width: usize) -> Self {
        self.max_width = Some(width);
        self
    }

    /// Builder: set alignment
    pub fn with_alignment(mut self, align: Alignment) -> Self {
        self.align = align;
        self
    }
}

/// Text alignment for columns
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum Alignment {
    #[default]
    Left,
    Center,
    Right,
}

/// Trait for types that can be formatted as output
///
/// Types implementing this trait can be rendered in any supported format.
pub trait Outputter: Serialize + Sized {
    /// Render as table format
    fn to_table(&self, config: &OutputConfig) -> String;

    /// Render as JSON format
    fn to_json(&self, config: &OutputConfig) -> String {
        JsonOutput::format(self, config)
    }

    /// Render as CSV format
    fn to_csv(&self, config: &OutputConfig) -> String;

    /// Render as MU sigil format
    fn to_mu(&self, config: &OutputConfig) -> String {
        // Default implementation falls back to table
        self.to_table(config)
    }

    /// Render as tree format
    fn to_tree(&self, config: &OutputConfig) -> String {
        // Default implementation falls back to table
        self.to_table(config)
    }

    /// Render using the format specified in config
    fn render(&self, config: &OutputConfig) -> String {
        match config.format {
            OutputFormat::Table => self.to_table(config),
            OutputFormat::Json => self.to_json(config),
            OutputFormat::Csv => self.to_csv(config),
            OutputFormat::Mu => self.to_mu(config),
            OutputFormat::Tree => self.to_tree(config),
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

    /// Create a new output wrapper with full config
    pub fn with_config(data: T, config: OutputConfig) -> Self {
        Self { data, config }
    }

    /// Render the output to stdout
    pub fn render(&self) -> anyhow::Result<()> {
        self.data.output(&self.config);
        Ok(())
    }

    /// Get the rendered string without printing
    pub fn render_to_string(&self) -> String {
        self.data.render(&self.config)
    }
}

// ============================================================================
// Legacy compatibility - TableDisplay trait
// ============================================================================

/// Legacy trait for types that can be displayed as a table
///
/// This trait is maintained for backward compatibility with existing code.
/// New code should implement `Outputter` instead.
pub trait TableDisplay: Serialize {
    /// Convert to table format string
    fn to_table(&self) -> String;

    /// Convert to MU sigil format string
    fn to_mu(&self) -> String {
        // Default implementation just uses table format
        self.to_table()
    }
}

/// Blanket implementation of Outputter for TableDisplay types
impl<T: TableDisplay + Serialize> Outputter for T {
    fn to_table(&self, _config: &OutputConfig) -> String {
        TableDisplay::to_table(self)
    }

    fn to_csv(&self, _config: &OutputConfig) -> String {
        // Default CSV implementation for legacy types
        format!(
            "data\n\"{}\"",
            TableDisplay::to_table(self).replace('"', "\"\"")
        )
    }

    fn to_mu(&self, _config: &OutputConfig) -> String {
        TableDisplay::to_mu(self)
    }
}

// ============================================================================
// Built-in message types
// ============================================================================

/// Simple success message
#[derive(Debug, Serialize)]
pub struct SuccessMessage {
    pub message: String,
}

impl SuccessMessage {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl TableDisplay for SuccessMessage {
    fn to_table(&self) -> String {
        use colored::Colorize;
        format!("{} {}", "SUCCESS:".green().bold(), self.message)
    }

    fn to_mu(&self) -> String {
        format!(":: success\n{}", self.message)
    }
}

/// Simple error message
#[derive(Debug, Serialize)]
pub struct ErrorMessage {
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<String>,
}

impl ErrorMessage {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            details: None,
        }
    }

    pub fn with_details(message: impl Into<String>, details: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            details: Some(details.into()),
        }
    }
}

impl TableDisplay for ErrorMessage {
    fn to_table(&self) -> String {
        use colored::Colorize;
        let mut output = format!("{} {}", "ERROR:".red().bold(), self.message);
        if let Some(details) = &self.details {
            output.push_str(&format!("\n{}", details.dimmed()));
        }
        output
    }

    fn to_mu(&self) -> String {
        let mut output = format!(":: error\n{}", self.message);
        if let Some(details) = &self.details {
            output.push_str(&format!("\n  | {}", details));
        }
        output
    }
}

/// Not implemented placeholder
#[derive(Debug, Serialize)]
pub struct NotImplemented {
    pub command: String,
}

impl NotImplemented {
    pub fn new(command: impl Into<String>) -> Self {
        Self {
            command: command.into(),
        }
    }
}

impl TableDisplay for NotImplemented {
    fn to_table(&self) -> String {
        use colored::Colorize;
        format!(
            "{} Command '{}' is not implemented yet",
            "INFO:".yellow().bold(),
            self.command.cyan()
        )
    }

    fn to_mu(&self) -> String {
        format!(":: pending\n# {} -> not implemented", self.command)
    }
}

/// Print a not implemented message
pub fn not_implemented(command: &str, format: OutputFormat) -> anyhow::Result<()> {
    Output::new(NotImplemented::new(command), format).render()
}

// ============================================================================
// Utility functions
// ============================================================================

/// Truncate a string to a maximum width with ellipsis
pub fn truncate(s: &str, max_width: usize) -> String {
    if s.len() <= max_width {
        s.to_string()
    } else if max_width <= 3 {
        s.chars().take(max_width).collect()
    } else {
        let truncated: String = s.chars().take(max_width - 3).collect();
        format!("{}...", truncated)
    }
}

/// Detect if stdout is a TTY
pub fn is_tty() -> bool {
    std::io::stdout().is_terminal()
}

/// Get terminal width, defaulting to 80 if unavailable
pub fn terminal_width() -> usize {
    terminal_size::terminal_size()
        .map(|(w, _)| w.0 as usize)
        .unwrap_or(80)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_truncate_short_string() {
        assert_eq!(truncate("hello", 10), "hello");
    }

    #[test]
    fn test_truncate_long_string() {
        assert_eq!(truncate("hello world", 8), "hello...");
    }

    #[test]
    fn test_truncate_exact_length() {
        assert_eq!(truncate("hello", 5), "hello");
    }

    #[test]
    fn test_output_config_auto_detect() {
        let config = OutputConfig::auto_detect(OutputFormat::Table);
        assert_eq!(config.format, OutputFormat::Table);
    }

    #[test]
    fn test_output_config_builder() {
        let config = OutputConfig::new(OutputFormat::Json)
            .without_colors()
            .without_truncation()
            .with_width(120)
            .compact();

        assert_eq!(config.format, OutputFormat::Json);
        assert!(config.no_color);
        assert!(config.no_truncate);
        assert_eq!(config.width, Some(120));
        assert!(config.compact);
    }

    #[test]
    fn test_column_builder() {
        let col = Column::new("Name", "name")
            .with_max_width(50)
            .with_alignment(Alignment::Right);

        assert_eq!(col.name, "Name");
        assert_eq!(col.key, "name");
        assert_eq!(col.max_width, Some(50));
        assert_eq!(col.align, Alignment::Right);
    }
}
