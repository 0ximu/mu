//! Parse cache for incremental builds.
//!
//! This module provides caching of parse results to speed up subsequent runs of `mu bootstrap`.
//! When caching is enabled, MU stores parse results keyed by file hash and only re-parses
//! files that have changed.
//!
//! # Cache Format
//!
//! The cache is stored as a JSON file at `.mu/cache/parse_cache.json` with the structure:
//!
//! ```json
//! {
//!   "version": "1",
//!   "entries": {
//!     "src/main.py": {
//!       "hash": "xxh3:abc123...",
//!       "module": { ... }
//!     }
//!   }
//! }
//! ```

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::Path;

use mu_core::types::ModuleDef;

/// Current cache format version. Increment when cache format changes.
const CACHE_VERSION: &str = "1";

/// Default cache file path relative to project root.
const DEFAULT_CACHE_PATH: &str = ".mu/cache/parse_cache.json";

/// A cached parse result for a single file.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheEntry {
    /// File content hash (xxh3 format).
    pub hash: String,
    /// Cached parsed module.
    pub module: ModuleDef,
}

/// The complete parse cache.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParseCache {
    /// Cache format version for compatibility checking.
    pub version: String,
    /// Cached entries keyed by relative file path.
    pub entries: HashMap<String, CacheEntry>,
}

impl Default for ParseCache {
    fn default() -> Self {
        Self {
            version: CACHE_VERSION.to_string(),
            entries: HashMap::new(),
        }
    }
}

impl ParseCache {
    /// Create a new empty cache.
    pub fn new() -> Self {
        Self::default()
    }

    /// Load cache from disk.
    ///
    /// Returns an empty cache if the file doesn't exist, is invalid, or has
    /// an incompatible version.
    pub fn load(cache_dir: Option<&str>, project_root: &Path) -> Self {
        let cache_path = Self::cache_path(cache_dir, project_root);

        if !cache_path.exists() {
            tracing::debug!("No parse cache found at {:?}", cache_path);
            return Self::new();
        }

        match fs::read_to_string(&cache_path) {
            Ok(content) => match serde_json::from_str::<ParseCache>(&content) {
                Ok(cache) => {
                    // Check version compatibility
                    if cache.version != CACHE_VERSION {
                        tracing::info!(
                            "Cache version mismatch (found {}, expected {}), starting fresh",
                            cache.version,
                            CACHE_VERSION
                        );
                        return Self::new();
                    }
                    tracing::debug!("Loaded parse cache with {} entries", cache.entries.len());
                    cache
                }
                Err(e) => {
                    tracing::warn!("Failed to parse cache file: {}", e);
                    Self::new()
                }
            },
            Err(e) => {
                tracing::warn!("Failed to read cache file: {}", e);
                Self::new()
            }
        }
    }

    /// Save cache to disk.
    pub fn save(&self, cache_dir: Option<&str>, project_root: &Path) -> anyhow::Result<()> {
        let cache_path = Self::cache_path(cache_dir, project_root);

        // Ensure parent directory exists
        if let Some(parent) = cache_path.parent() {
            fs::create_dir_all(parent)?;
        }

        let content = serde_json::to_string_pretty(self)?;
        fs::write(&cache_path, content)?;

        tracing::debug!(
            "Saved parse cache with {} entries to {:?}",
            self.entries.len(),
            cache_path
        );

        Ok(())
    }

    /// Get the cache file path.
    fn cache_path(cache_dir: Option<&str>, project_root: &Path) -> std::path::PathBuf {
        match cache_dir {
            Some(dir) => project_root.join(dir).join("parse_cache.json"),
            None => project_root.join(DEFAULT_CACHE_PATH),
        }
    }

    /// Check if a file is cached with a matching hash.
    ///
    /// Returns `Some(&ModuleDef)` if the file is cached and the hash matches,
    /// otherwise `None`.
    pub fn get(&self, path: &str, hash: &str) -> Option<&ModuleDef> {
        self.entries.get(path).and_then(|entry| {
            if entry.hash == hash {
                Some(&entry.module)
            } else {
                None
            }
        })
    }

    /// Insert or update a cache entry.
    pub fn insert(&mut self, path: String, hash: String, module: ModuleDef) {
        self.entries.insert(path, CacheEntry { hash, module });
    }

