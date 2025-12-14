//! Incremental embedding command - Generate and update embeddings for code nodes
//!
//! This command:
//! 1. Scans current file hashes using blake3
//! 2. Compares with stored hashes to find stale files
//! 3. Re-embeds only changed files
//! 4. Updates the hash table

use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::time::Instant;

use colored::Colorize;
use indicatif::{ProgressBar, ProgressStyle};
use serde::Serialize;

use crate::output::{Output, OutputFormat, TableDisplay};

/// Result of embed operation
#[derive(Debug, Serialize)]
pub struct EmbedResult {
    pub success: bool,
    pub total_files: usize,
    pub stale_files: usize,
    pub embedded_count: usize,
    pub skipped_count: usize,
    pub duration_ms: u64,
    pub was_incremental: bool,
}

impl TableDisplay for EmbedResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        if self.success {
            output.push_str(&format!(
                "{} Embeddings updated successfully\n",
                "SUCCESS:".green().bold()
            ));
        } else {
            output.push_str(&format!("{} Embedding failed\n", "ERROR:".red().bold()));
            return output;
        }

        output.push_str(&format!("\n{}\n", "Summary".cyan().bold()));
        output.push_str(&format!(
            "  Mode:       {}\n",
            if self.was_incremental {
                "incremental".yellow()
            } else {
                "full".green()
            }
        ));
        output.push_str(&format!(
            "  Duration:   {}ms\n",
            self.duration_ms.to_string().yellow()
        ));

        output.push_str(&format!("\n{}\n", "Files".cyan().bold()));
        output.push_str(&format!("  Total:      {}\n", self.total_files));
        output.push_str(&format!(
            "  Changed:    {}\n",
            self.stale_files.to_string().yellow()
        ));
        output.push_str(&format!(
            "  Embedded:   {}\n",
            self.embedded_count.to_string().green()
        ));
        output.push_str(&format!("  Skipped:    {}\n", self.skipped_count));

        output
    }

    fn to_mu(&self) -> String {
        format!(
            r#":: embed
# mode: {}
# total: {}
# stale: {}
# embedded: {}
# duration: {}ms"#,
            if self.was_incremental {
                "incremental"
            } else {
                "full"
            },
            self.total_files,
            self.stale_files,
            self.embedded_count,
            self.duration_ms
        )
    }
}

/// Result of embed status command
#[derive(Debug, Serialize)]
pub struct EmbedStatusResult {
    pub total_files: usize,
    pub embedded_files: usize,
    pub stale_files: usize,
    pub missing_files: usize,
    pub coverage_percent: f64,
    pub stale_file_list: Vec<String>,
}

impl TableDisplay for EmbedStatusResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!("{}\n", "Embedding Status".cyan().bold()));
        output.push_str(&format!("{}\n", "-".repeat(40).dimmed()));
        output.push_str(&format!(
            "  Total files:     {}\n",
            self.total_files.to_string().white()
        ));
        output.push_str(&format!(
            "  Embedded:        {}\n",
            self.embedded_files.to_string().green()
        ));
        output.push_str(&format!(
            "  Stale:           {}\n",
            if self.stale_files > 0 {
                self.stale_files.to_string().yellow()
            } else {
                self.stale_files.to_string().green()
            }
        ));
        output.push_str(&format!(
            "  Missing:         {}\n",
            if self.missing_files > 0 {
                self.missing_files.to_string().red()
            } else {
                self.missing_files.to_string().green()
            }
        ));
        output.push_str(&format!(
            "  Coverage:        {:.1}%\n",
            self.coverage_percent
        ));

        if !self.stale_file_list.is_empty() && self.stale_file_list.len() <= 10 {
            output.push_str(&format!("\n{}\n", "Stale Files".yellow().bold()));
            for file in &self.stale_file_list {
                output.push_str(&format!("  - {}\n", file));
            }
        } else if self.stale_file_list.len() > 10 {
            output.push_str(&format!(
                "\n{} {} stale files (run 'mu embed' to update)\n",
                "Note:".yellow().bold(),
                self.stale_file_list.len()
            ));
        }

        if self.stale_files > 0 || self.missing_files > 0 {
            output.push_str(&format!("\n{}\n", "Next Steps".cyan().bold()));
            output.push_str("  mu embed             # Update stale embeddings\n");
            output.push_str("  mu embed --force     # Rebuild all embeddings\n");
        }

        output
    }

    fn to_mu(&self) -> String {
        format!(
            r#":: embed-status
# total: {}
# embedded: {}
# stale: {}
# missing: {}
# coverage: {:.1}%"#,
            self.total_files,
            self.embedded_files,
            self.stale_files,
            self.missing_files,
            self.coverage_percent
        )
    }
}

/// Compute blake3 hash of a file's content
pub fn compute_file_hash(path: &Path) -> anyhow::Result<String> {
    let content = fs::read(path)?;
    Ok(blake3::hash(&content).to_hex().to_string())
}

