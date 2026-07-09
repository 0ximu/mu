//! Index staleness detection.
//!
//! The graph silently rotting as code changes is the fastest way to lose a
//! user's trust: tools keep answering, just from yesterday's codebase. This
//! module gives a cheap "how many source files changed since the last
//! bootstrap" check (one scan + one stat per file, no hashing, no parsing).

use std::path::Path;
use std::time::UNIX_EPOCH;

/// Files changed since the index was built.
#[derive(Debug, Clone, Default)]
pub struct StalenessReport {
    /// Source files modified (or created) after indexed_at.
    pub stale_files: usize,
    /// Total supported source files seen by the scan.
    pub total_files: usize,
}

impl StalenessReport {
    pub fn is_stale(&self) -> bool {
        self.stale_files > 0
    }
}

/// Count supported source files under `root` modified after `indexed_at`
/// (unix seconds). Respects the same ignore patterns bootstrap uses.
pub fn check_staleness(
    root: &Path,
    indexed_at: u64,
    ignore_patterns: Vec<String>,
) -> anyhow::Result<StalenessReport> {
    let root_str = root.to_str().unwrap_or(".");
    let options = mu_core::scanner::ScanOptions::new()
        .with_ignore_patterns(ignore_patterns)
        .compute_hashes(false);

    let scan = mu_core::scanner::scan_with_options(root_str, options)
        .map_err(|e| anyhow::anyhow!("staleness scan failed: {}", e))?;

    let mut stale = 0usize;
    for file in &scan.files {
        let mtime = std::fs::metadata(root.join(&file.path))
            .and_then(|m| m.modified())
            .ok()
            .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
            .map(|d| d.as_secs())
            .unwrap_or(0);
        if mtime > indexed_at {
            stale += 1;
        }
    }

    Ok(StalenessReport {
        stale_files: stale,
        total_files: scan.files.len(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fresh_index_is_not_stale() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("a.py"), "def f():\n    pass\n").unwrap();
        // Index "built" in the future relative to the file's mtime.
        let now = std::time::SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let report = check_staleness(dir.path(), now + 10, vec![]).unwrap();
        assert_eq!(report.total_files, 1);
        assert_eq!(report.stale_files, 0);
        assert!(!report.is_stale());
    }

    #[test]
    fn test_modified_file_counts_as_stale() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("a.py"), "def f():\n    pass\n").unwrap();
        // Index "built" before the file existed.
        let report = check_staleness(dir.path(), 1, vec![]).unwrap();
        assert_eq!(report.stale_files, 1);
        assert!(report.is_stale());
    }

    #[test]
    fn test_unsupported_files_ignored() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("notes.txt"), "hello").unwrap();
        let report = check_staleness(dir.path(), 1, vec![]).unwrap();
        assert_eq!(report.total_files, 0);
        assert!(!report.is_stale());
    }
}
