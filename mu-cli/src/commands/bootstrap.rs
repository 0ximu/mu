//! Bootstrap command - Initialize and build MU database in one step
//!
//! This command:
//! 1. Creates .murc.toml config if missing
//! 2. Adds .mu/ to .gitignore
//! 3. Builds the .mu/mubase code graph
//! 4. Shows progress and final stats

use std::collections::{HashMap, HashSet};
use std::fs;
use std::io::{self, IsTerminal};
use std::path::Path;
use std::time::Instant;

use colored::Colorize;
use dialoguer::Confirm;
use indicatif::{ProgressBar, ProgressStyle};
use serde::Serialize;
use serde_json::json;

use crate::cache::{CacheStats, ParseCache};
use crate::config::MuConfig;
use crate::output::{Output, OutputFormat, TableDisplay};
use crate::tsconfig::PathAliasResolver;

/// Result of bootstrap operation
#[derive(Debug, Serialize)]
pub struct BootstrapResult {
    pub success: bool,
    pub root_path: String,
    pub mubase_path: String,
    pub files_scanned: usize,
    pub files_parsed: usize,
    pub files_cached: usize,
    pub node_count: usize,
    pub edge_count: usize,
    pub nodes_by_type: HashMap<String, usize>,
    pub duration_ms: u64,
    pub config_created: bool,
    pub gitignore_updated: bool,
    pub embeddings_generated: usize,
    pub hnsw_index_created: bool,
    pub fts_index_created: bool,
}

impl TableDisplay for BootstrapResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        if self.success {
            output.push_str(&format!(
                "{} MU bootstrapped successfully\n",
                "SUCCESS:".green().bold()
            ));
        } else {
            output.push_str(&format!("{} Bootstrap failed\n", "ERROR:".red().bold()));
            return output;
        }

        output.push_str(&format!("\n{}\n", "Summary".cyan().bold()));
        output.push_str(&format!("  Root:     {}\n", self.root_path));
        output.push_str(&format!("  Database: {}\n", self.mubase_path));
        output.push_str(&format!(
            "  Duration: {}ms\n",
            self.duration_ms.to_string().yellow()
        ));

        output.push_str(&format!("\n{}\n", "Graph".cyan().bold()));
        output.push_str(&format!(
            "  Nodes: {}\n",
            self.node_count.to_string().green()
        ));
        output.push_str(&format!(
            "  Edges: {}\n",
            self.edge_count.to_string().green()
        ));

        if !self.nodes_by_type.is_empty() {
            output.push_str(&format!("\n{}\n", "Node Types".cyan().bold()));
            for (node_type, count) in &self.nodes_by_type {
                output.push_str(&format!("  {}: {}\n", node_type, count));
            }
        }

        output.push_str(&format!("\n{}\n", "Files".cyan().bold()));
        output.push_str(&format!("  Scanned: {}\n", self.files_scanned));
        output.push_str(&format!("  Parsed:  {}\n", self.files_parsed));
        if self.files_cached > 0 {
            output.push_str(&format!(
                "  Cached:  {} (skipped)\n",
                self.files_cached.to_string().green()
            ));
        }

        if self.config_created || self.gitignore_updated {
            output.push_str(&format!("\n{}\n", "Setup".cyan().bold()));
            if self.config_created {
                output.push_str("  Created .murc.toml\n");
            }
            if self.gitignore_updated {
                output.push_str("  Updated .gitignore\n");
            }
        }

        if self.embeddings_generated > 0 || self.hnsw_index_created || self.fts_index_created {
            output.push_str(&format!("\n{}\n", "Search".cyan().bold()));
            if self.fts_index_created {
                output.push_str(&format!(
                    "  FTS Index:  {} (BM25 keyword search)\n",
                    "created".green()
                ));
            }
            if self.embeddings_generated > 0 {
                output.push_str(&format!(
                    "  Embeddings: {} (semantic search)\n",
                    self.embeddings_generated.to_string().green()
                ));
            }
            if self.hnsw_index_created {
                output.push_str(&format!(
                    "  HNSW Index: {} (fast vector search)\n",
                    "created".green()
                ));
            }
        }

        output.push_str(&format!("\n{}\n", "Next Steps".cyan().bold()));
        output.push_str("  mu status              # Check status\n");
        output.push_str("  mu query 'functions'   # Query the graph\n");
        if self.embeddings_generated > 0 {
            output.push_str("  mu search 'auth'       # Semantic search\n");
            if !self.hnsw_index_created && self.embeddings_generated > 5000 {
                output.push_str("  mu bootstrap --hnsw    # Enable fast search (recommended)\n");
            }
        } else {
            output.push_str("  mu bootstrap --embed   # Enable semantic search\n");
        }

        output
    }

    fn to_mu(&self) -> String {
        format!(
            r#":: bootstrap
# root: {}
# mubase: {}
# nodes: {}
# edges: {}
# duration: {}ms"#,
            self.root_path, self.mubase_path, self.node_count, self.edge_count, self.duration_ms
        )
    }
}

/// Default .murc.toml content
fn get_default_config() -> &'static str {
    r#"# MU Configuration
# https://github.com/0ximu/mu

[mu]
version = "1.0"

[scanner]
ignore = [
    "node_modules/",
    ".git/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
    "dist/",
    "build/",
    "target/",
    "archive/",
    "*.min.js",
    "*.bundle.js",
    "*.lock",
    ".mu/",
]
include_hidden = false
max_file_size_kb = 1000

[parser]
# languages = ["python", "typescript", "rust"]  # Uncomment to limit parsing

[output]
format = "table"
include_line_numbers = false

[cache]
enabled = true
directory = ".mu/cache"
"#
}

/// Add .mu/ to .gitignore if not present
fn update_gitignore(root: &Path) -> bool {
    let gitignore_path = root.join(".gitignore");
    let marker = "# MU (Machine Understanding)";
    let mu_entry = ".mu/";

    // Read existing content
    let existing_content = fs::read_to_string(&gitignore_path).unwrap_or_default();

    // Check if already present
    if existing_content.contains(marker) || existing_content.contains(mu_entry) {
        return false;
    }

    // Append MU section
    let new_section = format!("\n{}\n{}\n", marker, mu_entry);
    let new_content = if existing_content.is_empty() || existing_content.ends_with('\n') {
        format!("{}{}", existing_content, new_section)
    } else {
        format!("{}\n{}", existing_content, new_section)
    };

    if fs::write(&gitignore_path, new_content).is_ok() {
        return true;
    }

    false
}

