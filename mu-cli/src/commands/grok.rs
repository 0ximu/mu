//! Grok command - Extract relevant context for LLM comprehension
//!
//! Uses semantic search to find relevant code nodes and extracts context
//! in a token-efficient MU format optimized for LLMs.

use std::collections::HashSet;
use std::fs;
use std::path::Path;
use std::time::Instant;

use colored::Colorize;
use serde::Serialize;

use crate::output::{Output, OutputFormat, TableDisplay};

/// Context item containing code snippet
#[derive(Debug, Clone, Serialize)]
pub struct GrokContext {
    pub node_id: String,
    pub name: String,
    pub node_type: String,
    pub file_path: Option<String>,
    pub line_start: Option<usize>,
    pub line_end: Option<usize>,
    pub similarity: f32,
    pub source_code: Option<String>,
    pub dependencies: Vec<String>,
}

/// Search method used for context extraction
#[derive(Debug, Clone, Copy, Serialize, PartialEq)]
pub enum SearchMethod {
    /// Semantic search using embeddings
    Semantic,
    /// Keyword-based search (fallback)
    Keyword,
}

/// Grok result collection
#[derive(Debug, Serialize)]
pub struct GrokResult {
    pub question: String,
    pub contexts: Vec<GrokContext>,
    pub total_nodes: usize,
    pub depth: u8,
    pub has_embeddings: bool,
    pub search_method: SearchMethod,
    pub duration_ms: u64,
    pub total_lines: usize,
}

