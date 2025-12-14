//! Search command - Semantic search across the codebase
//!
//! Uses mu-sigma-v2 (or all-MiniLM-L6-v2) embeddings to find
//! semantically similar code nodes to the query.

use std::path::Path;
use std::time::Instant;

use colored::Colorize;
use serde::{Deserialize, Serialize};

use crate::output::{Output, OutputFormat, TableDisplay};

/// Search result item
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    pub node_id: String,
    pub name: String,
    pub node_type: String,
    pub file_path: Option<String>,
    pub line_start: Option<usize>,
    pub similarity: f32,
}

/// Search results collection
#[derive(Debug, Serialize, Deserialize)]
pub struct SearchResults {
    pub query: String,
    pub results: Vec<SearchResult>,
    pub total_found: usize,
    pub has_embeddings: bool,
    #[serde(default)]
    pub duration_ms: u64,
}


impl TableDisplay for SearchResults {
    fn to_table(&self) -> String {
        let mut output = String::new();

        if !self.has_embeddings {
            output.push_str(&format!(
                "{} No embeddings found. Run '{}' first.\n\n",
                "WARNING:".yellow().bold(),
                "mu bootstrap --embed".cyan()
            ));
            output.push_str("Using keyword search fallback:\n\n");
        } else {
            output.push_str(&format!(
                "{} Semantic search: \"{}\"\n",
                "SEARCH:".cyan().bold(),
                self.query
            ));
            output.push_str(&format!(
                "Found {} results in {}ms\n\n",
                self.total_found.to_string().green(),
                self.duration_ms
            ));
        }

        if self.results.is_empty() {
            output.push_str(&format!("{}\n", "No results found.".dimmed()));
            return output;
        }

        // Format results as table
        for (i, result) in self.results.iter().enumerate() {
            let score_pct = (result.similarity * 100.0) as u32;
            let score_bar = "█".repeat((score_pct / 10) as usize);
            let score_color = if score_pct >= 70 {
                score_bar.green()
            } else if score_pct >= 40 {
                score_bar.yellow()
            } else {
                score_bar.red()
            };

            output.push_str(&format!(
                "{:2}. {} {} ({})\n",
                i + 1,
                result.name.cyan().bold(),
                format!("[{}]", result.node_type).dimmed(),
                format!("{}%", score_pct).to_string().as_str()
            ));

            output.push_str(&format!("    {} {}\n", "Score:".dimmed(), score_color));

            if let Some(ref file_path) = result.file_path {
                let location = if let Some(line) = result.line_start {
                    format!("{}:{}", file_path, line)
                } else {
                    file_path.clone()
                };
                output.push_str(&format!("    {} {}\n", "File:".dimmed(), location));
            }

            output.push('\n');
        }

        output.push_str(&format!(
            "{}\n",
            "Tip: Use 'mu read <node_id>' to view source code".dimmed()
        ));

        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();
        output.push_str(&format!(":: search \"{}\"\n", self.query));
        output.push_str(&format!("# results: {}\n", self.total_found));
        output.push_str(&format!("# duration: {}ms\n\n", self.duration_ms));

        for result in &self.results {
            let sigil = match result.node_type.as_str() {
                "module" => "!",
                "class" => "@",
                "function" => "$",
                _ => "#",
            };
            output.push_str(&format!(
                "{}{} [{}] score={:.2}\n",
                sigil, result.name, result.node_type, result.similarity
            ));
            if let Some(ref path) = result.file_path {
                output.push_str(&format!("  | {}\n", path));
            }
        }

        output
    }
}

/// Find the mubase path starting from the given directory
fn find_mubase_path(start_dir: &Path) -> Option<std::path::PathBuf> {
    let mut current = start_dir.to_path_buf();
    loop {
        let mubase_path = current.join(".mu").join("mubase");
        if mubase_path.exists() {
            return Some(mubase_path);
        }
        if !current.pop() {
            return None;
        }
    }
}

/// Run the search command
pub async fn run(
    query: &str,
    limit: usize,
    threshold: f32,
    format: OutputFormat,
) -> anyhow::Result<()> {
    // Validate query is not empty
    if query.trim().is_empty() {
        anyhow::bail!("Search query cannot be empty. Please provide a search term.");
    }

    let start = Instant::now();
    run_direct(query, limit, threshold, format, start).await
}

