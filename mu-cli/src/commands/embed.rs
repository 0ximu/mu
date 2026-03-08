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

/// Max characters for embedding text input.
const EMBED_TEXT_MAX_CHARS: usize = 400;

/// Extract source code lines from a file on disk.
fn extract_source(
    project_root: &Path,
    file_path: &str,
    line_start: Option<u32>,
    line_end: Option<u32>,
) -> Option<String> {
    let full_path = project_root.join(file_path);
    let content = fs::read_to_string(&full_path).ok()?;

    match (line_start, line_end) {
        (Some(start), Some(end)) => {
            let lines: Vec<&str> = content.lines().collect();
            let start_idx = (start.saturating_sub(1) as usize).min(lines.len());
            let end_idx = (end as usize).min(lines.len());
            if start_idx < end_idx {
                Some(lines[start_idx..end_idx].join("\n"))
            } else {
                None
            }
        }
        (Some(start), None) => {
            let lines: Vec<&str> = content.lines().collect();
            let start_idx = (start.saturating_sub(1) as usize).min(lines.len());
            if start_idx < lines.len() {
                Some(lines[start_idx..].join("\n"))
            } else {
                None
            }
        }
        _ => None,
    }
}

/// Build rich text for embedding a node.
///
/// Priority: docstring (up to 100 chars) + source (remainder), capped at EMBED_TEXT_MAX_CHARS.
/// Falls back to "{type} {name} {qualified_name}" when source is unavailable.
fn build_embedding_text(
    project_root: &Path,
    type_str: &str,
    name: &str,
    qualified_name: &str,
    file_path: Option<&str>,
    line_start: Option<u32>,
    line_end: Option<u32>,
    properties_json: Option<&str>,
) -> String {
    // Try to extract docstring from properties
    let docstring = properties_json.and_then(|p| {
        serde_json::from_str::<serde_json::Value>(p)
            .ok()
            .and_then(|v| v.get("docstring")?.as_str().map(|s| s.to_string()))
    });

    // Try to extract source from file
    let source = file_path.and_then(|fp| extract_source(project_root, fp, line_start, line_end));

    let header = format!("{} {}\n", type_str, name);

    match (docstring, source) {
        (Some(doc), Some(src)) => {
            let doc_budget = 100usize.min(EMBED_TEXT_MAX_CHARS.saturating_sub(header.len()));
            let doc_truncated: String = doc.chars().take(doc_budget).collect();
            let remaining = EMBED_TEXT_MAX_CHARS
                .saturating_sub(header.len())
                .saturating_sub(doc_truncated.len())
                .saturating_sub(1); // newline between doc and src
            let src_truncated: String = src.chars().take(remaining).collect();
            let mut text = header;
            text.push_str(&doc_truncated);
            text.push('\n');
            text.push_str(&src_truncated);
            text
        }
        (None, Some(src)) => {
            let src_budget = EMBED_TEXT_MAX_CHARS.saturating_sub(header.len());
            let src_truncated: String = src.chars().take(src_budget).collect();
            let mut text = header;
            text.push_str(&src_truncated);
            text
        }
        (Some(doc), None) => {
            let doc_budget = EMBED_TEXT_MAX_CHARS.saturating_sub(header.len());
            let doc_truncated: String = doc.chars().take(doc_budget).collect();
            let mut text = header;
            text.push_str(&doc_truncated);
            text
        }
        (None, None) => {
            // Fallback: metadata only
            format!("{} {} {}", type_str, name, qualified_name)
        }
    }
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
        "SELECT id, type, name, qualified_name, file_path, line_start, line_end, properties FROM nodes WHERE type != 'external'",
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

        // Create text content for each node using source code
        let mut node_ids: Vec<String> = Vec::new();
        let texts: Vec<String> = batch
            .iter()
            .map(|row| {
                let id = match row.first() {
                    Some(serde_json::Value::String(s)) => s.clone(),
                    _ => String::new(),
                };
                let type_str = match row.get(1) {
                    Some(serde_json::Value::String(s)) => s.as_str(),
                    _ => "node",
                };
                let name = match row.get(2) {
                    Some(serde_json::Value::String(s)) => s.as_str(),
                    _ => "",
                };
                let qualified_name = match row.get(3) {
                    Some(serde_json::Value::String(s)) => s.as_str(),
                    _ => "",
                };
                let file_path = match row.get(4) {
                    Some(serde_json::Value::String(s)) => Some(s.as_str()),
                    _ => None,
                };
                let line_start = match row.get(5) {
                    Some(serde_json::Value::Number(n)) => n.as_u64().map(|v| v as u32),
                    _ => None,
                };
                let line_end = match row.get(6) {
                    Some(serde_json::Value::Number(n)) => n.as_u64().map(|v| v as u32),
                    _ => None,
                };
                let properties = match row.get(7) {
                    Some(serde_json::Value::String(s)) => Some(s.as_str()),
                    _ => None,
                };

                node_ids.push(id);
                build_embedding_text(
                    &root,
                    type_str,
                    name,
                    qualified_name,
                    file_path,
                    line_start,
                    line_end,
                    properties,
                )
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

    #[test]
    fn test_extract_source_missing_file() {
        let dir = tempdir().unwrap();
        let result = extract_source(dir.path(), "nonexistent.rs", Some(1), Some(5));
        assert!(result.is_none());
    }

    #[test]
    fn test_extract_source_line_range() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.rs");
        fs::write(&file_path, "line1\nline2\nline3\nline4\nline5\n").unwrap();

        let result = extract_source(dir.path(), "test.rs", Some(2), Some(4));
        assert_eq!(result, Some("line2\nline3\nline4".to_string()));
    }

    #[test]
    fn test_extract_source_out_of_range() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.rs");
        fs::write(&file_path, "line1\nline2\n").unwrap();

        // start beyond file length
        let result = extract_source(dir.path(), "test.rs", Some(100), Some(200));
        assert!(result.is_none());
    }

    #[test]
    fn test_extract_source_no_lines_returns_none() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.rs");
        fs::write(&file_path, "line1\nline2\n").unwrap();

        // No line range and no start = None (we don't return entire file for embedding)
        let result = extract_source(dir.path(), "test.rs", None, None);
        assert!(result.is_none());
    }

    #[test]
    fn test_build_embedding_text_with_source() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.rs");
        fs::write(&file_path, "fn hello() {\n    println!(\"hi\");\n}\n").unwrap();

        let text = build_embedding_text(
            dir.path(),
            "function",
            "hello",
            "mod::hello",
            Some("test.rs"),
            Some(1),
            Some(3),
            None,
        );

        assert!(text.starts_with("function hello\n"));
        assert!(text.contains("fn hello()"));
    }

    #[test]
    fn test_build_embedding_text_truncated_to_max() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("big.rs");
        let big_content = "x".repeat(1000);
        fs::write(&file_path, &big_content).unwrap();

        let text = build_embedding_text(
            dir.path(),
            "function",
            "big_fn",
            "mod::big_fn",
            Some("big.rs"),
            Some(1),
            Some(1),
            None,
        );

        assert!(text.len() <= EMBED_TEXT_MAX_CHARS);
    }

    #[test]
    fn test_build_embedding_text_fallback_no_source() {
        let dir = tempdir().unwrap();
        // No file on disk
        let text = build_embedding_text(
            dir.path(),
            "function",
            "orphan",
            "mod::orphan",
            Some("missing.rs"),
            Some(1),
            Some(5),
            None,
        );

        assert_eq!(text, "function orphan mod::orphan");
    }

    #[test]
    fn test_build_embedding_text_with_docstring_and_source() {
        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.rs");
        fs::write(&file_path, "fn greet() {\n    println!(\"hi\");\n}\n").unwrap();

        let props = r#"{"docstring": "Greets the user politely"}"#;
        let text = build_embedding_text(
            dir.path(),
            "function",
            "greet",
            "mod::greet",
            Some("test.rs"),
            Some(1),
            Some(3),
            Some(props),
        );

        assert!(text.starts_with("function greet\n"));
        assert!(text.contains("Greets the user politely"));
        assert!(text.contains("fn greet()"));
        assert!(text.len() <= EMBED_TEXT_MAX_CHARS);
    }
}