/// Create .murc.toml if it doesn't exist
fn ensure_config(root: &Path) -> bool {
    let config_path = root.join(".murc.toml");
    if config_path.exists() {
        return false;
    }

    if fs::write(&config_path, get_default_config()).is_ok() {
        return true;
    }

    false
}

/// Determine whether to generate embeddings based on flags and user input
fn should_embed(embed_flag: bool, no_embed_flag: bool) -> bool {
    // Explicit flags take precedence
    if embed_flag {
        return true;
    }
    if no_embed_flag {
        return false;
    }

    // If running interactively, prompt the user
    if io::stdin().is_terminal() && io::stdout().is_terminal() {
        println!();
        println!(
            "{} Embeddings dramatically improve semantic search results.",
            "TIP:".cyan().bold()
        );
        println!("     This enables 'mu search' to find code by meaning, not just keywords.");
        println!("     Embedding takes ~30s for most projects.\n");

        Confirm::new()
            .with_prompt("Generate embeddings now?")
            .default(true)
            .interact()
            .unwrap_or(false)
    } else {
        // Non-interactive: default to no embeddings (user can use --embed explicitly)
        false
    }
}

/// Determine whether to create HNSW index based on flags, embedding count, and user input.
///
/// HNSW is only useful when:
/// 1. Embeddings exist (otherwise nothing to index)
/// 2. There are enough embeddings to benefit from indexing (>5000 threshold)
fn should_hnsw(hnsw_flag: bool, no_hnsw_flag: bool, embedding_count: usize) -> bool {
    // Explicit flags take precedence
    if hnsw_flag {
        return true;
    }
    if no_hnsw_flag {
        return false;
    }

    // Only consider HNSW if we have enough embeddings to benefit
    const HNSW_THRESHOLD: usize = 5000;
    if embedding_count < HNSW_THRESHOLD {
        return false;
    }

    // If running interactively, prompt the user
    if io::stdin().is_terminal() && io::stdout().is_terminal() {
        println!();
        println!(
            "{} You have {} embeddings. HNSW indexing can speed up vector search.",
            "TIP:".cyan().bold(),
            embedding_count
        );
        println!("     This creates an index for O(log n) approximate nearest neighbor search.");
        println!("     Index creation takes ~10s and adds ~10MB to database size.\n");

        Confirm::new()
            .with_prompt("Create HNSW index for faster search?")
            .default(true)
            .interact()
            .unwrap_or(false)
    } else {
        // Non-interactive: default to no HNSW (user can use --hnsw explicitly)
        false
    }
}

