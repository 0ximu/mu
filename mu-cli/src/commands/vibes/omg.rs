//! Omg command - OMEGA compressed context (S-expression format)
//!
//! Extracts context using OMEGA S-expression format with intelligent node
//! ranking based on complexity, connectivity, and semantic centrality.

use std::collections::{HashMap, HashSet};
use std::path::Path;

use colored::Colorize;
use mu_daemon::storage::{MUbase, Node, NodeType};

use crate::output::OutputFormat;

/// Default token budget for output
const DEFAULT_MAX_TOKENS: usize = 8000;
/// Estimated tokens per node in output (avg ~15 chars/line, ~4 chars/token)
const TOKENS_PER_NODE: usize = 15;
/// Estimated tokens per edge in output
const TOKENS_PER_EDGE: usize = 10;
/// Reserve tokens for schema seed
const SCHEMA_SEED_TOKENS: usize = 100;

/// OMEGA context extraction result
#[derive(Debug, serde::Serialize)]
pub struct OmgResult {
    pub seed: String,
    pub body: String,
    pub full_output: String,
    pub seed_tokens: usize,
    pub body_tokens: usize,
    pub total_tokens: usize,
    pub node_count: usize,
    pub edge_count: usize,
    pub total_nodes_in_db: usize,
    pub total_edges_in_db: usize,
    pub compression_ratio: f64,
}

impl OmgResult {
    fn has_content(&self) -> bool {
        !self.body.is_empty()
    }
}

