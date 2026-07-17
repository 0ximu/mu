//! Bootstrap command - Initialize and build MU database in one step
//!
//! This command:
//! 1. Creates .murc.toml config if missing
//! 2. Adds .mu/ to .gitignore
//! 3. Builds the .mu/mubase code graph
//! 4. Shows progress and final stats

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;
use std::time::Instant;

use colored::Colorize;
use indicatif::{ProgressBar, ProgressStyle};
use regex::Regex;
use serde::Serialize;
use serde_json::json;

use crate::cache::{CacheStats, ParseCache};
use crate::config::MuConfig;
use crate::output::{Output, OutputFormat, TableDisplay};
use crate::tsconfig::PathAliasResolver;

/// Per-node snapshot of (summary_code_hash, summary_source, summary_text),
/// captured before a rebuild for staleness detection.
type PriorSummaries = HashMap<String, (Option<String>, Option<String>, Option<String>)>;

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
    pub importance_scores_computed: usize,
    pub summaries_generated: usize,
    pub fts_index_created: bool,
    /// True when mubase already existed and force was not set (early return, no rebuild).
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub already_existed: bool,
}

impl TableDisplay for BootstrapResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        if self.already_existed {
            output.push_str(&format!(
                "{} MU already initialized. Use --force to rebuild.\n",
                "INFO:".yellow().bold()
            ));
            output.push_str(&format!("  Nodes: {}\n", self.node_count));
            output.push_str(&format!("  Edges: {}\n", self.edge_count));
            return output;
        }

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

        if self.importance_scores_computed > 0
            || self.summaries_generated > 0
            || self.fts_index_created
        {
            output.push_str(&format!("\n{}\n", "Search".cyan().bold()));
            if self.importance_scores_computed > 0 {
                output.push_str(&format!(
                    "  PageRank:   {} importance scores\n",
                    self.importance_scores_computed.to_string().green()
                ));
            }
            if self.summaries_generated > 0 {
                output.push_str(&format!(
                    "  Summaries:  {} heuristic summaries\n",
                    self.summaries_generated.to_string().green()
                ));
            }
            if self.fts_index_created {
                output.push_str(&format!(
                    "  FTS Index:  {} (BM25 on search_text)\n",
                    "created".green()
                ));
            }
        }

        output.push_str(&format!("\n{}\n", "Next Steps".cyan().bold()));
        output.push_str("  mu status              # Check status\n");
        output.push_str("  mu compress            # Codebase overview\n");
        output.push_str("  mu impact MyClass      # What breaks if I change it?\n");
        output.push_str(&format!(
            "\n  {}\n",
            "Ask your LLM to call mu_enrich to improve search quality.".dimmed()
        ));

        output
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

/// Set spinner message if spinner is present.
fn spin(spinner: Option<&ProgressBar>, msg: impl Into<std::borrow::Cow<'static, str>>) {
    if let Some(s) = spinner {
        s.set_message(msg);
    }
}

/// Scan the codebase and parse all source files, using cache when available.
fn scan_and_parse(
    root: &Path,
    config: &MuConfig,
    spinner: Option<&ProgressBar>,
    force: bool,
) -> anyhow::Result<ParsedCodebase> {
    // Step 1: Scan codebase
    spin(spinner, "Scanning codebase...");
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
    spin(spinner, format!("Found {} files", files_scanned));

    if files_scanned == 0 {
        return Ok(ParsedCodebase {
            parse_results: Vec::new(),
            files_scanned: 0,
            files_parsed: 0,
            files_cached: 0,
        });
    }

    // Step 2: Load cache and determine what needs parsing.
    // --force means "rebuild everything": that must include re-parsing, or a
    // parser fix never reaches an index whose files haven't changed on disk.
    spin(spinner, "Loading cache...");
    let mut cache = if cache_enabled && !force {
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
    spin(spinner, "Checking cache...");
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
    spin(
        spinner,
        format!(
            "Parsing {} files ({} cached)...",
            files_to_parse.len(),
            cache_stats.hits
        ),
    );

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
        spin(spinner, "Saving cache...");
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
    spinner: Option<&ProgressBar>,
) -> (
    Vec<crate::engine::storage::Node>,
    Vec<crate::engine::storage::Edge>,
) {
    spin(spinner, "Building graph...");

    // Load path alias resolver for TS/JS
    let path_alias_resolver = PathAliasResolver::from_project(root);
    if path_alias_resolver.is_some() {
        tracing::debug!("Loaded TypeScript path alias resolver");
    }

    // Build C# namespace map
    let csharp_namespace_map = build_csharp_namespace_map(parse_results);
    if !csharp_namespace_map.is_empty() {
        tracing::debug!(
            "Built C# namespace map with {} namespaces",
            csharp_namespace_map.len()
        );
    }

    let mut nodes = Vec::new();
    let mut edges = Vec::new();

    // Pre-pass: Build class lookup for inheritance resolution
    let class_lookup = build_class_lookup(parse_results);
    tracing::debug!("Built class lookup with {} entries", class_lookup.len());

    // Pre-pass: class ID set + unique-name map for constructor-call resolution
    let (class_ids, unique_class_names) = build_class_id_sets(parse_results);

    // Pre-pass: index Python module paths so absolute imports resolve even
    // when the package root is not the scan root (PYTHONPATH layouts).
    let python_module_index = PythonModuleIndex::build(parse_results);

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
                &python_module_index,
                &mut nodes,
                &mut edges,
            );
        }
    }

    // Build function lookup for call resolution
    let func_lookup = build_function_lookup(&nodes);
    tracing::debug!("Built function lookup with {} entries", func_lookup.len());

    // Build DI-aware receiver type map from constructor parameters
    let receiver_type_map = build_receiver_type_map(parse_results, &class_lookup);
    tracing::debug!(
        "Built receiver type map with {} entries",
        receiver_type_map.len()
    );

    // Build inheritance map for method resolution up the class hierarchy
    let inherits_map = build_inherits_map(&edges);
    tracing::debug!(
        "Built inherits map with {} classes having parents",
        inherits_map.len()
    );

    // Resolve call sites
    spin(spinner, "Resolving call sites...");
    let (total, resolved) = resolve_all_call_sites(
        parse_results,
        &func_lookup,
        &mut edges,
        &receiver_type_map,
        &inherits_map,
        &class_lookup,
        &class_ids,
        &unique_class_names,
        &python_module_index,
    );
    tracing::info!(
        "Call sites: {} found, {} resolved ({:.1}%)",
        total,
        resolved,
        if total > 0 {
            (resolved as f64 / total as f64) * 100.0
        } else {
            0.0
        }
    );

    // Detect cross-service patterns (MassTransit, HTTP, contracts) in C# code
    spin(spinner, "Detecting cross-service patterns...");
    detect_cross_service_edges(parse_results, &class_lookup, &mut nodes, &mut edges);

    // Synthesize trait_impl edges from inherits + decorator data
    spin(spinner, "Synthesizing implementation edges...");
    synthesize_impl_edges(&nodes, &mut edges, parse_results);

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

/// Build (all class node IDs, bare class name -> ID for unique names only).
///
/// The ID set lets call resolution check precise `cls:{path}:{Name}` candidates;
/// the unique-name map lets constructor calls resolve across modules without
/// creating false edges for ambiguous class names (mirrors the bare-name rule
/// in [`build_function_lookup`]).
fn build_class_id_sets(
    parse_results: &[mu_core::types::ParseResult],
) -> (HashSet<String>, HashMap<String, String>) {
    let mut class_ids = HashSet::new();
    let mut name_counts: HashMap<&str, usize> = HashMap::new();
    for result in parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            for class in &module.classes {
                class_ids.insert(format!("cls:{}:{}", module.path, class.name));
                *name_counts.entry(class.name.as_str()).or_insert(0) += 1;
            }
        }
    }
    let mut unique_class_names = HashMap::new();
    for result in parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            for class in &module.classes {
                if name_counts.get(class.name.as_str()).copied() == Some(1) {
                    unique_class_names.insert(
                        class.name.clone(),
                        format!("cls:{}:{}", module.path, class.name),
                    );
                }
            }
        }
    }
    (class_ids, unique_class_names)
}

/// Index of Python module paths for absolute-import resolution.
///
/// Python projects often mount a subdirectory on `PYTHONPATH` (imports like
/// `auth.token_forwarding` living at `src/pkg/auth/token_forwarding.py`), so
/// absolute imports can't be resolved by joining the dotted path onto the
/// scan root. Instead every dotted suffix of each module's path is indexed;
/// an import resolves only when its dotted path matches exactly one module.
struct PythonModuleIndex {
    /// Dotted module path -> file path. `None` marks an ambiguous suffix
    /// (multiple modules match) that must not resolve.
    by_suffix: HashMap<String, Option<String>>,
    /// Every Python module path in the scanned tree, for existence checks.
    paths: HashSet<String>,
}

impl PythonModuleIndex {
    fn build(parse_results: &[mu_core::types::ParseResult]) -> Self {
        let mut by_suffix: HashMap<String, Option<String>> = HashMap::new();
        let mut paths = HashSet::new();
        for result in parse_results {
            if !result.success {
                continue;
            }
            let Some(ref module) = result.module else {
                continue;
            };
            if module.language != "python" {
                continue;
            }
            paths.insert(module.path.clone());
            let Some(logical) = module
                .path
                .strip_suffix(".py")
                .map(|p| p.strip_suffix("/__init__").unwrap_or(p))
            else {
                continue;
            };
            // A bare __init__.py at the scan root has no importable name.
            if logical.is_empty() || logical == "__init__" {
                continue;
            }
            let components: Vec<&str> = logical.split('/').collect();
            for i in 0..components.len() {
                let suffix = components[i..].join(".");
                by_suffix
                    .entry(suffix)
                    .and_modify(|existing| {
                        if existing.as_deref() != Some(module.path.as_str()) {
                            *existing = None;
                        }
                    })
                    .or_insert_with(|| Some(module.path.clone()));
            }
        }
        Self { by_suffix, paths }
    }

    /// Resolve a dotted absolute import to a module path; unique matches only.
    fn resolve(&self, dotted: &str) -> Option<&str> {
        self.by_suffix.get(dotted)?.as_deref()
    }

    fn contains_path(&self, path: &str) -> bool {
        self.paths.contains(path)
    }
}

/// Build function name -> node ID lookup for call resolution.
///
/// Bare names (e.g. "Clear") are only stored when unique across the codebase.
/// Ambiguous bare names are removed so step-4 fallback can't create false edges.
fn build_function_lookup(nodes: &[crate::engine::storage::Node]) -> HashMap<String, String> {
    let mut func_lookup = HashMap::new();
    // Track bare names seen more than once — these are ambiguous and must not resolve globally
    let mut bare_name_counts: HashMap<String, usize> = HashMap::new();

    for node in nodes {
        if node.node_type == crate::engine::storage::NodeType::Function {
            func_lookup.insert(node.id.clone(), node.id.clone());
            *bare_name_counts.entry(node.name.clone()).or_insert(0) += 1;
            if let Some(ref qname) = node.qualified_name {
                func_lookup.insert(qname.clone(), node.id.clone());
            }
        }
    }

    // Only insert bare names that are unique — ambiguous names (Clear, ToString, Dispose, etc.)
    // would create arbitrary cross-project edges
    for node in nodes {
        if node.node_type == crate::engine::storage::NodeType::Function
            && bare_name_counts.get(&node.name).copied().unwrap_or(0) == 1
        {
            func_lookup.insert(node.name.clone(), node.id.clone());
        }
    }

    func_lookup
}