    /// Remove entries for files that no longer exist.
    ///
    /// Takes a set of current file paths and removes any cached entries
    /// that are not in this set.
    pub fn prune(&mut self, current_files: &std::collections::HashSet<String>) {
        let before = self.entries.len();
        self.entries.retain(|path, _| current_files.contains(path));
        let removed = before - self.entries.len();
        if removed > 0 {
            tracing::debug!("Pruned {} stale cache entries", removed);
        }
    }

    /// Get the number of cached entries.
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Check if the cache is empty.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

/// Statistics about cache usage during a build.
#[derive(Debug, Default, Clone)]
pub struct CacheStats {
    /// Number of cache hits (files skipped).
    pub hits: usize,
    /// Number of cache misses (files parsed).
    pub misses: usize,
    /// Number of stale entries removed.
    pub pruned: usize,
}

impl CacheStats {
    /// Calculate hit rate as a percentage.
    pub fn hit_rate(&self) -> f64 {
        let total = self.hits + self.misses;
        if total == 0 {
            0.0
        } else {
            (self.hits as f64 / total as f64) * 100.0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn create_test_module(name: &str) -> ModuleDef {
        ModuleDef {
            name: name.to_string(),
            path: format!("{}.py", name),
            language: "python".to_string(),
            ..Default::default()
        }
    }

    #[test]
    fn test_cache_new() {
        let cache = ParseCache::new();
        assert!(cache.is_empty());
        assert_eq!(cache.version, CACHE_VERSION);
    }

    #[test]
    fn test_cache_insert_and_get() {
        let mut cache = ParseCache::new();
        let module = create_test_module("test");

        cache.insert("test.py".to_string(), "xxh3:abc123".to_string(), module);

        // Matching hash should return the module
        assert!(cache.get("test.py", "xxh3:abc123").is_some());

        // Non-matching hash should return None
        assert!(cache.get("test.py", "xxh3:different").is_none());

        // Non-existent file should return None
        assert!(cache.get("other.py", "xxh3:abc123").is_none());
    }

    #[test]
    fn test_cache_save_and_load() {
        let dir = TempDir::new().unwrap();
        let mut cache = ParseCache::new();

        cache.insert(
            "test.py".to_string(),
            "xxh3:abc123".to_string(),
            create_test_module("test"),
        );

        // Save
        cache.save(Some(".cache"), dir.path()).unwrap();

        // Load
        let loaded = ParseCache::load(Some(".cache"), dir.path());
        assert_eq!(loaded.len(), 1);
        assert!(loaded.get("test.py", "xxh3:abc123").is_some());
    }

    #[test]
    fn test_cache_prune() {
        let mut cache = ParseCache::new();

        cache.insert(
            "keep.py".to_string(),
            "xxh3:1".to_string(),
            create_test_module("keep"),
        );
        cache.insert(
            "remove.py".to_string(),
            "xxh3:2".to_string(),
            create_test_module("remove"),
        );

        let current: std::collections::HashSet<String> =
            ["keep.py".to_string()].into_iter().collect();
        cache.prune(&current);

        assert_eq!(cache.len(), 1);
        assert!(cache.get("keep.py", "xxh3:1").is_some());
        assert!(cache.get("remove.py", "xxh3:2").is_none());
    }

    #[test]
    fn test_cache_version_mismatch() {
        let dir = TempDir::new().unwrap();
        let cache_path = dir.path().join(".mu/cache/parse_cache.json");
        fs::create_dir_all(cache_path.parent().unwrap()).unwrap();

        // Write a cache with an old version
        let old_cache = r#"{"version": "0", "entries": {}}"#;
        fs::write(&cache_path, old_cache).unwrap();

        // Loading should return a fresh cache
        let loaded = ParseCache::load(None, dir.path());
        assert_eq!(loaded.version, CACHE_VERSION);
        assert!(loaded.is_empty());
    }

    #[test]
    fn test_cache_stats_hit_rate() {
        let mut stats = CacheStats::default();
        assert_eq!(stats.hit_rate(), 0.0);

        stats.hits = 7;
        stats.misses = 3;
        assert!((stats.hit_rate() - 70.0).abs() < 0.01);
    }
}