/// Run the omg command - OMEGA compressed context with intelligent ranking
pub async fn run(max_tokens: usize, include_edges: bool, format: OutputFormat) -> anyhow::Result<()> {
    // Find mubase
    let cwd = std::env::current_dir()?;
    let mubase_path = match find_mubase_path(&cwd) {
        Some(path) => path,
        None => {
            // No database - show helpful message
            let result = OmgResult {
                seed: String::new(),
                body: String::new(),
                full_output: String::new(),
                seed_tokens: 0,
                body_tokens: 0,
                total_tokens: 0,
                node_count: 0,
                edge_count: 0,
                total_nodes_in_db: 0,
                total_edges_in_db: 0,
                compression_ratio: 1.0,
            };

            match format {
                OutputFormat::Json => {
                    println!("{}", serde_json::to_string_pretty(&result)?);
                }
                _ => {
                    print_omg_output(&result);
                }
            }
            return Ok(());
        }
    };

    // Open database in read-only mode
    let mubase = MUbase::open_read_only(&mubase_path)?;

    // Generate OMEGA output with intelligent ranking
    let result = generate_omega_context(&mubase, max_tokens, include_edges)?;

    match format {
        OutputFormat::Json => {
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
        _ => {
            print_omg_output(&result);
        }
    }

    Ok(())
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

/// Score a node for importance ranking
fn score_node(node: &Node, edge_count: usize) -> f32 {
    // Complexity score: 0-5 points (normalize to max 5)
    let complexity_score = (node.complexity as f32 / 10.0).min(5.0);

    // Connectivity score: 0-5 points (more edges = more important)
    let connectivity_score = (edge_count as f32 / 5.0).min(5.0);

    // Type bonus: classes are structural, functions contain logic
    let type_bonus = match node.node_type {
        NodeType::Class => 2.0,
        NodeType::Function => 1.0,
        NodeType::Module => 0.5,
        NodeType::External => 0.0,
    };

    // Penalty for empty names (likely parser artifacts)
    let name_penalty = if node.name.is_empty() { -10.0 } else { 0.0 };

    complexity_score + connectivity_score + type_bonus + name_penalty
}

/// Compute edge counts per node from the graph
fn compute_edge_counts(edges: &[(String, String, String)]) -> HashMap<String, usize> {
    let mut counts: HashMap<String, usize> = HashMap::new();

    for (source, target, _edge_type) in edges {
        *counts.entry(source.clone()).or_insert(0) += 1;
        *counts.entry(target.clone()).or_insert(0) += 1;
    }

    counts
}

/// Select top nodes within token budget based on scores
fn select_top_nodes(
    nodes: Vec<Node>,
    edge_counts: &HashMap<String, usize>,
    max_tokens: usize,
) -> Vec<Node> {
    // Reserve tokens for seed and edges
    let available_tokens = max_tokens.saturating_sub(SCHEMA_SEED_TOKENS);
    let max_node_tokens = available_tokens * 2 / 3; // 2/3 for nodes, 1/3 for edges
    let max_nodes = max_node_tokens / TOKENS_PER_NODE;

    // Score all nodes
    let mut scored: Vec<(Node, f32)> = nodes
        .into_iter()
        .filter(|n| !n.name.is_empty()) // Filter out empty names
        .map(|n| {
            let ec = edge_counts.get(&n.id).copied().unwrap_or(0);
            let score = score_node(&n, ec);
            (n, score)
        })
        .collect();

    // Sort by score descending
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Take top N
    scored.into_iter().take(max_nodes).map(|(n, _)| n).collect()
}

/// Select edges that connect selected nodes
fn select_edges(
    all_edges: &[(String, String, String)],
    selected_node_ids: &HashSet<String>,
    max_tokens: usize,
) -> Vec<(String, String, String)> {
    let max_edges = max_tokens / TOKENS_PER_EDGE / 3; // ~1/3 of budget for edges

    // Prioritize non-contains edges (imports, inherits, calls are more interesting)
    let mut priority_edges: Vec<_> = all_edges
        .iter()
        .filter(|(source, target, edge_type)| {
            // Include edge if at least one endpoint is selected (not just both)
            // and it's not a contains edge
            edge_type != "contains"
                && (selected_node_ids.contains(source) || selected_node_ids.contains(target))
        })
        .cloned()
        .collect();

    // If we have few priority edges, add some contains edges to show hierarchy
    if priority_edges.len() < max_edges / 2 {
        let contains_edges: Vec<_> = all_edges
            .iter()
            .filter(|(source, target, edge_type)| {
                edge_type == "contains"
                    && (selected_node_ids.contains(source) || selected_node_ids.contains(target))
            })
            .take(max_edges - priority_edges.len())
            .cloned()
            .collect();
        priority_edges.extend(contains_edges);
    }

    priority_edges.truncate(max_edges);
    priority_edges
}

/// Generate OMEGA compressed context with intelligent ranking
fn generate_omega_context(
    mubase: &MUbase,
    max_tokens: usize,
    include_edges: bool,
) -> anyhow::Result<OmgResult> {
    // Get all nodes
    let modules = mubase.get_nodes_by_type(NodeType::Module)?;
    let classes = mubase.get_nodes_by_type(NodeType::Class)?;
    let functions = mubase.get_nodes_by_type(NodeType::Function)?;

    let total_nodes_in_db = modules.len() + classes.len() + functions.len();

    // Combine all nodes
    let mut all_nodes: Vec<Node> = Vec::with_capacity(total_nodes_in_db);
    all_nodes.extend(modules);
    all_nodes.extend(classes);
    all_nodes.extend(functions);

    // Load graph for edge data
    let graph = mubase.load_graph()?;
    let all_edges = graph.get_edges();
    let total_edges_in_db = all_edges.len();

    // Compute edge counts for scoring
    let edge_counts = compute_edge_counts(all_edges);

    // Select top nodes within budget
    let selected_nodes = select_top_nodes(all_nodes, &edge_counts, max_tokens);
    let selected_node_ids: HashSet<String> = selected_nodes.iter().map(|n| n.id.clone()).collect();

    // Select edges if requested
    let selected_edges = if include_edges {
        select_edges(all_edges, &selected_node_ids, max_tokens)
    } else {
        Vec::new()
    };

    // Generate schema seed
    let seed = generate_schema_seed(include_edges);
    let seed_tokens = estimate_tokens(&seed);

    // Generate compressed body
    let body = generate_compressed_body(&selected_nodes, &selected_edges);
    let body_tokens = estimate_tokens(&body);

    let total_tokens = seed_tokens + body_tokens;

    // Calculate compression ratio vs raw JSON
    let raw_data = RawOmegaData {
        nodes: &selected_nodes,
        edges: &selected_edges,
    };
    let raw_json = serde_json::to_string(&raw_data)?;
    let raw_tokens = estimate_tokens(&raw_json);
    let compression_ratio = if total_tokens > 0 {
        raw_tokens as f64 / total_tokens as f64
    } else {
        1.0
    };

    let full_output = format!("{}\n\n{}", seed, body);

    Ok(OmgResult {
        seed,
        body,
        full_output,
        seed_tokens,
        body_tokens,
        total_tokens,
        node_count: selected_nodes.len(),
        edge_count: selected_edges.len(),
        total_nodes_in_db,
        total_edges_in_db,
        compression_ratio,
    })
}

/// Temporary struct for serializing raw data to compute compression ratio
#[derive(serde::Serialize)]
struct RawOmegaData<'a> {
    nodes: &'a [Node],
    edges: &'a [(String, String, String)],
}

/// Generate schema seed with macro definitions (cacheable)
fn generate_schema_seed(include_edges: bool) -> String {
    let edge_schema = if include_edges {
        "\n  (-> source target type)  ; Edge: source -> target via type"
    } else {
        ""
    };

    format!(
        r#";; OMEGA Schema - MU codebase overview
;; Nodes ranked by importance (complexity + connectivity)

(defschema mu
  (mod path)                  ; Module/file
  (cls name :cx complexity)   ; Class with complexity
  (fn name :cx complexity)    ; Function with complexity{})"#,
        edge_schema
    )
}

/// Generate compressed body with nodes grouped by file and edges section
fn generate_compressed_body(
    nodes: &[Node],
    edges: &[(String, String, String)],
) -> String {
    let mut output = String::from("(context\n");

    // Group nodes by file
    let mut by_file: HashMap<String, Vec<&Node>> = HashMap::new();
    for node in nodes {
        let file_key = node
            .file_path
            .clone()
            .unwrap_or_else(|| "unknown".to_string());
        by_file.entry(file_key).or_default().push(node);
    }

    // Sort files by total complexity (most important files first)
    let mut sorted_files: Vec<_> = by_file.iter().collect();
    sorted_files.sort_by(|a, b| {
        let complexity_a: u32 = a.1.iter().map(|n| n.complexity).sum();
        let complexity_b: u32 = b.1.iter().map(|n| n.complexity).sum();
        complexity_b.cmp(&complexity_a)
    });

    // Generate output per file
    for (file_path, file_nodes) in sorted_files {
        let simplified_path = simplify_path(file_path);
        output.push_str(&format!("  (mod \"{}\"\n", simplified_path));

        // Sort nodes within file: classes first, then functions, by complexity desc
        let mut sorted_nodes = file_nodes.clone();
        sorted_nodes.sort_by(|a, b| {
            let type_order = |n: &Node| match n.node_type {
                NodeType::Class => 0,
                NodeType::Function => 1,
                NodeType::Module => 2,
                NodeType::External => 3,
            };
            let ord = type_order(a).cmp(&type_order(b));
            if ord == std::cmp::Ordering::Equal {
                b.complexity.cmp(&a.complexity)
            } else {
                ord
            }
        });

        for node in sorted_nodes {
            match node.node_type {
                NodeType::Class => {
                    output.push_str(&format!("    (cls \"{}\"", node.name));
                    if node.complexity > 0 {
                        output.push_str(&format!(" :cx {}", node.complexity));
                    }
                    output.push_str(")\n");
                }
                NodeType::Function => {
                    // Skip test functions in overview (less important)
                    if node.name.starts_with("test_") || node.name.starts_with("Test") {
                        continue;
                    }
                    output.push_str(&format!("    (fn \"{}\"", node.name));
                    if node.complexity > 5 {
                        output.push_str(&format!(" :cx {}", node.complexity));
                    }
                    output.push_str(")\n");
                }
                _ => {}
            }
        }

        output.push_str("  )\n");
    }

    // Add edges section if present
    if !edges.is_empty() {
        output.push_str("\n  ;; Key relationships\n  (edges\n");

        // Group edges by type for readability
        let mut edges_by_type: HashMap<&str, Vec<(&str, &str)>> = HashMap::new();
        for (source, target, edge_type) in edges {
            edges_by_type
                .entry(edge_type.as_str())
                .or_default()
                .push((source.as_str(), target.as_str()));
        }

        // Output edges grouped by type
        for (edge_type, edge_list) in edges_by_type {
            for (source, target) in edge_list.iter().take(50) {
                // Limit per type
                let src_name = extract_node_name(source);
                let tgt_name = extract_node_name(target);
                output.push_str(&format!("    (-> {} {} {})\n", src_name, tgt_name, edge_type));
            }
        }

        output.push_str("  )\n");
    }

    output.push(')');
    output
}

/// Extract meaningful name from node ID
/// - "fn:src/cli.rs:main" -> "main"
/// - "mod:mu-sigma/pairs.py" -> "pairs"
/// - "cls:src/storage.rs:MUbase" -> "MUbase"
/// - "ext:logging" -> "logging"
fn extract_node_name(node_id: &str) -> String {
    // Split by : to get the last component
    let parts: Vec<&str> = node_id.split(':').collect();

    if parts.len() >= 2 {
        let last_part = parts.last().unwrap_or(&node_id);

        // For paths like "mu-sigma/pairs.py", extract the filename without extension
        if last_part.contains('/') || last_part.contains('.') {
            // Get the filename
            let filename = last_part.rsplit('/').next().unwrap_or(last_part);
            // Remove extension
            let name = filename.rsplit('.').last().unwrap_or(filename);
            // If it's just the extension (e.g., "py"), use the stem instead
            if name.len() <= 3 && filename.contains('.') {
                return filename.split('.').next().unwrap_or(filename).to_string();
            }
            return name.to_string();
        }
        return (*last_part).to_string();
    }

    node_id.to_string()
}

/// Simplify file path for display
fn simplify_path(path: &str) -> String {
    path.trim_start_matches("./")
        .trim_start_matches("src/")
        .to_string()
}

/// Estimate token count (rough approximation: 4 chars per token)
fn estimate_tokens(text: &str) -> usize {
    text.len() / 4
}

fn print_omg_output(result: &OmgResult) {
    println!();
    println!(
        "{} {}",
        "OMG Context".green().bold(),
        format!("({} tokens)", result.total_tokens).dimmed()
    );
    println!();

    if !result.has_content() {
        println!(
            "{}",
            "No MU database found. Run 'mu bootstrap' first.".yellow()
        );
        println!();
        println!(
            "{}",
            "OMG provides OMEGA-compressed codebase overview for LLMs.".dimmed()
        );
        println!();
        println!("{}", "Features:".cyan());
        println!(
            "  {} Intelligent ranking by complexity + connectivity",
            "*".dimmed()
        );
        println!(
            "  {} Includes key relationships (calls, imports, inherits)",
            "*".dimmed()
        );
        println!("  {} Token-budget aware output", "*".dimmed());
        println!("  {} S-expression format for dense encoding", "*".dimmed());
        println!();
        println!("{}", "Usage:".cyan());
        println!("  {} mu omg                    # Default 8000 tokens", "$".dimmed());
        println!("  {} mu omg -t 4000            # Smaller budget", "$".dimmed());
        println!("  {} mu omg --no-edges         # Nodes only", "$".dimmed());
    } else {
        // Show schema seed
        if !result.seed.is_empty() {
            println!(
                "{}",
                format!(";; Schema ({} tokens)", result.seed_tokens).dimmed()
            );
            println!("{}", result.seed);
            println!();
        }

        // Show body
        println!(
            "{}",
            format!(";; Body ({} tokens)", result.body_tokens).dimmed()
        );
        println!("{}", result.body);
        println!();

        // Stats
        println!(
            "{} {} {} {} {}",
            "Coverage:".dimmed(),
            format!("{}/{}", result.node_count, result.total_nodes_in_db)
                .cyan()
                .bold(),
            "nodes,".dimmed(),
            format!("{}/{}", result.edge_count, result.total_edges_in_db)
                .cyan()
                .bold(),
            "edges".dimmed()
        );

        println!(
            "{} {}",
            "Compression:".dimmed(),
            format!("{:.1}x vs JSON", result.compression_ratio)
                .cyan()
                .bold(),
        );

        println!("{}", "Your context just lost mass.".dimmed());
    }

    println!();
}