/// Map injected field names to their resolved class IDs using constructor parameters.
///
/// In C# DI, constructor `Foo(IBarService barService)` produces field `_barService`.
/// This builds `(module_path, "_barService") → cls:...:BarService` by stripping the
/// leading `I` from interface types and looking up the concrete class.
fn build_receiver_type_map(
    parse_results: &[mu_core::types::ParseResult],
    class_lookup: &HashMap<String, String>,
) -> HashMap<(String, String), String> {
    let mut map = HashMap::new();

    for result in parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            for class in &module.classes {
                // Find the constructor (tagged with "constructor" decorator by the C# parser)
                let ctor = class
                    .methods
                    .iter()
                    .find(|m| m.decorators.contains(&"constructor".to_string()));

                let ctor = match ctor {
                    Some(c) => c,
                    None => continue,
                };

                for param in &ctor.parameters {
                    let type_name = match &param.type_annotation {
                        Some(t) => t.as_str(),
                        None => continue,
                    };

                    // Strip generic args: ILogger<Foo> -> ILogger
                    let base_type = type_name.split('<').next().unwrap_or(type_name);

                    // Strip leading I for interface: ITransactionService -> TransactionService
                    let concrete_name = if base_type.starts_with('I')
                        && base_type.len() > 1
                        && base_type[1..].starts_with(|c: char| c.is_uppercase())
                    {
                        &base_type[1..]
                    } else {
                        base_type
                    };

                    // Look up the concrete class (try without I first, then with I)
                    let class_id = class_lookup
                        .get(concrete_name)
                        .or_else(|| class_lookup.get(base_type));

                    if let Some(class_id) = class_id {
                        // Map the conventional field name: param "dbContext" -> field "_dbContext"
                        let field_name = format!("_{}", param.name);
                        map.insert((module.path.clone(), field_name), class_id.clone());
                        // Also map the raw param name (some code uses it directly)
                        map.insert((module.path.clone(), param.name.clone()), class_id.clone());
                    }
                }
            }
        }
    }
    map
}

/// Build `class_id → Vec<parent_class_id>` from existing Inherits edges.
fn build_inherits_map(edges: &[crate::engine::storage::Edge]) -> HashMap<String, Vec<String>> {
    use crate::engine::storage::schema::EdgeType;
    let mut map: HashMap<String, Vec<String>> = HashMap::new();
    for edge in edges {
        if edge.edge_type == EdgeType::Inherits {
            map.entry(edge.source_id.clone())
                .or_default()
                .push(edge.target_id.clone());
        }
    }
    map
}

/// Walk up the class hierarchy (BFS) to find which ancestor defines the given method.
fn resolve_inherited_method(
    class_id: &str,
    method_name: &str,
    func_lookup: &HashMap<String, String>,
    inherits_map: &HashMap<String, Vec<String>>,
) -> Option<String> {
    use std::collections::VecDeque;

    let mut visited = HashSet::new();
    let mut queue = VecDeque::new();
    queue.push_back(class_id.to_string());

    while let Some(current) = queue.pop_front() {
        if !visited.insert(current.clone()) {
            continue;
        }

        // Extract class name and module path from class_id like "cls:path/to/file.cs:ClassName"
        let class_name = current.rsplit(':').next().unwrap_or("");
        let module_path = current
            .strip_prefix("cls:")
            .and_then(|s| s.rsplit_once(':'))
            .map(|(p, _)| p)
            .unwrap_or("");

        let method_id = format!("fn:{}:{}.{}", module_path, class_name, method_name);
        if func_lookup.contains_key(&method_id) {
            return Some(method_id);
        }

        if let Some(parents) = inherits_map.get(&current) {
            queue.extend(parents.iter().cloned());
        }
    }
    None
}

/// Build source_text for a function/method from parsed data.
///
/// Format: `{docstring}\n{signature}\n{body_preview}`
fn build_function_source_text(func: &mu_core::types::FunctionDef) -> Option<String> {
    let mut parts = Vec::new();

    if let Some(ref docstring) = func.docstring {
        parts.push(docstring.clone());
    }

    // Build signature
    let params_str: String = func
        .parameters
        .iter()
        .map(|p| {
            if let Some(ref ty) = p.type_annotation {
                format!("{}: {}", p.name, ty)
            } else {
                p.name.clone()
            }
        })
        .collect::<Vec<_>>()
        .join(", ");

    let return_str = func
        .return_type
        .as_deref()
        .map(|rt| format!(" -> {}", rt))
        .unwrap_or_default();

    parts.push(format!("fn {}({}){}", func.name, params_str, return_str));

    // Body preview (truncated to 500 chars)
    if let Some(ref body) = func.body_source {
        let preview = if body.len() > 500 {
            let mut end = 500;
            while !body.is_char_boundary(end) {
                end -= 1;
            }
            format!("{}...", &body[..end])
        } else {
            body.clone()
        };
        parts.push(preview);
    }

    Some(parts.join("\n"))
}

/// Build graph nodes and edges for a single module.
fn build_module_graph(
    module: &mu_core::types::ModuleDef,
    class_lookup: &HashMap<String, String>,
    path_alias_resolver: Option<&PathAliasResolver>,
    csharp_namespace_map: &HashMap<String, Vec<String>>,
    python_module_index: &PythonModuleIndex,
    nodes: &mut Vec<crate::engine::storage::Node>,
    edges: &mut Vec<crate::engine::storage::Edge>,
) {
    let rel_path = &module.path;

    // Create module node with source_text
    let mut module_node = crate::engine::storage::Node::module(rel_path);
    {
        let mut parts = Vec::new();
        if let Some(ref docstring) = module.module_docstring {
            parts.push(docstring.clone());
        }
        if !module.imports.is_empty() {
            let import_names: Vec<&str> =
                module.imports.iter().map(|i| i.module.as_str()).collect();
            parts.push(format!("imports: {}", import_names.join(", ")));
        }
        if !parts.is_empty() {
            module_node.source_text = Some(parts.join("\n"));
        }
    }
    let module_id = module_node.id.clone();
    nodes.push(module_node);

    // Create class nodes
    for class in &module.classes {
        // Build source_text for class
        let class_source_text = {
            let mut parts = Vec::new();
            if let Some(ref docstring) = class.docstring {
                parts.push(docstring.clone());
            }
            let bases_str = if class.bases.is_empty() {
                String::new()
            } else {
                format!("({})", class.bases.join(", "))
            };
            parts.push(format!("class {}{}", class.name, bases_str));
            if !class.attributes.is_empty() {
                parts.push(format!("  attributes: {}", class.attributes.join(", ")));
            }
            if !class.methods.is_empty() {
                let method_names: Vec<&str> =
                    class.methods.iter().map(|m| m.name.as_str()).collect();
                parts.push(format!("  methods: {}", method_names.join(", ")));
            }
            Some(parts.join("\n"))
        };

        let mut class_node = crate::engine::storage::Node::class(
            rel_path,
            &class.name,
            class.start_line,
            class.end_line,
            class_source_text,
        );

        // Build properties JSON with decorators and metadata
        let mut props = serde_json::Map::new();
        if let Some(ref docstring) = class.docstring {
            props.insert("docstring".to_string(), json!(docstring));
        }
        if !class.decorators.is_empty() {
            props.insert("decorators".to_string(), json!(class.decorators));
        }
        // Mark as DTO if class has only properties (no method bodies)
        let is_dto = !class.methods.is_empty()
            && class
                .methods
                .iter()
                .all(|m| m.is_property || m.body_source.is_none());
        if is_dto {
            props.insert("is_dto".to_string(), json!(true));
        }
        if !props.is_empty() {
            class_node = class_node.with_properties(serde_json::Value::Object(props));
        }

        let class_id = class_node.id.clone();
        nodes.push(class_node);
        edges.push(crate::engine::storage::Edge::contains(
            &module_id, &class_id,
        ));

        // Inheritance edges
        for base in &class.bases {
            let base_id = class_lookup
                .get(base)
                .cloned()
                .unwrap_or_else(|| format!("ext:{}", base));
            edges.push(crate::engine::storage::Edge::inherits(&class_id, &base_id));
        }

        // Composition edges (uses) - from struct/class fields and method type references
        for ref_type in &class.referenced_types {
            // Only create edges for types that exist in our codebase
            if let Some(target_id) = class_lookup.get(ref_type) {
                edges.push(crate::engine::storage::Edge::uses(&class_id, target_id));
            }
            // Skip external types - they don't add value to the graph
        }

        // Method nodes
        for method in &class.methods {
            let method_source_text = build_function_source_text(method);
            let mut method_node = crate::engine::storage::Node::function(
                rel_path,
                &method.name,
                Some(&class.name),
                method.start_line,
                method.end_line,
                method.body_complexity,
                method_source_text,
            );

            // Build properties JSON with decorators and metadata
            let mut method_props = serde_json::Map::new();
            if let Some(ref docstring) = method.docstring {
                method_props.insert("docstring".to_string(), json!(docstring));
            }
            if !method.decorators.is_empty() {
                // Check for dispatch markers
                if let Some(dt) = method
                    .decorators
                    .iter()
                    .find_map(|d| d.strip_prefix("dispatch:"))
                {
                    method_props.insert("dispatch_type".to_string(), json!(dt));
                }
                method_props.insert("decorators".to_string(), json!(method.decorators));
            }
            if method.is_property {
                method_props.insert("is_property".to_string(), json!(true));
            }
            // Inherit DTO status from parent class
            if is_dto {
                method_props.insert("parent_is_dto".to_string(), json!(true));
            }
            if !method_props.is_empty() {
                method_node = method_node.with_properties(serde_json::Value::Object(method_props));
            }

            let method_id = method_node.id.clone();
            nodes.push(method_node);
            edges.push(crate::engine::storage::Edge::contains(
                &class_id, &method_id,
            ));

            // Emit macro_dispatch soft edge for dispatch-marked methods
            if method.decorators.iter().any(|d| d == "dispatch:macro") {
                edges.push(crate::engine::storage::Edge::macro_dispatch(
                    &module_id, &method_id,
                ));
            }
        }
    }

    // Module-level function nodes
    for func in &module.functions {
        let func_source_text = build_function_source_text(func);
        let mut func_node = crate::engine::storage::Node::function(
            rel_path,
            &func.name,
            None,
            func.start_line,
            func.end_line,
            func.body_complexity,
            func_source_text,
        );

        // Build properties JSON with decorators
        let mut func_props = serde_json::Map::new();
        if let Some(ref docstring) = func.docstring {
            func_props.insert("docstring".to_string(), json!(docstring));
        }
        if !func.decorators.is_empty() {
            // Check for dispatch markers
            if let Some(dt) = func
                .decorators
                .iter()
                .find_map(|d| d.strip_prefix("dispatch:"))
            {
                func_props.insert("dispatch_type".to_string(), json!(dt));
            }
            func_props.insert("decorators".to_string(), json!(func.decorators));
        }
        if !func_props.is_empty() {
            func_node = func_node.with_properties(serde_json::Value::Object(func_props));
        }

        let func_id = func_node.id.clone();
        nodes.push(func_node);
        edges.push(crate::engine::storage::Edge::contains(&module_id, &func_id));

        // Emit macro_dispatch soft edge for dispatch-marked functions
        if func.decorators.iter().any(|d| d == "dispatch:macro") {
            edges.push(crate::engine::storage::Edge::macro_dispatch(
                &module_id, &func_id,
            ));
        }
    }

    // Import edges
    for import in &module.imports {
        let target_id = resolve_import(
            &import.module,
            rel_path,
            &module.language,
            path_alias_resolver,
            Some(csharp_namespace_map),
            Some(python_module_index),
        );
        edges.push(crate::engine::storage::Edge::imports(
            &module_id, &target_id,
        ));
    }
}

