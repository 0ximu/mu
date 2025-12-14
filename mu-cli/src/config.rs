//! MU configuration loading from .murc.toml

use serde::Deserialize;
use std::path::Path;

/// MU configuration loaded from .murc.toml
#[derive(Debug, Deserialize, Default)]
pub struct MuConfig {
    #[serde(default)]
    pub mu: MuSection,
    #[serde(default)]
    pub scanner: ScannerConfig,
    #[serde(default)]
    pub parser: ParserConfig,
    #[serde(default)]
    pub output: OutputConfig,
    #[serde(default)]
    pub cache: CacheConfig,
}

#[derive(Debug, Deserialize, Default)]
pub struct MuSection {
    #[serde(default)]
    pub version: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
pub struct ScannerConfig {
    /// Patterns to ignore during scanning
    #[serde(default)]
    pub ignore: Vec<String>,
    /// Whether to include hidden files
    #[serde(default)]
    pub include_hidden: bool,
    /// Maximum file size in KB
    #[serde(default)]
    pub max_file_size_kb: Option<u64>,
}

#[derive(Debug, Deserialize, Default)]
pub struct ParserConfig {
    /// Languages to parse ("auto" or list)
    #[serde(default)]
    pub languages: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
pub struct OutputConfig {
    /// Default output format
    #[serde(default)]
    pub format: Option<String>,
    /// Include line numbers in output
    #[serde(default)]
    pub include_line_numbers: bool,
}

#[derive(Debug, Deserialize)]
pub struct CacheConfig {
    /// Whether caching is enabled
    #[serde(default = "default_cache_enabled")]
    pub enabled: bool,
    /// Cache directory path
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

impl MuConfig {
    /// Load configuration from .murc.toml in the given directory
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

    /// Get ignore patterns for the scanner, with defaults included
    pub fn ignore_patterns(&self) -> Vec<String> {
        let mut patterns = self.scanner.ignore.clone();

        // Add default patterns if not already present
        let defaults = vec![
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

        for default in defaults {
            let default_str = default.to_string();
            if !patterns.iter().any(|p| p == &default_str) {
                patterns.push(default_str);
            }
        }

        patterns
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
    }

    #[test]
    fn test_parse_config() {
        let toml_content = r#"
[mu]
version = "1.0"

[scanner]
ignore = ["vendor/", "dist/"]
include_hidden = false

[cache]
enabled = true
"#;
        let config: MuConfig = toml::from_str(toml_content).unwrap();
        assert_eq!(config.mu.version, Some("1.0".to_string()));
        assert_eq!(config.scanner.ignore, vec!["vendor/", "dist/"]);
        assert!(config.cache.enabled);
    }

    #[test]
    fn test_ignore_patterns_with_defaults() {
        let config = MuConfig::default();
        let patterns = config.ignore_patterns();
        assert!(patterns.contains(&".git/".to_string()));
        assert!(patterns.contains(&".mu/".to_string()));
        assert!(patterns.contains(&"archive/".to_string()));
    }
}
