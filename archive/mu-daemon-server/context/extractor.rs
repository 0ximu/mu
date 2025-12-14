//! Smart context extractor implementation.

use anyhow::Result;
use std::collections::{HashMap, HashSet};

use crate::server::AppState;
use crate::storage::NodeType;

/// Result of context extraction.
#[derive(Debug, Clone)]
pub struct ContextResult {
    /// MU format output
    pub mu_output: String,
    /// List of relevant node IDs
    pub nodes: Vec<String>,
    /// Estimated token count
    pub tokens: usize,
}

/// Extractor for smart context based on questions.
pub struct ContextExtractor<'a> {
    state: &'a AppState,
}

impl<'a> ContextExtractor<'a> {
    /// Create a new context extractor.
    pub fn new(state: &'a AppState) -> Self {
        Self { state }
    }

    /// Extract context relevant to a question.
    pub async fn extract(&self, question: &str, max_tokens: usize) -> Result<ContextResult> {
        // 1. Extract entities from the question
        let entities = self.extract_entities(question);

        // 2. Find matching nodes
        let seed_nodes = self.find_nodes(&entities).await?;

        // 3. Expand context via graph traversal
        let expanded = self.expand_context(&seed_nodes, max_tokens / 2).await?;

        // 4. Score and select nodes
        let scored = self.score_nodes(&expanded, question);

        // 5. Fit to token budget
        let selected = self.fit_to_budget(scored, max_tokens);

        // 6. Generate MU output
        let mu_output = self.generate_mu_output(&selected).await?;

        // 7. Estimate tokens
        let tokens = estimate_tokens(&mu_output);

        Ok(ContextResult {
            mu_output,
            nodes: selected,
            tokens,
        })
    }

    /// Extract potential entity names from the question.
    fn extract_entities(&self, question: &str) -> Vec<String> {
        // Simple tokenization and filtering
        let stop_words: HashSet<&str> = [
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "have", "has",
            "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must",
            "shall", "can", "need", "dare", "ought", "used", "to", "of", "in", "for", "on", "with",
            "at", "by", "from", "as", "into", "through", "during", "before", "after", "above",
            "below", "between", "under", "again", "further", "then", "once", "here", "there",
            "when", "where", "why", "how", "all", "each", "few", "more", "most", "other", "some",
            "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very", "just",
            "and", "but", "if", "or", "because", "until", "while", "what", "which", "who", "this",
            "that", "these", "those", "it", "its", "i", "you", "he", "she", "we", "they", "me",
            "him", "her", "us", "them", "my", "your", "his", "our", "their", "code", "function",
            "class", "module", "file", "works", "work", "does", "show", "explain", "find", "get",
            "set",
        ]
        .into_iter()
        .collect();

        question
            .split(|c: char| !c.is_alphanumeric() && c != '_')
            .filter(|w| w.len() > 2)
            .filter(|w| !stop_words.contains(w.to_lowercase().as_str()))
            .map(|w| w.to_string())
            .collect()
    }

    /// Find nodes matching the extracted entities.
    async fn find_nodes(&self, entities: &[String]) -> Result<Vec<String>> {
        let mubase = self.state.mubase.read().await;
        let mut found_nodes = Vec::new();

        for entity in entities {
            // Search by name (case-insensitive)
            let sql = format!(
                "SELECT id FROM nodes WHERE LOWER(name) LIKE '%{}%' LIMIT 20",
                entity.to_lowercase().replace('\'', "''")
            );

            if let Ok(result) = mubase.query(&sql) {
                for row in &result.rows {
                    if let Some(id) = row.first().and_then(|v| v.as_str()) {
                        found_nodes.push(id.to_string());
                    }
                }
            }
        }

        // Deduplicate
        let unique: HashSet<String> = found_nodes.into_iter().collect();
        Ok(unique.into_iter().collect())
    }

    /// Expand context by following graph edges.
    async fn expand_context(&self, seed_nodes: &[String], budget: usize) -> Result<Vec<String>> {
        let graph = self.state.graph.read().await;
        let edges = graph.get_edges();

        let mut expanded: HashSet<String> = seed_nodes.iter().cloned().collect();

        // Add direct neighbors (1-hop)
        for seed in seed_nodes {
            // Outgoing edges (dependencies)
            for (src, dst, _) in edges {
                if src == seed && !expanded.contains(dst.as_str()) {
                    expanded.insert(dst.clone());
                    if expanded.len() >= budget / 100 {
                        break;
                    }
                }
            }

            // Incoming edges (dependents)
            for (src, dst, _) in edges {
                if dst == seed && !expanded.contains(src.as_str()) {
                    expanded.insert(src.clone());
                    if expanded.len() >= budget / 100 {
                        break;
                    }
                }
            }
        }

        Ok(expanded.into_iter().collect())
    }