/// Resolve all call sites across all modules. Returns (total, resolved) counts.
#[allow(clippy::too_many_arguments)]
fn resolve_all_call_sites(
    parse_results: &[mu_core::types::ParseResult],
    func_lookup: &HashMap<String, String>,
    edges: &mut Vec<crate::engine::storage::Edge>,
    receiver_type_map: &HashMap<(String, String), String>,
    inherits_map: &HashMap<String, Vec<String>>,
    class_lookup: &HashMap<String, String>,
    class_ids: &HashSet<String>,
    unique_class_names: &HashMap<String, String>,
    python_module_index: &PythonModuleIndex,
) -> (usize, usize) {
    let mut total = 0usize;
    let mut resolved = 0usize;

    let maps = CallResolutionMaps {
        func_lookup,
        receiver_type_map,
        inherits_map,
        class_lookup,
        class_ids,
        unique_class_names,
        python_module_index,
    };

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
                    let param_types = param_type_map(&method.parameters);
                    total += method.call_sites.len();
                    for call in &method.call_sites {
                        if let Some(target_id) = resolve_call_site(
                            call,
                            rel_path,
                            Some(&class.name),
                            &module.imports,
                            &param_types,
                            maps,
                        ) {
                            edges.push(crate::engine::storage::Edge::calls(&method_id, &target_id));
                            resolved += 1;
                        }
                        push_arg_ref_edges(
                            call,
                            &method_id,
                            rel_path,
                            &module.imports,
                            maps,
                            edges,
                        );
                    }
                }
            }

            // Module-level functions
            for func in &module.functions {
                let func_id = format!("fn:{}:{}", rel_path, func.name);
                let param_types = param_type_map(&func.parameters);
                total += func.call_sites.len();
                for call in &func.call_sites {
                    if let Some(target_id) =
                        resolve_call_site(call, rel_path, None, &module.imports, &param_types, maps)
                    {
                        edges.push(crate::engine::storage::Edge::calls(&func_id, &target_id));
                        resolved += 1;
                    }
                    push_arg_ref_edges(call, &func_id, rel_path, &module.imports, maps, edges);
                }
            }
        }
    }

    (total, resolved)
}

/// Emit `uses` edges for function references passed as call arguments
/// (callback registration: `event.listen(Session, "do_orm_execute", hook)`).
/// Impact BFS traverses all edge types, so the hook stops looking like dead
/// weight the moment something registers it.
fn push_arg_ref_edges(
    call: &mu_core::types::CallSiteDef,
    from_id: &str,
    current_module: &str,
    imports: &[mu_core::types::ImportDef],
    maps: CallResolutionMaps<'_>,
    edges: &mut Vec<crate::engine::storage::Edge>,
) {
    for arg in &call.arg_refs {
        if let Some(target_id) = resolve_arg_ref(
            arg,
            current_module,
            imports,
            maps.func_lookup,
            maps.python_module_index,
        ) {
            edges.push(crate::engine::storage::Edge::uses(from_id, &target_id));
        }
    }
}

// ============================================================================
// Trait/Interface Implementation Edge Synthesis
// ============================================================================