impl TableDisplay for GrokResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        // Show search method info
        match self.search_method {
            SearchMethod::Keyword => {
                output.push_str(&format!(
                    "{} Using keyword search (run '{}' for better semantic results).\n\n",
                    "NOTE:".yellow().bold(),
                    "mu embed".cyan()
                ));
            }
            SearchMethod::Semantic => {
                // No warning needed for semantic search
            }
        }

        output.push_str(&format!(
            "{} {}\n",
            "QUESTION:".cyan().bold(),
            self.question.bright_white()
        ));
        output.push_str(&format!(
            "Found {} relevant contexts ({} total lines) in {}ms\n\n",
            self.total_nodes.to_string().green(),
            self.total_lines.to_string().yellow(),
            self.duration_ms
        ));

        if self.contexts.is_empty() {
            output.push_str(&format!("{}\n", "No relevant context found.".dimmed()));
            return output;
        }

        output.push_str(&format!("{}\n\n", "CONTEXT:".cyan().bold()));

        for (i, ctx) in self.contexts.iter().enumerate() {
            let score_pct = (ctx.similarity * 100.0) as u32;
            let score_color = if score_pct >= 70 {
                format!("{}%", score_pct).green()
            } else if score_pct >= 40 {
                format!("{}%", score_pct).yellow()
            } else {
                format!("{}%", score_pct).red()
            };

            output.push_str(&format!(
                "{}. {} {} {} {}\n",
                i + 1,
                ctx.name.cyan().bold(),
                format!("[{}]", ctx.node_type).dimmed(),
                "·".dimmed(),
                score_color
            ));

            if let Some(ref file_path) = ctx.file_path {
                let location = if let (Some(start), Some(end)) = (ctx.line_start, ctx.line_end) {
                    format!("{}:{}-{}", file_path, start, end)
                } else if let Some(start) = ctx.line_start {
                    format!("{}:{}", file_path, start)
                } else {
                    file_path.clone()
                };
                output.push_str(&format!("   {} {}\n", "Location:".dimmed(), location));
            }

            if !ctx.dependencies.is_empty() {
                output.push_str(&format!(
                    "   {} {}\n",
                    "Dependencies:".dimmed(),
                    ctx.dependencies.join(", ")
                ));
            }

            if let Some(ref code) = ctx.source_code {
                let lines: Vec<&str> = code.lines().collect();
                let preview_lines = if lines.len() > 10 {
                    &lines[0..10]
                } else {
                    &lines[..]
                };

                output.push_str(&format!("   {}\n", "Code:".dimmed()));
                for line in preview_lines {
                    output.push_str(&format!("   {} {}\n", "│".dimmed(), line));
                }

                if lines.len() > 10 {
                    output.push_str(&format!(
                        "   {} ... {} more lines\n",
                        "│".dimmed(),
                        lines.len() - 10
                    ));
                }
            }

            output.push('\n');
        }

        output.push_str(&format!(
            "{}\n",
            "Tip: Use '--format mu' for LLM-optimized output".dimmed()
        ));

        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();

        // Header
        output.push_str(&format!(":: grok \"{}\"\n", self.question));
        output.push_str(&format!("# contexts: {}\n", self.total_nodes));
        output.push_str(&format!("# depth: {}\n", self.depth));
        output.push_str(&format!("# lines: {}\n", self.total_lines));
        let method_str = match self.search_method {
            SearchMethod::Semantic => "semantic",
            SearchMethod::Keyword => "keyword",
        };
        output.push_str(&format!("# search: {}\n", method_str));
        output.push_str(&format!("# duration: {}ms\n\n", self.duration_ms));

        // Context sections
        for ctx in &self.contexts {
            let sigil = match ctx.node_type.as_str() {
                "module" => "!",
                "class" => "@",
                "function" => "$",
                _ => "#",
            };

            // Node header with metadata
            output.push_str(&format!(
                "{}{} [{}] score={:.2}\n",
                sigil, ctx.name, ctx.node_type, ctx.similarity
            ));

            if let Some(ref path) = ctx.file_path {
                let location = if let (Some(start), Some(end)) = (ctx.line_start, ctx.line_end) {
                    format!("{}:{}-{}", path, start, end)
                } else if let Some(start) = ctx.line_start {
                    format!("{}:{}", path, start)
                } else {
                    path.clone()
                };
                output.push_str(&format!("  | {}\n", location));
            }

            // Dependencies
            if !ctx.dependencies.is_empty() {
                output.push_str("  | deps:\n");
                for dep in &ctx.dependencies {
                    output.push_str(&format!("  |   & {}\n", dep));
                }
            }

            // Source code (token-efficient, no line numbers)
            if let Some(ref code) = ctx.source_code {
                output.push_str("  |\n");
                for line in code.lines() {
                    // Skip empty lines to save tokens
                    if !line.trim().is_empty() {
                        output.push_str(&format!("  | {}\n", line));
                    }
                }
            }

            output.push('\n');
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

/// Find the project root (where .mu directory is located)
fn find_project_root(start_dir: &Path) -> Option<std::path::PathBuf> {
    let mut current = start_dir.to_path_buf();
    loop {
        let mu_dir = current.join(".mu");
        if mu_dir.exists() {
            return Some(current);
        }
        if !current.pop() {
            return None;
        }
    }
}

/// Extract source code from file given line range
fn extract_source_code(
    project_root: &Path,
    file_path: &str,
    line_start: Option<u32>,
    line_end: Option<u32>,
) -> Option<String> {
    let full_path = project_root.join(file_path);
    let content = fs::read_to_string(&full_path).ok()?;

    match (line_start, line_end) {
        (Some(start), Some(end)) => {
            // Extract specific line range
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
            // Extract from start to end of file
            let lines: Vec<&str> = content.lines().collect();
            let start_idx = (start.saturating_sub(1) as usize).min(lines.len());

            if start_idx < lines.len() {
                Some(lines[start_idx..].join("\n"))
            } else {
                None
            }
        }
        _ => {
            // Return entire file (for modules)
            Some(content)
        }
    }
}

/// Get dependencies for a node
fn get_node_dependencies(
    mubase: &mu_daemon::storage::MUbase,
    node_id: &str,
) -> anyhow::Result<Vec<String>> {
    let sql = format!(
        r#"
        SELECT DISTINCT n.name
        FROM edges e
        JOIN nodes n ON e.target_id = n.id
        WHERE e.source_id = '{}'
          AND e.type IN ('imports', 'calls', 'uses')
        LIMIT 5
        "#,
        node_id.replace('\'', "''")
    );

    let result = mubase.query(&sql)?;
    let deps: Vec<String> = result
        .rows
        .iter()
        .filter_map(|row| row.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect();

    Ok(deps)
}

/// Get related nodes based on depth (transitive dependencies)
fn get_related_nodes(
    mubase: &mu_daemon::storage::MUbase,
    initial_node_ids: &[String],
    depth: u8,
) -> anyhow::Result<Vec<String>> {
    if depth == 0 {
        return Ok(initial_node_ids.to_vec());
    }

    let mut all_nodes: HashSet<String> = initial_node_ids.iter().cloned().collect();
    let mut frontier: Vec<String> = initial_node_ids.to_vec();

    for _ in 0..depth {
        if frontier.is_empty() {
            break;
        }

        let mut next_frontier = Vec::new();

        for node_id in &frontier {
            // Get immediate dependencies
            let deps = get_node_dependencies(mubase, node_id)?;

            for dep in deps {
                // Get the full node ID for the dependency by name
                let sql = format!(
                    r#"
                    SELECT id
                    FROM nodes
                    WHERE name = '{}'
                    LIMIT 1
                    "#,
                    dep.replace('\'', "''")
                );

                let result = mubase.query(&sql)?;
                if let Some(row) = result.rows.first() {
                    if let Some(dep_id) = row.first().and_then(|v| v.as_str()) {
                        let dep_id_str = dep_id.to_string();
                        if all_nodes.insert(dep_id_str.clone()) {
                            next_frontier.push(dep_id_str);
                        }
                    }
                }
            }
        }

        frontier = next_frontier;
    }

    Ok(all_nodes.into_iter().collect())
}

/// Run the grok command
pub async fn run(question: &str, depth: u8, format: OutputFormat) -> anyhow::Result<()> {
    // Validate question is not empty
    if question.trim().is_empty() {
        anyhow::bail!("Question cannot be empty. Please provide a question or topic.");
    }

    let start = Instant::now();

    // Validate depth
    let depth = depth.clamp(1, 3);

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

    let project_root = match find_project_root(&cwd) {
        Some(path) => path,
        None => {
            anyhow::bail!("Could not determine project root. Ensure .mu directory exists.");
        }
    };

    // Open database in read-only mode (grok only reads, doesn't write)
    let mubase = mu_daemon::storage::MUbase::open_read_only(&mubase_path)?;

    // Check if we have embeddings
    let has_embeddings = mubase.has_embeddings()?;

    // Get initial relevant nodes - try semantic search first, fall back to keywords
    let (initial_results, search_method) = if has_embeddings {
        let results = run_semantic_search(&mubase, question, 5)?;
        if results.is_empty() {
            // Semantic search returned nothing, fall back to keyword search
            (
                run_keyword_search(&mubase, question, 10)?,
                SearchMethod::Keyword,
            )
        } else {
            (results, SearchMethod::Semantic)
        }
    } else {
        // No embeddings available, use keyword search
        (
            run_keyword_search(&mubase, question, 10)?,
            SearchMethod::Keyword,
        )
    };

    if initial_results.is_empty() {
        let duration_ms = start.elapsed().as_millis() as u64;
        let result = GrokResult {
            question: question.to_string(),
            contexts: Vec::new(),
            total_nodes: 0,
            depth,
            has_embeddings,
            search_method,
            duration_ms,
            total_lines: 0,
        };

        return Output::new(result, format).render();
    }

    // Extract node IDs from initial results
    let initial_node_ids: Vec<String> = initial_results
        .iter()
        .map(|result| result.node_id.clone())
        .collect();

    // Get related nodes based on depth
    let all_node_ids = if depth > 1 {
        get_related_nodes(&mubase, &initial_node_ids, depth - 1)?
    } else {
        initial_node_ids.clone()
    };

    // Fetch full node information for all related nodes
    let mut contexts = Vec::new();
    let mut total_lines = 0;

    for node_id in &all_node_ids {
        if let Some(node) = mubase.get_node(node_id)? {
            // Find similarity score (if this was an initial result)
            let similarity = initial_results
                .iter()
                .find(|r| &r.node_id == node_id)
                .map(|r| r.similarity)
                .unwrap_or(0.5); // Default similarity for transitive nodes

            // Extract source code
            let source_code = if let Some(ref file_path) = node.file_path {
                extract_source_code(&project_root, file_path, node.line_start, node.line_end)
            } else {
                None
            };

            // Count lines
            if let Some(ref code) = source_code {
                total_lines += code.lines().count();
            }

            // Get dependencies
            let dependencies = get_node_dependencies(&mubase, &node.id).unwrap_or_default();

            contexts.push(GrokContext {
                node_id: node.id,
                name: node.name,
                node_type: node.node_type.to_string(),
                file_path: node.file_path,
                line_start: node.line_start.map(|l| l as usize),
                line_end: node.line_end.map(|l| l as usize),
                similarity,
                source_code,
                dependencies,
            });
        }
    }

    // Sort by similarity (highest first)
    contexts.sort_by(|a, b| {
        b.similarity
            .partial_cmp(&a.similarity)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let duration_ms = start.elapsed().as_millis() as u64;

    let result = GrokResult {
        question: question.to_string(),
        total_nodes: contexts.len(),
        contexts,
        depth,
        has_embeddings,
        search_method,
        duration_ms,
        total_lines,
    };

    Output::new(result, format).render()
}

/// Run semantic search using embeddings
fn run_semantic_search(
    mubase: &mu_daemon::storage::MUbase,
    query: &str,
    limit: usize,
) -> anyhow::Result<Vec<mu_daemon::storage::VectorSearchResult>> {
    // Load the embedding model from embedded weights (zero-config)
    let model = mu_embeddings::MuSigmaModel::embedded()?;

    // Embed the query
    let query_embedding = model.embed_one(query)?;

    // Perform vector search with lower threshold for broader context
    let results = mubase.vector_search(&query_embedding, limit, Some(0.1))?;

    Ok(results)
}

/// Extract keywords from a natural language question
///
/// Filters out common stop words and extracts likely code identifiers.
fn extract_keywords(question: &str) -> Vec<String> {
    const STOP_WORDS: &[&str] = &[
        "what",
        "does",
        "do",
        "how",
        "the",
        "a",
        "an",
        "is",
        "are",
        "this",
        "that",
        "it",
        "to",
        "for",
        "in",
        "on",
        "of",
        "and",
        "or",
        "can",
        "could",
        "would",
        "should",
        "will",
        "why",
        "where",
        "when",
        "which",
        "who",
        "there",
        "here",
        "with",
        "from",
        "by",
        "about",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "then",
        "once",
        "any",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "also",
        "now",
        "use",
        "uses",
        "used",
        "using",
        "work",
        "works",
        "working",
        "call",
        "calls",
        "called",
        "get",
        "gets",
        "getting",
        "set",
        "sets",
        "setting",
        "find",
        "finds",
        "finding",
        "make",
        "makes",
        "making",
        "take",
        "takes",
        "taking",
        "show",
        "shows",
        "showing",
        "help",
        "helps",
        "code",
        "function",
        "method",
        "class",
        "module",
        "file",
        "files",
        "implement",
        "implements",
    ];

    question
        .split(|c: char| !c.is_alphanumeric() && c != '_')
        .filter(|w| w.len() > 2)
        .filter(|w| !STOP_WORDS.contains(&w.to_lowercase().as_str()))
        .map(|w| w.to_string())
        .collect()
}

/// Run keyword search (fallback when no embeddings)
///
/// Extracts keywords from the query and searches for nodes matching any keyword.
/// Uses a scoring system to rank results by how many keywords match.
fn run_keyword_search(
    mubase: &mu_daemon::storage::MUbase,
    query: &str,
    limit: usize,
) -> anyhow::Result<Vec<mu_daemon::storage::VectorSearchResult>> {
    let keywords = extract_keywords(query);

    if keywords.is_empty() {
        // No keywords extracted, return empty results
        return Ok(vec![]);
    }

    // Build OR conditions for each keyword
    let conditions: Vec<String> = keywords
        .iter()
        .map(|k| {
            let escaped = k.to_lowercase().replace('\'', "''");
            format!(
                "(LOWER(name) LIKE '%{0}%' OR LOWER(qualified_name) LIKE '%{0}%' OR LOWER(file_path) LIKE '%{0}%')",
                escaped
            )
        })
        .collect();

    // Build a scoring expression - nodes that match more keywords rank higher
    let score_expr: Vec<String> = keywords
        .iter()
        .map(|k| {
            let escaped = k.to_lowercase().replace('\'', "''");
            format!(
                "CASE WHEN LOWER(name) LIKE '%{0}%' THEN 2 ELSE 0 END + CASE WHEN LOWER(qualified_name) LIKE '%{0}%' THEN 1 ELSE 0 END",
                escaped
            )
        })
        .collect();

    let sql = format!(
        r#"
        SELECT id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity,
               ({}) as match_score
        FROM nodes
        WHERE {}
        ORDER BY match_score DESC, complexity DESC
        LIMIT {}
        "#,
        score_expr.join(" + "),
        conditions.join(" OR "),
        limit
    );

    let result = mubase.query(&sql)?;

    // Maximum possible score for normalization
    let max_score = (keywords.len() * 3) as f32; // 2 for name + 1 for qualified_name per keyword

    let results: Vec<mu_daemon::storage::VectorSearchResult> = result
        .rows
        .iter()
        .map(|row| {
            let node_id = row
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
            let qualified_name = row.get(3).and_then(|v| v.as_str()).map(|s| s.to_string());
            let file_path = row.get(4).and_then(|v| v.as_str()).map(|s| s.to_string());

            // Extract match_score from the query results (last column)
            let match_score = row.get(9).and_then(|v| v.as_i64()).unwrap_or(1) as f32;

            // Normalize to 0.0-1.0 range (cap at 1.0)
            let similarity = (match_score / max_score).min(1.0);

            mu_daemon::storage::VectorSearchResult {
                node_id,
                similarity,
                name,
                node_type,
                file_path,
                qualified_name,
            }
        })
        .collect();

    Ok(results)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_source_code_with_range() {
        use std::io::Write;
        use tempfile::tempdir;

        let dir = tempdir().unwrap();
        let file_path = dir.path().join("test.py");
        let mut file = std::fs::File::create(&file_path).unwrap();
        writeln!(file, "line 1").unwrap();
        writeln!(file, "line 2").unwrap();
        writeln!(file, "line 3").unwrap();
        writeln!(file, "line 4").unwrap();
        writeln!(file, "line 5").unwrap();

        let code = extract_source_code(dir.path(), "test.py", Some(2), Some(4));
        assert!(code.is_some());
        let code = code.unwrap();
        // Line range is inclusive: lines 2, 3, 4
        assert!(code.contains("line 2"));
        assert!(code.contains("line 3"));
        assert!(code.contains("line 4"));
        assert!(!code.contains("line 5"));
    }

    #[test]
    fn test_grok_result_serialization() {
        let result = GrokResult {
            question: "test question".to_string(),
            contexts: Vec::new(),
            total_nodes: 0,
            depth: 2,
            has_embeddings: true,
            search_method: SearchMethod::Semantic,
            duration_ms: 100,
            total_lines: 0,
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("test question"));
        assert!(json.contains("\"depth\":2"));
    }

    #[test]
    fn test_extract_keywords() {
        // Test basic extraction
        let keywords = extract_keywords("What does the Parser do?");
        assert!(keywords.contains(&"Parser".to_string()));
        assert!(!keywords.iter().any(|k| k.to_lowercase() == "what"));
        assert!(!keywords.iter().any(|k| k.to_lowercase() == "does"));
        assert!(!keywords.iter().any(|k| k.to_lowercase() == "the"));

        // Test with underscore identifiers
        let keywords = extract_keywords("How does run_semantic_search work?");
        assert!(keywords.contains(&"run_semantic_search".to_string()));

        // Test with multiple identifiers
        let keywords =
            extract_keywords("What is the relationship between MUbase and VectorSearchResult?");
        assert!(keywords.contains(&"MUbase".to_string()));
        assert!(keywords.contains(&"VectorSearchResult".to_string()));

        // Test that short words are filtered
        let keywords = extract_keywords("a b ab ABC");
        assert!(!keywords.contains(&"a".to_string()));
        assert!(!keywords.contains(&"b".to_string()));
        assert!(!keywords.contains(&"ab".to_string()));
        assert!(keywords.contains(&"ABC".to_string()));
    }

    #[test]
    fn test_search_method_serialization() {
        let semantic = SearchMethod::Semantic;
        let keyword = SearchMethod::Keyword;

        let json = serde_json::to_string(&semantic).unwrap();
        assert!(json.contains("Semantic"));

        let json = serde_json::to_string(&keyword).unwrap();
        assert!(json.contains("Keyword"));
    }
}
