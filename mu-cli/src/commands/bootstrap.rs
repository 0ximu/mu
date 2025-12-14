//! Bootstrap command - Initialize and build MU database in one step
//!
//! This command:
//! 1. Creates .murc.toml config if missing
//! 2. Adds .mu/ to .gitignore
//! 3. Builds the .mu/mubase code graph
//! 4. Shows progress and final stats

use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::time::Instant;

use colored::Colorize;
use indicatif::{ProgressBar, ProgressStyle};
use serde::Serialize;

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
    pub node_count: usize,
    pub edge_count: usize,
    pub nodes_by_type: HashMap<String, usize>,
    pub duration_ms: u64,
    pub config_created: bool,
    pub gitignore_updated: bool,
    pub embeddings_generated: usize,
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

        if self.config_created || self.gitignore_updated {
            output.push_str(&format!("\n{}\n", "Setup".cyan().bold()));
            if self.config_created {
                output.push_str("  Created .murc.toml\n");
            }
            if self.gitignore_updated {
                output.push_str("  Updated .gitignore\n");
            }
        }

        if self.embeddings_generated > 0 {
            output.push_str(&format!("\n{}\n", "Embeddings".cyan().bold()));
            output.push_str(&format!(
                "  Generated: {} (semantic search ready)\n",
                self.embeddings_generated.to_string().green()
            ));
        }

        output.push_str(&format!("\n{}\n", "Next Steps".cyan().bold()));
        output.push_str("  mu status              # Check status\n");
        output.push_str("  mu query 'functions'   # Query the graph\n");
        if self.embeddings_generated > 0 {
            output.push_str("  mu search 'auth'       # Semantic search\n");
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
# https://github.com/dominaite/mu

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
languages = "auto"

[output]
format = "mu"
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

/// Run the bootstrap command
pub async fn run(path: &str, force: bool, embed: bool, format: OutputFormat) -> anyhow::Result<()> {
    let start = Instant::now();

    // Resolve and canonicalize path
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

    // Load configuration (after ensuring config exists)
    let config = MuConfig::load(&root);
    let ignore_patterns = config.ignore_patterns();
    tracing::debug!("Loaded ignore patterns: {:?}", ignore_patterns);

    // Determine mubase path
    let mu_dir = root.join(".mu");
    let mubase_path = mu_dir.join("mubase");

    // Check if rebuild is needed
    if mubase_path.exists() && !force {
        // Open existing database and show stats
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

    // Create .mu directory if needed
    if !mu_dir.exists() {
        fs::create_dir_all(&mu_dir)?;
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

    // Step 1: Scan codebase
    spinner.set_message("Scanning codebase...");
    let root_str = root.to_str().unwrap_or(".");
    let scan_result = mu_core::scanner::scan_directory_sync(
        root_str,
        None,
        Some(ignore_patterns),
        false,
        false,
        false,
    )
    .map_err(|e| anyhow::anyhow!(e))?;

    let files_scanned = scan_result.files.len();
    spinner.set_message(format!("Found {} files", files_scanned));

    if files_scanned == 0 {
        spinner.finish_and_clear();
        println!(
            "{} No supported files found in {}",
            "WARNING:".yellow().bold(),
            root.display()
        );
        return Ok(());
    }

    // Step 2: Parse files
    spinner.set_message("Parsing files...");
    let file_infos: Vec<mu_core::types::FileInfo> = scan_result
        .files
        .iter()
        .filter_map(|f| {
            let full_path = root.join(&f.path);
            let content = fs::read_to_string(&full_path).ok()?;
            Some(mu_core::types::FileInfo {
                path: f.path.clone(),
                source: content,
                language: f.language.clone(),
            })
        })
        .collect();

    let parse_results = mu_core::parser::parse_files_parallel(file_infos, None);
    let files_parsed = parse_results.iter().filter(|r| r.success).count();
    spinner.set_message(format!("Parsed {} files", files_parsed));

    // Step 3: Build graph
    spinner.set_message("Building graph...");

    // Load TypeScript/JavaScript path alias resolver if available
    let path_alias_resolver = PathAliasResolver::from_project(&root);
    if path_alias_resolver.is_some() {
        tracing::debug!("Loaded TypeScript path alias resolver from tsconfig.json/jsconfig.json");
    }

    // Build C# namespace-to-file mapping for resolving using statements
    let csharp_namespace_map = build_csharp_namespace_map(&parse_results);
    if !csharp_namespace_map.is_empty() {
        tracing::debug!(
            "Built C# namespace map with {} namespaces",
            csharp_namespace_map.len()
        );
    }

    let mut nodes = Vec::new();
    let mut edges = Vec::new();

    // Pre-pass: Build class/interface lookup map for inheritance resolution
    // Maps simple name (e.g., "BaseService") to full node ID (e.g., "cls:src/.../BaseService.cs:BaseService")
    let mut class_lookup: HashMap<String, String> = HashMap::new();
    for result in &parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            let rel_path = &module.path;
            for class in &module.classes {
                let class_id = format!("cls:{}:{}", rel_path, class.name);
                // Map by simple name (may have collisions, last one wins)
                class_lookup.insert(class.name.clone(), class_id.clone());
                // Also map interface names (IFoo -> cls:...:IFoo)
                // This helps resolve interface implementations
            }
        }
    }
    tracing::debug!("Built class lookup with {} entries", class_lookup.len());

    for result in &parse_results {
        if !result.success {
            continue;
        }

        if let Some(ref module) = result.module {
            // Make path relative (it should already be relative from scan)
            let rel_path = &module.path;

            // Create module node
            let module_node = mu_daemon::storage::Node::module(rel_path);
            let module_id = module_node.id.clone();
            nodes.push(module_node);

            // Create class nodes
            for class in &module.classes {
                let class_node = mu_daemon::storage::Node::class(
                    rel_path,
                    &class.name,
                    class.start_line,
                    class.end_line,
                );
                let class_id = class_node.id.clone();
                nodes.push(class_node);

                // Module contains class
                edges.push(mu_daemon::storage::Edge::contains(&module_id, &class_id));

                // Inheritance edges - resolve to internal class if found
                for base in &class.bases {
                    let base_id = if let Some(resolved_id) = class_lookup.get(base) {
                        // Found in codebase - use actual class ID
                        resolved_id.clone()
                    } else {
                        // Not found - mark as external reference
                        format!("ext:{}", base)
                    };
                    edges.push(mu_daemon::storage::Edge::inherits(&class_id, &base_id));
                }

                // Create method nodes
                for method in &class.methods {
                    let method_node = mu_daemon::storage::Node::function(
                        rel_path,
                        &method.name,
                        Some(&class.name),
                        method.start_line,
                        method.end_line,
                        method.body_complexity,
                    );
                    let method_id = method_node.id.clone();
                    nodes.push(method_node);

                    // Class contains method
                    edges.push(mu_daemon::storage::Edge::contains(&class_id, &method_id));
                }
            }

            // Create function nodes (module-level)
            for func in &module.functions {
                let func_node = mu_daemon::storage::Node::function(
                    rel_path,
                    &func.name,
                    None,
                    func.start_line,
                    func.end_line,
                    func.body_complexity,
                );
                let func_id = func_node.id.clone();
                nodes.push(func_node);

                // Module contains function
                edges.push(mu_daemon::storage::Edge::contains(&module_id, &func_id));
            }

            // Create import edges
            for import in &module.imports {
                let target_id = resolve_import(
                    &import.module,
                    rel_path,
                    &module.language,
                    path_alias_resolver.as_ref(),
                    Some(&csharp_namespace_map),
                );
                edges.push(mu_daemon::storage::Edge::imports(&module_id, &target_id));
            }
        }
    }

    // Build func_lookup map for call resolution
    // Maps: simple name, qualified name, and full ID -> node ID
    let mut func_lookup: HashMap<String, String> = HashMap::new();
    for node in &nodes {
        if node.node_type == mu_daemon::storage::NodeType::Function {
            // Map by full ID for exact match
            func_lookup.insert(node.id.clone(), node.id.clone());
            // Map by simple name for fallback
            func_lookup.insert(node.name.clone(), node.id.clone());
            // Map by qualified name for disambiguation
            if let Some(ref qname) = node.qualified_name {
                func_lookup.insert(qname.clone(), node.id.clone());
            }
        }
    }
    tracing::debug!("Built function lookup with {} entries", func_lookup.len());

    // Pass 2: Create CALLS edges from call_sites
    spinner.set_message("Resolving call sites...");
    let mut total_call_sites = 0usize;
    let mut resolved_call_sites = 0usize;

    for result in &parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            let rel_path = &module.path;

            // Process class methods
            for class in &module.classes {
                for method in &class.methods {
                    let method_id = format!("fn:{}:{}.{}", rel_path, class.name, method.name);
                    total_call_sites += method.call_sites.len();
                    for call in &method.call_sites {
                        if let Some(target_id) = resolve_call_site(
                            call,
                            rel_path,
                            Some(&class.name),
                            &func_lookup,
                            &module.imports,
                        ) {
                            edges.push(mu_daemon::storage::Edge::calls(&method_id, &target_id));
                            resolved_call_sites += 1;
                        }
                    }
                }
            }

            // Process module-level functions
            for func in &module.functions {
                let func_id = format!("fn:{}:{}", rel_path, func.name);
                total_call_sites += func.call_sites.len();
                for call in &func.call_sites {
                    if let Some(target_id) =
                        resolve_call_site(call, rel_path, None, &func_lookup, &module.imports)
                    {
                        edges.push(mu_daemon::storage::Edge::calls(&func_id, &target_id));
                        resolved_call_sites += 1;
                    }
                }
            }
        }
    }

    tracing::info!(
        "Call sites: {} found, {} resolved ({:.1}%)",
        total_call_sites,
        resolved_call_sites,
        if total_call_sites > 0 {
            (resolved_call_sites as f64 / total_call_sites as f64) * 100.0
        } else {
            0.0
        }
    );

    spinner.set_message("Writing database...");

    // Step 4: Write to database
    let mubase = mu_daemon::storage::MUbase::open(&mubase_path)?;
    mubase.clear()?;
    mubase.insert_nodes(&nodes)?;
    mubase.insert_edges(&edges)?;

    // Get final stats
    let stats = mubase.stats()?;

    // Step 5: Generate embeddings if requested
    let embeddings_generated = if embed {
        spinner.set_message("Loading embedding model...");

        // Use embedded model weights (compiled into the binary)
        match mu_embeddings::MuSigmaModel::embedded() {
            Ok(model) => {
                spinner.set_message("Generating embeddings...");

                // Embed all non-external nodes
                let nodes_to_embed: Vec<_> = nodes
                    .iter()
                    .filter(|n| n.node_type != mu_daemon::storage::NodeType::External)
                    .collect();

                let total = nodes_to_embed.len();
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
                            // Create a semantic text representation of the node
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

                    // Convert to &str slice for embedding
                    let text_refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();

                    match model.embed(&text_refs) {
                        Ok(batch_embeddings) => {
                            for (node, (text, embedding)) in
                                batch.iter().zip(texts.iter().zip(batch_embeddings))
                            {
                                embeddings_batch.push((
                                    node.id.clone(),
                                    embedding,
                                    Some(text.clone()),
                                ));
                                embedded_count += 1;
                            }
                        }
                        Err(e) => {
                            tracing::warn!("Failed to embed batch: {}", e);
                        }
                    }
                }

                // Insert all embeddings
                if !embeddings_batch.is_empty() {
                    spinner.set_message("Storing embeddings...");
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
                println!(
                    "{} Failed to load embedding model: {}",
                    "WARNING:".yellow().bold(),
                    e
                );
                0
            }
        }
    } else {
        0
    };

    spinner.finish_and_clear();

    let duration_ms = start.elapsed().as_millis() as u64;

    let result = BootstrapResult {
        success: true,
        root_path: root.to_string_lossy().to_string(),
        mubase_path: mubase_path.to_string_lossy().to_string(),
        files_scanned,
        files_parsed,
        node_count: stats.node_count,
        edge_count: stats.edge_count,
        nodes_by_type: stats.type_counts,
        duration_ms,
        config_created,
        gitignore_updated,
        embeddings_generated,
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
            if best_match.map_or(true, |(best_ns, _)| ns.len() > best_ns.len()) {
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