/// Synthesize `trait_impl` edges between implementation methods and their
/// interface/trait counterparts.
///
/// Two complementary strategies, naturally disjoint by parser convention:
///
/// 1. **Inherits-based** (C#/Java/TS/Python): Walk `inherits` edges, match
///    child class methods to parent class methods by name. These parsers
///    populate `class.bases` for interface/class inheritance.
///
/// 2. **Decorator-based** (Rust): Methods with `impl:TraitName` decorators
///    are matched to methods on the trait class. The Rust parser does NOT
///    emit `inherits` edges for `impl Trait for Struct` — it only tags
///    each method with an `impl:` decorator. So Strategy 1 is a no-op for
///    Rust, and Strategy 2 is a no-op for C#/Java/TS/Python.
fn synthesize_impl_edges(
    nodes: &[crate::engine::storage::Node],
    edges: &mut Vec<crate::engine::storage::Edge>,
    parse_results: &[mu_core::types::ParseResult],
) {
    use crate::engine::storage::schema::EdgeType;

    // Build class_id → Vec<(method_name, method_id)> from contains edges
    let method_names: HashMap<&str, &str> = nodes
        .iter()
        .filter(|n| n.node_type == crate::engine::storage::NodeType::Function)
        .map(|n| (n.id.as_str(), n.name.as_str()))
        .collect();

    let mut class_methods: HashMap<&str, Vec<(&str, &str)>> = HashMap::new();
    for edge in edges.iter() {
        if edge.edge_type == EdgeType::Contains {
            if let Some(&method_name) = method_names.get(edge.target_id.as_str()) {
                class_methods
                    .entry(edge.source_id.as_str())
                    .or_default()
                    .push((method_name, edge.target_id.as_str()));
            }
        }
    }

    // Strategy 1: Walk inherits edges, match methods by name
    let inherits_pairs: Vec<(String, String)> = edges
        .iter()
        .filter(|e| e.edge_type == EdgeType::Inherits)
        .map(|e| (e.source_id.clone(), e.target_id.clone()))
        .collect();

    let mut new_edges = Vec::new();
    for (child_id, parent_id) in &inherits_pairs {
        let parent_methods = match class_methods.get(parent_id.as_str()) {
            Some(m) => m,
            None => continue,
        };
        let child_methods = match class_methods.get(child_id.as_str()) {
            Some(m) => m,
            None => continue,
        };

        for &(parent_name, parent_method_id) in parent_methods {
            for &(child_name, child_method_id) in child_methods {
                if child_name == parent_name {
                    new_edges.push(crate::engine::storage::Edge::trait_impl(
                        child_method_id,
                        parent_method_id,
                    ));
                }
            }
        }
    }

    // Strategy 2: Rust "impl:Trait" decorators
    for result in parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            for class in &module.classes {
                for method in &class.methods {
                    for dec in &method.decorators {
                        if let Some(trait_name) = dec.strip_prefix("impl:") {
                            let impl_method_id =
                                format!("fn:{}:{}.{}", module.path, class.name, method.name);
                            // Find trait class methods by matching class ID suffix
                            for (&cid, methods) in &class_methods {
                                if cid.ends_with(&format!(":{}", trait_name)) {
                                    for &(m_name, trait_method_id) in methods {
                                        if m_name == method.name.as_str() {
                                            new_edges.push(
                                                crate::engine::storage::Edge::trait_impl(
                                                    &impl_method_id,
                                                    trait_method_id,
                                                ),
                                            );
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    let count = new_edges.len();
    edges.extend(new_edges);
    if count > 0 {
        tracing::info!("Synthesized {} trait_impl edges", count);
    }
}

// ============================================================================
// Cross-Service Edge Detection (C# MassTransit, HTTP, Contracts)
// ============================================================================

/// Strip a namespace qualifier from a type name: `Contracts.SendEmail` -> `SendEmail`.
fn short_type_name(type_name: &str) -> &str {
    type_name.rsplit('.').next().unwrap_or(type_name)
}

/// Receiver evidence for calls_http detection: the token chain before
/// `.GetAsync(` / `.PostAsync(` / etc. must look like an HttpClient
/// (`_httpClient`, `client`, `_clientFactory.CreateClient()`, ...).
/// Verb names alone are too weak: any DI-injected service can have a
/// `SendAsync` method.
fn receiver_looks_like_http_client(receiver: &str) -> bool {
    let r = receiver.to_ascii_lowercase();
    r.contains("http") || r.contains("client")
}

/// Detect cross-service patterns in C# code and add message nodes + edges.
///
/// Scans parsed data (bases, body_source, referenced_types) with regex to find:
/// - MassTransit IConsumer<T> subscribers (including IConsumer<Batch<T>>)
/// - MassTransit Publish<T>() publishers
/// - HttpClient usage (GetAsync, PostAsync, etc.)
/// - Shared contract references (.Contracts., .Shared. namespaces)
///
/// # Edge direction convention
///
/// `mu impact` runs an INCOMING BFS from the target
/// (`GraphData::dependents`), so an edge `A -> B` must read "A depends
/// on B" for A to appear in B's blast radius (same convention as
/// `calls`: caller -> callee). Message-bus edges are emitted as:
///
/// - `consumer_class --subscribes--> msg`: the consumer depends on the
///   message contract, so consumers land in the message's blast radius.
/// - `publisher_method --publishes--> msg`: kept in this direction
///   because a message contract change breaks its publishers too, and
///   summaries/PageRank read "published by" as incoming edges on the
///   message node.
/// - `msg --publishes--> publisher_method` with properties
///   `{"reverse": true}`: companion edge. Without it both real edges
///   point AT the message, so an incoming BFS from the publisher can
///   never leave it. With it, impact of a publisher climbs
///   `publisher <- msg <- consumer` and reports every consumer.
///   Trade-off: co-publishers of the same message type show up in each
///   other's blast radius (recall over precision).
fn detect_cross_service_edges(
    parse_results: &[mu_core::types::ParseResult],
    class_lookup: &HashMap<String, String>,
    nodes: &mut Vec<crate::engine::storage::Node>,
    edges: &mut Vec<crate::engine::storage::Edge>,
) {
    // Matches IConsumer<T>, IConsumer<Batch<T>>, and namespace-qualified
    // type arguments. Batch is unwrapped: the consumer subscribes to T.
    let consumer_re = Regex::new(r"IConsumer<\s*(?:Batch<\s*([\w.]+)\s*>|([\w.]+))\s*>").unwrap();
    let publish_re = Regex::new(r"\.Publish<\s*([\w.]+)\s*>\s*\(").unwrap();
    // Group 1 is the receiver chain before the verb (simple call segments
    // like `.CreateClient("api")` stay part of it), group 2 the verb.
    // The receiver must pass receiver_looks_like_http_client.
    let http_verb_re = Regex::new(
        r"([A-Za-z_]\w*(?:\([^()]*\))?(?:\.[A-Za-z_]\w*(?:\([^()]*\))?)*)\.(GetAsync|PostAsync|PutAsync|DeleteAsync|SendAsync|GetStringAsync|PatchAsync)\s*\(",
    )
    .unwrap();
    let http_url_re = Regex::new(r#"["'](/api/[^"']+)["']"#).unwrap();
    let contract_ns_re =
        Regex::new(r"\b(\w+)\.(Contracts|Shared|Messages|Events|Commands)\.(\w+)").unwrap();

    // Track created message nodes to avoid duplicates. Keyed by the short
    // type name ONLY: publisher and consumer live in different namespaces
    // (that is the whole point of a message bus), and keying on the
    // publishing module's namespace used to split one message type into
    // two disconnected nodes, breaking publisher -> consumer traversal.
    let mut message_nodes: HashMap<String, String> = HashMap::new();

    let mut get_or_create_message_node =
        |type_name: &str, nodes: &mut Vec<crate::engine::storage::Node>| -> String {
            if let Some(id) = message_nodes.get(type_name) {
                return id.clone();
            }
            // Check if this type already exists as a class in the graph
            if let Some(class_id) = class_lookup.get(type_name) {
                message_nodes.insert(type_name.to_string(), class_id.clone());
                return class_id.clone();
            }
            let node = crate::engine::storage::Node::message(type_name, None);
            let id = node.id.clone();
            nodes.push(node);
            message_nodes.insert(type_name.to_string(), id.clone());
            id
        };

    for result in parse_results {
        if !result.success {
            continue;
        }
        let module = match &result.module {
            Some(m) if m.language == "csharp" => m,
            _ => continue,
        };

        let rel_path = &module.path;

        for class in &module.classes {
            let class_id = format!("cls:{}:{}", rel_path, class.name);

            // 1. MassTransit Consumer detection: IConsumer<T> in bases.
            // Group 1 is the Batch<T> payload, group 2 the plain type arg.
            for base in &class.bases {
                for cap in consumer_re.captures_iter(base) {
                    let raw_type = cap
                        .get(1)
                        .or_else(|| cap.get(2))
                        .map(|m| m.as_str())
                        .unwrap_or_default();
                    let message_type = short_type_name(raw_type);
                    let msg_id = get_or_create_message_node(message_type, nodes);
                    let edge = crate::engine::storage::Edge::subscribes(&class_id, &msg_id)
                        .with_properties(json!({"message_type": message_type}));
                    edges.push(edge);
                    tracing::debug!(
                        "Cross-service: {} subscribes to {}",
                        class.name,
                        message_type
                    );
                }
            }

            // 2. Scan method bodies for Publish<T>(), HTTP calls, contracts
            for method in &class.methods {
                let method_id = format!("fn:{}:{}.{}", rel_path, class.name, method.name);
                let body = match &method.body_source {
                    Some(b) => b,
                    None => continue,
                };

                // MassTransit Publish<T>()
                for cap in publish_re.captures_iter(body) {
                    let message_type = short_type_name(&cap[1]);
                    let msg_id = get_or_create_message_node(message_type, nodes);
                    let edge = crate::engine::storage::Edge::publishes(&method_id, &msg_id)
                        .with_properties(json!({"message_type": message_type}));
                    edges.push(edge);
                    // Reverse companion edge so the incoming impact BFS can
                    // traverse publisher <- msg <- consumer (see the edge
                    // direction convention in the function docs).
                    let reverse = crate::engine::storage::Edge::publishes(&msg_id, &method_id)
                        .with_properties(json!({"message_type": message_type, "reverse": true}));
                    edges.push(reverse);
                    tracing::debug!(
                        "Cross-service: {}.{} publishes {}",
                        class.name,
                        method.name,
                        message_type
                    );
                }

                // HTTP client calls. The verb alone is not enough evidence:
                // any DI-injected service can expose SendAsync/GetAsync
                // (e.g. _notifSvc.SendAsync), which produced false
                // calls_http edges. Require a client-ish receiver.
                let http_call = http_verb_re
                    .captures_iter(body)
                    .find(|c| receiver_looks_like_http_client(&c[1]));
                if let Some(cap) = http_call {
                    let http_method = cap[2].replace("Async", "").replace("String", "");

                    // Try to extract URL pattern
                    let url_pattern = http_url_re
                        .captures(body)
                        .and_then(|c| c.get(1))
                        .map(|m| m.as_str().to_string());

                    let target_id = format!("ext:http:{}", class.name);
                    let mut props = serde_json::Map::new();
                    props.insert("method".to_string(), json!(http_method));
                    if let Some(ref url) = url_pattern {
                        props.insert("url_pattern".to_string(), json!(url));
                    }

                    let edge = crate::engine::storage::Edge::calls_http(&method_id, &target_id)
                        .with_properties(serde_json::Value::Object(props));
                    edges.push(edge);
                    tracing::debug!(
                        "Cross-service: {}.{} calls HTTP ({})",
                        class.name,
                        method.name,
                        http_method
                    );
                }
            }

            // 3. Shared contract detection from referenced_types
            for ref_type in &class.referenced_types {
                for cap in contract_ns_re.captures_iter(ref_type) {
                    let contract_ns = format!("{}.{}", &cap[1], &cap[2]);
                    let contract_type = &cap[3];
                    // Look up the contract class in the graph, or create a virtual ref
                    let target_id = class_lookup
                        .get(contract_type)
                        .cloned()
                        .unwrap_or_else(|| format!("ext:{}:{}", contract_ns, contract_type));

                    let edge = crate::engine::storage::Edge::uses_contract(&class_id, &target_id)
                        .with_properties(
                            json!({"namespace": contract_ns, "contract_type": contract_type}),
                        );
                    edges.push(edge);
                    tracing::debug!(
                        "Cross-service: {} uses contract {}.{}",
                        class.name,
                        contract_ns,
                        contract_type
                    );
                }
            }

            // Also check bases for contract namespace references (e.g., implements IValidator<SomeContract>)
            let bases_str = class.bases.join(", ");
            for cap in contract_ns_re.captures_iter(&bases_str) {
                let contract_ns = format!("{}.{}", &cap[1], &cap[2]);
                let contract_type = &cap[3];
                let target_id = class_lookup
                    .get(contract_type)
                    .cloned()
                    .unwrap_or_else(|| format!("ext:{}:{}", contract_ns, contract_type));

                let edge = crate::engine::storage::Edge::uses_contract(&class_id, &target_id)
                    .with_properties(
                        json!({"namespace": contract_ns, "contract_type": contract_type}),
                    );
                edges.push(edge);
            }
        }
    }

    let msg_count = message_nodes.len();
    let cross_edges: usize = edges
        .iter()
        .filter(|e| e.edge_type.is_cross_service())
        .count();
    if cross_edges > 0 {
        tracing::info!(
            "Cross-service detection: {} message nodes, {} cross-service edges",
            msg_count,
            cross_edges
        );
    }
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

/// Headless bootstrap pipeline — core logic without CLI output rendering.
///
/// Called by both the CLI `run()` and the MCP `mu_bootstrap` tool.
/// When `spinner` is None, progress messages are silently skipped.
pub fn bootstrap_pipeline(
    root: &Path,
    force: bool,
    spinner: Option<&ProgressBar>,
) -> anyhow::Result<BootstrapResult> {
    let start = Instant::now();

    // Setup: config and gitignore
    let config_created = ensure_config(root);
    let gitignore_updated = update_gitignore(root);

    // Load configuration (strict mode: fail on config errors)
    let config = MuConfig::load_strict(root)?;
    tracing::debug!("Loaded ignore patterns: {:?}", config.ignore_patterns());

    // Determine mubase path
    let mu_dir = root.join(".mu");
    let mubase_path = mu_dir.join("mubase");

    // Check if rebuild is needed
    if mubase_path.exists() && !force {
        let mubase = crate::engine::storage::MUbase::open(&mubase_path)?;
        let stats = mubase.stats()?;
        return Ok(BootstrapResult {
            success: true,
            root_path: root.to_string_lossy().to_string(),
            mubase_path: mubase_path.to_string_lossy().to_string(),
            node_count: stats.node_count,
            edge_count: stats.edge_count,
            nodes_by_type: stats.type_counts,
            already_existed: true,
            files_scanned: 0,
            files_parsed: 0,
            files_cached: 0,
            duration_ms: start.elapsed().as_millis() as u64,
            config_created: false,
            gitignore_updated: false,
            importance_scores_computed: 0,
            summaries_generated: 0,
            fts_index_created: false,
        });
    }

    // Create .mu directory
    if !mu_dir.exists() {
        fs::create_dir_all(&mu_dir)?;
    }

    // Step 1: Scan and parse
    let parsed = scan_and_parse(root, &config, spinner, force)?;
    if parsed.files_scanned == 0 {
        return Ok(BootstrapResult {
            success: true,
            root_path: root.to_string_lossy().to_string(),
            mubase_path: mubase_path.to_string_lossy().to_string(),
            files_scanned: 0,
            files_parsed: 0,
            files_cached: 0,
            node_count: 0,
            edge_count: 0,
            nodes_by_type: HashMap::new(),
            duration_ms: start.elapsed().as_millis() as u64,
            config_created,
            gitignore_updated,
            importance_scores_computed: 0,
            summaries_generated: 0,
            fts_index_created: false,
            already_existed: false,
        });
    }

    // Step 2: Build graph
    let (mut nodes, edges) = build_graph(&parsed.parse_results, root, spinner);

    // Classify nodes before insertion
    let auto_config = crate::engine::auto_config::AutoConfig::load(root);
    for node in &mut nodes {
        node.node_category = crate::engine::auto_config::classify_node(
            node.file_path.as_deref(),
            auto_config.as_ref(),
        )
        .to_string();
    }

    // Step 3: Write to database
    spin(spinner, "Writing database...");
    let mubase = crate::engine::storage::MUbase::open(&mubase_path)?;

    // Snapshot existing summary info BEFORE clearing, for staleness detection later.
    let prior_summaries: PriorSummaries = mubase
        .all_nodes()
        .unwrap_or_default()
        .into_iter()
        .filter_map(|n| {
            if n.summary_code_hash.is_some() {
                Some((
                    n.id,
                    (n.summary_code_hash, n.summary_source, n.summary_text),
                ))
            } else {
                None
            }
        })
        .collect();

    mubase.clear()?;
    mubase.insert_nodes(&nodes)?;
    mubase.insert_edges(&edges)?;
    let stats = mubase.stats()?;

    // Step 4: Compute composite importance scores (PageRank + complexity + LOC + visibility)
    spin(spinner, "Computing importance scores...");
    let node_ids: Vec<String> = nodes.iter().map(|n| n.id.clone()).collect();
    let edge_tuples: Vec<(String, String, String)> = edges
        .iter()
        .map(|e| {
            (
                e.source_id.clone(),
                e.target_id.clone(),
                e.edge_type.to_string(),
            )
        })
        .collect();
    let pr_config = crate::engine::pagerank::PageRankConfig::default();
    let pagerank_scores =
        crate::engine::pagerank::compute_pagerank(&node_ids, &edge_tuples, &pr_config);

    // Compute in-degree per node from edges
    let mut in_degree_map: std::collections::HashMap<&str, u32> = std::collections::HashMap::new();
    for (_, tgt, _) in &edge_tuples {
        *in_degree_map.entry(tgt.as_str()).or_insert(0) += 1;
    }

    // Gather metadata for composite scoring
    let node_metadata: Vec<(String, crate::engine::pagerank::NodeMeta)> = nodes
        .iter()
        .map(|n| {
            let loc = match (n.line_start, n.line_end) {
                (Some(start), Some(end)) if end >= start => end - start,
                _ => 0,
            };
            let is_public = n
                .source_text
                .as_deref()
                .map(|s| s.contains("pub ") || s.contains("pub(") || s.contains("export "))
                .unwrap_or(false);
            let is_test = n.node_category == "test";

            let in_degree = in_degree_map.get(n.id.as_str()).copied().unwrap_or(0);

            (
                n.id.clone(),
                crate::engine::pagerank::NodeMeta {
                    complexity: n.complexity,
                    loc,
                    is_public,
                    is_test,
                    in_degree,
                },
            )
        })
        .collect();

    let importance_scores =
        crate::engine::pagerank::compute_composite_importance(&pagerank_scores, &node_metadata);
    let score_pairs: Vec<(String, f32)> = importance_scores.into_iter().collect();
    mubase.update_importance_batch(&score_pairs)?;
    let importance_scores_computed = score_pairs.len();
    tracing::info!(
        "Updated {} composite importance scores",
        importance_scores_computed
    );

    // Step 5: Generate heuristic summaries (needs edges for callers/callees)
    // Staleness check: preserve LLM-enriched summaries when code hasn't changed.
    // Hash is node-level (hash of node's own source_text), NOT file-level.
    // Uses prior_summaries snapshot taken BEFORE clear().
    spin(spinner, "Generating heuristic summaries...");
    let mut summaries_generated = 0;
    let mut summaries_preserved = 0;
    for node in &nodes {
        let source_text = node.source_text.as_deref().unwrap_or("");
        let code_hash = crate::engine::summary::compute_code_hash(source_text);

        // If code hasn't changed, restore the prior summary (preserves LLM enrichments)
        if let Some((Some(ref old_hash), Some(ref old_source), Some(ref old_text))) =
            prior_summaries.get(&node.id)
        {
            if old_hash == &code_hash {
                mubase.update_summary(&node.id, old_text, old_source, &code_hash)?;
                summaries_preserved += 1;
                continue;
            }
        }

        // Source changed or new node — generate fresh heuristic
        let summary = crate::engine::summary::generate_heuristic_summary(node, &edge_tuples);
        mubase.update_summary(&node.id, &summary, "heuristic", &code_hash)?;
        summaries_generated += 1;
    }
    tracing::info!(
        "Summaries: {} generated, {} preserved (unchanged code)",
        summaries_generated,
        summaries_preserved
    );

    // Step 6: Build search_text from summaries + identity fields
    spin(spinner, "Building search text...");
    let updated_nodes = mubase.all_nodes()?;
    let search_texts: Vec<(String, String)> = updated_nodes
        .iter()
        .map(|n| {
            let search_text =
                crate::engine::summary::build_search_text(n, n.summary_text.as_deref());
            (n.id.clone(), search_text)
        })
        .collect();
    mubase.update_search_text_batch(&search_texts)?;

    // Step 7: Rebuild FTS index on search_text
    spin(spinner, "Building FTS index...");
    let fts_index_created = match mubase.rebuild_fts_on_search_text() {
        Ok(created) => {
            if created {
                tracing::info!("FTS index rebuilt on search_text");
            }
            created
        }
        Err(e) => {
            tracing::warn!("Failed to create FTS index: {}", e);
            false
        }
    };

    // Step 8: Stamp the index time so staleness can be detected later.
    // Stored as unix seconds; consumers compare against source file mtimes.
    if let Err(e) = mubase.set_indexed_at_now() {
        tracing::warn!("Failed to record indexed_at: {}", e);
    }

    Ok(BootstrapResult {
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
        importance_scores_computed,
        summaries_generated,
        fts_index_created,
        already_existed: false,
    })
}

/// Run the bootstrap command (CLI entry point)
pub async fn run(path: &str, force: bool, format: OutputFormat) -> anyhow::Result<()> {
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

    let spinner = create_spinner();
    let result = bootstrap_pipeline(&root, force, Some(&spinner))?;
    spinner.finish_and_clear();

    if result.already_existed {
        // Print inline for backwards compat (no-force case)
    } else if result.files_scanned == 0 {
        println!(
            "{} No supported files found in {}",
            "WARNING:".yellow().bold(),
            root.display()
        );
        return Ok(());
    }

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
fn resolve_python_import(
    import_path: &str,
    source_file: &str,
    python_module_index: Option<&PythonModuleIndex>,
) -> String {
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

    // Relative imports can point at a package rather than a file
    // (`from . import x`, `from .pkg import y`); map those onto the
    // package's __init__.py when that file actually exists.
    if let Some(index) = python_module_index {
        if !index.contains_path(&final_path) {
            let base = final_path.strip_suffix(".py").unwrap_or(&final_path);
            let candidate = format!("{}/__init__.py", base);
            if index.contains_path(&candidate) {
                return format!("mod:{}", candidate);
            }
        }
    }

    format!("mod:{}", final_path)
}

fn resolve_import(
    import_path: &str,
    source_file: &str,
    language: &str,
    path_alias_resolver: Option<&PathAliasResolver>,
    csharp_namespace_map: Option<&HashMap<String, Vec<String>>>,
    python_module_index: Option<&PythonModuleIndex>,
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
        return resolve_python_import(import_path, source_file, python_module_index);
    }

    // Python absolute imports: resolve against the module index, which knows
    // the real file layout (including package roots below the scan root).
    if language == "python" {
        if let Some(index) = python_module_index {
            if let Some(path) = index.resolve(import_path) {
                return format!("mod:{}", path);
            }
        }
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

/// Map parameter names to their type annotations for one function.
fn param_type_map(params: &[mu_core::types::ParameterDef]) -> HashMap<&str, &str> {
    params
        .iter()
        .filter_map(|p| p.type_annotation.as_deref().map(|t| (p.name.as_str(), t)))
        .collect()
}

/// Extract the class name from a parameter type annotation. Handles the
/// common spellings: `Svc`, `Optional[Svc]`, `Svc | None`, `pkg.Svc`, and
/// quoted forward references. Returns None for anything that doesn't reduce
/// to a plain identifier (generics like `list[Svc]` are deliberately skipped:
/// the receiver's methods are the container's, not the element's).
fn annotation_class_name(annotation: &str) -> Option<&str> {
    let mut s = annotation.trim().trim_matches('"').trim_matches('\'');
    if let Some((head, tail)) = s.split_once('|') {
        let head = head.trim();
        let tail = tail.trim();
        s = if head == "None" { tail } else { head };
    }
    if let Some(inner) = s
        .strip_prefix("Optional[")
        .and_then(|r| r.strip_suffix(']'))
    {
        s = inner.trim();
    }
    let s = s.rsplit('.').next().unwrap_or(s);
    let valid = !s.is_empty() && s.chars().all(|c| c.is_alphanumeric() || c == '_');
    valid.then_some(s)
}

/// Resolve a bare identifier passed as a call argument to a function node.
/// Only precise resolutions (same module, or explicitly imported name) are
/// attempted: argument identifiers are usually plain variables, so a global
/// bare-name fallback would fabricate edges.
fn resolve_arg_ref(
    arg: &str,
    current_module: &str,
    imports: &[mu_core::types::ImportDef],
    func_lookup: &HashMap<String, String>,
    python_module_index: &PythonModuleIndex,
) -> Option<String> {
    let local_id = format!("fn:{}:{}", current_module, arg);
    if func_lookup.contains_key(&local_id) {
        return Some(local_id);
    }
    for import in imports {
        if import.names.contains(&arg.to_string()) {
            let import_path = import.module.replace('.', "/");
            let mut candidates: Vec<String> = Vec::new();
            if let Some(resolved) = python_module_index.resolve(&import.module) {
                candidates.push(resolved.to_string());
            }
            candidates.push(import_path.clone());
            candidates.push(format!("{}.py", import_path));
            for path in &candidates {
                let id = format!("fn:{}:{}", path, arg);
                if func_lookup.contains_key(&id) {
                    return Some(id);
                }
            }
        }
    }
    None
}

/// The project-wide lookup tables call-site resolution needs.
#[derive(Clone, Copy)]
struct CallResolutionMaps<'a> {
    func_lookup: &'a HashMap<String, String>,
    receiver_type_map: &'a HashMap<(String, String), String>,
    inherits_map: &'a HashMap<String, Vec<String>>,
    class_lookup: &'a HashMap<String, String>,
    class_ids: &'a HashSet<String>,
    unique_class_names: &'a HashMap<String, String>,
    python_module_index: &'a PythonModuleIndex,
}

/// Resolve a call site to a function/method node ID.
/// Returns None if the call cannot be resolved (external function, unresolvable reference).
fn resolve_call_site(
    call: &mu_core::types::CallSiteDef,
    current_module: &str,
    current_class: Option<&str>,
    imports: &[mu_core::types::ImportDef],
    param_types: &HashMap<&str, &str>,
    maps: CallResolutionMaps<'_>,
) -> Option<String> {
    let CallResolutionMaps {
        func_lookup,
        receiver_type_map,
        inherits_map,
        class_lookup,
        class_ids,
        unique_class_names,
        python_module_index,
    } = maps;
    let callee = &call.callee;

    // Normalize the receiver: `this._svc.M()` extracts receiver "this._svc",
    // but the DI receiver map and field conventions key on "_svc". Strip the
    // self-reference prefix so both spellings resolve identically.
    let receiver_norm: Option<&str> = call.receiver.as_deref().map(|r| {
        r.strip_prefix("this.")
            .or_else(|| r.strip_prefix("base."))
            .or_else(|| r.strip_prefix("self."))
            .or_else(|| r.strip_prefix("super."))
            .unwrap_or(r)
    });

    // 1. Method call on self/this - look in current class, then walk inheritance chain
    // Python: self, cls | C#/Java: this, base/super | Rust: self
    if call.is_method_call {
        if let Some(receiver) = receiver_norm {
            if matches!(receiver, "self" | "cls" | "this" | "base" | "super") {
                if let Some(class_name) = current_class {
                    // Try: fn:module:Class.method (direct method on current class)
                    let method_id = format!("fn:{}:{}.{}", current_module, class_name, callee);
                    if func_lookup.contains_key(&method_id) {
                        return Some(method_id);
                    }
                    // Try inherited method: walk up the class hierarchy
                    let class_id = format!("cls:{}:{}", current_module, class_name);
                    if let Some(inherited) =
                        resolve_inherited_method(&class_id, callee, func_lookup, inherits_map)
                    {
                        return Some(inherited);
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

    // 3.5. Constructor call to a class in the same module: `Foo()`
    if !call.is_method_call {
        let local_class_id = format!("cls:{}:{}", current_module, callee);
        if class_ids.contains(&local_class_id) {
            return Some(local_class_id);
        }
    }

    // 4. Check by simple name — only for free function calls or self/this calls.
    // Method calls on arbitrary receivers (e.g., `_items.Clear()`) cannot be resolved
    // without type information; matching by bare name creates false cross-project edges.
    let is_arbitrary_receiver = call.is_method_call
        && receiver_norm.is_some_and(|r| !matches!(r, "self" | "cls" | "this" | "base" | "super"));

    if is_arbitrary_receiver {
        // Try to resolve via constructor-injected field types
        if let Some(receiver) = receiver_norm {
            let key = (current_module.to_string(), receiver.to_string());
            if let Some(receiver_class_id) = receiver_type_map.get(&key) {
                // Try direct method on the resolved type
                let class_name = receiver_class_id.rsplit(':').next().unwrap_or("");
                let module_path = receiver_class_id
                    .strip_prefix("cls:")
                    .and_then(|s| s.rsplit_once(':'))
                    .map(|(p, _)| p)
                    .unwrap_or(current_module);

                let method_id = format!("fn:{}:{}.{}", module_path, class_name, callee);
                if func_lookup.contains_key(&method_id) {
                    return Some(method_id);
                }
                // Try inherited method on the resolved type
                if let Some(inherited) =
                    resolve_inherited_method(receiver_class_id, callee, func_lookup, inherits_map)
                {
                    return Some(inherited);
                }
            }

            // Try the enclosing function's parameter annotations:
            // `def go(s: Svc): s.run()` resolves through the declared type.
            // The Python parser stores non-self attribute calls with the full
            // dotted text as callee ("invoker.invoke"), so take the last
            // segment as the method name.
            if let Some(annotation) = param_types.get(receiver) {
                if let Some(class_name) = annotation_class_name(annotation) {
                    if let Some(class_id) = class_lookup.get(class_name) {
                        let method_name = callee.rsplit('.').next().unwrap_or(callee);
                        let module_path = class_id
                            .strip_prefix("cls:")
                            .and_then(|s| s.rsplit_once(':'))
                            .map(|(p, _)| p)
                            .unwrap_or(current_module);
                        let method_id =
                            format!("fn:{}:{}.{}", module_path, class_name, method_name);
                        if func_lookup.contains_key(&method_id) {
                            return Some(method_id);
                        }
                        if let Some(inherited) = resolve_inherited_method(
                            class_id,
                            method_name,
                            func_lookup,
                            inherits_map,
                        ) {
                            return Some(inherited);
                        }
                    }
                }
            }

            // Try treating the receiver itself as a class name (e.g., static calls)
            if let Some(class_id) = class_lookup.get(receiver) {
                let class_name = class_id.rsplit(':').next().unwrap_or("");
                let module_path = class_id
                    .strip_prefix("cls:")
                    .and_then(|s| s.rsplit_once(':'))
                    .map(|(p, _)| p)
                    .unwrap_or(current_module);

                let method_id = format!("fn:{}:{}.{}", module_path, class_name, callee);
                if func_lookup.contains_key(&method_id) {
                    return Some(method_id);
                }
            }
        }
    } else if let Some(target_id) = func_lookup.get(callee) {
        return Some(target_id.clone());
    }

    // 5. Check imported names
    for import in imports {
        if import.names.contains(&callee.to_string()) {
            // Candidate module paths for the import target: the module-index
            // resolution (real file layout) first, then the naive dotted->slash
            // spellings for layouts the index doesn't cover.
            let import_path = import.module.replace('.', "/");
            let mut candidate_paths: Vec<String> = Vec::new();
            if let Some(resolved) = python_module_index.resolve(&import.module) {
                candidate_paths.push(resolved.to_string());
            }
            candidate_paths.push(import_path.clone());
            candidate_paths.push(format!("{}.py", import_path));

            for path in &candidate_paths {
                let imported_fn_id = format!("fn:{}:{}", path, callee);
                if func_lookup.contains_key(&imported_fn_id) {
                    return Some(imported_fn_id);
                }
                // Imported class used as a constructor: `Foo()`
                if !call.is_method_call {
                    let imported_cls_id = format!("cls:{}:{}", path, callee);
                    if class_ids.contains(&imported_cls_id) {
                        return Some(imported_cls_id);
                    }
                }
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

    // 7. Constructor call to a uniquely-named class anywhere in the project.
    // Covers re-exports (`from pkg import Foo` where pkg/__init__.py forwards
    // Foo) that step 5 can't see. Unique names only — same rule as bare
    // function names in step 4.
    if !call.is_method_call && !callee.contains('.') {
        if let Some(class_id) = unique_class_names.get(callee) {
            return Some(class_id.clone());
        }
    }

    // 8. Unresolved - return None (no edge created)
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Shadows [`super::resolve_import`] for the pre-existing tests, which
    /// exercise resolution without a Python module index.
    fn resolve_import(
        import_path: &str,
        source_file: &str,
        language: &str,
        path_alias_resolver: Option<&PathAliasResolver>,
        csharp_namespace_map: Option<&HashMap<String, Vec<String>>>,
    ) -> String {
        super::resolve_import(
            import_path,
            source_file,
            language,
            path_alias_resolver,
            csharp_namespace_map,
            None,
        )
    }

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

    // ===== Cross-service edge detection tests =====

    fn make_csharp_module(
        path: &str,
        namespace: Option<&str>,
        classes: Vec<mu_core::types::ClassDef>,
    ) -> mu_core::types::ParseResult {
        mu_core::types::ParseResult {
            success: true,
            module: Some(mu_core::types::ModuleDef {
                name: path.to_string(),
                path: path.to_string(),
                language: "csharp".to_string(),
                imports: vec![],
                classes,
                functions: vec![],
                module_docstring: None,
                total_lines: 10,
                namespace: namespace.map(|s| s.to_string()),
                has_parse_errors: false,
            }),
            error: None,
        }
    }

    #[test]
    fn test_detect_masstransit_consumer() {
        let class = mu_core::types::ClassDef {
            name: "OrderCreatedConsumer".to_string(),
            bases: vec!["IConsumer<OrderCreatedEvent>".to_string()],
            methods: vec![],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module(
            "src/Consumers/OrderCreatedConsumer.cs",
            Some("MyService.Consumers"),
            vec![class],
        )];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        // Should create a message node and a subscribes edge
        assert!(
            nodes.iter().any(|n| n.name == "OrderCreatedEvent"
                && n.node_type == crate::engine::storage::NodeType::Message),
            "Should create message node for OrderCreatedEvent"
        );
        assert!(
            edges.iter().any(|e| e.edge_type
                == crate::engine::storage::schema::EdgeType::Subscribes
                && e.source_id.contains("OrderCreatedConsumer")),
            "Should create subscribes edge from consumer"
        );
    }

    #[test]
    fn test_detect_masstransit_publisher() {
        let method = mu_core::types::FunctionDef {
            name: "CreateOrder".to_string(),
            is_method: true,
            body_source: Some(
                r#"
                var order = new Order(request);
                await _publishEndpoint.Publish<OrderCreatedEvent>(new { order.Id });
                "#
                .to_string(),
            ),
            ..Default::default()
        };

        let class = mu_core::types::ClassDef {
            name: "OrderService".to_string(),
            bases: vec![],
            methods: vec![method],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module(
            "src/Services/OrderService.cs",
            None,
            vec![class],
        )];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        assert!(
            nodes.iter().any(|n| n.name == "OrderCreatedEvent"),
            "Should create message node for OrderCreatedEvent"
        );
        assert!(
            edges.iter().any(|e| e.edge_type
                == crate::engine::storage::schema::EdgeType::Publishes
                && e.source_id.contains("OrderService.CreateOrder")
                && e.target_id == "msg:OrderCreatedEvent"),
            "Should create publishes edge from method"
        );
        // Reverse companion edge (msg -> publisher) for impact traversal.
        let reverse = edges
            .iter()
            .find(|e| {
                e.edge_type == crate::engine::storage::schema::EdgeType::Publishes
                    && e.source_id == "msg:OrderCreatedEvent"
            })
            .expect("Should create reverse publishes edge from message node");
        assert!(reverse.target_id.contains("OrderService.CreateOrder"));
        assert_eq!(
            reverse.properties.as_ref().unwrap()["reverse"],
            serde_json::Value::Bool(true),
            "reverse edge must be marked"
        );
    }

    #[test]
    fn test_detect_http_client_calls() {
        let method = mu_core::types::FunctionDef {
            name: "FetchUser".to_string(),
            is_method: true,
            body_source: Some(
                r#"
                var response = await _httpClient.GetAsync("/api/users/123");
                "#
                .to_string(),
            ),
            ..Default::default()
        };

        let class = mu_core::types::ClassDef {
            name: "UserClient".to_string(),
            bases: vec![],
            methods: vec![method],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module(
            "src/Clients/UserClient.cs",
            None,
            vec![class],
        )];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        assert!(
            edges.iter().any(|e| e.edge_type
                == crate::engine::storage::schema::EdgeType::CallsHttp
                && e.source_id.contains("UserClient.FetchUser")),
            "Should create calls_http edge from method"
        );
        // Check properties contain URL pattern
        let http_edge = edges
            .iter()
            .find(|e| e.edge_type == crate::engine::storage::schema::EdgeType::CallsHttp)
            .unwrap();
        let props = http_edge.properties.as_ref().unwrap();
        assert_eq!(props["method"], "Get");
        assert_eq!(props["url_pattern"], "/api/users/123");
    }

    #[test]
    fn test_send_async_on_non_http_service_is_not_http_call() {
        // A DI-injected mail service with SendAsync must NOT produce a
        // calls_http edge: verb names alone are not receiver evidence.
        let method = mu_core::types::FunctionDef {
            name: "Notify".to_string(),
            is_method: true,
            body_source: Some(
                r#"
                await _notifSvc.SendAsync(new EmailMessage(user.Email));
                "#
                .to_string(),
            ),
            ..Default::default()
        };
        let class = mu_core::types::ClassDef {
            name: "NotificationHandler".to_string(),
            methods: vec![method],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module(
            "src/Handlers/NotificationHandler.cs",
            None,
            vec![class],
        )];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        assert!(
            !edges
                .iter()
                .any(|e| e.edge_type == crate::engine::storage::schema::EdgeType::CallsHttp),
            "SendAsync on a non-client receiver must not create calls_http"
        );
    }

    #[test]
    fn test_http_client_factory_chain_detected() {
        // IHttpClientFactory pattern: _clientFactory.CreateClient().GetAsync(...)
        let method = mu_core::types::FunctionDef {
            name: "FetchOrders".to_string(),
            is_method: true,
            body_source: Some(
                r#"
                var response = await _clientFactory.CreateClient("orders").GetAsync("/api/orders");
                "#
                .to_string(),
            ),
            ..Default::default()
        };
        let class = mu_core::types::ClassDef {
            name: "OrdersGateway".to_string(),
            methods: vec![method],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module(
            "src/Gateways/OrdersGateway.cs",
            None,
            vec![class],
        )];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        let http_edge = edges
            .iter()
            .find(|e| e.edge_type == crate::engine::storage::schema::EdgeType::CallsHttp)
            .expect("factory-created client must still be detected");
        assert_eq!(http_edge.properties.as_ref().unwrap()["method"], "Get");
        assert_eq!(
            http_edge.properties.as_ref().unwrap()["url_pattern"],
            "/api/orders"
        );
    }

    #[test]
    fn test_mixed_body_picks_the_http_call_not_the_bus_send() {
        // Both a bus SendAsync and a real HTTP call in one body: only the
        // HTTP call counts, and the extracted verb comes from it.
        let method = mu_core::types::FunctionDef {
            name: "Sync".to_string(),
            is_method: true,
            body_source: Some(
                r#"
                await _bus.SendAsync(new SyncStarted());
                var res = await _httpClient.PostAsync("/api/sync", content);
                "#
                .to_string(),
            ),
            ..Default::default()
        };
        let class = mu_core::types::ClassDef {
            name: "SyncService".to_string(),
            methods: vec![method],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module(
            "src/Services/SyncService.cs",
            None,
            vec![class],
        )];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        let http_edges: Vec<_> = edges
            .iter()
            .filter(|e| e.edge_type == crate::engine::storage::schema::EdgeType::CallsHttp)
            .collect();
        assert_eq!(http_edges.len(), 1);
        assert_eq!(
            http_edges[0].properties.as_ref().unwrap()["method"],
            "Post",
            "verb must come from the client call, not the bus SendAsync"
        );
    }

    #[test]
    fn test_detect_shared_contracts() {
        let class = mu_core::types::ClassDef {
            name: "OrderHandler".to_string(),
            bases: vec![],
            methods: vec![],
            referenced_types: vec!["MyApp.Contracts.OrderDto".to_string()],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module(
            "src/Handlers/OrderHandler.cs",
            None,
            vec![class],
        )];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        assert!(
            edges.iter().any(|e| e.edge_type
                == crate::engine::storage::schema::EdgeType::UsesContract
                && e.source_id.contains("OrderHandler")),
            "Should create uses_contract edge"
        );
    }

    #[test]
    fn test_consumer_links_to_existing_class() {
        // When the message type already exists as a class, link to it directly
        let consumer = mu_core::types::ClassDef {
            name: "EventConsumer".to_string(),
            bases: vec!["IConsumer<UserCreated>".to_string()],
            methods: vec![],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module("src/Consumer.cs", None, vec![consumer])];
        let mut class_lookup = HashMap::new();
        class_lookup.insert(
            "UserCreated".to_string(),
            "cls:src/Events.cs:UserCreated".to_string(),
        );
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        // Should NOT create a new message node (links to existing class)
        assert!(
            !nodes.iter().any(|n| n.name == "UserCreated"),
            "Should not create message node when class exists"
        );
        let sub_edge = edges
            .iter()
            .find(|e| e.edge_type == crate::engine::storage::schema::EdgeType::Subscribes)
            .expect("Should create subscribes edge");
        assert_eq!(sub_edge.target_id, "cls:src/Events.cs:UserCreated");
    }

    #[test]
    fn test_consumer_batch_message_unwrapped() {
        // IConsumer<Batch<T>> subscribes to T, not to Batch.
        let class = mu_core::types::ClassDef {
            name: "OrderBatchConsumer".to_string(),
            bases: vec!["IConsumer<Batch<OrderCreatedEvent>>".to_string()],
            methods: vec![],
            ..Default::default()
        };

        let parse_results = vec![make_csharp_module(
            "src/Consumers/OrderBatchConsumer.cs",
            Some("MyService.Consumers"),
            vec![class],
        )];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        assert!(
            nodes.iter().any(|n| n.name == "OrderCreatedEvent"
                && n.node_type == crate::engine::storage::NodeType::Message),
            "Batch<T> must be unwrapped to a message node for T"
        );
        assert!(
            !nodes.iter().any(|n| n.name.contains("Batch")),
            "No message node for the Batch wrapper itself"
        );
        let sub = edges
            .iter()
            .find(|e| e.edge_type == crate::engine::storage::schema::EdgeType::Subscribes)
            .expect("subscribes edge");
        assert!(sub.source_id.contains("OrderBatchConsumer"));
        assert_eq!(sub.target_id, "msg:OrderCreatedEvent");
    }

    #[test]
    fn test_publisher_and_consumer_share_message_node() {
        // Publisher and consumer live in different namespaces (that's the
        // point of a bus). Both sides must land on the SAME message node,
        // otherwise the pub -> sub path can never be traversed.
        let publish_method = mu_core::types::FunctionDef {
            name: "SendWelcome".to_string(),
            is_method: true,
            body_source: Some(
                "await _publishEndpoint.Publish<SendEmail>(new SendEmail());".to_string(),
            ),
            ..Default::default()
        };
        let publisher = mu_core::types::ClassDef {
            name: "OnboardingService".to_string(),
            methods: vec![publish_method],
            ..Default::default()
        };
        let consumer = mu_core::types::ClassDef {
            name: "NotificationsConsumer".to_string(),
            bases: vec!["IConsumer<SendEmail>".to_string()],
            ..Default::default()
        };

        let parse_results = vec![
            make_csharp_module(
                "src/Onboarding/OnboardingService.cs",
                Some("Company.Onboarding"),
                vec![publisher],
            ),
            make_csharp_module(
                "src/Notifications/NotificationsConsumer.cs",
                Some("Company.Notifications"),
                vec![consumer],
            ),
        ];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        let msg_nodes: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == crate::engine::storage::NodeType::Message)
            .collect();
        assert_eq!(msg_nodes.len(), 1, "exactly one node for SendEmail");

        let pub_edge = edges
            .iter()
            .find(|e| {
                e.edge_type == crate::engine::storage::schema::EdgeType::Publishes
                    && e.source_id.contains("OnboardingService.SendWelcome")
            })
            .expect("publishes edge");
        let sub_edge = edges
            .iter()
            .find(|e| e.edge_type == crate::engine::storage::schema::EdgeType::Subscribes)
            .expect("subscribes edge");
        assert_eq!(
            pub_edge.target_id, sub_edge.target_id,
            "publisher and consumer must reference the same message node"
        );
    }

    #[test]
    fn test_qualified_message_type_collapses_to_short_name() {
        // Publish<Contracts.SendEmail> and IConsumer<SendEmail> must meet
        // on the same node.
        let publish_method = mu_core::types::FunctionDef {
            name: "Run".to_string(),
            is_method: true,
            body_source: Some("await bus.Publish<Contracts.SendEmail>(msg);".to_string()),
            ..Default::default()
        };
        let publisher = mu_core::types::ClassDef {
            name: "Publisher".to_string(),
            methods: vec![publish_method],
            ..Default::default()
        };
        let consumer = mu_core::types::ClassDef {
            name: "Consumer".to_string(),
            bases: vec!["IConsumer<SendEmail>".to_string()],
            ..Default::default()
        };

        let parse_results = vec![
            make_csharp_module("src/Pub.cs", None, vec![publisher]),
            make_csharp_module("src/Sub.cs", None, vec![consumer]),
        ];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        let msg_nodes: Vec<_> = nodes
            .iter()
            .filter(|n| n.node_type == crate::engine::storage::NodeType::Message)
            .collect();
        assert_eq!(msg_nodes.len(), 1);
        assert_eq!(msg_nodes[0].id, "msg:SendEmail");
    }

    #[test]
    fn test_impact_of_publisher_reaches_consumer_through_bus() {
        // End-to-end: real C# sources through the parser and build_graph,
        // loaded into a DuckDB graph, then the same incoming BFS mu_impact
        // uses. The blast radius of the publishing method must include the
        // message node and the consumer on the other side of the bus.
        let publisher = mu_core::parser::parse_source(
            r#"
using MassTransit;
using System.Threading.Tasks;
namespace Orders {
    public class OrderService {
        private readonly IPublishEndpoint _publishEndpoint;
        public OrderService(IPublishEndpoint publishEndpoint) { _publishEndpoint = publishEndpoint; }
        public async Task CreateOrder() {
            await _publishEndpoint.Publish<SendEmail>(new SendEmail());
        }
    }
}
"#,
            "Orders/OrderService.cs",
            "csharp",
        );
        let consumer = mu_core::parser::parse_source(
            r#"
using MassTransit;
using System.Threading.Tasks;
namespace Notifications {
    public class NotificationsConsumer : IConsumer<SendEmail> {
        public async Task Consume(ConsumeContext<SendEmail> context) {
            await Task.CompletedTask;
        }
    }
}
"#,
            "Notifications/NotificationsConsumer.cs",
            "csharp",
        );
        assert!(publisher.success && consumer.success, "fixtures must parse");
        // Sanity: the parser must surface the generic base verbatim.
        assert!(
            consumer.module.as_ref().unwrap().classes[0]
                .bases
                .contains(&"IConsumer<SendEmail>".to_string()),
            "parser must capture IConsumer<SendEmail> in bases, got {:?}",
            consumer.module.as_ref().unwrap().classes[0].bases
        );
        let results = vec![publisher, consumer];

        let (nodes, edges) = build_graph(&results, Path::new("."), None);

        let publisher_fn = "fn:Orders/OrderService.cs:OrderService.CreateOrder";
        let consumer_cls = "cls:Notifications/NotificationsConsumer.cs:NotificationsConsumer";
        let msg = "msg:SendEmail";
        assert!(nodes.iter().any(|n| n.id == msg), "message node exists");

        // Load into a throwaway DuckDB with the columns GraphData reads.
        let dir = tempfile::tempdir().unwrap();
        let conn = duckdb::Connection::open(dir.path().join("test.mubase")).unwrap();
        conn.execute_batch(
            "CREATE TABLE nodes (id VARCHAR, name VARCHAR, type VARCHAR, file_path VARCHAR);
             CREATE TABLE edges (source_id VARCHAR, target_id VARCHAR, type VARCHAR);",
        )
        .unwrap();
        for n in &nodes {
            conn.execute(
                "INSERT INTO nodes VALUES (?, ?, ?, ?)",
                duckdb::params![n.id, n.name, n.node_type.as_str(), n.file_path],
            )
            .unwrap();
        }
        for e in &edges {
            conn.execute(
                "INSERT INTO edges VALUES (?, ?, ?)",
                duckdb::params![e.source_id, e.target_id, e.edge_type.as_str()],
            )
            .unwrap();
        }

        let graph = crate::commands::graph::GraphData::from_db(&conn).unwrap();

        // Impact of the publisher method: consumers must be in the
        // dependents set (publisher <- msg <- consumer).
        let publisher_impact = graph.dependents(publisher_fn, None, None);
        assert!(
            publisher_impact.contains(&msg.to_string()),
            "publisher impact must include the message node, got {:?}",
            publisher_impact
        );
        assert!(
            publisher_impact.contains(&consumer_cls.to_string()),
            "publisher impact must include the consumer, got {:?}",
            publisher_impact
        );

        // Impact of the message type: both sides of the bus.
        let msg_impact = graph.dependents(msg, None, None);
        assert!(
            msg_impact.contains(&publisher_fn.to_string()),
            "message impact must include the publisher, got {:?}",
            msg_impact
        );
        assert!(
            msg_impact.contains(&consumer_cls.to_string()),
            "message impact must include the consumer, got {:?}",
            msg_impact
        );
    }

    #[test]
    fn test_non_csharp_modules_skipped() {
        let class = mu_core::types::ClassDef {
            name: "PythonConsumer".to_string(),
            bases: vec!["IConsumer<SomeEvent>".to_string()],
            methods: vec![],
            ..Default::default()
        };

        // Python module with the same base pattern should be ignored
        let parse_results = vec![mu_core::types::ParseResult {
            success: true,
            module: Some(mu_core::types::ModuleDef {
                name: "consumer".to_string(),
                path: "consumer.py".to_string(),
                language: "python".to_string(),
                classes: vec![class],
                ..Default::default()
            }),
            error: None,
        }];
        let class_lookup = HashMap::new();
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        detect_cross_service_edges(&parse_results, &class_lookup, &mut nodes, &mut edges);

        assert!(
            nodes.is_empty(),
            "Should not detect patterns in non-C# code"
        );
        assert!(edges.is_empty());
    }

    #[test]
    fn test_resolve_receiver_with_this_prefix() {
        // C# extracts `this._svc.Send()` with receiver "this._svc"; the DI map
        // keys on "_svc". The resolver must strip the self-reference prefix or
        // every this-qualified DI call silently fails to produce an edge.
        let mut func_lookup = HashMap::new();
        func_lookup.insert(
            "fn:svc.cs:NotificationsService.SendEmailAsync".to_string(),
            "fn:svc.cs:NotificationsService.SendEmailAsync".to_string(),
        );
        let mut receiver_type_map = HashMap::new();
        receiver_type_map.insert(
            ("caller.cs".to_string(), "_notificationsService".to_string()),
            "cls:svc.cs:NotificationsService".to_string(),
        );
        let inherits_map = HashMap::new();
        let class_lookup = HashMap::new();
        let class_ids = HashSet::new();
        let unique_class_names = HashMap::new();
        let python_module_index = PythonModuleIndex::build(&[]);
        let maps = CallResolutionMaps {
            func_lookup: &func_lookup,
            receiver_type_map: &receiver_type_map,
            inherits_map: &inherits_map,
            class_lookup: &class_lookup,
            class_ids: &class_ids,
            unique_class_names: &unique_class_names,
            python_module_index: &python_module_index,
        };

        let call = mu_core::types::CallSiteDef {
            callee: "SendEmailAsync".to_string(),
            line: 10,
            is_method_call: true,
            receiver: Some("this._notificationsService".to_string()),
            arg_refs: Vec::new(),
        };
        let resolved = resolve_call_site(
            &call,
            "caller.cs",
            Some("Caller"),
            &[],
            &HashMap::new(),
            maps,
        );
        assert_eq!(
            resolved.as_deref(),
            Some("fn:svc.cs:NotificationsService.SendEmailAsync"),
            "this.-prefixed receiver must resolve through the DI map"
        );

        // Bare field receiver keeps working.
        let bare = mu_core::types::CallSiteDef {
            callee: "SendEmailAsync".to_string(),
            line: 11,
            is_method_call: true,
            receiver: Some("_notificationsService".to_string()),
            arg_refs: Vec::new(),
        };
        let resolved = resolve_call_site(
            &bare,
            "caller.cs",
            Some("Caller"),
            &[],
            &HashMap::new(),
            maps,
        );
        assert_eq!(
            resolved.as_deref(),
            Some("fn:svc.cs:NotificationsService.SendEmailAsync")
        );
    }

    #[test]
    fn test_receiver_type_map_from_parsed_csharp() {
        // End-to-end DI map construction from real parser output: the eval
        // showed zero DI edges on a 920k-line C# codebase even though every
        // link looked correct in isolation.
        let a = mu_core::parser::parse_source(
            r#"
namespace Demo {
    public interface INotifSvc { }
    public class NotifSvc : INotifSvc { public void SendAsync(string m) { } }
}
"#,
            "A.cs",
            "csharp",
        );
        let b = mu_core::parser::parse_source(
            r#"
using System.Threading.Tasks;
namespace Demo {
    public class Caller {
        private readonly INotifSvc _notifSvc;
        public Caller(INotifSvc notifSvc) { _notifSvc = notifSvc; }
        public async Task Run() {
            await this._notifSvc.SendAsync("x").ConfigureAwait(false);
        }
    }
}
"#,
            "B.cs",
            "csharp",
        );
        assert!(a.success && b.success, "fixture must parse");
        let results = vec![a, b];

        let caller = results[1].module.as_ref().unwrap();
        let ctor = caller.classes[0]
            .methods
            .iter()
            .find(|m| m.decorators.contains(&"constructor".to_string()))
            .expect("constructor must be tagged");
        assert_eq!(
            ctor.parameters
                .first()
                .and_then(|p| p.type_annotation.as_deref()),
            Some("INotifSvc"),
            "constructor param type must be captured"
        );

        let class_lookup = build_class_lookup(&results);
        assert!(class_lookup.contains_key("NotifSvc"), "class lookup");

        let map = build_receiver_type_map(&results, &class_lookup);
        assert_eq!(
            map.get(&("B.cs".to_string(), "_notifSvc".to_string())),
            Some(&"cls:A.cs:NotifSvc".to_string()),
            "DI receiver map must map _notifSvc to the concrete class"
        );
    }

    // ------------------------------------------------------------------
    // Python module index + constructor-call resolution
    // ------------------------------------------------------------------

    fn python_parse_results(paths: &[&str]) -> Vec<mu_core::types::ParseResult> {
        paths
            .iter()
            .map(|p| mu_core::types::ParseResult {
                success: true,
                module: Some(mu_core::types::ModuleDef {
                    name: std::path::Path::new(p)
                        .file_stem()
                        .unwrap()
                        .to_string_lossy()
                        .to_string(),
                    path: p.to_string(),
                    language: "python".to_string(),
                    ..Default::default()
                }),
                error: None,
            })
            .collect()
    }

    #[test]
    fn test_python_module_index_resolves_suffixes() {
        let results = python_parse_results(&[
            "src/pkg/auth/token_forwarding.py",
            "src/pkg/auth/__init__.py",
        ]);
        let index = PythonModuleIndex::build(&results);

        // Imports as PYTHONPATH=src/pkg sees them
        assert_eq!(
            index.resolve("auth.token_forwarding"),
            Some("src/pkg/auth/token_forwarding.py")
        );
        assert_eq!(index.resolve("auth"), Some("src/pkg/auth/__init__.py"));
        // Full path from scan root also resolves
        assert_eq!(
            index.resolve("src.pkg.auth.token_forwarding"),
            Some("src/pkg/auth/token_forwarding.py")
        );
        assert_eq!(index.resolve("does.not.exist"), None);
    }

    #[test]
    fn test_python_module_index_ambiguous_suffix_does_not_resolve() {
        let results = python_parse_results(&["src/a/models.py", "src/b/models.py"]);
        let index = PythonModuleIndex::build(&results);

        assert_eq!(index.resolve("models"), None, "ambiguous suffix");
        assert_eq!(index.resolve("a.models"), Some("src/a/models.py"));
        assert_eq!(index.resolve("b.models"), Some("src/b/models.py"));
    }

    #[test]
    fn test_resolve_import_python_nested_package_root() {
        let results = python_parse_results(&["src/pkg/auth/token_forwarding.py"]);
        let index = PythonModuleIndex::build(&results);

        assert_eq!(
            super::resolve_import(
                "auth.token_forwarding",
                "src/pkg/clients/base_client.py",
                "python",
                None,
                None,
                Some(&index)
            ),
            "mod:src/pkg/auth/token_forwarding.py"
        );
        // Unknown qualified imports keep the legacy spelling
        assert_eq!(
            super::resolve_import(
                "sqlalchemy.orm",
                "src/pkg/clients/base_client.py",
                "python",
                None,
                None,
                Some(&index)
            ),
            "mod:sqlalchemy/orm"
        );
    }

    #[test]
    fn test_resolve_python_relative_import_to_package_init() {
        let results = python_parse_results(&["src/pkg/auth/__init__.py"]);
        let index = PythonModuleIndex::build(&results);

        assert_eq!(
            super::resolve_import(
                ".auth",
                "src/pkg/main.py",
                "python",
                None,
                None,
                Some(&index)
            ),
            "mod:src/pkg/auth/__init__.py"
        );
    }

    fn empty_maps<'a>(
        func_lookup: &'a HashMap<String, String>,
        receiver_type_map: &'a HashMap<(String, String), String>,
        inherits_map: &'a HashMap<String, Vec<String>>,
        class_lookup: &'a HashMap<String, String>,
        class_ids: &'a HashSet<String>,
        unique_class_names: &'a HashMap<String, String>,
        python_module_index: &'a PythonModuleIndex,
    ) -> CallResolutionMaps<'a> {
        CallResolutionMaps {
            func_lookup,
            receiver_type_map,
            inherits_map,
            class_lookup,
            class_ids,
            unique_class_names,
            python_module_index,
        }
    }

    #[test]
    fn test_resolve_call_site_constructor_via_import() {
        let results = python_parse_results(&["src/pkg/auth/token_forwarding.py"]);
        let index = PythonModuleIndex::build(&results);

        let func_lookup = HashMap::new();
        let receiver_type_map = HashMap::new();
        let inherits_map = HashMap::new();
        let class_lookup = HashMap::new();
        let mut class_ids = HashSet::new();
        class_ids.insert("cls:src/pkg/auth/token_forwarding.py:TokenForwardingHandler".to_string());
        let unique_class_names = HashMap::new();

        let maps = empty_maps(
            &func_lookup,
            &receiver_type_map,
            &inherits_map,
            &class_lookup,
            &class_ids,
            &unique_class_names,
            &index,
        );

        let call = mu_core::types::CallSiteDef {
            callee: "TokenForwardingHandler".to_string(),
            is_method_call: false,
            ..Default::default()
        };
        let imports = vec![mu_core::types::ImportDef {
            module: "auth.token_forwarding".to_string(),
            names: vec!["TokenForwardingHandler".to_string()],
            is_from: true,
            ..Default::default()
        }];

        assert_eq!(
            resolve_call_site(
                &call,
                "src/pkg/clients/base_client.py",
                Some("BpHttpClient"),
                &imports,
                &HashMap::new(),
                maps
            ),
            Some("cls:src/pkg/auth/token_forwarding.py:TokenForwardingHandler".to_string())
        );
    }

    #[test]
    fn test_resolve_call_site_constructor_same_module() {
        let results = python_parse_results(&["app.py"]);
        let index = PythonModuleIndex::build(&results);

        let func_lookup = HashMap::new();
        let receiver_type_map = HashMap::new();
        let inherits_map = HashMap::new();
        let class_lookup = HashMap::new();
        let mut class_ids = HashSet::new();
        class_ids.insert("cls:app.py:Config".to_string());
        let unique_class_names = HashMap::new();

        let maps = empty_maps(
            &func_lookup,
            &receiver_type_map,
            &inherits_map,
            &class_lookup,
            &class_ids,
            &unique_class_names,
            &index,
        );

        let call = mu_core::types::CallSiteDef {
            callee: "Config".to_string(),
            is_method_call: false,
            ..Default::default()
        };

        assert_eq!(
            resolve_call_site(&call, "app.py", None, &[], &HashMap::new(), maps),
            Some("cls:app.py:Config".to_string())
        );
    }

    #[test]
    fn test_resolve_call_site_constructor_unique_name_fallback() {
        // Re-export case: `from auth import Handler` while the class lives in
        // auth/handler.py — step 5 misses, the unique-name fallback hits.
        let results = python_parse_results(&["auth/__init__.py", "auth/handler.py"]);
        let index = PythonModuleIndex::build(&results);

        let func_lookup = HashMap::new();
        let receiver_type_map = HashMap::new();
        let inherits_map = HashMap::new();
        let class_lookup = HashMap::new();
        let mut class_ids = HashSet::new();
        class_ids.insert("cls:auth/handler.py:Handler".to_string());
        let mut unique_class_names = HashMap::new();
        unique_class_names.insert(
            "Handler".to_string(),
            "cls:auth/handler.py:Handler".to_string(),
        );

        let maps = empty_maps(
            &func_lookup,
            &receiver_type_map,
            &inherits_map,
            &class_lookup,
            &class_ids,
            &unique_class_names,
            &index,
        );

        let call = mu_core::types::CallSiteDef {
            callee: "Handler".to_string(),
            is_method_call: false,
            ..Default::default()
        };
        let imports = vec![mu_core::types::ImportDef {
            module: "auth".to_string(),
            names: vec!["Handler".to_string()],
            is_from: true,
            ..Default::default()
        }];

        assert_eq!(
            resolve_call_site(&call, "main.py", None, &imports, &HashMap::new(), maps),
            Some("cls:auth/handler.py:Handler".to_string())
        );

        // Ambiguous class names must NOT resolve through the fallback
        let empty_unique = HashMap::new();
        let maps_ambiguous = empty_maps(
            &func_lookup,
            &receiver_type_map,
            &inherits_map,
            &class_lookup,
            &class_ids,
            &empty_unique,
            &index,
        );
        assert_eq!(
            resolve_call_site(&call, "main.py", None, &[], &HashMap::new(), maps_ambiguous),
            None
        );
    }

    #[test]
    fn test_annotation_class_name_spellings() {
        assert_eq!(annotation_class_name("Svc"), Some("Svc"));
        assert_eq!(annotation_class_name("Optional[Svc]"), Some("Svc"));
        assert_eq!(annotation_class_name("Svc | None"), Some("Svc"));
        assert_eq!(annotation_class_name("None | Svc"), Some("Svc"));
        assert_eq!(annotation_class_name("pkg.mod.Svc"), Some("Svc"));
        assert_eq!(annotation_class_name("\"Svc\""), Some("Svc"));
        // Containers are not the receiver's type
        assert_eq!(annotation_class_name("list[Svc]"), None);
        assert_eq!(annotation_class_name("dict[str, Svc]"), None);
    }

    #[test]
    fn test_resolve_call_site_annotated_param_receiver() {
        // def go(s: Svc): s.run()  ->  edge to Svc.run
        let results = python_parse_results(&["src/svc.py"]);
        let index = PythonModuleIndex::build(&results);

        let mut func_lookup = HashMap::new();
        func_lookup.insert(
            "fn:src/svc.py:Svc.run".to_string(),
            "fn:src/svc.py:Svc.run".to_string(),
        );
        let receiver_type_map = HashMap::new();
        let inherits_map = HashMap::new();
        let mut class_lookup = HashMap::new();
        class_lookup.insert("Svc".to_string(), "cls:src/svc.py:Svc".to_string());
        let class_ids = HashSet::new();
        let unique_class_names = HashMap::new();

        let maps = empty_maps(
            &func_lookup,
            &receiver_type_map,
            &inherits_map,
            &class_lookup,
            &class_ids,
            &unique_class_names,
            &index,
        );

        let call = mu_core::types::CallSiteDef {
            // Python stores non-self attribute calls with the dotted text
            callee: "s.run".to_string(),
            is_method_call: true,
            receiver: Some("s".to_string()),
            ..Default::default()
        };
        let mut param_types = HashMap::new();
        param_types.insert("s", "Svc");

        assert_eq!(
            resolve_call_site(&call, "src/caller.py", None, &[], &param_types, maps),
            Some("fn:src/svc.py:Svc.run".to_string())
        );

        // Without the annotation the receiver stays unresolvable
        assert_eq!(
            resolve_call_site(&call, "src/caller.py", None, &[], &HashMap::new(), maps),
            None
        );
    }

    #[test]
    fn test_resolve_arg_ref_local_and_imported() {
        let results = python_parse_results(&["src/pkg/hooks.py", "src/pkg/main.py"]);
        let index = PythonModuleIndex::build(&results);

        let mut func_lookup = HashMap::new();
        func_lookup.insert(
            "fn:src/pkg/hooks.py:on_event".to_string(),
            "fn:src/pkg/hooks.py:on_event".to_string(),
        );
        func_lookup.insert(
            "fn:src/pkg/main.py:local_hook".to_string(),
            "fn:src/pkg/main.py:local_hook".to_string(),
        );

        // Local function reference
        assert_eq!(
            resolve_arg_ref("local_hook", "src/pkg/main.py", &[], &func_lookup, &index),
            Some("fn:src/pkg/main.py:local_hook".to_string())
        );

        // Imported function reference, resolved through the module index
        let imports = vec![mu_core::types::ImportDef {
            module: "hooks".to_string(),
            names: vec!["on_event".to_string()],
            is_from: true,
            ..Default::default()
        }];
        assert_eq!(
            resolve_arg_ref(
                "on_event",
                "src/pkg/main.py",
                &imports,
                &func_lookup,
                &index
            ),
            Some("fn:src/pkg/hooks.py:on_event".to_string())
        );

        // Plain variables must not resolve
        assert_eq!(
            resolve_arg_ref("session", "src/pkg/main.py", &imports, &func_lookup, &index),
            None
        );
    }
}
