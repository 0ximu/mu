//! Shared utilities for finding MU database paths.
//!
//! This module provides functions to locate the MU database file (`.mu/mubase`)
//! by searching from a starting directory upward through parent directories.
//! Also supports legacy `.mubase` path for backwards compatibility.

use anyhow::Result;
use std::path::{Path, PathBuf};

/// MU directory name.
pub const MU_DIR: &str = ".mu";

/// MU database filename (inside .mu/).
pub const MUBASE_FILE: &str = "mubase";

/// Legacy database filename (deprecated, but still supported).
pub const LEGACY_MUBASE: &str = ".mubase";

/// Find the MU database by walking up from `start_path`.
///
/// Returns the path to the database file (`.mu/mubase` or legacy `.mubase`).
/// Returns an error if no database is found.
///
/// # Example
/// ```ignore
/// let db_path = find_mubase(".")?;
/// let store = NodeStore::open(db_path)?;
/// ```
pub fn find_mubase(start_path: &str) -> Result<PathBuf> {
    find_mubase_optional(start_path)
        .ok_or_else(|| anyhow::anyhow!("No MU database found. Run 'mu bootstrap' first."))
}

/// Find the MU database by walking up from `start_path`.
///
/// Returns `None` if no database is found.
pub fn find_mubase_optional(start_path: &str) -> Option<PathBuf> {
    let start = Path::new(start_path).canonicalize().ok()?;
    find_mubase_from(&start)
}

/// Find the MU database by walking up from `start_path`.
///
/// Takes a `&Path` instead of `&str` for convenience.
pub fn find_mubase_from(start: &Path) -> Option<PathBuf> {
    let mut current = start;

    loop {
        // Check in current directory
        if let Some(path) = find_mubase_in(current) {
            return Some(path);
        }

        // Move up to parent
        match current.parent() {
            Some(parent) => current = parent,
            None => return None,
        }
    }
}

/// Check for MU database in a specific directory (no traversal).
///
/// Returns `Some(path)` if found, `None` otherwise.
/// Checks both new path (`.mu/mubase`) and legacy path (`.mubase`).
pub fn find_mubase_in(root: &Path) -> Option<PathBuf> {
    // New standard path: .mu/mubase
    let new_path = root.join(MU_DIR).join(MUBASE_FILE);
    if new_path.exists() {
        return Some(new_path);
    }

    // Legacy path: .mubase
    let legacy_path = root.join(LEGACY_MUBASE);
    if legacy_path.exists() {
        return Some(legacy_path);
    }

    None
}

/// Get the MU directory path for a project root.
///
/// Returns `.mu` path without checking if it exists.
pub fn mu_dir(root: &Path) -> PathBuf {
    root.join(MU_DIR)
}

/// Get the MU database path for a project root.
///
/// Returns `.mu/mubase` path without checking if it exists.
pub fn mubase_path(root: &Path) -> PathBuf {
    mu_dir(root).join(MUBASE_FILE)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_find_mubase_in_new_path() {
        let dir = TempDir::new().unwrap();
        let mu_dir = dir.path().join(".mu");
        fs::create_dir_all(&mu_dir).unwrap();
        fs::write(mu_dir.join("mubase"), "").unwrap();

        let result = find_mubase_in(dir.path());
        assert!(result.is_some());
        assert!(result.unwrap().ends_with(".mu/mubase"));
    }

    #[test]
    fn test_find_mubase_in_legacy_path() {
        let dir = TempDir::new().unwrap();
        fs::write(dir.path().join(".mubase"), "").unwrap();

        let result = find_mubase_in(dir.path());
        assert!(result.is_some());
        assert!(result.unwrap().ends_with(".mubase"));
    }

    #[test]
    fn test_find_mubase_in_not_found() {
        let dir = TempDir::new().unwrap();
        let result = find_mubase_in(dir.path());
        assert!(result.is_none());
    }

    #[test]
    fn test_find_mubase_prefers_new_path() {
        let dir = TempDir::new().unwrap();

        // Create both paths
        let mu_dir = dir.path().join(".mu");
        fs::create_dir_all(&mu_dir).unwrap();
        fs::write(mu_dir.join("mubase"), "").unwrap();
        fs::write(dir.path().join(".mubase"), "").unwrap();

        // Should prefer .mu/mubase
        let result = find_mubase_in(dir.path());
        assert!(result.is_some());
        assert!(result.unwrap().ends_with(".mu/mubase"));
    }

    #[test]
    fn test_find_mubase_traverses_up() {
        let dir = TempDir::new().unwrap();

        // Create mubase in root
        let mu_dir = dir.path().join(".mu");
        fs::create_dir_all(&mu_dir).unwrap();
        fs::write(mu_dir.join("mubase"), "").unwrap();

        // Create nested directory
        let nested = dir.path().join("src").join("lib");
        fs::create_dir_all(&nested).unwrap();

        // Should find it from nested
        let result = find_mubase_from(&nested);
        assert!(result.is_some());
    }
}