/// Run embeddings only on an existing database (without rebuilding the graph)
async fn run_embeddings_only(mubase_path: &Path, format: OutputFormat) -> anyhow::Result<()> {
    let start = Instant::now();

    let spinner = ProgressBar::new_spinner();
    spinner.set_style(
        ProgressStyle::default_spinner()
            .tick_chars("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
            .template("{spinner:.cyan} {msg}")
            .unwrap(),
    );
    spinner.enable_steady_tick(std::time::Duration::from_millis(100));

    spinner.set_message("Opening database...");
    // Note: MUbase::open() automatically runs any needed migrations (v1.0.0 → v1.1.0)
    let mubase = mu_daemon::storage::MUbase::open(mubase_path)?;
    let stats = mubase.stats()?;

    spinner.set_message("Loading embedding model...");

    let embeddings_generated = match mu_embeddings::MuSigmaModel::embedded() {
        Ok(model) => {
            spinner.set_message("Loading nodes...");

            // Get all nodes from the database
            let nodes = mubase.all_nodes()?;
            let nodes_to_embed: Vec<_> = nodes
                .iter()
                .filter(|n| n.node_type != mu_daemon::storage::NodeType::External)
                .collect();

            let total = nodes_to_embed.len();
            spinner.set_message(format!("Generating embeddings for {} nodes...", total));

            let mut embeddings_batch = Vec::new();
            let mut embedded_count = 0;

            // Process in batches for better progress feedback
            let batch_size = 32;
            for (batch_idx, batch) in nodes_to_embed.chunks(batch_size).enumerate() {
                spinner.set_message(format!(
                    "Generating embeddings... {}/{}",
                    (batch_idx * batch_size).min(total),
                    total
                ));

                // Create text content for each node
                let texts: Vec<String> = batch
                    .iter()
                    .map(|n| {
                        let type_prefix = match n.node_type {
                            mu_daemon::storage::NodeType::Module => "module",
                            mu_daemon::storage::NodeType::Class => "class",
                            mu_daemon::storage::NodeType::Function => "function",
                            mu_daemon::storage::NodeType::External => "external",
                        };
                        format!(
                            "{} {} {}",
                            type_prefix,
                            n.name,
                            n.qualified_name.as_deref().unwrap_or("")
                        )
                    })
                    .collect();

                let text_refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();

                match model.embed(&text_refs) {
                    Ok(batch_embeddings) => {
                        for (node, (text, embedding)) in
                            batch.iter().zip(texts.iter().zip(batch_embeddings))
                        {
                            embeddings_batch.push((node.id.clone(), embedding, Some(text.clone())));
                            embedded_count += 1;
                        }
                    }
                    Err(e) => {
                        tracing::warn!("Failed to embed batch: {}", e);
                    }
                }
            }

            // Clear existing embeddings and insert new ones
            if !embeddings_batch.is_empty() {
                spinner.set_message("Storing embeddings...");
                mubase.clear_embeddings()?;
                if let Err(e) =
                    mubase.insert_embeddings_batch(&embeddings_batch, Some("mu-sigma-v2"))
                {
                    tracing::warn!("Failed to store embeddings: {}", e);
                }
            }

            embedded_count
        }
        Err(e) => {
            spinner.finish_and_clear();
            anyhow::bail!("Failed to load embedding model: {}", e);
        }
    };

    spinner.finish_and_clear();

    let duration_ms = start.elapsed().as_millis() as u64;

    // Build a simple result for embedding-only mode
    let result = BootstrapResult {
        success: true,
        root_path: mubase_path
            .parent()
            .and_then(|p| p.parent())
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_default(),
        mubase_path: mubase_path.to_string_lossy().to_string(),
        files_scanned: 0,
        files_parsed: 0,
        files_cached: 0,
        node_count: stats.node_count,
        edge_count: stats.edge_count,
        nodes_by_type: stats.type_counts,
        duration_ms,
        config_created: false,
        gitignore_updated: false,
        embeddings_generated,
        hnsw_index_created: false, // HNSW not created in embedding-only mode
        fts_index_created: false,  // FTS not created in embedding-only mode
    };

    // Custom output for embedding-only mode
    if format == OutputFormat::Table {
        println!(
            "{} Generated {} embeddings in {}ms",
            "SUCCESS:".green().bold(),
            embeddings_generated.to_string().green(),
            duration_ms
        );
        println!("\n{}", "Semantic search is now ready!".cyan());
        println!("  mu search 'auth'       # Find authentication code");
        println!("  mu search 'database'   # Find database operations");
    } else {
        Output::new(result, format).render()?;
    }

    Ok(())
}

// ============================================================================
// Scanning & Parsing
// ============================================================================

/// Result of scanning and parsing the codebase.
struct ParsedCodebase {
    parse_results: Vec<mu_core::types::ParseResult>,
    files_scanned: usize,
    files_parsed: usize,
    files_cached: usize,
}

/// Scan the codebase and parse all source files, using cache when available.
fn scan_and_parse(
    root: &Path,
    config: &MuConfig,
    spinner: &ProgressBar,
) -> anyhow::Result<ParsedCodebase> {
    // Step 1: Scan codebase
    spinner.set_message("Scanning codebase...");
    let root_str = root.to_str().unwrap_or(".");
    let cache_enabled = config.cache_enabled();
    let ignore_patterns = config.ignore_patterns();

    // Build scan options from config
    let mut scan_options = mu_core::scanner::ScanOptions::new()
        .with_ignore_patterns(ignore_patterns)
        .include_hidden(config.scanner.include_hidden)
        .compute_hashes(cache_enabled);

    if let Some(max_size) = config.max_file_size_bytes() {
        scan_options = scan_options.with_max_file_size(max_size);
    }
    if let Some(languages) = config.languages() {
        scan_options = scan_options.with_languages(languages.to_vec());
    }

    let scan_result = mu_core::scanner::scan_with_options(root_str, scan_options)
        .map_err(|e| anyhow::anyhow!(e))?;

    let files_scanned = scan_result.files.len();
    spinner.set_message(format!("Found {} files", files_scanned));

    if files_scanned == 0 {
        return Ok(ParsedCodebase {
            parse_results: Vec::new(),
            files_scanned: 0,
            files_parsed: 0,
            files_cached: 0,
        });
    }

    // Step 2: Load cache and determine what needs parsing
    spinner.set_message("Loading cache...");
    let mut cache = if cache_enabled {
        ParseCache::load(config.cache_directory(), root)
    } else {
        ParseCache::new()
    };

    let mut cache_stats = CacheStats::default();
    let current_files: HashSet<String> = scan_result.files.iter().map(|f| f.path.clone()).collect();

    if cache_enabled && !cache.is_empty() {
        let before = cache.len();
        cache.prune(&current_files);
        cache_stats.pruned = before - cache.len();
    }

    // Separate files into cached vs needs-parsing
    spinner.set_message("Checking cache...");
    let mut cached_modules: Vec<mu_core::types::ParseResult> = Vec::new();
    let mut files_to_parse: Vec<(mu_core::scanner::ScannedFile, String)> = Vec::new();

    for scanned_file in &scan_result.files {
        let full_path = root.join(&scanned_file.path);
        let content = match fs::read_to_string(&full_path) {
            Ok(c) => c,
            Err(_) => continue,
        };

        if cache_enabled {
            if let Some(hash) = &scanned_file.hash {
                if let Some(cached_module) = cache.get(&scanned_file.path, hash) {
                    cached_modules.push(mu_core::types::ParseResult::ok(cached_module.clone()));
                    cache_stats.hits += 1;
                    continue;
                }
            }
        }

        cache_stats.misses += 1;
        files_to_parse.push((scanned_file.clone(), content));
    }

    // Parse files that weren't in cache
    spinner.set_message(format!(
        "Parsing {} files ({} cached)...",
        files_to_parse.len(),
        cache_stats.hits
    ));

    let file_infos: Vec<mu_core::types::FileInfo> = files_to_parse
        .iter()
        .map(|(f, content)| mu_core::types::FileInfo {
            path: f.path.clone(),
            source: content.clone(),
            language: f.language.clone(),
        })
        .collect();

    let fresh_parse_results = mu_core::parser::parse_files_parallel(file_infos, None);

    // Update cache with freshly parsed results
    if cache_enabled {
        for ((scanned_file, _content), result) in
            files_to_parse.iter().zip(fresh_parse_results.iter())
        {
            if result.success {
                if let (Some(hash), Some(module)) = (&scanned_file.hash, &result.module) {
                    cache.insert(scanned_file.path.clone(), hash.clone(), module.clone());
                }
            }
        }
        spinner.set_message("Saving cache...");
        if let Err(e) = cache.save(config.cache_directory(), root) {
            tracing::warn!("Failed to save parse cache: {}", e);
        }
    }

    let parse_results: Vec<mu_core::types::ParseResult> = cached_modules
        .into_iter()
        .chain(fresh_parse_results)
        .collect();

    Ok(ParsedCodebase {
        parse_results,
        files_scanned,
        files_parsed: cache_stats.misses,
        files_cached: cache_stats.hits,
    })
}

// ============================================================================
// Graph Building
// ============================================================================

/// Build graph nodes and edges from parsed modules.
fn build_graph(
    parse_results: &[mu_core::types::ParseResult],
    root: &Path,
    spinner: &ProgressBar,
) -> (Vec<mu_daemon::storage::Node>, Vec<mu_daemon::storage::Edge>) {
    spinner.set_message("Building graph...");

    // Load path alias resolver for TS/JS
    let path_alias_resolver = PathAliasResolver::from_project(root);
    if path_alias_resolver.is_some() {
        tracing::debug!("Loaded TypeScript path alias resolver");
    }

    // Build C# namespace map
    let csharp_namespace_map = build_csharp_namespace_map(parse_results);
    if !csharp_namespace_map.is_empty() {
        tracing::debug!("Built C# namespace map with {} namespaces", csharp_namespace_map.len());
    }

    let mut nodes = Vec::new();
    let mut edges = Vec::new();

    // Pre-pass: Build class lookup for inheritance resolution
    let class_lookup = build_class_lookup(parse_results);
    tracing::debug!("Built class lookup with {} entries", class_lookup.len());

    // Build nodes and containment/inheritance/import edges
    for result in parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            build_module_graph(
                module,
                &class_lookup,
                path_alias_resolver.as_ref(),
                &csharp_namespace_map,
                &mut nodes,
                &mut edges,
            );
        }
    }

    // Build function lookup for call resolution
    let func_lookup = build_function_lookup(&nodes);
    tracing::debug!("Built function lookup with {} entries", func_lookup.len());

    // Resolve call sites
    spinner.set_message("Resolving call sites...");
    let (total, resolved) = resolve_all_call_sites(parse_results, &func_lookup, &mut edges);
    tracing::info!(
        "Call sites: {} found, {} resolved ({:.1}%)",
        total,
        resolved,
        if total > 0 { (resolved as f64 / total as f64) * 100.0 } else { 0.0 }
    );

    (nodes, edges)
}