/// Run search directly against the database
async fn run_direct(
    query: &str,
    limit: usize,
    threshold: f32,
    format: OutputFormat,
    start: Instant,
) -> anyhow::Result<()> {
    // Find mubase
    let cwd = std::env::current_dir()?;
    let mubase_path = match find_mubase_path(&cwd) {
        Some(path) => path,
        None => {
            anyhow::bail!(
                "No .mu/mubase found. Run 'mu bootstrap' first to initialize MU for this project."
            );
        }
    };

    // Open database in read-only mode (search only reads, doesn't write)
    let mubase = mu_daemon::storage::MUbase::open_read_only(&mubase_path)?;

    // Check if we have embeddings
    let has_embeddings = mubase.has_embeddings()?;

    let results = if has_embeddings {
        // Semantic search path
        run_semantic_search(&mubase, query, limit, threshold)?
    } else {
        // Fallback to keyword search
        run_keyword_search(&mubase, query, limit)?
    };

    let duration_ms = start.elapsed().as_millis() as u64;

    let search_results = SearchResults {
        query: query.to_string(),
        total_found: results.len(),
        results,
        has_embeddings,
        duration_ms,
    };

    Output::new(search_results, format).render()
}

/// Run semantic search using embeddings
fn run_semantic_search(
    mubase: &mu_daemon::storage::MUbase,
    query: &str,
    limit: usize,
    threshold: f32,
) -> anyhow::Result<Vec<SearchResult>> {
    // Load the embedding model from embedded weights (zero-config)
    let model = mu_embeddings::MuSigmaModel::embedded()?;

    // Embed the query
    let query_embedding = model.embed_one(query)?;

    // Perform vector search
    let results = mubase.vector_search(&query_embedding, limit, Some(threshold))?;

    // Convert to SearchResult
    let search_results: Vec<SearchResult> = results
        .into_iter()
        .map(|result| SearchResult {
            node_id: result.node_id,
            name: result.name,
            node_type: result.node_type,
            file_path: result.file_path,
            line_start: None, // VectorSearchResult doesn't include line info
            similarity: result.similarity,
        })
        .collect();

    Ok(search_results)
}

/// Run keyword search (fallback when no embeddings)
fn run_keyword_search(
    mubase: &mu_daemon::storage::MUbase,
    query: &str,
    limit: usize,
) -> anyhow::Result<Vec<SearchResult>> {
    // Search by name pattern
    let sql = format!(
        r#"
        SELECT id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity
        FROM nodes
        WHERE LOWER(name) LIKE '%{}%'
           OR LOWER(qualified_name) LIKE '%{}%'
        ORDER BY
            CASE WHEN LOWER(name) LIKE '{}%' THEN 0 ELSE 1 END,
            complexity DESC
        LIMIT {}
        "#,
        query.to_lowercase().replace('\'', "''"),
        query.to_lowercase().replace('\'', "''"),
        query.to_lowercase().replace('\'', "''"),
        limit
    );

    let result = mubase.query(&sql)?;

    let search_results: Vec<SearchResult> = result
        .rows
        .iter()
        .map(|row| {
            let id = row
                .first()
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let node_type = row
                .get(1)
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let name = row
                .get(2)
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let file_path = row.get(4).and_then(|v| v.as_str()).map(|s| s.to_string());
            let line_start = row.get(5).and_then(|v| v.as_i64()).map(|n| n as usize);

            SearchResult {
                node_id: id,
                name,
                node_type,
                file_path,
                line_start,
                similarity: 1.0, // No real similarity for keyword search
            }
        })
        .collect();

    Ok(search_results)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_search_result_serialization() {
        let result = SearchResult {
            node_id: "fn:test.py:main".to_string(),
            name: "main".to_string(),
            node_type: "function".to_string(),
            file_path: Some("test.py".to_string()),
            line_start: Some(10),
            similarity: 0.85,
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("main"));
        assert!(json.contains("0.85"));
    }
}
