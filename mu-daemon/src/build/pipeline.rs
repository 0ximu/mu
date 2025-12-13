//! Build pipeline implementation.

use anyhow::{Context, Result};
use std::path::Path;
use std::time::{Duration, Instant};
use tracing::{debug, info};

use crate::server::state::GraphEvent;
use crate::server::AppState;
use crate::storage::{Edge, Node};

/// Result of a build operation.
#[derive(Debug, Clone)]
pub struct BuildResult {
    pub node_count: usize,
    pub edge_count: usize,
    pub file_count: usize,
    pub duration: Duration,
}

/// Pipeline for building the code graph from source files.
#[derive(Clone)]
pub struct BuildPipeline {
    state: AppState,
}

impl BuildPipeline {
    /// Create a new build pipeline.
    pub fn new(state: AppState) -> Self {
        Self { state }
    }

    /// Build the full graph from a codebase.
    pub async fn build(&self, root: &Path) -> Result<BuildResult> {
        let start = Instant::now();

        // Broadcast build started
        self.state.broadcast(GraphEvent::BuildStarted);

        info!("Starting build from {:?}", root);

        // 1. Scan files using mu-core scanner (use sync version without Python GIL)
        let root_str = root.to_str().unwrap_or(".");
        let scan_result =
            mu_core::scanner::scan_directory_sync(root_str, None, None, false, false, false)
                .map_err(|e| anyhow::anyhow!(e))
                .context("Failed to scan directory")?;

        let file_count = scan_result.files.len();
        info!("Scanned {} files", file_count);

        // 2. Parse files using mu-core parser
        let file_infos: Vec<mu_core::types::FileInfo> = scan_result
            .files
            .iter()
            .filter_map(|f| {
                let content = std::fs::read_to_string(&f.path).ok()?;
                Some(mu_core::types::FileInfo {
                    path: f.path.clone(),
                    source: content,
                    language: f.language.clone(),
                })
            })
            .collect();

        let parse_results = mu_core::parser::parse_files_parallel(file_infos, None);
        info!("Parsed {} files", parse_results.len());

        // 3. Convert parsed modules to nodes and edges (three-pass approach)
        let mut nodes = Vec::new();
        let mut edges = Vec::new();

        // Pre-pass: Build class lookup map (class name -> class ID) for inheritance resolution
        let mut class_lookup: std::collections::HashMap<String, String> =
            std::collections::HashMap::new();
        for result in &parse_results {
            if !result.success {
                continue;
            }
            if let Some(ref module) = result.module {
                let rel_path = Path::new(&module.path)
                    .strip_prefix(root)
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_else(|_| module.path.clone());

                for class in &module.classes {
                    let class_id = format!("cls:{}:{}", rel_path, class.name);
                    // Map by simple name (may have collisions, last one wins)
                    class_lookup.insert(class.name.clone(), class_id.clone());
                    // Also map by qualified name (module:class) for disambiguation
                    let qualified_name = format!("{}:{}", rel_path, class.name);
                    class_lookup.insert(qualified_name, class_id);
                }
            }
        }

        // Pass 1: Create all nodes and CONTAINS/IMPORTS/INHERITS edges
        for result in &parse_results {
            if !result.success {
                if let Some(ref err) = result.error {
                    debug!("Parse error: {}", err);
                }
                continue;
            }

            if let Some(ref module) = result.module {
                // Make path relative to root
                let rel_path = Path::new(&module.path)
                    .strip_prefix(root)
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_else(|_| module.path.clone());

                // Create module node
                let module_node = Node::module(&rel_path);
                let module_id = module_node.id.clone();
                nodes.push(module_node);

                // Create class nodes
                for class in &module.classes {
                    let class_node =
                        Node::class(&rel_path, &class.name, class.start_line, class.end_line);
                    let class_id = class_node.id.clone();
                    nodes.push(class_node);

                    // Module contains class
                    edges.push(Edge::contains(&module_id, &class_id));

                    // Inheritance edges - resolve to actual class if found
                    for base in &class.bases {
                        let base_id = if let Some(resolved_id) = class_lookup.get(base) {
                            // Found in codebase - use actual class ID
                            resolved_id.clone()
                        } else {
                            // Not found - mark as external reference
                            format!("ext:{}", base)
                        };
                        edges.push(Edge::inherits(&class_id, &base_id));
                    }

                    // Create method nodes
                    for method in &class.methods {
                        let method_node = Node::function(
                            &rel_path,
                            &method.name,
                            Some(&class.name),
                            method.start_line,
                            method.end_line,
                            method.body_complexity,
                        );
                        let method_id = method_node.id.clone();
                        nodes.push(method_node);

                        // Class contains method
                        edges.push(Edge::contains(&class_id, &method_id));
                    }

                    // Create USES edges for referenced types (types used in method signatures)
                    for ref_type in &class.referenced_types {
                        // Try to resolve to an internal class, otherwise mark as external
                        let target_id = if let Some(resolved_id) = class_lookup.get(ref_type) {
                            // Found in codebase - use actual class ID
                            resolved_id.clone()
                        } else {
                            // Not found - mark as external reference
                            format!("ext:{}", ref_type)
                        };
                        edges.push(Edge::uses(&class_id, &target_id));
                    }
                }

                // Create function nodes (module-level)
                for func in &module.functions {
                    let func_node = Node::function(
                        &rel_path,
                        &func.name,
                        None,
                        func.start_line,
                        func.end_line,
                        func.body_complexity,
                    );
                    let func_id = func_node.id.clone();
                    nodes.push(func_node);

                    // Module contains function
                    edges.push(Edge::contains(&module_id, &func_id));
                }

                // Create import edges
                for import in &module.imports {
                    // Resolve import to module ID
                    let target_id = resolve_import(&import.module, root_str);
                    edges.push(Edge::imports(&module_id, &target_id));
                }
            }
        }

        // Build function lookup map for call resolution
        let mut func_lookup: std::collections::HashMap<String, String> =
            std::collections::HashMap::new();
        for node in &nodes {
            if node.node_type == crate::storage::NodeType::Function {
                // Map by simple name and qualified name
                func_lookup.insert(node.name.clone(), node.id.clone());
                if let Some(ref qname) = node.qualified_name {
                    func_lookup.insert(qname.clone(), node.id.clone());
                }
            }
        }

        // Pass 2: Create CALLS edges (iterate again with func_lookup available)
        let mut total_call_sites = 0usize;
        let mut resolved_call_sites = 0usize;

        for result in &parse_results {
            if !result.success {
                continue;
            }
            if let Some(ref module) = result.module {
                let rel_path = Path::new(&module.path)
                    .strip_prefix(root)
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_else(|_| module.path.clone());

                // Process class methods
                for class in &module.classes {
                    for method in &class.methods {
                        let method_id = format!("fn:{}:{}.{}", rel_path, class.name, method.name);
                        total_call_sites += method.call_sites.len();
                        for call in &method.call_sites {
                            if let Some(target_id) = resolve_call_site(
                                call,
                                &rel_path,
                                Some(&class.name),
                                &func_lookup,
                                &module.imports,
                            ) {
                                edges.push(Edge::calls(&method_id, &target_id));
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
                            resolve_call_site(call, &rel_path, None, &func_lookup, &module.imports)
                        {
                            edges.push(Edge::calls(&func_id, &target_id));
                            resolved_call_sites += 1;
                        }
                    }
                }
            }
        }

        info!("Built {} nodes and {} edges", nodes.len(), edges.len());
        info!("Call sites: {} found, {} resolved to CALLS edges", total_call_sites, resolved_call_sites);

        // 4. Write to DuckDB
        {
            let mubase = self.state.mubase.write().await;
            mubase.clear()?;
            mubase.insert_nodes(&nodes)?;
            mubase.insert_edges(&edges)?;
            // Verify write succeeded
            let stats = mubase.stats()?;
            info!("After insert - DB stats: {} nodes, {} edges", stats.node_count, stats.edge_count);
        }

        // 5. Reload in-memory graph
        {
            let mubase = self.state.mubase.read().await;
            let new_graph = mubase.load_graph()?;
            info!("Reloaded graph: {} nodes, {} edges", new_graph.node_count(), new_graph.edge_count());

            let mut graph = self.state.graph.write().await;
            *graph = new_graph;
        }

        let duration = start.elapsed();

        // Broadcast completion
        self.state.broadcast(GraphEvent::GraphRebuilt {
            node_count: nodes.len(),
            edge_count: edges.len(),
        });
        self.state.broadcast(GraphEvent::BuildCompleted {
            duration_ms: duration.as_millis() as u64,
        });

        Ok(BuildResult {
            node_count: nodes.len(),
            edge_count: edges.len(),
            file_count,
            duration,
        })
    }

    /// Incrementally update the graph for changed files.
    pub async fn incremental_update(
        &self,
        changed_files: &[std::path::PathBuf],
    ) -> Result<BuildResult> {
        let start = Instant::now();
        let root = &self.state.root;

        let mut total_nodes = 0;
        let mut total_edges = 0;

        // Build func_lookup and class_lookup from existing database for resolution
        let (func_lookup, class_lookup): (
            std::collections::HashMap<String, String>,
            std::collections::HashMap<String, String>,
        ) = {
            let mubase = self.state.mubase.read().await;

            // Build function lookup
            let func_nodes = mubase
                .get_nodes_by_type(crate::storage::NodeType::Function)
                .unwrap_or_default();
            let mut func_map = std::collections::HashMap::new();
            for node in func_nodes {
                func_map.insert(node.name.clone(), node.id.clone());
                if let Some(ref qname) = node.qualified_name {
                    func_map.insert(qname.clone(), node.id.clone());
                }
            }

            // Build class lookup for inheritance resolution
            let class_nodes = mubase
                .get_nodes_by_type(crate::storage::NodeType::Class)
                .unwrap_or_default();
            let mut class_map = std::collections::HashMap::new();
            for node in class_nodes {
                class_map.insert(node.name.clone(), node.id.clone());
                if let Some(ref qname) = node.qualified_name {
                    class_map.insert(qname.clone(), node.id.clone());
                }
            }

            (func_map, class_map)
        };

        for file_path in changed_files {
            // Make path relative
            let rel_path = file_path
                .strip_prefix(root)
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_else(|_| file_path.to_string_lossy().to_string());

            // Delete old nodes for this file
            {
                let mubase = self.state.mubase.write().await;
                let deleted = mubase.delete_nodes_for_file(&rel_path)?;
                debug!("Deleted {} nodes for {}", deleted, rel_path);
            }

            // Re-parse the file
            if file_path.exists() {
                if let Ok(content) = std::fs::read_to_string(file_path) {
                    let language = detect_language(file_path);
                    if let Some(lang) = language {
                        let result = mu_core::parser::parse_source(&content, &rel_path, &lang);

                        if result.success {
                            if let Some(ref module) = result.module {
                                let (nodes, edges) = build_nodes_for_module(
                                    module,
                                    &rel_path,
                                    Some(&func_lookup),
                                    Some(&class_lookup),
                                );

                                let mubase = self.state.mubase.write().await;
                                mubase.insert_nodes(&nodes)?;
                                mubase.insert_edges(&edges)?;

                                total_nodes += nodes.len();
                                total_edges += edges.len();
                            }
                        }
                    }
                }
            }
        }

        // Reload graph
        {
            let mubase = self.state.mubase.read().await;
            let new_graph = mubase.load_graph()?;
            let mut graph = self.state.graph.write().await;
            *graph = new_graph;
        }

        Ok(BuildResult {
            node_count: total_nodes,
            edge_count: total_edges,
            file_count: changed_files.len(),
            duration: start.elapsed(),
        })
    }
}

/// Build nodes and edges for a single module.
/// If func_lookup is provided, CALLS edges will be created.
/// If class_lookup is provided, inheritance edges will resolve to actual class IDs.
fn build_nodes_for_module(
    module: &mu_core::types::ModuleDef,
    rel_path: &str,
    func_lookup: Option<&std::collections::HashMap<String, String>>,
    class_lookup: Option<&std::collections::HashMap<String, String>>,
) -> (Vec<Node>, Vec<Edge>) {
    let mut nodes = Vec::new();
    let mut edges = Vec::new();

    // Module node
    let module_node = Node::module(rel_path);
    let module_id = module_node.id.clone();
    nodes.push(module_node);

    // Classes
    for class in &module.classes {
        let class_node = Node::class(rel_path, &class.name, class.start_line, class.end_line);
        let class_id = class_node.id.clone();
        nodes.push(class_node);
        edges.push(Edge::contains(&module_id, &class_id));

        // Inheritance - resolve to actual class if found in class_lookup
        for base in &class.bases {
            let base_id = if let Some(lookup) = class_lookup {
                if let Some(resolved_id) = lookup.get(base) {
                    resolved_id.clone()
                } else {
                    format!("ext:{}", base)
                }
            } else {
                format!("ext:{}", base)
            };
            edges.push(Edge::inherits(&class_id, &base_id));
        }

        // Methods
        for method in &class.methods {
            let method_node = Node::function(
                rel_path,
                &method.name,
                Some(&class.name),
                method.start_line,
                method.end_line,
                method.body_complexity,
            );
            let method_id = method_node.id.clone();
            nodes.push(method_node);
            edges.push(Edge::contains(&class_id, &method_id));

            // Create CALLS edges if func_lookup is available
            if let Some(lookup) = func_lookup {
                for call in &method.call_sites {
                    if let Some(target_id) = resolve_call_site(
                        call,
                        rel_path,
                        Some(&class.name),
                        lookup,
                        &module.imports,
                    ) {
                        edges.push(Edge::calls(&method_id, &target_id));
                    }
                }
            }
        }

        // Create USES edges for referenced types (types used in method signatures)
        for ref_type in &class.referenced_types {
            // Try to resolve to an internal class, otherwise mark as external
            let target_id = if let Some(lookup) = class_lookup {
                if let Some(resolved_id) = lookup.get(ref_type) {
                    resolved_id.clone()
                } else {
                    format!("ext:{}", ref_type)
                }
            } else {
                format!("ext:{}", ref_type)
            };
            edges.push(Edge::uses(&class_id, &target_id));
        }
    }

    // Functions
    for func in &module.functions {
        let func_node = Node::function(
            rel_path,
            &func.name,
            None,
            func.start_line,
            func.end_line,
            func.body_complexity,
        );
        let func_id = func_node.id.clone();
        nodes.push(func_node);
        edges.push(Edge::contains(&module_id, &func_id));

        // Create CALLS edges if func_lookup is available
        if let Some(lookup) = func_lookup {
            for call in &func.call_sites {
                if let Some(target_id) =
                    resolve_call_site(call, rel_path, None, lookup, &module.imports)
                {
                    edges.push(Edge::calls(&func_id, &target_id));
                }
            }
        }
    }

    // Imports
    for import in &module.imports {
        let target_id = format!("mod:{}", import.module.replace('.', "/"));
        edges.push(Edge::imports(&module_id, &target_id));
    }

    (nodes, edges)
}

/// Resolve a call site to a target function node ID.
fn resolve_call_site(
    call: &mu_core::types::CallSiteDef,
    current_module: &str,
    current_class: Option<&str>,
    func_lookup: &std::collections::HashMap<String, String>,
    imports: &[mu_core::types::ImportDef],
) -> Option<String> {
    let callee = &call.callee;

    // 1. Method call on self - look in current class
    // Python: self, cls | C#/Java: this, base/super
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

    // 3. Check by simple name (may match if unique)
    if let Some(target_id) = func_lookup.get(callee) {
        return Some(target_id.clone());
    }

    // 4. Check imported names
    for import in imports {
        if import.names.contains(&callee.to_string()) {
            // Resolve to imported module's function
            let import_path = import.module.replace('.', "/");
            let imported_fn_id = format!("fn:{}:{}", import_path, callee);
            if func_lookup.contains_key(&imported_fn_id) {
                return Some(imported_fn_id);
            }
        }
    }

    // 5. Unresolved - return None (no edge created)
    None
}

/// Resolve an import statement to a module ID.
fn resolve_import(import_path: &str, root: &str) -> String {
    // Simple resolution: convert dots to slashes
    // In reality, this would need to check if the file exists
    let path = import_path.replace('.', "/");

    // Check common patterns
    if import_path.starts_with('.') {
        // Relative import - would need context to resolve
        format!("mod:{}", path)
    } else if import_path.contains('.') {
        // Could be internal or external
        format!("mod:{}", path)
    } else {
        // Single name - likely external package
        format!("ext:{}", import_path)
    }
}

/// Detect language from file extension.
fn detect_language(path: &Path) -> Option<String> {
    let ext = path.extension()?.to_str()?;
    match ext {
        "py" => Some("python".to_string()),
        "ts" => Some("typescript".to_string()),
        "tsx" => Some("typescript".to_string()),
        "js" => Some("javascript".to_string()),
        "jsx" => Some("javascript".to_string()),
        "go" => Some("go".to_string()),
        "java" => Some("java".to_string()),
        "rs" => Some("rust".to_string()),
        "cs" => Some("csharp".to_string()),
        _ => None,
    }
}