/// Build class name -> node ID lookup for inheritance resolution.
fn build_class_lookup(parse_results: &[mu_core::types::ParseResult]) -> HashMap<String, String> {
    let mut class_lookup = HashMap::new();
    for result in parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            for class in &module.classes {
                let class_id = format!("cls:{}:{}", module.path, class.name);
                class_lookup.insert(class.name.clone(), class_id);
            }
        }
    }
    class_lookup
}

/// Build function name -> node ID lookup for call resolution.
fn build_function_lookup(nodes: &[mu_daemon::storage::Node]) -> HashMap<String, String> {
    let mut func_lookup = HashMap::new();
    for node in nodes {
        if node.node_type == mu_daemon::storage::NodeType::Function {
            func_lookup.insert(node.id.clone(), node.id.clone());
            func_lookup.insert(node.name.clone(), node.id.clone());
            if let Some(ref qname) = node.qualified_name {
                func_lookup.insert(qname.clone(), node.id.clone());
            }
        }
    }
    func_lookup
}

/// Build graph nodes and edges for a single module.
fn build_module_graph(
    module: &mu_core::types::ModuleDef,
    class_lookup: &HashMap<String, String>,
    path_alias_resolver: Option<&PathAliasResolver>,
    csharp_namespace_map: &HashMap<String, Vec<String>>,
    nodes: &mut Vec<mu_daemon::storage::Node>,
    edges: &mut Vec<mu_daemon::storage::Edge>,
) {
    let rel_path = &module.path;

    // Create module node
    let module_node = mu_daemon::storage::Node::module(rel_path);
    let module_id = module_node.id.clone();
    nodes.push(module_node);

    // Create class nodes
    for class in &module.classes {
        let mut class_node = mu_daemon::storage::Node::class(
            rel_path,
            &class.name,
            class.start_line,
            class.end_line,
        );
        if let Some(ref docstring) = class.docstring {
            class_node = class_node.with_properties(json!({"docstring": docstring}));
        }
        let class_id = class_node.id.clone();
        nodes.push(class_node);
        edges.push(mu_daemon::storage::Edge::contains(&module_id, &class_id));

        // Inheritance edges
        for base in &class.bases {
            let base_id = class_lookup
                .get(base)
                .cloned()
                .unwrap_or_else(|| format!("ext:{}", base));
            edges.push(mu_daemon::storage::Edge::inherits(&class_id, &base_id));
        }

        // Method nodes
        for method in &class.methods {
            let mut method_node = mu_daemon::storage::Node::function(
                rel_path,
                &method.name,
                Some(&class.name),
                method.start_line,
                method.end_line,
                method.body_complexity,
            );
            if let Some(ref docstring) = method.docstring {
                method_node = method_node.with_properties(json!({"docstring": docstring}));
            }
            let method_id = method_node.id.clone();
            nodes.push(method_node);
            edges.push(mu_daemon::storage::Edge::contains(&class_id, &method_id));
        }
    }

    // Module-level function nodes
    for func in &module.functions {
        let mut func_node = mu_daemon::storage::Node::function(
            rel_path,
            &func.name,
            None,
            func.start_line,
            func.end_line,
            func.body_complexity,
        );
        if let Some(ref docstring) = func.docstring {
            func_node = func_node.with_properties(json!({"docstring": docstring}));
        }
        let func_id = func_node.id.clone();
        nodes.push(func_node);
        edges.push(mu_daemon::storage::Edge::contains(&module_id, &func_id));
    }

    // Import edges
    for import in &module.imports {
        let target_id = resolve_import(
            &import.module,
            rel_path,
            &module.language,
            path_alias_resolver,
            Some(csharp_namespace_map),
        );
        edges.push(mu_daemon::storage::Edge::imports(&module_id, &target_id));
    }
}

/// Resolve all call sites across all modules. Returns (total, resolved) counts.
fn resolve_all_call_sites(
    parse_results: &[mu_core::types::ParseResult],
    func_lookup: &HashMap<String, String>,
    edges: &mut Vec<mu_daemon::storage::Edge>,
) -> (usize, usize) {
    let mut total = 0usize;
    let mut resolved = 0usize;

    for result in parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            let rel_path = &module.path;

            // Class methods
            for class in &module.classes {
                for method in &class.methods {
                    let method_id = format!("fn:{}:{}.{}", rel_path, class.name, method.name);
                    total += method.call_sites.len();
                    for call in &method.call_sites {
                        if let Some(target_id) = resolve_call_site(
                            call,
                            rel_path,
                            Some(&class.name),
                            func_lookup,
                            &module.imports,
                        ) {
                            edges.push(mu_daemon::storage::Edge::calls(&method_id, &target_id));
                            resolved += 1;
                        }
                    }
                }
            }

            // Module-level functions
            for func in &module.functions {
                let func_id = format!("fn:{}:{}", rel_path, func.name);
                total += func.call_sites.len();
                for call in &func.call_sites {
                    if let Some(target_id) =
                        resolve_call_site(call, rel_path, None, func_lookup, &module.imports)
                    {
                        edges.push(mu_daemon::storage::Edge::calls(&func_id, &target_id));
                        resolved += 1;
                    }
                }
            }
        }
    }

    (total, resolved)
}

