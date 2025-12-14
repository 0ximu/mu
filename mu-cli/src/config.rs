//! MU configuration loading from `.murc.toml`.
//!
//! This module provides configuration management for MU, loading settings from
//! a `.murc.toml` file in the project root. Configuration is optional - MU will
//! use sensible defaults if no config file exists.
//!
//! # Example Configuration
//!
//! ```toml
//! [mu]
//! version = "1.0"
//!
//! [scanner]
//! ignore = ["vendor/", "dist/", "generated/"]
//! include_hidden = false
//! max_file_size_kb = 1024
//!
//! [parser]
//! languages = ["python", "typescript", "rust"]
//!
//! [output]
//! format = "table"
//! color = true
//!
//! [cache]
//! enabled = true
//! directory = ".mu/cache"
//! ```

use serde::Deserialize;
use std::path::Path;

/// Root configuration structure loaded from `.murc.toml`.
///
/// All sections are optional and will use defaults if not specified.
/// The configuration file is loaded from the project root directory.
#[derive(Debug, Deserialize, Default)]
pub struct MuConfig {
    /// General MU settings (version tracking).
    #[serde(default)]
    pub mu: MuSection,

    /// File scanning configuration (what to include/exclude).
    #[serde(default)]
    pub scanner: ScannerConfig,

    /// Parser configuration (language selection).
    #[serde(default)]
    pub parser: ParserConfig,

    /// Output formatting preferences.
    #[serde(default)]
    pub output: OutputSettings,

    /// Cache configuration for incremental builds.
    #[serde(default)]
    pub cache: CacheConfig,
}

/// General MU configuration section.
///
/// Contains metadata about the configuration itself.
#[derive(Debug, Deserialize, Default)]
pub struct MuSection {
    /// Configuration schema version for future compatibility.
    /// Currently informational only.
    #[serde(default)]
    pub version: Option<String>,
}

/// Scanner configuration controlling file discovery.
///
/// These settings affect which files are discovered during `mu bootstrap`
/// and other scanning operations.
#[derive(Debug, Deserialize, Default)]
pub struct ScannerConfig {
    /// Additional glob patterns to ignore during scanning.
    ///
    /// These patterns are combined with built-in defaults (`.git/`, `node_modules/`, etc.)
    /// and any `.gitignore` / `.muignore` rules.
    ///
    /// # Example
    /// ```toml
    /// ignore = ["vendor/", "*.generated.ts", "dist/"]
    /// ```
    #[serde(default)]
    pub ignore: Vec<String>,

    /// Whether to include hidden files (starting with `.`).
    ///
    /// Defaults to `false`. Even when `true`, `.gitignore` rules still apply.
    #[serde(default)]
    pub include_hidden: bool,

    /// Maximum file size to process, in kilobytes.
    ///
    /// Files larger than this are skipped during scanning. Useful for excluding
    /// large generated files or binary assets that accidentally have code extensions.
    ///
    /// Default: no limit (all files processed).
    #[serde(default)]
    pub max_file_size_kb: Option<u64>,
}

/// Parser configuration controlling language processing.
///
/// These settings affect which languages are parsed and how.
#[derive(Debug, Deserialize, Default)]
pub struct ParserConfig {
    /// Languages to parse.
    ///
    /// Can be:
    /// - Empty/None: Parse all supported languages (default)
    /// - List of language names: Only parse specified languages
    ///
    /// Supported languages: `python`, `typescript`, `javascript`, `tsx`, `jsx`,
    /// `rust`, `go`, `java`, `csharp`
    ///
    /// # Example
    /// ```toml
    /// languages = ["python", "typescript"]
    /// ```
    #[serde(default)]
    pub languages: Option<Vec<String>>,
}

/// Output formatting preferences.
///
/// These settings provide defaults for CLI output formatting.
/// Command-line flags (e.g., `--format json`) override these settings.
///
/// Note: This is distinct from the runtime `OutputConfig` in the output module,
/// which handles actual rendering. These settings provide user preferences.
#[derive(Debug, Deserialize, Default)]
pub struct OutputSettings {
    /// Default output format for CLI commands.
    ///
    /// Valid values: `table`, `json`, `csv`, `mu`, `tree`
    /// Default: `table`
    #[serde(default)]
    pub format: Option<String>,

