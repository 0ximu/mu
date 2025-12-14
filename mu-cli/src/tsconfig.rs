//! TypeScript/JavaScript path alias resolution
//!
//! Parses tsconfig.json/jsconfig.json to resolve path aliases like `@/lib/logger`
//! to actual file paths. Supports `extends`, JSON comments, and common alias patterns.

use serde::Deserialize;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

/// TypeScript/JavaScript compiler options relevant to path resolution
#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct CompilerOptions {
    /// Base URL for resolving non-relative module names
    #[serde(default)]
    pub base_url: Option<String>,

    /// Path mapping entries (e.g., "@/*": ["src/*"])
    #[serde(default)]
    pub paths: HashMap<String, Vec<String>>,
}

/// TypeScript configuration file structure
#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct TsConfig {
    /// Extends another config file
    #[serde(default)]
    pub extends: Option<String>,

    /// Compiler options including paths
    #[serde(default)]
    pub compiler_options: Option<CompilerOptions>,
}

/// Resolves TypeScript/JavaScript path aliases to actual file paths
#[derive(Debug, Clone)]
pub struct PathAliasResolver {
    /// The project root directory
    root: PathBuf,

    /// Base URL for path resolution (absolute)
    base_url: PathBuf,

    /// Parsed path mappings: alias pattern -> list of target patterns
    paths: HashMap<String, Vec<String>>,
}

impl PathAliasResolver {
    /// Load a PathAliasResolver from a project root directory.
    ///
    /// Looks for tsconfig.json or jsconfig.json in the root directory.
    /// Returns None if no config file is found or if it has no path mappings.
    pub fn from_project(root: &Path) -> Option<Self> {
        let root = root.to_path_buf();

        // Try tsconfig.json first, then jsconfig.json
        let config_path = if root.join("tsconfig.json").exists() {
            root.join("tsconfig.json")
        } else if root.join("jsconfig.json").exists() {
            root.join("jsconfig.json")
        } else {
            return None;
        };

        Self::from_config_file(&config_path, &root)
    }

    /// Load from a specific config file path
    fn from_config_file(config_path: &Path, root: &Path) -> Option<Self> {
        let content = fs::read_to_string(config_path).ok()?;
        let content = strip_json_comments(&content);

        let config: TsConfig = serde_json::from_str(&content).ok()?;

        // Handle extends
        let mut merged_options = CompilerOptions::default();

        if let Some(extends) = &config.extends {
            if let Some(parent_config) = Self::resolve_extends(extends, config_path, root) {
                if let Some(parent_opts) = parent_config.compiler_options {
                    merged_options.base_url = parent_opts.base_url;
                    merged_options.paths = parent_opts.paths;
                }
            }
        }

        // Override with current config's options
        if let Some(opts) = config.compiler_options {
            if opts.base_url.is_some() {
                merged_options.base_url = opts.base_url;
            }
            // Merge paths (current config takes precedence)
            for (key, value) in opts.paths {
                merged_options.paths.insert(key, value);
            }
        }

        // Return None if no paths defined
        if merged_options.paths.is_empty() {
            return None;
        }

        // Resolve base_url relative to config file directory
        let config_dir = config_path.parent().unwrap_or(root);
        let base_url = if let Some(ref base) = merged_options.base_url {
            config_dir.join(base)
        } else {
            config_dir.to_path_buf()
        };

        Some(Self {
            root: root.to_path_buf(),
            base_url,
            paths: merged_options.paths,
        })
    }

    /// Resolve an extends reference to the parent config
    fn resolve_extends(extends: &str, config_path: &Path, root: &Path) -> Option<TsConfig> {
        let config_dir = config_path.parent().unwrap_or(root);

        // Handle relative paths
        let parent_path = if extends.starts_with("./") || extends.starts_with("../") {
            config_dir.join(extends)
        } else if extends.starts_with('@') {
            // Package reference like @tsconfig/node20/tsconfig.json
            // Try to resolve from node_modules
            root.join("node_modules").join(extends)
        } else {
            // Assume relative to config dir
            config_dir.join(extends)
        };

        // Add .json extension if missing
        let parent_path = if parent_path.extension().is_none() {
            parent_path.with_extension("json")
        } else {
            parent_path
        };

        let content = fs::read_to_string(&parent_path).ok()?;
        let content = strip_json_comments(&content);
        serde_json::from_str(&content).ok()
    }