// ============================================================================
// Embeddings
// ============================================================================

/// Generate embeddings for nodes and store them in the database.
fn generate_embeddings(
    nodes: &[mu_daemon::storage::Node],
    mubase: &mu_daemon::storage::MUbase,
    spinner: &ProgressBar,
) -> usize {
    spinner.set_message("Loading embedding model...");

    let model = match mu_embeddings::MuSigmaModel::embedded() {
        Ok(m) => m,
        Err(e) => {
            tracing::warn!("Failed to load embedding model: {}", e);
            return 0;
        }
    };

    spinner.set_message("Generating embeddings...");

    let nodes_to_embed: Vec<_> = nodes
        .iter()
        .filter(|n| n.node_type != mu_daemon::storage::NodeType::External)
        .collect();

    let total = nodes_to_embed.len();
    let mut embeddings_batch = Vec::new();
    let mut embedded_count = 0;
    let batch_size = 32;

    for (batch_idx, batch) in nodes_to_embed.chunks(batch_size).enumerate() {
        spinner.set_message(format!(
            "Generating embeddings... {}/{}",
            (batch_idx * batch_size).min(total),
            total
        ));

        let texts: Vec<String> = batch
            .iter()
            .map(|n| {
                let type_prefix = match n.node_type {
                    mu_daemon::storage::NodeType::Module => "module",
                    mu_daemon::storage::NodeType::Class => "class",
                    mu_daemon::storage::NodeType::Function => "function",
                    mu_daemon::storage::NodeType::External => "external",
                };
                format!("{} {} {}", type_prefix, n.name, n.qualified_name.as_deref().unwrap_or(""))
            })
            .collect();

        let text_refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();

        match model.embed(&text_refs) {
            Ok(batch_embeddings) => {
                for (node, (text, embedding)) in batch.iter().zip(texts.iter().zip(batch_embeddings))
                {
                    embeddings_batch.push((node.id.clone(), embedding, Some(text.clone())));
                    embedded_count += 1;
                }
            }
            Err(e) => {
                tracing::warn!("Failed to embed batch: {}", e);
            }
        }
    }

    if !embeddings_batch.is_empty() {
        spinner.set_message("Storing embeddings...");
        if let Err(e) = mubase.insert_embeddings_batch(&embeddings_batch, Some("mu-sigma-v2")) {
            tracing::warn!("Failed to store embeddings: {}", e);
        }
    }

    embedded_count
}

// ============================================================================
// Main Entry Point
// ============================================================================

/// Create a spinner for progress display.
fn create_spinner() -> ProgressBar {
    let spinner = ProgressBar::new_spinner();
    spinner.set_style(
        ProgressStyle::default_spinner()
            .tick_chars("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
            .template("{spinner:.cyan} {msg}")
            .unwrap(),
    );
    spinner.enable_steady_tick(std::time::Duration::from_millis(100));
    spinner
}

/// Run the bootstrap command
pub async fn run(
    path: &str,
    force: bool,
    embed: bool,
    no_embed: bool,
    hnsw: bool,
    no_hnsw: bool,
    strict: bool,
    format: OutputFormat,
) -> anyhow::Result<()> {
    let start = Instant::now();

    // Resolve and validate path
    let root = Path::new(path)
        .canonicalize()
        .unwrap_or_else(|_| Path::new(path).to_path_buf());

    if !root.exists() {
        anyhow::bail!("Path does not exist: {}", root.display());
    }
    if !root.is_dir() {
        anyhow::bail!("Path is not a directory: {}", root.display());
    }

    // Setup: config and gitignore
    let config_created = ensure_config(&root);
    let gitignore_updated = update_gitignore(&root);

    // Load configuration
    let config = if strict {
        MuConfig::load_strict(&root)?
    } else {
        MuConfig::load(&root)
    };
    tracing::debug!("Loaded ignore patterns: {:?}", config.ignore_patterns());

    // Determine mubase path
    let mu_dir = root.join(".mu");
    let mubase_path = mu_dir.join("mubase");

    // Check if rebuild is needed
    if mubase_path.exists() && !force {
        if embed {
            return run_embeddings_only(&mubase_path, format).await;
        }

        let mubase = mu_daemon::storage::MUbase::open(&mubase_path)?;
        let stats = mubase.stats()?;
        println!(
            "{} MU already initialized. Use --force to rebuild.",
            "INFO:".yellow().bold()
        );
        println!("  Nodes: {}", stats.node_count);
        println!("  Edges: {}", stats.edge_count);
        return Ok(());
    }

    // Create .mu directory
    if !mu_dir.exists() {
        fs::create_dir_all(&mu_dir)?;
    }

    let do_embed = should_embed(embed, no_embed);
    let spinner = create_spinner();

    // Step 1: Scan and parse
    let parsed = scan_and_parse(&root, &config, &spinner)?;
    if parsed.files_scanned == 0 {
        spinner.finish_and_clear();
        println!(
            "{} No supported files found in {}",
            "WARNING:".yellow().bold(),
            root.display()
        );
        return Ok(());
    }

    // Step 2: Build graph
    let (nodes, edges) = build_graph(&parsed.parse_results, &root, &spinner);

    // Step 3: Write to database
    spinner.set_message("Writing database...");
    let mubase = mu_daemon::storage::MUbase::open(&mubase_path)?;
    mubase.clear()?;
    mubase.insert_nodes(&nodes)?;
    mubase.insert_edges(&edges)?;
    let stats = mubase.stats()?;

    // Step 4: Generate embeddings
    let embeddings_generated = if do_embed {
        generate_embeddings(&nodes, &mubase, &spinner)
    } else {
        0
    };

    spinner.finish_and_clear();

    // Step 5: Create HNSW index (optional, based on flags and embedding count)
    let hnsw_index_created = if embeddings_generated > 0 && should_hnsw(hnsw, no_hnsw, embeddings_generated) {
        let spinner = create_spinner();
        spinner.set_message("Creating HNSW index...");

        match mubase.create_hnsw_index() {
            Ok(created) => {
                spinner.finish_and_clear();
                if created {
                    tracing::info!("HNSW index created successfully");
                }
                created
            }
            Err(e) => {
                spinner.finish_and_clear();
                // Don't fail bootstrap if HNSW creation fails - it's optional
                tracing::warn!("Failed to create HNSW index: {}", e);
                println!(
                    "{} HNSW index creation failed: {}",
                    "WARNING:".yellow().bold(),
                    e
                );
                println!("         Vector search will use linear scan (still functional).\n");
                false
            }
        }
    } else {
        false
    };

    // Step 6: Create FTS index for BM25 keyword search (always, if nodes exist)
    let fts_index_created = {
        let spinner = create_spinner();
        spinner.set_message("Creating FTS index for keyword search...");

        match mubase.create_fts_index() {
            Ok(created) => {
                spinner.finish_and_clear();
                if created {
                    tracing::info!("FTS index created successfully");
                }
                created
            }
            Err(e) => {
                spinner.finish_and_clear();
                // Don't fail bootstrap if FTS creation fails - fallback to LIKE search
                tracing::warn!("Failed to create FTS index: {}", e);
                false
            }
        }
    };

    // Output result
    let result = BootstrapResult {
        success: true,
        root_path: root.to_string_lossy().to_string(),
        mubase_path: mubase_path.to_string_lossy().to_string(),
        files_scanned: parsed.files_scanned,
        files_parsed: parsed.files_parsed,
        files_cached: parsed.files_cached,
        node_count: stats.node_count,
        edge_count: stats.edge_count,
        nodes_by_type: stats.type_counts,
        duration_ms: start.elapsed().as_millis() as u64,
        config_created,
        gitignore_updated,
        embeddings_generated,
        hnsw_index_created,
        fts_index_created,
    };

    Output::new(result, format).render()
}

/// Build a namespace-to-file mapping for C# modules.
/// This enables resolving C# `using` statements to actual source files.
fn build_csharp_namespace_map(
    parse_results: &[mu_core::types::ParseResult],
) -> HashMap<String, Vec<String>> {
    let mut map: HashMap<String, Vec<String>> = HashMap::new();

    for result in parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            if module.language == "csharp" {
                if let Some(ref namespace) = module.namespace {
                    map.entry(namespace.clone())
                        .or_default()
                        .push(module.path.clone());
                }
            }
        }
    }

    map
}

