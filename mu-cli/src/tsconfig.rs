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
        if let Some(prefix) = pattern.strip_suffix('*') {
            // Wildcard pattern
            if let Some(matched) = import_path.strip_prefix(prefix) {
                return Some(matched.to_string());
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
        let resolved_target = if let Some(prefix) = target.strip_suffix('*') {
            format!("{}{}", prefix, matched)
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

/// Resolves npm/yarn/pnpm workspace package imports to actual file paths.
///
/// Scans package.json workspaces to map package names like `@myorg/utils`
/// to their actual module paths like `mod:packages/utils/src/index.ts`.
#[derive(Debug, Clone)]
pub struct WorkspaceResolver {
    /// Maps package name -> module ID (e.g., "@expo-shell/ui" -> "mod:packages/ui/src/index.ts")
    packages: HashMap<String, String>,
}

/// Package.json structure for workspace resolution
#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct PackageJson {
    /// Package name
    #[serde(default)]
    name: Option<String>,

    /// Workspaces configuration (array or object with packages field)
    #[serde(default)]
    workspaces: Option<WorkspacesConfig>,

    /// Main entry point
    #[serde(default)]
    main: Option<String>,

    /// Module entry point (ESM)
    #[serde(default)]
    module: Option<String>,

    /// Exports map (modern Node.js)
    #[serde(default)]
    exports: Option<serde_json::Value>,
}

/// Workspaces can be an array or an object with a packages field
#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
enum WorkspacesConfig {
    Array(Vec<String>),
    Object { packages: Vec<String> },
}

impl WorkspaceResolver {
    /// Load a WorkspaceResolver from a project root directory.
    ///
    /// Reads package.json, finds all workspace packages, and builds a mapping
    /// from package names to their module paths.
    pub fn from_project(root: &Path) -> Option<Self> {
        let package_json_path = root.join("package.json");
        if !package_json_path.exists() {
            return None;
        }

        let content = fs::read_to_string(&package_json_path).ok()?;
        let package_json: PackageJson = serde_json::from_str(&content).ok()?;

        let workspace_patterns = match package_json.workspaces {
            Some(WorkspacesConfig::Array(patterns)) => patterns,
            Some(WorkspacesConfig::Object { packages }) => packages,
            None => return None,
        };

        let mut packages = HashMap::new();

        for pattern in workspace_patterns {
            // Expand glob pattern to find workspace directories
            let workspace_dirs = Self::expand_workspace_pattern(root, &pattern);

            for ws_dir in workspace_dirs {
                if let Some((name, module_id)) = Self::read_workspace_package(root, &ws_dir) {
                    packages.insert(name, module_id);
                }
            }
        }

        if packages.is_empty() {
            return None;
        }

        tracing::debug!(
            "WorkspaceResolver: found {} workspace packages",
            packages.len()
        );

        Some(Self { packages })
    }

    /// Expand a workspace pattern like "packages/*" to actual directories
    fn expand_workspace_pattern(root: &Path, pattern: &str) -> Vec<PathBuf> {
        let mut dirs = Vec::new();

        if pattern.ends_with("/*") {
            // Simple glob: packages/* -> list all subdirectories of packages/
            let base_dir = root.join(pattern.trim_end_matches("/*"));
            if let Ok(entries) = fs::read_dir(&base_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() && path.join("package.json").exists() {
                        dirs.push(path);
                    }
                }
            }
        } else if !pattern.contains('*') {
            // Exact path: packages/core
            let path = root.join(pattern);
            if path.is_dir() && path.join("package.json").exists() {
                dirs.push(path);
            }
        }
        // More complex globs like "packages/**" are not supported yet

        dirs
    }

    /// Read a workspace package's package.json and return (name, module_id)
    fn read_workspace_package(root: &Path, ws_dir: &Path) -> Option<(String, String)> {
        let pkg_json_path = ws_dir.join("package.json");
        let content = fs::read_to_string(&pkg_json_path).ok()?;
        let pkg: PackageJson = serde_json::from_str(&content).ok()?;

        let name = pkg.name.clone()?;

        // Find entry point: exports > module > main > src/index.ts > index.ts
        let entry_point = Self::find_entry_point(&pkg, ws_dir)?;

        // Make path relative to root
        let relative_path = entry_point.strip_prefix(root).ok()?;
        let module_id = format!("mod:{}", relative_path.display());

        Some((name, module_id))
    }

    /// Find the entry point file for a package
    fn find_entry_point(pkg: &PackageJson, ws_dir: &Path) -> Option<PathBuf> {
        // Check exports field (modern)
        if let Some(exports) = &pkg.exports {
            if let Some(entry) = Self::parse_exports(exports, ws_dir) {
                return Some(entry);
            }
        }

        // Check module field (ESM)
        if let Some(module) = &pkg.module {
            let path = ws_dir.join(module);
            if path.exists() {
                return Some(path);
            }
        }

        // Check main field
        if let Some(main) = &pkg.main {
            let path = ws_dir.join(main);
            if path.exists() {
                return Some(path);
            }
        }

        // Common conventions
        let conventions = [
            "src/index.ts",
            "src/index.tsx",
            "src/index.js",
            "lib/index.ts",
            "lib/index.js",
            "index.ts",
            "index.tsx",
            "index.js",
        ];

        for conv in conventions {
            let path = ws_dir.join(conv);
            if path.exists() {
                return Some(path);
            }
        }

        None
    }

    /// Parse exports field to find the main entry point
    fn parse_exports(exports: &serde_json::Value, ws_dir: &Path) -> Option<PathBuf> {
        match exports {
            // String: "exports": "./dist/index.js"
            serde_json::Value::String(s) => {
                let path = ws_dir.join(s.trim_start_matches("./"));
                if path.exists() {
                    return Some(path);
                }
            }
            // Object: "exports": { ".": "./dist/index.js" } or { "import": "...", "require": "..." }
            serde_json::Value::Object(obj) => {
                // Check for "." entry (main export)
                if let Some(main_export) = obj.get(".") {
                    return Self::parse_exports(main_export, ws_dir);
                }
                // Check for "import" or "default" or "types"
                for key in ["import", "default", "require", "types"] {
                    if let Some(serde_json::Value::String(s)) = obj.get(key) {
                        let path = ws_dir.join(s.trim_start_matches("./"));
                        if path.exists() {
                            return Some(path);
                        }
                    }
                }
            }
            _ => {}
        }
        None
    }

    /// Resolve a package import to a module path.
    ///
    /// Takes an import like `@myorg/utils` or `@myorg/utils/lib/helpers`
    /// and returns the resolved module ID.
    pub fn resolve(&self, import_path: &str) -> Option<String> {
        // Direct match: @myorg/utils -> mod:packages/utils/src/index.ts
        if let Some(module_id) = self.packages.get(import_path) {
            return Some(module_id.clone());
        }

        // Subpath match: @myorg/utils/lib/foo -> find @myorg/utils, append subpath
        // Find the longest matching package name
        for (pkg_name, module_id) in &self.packages {
            if import_path.starts_with(pkg_name)
                && import_path
                    .chars()
                    .nth(pkg_name.len())
                    .map_or(false, |c| c == '/')
            {
                // Extract subpath and resolve
                let subpath = &import_path[pkg_name.len() + 1..];
                // Get package directory from module_id
                if let Some(pkg_dir) = Self::module_id_to_dir(module_id) {
                    let sub_module_id = format!("mod:{}/{}", pkg_dir, subpath);
                    return Some(sub_module_id);
                }
            }
        }

        None
    }

    /// Convert a module ID like "mod:packages/ui/src/index.ts" to directory "packages/ui"
    fn module_id_to_dir(module_id: &str) -> Option<String> {
        let path = module_id.strip_prefix("mod:")?;
        // Find src/ or lib/ or the parent of index.* file
        if let Some(idx) = path.find("/src/") {
            return Some(path[..idx].to_string());
        }
        if let Some(idx) = path.find("/lib/") {
            return Some(path[..idx].to_string());
        }
        // If it ends with index.*, use parent directory
        if path.contains("/index.") {
            let parent = Path::new(path).parent()?;
            return Some(parent.display().to_string());
        }
        None
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
                for nc in chars.by_ref() {
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