    /// Whether to use colored output.
    ///
    /// Defaults to `true` when stdout is a TTY.
    #[serde(default)]
    pub color: Option<bool>,
}

/// Cache configuration for incremental operations.
///
/// MU can cache parse results and embeddings to speed up subsequent runs.
/// The cache is stored in the `.mu/` directory by default.
#[derive(Debug, Deserialize)]
pub struct CacheConfig {
    /// Whether caching is enabled.
    ///
    /// When enabled, MU will cache parse results and only re-parse files
    /// that have changed (detected via file hash).
    ///
    /// Default: `true`
    #[serde(default = "default_cache_enabled")]
    pub enabled: bool,

    /// Custom cache directory path.
    ///
    /// If not specified, defaults to `.mu/cache` in the project root.
    #[serde(default)]
    pub directory: Option<String>,
}

fn default_cache_enabled() -> bool {
    true
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            directory: None,
        }
    }
}

/// Default ignore patterns that are always included.
const DEFAULT_IGNORE_PATTERNS: &[&str] = &[
    ".git/",
    ".mu/",
    "node_modules/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
    "target/",  // Rust build output
    "archive/", // MU archive folder
];

impl MuConfig {
    /// Load configuration from `.murc.toml` in the given directory.
    ///
    /// If the config file doesn't exist or can't be parsed, returns defaults.
    /// Parse errors are logged as warnings but don't cause failures.
    ///
    /// # Arguments
    ///
    /// * `root` - Project root directory to search for `.murc.toml`
    ///
    /// # Returns
    ///
    /// Loaded configuration, or defaults if no config file exists.
    pub fn load(root: &Path) -> Self {
        let config_path = root.join(".murc.toml");
        if config_path.exists() {
            match std::fs::read_to_string(&config_path) {
                Ok(content) => match toml::from_str(&content) {
                    Ok(config) => return config,
                    Err(e) => {
                        tracing::warn!("Failed to parse .murc.toml: {}", e);
                    }
                },
                Err(e) => {
                    tracing::warn!("Failed to read .murc.toml: {}", e);
                }
            }
        }
        Self::default()
    }

    /// Get ignore patterns for the scanner, with defaults included.
    ///
    /// Combines user-specified patterns from `[scanner].ignore` with
    /// built-in defaults. User patterns take precedence (appear first).
    ///
    /// # Default patterns
    ///
    /// - `.git/` - Git directory
    /// - `.mu/` - MU database directory
    /// - `node_modules/` - Node.js dependencies
    /// - `__pycache__/`, `*.pyc` - Python bytecode
    /// - `.venv/`, `venv/` - Python virtual environments
    /// - `target/` - Rust build output
    /// - `archive/` - MU archive folder
    pub fn ignore_patterns(&self) -> Vec<String> {
        let mut patterns = self.scanner.ignore.clone();

        // Add default patterns if not already present
        for default in DEFAULT_IGNORE_PATTERNS {
            let default_str = default.to_string();
            if !patterns.iter().any(|p| p == &default_str) {
                patterns.push(default_str);
            }
        }

        patterns
    }

    /// Get the maximum file size in bytes, if configured.
    ///
    /// Converts the `max_file_size_kb` setting to bytes.
    pub fn max_file_size_bytes(&self) -> Option<u64> {
        self.scanner.max_file_size_kb.map(|kb| kb * 1024)
    }

    /// Get the list of languages to parse, if configured.
    ///
    /// Returns `None` if all languages should be parsed (default behavior).
    pub fn languages(&self) -> Option<&[String]> {
        self.parser.languages.as_deref()
    }

    /// Check if a specific language should be parsed.
    ///
    /// Returns `true` if:
    /// - No language filter is configured (parse all), or
    /// - The language is in the configured list
    pub fn should_parse_language(&self, lang: &str) -> bool {
        match &self.parser.languages {
            None => true,
            Some(langs) => langs.iter().any(|l| l.eq_ignore_ascii_case(lang)),
        }
    }