/// Resolve a C# using statement to a module ID.
/// Tries to match the using statement against known namespaces from the project.
fn resolve_csharp_import(using_stmt: &str, namespace_map: &HashMap<String, Vec<String>>) -> String {
    // Try exact namespace match
    if let Some(files) = namespace_map.get(using_stmt) {
        if files.len() == 1 {
            // Single file in namespace - direct reference
            return format!("mod:{}", files[0]);
        }
        // Multiple files in namespace - use namespace as module identifier
        // This creates a "virtual" module representing the namespace
        return format!("mod:{}", using_stmt.replace('.', "/"));
    }

    // Try prefix match (e.g., "Company.App.Services.Auth" might match "Company.App.Services")
    // Find the longest matching prefix
    let mut best_match: Option<(&String, &Vec<String>)> = None;
    for (ns, files) in namespace_map {
        if using_stmt.starts_with(ns.as_str()) {
            // Check if this is a longer match than our current best
            if best_match.is_none_or(|(best_ns, _)| ns.len() > best_ns.len()) {
                best_match = Some((ns, files));
            }
        }
    }

    if let Some((matched_ns, files)) = best_match {
        if files.len() == 1 {
            return format!("mod:{}", files[0]);
        }
        // Use the matched namespace path
        return format!("mod:{}", matched_ns.replace('.', "/"));
    }

    // Check if it's a .NET system namespace
    if using_stmt.starts_with("System")
        || using_stmt.starts_with("Microsoft")
        || using_stmt.starts_with("Newtonsoft")
        || using_stmt.starts_with("NUnit")
        || using_stmt.starts_with("Xunit")
        || using_stmt.starts_with("Moq")
        || using_stmt.starts_with("FluentAssertions")
        || using_stmt.starts_with("Serilog")
        || using_stmt.starts_with("AutoMapper")
        || using_stmt.starts_with("MediatR")
        || using_stmt.starts_with("FluentValidation")
    {
        return format!("ext:{}", using_stmt);
    }

    // Unknown namespace - assume external
    format!("ext:{}", using_stmt)
}

/// Resolve an import statement to a module ID
/// Check if an import is TypeScript style (uses slashes like ./foo, ../foo)
fn is_typescript_style_import(import_path: &str) -> bool {
    import_path.starts_with("./") || import_path.starts_with("../")
}

