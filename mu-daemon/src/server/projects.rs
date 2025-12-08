//! Multi-project support for MU daemon.
//!
//! Manages multiple MUbase instances for different projects, routing requests
//! to the appropriate database based on the client's working directory.

use anyhow::{Context, Result};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{debug, info};

use crate::storage::{GraphEngine, MUbase};

/// Names of the MU data directory and database file.
const MU_DIR: &str = ".mu";
const MUBASE_FILE: &str = "mubase";

/// Manages multiple project databases for multi-project daemon mode.
///
/// Caches MUbase instances keyed by project root path.
/// Thread-safe via tokio RwLock.
pub struct ProjectManager {
    /// Default MUbase instance (the one the daemon started with)
    default_mubase: Arc<RwLock<MUbase>>,
    /// Default graph engine
    default_graph: Arc<RwLock<GraphEngine>>,
    /// Path to the default .mubase
    default_path: PathBuf,
    /// Root directory for the default project
    default_root: PathBuf,
    /// Cache of opened project databases: mubase_path -> (MUbase, GraphEngine)
    cache: RwLock<HashMap<PathBuf, (Arc<RwLock<MUbase>>, Arc<RwLock<GraphEngine>>)>>,
}

impl ProjectManager {
    /// Create a new ProjectManager with a default project.
    pub fn new(
        default_mubase: Arc<RwLock<MUbase>>,
        default_graph: Arc<RwLock<GraphEngine>>,
        default_path: PathBuf,
        default_root: PathBuf,
    ) -> Self {
        Self {
            default_mubase,
            default_graph,
            default_path: default_path.canonicalize().unwrap_or(default_path),
            default_root: default_root.canonicalize().unwrap_or(default_root),
            cache: RwLock::new(HashMap::new()),
        }
    }

    /// Get MUbase and GraphEngine for a working directory.
    ///
    /// If `cwd` is None, returns the default project.
    /// Otherwise, finds the nearest .mu/mubase for the cwd.
    pub async fn get_project(
        &self,
        cwd: Option<&str>,
    ) -> Result<(Arc<RwLock<MUbase>>, Arc<RwLock<GraphEngine>>, PathBuf)> {
        // No cwd specified - return default
        if cwd.is_none() {
            return Ok((
                self.default_mubase.clone(),
                self.default_graph.clone(),
                self.default_path.clone(),
            ));
        }

        let cwd_str = cwd.unwrap();
        let cwd_path = PathBuf::from(cwd_str);
        let cwd_path = cwd_path.canonicalize().unwrap_or(cwd_path);

        // Find nearest mubase
        let mubase_path = match find_mubase_for_path(&cwd_path) {
            Some(path) => path,
            None => {
                // No mubase found - return default
                debug!("No .mu/mubase found for {:?}, using default", cwd_path);
                return Ok((
                    self.default_mubase.clone(),
                    self.default_graph.clone(),
                    self.default_path.clone(),
                ));
            }
        };

        let mubase_path = mubase_path.canonicalize().unwrap_or(mubase_path);

        // Check if it's the default project
        if mubase_path == self.default_path {
            return Ok((
                self.default_mubase.clone(),
                self.default_graph.clone(),
                self.default_path.clone(),
            ));
        }

        // Check cache
        {
            let cache = self.cache.read().await;
            if let Some((mubase, graph)) = cache.get(&mubase_path) {
                return Ok((mubase.clone(), graph.clone(), mubase_path));
            }
        }

        // Open new MUbase for this project
        info!("Opening MUbase for project: {:?}", mubase_path);
        let mubase = MUbase::open(&mubase_path)
            .with_context(|| format!("Failed to open mubase: {:?}", mubase_path))?;

        let graph = mubase
            .load_graph()
            .with_context(|| format!("Failed to load graph from: {:?}", mubase_path))?;

        let mubase = Arc::new(RwLock::new(mubase));
        let graph = Arc::new(RwLock::new(graph));

        // Cache it
        {
            let mut cache = self.cache.write().await;
            cache.insert(mubase_path.clone(), (mubase.clone(), graph.clone()));
        }

        Ok((mubase, graph, mubase_path))
    }

    /// Get only the MUbase for a working directory.
    pub async fn get_mubase(&self, cwd: Option<&str>) -> Result<Arc<RwLock<MUbase>>> {
        let (mubase, _, _) = self.get_project(cwd).await?;
        Ok(mubase)
    }

    /// Get only the GraphEngine for a working directory.
    pub async fn get_graph(&self, cwd: Option<&str>) -> Result<Arc<RwLock<GraphEngine>>> {
        let (_, graph, _) = self.get_project(cwd).await?;
        Ok(graph)
    }

    /// Get the number of cached projects (including default).
    pub async fn project_count(&self) -> usize {
        let cache = self.cache.read().await;
        cache.len() + 1 // +1 for default
    }

    /// List all cached project paths.
    pub async fn list_projects(&self) -> Vec<String> {
        let cache = self.cache.read().await;
        let mut paths: Vec<String> = cache.keys().map(|p| p.display().to_string()).collect();
        paths.insert(0, self.default_path.display().to_string());
        paths
    }

    /// Get the default project root path.
    pub fn default_root(&self) -> &Path {
        &self.default_root
    }

    /// Get the default mubase path.
    pub fn default_path(&self) -> &Path {
        &self.default_path
    }
}

/// Find the nearest mubase file for a given path.
///
/// Walks up the directory tree from `path` looking for .mu/mubase.
fn find_mubase_for_path(path: &Path) -> Option<PathBuf> {
    let mut current = if path.is_file() {
        path.parent()?.to_path_buf()
    } else {
        path.to_path_buf()
    };

    loop {
        let mubase_path = current.join(MU_DIR).join(MUBASE_FILE);
        if mubase_path.exists() {
            return Some(mubase_path);
        }

        // Also check for legacy .mubase at root
        let legacy_path = current.join(".mubase");
        if legacy_path.exists() {
            return Some(legacy_path);
        }

        // Move up
        match current.parent() {
            Some(parent) if parent != current => {
                current = parent.to_path_buf();
            }
            _ => break,
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_find_mubase_for_path_not_found() {
        let dir = tempdir().unwrap();
        let result = find_mubase_for_path(dir.path());
        assert!(result.is_none());
    }

    #[test]
    fn test_find_mubase_for_path_found() {
        let dir = tempdir().unwrap();

        // Create .mu/mubase
        let mu_dir = dir.path().join(MU_DIR);
        std::fs::create_dir_all(&mu_dir).unwrap();
        let mubase_path = mu_dir.join(MUBASE_FILE);
        std::fs::write(&mubase_path, "").unwrap();

        // Search from subdirectory
        let subdir = dir.path().join("src").join("lib");
        std::fs::create_dir_all(&subdir).unwrap();

        let result = find_mubase_for_path(&subdir);
        assert!(result.is_some());
        assert_eq!(
            result.unwrap().canonicalize().unwrap(),
            mubase_path.canonicalize().unwrap()
        );
    }
}