    /// Get the default output format, if configured.
    ///
    /// Returns `None` if the default (table) should be used.
    pub fn default_format(&self) -> Option<&str> {
        self.output.format.as_deref()
    }

    /// Check if colored output should be used.
    ///
    /// Returns the configured value, or `None` to use auto-detection.
    pub fn use_color(&self) -> Option<bool> {
        self.output.color
    }

    /// Check if caching is enabled.
    pub fn cache_enabled(&self) -> bool {
        self.cache.enabled
    }

    /// Get the cache directory path, if configured.
    pub fn cache_directory(&self) -> Option<&str> {
        self.cache.directory.as_deref()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = MuConfig::default();
        assert!(!config.scanner.include_hidden);
        assert!(config.cache.enabled);
        assert!(config.parser.languages.is_none());
        assert!(config.output.format.is_none());
    }

    #[test]
    fn test_parse_full_config() {
        let toml_content = r#"
[mu]
version = "1.0"

[scanner]
ignore = ["vendor/", "dist/"]
include_hidden = true
max_file_size_kb = 512

[parser]
languages = ["python", "typescript"]

[output]
format = "json"
color = false

[cache]
enabled = false
directory = "/tmp/mu-cache"
"#;
        let config: MuConfig = toml::from_str(toml_content).unwrap();

        // MU section
        assert_eq!(config.mu.version, Some("1.0".to_string()));

        // Scanner section
        assert_eq!(config.scanner.ignore, vec!["vendor/", "dist/"]);
        assert!(config.scanner.include_hidden);
        assert_eq!(config.scanner.max_file_size_kb, Some(512));
        assert_eq!(config.max_file_size_bytes(), Some(512 * 1024));

        // Parser section
        assert_eq!(
            config.parser.languages,
            Some(vec!["python".to_string(), "typescript".to_string()])
        );
        assert!(config.should_parse_language("python"));
        assert!(config.should_parse_language("Python")); // Case insensitive
        assert!(!config.should_parse_language("rust"));

        // Output section
        assert_eq!(config.output.format, Some("json".to_string()));
        assert_eq!(config.default_format(), Some("json"));
        assert_eq!(config.output.color, Some(false));

        // Cache section
        assert!(!config.cache.enabled);
        assert_eq!(config.cache.directory, Some("/tmp/mu-cache".to_string()));
    }

    #[test]
    fn test_ignore_patterns_with_defaults() {
        let config = MuConfig::default();
        let patterns = config.ignore_patterns();

        // All defaults should be present
        for default in DEFAULT_IGNORE_PATTERNS {
            assert!(
                patterns.contains(&default.to_string()),
                "Missing default pattern: {}",
                default
            );
        }
    }

    #[test]
    fn test_ignore_patterns_with_custom() {
        let toml_content = r#"
[scanner]
ignore = ["custom/", ".git/"]
"#;
        let config: MuConfig = toml::from_str(toml_content).unwrap();
        let patterns = config.ignore_patterns();

        // Custom pattern should be first
        assert_eq!(patterns[0], "custom/");
        // .git/ was already specified, shouldn't be duplicated
        assert_eq!(patterns.iter().filter(|p| *p == ".git/").count(), 1);
    }

    #[test]
    fn test_should_parse_language_no_filter() {
        let config = MuConfig::default();

        // Without filter, all languages should be parsed
        assert!(config.should_parse_language("python"));
        assert!(config.should_parse_language("rust"));
        assert!(config.should_parse_language("typescript"));
        assert!(config.should_parse_language("anything"));
    }

    #[test]
    fn test_max_file_size_conversion() {
        let config = MuConfig::default();
        assert_eq!(config.max_file_size_bytes(), None);

        let toml_content = r#"
[scanner]
max_file_size_kb = 100
"#;
        let config: MuConfig = toml::from_str(toml_content).unwrap();
        assert_eq!(config.max_file_size_bytes(), Some(100 * 1024));
    }
}