/// Resolve a TypeScript/JavaScript style import (./foo, ../foo)
fn resolve_typescript_import(import_path: &str, source_file: &str) -> String {
    let source_path = std::path::Path::new(source_file);
    let source_dir = source_path.parent().unwrap_or(std::path::Path::new(""));

    // Parse the import path to count "../" segments and extract the remainder
    let mut path_parts: Vec<&str> = import_path.split('/').collect();
    let mut levels_up = 0;

    // Count and consume leading ".." and "." segments
    while !path_parts.is_empty() {
        match path_parts[0] {
            ".." => {
                levels_up += 1;
                path_parts.remove(0);
            }
            "." => {
                path_parts.remove(0);
            }
            "" => {
                path_parts.remove(0);
            }
            _ => break,
        }
    }

    // Navigate up the directory tree
    let mut base_path = source_dir.to_path_buf();
    for _ in 0..levels_up {
        if let Some(parent) = base_path.parent() {
            base_path = parent.to_path_buf();
        }
    }

    // Join the remaining path parts
    let remainder = path_parts.join("/");
    let resolved = if remainder.is_empty() {
        base_path
    } else {
        base_path.join(&remainder)
    };

    let resolved_str = resolved.to_string_lossy().to_string();

    // For TypeScript imports, we need to handle:
    // 1. Direct file imports: ./foo -> ./foo.ts
    // 2. Directory imports: ./client -> ./client/index.ts
    // We'll prefer index.ts for paths that look like directories
    let final_path = if resolved_str.contains('.') && !resolved_str.ends_with('/') {
        // Already has extension
        resolved_str
    } else if resolved_str.is_empty() {
        source_dir.to_string_lossy().to_string()
    } else {
        // Check if this looks like a directory (no extension, not ending with common file patterns)
        // Try index.ts first (common TS pattern), then .ts
        format!("{}/index.ts", resolved_str)
    };

    format!("mod:{}", final_path)
}

/// Resolve a Python style relative import (..foo, .foo)
fn resolve_python_import(import_path: &str, source_file: &str) -> String {
    // Count leading dots
    let dot_count = import_path.chars().take_while(|&c| c == '.').count();
    let remainder = &import_path[dot_count..];

    let source_path = std::path::Path::new(source_file);
    let source_dir = source_path.parent().unwrap_or(std::path::Path::new(""));

    // Navigate up (dot_count - 1) directories
    let levels_up = dot_count.saturating_sub(1);
    let mut base_path = source_dir.to_path_buf();
    for _ in 0..levels_up {
        if let Some(parent) = base_path.parent() {
            base_path = parent.to_path_buf();
        }
    }

    // Append the remainder (converting dots to path separators)
    let remainder_path = remainder.replace('.', "/");
    let resolved = if remainder_path.is_empty() {
        base_path
    } else {
        base_path.join(&remainder_path)
    };

    let resolved_str = resolved.to_string_lossy().to_string();

    // Add .py extension if appropriate
    let final_path = if resolved_str.is_empty() {
        source_dir.to_string_lossy().to_string()
    } else if remainder_path.is_empty() {
        resolved_str
    } else if !resolved_str.contains('.') || resolved_str.ends_with('/') {
        format!("{}.py", resolved_str)
    } else {
        resolved_str
    };

    format!("mod:{}", final_path)
}

fn resolve_import(
    import_path: &str,
    source_file: &str,
    language: &str,
    path_alias_resolver: Option<&PathAliasResolver>,
    csharp_namespace_map: Option<&HashMap<String, Vec<String>>>,
) -> String {
    // C# uses namespace-based imports - use our namespace map
    if language == "csharp" {
        if let Some(ns_map) = csharp_namespace_map {
            return resolve_csharp_import(import_path, ns_map);
        }
        // Fallback if no namespace map
        return format!("ext:{}", import_path);
    }

    // First, try TypeScript path aliases (e.g., @/lib/logger, @components/Button)
    // This takes priority for non-relative imports
    if let Some(resolver) = path_alias_resolver {
        if let Some(resolved) = resolver.resolve(import_path) {
            return resolved;
        }
    }

    // TypeScript/JS style imports (./foo, ../foo)
    if is_typescript_style_import(import_path) {
        return resolve_typescript_import(import_path, source_file);
    }

    // Python style relative imports (..foo, .foo)
    if import_path.starts_with('.') {
        return resolve_python_import(import_path, source_file);
    }

    // Absolute imports
    let path = import_path.replace('.', "/");
    if import_path.contains('.') {
        // Qualified import (could be internal or external)
        format!("mod:{}", path)
    } else {
        // Single name - likely external package
        format!("ext:{}", import_path)
    }
}

