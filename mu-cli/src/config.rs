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
use std::path::{Path, PathBuf};
use thiserror::Error;

/// Errors that can occur when loading configuration.
#[derive(Debug, Error)]
pub enum ConfigError {
    /// Failed to read the configuration file.
    #[error("Failed to read config file {}: {}", .0.display(), .1)]
    ReadError(PathBuf, std::io::Error),

    /// Failed to parse the configuration file.
    #[error("Failed to parse {}: {}\n  Hint: {}", .path.display(), .error, .suggestion)]
    ParseError {
        path: PathBuf,
        error: String,
        suggestion: String,
    },
}

/// Suggest a fix for common TOML parsing errors.
fn suggest_config_fix(error: &toml::de::Error) -> String {
    let msg = error.to_string();
    if msg.contains("expected array") {
        "Use array syntax: languages = [\"python\", \"rust\"]".to_string()
    } else if msg.contains("expected string") {
        "Use quotes around string values".to_string()
    } else if msg.contains("expected boolean") {
        "Use true or false (without quotes)".to_string()
    } else if msg.contains("expected integer") {
        "Use a number without quotes".to_string()
    } else if msg.contains("invalid type") {
        "Check that the value type matches expected (string, array, boolean, etc.)".to_string()
    } else {
        "Check TOML syntax at https://toml.io".to_string()
    }
}

/// Root configuration structure loaded from `.murc.toml`.
///
/// All sections are optional and will use defaults if not specified.
/// The configuration file is loaded from the project root directory.
#[derive(Debug, Deserialize, Default)]
pub struct MuConfig {
    /// General MU settings (version tracking).
    /// Parsed from config but reserved for future use.
    #[serde(default)]
    #[allow(dead_code)]
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
    /// Currently informational only; reserved for future use.
    #[serde(default)]
    #[allow(dead_code)]
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

    /// Load configuration with strict validation - returns error on parse failure.
    ///
    /// Unlike [`load`], this method returns meaningful errors when the configuration
    /// file exists but cannot be parsed. Use this for commands where users expect
    /// their configuration to be applied (e.g., `mu bootstrap --strict`).
    ///
    /// # Arguments
    ///
    /// * `root` - Project root directory to search for `.murc.toml`
    ///
    /// # Returns
    ///
    /// - `Ok(config)` if the file doesn't exist (uses defaults) or was parsed successfully
    /// - `Err(ConfigError)` if the file exists but couldn't be read or parsed
    ///
    /// # Example
    ///
    /// ```ignore
    /// match MuConfig::load_strict(&project_root) {
    ///     Ok(config) => println!("Config loaded"),
    ///     Err(e) => eprintln!("Config error: {}", e),
    /// }
    /// ```
    pub fn load_strict(root: &Path) -> Result<Self, ConfigError> {
        let config_path = root.join(".murc.toml");

        // No config file = use defaults (not an error)
        if !config_path.exists() {
            return Ok(Self::default());
        }

        // Read the file
        let content = std::fs::read_to_string(&config_path)
            .map_err(|e| ConfigError::ReadError(config_path.clone(), e))?;

        // Empty file = use defaults
        if content.trim().is_empty() {
            return Ok(Self::default());
        }

        // Parse the TOML
        toml::from_str(&content).map_err(|e| ConfigError::ParseError {
            path: config_path,
            error: e.to_string(),
            suggestion: suggest_config_fix(&e),
        })
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

    #[test]
    fn test_load_strict_no_file() {
        let temp_dir = std::env::temp_dir().join("mu_test_no_config");
        let _ = std::fs::create_dir_all(&temp_dir);

        // Remove config file if it exists
        let config_path = temp_dir.join(".murc.toml");
        let _ = std::fs::remove_file(&config_path);

        let result = MuConfig::load_strict(&temp_dir);
        assert!(result.is_ok());
        let config = result.unwrap();
        // Should use defaults
        assert!(config.cache.enabled);
    }

    #[test]
    fn test_load_strict_empty_file() {
        let temp_dir = std::env::temp_dir().join("mu_test_empty_config");
        let _ = std::fs::create_dir_all(&temp_dir);

        let config_path = temp_dir.join(".murc.toml");
        std::fs::write(&config_path, "").unwrap();

        let result = MuConfig::load_strict(&temp_dir);
        assert!(result.is_ok());
        let config = result.unwrap();
        // Should use defaults
        assert!(config.cache.enabled);
    }

    #[test]
    fn test_load_strict_valid_config() {
        let temp_dir = std::env::temp_dir().join("mu_test_valid_config");
        let _ = std::fs::create_dir_all(&temp_dir);

        let config_path = temp_dir.join(".murc.toml");
        std::fs::write(
            &config_path,
            r#"
[cache]
enabled = false
"#,
        )
        .unwrap();

        let result = MuConfig::load_strict(&temp_dir);
        assert!(result.is_ok());
        let config = result.unwrap();
        assert!(!config.cache.enabled);
    }

    #[test]
    fn test_load_strict_invalid_toml() {
        let temp_dir = std::env::temp_dir().join("mu_test_invalid_config");
        let _ = std::fs::create_dir_all(&temp_dir);

        let config_path = temp_dir.join(".murc.toml");
        std::fs::write(&config_path, "this is not valid toml [[[").unwrap();

        let result = MuConfig::load_strict(&temp_dir);
        assert!(result.is_err());

        let err = result.unwrap_err();
        let err_msg = err.to_string();
        assert!(err_msg.contains("Failed to parse"));
        assert!(err_msg.contains("Hint:"));
    }

    #[test]
    fn test_load_strict_type_error() {
        let temp_dir = std::env::temp_dir().join("mu_test_type_error_config");
        let _ = std::fs::create_dir_all(&temp_dir);

        let config_path = temp_dir.join(".murc.toml");
        // languages should be an array, not a string
        std::fs::write(
            &config_path,
            r#"
[parser]
languages = "python"
"#,
        )
        .unwrap();

        let result = MuConfig::load_strict(&temp_dir);
        assert!(result.is_err());

        let err = result.unwrap_err();
        let err_msg = err.to_string();
        assert!(err_msg.contains("Failed to parse"));
        // Should suggest array syntax
        assert!(err_msg.contains("array"));
    }

    #[test]
    fn test_suggest_config_fix_array_error() {
        // Create a fake toml parse error for array
        let bad_toml = r#"languages = "python""#;
        let err: Result<ParserConfig, _> = toml::from_str(bad_toml);
        if let Err(e) = err {
            let suggestion = suggest_config_fix(&e);
            assert!(suggestion.contains("array"));
        }
    }
}
