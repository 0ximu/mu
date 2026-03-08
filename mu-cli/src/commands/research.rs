//! Research command - Deep code exploration via search + graph walk + compress.
//!
//! Chains: embed query -> vector search -> [expand] -> [rerank] -> BFS graph walk
//! -> collect subgraph -> compress with adaptive budget -> output.

use std::collections::HashSet;
use std::path::Path;
use std::time::Instant;

use colored::Colorize;
use serde::{Deserialize, Serialize};

use crate::output::{Output, OutputFormat, TableDisplay};

/// Research result for output formatting
#[derive(Debug, Serialize, Deserialize)]
pub struct ResearchResult {
    pub query: String,
    pub seed_count: usize,
    pub explored_nodes: usize,
    pub max_hops: usize,
    pub subgraph_content: String,
    pub connections: Vec<ConnectionEntry>,
    pub duration_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConnectionEntry {
    pub source: String,
    pub target: String,
    pub edge_type: String,
}

impl TableDisplay for ResearchResult {
    fn to_table(&self) -> String {
        self.subgraph_content.clone()
    }

    fn to_mu(&self) -> String {
        let mut out = String::new();
        out.push_str(&format!("# MU Research: \"{}\"\n", self.query));
        out.push_str(&format!(
            "# Explored {} nodes via {} seed results, max_hops={}\n",
            self.explored_nodes, self.seed_count, self.max_hops,
        ));
        out.push_str(&format!("# Duration: {}ms\n\n", self.duration_ms));
        out.push_str(&self.subgraph_content);

        if !self.connections.is_empty() {
            out.push_str("\n## Connections\n");
            for conn in &self.connections {
                out.push_str(&format!(
                    "  {} -> {} [{}]\n",
                    conn.source, conn.target, conn.edge_type
                ));
            }
        }

        out
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

/// Run the research command
pub async fn run(
    query: &str,
    max_hops: usize,
    max_tokens: Option<usize>,
    expand: bool,
    rerank: bool,
    format: OutputFormat,
) -> anyhow::Result<()> {
    if query.trim().is_empty() {
        anyhow::bail!("Research query cannot be empty.");
    }

    let start = Instant::now();

    // Find mubase
    let cwd = std::env::current_dir()?;
    let mubase_path = match find_mubase_path(&cwd) {
        Some(path) => path,
        None => {
            anyhow::bail!("No .mu/mubase found. Run 'mu bootstrap --embed' first.");
        }
    };

    let mubase = mu_daemon::storage::MUbase::open_read_only(&mubase_path)?;

    if !mubase.has_embeddings()? {
        anyhow::bail!("No embeddings found. Run 'mu bootstrap --embed' or 'mu embed' first.");
    }

    // Step 1: Semantic search to get seed nodes
    let model = mu_embeddings::MuSigmaModel::embedded()?;
    let threshold = 0.1_f32;

    let fetch_limit = if rerank {
        mu_daemon::rerank::RerankConfig::default().candidate_pool
    } else {
        10
    };

    let mut candidates = if expand {
        run_expanded_search(&mubase, &model, query, fetch_limit, threshold)?
    } else {
        run_semantic_search(&mubase, &model, query, fetch_limit, threshold)?
    };

    // Step 2: Rerank if enabled
    if rerank && candidates.len() > 1 {
        let graph = mubase.load_graph()?;
        let config = mu_daemon::rerank::RerankConfig {
            final_count: 10,
            ..mu_daemon::rerank::RerankConfig::default()
        };
        candidates = mu_daemon::rerank::rerank(candidates, &graph, &config);
    } else {
        candidates.truncate(10);
    }

    // Handle empty results
    if candidates.is_empty() {
        let result = ResearchResult {
            query: query.to_string(),
            seed_count: 0,
            explored_nodes: 0,
            max_hops,
            subgraph_content: format!(
                "{} No results found for \"{}\"\n",
                "RESEARCH:".cyan().bold(),
                query
            ),
            connections: vec![],
            duration_ms: start.elapsed().as_millis() as u64,
        };
        return Output::new(result, format).render();
    }

    let seed_count = candidates.len();
    let seed_ids: Vec<String> = candidates.iter().map(|c| c.node_id.clone()).collect();

    // Step 3: Load full graph and BFS walk
    let conn = super::graph::open_db()?;
    let graph = super::graph::GraphData::from_db(&conn)?;

    let visited = graph.bfs_multi_seed(&seed_ids, max_hops, None);
    let explored_nodes = visited.len();

    // Step 4: Extract subgraph edges
    let subgraph_edges = graph.extract_subgraph(&visited);

    // Step 5: Load node details from DB for visited nodes
    let subgraph_content = format_subgraph(
        query,
        &visited,
        &seed_ids,
        &subgraph_edges,
        &graph,
        max_hops,
        max_tokens,
        seed_count,
        explored_nodes,
    );

    let connections: Vec<ConnectionEntry> = subgraph_edges
        .iter()
        .filter(|(_, _, edge_type)| edge_type != "contains")
        .map(|(src, tgt, edge_type)| {
            let src_name = graph
                .get_info(src)
                .map(|i| i.name.clone())
                .unwrap_or_else(|| src.clone());
            let tgt_name = graph
                .get_info(tgt)
                .map(|i| i.name.clone())
                .unwrap_or_else(|| tgt.clone());
            ConnectionEntry {
                source: src_name,
                target: tgt_name,
                edge_type: edge_type.clone(),
            }
        })
        .collect();

    let duration_ms = start.elapsed().as_millis() as u64;

    let result = ResearchResult {
        query: query.to_string(),
        seed_count,
        explored_nodes,
        max_hops,
        subgraph_content,
        connections,
        duration_ms,
    };

    Output::new(result, format).render()
}

/// Run basic semantic search
fn run_semantic_search(
    mubase: &mu_daemon::storage::MUbase,
    model: &mu_embeddings::MuSigmaModel,
    query: &str,
    limit: usize,
    threshold: f32,
) -> anyhow::Result<Vec<mu_daemon::storage::VectorSearchResult>> {
    let query_embedding = model.embed_one(query)?;
    mubase.vector_search(&query_embedding, limit, Some(threshold))
}

/// Run expanded semantic search using graph neighbors
fn run_expanded_search(
    mubase: &mu_daemon::storage::MUbase,
    model: &mu_embeddings::MuSigmaModel,
    query: &str,
    limit: usize,
    threshold: f32,
) -> anyhow::Result<Vec<mu_daemon::storage::VectorSearchResult>> {
    use mu_daemon::query_expansion::{expand_query, merge_search_results};

    // Initial search
    let query_embedding = model.embed_one(query)?;
    let initial_results = mubase.vector_search(&query_embedding, 10, Some(threshold))?;

    if initial_results.is_empty() {
        return Ok(vec![]);
    }

    // Load graph and collect neighbor names
    let conn = super::graph::open_db()?;
    let graph = super::graph::GraphData::from_db(&conn)?;

    let mut neighbor_names = Vec::new();
    for result in &initial_results {
        let neighbor_ids = graph.impact(&result.node_id, None, Some(1));
        for nid in &neighbor_ids {
            if let Some(info) = graph.get_info(nid) {
                neighbor_names.push(info.name.clone());
            }
        }
    }

    // Expand query
    let queries = expand_query(query, &neighbor_names, 5);

    // Run search for each expanded query
    let mut all_results = Vec::new();
    for q in &queries {
        let emb = model.embed_one(q)?;
        let results = mubase.vector_search(&emb, limit, Some(threshold))?;
        all_results.push(results);
    }

    Ok(merge_search_results(all_results))
}

/// Format the subgraph into MU sigil output
#[allow(clippy::too_many_arguments)]
fn format_subgraph(
    query: &str,
    visited: &HashSet<String>,
    seed_ids: &[String],
    _edges: &[(String, String, String)],
    graph: &super::graph::GraphData,
    max_hops: usize,
    max_tokens: Option<usize>,
    seed_count: usize,
    explored_nodes: usize,
) -> String {
    use crate::commands::compress::budget::estimate_tokens;

    let seed_set: HashSet<&String> = seed_ids.iter().collect();
    let mut out = String::new();

    out.push_str(&format!("{} \"{}\"\n", "RESEARCH:".cyan().bold(), query));
    out.push_str(&format!(
        "Explored {} nodes via {} seed results, max_hops={}\n\n",
        explored_nodes, seed_count, max_hops,
    ));

    // Group nodes by file path
    let mut by_file: std::collections::BTreeMap<
        String,
        Vec<(&str, &super::graph::NodeInfo, bool)>,
    > = std::collections::BTreeMap::new();

    for node_id in visited {
        if let Some(info) = graph.get_info(node_id) {
            let file = info.file_path.as_deref().unwrap_or("(unknown)").to_string();
            let is_seed = seed_set.contains(node_id);
            by_file
                .entry(file)
                .or_default()
                .push((node_id, info, is_seed));
        }
    }

    out.push_str("## Subgraph\n");

    for (file, mut nodes) in by_file {
        // Sort: modules first, then classes, then functions
        nodes.sort_by(|a, b| {
            let type_ord = |t: &str| match t {
                "module" => 0,
                "class" => 1,
                "function" => 2,
                _ => 3,
            };
            type_ord(&a.1.node_type).cmp(&type_ord(&b.1.node_type))
        });

        out.push_str(&format!("! {}\n", file));

        for (_node_id, info, is_seed) in &nodes {
            if info.node_type == "module" {
                continue; // Already represented by the file header
            }

            let sigil = match info.node_type.as_str() {
                "class" => "  $",
                "function" => "    #",
                _ => "    @",
            };
            let star = if *is_seed { " *" } else { "" };
            out.push_str(&format!("{} {}{}\n", sigil, info.name, star));
        }
    }

    // Apply budget if specified
    if let Some(budget) = max_tokens {
        let estimated = estimate_tokens(&out);
        if estimated > budget {
            // Truncate content to fit budget
            let words: Vec<&str> = out.split_whitespace().collect();
            let target_words = (budget as f64 / 1.3) as usize;
            if target_words < words.len() {
                out = words[..target_words].join(" ");
                out.push_str(&format!(
                    "\n\n... truncated ({} tokens exceeded {} budget)\n",
                    estimated, budget
                ));
            }
        }
    }

    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_research_result_serialization() {
        let result = ResearchResult {
            query: "how does auth work".to_string(),
            seed_count: 5,
            explored_nodes: 20,
            max_hops: 2,
            subgraph_content: "test content".to_string(),
            connections: vec![ConnectionEntry {
                source: "AuthService".to_string(),
                target: "TokenManager".to_string(),
                edge_type: "calls".to_string(),
            }],
            duration_ms: 150,
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("auth"));
        assert!(json.contains("TokenManager"));
    }

    #[test]
    fn test_connection_entry() {
        let conn = ConnectionEntry {
            source: "A".to_string(),
            target: "B".to_string(),
            edge_type: "imports".to_string(),
        };
        let json = serde_json::to_string(&conn).unwrap();
        assert!(json.contains("imports"));
    }

    #[test]
    fn test_research_result_mu_format() {
        let result = ResearchResult {
            query: "test query".to_string(),
            seed_count: 3,
            explored_nodes: 10,
            max_hops: 2,
            subgraph_content: "! src/main.py\n  $ MyClass\n".to_string(),
            connections: vec![ConnectionEntry {
                source: "A".to_string(),
                target: "B".to_string(),
                edge_type: "calls".to_string(),
            }],
            duration_ms: 50,
        };

        let mu = result.to_mu();
        assert!(mu.contains("MU Research"));
        assert!(mu.contains("test query"));
        assert!(mu.contains("## Connections"));
        assert!(mu.contains("A -> B [calls]"));
    }

    #[test]
    fn test_empty_connections_mu_format() {
        let result = ResearchResult {
            query: "nothing".to_string(),
            seed_count: 0,
            explored_nodes: 0,
            max_hops: 2,
            subgraph_content: "No results".to_string(),
            connections: vec![],
            duration_ms: 10,
        };

        let mu = result.to_mu();
        assert!(mu.contains("MU Research"));
        assert!(!mu.contains("## Connections"));
    }
}