    /// Resolve a path alias to a module path.
    ///
    /// Takes an import path like `@/lib/logger` and returns the resolved path
    /// relative to the project root (e.g., `mod:src/lib/logger.ts`).
    ///
    /// Returns None if the import doesn't match any path alias.
    pub fn resolve(&self, import_path: &str) -> Option<String> {
        for (pattern, targets) in &self.paths {
            if let Some(matched) = self.match_pattern(pattern, import_path) {
                // Try each target in order
                for target in targets {
                    if let Some(resolved) = self.resolve_target(target, &matched) {
                        return Some(resolved);
                    }
                }
            }
        }
        None
    }

    /// Match an import path against a pattern, returning the wildcard match if successful.
    ///
    /// Pattern examples:
    /// - `@/*` matches `@/lib/logger` -> returns Some("lib/logger")
    /// - `@components/*` matches `@components/Button` -> returns Some("Button")
    /// - `utils` matches `utils` exactly -> returns Some("")
    fn match_pattern(&self, pattern: &str, import_path: &str) -> Option<String> {
        if pattern.ends_with('*') {
            // Wildcard pattern
            let prefix = &pattern[..pattern.len() - 1];
            if import_path.starts_with(prefix) {
                return Some(import_path[prefix.len()..].to_string());
            }
        } else {
            // Exact match
            if import_path == pattern {
                return Some(String::new());
            }
        }
        None
    }

    /// Resolve a target pattern with the matched wildcard portion.
    ///
    /// Target examples:
    /// - `src/*` with match "lib/logger" -> "src/lib/logger"
    /// - `./src/*` with match "lib/logger" -> "src/lib/logger"
    fn resolve_target(&self, target: &str, matched: &str) -> Option<String> {
        // Replace wildcard in target
        let resolved_target = if target.ends_with('*') {
            format!("{}{}", &target[..target.len() - 1], matched)
        } else {
            target.to_string()
        };

        // Clean up the path (remove leading ./)
        let resolved_target = resolved_target.trim_start_matches("./");

        // Resolve relative to base_url
        let full_path = self.base_url.join(resolved_target);

        // Try to find the actual file with various extensions
        if let Some(resolved_file) = self.resolve_file(&full_path) {
            // Make path relative to root
            if let Ok(relative) = resolved_file.strip_prefix(&self.root) {
                return Some(format!("mod:{}", relative.display()));
            }
        }

        None
    }

    /// Resolve a file path, trying various extensions and index files.
    fn resolve_file(&self, path: &Path) -> Option<PathBuf> {
        // Extensions to try (in order of preference)
        let extensions = ["ts", "tsx", "js", "jsx", "mts", "mjs", "cts", "cjs"];

        // If path already has an extension and exists, use it
        if path.extension().is_some() && path.exists() {
            return Some(path.to_path_buf());
        }

        // Try direct file with extensions
        for ext in &extensions {
            let with_ext = path.with_extension(ext);
            if with_ext.exists() {
                return Some(with_ext);
            }
        }

        // Try index files in directory
        if path.is_dir() {
            for ext in &extensions {
                let index_path = path.join(format!("index.{}", ext));
                if index_path.exists() {
                    return Some(index_path);
                }
            }
        }

        // If we can't verify existence, still return the path with .ts extension
        // (common case for build-time resolution)
        Some(path.with_extension("ts"))
    }
}