/// Compute hashes for all files in scan result
pub fn compute_all_hashes(
    root: &Path,
    files: &[mu_core::scanner::ScannedFile],
) -> HashMap<String, String> {
    let mut hashes = HashMap::new();

    for file in files {
        let full_path = root.join(&file.path);
        if let Ok(hash) = compute_file_hash(&full_path) {
            hashes.insert(file.path.clone(), hash);
        }
    }

    hashes
}

/// Run incremental embedding update
pub async fn run_incremental(path: &str, force: bool, format: OutputFormat) -> anyhow::Result<()> {
    let start = Instant::now();

    // Resolve and canonicalize path
    let root = Path::new(path)
        .canonicalize()
        .unwrap_or_else(|_| Path::new(path).to_path_buf());

    if !root.exists() {
        anyhow::bail!("Path does not exist: {}", root.display());
    }

    // Check if mubase exists
    let mu_dir = root.join(".mu");
    let mubase_path = mu_dir.join("mubase");

    if !mubase_path.exists() {
        anyhow::bail!(
            "MU database not found. Run 'mu bootstrap' first.\n  Path: {}",
            mubase_path.display()
        );
    }

    // Show progress
    let spinner = ProgressBar::new_spinner();
    spinner.set_style(
        ProgressStyle::default_spinner()
            .tick_chars("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
            .template("{spinner:.cyan} {msg}")
            .unwrap(),
    );
    spinner.enable_steady_tick(std::time::Duration::from_millis(100));

    // Step 1: Scan current files
    spinner.set_message("Scanning files...");
    let root_str = root.to_str().unwrap_or(".");
    let scan_result =
        mu_core::scanner::scan_directory_sync(root_str, None, None, false, false, false)
            .map_err(|e| anyhow::anyhow!(e))?;

    let total_files = scan_result.files.len();

    if total_files == 0 {
        spinner.finish_and_clear();
        println!(
            "{} No supported files found in {}",
            "WARNING:".yellow().bold(),
            root.display()
        );
        return Ok(());
    }

    // Step 2: Compute current file hashes
    spinner.set_message("Computing file hashes...");
    let current_hashes = compute_all_hashes(&root, &scan_result.files);

    // Step 3: Open database and find stale files
    spinner.set_message("Checking for changes...");
    let mubase = mu_daemon::storage::MUbase::open(&mubase_path)?;

    let stale_files = if force {
        // Force mode: re-embed everything
        current_hashes.keys().cloned().collect::<Vec<_>>()
    } else {
        mubase.get_stale_files(&current_hashes)?
    };

    let stale_count = stale_files.len();

    if stale_count == 0 {
        spinner.finish_and_clear();

        let result = EmbedResult {
            success: true,
            total_files,
            stale_files: 0,
            embedded_count: 0,
            skipped_count: total_files,
            duration_ms: start.elapsed().as_millis() as u64,
            was_incremental: !force,
        };

        println!("{} All embeddings are up to date.", "INFO:".green().bold());
        Output::new(result, format).render()?;
        return Ok(());
    }

    spinner.set_message(format!("Found {} files to embed...", stale_count));

    // Step 4: Load embedding model
    spinner.set_message("Loading embedding model...");
    let model = match mu_embeddings::MuSigmaModel::embedded() {
        Ok(m) => m,
        Err(e) => {
            spinner.finish_and_clear();
            anyhow::bail!("Failed to load embedding model: {}", e);
        }
    };

    // Step 5: Get nodes for stale files and embed them
    spinner.set_message("Generating embeddings...");

    // Get nodes from the database that belong to stale files
    let mut embeddings_batch: Vec<(String, Vec<f32>, Option<String>)> = Vec::new();
    let mut embedded_count = 0;

    // Get all nodes and filter by file path
    let all_nodes_result = mubase.query(
        "SELECT id, type, name, qualified_name, file_path FROM nodes WHERE type != 'external'",
    )?;

    let stale_set: std::collections::HashSet<_> = stale_files.iter().cloned().collect();

    let nodes_to_embed: Vec<_> = all_nodes_result
        .rows
        .iter()
        .filter(|row| {
            if let Some(serde_json::Value::String(file_path)) = row.get(4) {
                stale_set.contains(file_path)
            } else {
                false
            }
        })
        .collect();

    let total_to_embed = nodes_to_embed.len();
    let batch_size = 32;

    for (batch_idx, batch) in nodes_to_embed.chunks(batch_size).enumerate() {
        spinner.set_message(format!(
            "Generating embeddings... {}/{}",
            (batch_idx * batch_size).min(total_to_embed),
            total_to_embed
        ));

        // Create text content for each node
        let mut node_ids: Vec<String> = Vec::new();
        let texts: Vec<String> = batch
            .iter()
            .map(|row| {
                let id = match row.get(0) {
                    Some(serde_json::Value::String(s)) => s.clone(),
                    _ => String::new(),
                };
                let type_str = match row.get(1) {
                    Some(serde_json::Value::String(s)) => s.as_str(),
                    _ => "node",
                };
                let name = match row.get(2) {
                    Some(serde_json::Value::String(s)) => s.clone(),
                    _ => String::new(),
                };
                let qualified_name = match row.get(3) {
                    Some(serde_json::Value::String(s)) => s.clone(),
                    _ => String::new(),
                };

                node_ids.push(id);
                format!("{} {} {}", type_str, name, qualified_name)
            })
            .collect();

        // Convert to &str slice for embedding
        let text_refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();

        match model.embed(&text_refs) {
            Ok(batch_embeddings) => {
                for ((node_id, text), embedding) in
                    node_ids.iter().zip(texts.iter()).zip(batch_embeddings)
                {
                    embeddings_batch.push((node_id.clone(), embedding, Some(text.clone())));
                    embedded_count += 1;
                }
            }
            Err(e) => {
                tracing::warn!("Failed to embed batch: {}", e);
            }
        }
    }

    // Step 6: Store embeddings
    if !embeddings_batch.is_empty() {
        spinner.set_message("Storing embeddings...");
        if let Err(e) = mubase.insert_embeddings_batch(&embeddings_batch, Some("mu-sigma-v2")) {
            tracing::warn!("Failed to store embeddings: {}", e);
        }
    }

    // Step 7: Update file hashes
    spinner.set_message("Updating file hashes...");
    let hash_updates: Vec<(String, String)> = stale_files
        .iter()
        .filter_map(|path| {
            current_hashes
                .get(path)
                .map(|hash| (path.clone(), hash.clone()))
        })
        .collect();

    if !hash_updates.is_empty() {
        mubase.set_file_hashes_batch(&hash_updates)?;
    }

    spinner.finish_and_clear();

    let duration_ms = start.elapsed().as_millis() as u64;

    let result = EmbedResult {
        success: true,
        total_files,
        stale_files: stale_count,
        embedded_count,
        skipped_count: total_files - stale_count,
        duration_ms,
        was_incremental: !force,
    };

    Output::new(result, format).render()
}

/// Show embedding status
pub async fn run_status(path: &str, format: OutputFormat) -> anyhow::Result<()> {
    // Resolve and canonicalize path
    let root = Path::new(path)
        .canonicalize()
        .unwrap_or_else(|_| Path::new(path).to_path_buf());

    if !root.exists() {
        anyhow::bail!("Path does not exist: {}", root.display());
    }

    // Check if mubase exists
    let mu_dir = root.join(".mu");
    let mubase_path = mu_dir.join("mubase");

    if !mubase_path.exists() {
        anyhow::bail!(
            "MU database not found. Run 'mu bootstrap' first.\n  Path: {}",
            mubase_path.display()
        );
    }

    // Scan current files
    let root_str = root.to_str().unwrap_or(".");
    let scan_result =
        mu_core::scanner::scan_directory_sync(root_str, None, None, false, false, false)
            .map_err(|e| anyhow::anyhow!(e))?;

    let total_files = scan_result.files.len();

    // Compute current file hashes
    let current_hashes = compute_all_hashes(&root, &scan_result.files);

    // Open database
    let mubase = mu_daemon::storage::MUbase::open(&mubase_path)?;

    // Get stored hashes and embedding stats
    let stored_hashes = mubase.get_all_file_hashes()?;
    let embedding_stats = mubase.embedding_stats()?;

    // Find stale and missing files
    let stale_files = mubase.get_stale_files(&current_hashes)?;

    // Files that have never been embedded (not in stored hashes)
    let missing_files: Vec<String> = current_hashes
        .keys()
        .filter(|path| !stored_hashes.contains_key(*path))
        .cloned()
        .collect();

    let embedded_files = stored_hashes.len();
    let stale_count = stale_files.len();
    let missing_count = missing_files.len();

    let coverage_percent = if total_files > 0 {
        (embedding_stats.nodes_with_embeddings as f64 / embedding_stats.total_nodes.max(1) as f64)
            * 100.0
    } else {
        0.0
    };

    let result = EmbedStatusResult {
        total_files,
        embedded_files,
        stale_files: stale_count,
        missing_files: missing_count,
        coverage_percent,
        stale_file_list: stale_files,
    };

    Output::new(result, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::tempdir;

    #[test]
    fn test_compute_file_hash() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.txt");

        let mut file = fs::File::create(&file_path).unwrap();
        file.write_all(b"hello world").unwrap();

        let hash = compute_file_hash(&file_path).unwrap();

        // Verify it's a valid hex string of correct length (blake3 produces 256-bit hash = 64 hex chars)
        assert_eq!(hash.len(), 64);
        assert!(hash.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn test_hash_changes_with_content() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.txt");

        // First content
        fs::write(&file_path, b"hello").unwrap();
        let hash1 = compute_file_hash(&file_path).unwrap();

        // Changed content
        fs::write(&file_path, b"world").unwrap();
        let hash2 = compute_file_hash(&file_path).unwrap();

        assert_ne!(hash1, hash2);
    }

    #[test]
    fn test_hash_same_for_same_content() {
        let dir = tempdir().unwrap();
        let file1 = dir.path().join("file1.txt");
        let file2 = dir.path().join("file2.txt");

        fs::write(&file1, b"same content").unwrap();
        fs::write(&file2, b"same content").unwrap();

        let hash1 = compute_file_hash(&file1).unwrap();
        let hash2 = compute_file_hash(&file2).unwrap();

        assert_eq!(hash1, hash2);
    }
}