    /// Score nodes by relevance to the question.
    fn score_nodes(&self, nodes: &[String], question: &str) -> Vec<(String, f64)> {
        let question_lower = question.to_lowercase();
        let question_words: HashSet<&str> = question_lower.split_whitespace().collect();

        nodes
            .iter()
            .map(|node_id| {
                let mut score = 0.0;

                // Extract name from node ID
                let name = node_id
                    .split(':')
                    .last()
                    .unwrap_or(node_id)
                    .split('.')
                    .last()
                    .unwrap_or(node_id)
                    .to_lowercase();

                // Exact match bonus
                if question_lower.contains(&name) {
                    score += 10.0;
                }

                // Partial word match
                for word in &question_words {
                    if name.contains(word) || word.contains(&name) {
                        score += 2.0;
                    }
                }

                // Prefer specific node types - functions and classes provide more useful context
                // than just module headers
                if node_id.starts_with("fn:") {
                    score += 3.0; // Functions are most relevant - they have the actual logic
                } else if node_id.starts_with("cls:") {
                    score += 2.0; // Classes provide good structural context
                } else if node_id.starts_with("mod:") {
                    score += 0.5; // Modules are less specific, lower priority
                }

                (node_id.clone(), score)
            })
            .collect()
    }

    /// Select nodes that fit within the token budget.
    fn fit_to_budget(&self, mut scored: Vec<(String, f64)>, max_tokens: usize) -> Vec<String> {
        // Sort by score descending
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        // Estimate ~50 tokens per node on average
        let max_nodes = max_tokens / 50;

        scored
            .into_iter()
            .take(max_nodes)
            .map(|(id, _)| id)
            .collect()
    }

    /// Generate MU format output for the selected nodes.
    async fn generate_mu_output(&self, node_ids: &[String]) -> Result<String> {
        let mubase = self.state.mubase.read().await;
        let mut output = String::new();

        // Group nodes by file
        let mut by_file: HashMap<String, Vec<String>> = HashMap::new();

        for id in node_ids {
            if let Ok(Some(node)) = mubase.get_node(id) {
                let file = node.file_path.unwrap_or_else(|| "unknown".to_string());
                by_file.entry(file).or_default().push(id.clone());
            }
        }

        // Generate MU output per file
        for (file, ids) in by_file {
            output.push_str(&format!("! {}\n", file));

            for id in ids {
                if let Ok(Some(node)) = mubase.get_node(&id) {
                    match node.node_type {
                        NodeType::Module => {
                            // Include module-level info: imports info and summary
                            if let Some(ref props) = node.properties {
                                if let Some(docstring) =
                                    props.get("docstring").and_then(|v| v.as_str())
                                {
                                    let short_doc = if docstring.len() > 100 {
                                        format!("{}...", &docstring[..100])
                                    } else {
                                        docstring.to_string()
                                    };
                                    output.push_str(&format!(
                                        "  :: {}\n",
                                        short_doc.replace('\n', " ")
                                    ));
                                }
                            }
                        }
                        NodeType::Class => {
                            output.push_str(&format!("  $ {}\n", node.name));
                            // Include class docstring if available
                            if let Some(ref props) = node.properties {
                                if let Some(docstring) =
                                    props.get("docstring").and_then(|v| v.as_str())
                                {
                                    let short_doc = if docstring.len() > 80 {
                                        format!("{}...", &docstring[..80])
                                    } else {
                                        docstring.to_string()
                                    };
                                    output.push_str(&format!(
                                        "    :: {}\n",
                                        short_doc.replace('\n', " ")
                                    ));
                                }
                            }
                        }
                        NodeType::Function => {
                            let complexity = if node.complexity > 0 {
                                format!(" ::complexity={}", node.complexity)
                            } else {
                                String::new()
                            };
                            output.push_str(&format!("    # {}{}\n", node.name, complexity));
                        }
                        NodeType::External => {
                            output.push_str(&format!("  @ {}\n", node.name));
                        }
                    }
                }
            }

            output.push('\n');
        }

        Ok(output)
    }
}

/// Estimate token count for a string (rough approximation).
fn estimate_tokens(text: &str) -> usize {
    // Simple heuristic: ~4 characters per token
    text.len() / 4
}