/// Resolve a call site to a function/method node ID.
/// Returns None if the call cannot be resolved (external function, unresolvable reference).
fn resolve_call_site(
    call: &mu_core::types::CallSiteDef,
    current_module: &str,
    current_class: Option<&str>,
    func_lookup: &HashMap<String, String>,
    imports: &[mu_core::types::ImportDef],
) -> Option<String> {
    let callee = &call.callee;

    // 1. Method call on self/this - look in current class
    // Python: self, cls | C#/Java: this, base/super | Rust: self
    if call.is_method_call {
        if let Some(receiver) = &call.receiver {
            if receiver == "self"
                || receiver == "cls"
                || receiver == "this"
                || receiver == "base"
                || receiver == "super"
            {
                if let Some(class_name) = current_class {
                    // Try: fn:module:Class.method
                    let method_id = format!("fn:{}:{}.{}", current_module, class_name, callee);
                    if func_lookup.contains_key(&method_id) {
                        return Some(method_id);
                    }
                }
            }
        }
    }

    // 2. Check local functions in same module
    let local_fn_id = format!("fn:{}:{}", current_module, callee);
    if func_lookup.contains_key(&local_fn_id) {
        return Some(local_fn_id);
    }

    // 3. Check local class methods (for current class)
    if let Some(class_name) = current_class {
        let local_method_id = format!("fn:{}:{}.{}", current_module, class_name, callee);
        if func_lookup.contains_key(&local_method_id) {
            return Some(local_method_id);
        }
    }

    // 4. Check by simple name (may match if unique in codebase)
    if let Some(target_id) = func_lookup.get(callee) {
        return Some(target_id.clone());
    }

    // 5. Check imported names
    for import in imports {
        if import.names.contains(&callee.to_string()) {
            // Resolve to imported module's function
            let import_path = import.module.replace('.', "/");
            let imported_fn_id = format!("fn:{}:{}", import_path, callee);
            if func_lookup.contains_key(&imported_fn_id) {
                return Some(imported_fn_id);
            }
            // Also try with .py extension for Python
            let imported_fn_id_py = format!("fn:{}.py:{}", import_path, callee);
            if func_lookup.contains_key(&imported_fn_id_py) {
                return Some(imported_fn_id_py);
            }
        }
    }

    // 6. Check qualified calls (e.g., module.function or Class.static_method)
    if callee.contains('.') {
        let parts: Vec<&str> = callee.rsplitn(2, '.').collect();
        if parts.len() == 2 {
            let func_name = parts[0];
            let qualifier = parts[1];

            // Try as Class.method in current module
            let qualified_id = format!("fn:{}:{}.{}", current_module, qualifier, func_name);
            if func_lookup.contains_key(&qualified_id) {
                return Some(qualified_id);
            }

            // Try as module.function (check imports)
            for import in imports {
                if import.module.ends_with(qualifier) || import.alias.as_deref() == Some(qualifier)
                {
                    let import_path = import.module.replace('.', "/");
                    let imported_fn_id = format!("fn:{}:{}", import_path, func_name);
                    if func_lookup.contains_key(&imported_fn_id) {
                        return Some(imported_fn_id);
                    }
                }
            }
        }
    }

    // 7. Unresolved - return None (no edge created)
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolve_import_external() {
        // External single-name imports
        assert_eq!(
            resolve_import("os", "src/main.py", "python", None, None),
            "ext:os"
        );
        assert_eq!(
            resolve_import("typing", "src/main.py", "python", None, None),
            "ext:typing"
        );
    }

    #[test]
    fn test_resolve_import_qualified() {
        // Qualified absolute imports
        assert_eq!(
            resolve_import("mu.core", "src/main.py", "python", None, None),
            "mod:mu/core"
        );
    }

    #[test]
    fn test_resolve_python_relative_import() {
        // Python relative imports (.foo, ..foo)
        assert_eq!(
            resolve_import(".utils", "src/mu/commands/routing.py", "python", None, None),
            "mod:src/mu/commands/utils.py"
        );
        assert_eq!(
            resolve_import(
                "..kernel.builder",
                "src/mu/commands/routing.py",
                "python",
                None,
                None
            ),
            "mod:src/mu/kernel/builder.py"
        );
    }

    #[test]
    fn test_resolve_typescript_import() {
        // TypeScript relative imports (./foo, ../foo)
        // Without knowing if the target is a file or directory, we assume directory/index.ts
        assert_eq!(
            resolve_import(
                "./client",
                "tools/vscode-mu/src/extension.ts",
                "typescript",
                None,
                None
            ),
            "mod:tools/vscode-mu/src/client/index.ts"
        );
        assert_eq!(
            resolve_import(
                "../utils",
                "tools/vscode-mu/src/test/index.ts",
                "typescript",
                None,
                None
            ),
            "mod:tools/vscode-mu/src/utils/index.ts"
        );
        assert_eq!(
            resolve_import(
                "../../client",
                "tools/vscode-mu/src/test/suite/commands.test.ts",
                "typescript",
                None,
                None
            ),
            "mod:tools/vscode-mu/src/client/index.ts"
        );
    }

    #[test]
    fn test_resolve_typescript_import_with_extension() {
        // Explicit extension is preserved
        assert_eq!(
            resolve_import(
                "./client.ts",
                "tools/vscode-mu/src/extension.ts",
                "typescript",
                None,
                None
            ),
            "mod:tools/vscode-mu/src/client.ts"
        );
        assert_eq!(
            resolve_import(
                "./MUClient.tsx",
                "tools/vscode-mu/src/extension.ts",
                "typescript",
                None,
                None
            ),
            "mod:tools/vscode-mu/src/MUClient.tsx"
        );
    }

    #[test]
    fn test_resolve_typescript_deep_navigation() {
        // Deep relative navigation (5 levels up)
        // Source: tools/vscode-mu/src/test/suite/commands.test.ts
        // Going up 5 levels: suite->test->src->vscode-mu->tools->root
        assert_eq!(
            resolve_import(
                "../../../../../commands/query",
                "tools/vscode-mu/src/test/suite/commands.test.ts",
                "typescript",
                None,
                None
            ),
            "mod:commands/query/index.ts"
        );
    }

    #[test]
    fn test_resolve_csharp_import_with_namespace_map() {
        // Build a test namespace map
        let mut namespace_map = HashMap::new();
        namespace_map.insert(
            "DominaiteGateway.Api.Services".to_string(),
            vec!["src/Services/MyService.cs".to_string()],
        );
        namespace_map.insert(
            "DominaiteGateway.Api.Controllers".to_string(),
            vec![
                "src/Controllers/HomeController.cs".to_string(),
                "src/Controllers/ApiController.cs".to_string(),
            ],
        );

        // Exact match with single file
        assert_eq!(
            resolve_import(
                "DominaiteGateway.Api.Services",
                "src/Controllers/HomeController.cs",
                "csharp",
                None,
                Some(&namespace_map)
            ),
            "mod:src/Services/MyService.cs"
        );

        // Exact match with multiple files - uses namespace path
        assert_eq!(
            resolve_import(
                "DominaiteGateway.Api.Controllers",
                "src/Services/MyService.cs",
                "csharp",
                None,
                Some(&namespace_map)
            ),
            "mod:DominaiteGateway/Api/Controllers"
        );

        // System namespace - external
        assert_eq!(
            resolve_import(
                "System.Net.Http",
                "src/Services/MyService.cs",
                "csharp",
                None,
                Some(&namespace_map)
            ),
            "ext:System.Net.Http"
        );

        // Unknown namespace - external
        assert_eq!(
            resolve_import(
                "SomeOther.Library",
                "src/Services/MyService.cs",
                "csharp",
                None,
                Some(&namespace_map)
            ),
            "ext:SomeOther.Library"
        );
    }

    #[test]
    fn test_resolve_csharp_import_prefix_match() {
        // Test prefix matching for nested namespaces
        let mut namespace_map = HashMap::new();
        namespace_map.insert(
            "Company.App.Services".to_string(),
            vec!["src/Services/Base.cs".to_string()],
        );

        // Trying to import Company.App.Services.Auth should match Company.App.Services
        assert_eq!(
            resolve_import(
                "Company.App.Services.Auth",
                "src/Controllers/Ctrl.cs",
                "csharp",
                None,
                Some(&namespace_map)
            ),
            "mod:src/Services/Base.cs"
        );
    }

    #[test]
    fn test_default_config_is_valid_toml() {
        let config = get_default_config();
        toml::from_str::<toml::Value>(config).expect("Default config should be valid TOML");
    }
}