/// Strip JSON comments (// and /* */) from content.
///
/// tsconfig.json allows JavaScript-style comments which standard JSON parsers reject.
fn strip_json_comments(content: &str) -> String {
    let mut result = String::with_capacity(content.len());
    let mut chars = content.chars().peekable();
    let mut in_string = false;
    let mut escape_next = false;

    while let Some(c) = chars.next() {
        if escape_next {
            result.push(c);
            escape_next = false;
            continue;
        }

        if c == '\\' && in_string {
            result.push(c);
            escape_next = true;
            continue;
        }

        if c == '"' && !in_string {
            in_string = true;
            result.push(c);
            continue;
        }

        if c == '"' && in_string {
            in_string = false;
            result.push(c);
            continue;
        }

        if in_string {
            result.push(c);
            continue;
        }

        // Check for comments
        if c == '/' {
            if chars.peek() == Some(&'/') {
                // Line comment - skip until newline
                chars.next(); // consume second /
                while let Some(nc) = chars.next() {
                    if nc == '\n' {
                        result.push('\n'); // Preserve newlines for line counting
                        break;
                    }
                }
                continue;
            } else if chars.peek() == Some(&'*') {
                // Block comment - skip until */
                chars.next(); // consume *
                while let Some(nc) = chars.next() {
                    if nc == '*' && chars.peek() == Some(&'/') {
                        chars.next(); // consume /
                        break;
                    }
                    if nc == '\n' {
                        result.push('\n'); // Preserve newlines
                    }
                }
                continue;
            }
        }

        result.push(c);
    }

    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    fn create_tsconfig(dir: &Path, content: &str) {
        fs::write(dir.join("tsconfig.json"), content).unwrap();
    }

    fn create_file(dir: &Path, path: &str) {
        let full_path = dir.join(path);
        if let Some(parent) = full_path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(full_path, "// placeholder").unwrap();
    }

    #[test]
    fn test_path_alias_resolution_basic() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        // Create tsconfig with basic alias
        create_tsconfig(
            root,
            r#"{
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["src/*"]
                    }
                }
            }"#,
        );

        // Create the target file
        create_file(root, "src/lib/logger.ts");

        let resolver = PathAliasResolver::from_project(root).unwrap();

        // Test basic resolution
        let resolved = resolver.resolve("@/lib/logger").unwrap();
        assert_eq!(resolved, "mod:src/lib/logger.ts");
    }

    #[test]
    fn test_path_alias_no_match() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        create_tsconfig(
            root,
            r#"{
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["src/*"]
                    }
                }
            }"#,
        );

        let resolver = PathAliasResolver::from_project(root).unwrap();

        // Non-aliased imports should return None
        assert!(resolver.resolve("react").is_none());
        assert!(resolver.resolve("./local/file").is_none());
        assert!(resolver.resolve("../parent/file").is_none());
        assert!(resolver.resolve("lodash").is_none());
    }

    #[test]
    fn test_path_alias_multiple_patterns() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        create_tsconfig(
            root,
            r#"{
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["src/*"],
                        "@components/*": ["src/components/*"],
                        "~/*": ["./src/*"]
                    }
                }
            }"#,
        );

        // Create target files
        create_file(root, "src/lib/utils.ts");
        create_file(root, "src/components/Button.tsx");
        create_file(root, "src/hooks/useAuth.ts");

        let resolver = PathAliasResolver::from_project(root).unwrap();

        // Test @/* pattern
        let resolved = resolver.resolve("@/lib/utils").unwrap();
        assert_eq!(resolved, "mod:src/lib/utils.ts");

        // Test @components/* pattern
        let resolved = resolver.resolve("@components/Button").unwrap();
        assert_eq!(resolved, "mod:src/components/Button.tsx");

        // Test ~/* pattern
        let resolved = resolver.resolve("~/hooks/useAuth").unwrap();
        assert_eq!(resolved, "mod:src/hooks/useAuth.ts");
    }

    #[test]
    fn test_strip_json_comments_line() {
        let input = r#"{
            // This is a comment
            "key": "value"
        }"#;
        let stripped = strip_json_comments(input);
        assert!(!stripped.contains("// This is a comment"));
        assert!(stripped.contains("\"key\": \"value\""));
    }

    #[test]
    fn test_strip_json_comments_block() {
        let input = r#"{
            /* Block comment */
            "key": "value"
        }"#;
        let stripped = strip_json_comments(input);
        assert!(!stripped.contains("Block comment"));
        assert!(stripped.contains("\"key\": \"value\""));
    }

    #[test]
    fn test_strip_json_comments_preserves_strings() {
        let input = r#"{
            "url": "http://example.com",
            "pattern": "/* not a comment */"
        }"#;
        let stripped = strip_json_comments(input);
        // URL should be preserved (// in string)
        assert!(stripped.contains("http://example.com"));
        // Comment-like string should be preserved
        assert!(stripped.contains("/* not a comment */"));
    }

    #[test]
    fn test_jsconfig_fallback() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        // Create jsconfig.json instead of tsconfig.json
        fs::write(
            root.join("jsconfig.json"),
            r#"{
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["src/*"]
                    }
                }
            }"#,
        )
        .unwrap();

        create_file(root, "src/utils.js");

        let resolver = PathAliasResolver::from_project(root).unwrap();
        let resolved = resolver.resolve("@/utils").unwrap();
        assert!(resolved.starts_with("mod:src/utils."));
    }

    #[test]
    fn test_index_file_resolution() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        create_tsconfig(
            root,
            r#"{
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["src/*"]
                    }
                }
            }"#,
        );

        // Create a directory with index.ts
        create_file(root, "src/components/index.ts");

        let resolver = PathAliasResolver::from_project(root).unwrap();
        let resolved = resolver.resolve("@/components").unwrap();
        assert_eq!(resolved, "mod:src/components/index.ts");
    }

    #[test]
    fn test_no_paths_returns_none() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        // tsconfig with no paths
        create_tsconfig(
            root,
            r#"{
                "compilerOptions": {
                    "target": "ES2020"
                }
            }"#,
        );

        let resolver = PathAliasResolver::from_project(root);
        assert!(resolver.is_none());
    }

    #[test]
    fn test_no_tsconfig_returns_none() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        let resolver = PathAliasResolver::from_project(root);
        assert!(resolver.is_none());
    }

    #[test]
    fn test_extends_inherits_paths() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        // Create base config
        fs::write(
            root.join("tsconfig.base.json"),
            r#"{
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["src/*"]
                    }
                }
            }"#,
        )
        .unwrap();

        // Create extending config
        create_tsconfig(
            root,
            r#"{
                "extends": "./tsconfig.base.json",
                "compilerOptions": {
                    "paths": {
                        "@components/*": ["src/components/*"]
                    }
                }
            }"#,
        );

        create_file(root, "src/lib/utils.ts");
        create_file(root, "src/components/Button.tsx");

        let resolver = PathAliasResolver::from_project(root).unwrap();

        // Should have both paths from base and extending config
        let resolved = resolver.resolve("@/lib/utils").unwrap();
        assert_eq!(resolved, "mod:src/lib/utils.ts");

        let resolved = resolver.resolve("@components/Button").unwrap();
        assert_eq!(resolved, "mod:src/components/Button.tsx");
    }

    #[test]
    fn test_pattern_exact_match() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        create_tsconfig(
            root,
            r#"{
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "config": ["src/config/index.ts"]
                    }
                }
            }"#,
        );

        create_file(root, "src/config/index.ts");

        let resolver = PathAliasResolver::from_project(root).unwrap();

        // Exact match should work
        let resolved = resolver.resolve("config").unwrap();
        assert!(resolved.contains("config"));
    }

    #[test]
    fn test_tsx_extension_resolution() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();

        create_tsconfig(
            root,
            r#"{
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["src/*"]
                    }
                }
            }"#,
        );

        // Create .tsx file
        create_file(root, "src/components/Modal.tsx");

        let resolver = PathAliasResolver::from_project(root).unwrap();
        let resolved = resolver.resolve("@/components/Modal").unwrap();
        assert_eq!(resolved, "mod:src/components/Modal.tsx");
    }
}
