//! Data loading for codebase compression.

use super::models::*;
use anyhow::{Context, Result};
use duckdb::Connection;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

/// Type alias for relationship maps: node_id -> [(related_node_id, edge_type)]
type RelationshipMap = HashMap<String, Vec<(String, String)>>;

/// Find the MUbase database in the given directory or its parents
pub fn find_mubase(start_path: &str) -> Option<PathBuf> {
    let start = std::path::Path::new(start_path).canonicalize().ok()?;
    let mut current = start.as_path();

    loop {
        let mu_dir = current.join(".mu");
        let db_path = mu_dir.join("mubase");
        if db_path.exists() {
            return Some(db_path);
        }

        let legacy_path = current.join(".mubase");
        if legacy_path.exists() {
            return Some(legacy_path);
        }

        match current.parent() {
            Some(parent) => current = parent,
            None => return None,
        }
    }
}

/// Raw node from the database
#[derive(Debug)]
pub struct RawNode {
    pub id: String,
    pub name: String,
    pub node_type: String,
    pub qualified_name: Option<String>,
    pub file_path: Option<String>,
    pub complexity: Option<i32>,
    pub properties: Option<String>,
}

/// Raw edge from the database
#[derive(Debug)]
pub struct RawEdge {
    pub source_id: String,
    pub target_id: String,
    pub edge_type: String,
}

/// Load nodes from the database
fn load_nodes(conn: &Connection) -> Result<Vec<RawNode>> {
    let mut stmt = conn.prepare(
        "SELECT id, name, type, qualified_name, file_path, complexity, properties FROM nodes",
    )?;
    let mut rows = stmt.query([])?;
    let mut nodes = Vec::new();

    while let Some(row) = rows.next()? {
        nodes.push(RawNode {
            id: row.get(0)?,
            name: row.get(1)?,
            node_type: row.get(2)?,
            qualified_name: row.get(3)?,
            file_path: row.get(4)?,
            complexity: row.get(5)?,
            properties: row.get(6)?,
        });
    }

    Ok(nodes)
}

/// Load edges from the database
fn load_edges(conn: &Connection) -> Result<Vec<RawEdge>> {
    let mut stmt = conn.prepare("SELECT source_id, target_id, type FROM edges")?;
    let mut rows = stmt.query([])?;
    let mut edges = Vec::new();

    while let Some(row) = rows.next()? {
        edges.push(RawEdge {
            source_id: row.get(0)?,
            target_id: row.get(1)?,
            edge_type: row.get(2)?,
        });
    }

    Ok(edges)
}

/// Count incoming calls for each node
fn count_incoming_calls(edges: &[RawEdge]) -> HashMap<String, u32> {
    let mut counts: HashMap<String, u32> = HashMap::new();
    for edge in edges {
        if edge.edge_type == "calls" {
            *counts.entry(edge.target_id.clone()).or_default() += 1;
        }
    }
    counts
}

/// Build outgoing/incoming maps for relationship clusters
fn build_relationship_maps(edges: &[RawEdge]) -> (RelationshipMap, RelationshipMap) {
    let mut outgoing: RelationshipMap = HashMap::new();
    let mut incoming: RelationshipMap = HashMap::new();

    for edge in edges {
        outgoing
            .entry(edge.source_id.clone())
            .or_default()
            .push((edge.target_id.clone(), edge.edge_type.clone()));
        incoming
            .entry(edge.target_id.clone())
            .or_default()
            .push((edge.source_id.clone(), edge.edge_type.clone()));
    }

    (outgoing, incoming)
}

/// Extract function signature from properties JSON
fn extract_signature(node: &RawNode) -> String {
    if let Some(ref props) = node.properties {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(props) {
            let params = json
                .get("parameters")
                .and_then(|p| p.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|p| {
                            let name = p.get("name")?.as_str()?;
                            if name == "self" || name == "cls" {
                                return None;
                            }
                            let type_ann = p
                                .get("type_annotation")
                                .and_then(|t| t.as_str())
                                .filter(|s| !s.is_empty());
                            if let Some(t) = type_ann {
                                Some(format!("{}: {}", name, t))
                            } else {
                                Some(name.to_string())
                            }
                        })
                        .collect::<Vec<_>>()
                        .join(", ")
                })
                .unwrap_or_default();

            let return_type = json
                .get("return_type")
                .and_then(|r| r.as_str())
                .filter(|s| !s.is_empty())
                .map(|r| format!(" -> {}", r))
                .unwrap_or_default();

            return format!("({}){}", params, return_type);
        }
    }
    "()".to_string()
}

/// Extract bases from class properties
fn extract_bases(node: &RawNode) -> Vec<String> {
    if let Some(ref props) = node.properties {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(props) {
            if let Some(bases) = json.get("bases").and_then(|b| b.as_array()) {
                return bases
                    .iter()
                    .filter_map(|b| b.as_str().map(|s| s.to_string()))
                    .collect();
            }
        }
    }
    Vec::new()
}

/// Extract attributes from class properties
pub fn extract_attributes(node: &RawNode) -> Vec<String> {
    if let Some(ref props) = node.properties {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(props) {
            if let Some(attrs) = json.get("attributes").and_then(|a| a.as_array()) {
                return attrs
                    .iter()
                    .filter_map(|a| a.as_str().map(|s| s.to_string()))
                    .collect();
            }
        }
    }
    Vec::new()
}

/// Extract docstring from properties
fn extract_docstring(node: &RawNode) -> Option<String> {
    if let Some(ref props) = node.properties {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(props) {
            return json
                .get("docstring")
                .and_then(|d| d.as_str())
                .filter(|s| !s.is_empty())
                .map(|s| s.lines().next().unwrap_or(s).to_string());
        }
    }
    None
}

/// Load compressed codebase from database
pub fn load_from_database(db_path: &Path, source: &str) -> Result<CompressedCodebase> {
    let conn = Connection::open_with_flags(
        db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    let nodes = load_nodes(&conn)?;
    let edges = load_edges(&conn)?;

    let call_counts = count_incoming_calls(&edges);
    let (outgoing_map, incoming_map) = build_relationship_maps(&edges);

    let node_by_id: HashMap<&str, &RawNode> = nodes.iter().map(|n| (n.id.as_str(), n)).collect();

    let modules: Vec<&RawNode> = nodes.iter().filter(|n| n.node_type == "module").collect();
    let classes: Vec<&RawNode> = nodes.iter().filter(|n| n.node_type == "class").collect();
    let functions: Vec<&RawNode> = nodes.iter().filter(|n| n.node_type == "function").collect();

    let mut class_methods: HashMap<String, Vec<String>> = HashMap::new();
    let mut module_classes: HashMap<String, Vec<String>> = HashMap::new();
    let mut module_functions: HashMap<String, Vec<String>> = HashMap::new();

    for edge in &edges {
        if edge.edge_type == "contains" {
            if let Some(target_node) = node_by_id.get(edge.target_id.as_str()) {
                match target_node.node_type.as_str() {
                    "function" => {
                        if let Some(source_node) = node_by_id.get(edge.source_id.as_str()) {
                            if source_node.node_type == "class" {
                                class_methods
                                    .entry(edge.source_id.clone())
                                    .or_default()
                                    .push(edge.target_id.clone());
                            } else if source_node.node_type == "module" {
                                module_functions
                                    .entry(edge.source_id.clone())
                                    .or_default()
                                    .push(edge.target_id.clone());
                            }
                        }
                    }
                    "class" => {
                        module_classes
                            .entry(edge.source_id.clone())
                            .or_default()
                            .push(edge.target_id.clone());
                    }
                    _ => {}
                }
            }
        }
    }

    let mut compressed_modules: Vec<CompressedModule> = Vec::new();
    let mut hot_paths: Vec<HotPath> = Vec::new();

    for module_node in &modules {
        let module_id = &module_node.id;
        let file_path = module_node
            .file_path
            .clone()
            .unwrap_or_else(|| module_node.name.clone());

        let mut module_class_list: Vec<CompressedClass> = Vec::new();
        if let Some(class_ids) = module_classes.get(module_id) {
            for class_id in class_ids {
                if let Some(class_node) = node_by_id.get(class_id.as_str()) {
                    let mut methods: Vec<CompressedFunction> = Vec::new();
                    if let Some(method_ids) = class_methods.get(class_id) {
                        for method_id in method_ids {
                            if let Some(method_node) = node_by_id.get(method_id.as_str()) {
                                let complexity = method_node.complexity.unwrap_or(0) as u32;
                                let call_count = call_counts.get(method_id).copied().unwrap_or(0);
                                let is_hot = complexity > 20 || call_count > 5;

                                let func = CompressedFunction {
                                    name: method_node.name.clone(),
                                    qualified_name: method_node
                                        .qualified_name
                                        .clone()
                                        .unwrap_or_else(|| method_node.name.clone()),
                                    signature: extract_signature(method_node),
                                    complexity,
                                    call_count,
                                    is_hot,
                                    docstring: extract_docstring(method_node),
                                };

                                if is_hot {
                                    hot_paths.push(HotPath {
                                        qualified_name: func.qualified_name.clone(),
                                        complexity,
                                        call_count,
                                        file_path: file_path.clone(),
                                    });
                                }

                                methods.push(func);
                            }
                        }
                    }

                    let uses: Vec<String> = outgoing_map
                        .get(class_id)
                        .map(|rels| {
                            rels.iter()
                                .filter(|(_, t)| t != "contains")
                                .filter_map(|(target, _)| {
                                    node_by_id.get(target.as_str()).map(|n| n.name.clone())
                                })
                                .collect::<HashSet<_>>()
                                .into_iter()
                                .take(5)
                                .collect()
                        })
                        .unwrap_or_default();

                    let used_by: Vec<String> = incoming_map
                        .get(class_id)
                        .map(|rels| {
                            rels.iter()
                                .filter(|(_, t)| t != "contains")
                                .filter_map(|(source, _)| {
                                    node_by_id.get(source.as_str()).map(|n| n.name.clone())
                                })
                                .collect::<HashSet<_>>()
                                .into_iter()
                                .take(5)
                                .collect()
                        })
                        .unwrap_or_default();

                    module_class_list.push(CompressedClass {
                        name: class_node.name.clone(),
                        bases: extract_bases(class_node),
                        uses,
                        used_by,
                        methods,
                        attributes: extract_attributes(class_node),
                    });
                }
            }
        }

        let mut module_func_list: Vec<CompressedFunction> = Vec::new();
        if let Some(func_ids) = module_functions.get(module_id) {
            for func_id in func_ids {
                if let Some(func_node) = node_by_id.get(func_id.as_str()) {
                    let complexity = func_node.complexity.unwrap_or(0) as u32;
                    let call_count = call_counts.get(func_id).copied().unwrap_or(0);
                    let is_hot = complexity > 20 || call_count > 5;

                    let func = CompressedFunction {
                        name: func_node.name.clone(),
                        qualified_name: func_node
                            .qualified_name
                            .clone()
                            .unwrap_or_else(|| func_node.name.clone()),
                        signature: extract_signature(func_node),
                        complexity,
                        call_count,
                        is_hot,
                        docstring: extract_docstring(func_node),
                    };

                    if is_hot {
                        hot_paths.push(HotPath {
                            qualified_name: func.qualified_name.clone(),
                            complexity,
                            call_count,
                            file_path: file_path.clone(),
                        });
                    }

                    module_func_list.push(func);
                }
            }
        }

        compressed_modules.push(CompressedModule {
            name: module_node.name.clone(),
            path: file_path,
            classes: module_class_list,
            functions: module_func_list,
        });
    }

    let tree = build_folder_tree(&compressed_modules);

    hot_paths.sort_by(|a, b| {
        let score_a = a.complexity + a.call_count * 2;
        let score_b = b.complexity + b.call_count * 2;
        score_b.cmp(&score_a)
    });
    hot_paths.truncate(20);

    let relationship_clusters = build_relationship_clusters(&classes, &node_by_id, &edges);
    let domain = build_domain_overview(&classes, &edges, &node_by_id, source);

    let stats = CodebaseStats {
        total_modules: modules.len(),
        total_classes: classes.len(),
        total_functions: functions.len(),
        total_edges: edges.len(),
        has_graph: true,
    };

    Ok(CompressedCodebase {
        source: source.to_string(),
        stats,
        domain: Some(domain),
        tree,
        hot_paths,
        relationship_clusters,
    })
}

/// Build folder tree from compressed modules
pub fn build_folder_tree(modules: &[CompressedModule]) -> FolderNode {
    let mut root = FolderNode::new(".", "");

    for module in modules {
        let path = Path::new(&module.path);
        let components: Vec<&str> = path
            .components()
            .filter_map(|c| c.as_os_str().to_str())
            .collect();

        if components.is_empty() {
            root.modules.push(module.clone());
            continue;
        }

        let mut current = &mut root;
        let (folders, _file) = components.split_at(components.len().saturating_sub(1));

        for folder in folders {
            let folder_path = if current.path.is_empty() {
                folder.to_string()
            } else {
                format!("{}/{}", current.path, folder)
            };

            current = current
                .children
                .entry(folder.to_string())
                .or_insert_with(|| FolderNode::new(folder, &folder_path));
        }

        current.modules.push(module.clone());
    }

    root
}

/// Build relationship clusters for top entities
fn build_relationship_clusters(
    classes: &[&RawNode],
    node_by_id: &HashMap<&str, &RawNode>,
    edges: &[RawEdge],
) -> Vec<RelationshipCluster> {
    let (outgoing_map, incoming_map) = build_relationship_maps(edges);

    let mut clusters: Vec<RelationshipCluster> = Vec::new();

    let mut class_rel_counts: Vec<(&RawNode, usize)> = classes
        .iter()
        .map(|c| {
            let out_count = outgoing_map
                .get(&c.id)
                .map(|v| v.iter().filter(|(_, t)| t != "contains").count())
                .unwrap_or(0);
            let in_count = incoming_map
                .get(&c.id)
                .map(|v| v.iter().filter(|(_, t)| t != "contains").count())
                .unwrap_or(0);
            (*c, out_count + in_count)
        })
        .collect();

    class_rel_counts.sort_by(|a, b| b.1.cmp(&a.1));

    for (class, rel_count) in class_rel_counts.into_iter().take(10) {
        if rel_count == 0 {
            continue;
        }

        let outgoing: Vec<Relationship> = outgoing_map
            .get(&class.id)
            .map(|rels| {
                rels.iter()
                    .filter(|(_, t)| t != "contains")
                    .filter_map(|(target, edge_type)| {
                        node_by_id.get(target.as_str()).map(|n| Relationship {
                            target: n.name.clone(),
                            edge_type: edge_type.clone(),
                        })
                    })
                    .take(10)
                    .collect()
            })
            .unwrap_or_default();

        let incoming: Vec<Relationship> = incoming_map
            .get(&class.id)
            .map(|rels| {
                rels.iter()
                    .filter(|(_, t)| t != "contains")
                    .filter_map(|(source, edge_type)| {
                        node_by_id.get(source.as_str()).map(|n| Relationship {
                            target: n.name.clone(),
                            edge_type: edge_type.clone(),
                        })
                    })
                    .take(10)
                    .collect()
            })
            .unwrap_or_default();

        clusters.push(RelationshipCluster {
            entity: class.name.clone(),
            entity_type: "class".to_string(),
            relationship_count: rel_count,
            outgoing,
            incoming,
        });
    }

    clusters
}

// Domain detection helpers

fn is_infrastructure_class(name: &str, file_path: Option<&str>) -> bool {
    let name_lower = name.to_lowercase();

    if name.contains("Report") && name.ends_with("Model") {
        return true;
    }

    let infra_name_patterns = [
        "test",
        "spec",
        "mock",
        "fake",
        "stub",
        "base",
        "abstract",
        "context",
        "dbcontext",
        "connection",
        "session",
        "middleware",
        "filter",
        "handler",
        "interceptor",
        "extension",
        "helper",
        "util",
        "utils",
        "config",
        "configuration",
        "settings",
        "options",
        "validator",
        "serializer",
        "mapper",
        "converter",
        "factory",
        "builder",
        "provider",
        "dto",
        "request",
        "response",
        "viewmodel",
        "exception",
        "error",
        "migration",
        "seed",
        "schema",
        "startup",
        "program",
        "host",
        "controller",
        "endpoint",
        "api",
        "repository",
        "service",
        "event",
        "publisher",
        "subscriber",
        "listener",
        "mixin",
        "trait",
        "protocol",
        "coordinator",
        "orchestrator",
        "manager",
    ];

    for pattern in &infra_name_patterns {
        if name_lower.contains(pattern) {
            return true;
        }
    }

    if name.starts_with('I')
        && name.len() > 1
        && name
            .chars()
            .nth(1)
            .map(|c| c.is_uppercase())
            .unwrap_or(false)
    {
        return true;
    }

    if name.ends_with("Model") {
        if let Some(path) = file_path {
            let path_lower = path.to_lowercase();
            if !path_lower.contains("/entities/") && !path_lower.contains("/domain/") {
                return true;
            }
        } else {
            return true;
        }
    }

    if let Some(path) = file_path {
        let path_lower = path.to_lowercase();
        let infra_path_patterns = [
            "/test",
            "/tests/",
            "/spec/",
            "/__tests__/",
            "_test.",
            "/migrations/",
            "/seeds/",
            "/fixtures/",
            "/config/",
            "/configuration/",
            "/middleware/",
            "/interceptors/",
            "/filters/",
            "/infrastructure/",
            "/framework/",
            "/bootstrap/",
            "/controllers/",
            "/endpoints/",
            "/api/",
            "/services/",
            "/repositories/",
            "/contracts/",
            "/responses/",
            "/requests/",
            "/dtos/",
            "/viewmodels/",
            "/shared/",
            "/common/",
            "/base/",
            "/events/",
            "/messaging/",
            "/pubsub/",
        ];
        for pattern in &infra_path_patterns {
            if path_lower.contains(pattern) {
                return true;
            }
        }
    }

    false
}

fn is_likely_entity_path(file_path: Option<&str>) -> bool {
    if let Some(path) = file_path {
        let path_lower = path.to_lowercase();
        let entity_paths = ["/entities/", "/models/", "/aggregates/"];
        for pattern in &entity_paths {
            if path_lower.contains(pattern) {
                return true;
            }
        }
        if path_lower.contains("/domain/") && !path_lower.contains("/domain/shared/") {
            return true;
        }
    }
    false
}

fn has_foreign_key_to(node: &RawNode, target_name: &str) -> bool {
    if let Some(ref props) = node.properties {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(props) {
            if let Some(attrs) = json.get("attributes").and_then(|a| a.as_array()) {
                let target_lower = target_name.to_lowercase();
                for attr in attrs {
                    if let Some(name) = attr.as_str() {
                        let name_lower = name.to_lowercase();
                        if name_lower.contains(&target_lower)
                            && (name_lower.ends_with("_id") || name_lower.ends_with("id"))
                        {
                            return true;
                        }
                    }
                }
            }
        }
    }
    false
}

fn count_foreign_keys(node: &RawNode) -> usize {
    if let Some(ref props) = node.properties {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(props) {
            if let Some(attrs) = json.get("attributes").and_then(|a| a.as_array()) {
                return attrs
                    .iter()
                    .filter_map(|a| a.as_str())
                    .filter(|name| {
                        let lower = name.to_lowercase();
                        lower.ends_with("_id") || lower.ends_with("id")
                    })
                    .count();
            }
        }
    }
    0
}

fn score_entity(
    node: &RawNode,
    incoming: usize,
    outgoing: usize,
    status_entity_names: &HashSet<String>,
) -> i32 {
    let mut score: i32 = 0;
    let name_lower = node.name.to_lowercase();

    score += (incoming as i32) * 3;
    score += outgoing as i32;
    score += (count_foreign_keys(node) as i32) * 2;

    if let Some(ref props) = node.properties {
        if let Ok(json) = serde_json::from_str::<serde_json::Value>(props) {
            let prop_count = json
                .get("attributes")
                .and_then(|a| a.as_array())
                .map(|a| a.len())
                .unwrap_or(0);
            score += (prop_count as i32) / 2;
        }
    }

    if is_infrastructure_class(&node.name, node.file_path.as_deref()) {
        score -= 100;
    }

    let core_domain_names = [
        "transaction",
        "payment",
        "order",
        "invoice",
        "customer",
        "user",
        "account",
        "merchant",
        "product",
        "subscription",
        "payout",
        "refund",
        "booking",
        "reservation",
        "shipment",
        "delivery",
        "cart",
        "checkout",
        "contract",
        "agreement",
        "claim",
        "policy",
        "ticket",
        "case",
        "ride",
        "trip",
        "driver",
        "vehicle",
        "passenger",
        "route",
        "message",
        "conversation",
        "chat",
        "employee",
        "company",
        "organization",
        "team",
        "riderequest",
        "ridebooking",
        "request",
        "notification",
        "rating",
    ];
    if core_domain_names.contains(&name_lower.as_str()) {
        score += 25;
    }

    if status_entity_names.contains(&name_lower) {
        score += 20;
    }

    let child_entity_suffixes = [
        "line",
        "item",
        "entry",
        "detail",
        "history",
        "log",
        "event",
        "assignment",
        "membership",
        "attachment",
        "note",
        "comment",
        "status",
        "state",
        "type",
    ];
    for suffix in &child_entity_suffixes {
        if name_lower.ends_with(suffix) {
            score -= 15;
            break;
        }
    }

    let support_entity_patterns = [
        "preference",
        "setting",
        "config",
        "token",
        "session",
        "cache",
        "job",
        "task",
        "queue",
        "import",
        "export",
        "sync",
        "audit",
        "template",
        "lookup",
        "reference",
        "code",
        "attempt",
    ];
    for pattern in &support_entity_patterns {
        if name_lower.contains(pattern) {
            score -= 10;
            break;
        }
    }

    if let Some(ref path) = node.file_path {
        let path_lower = path.to_lowercase();

        if path_lower.contains("/entities/") || path_lower.contains("/aggregates/") {
            score += 30;
        }
        if path_lower.contains("/models/") {
            score += 20;
        }
        if path_lower.contains("/domain/") && !path_lower.contains("/domain/shared/") {
            score += 15;
        }
        if path_lower.contains("/contracts/")
            || path_lower.contains("/responses/")
            || path_lower.contains("/requests/")
            || path_lower.contains("/dtos/")
            || path_lower.contains("/viewmodels/")
        {
            score -= 25;
        }
        if path_lower.contains("/core/") && is_likely_entity_path(Some(path)) {
            score += 15;
        }
    }

    let generic_names = [
        "item", "data", "record", "object", "entity", "model", "info", "result",
    ];
    if generic_names.contains(&name_lower.as_str()) {
        score -= 15;
    }

    score
}

fn importance_to_stars(score: i32, max_score: i32) -> u8 {
    if max_score <= 0 {
        return 1;
    }
    let normalized = ((score as f32 / max_score as f32) * 3.0).ceil() as u8;
    normalized.clamp(1, 3)
}

fn infer_relationship_type(source: &RawNode, target: &RawNode, edge_type: &str) -> String {
    match edge_type {
        "inherits" => "extends".to_string(),
        "implements" => "implements".to_string(),
        "contains" => "has_many".to_string(),
        "calls" | "uses" => {
            if has_foreign_key_to(source, &target.name) {
                "belongs_to".to_string()
            } else {
                "uses".to_string()
            }
        }
        _ => edge_type.to_string(),
    }
}

fn detect_flows(nodes: &[&RawNode]) -> Vec<StateFlow> {
    let mut flows = Vec::new();

    for node in nodes {
        let name_lower = node.name.to_lowercase();
        let is_state_enum = name_lower.ends_with("status")
            || name_lower.ends_with("state")
            || name_lower.ends_with("phase")
            || name_lower.ends_with("stage");

        if !is_state_enum {
            continue;
        }

        if let Some(ref props) = node.properties {
            if let Ok(json) = serde_json::from_str::<serde_json::Value>(props) {
                let variants = json.get("variants").and_then(|v| v.as_array());
                let attrs = json.get("attributes").and_then(|a| a.as_array());

                let values: Vec<String> = variants
                    .or(attrs)
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(String::from))
                            .filter(|s| !s.starts_with('_'))
                            .collect()
                    })
                    .unwrap_or_default();

                if values.len() >= 2 {
                    let entity = node
                        .name
                        .trim_end_matches("Status")
                        .trim_end_matches("State")
                        .trim_end_matches("Phase")
                        .trim_end_matches("Stage")
                        .to_string();

                    flows.push(StateFlow {
                        name: entity,
                        states: values,
                    });
                }
            }
        }
    }

    flows
}

fn detect_integrations(external_deps: &[String]) -> Vec<String> {
    let integration_patterns: &[(&str, &str)] = &[
        ("stripe", "payments"),
        ("braintree", "payments"),
        ("paypal", "payments"),
        ("sendgrid", "email"),
        ("mailgun", "email"),
        ("rabbitmq", "messaging"),
        ("kafka", "messaging"),
        ("redis", "cache"),
        ("elasticsearch", "search"),
        ("auth0", "auth"),
        ("cognito", "auth"),
        ("s3", "storage"),
        ("datadog", "monitoring"),
        ("sentry", "monitoring"),
        ("twilio", "sms"),
    ];

    let mut found: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    for dep in external_deps {
        let dep_lower = dep.to_lowercase();
        for (pattern, category) in integration_patterns {
            if dep_lower.contains(pattern) && !seen.contains(*pattern) {
                found.push(format!("{} ({})", pattern, category));
                seen.insert(pattern.to_string());
            }
        }
    }

    found
}

fn detect_tech_stack(external_deps: &[String]) -> Vec<String> {
    let mut stack: Vec<String> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    let stack_patterns: &[(&str, &str)] = &[
        ("tokio", "Rust/Tokio"),
        ("actix", "Rust/Actix"),
        ("axum", "Rust/Axum"),
        ("django", "Python/Django"),
        ("flask", "Python/Flask"),
        ("fastapi", "Python/FastAPI"),
        ("express", "Node.js/Express"),
        ("spring", "Java/Spring"),
        ("aspnet", "C#/ASP.NET"),
        ("postgres", "PostgreSQL"),
        ("mysql", "MySQL"),
        ("mongodb", "MongoDB"),
        ("redis", "Redis"),
        ("kafka", "Kafka"),
    ];

    for dep in external_deps {
        let dep_lower = dep.to_lowercase();
        for (pattern, tech) in stack_patterns {
            if dep_lower.contains(pattern) && !seen.contains(*tech) {
                stack.push(tech.to_string());
                seen.insert(tech.to_string());
            }
        }
    }

    stack.truncate(5);
    stack
}

fn infer_domain_name(entities: &[DomainEntity], root_path: &str) -> Option<String> {
    if entities.len() >= 3 {
        let mut prefix_counts: HashMap<String, usize> = HashMap::new();

        for entity in entities.iter().take(5) {
            let name = &entity.name;
            let mut prefix = String::new();
            for (i, c) in name.chars().enumerate() {
                if i > 0 && c.is_uppercase() && prefix.len() >= 3 {
                    break;
                }
                prefix.push(c);
            }
            if prefix.len() >= 3 && prefix.len() < name.len() {
                *prefix_counts.entry(prefix).or_default() += 1;
            }
        }

        if let Some((prefix, count)) = prefix_counts.iter().max_by_key(|(_, c)| *c) {
            if *count >= 2 {
                return Some(format!("{} System", prefix));
            }
        }
    }

    std::path::Path::new(root_path)
        .file_name()
        .map(|s| s.to_string_lossy().to_string())
        .map(|s| {
            s.replace(['-', '_'], " ")
                .split_whitespace()
                .map(|word| {
                    let mut chars = word.chars();
                    match chars.next() {
                        Some(c) => c.to_uppercase().chain(chars).collect(),
                        None => String::new(),
                    }
                })
                .collect::<Vec<_>>()
                .join(" ")
        })
        .filter(|s| !s.is_empty())
}

fn build_domain_overview(
    classes: &[&RawNode],
    edges: &[RawEdge],
    node_by_id: &HashMap<&str, &RawNode>,
    source_path: &str,
) -> DomainOverview {
    let (outgoing_map, incoming_map) = build_relationship_maps(edges);

    let status_entity_names: HashSet<String> = classes
        .iter()
        .filter_map(|node| {
            let name = &node.name;
            let name_lower = name.to_lowercase();
            if name_lower.ends_with("status") {
                Some(
                    name.trim_end_matches("Status")
                        .trim_end_matches("status")
                        .to_lowercase(),
                )
            } else if name_lower.ends_with("state") {
                Some(
                    name.trim_end_matches("State")
                        .trim_end_matches("state")
                        .to_lowercase(),
                )
            } else {
                None
            }
        })
        .filter(|s| !s.is_empty())
        .collect();

    let mut scored_classes: Vec<(&RawNode, i32)> = classes
        .iter()
        .filter(|c| !is_infrastructure_class(&c.name, c.file_path.as_deref()))
        .map(|c| {
            let out = outgoing_map
                .get(&c.id)
                .map(|v| v.iter().filter(|(_, t)| t != "contains").count())
                .unwrap_or(0);
            let in_ = incoming_map
                .get(&c.id)
                .map(|v| v.iter().filter(|(_, t)| t != "contains").count())
                .unwrap_or(0);
            let score = score_entity(c, in_, out, &status_entity_names);
            (*c, score)
        })
        .filter(|(_, score)| *score > 0)
        .collect();

    scored_classes.sort_by(|a, b| b.1.cmp(&a.1));

    let mut seen_names: HashSet<String> = HashSet::new();
    scored_classes.retain(|(node, _)| {
        let name_lower = node.name.to_lowercase();
        if seen_names.contains(&name_lower) {
            false
        } else {
            seen_names.insert(name_lower);
            true
        }
    });

    let max_score = scored_classes.first().map(|(_, s)| *s).unwrap_or(1);

    let entities: Vec<DomainEntity> = scored_classes
        .iter()
        .take(8)
        .map(|(node, score)| {
            let attributes = extract_attributes(node);

            let outgoing_rels: Vec<EntityRelationship> = outgoing_map
                .get(&node.id)
                .map(|rels| {
                    rels.iter()
                        .filter(|(_, t)| t != "contains")
                        .filter_map(|(target_id, edge_type)| {
                            node_by_id
                                .get(target_id.as_str())
                                .map(|target| EntityRelationship {
                                    target: target.name.clone(),
                                    rel_type: infer_relationship_type(node, target, edge_type),
                                })
                        })
                        .take(5)
                        .collect()
                })
                .unwrap_or_default();

            let incoming_rels: Vec<EntityRelationship> = incoming_map
                .get(&node.id)
                .map(|rels| {
                    rels.iter()
                        .filter(|(_, t)| t != "contains")
                        .filter_map(|(source_id, edge_type)| {
                            node_by_id
                                .get(source_id.as_str())
                                .map(|source| EntityRelationship {
                                    target: source.name.clone(),
                                    rel_type: edge_type.clone(),
                                })
                        })
                        .take(5)
                        .collect()
                })
                .unwrap_or_default();

            DomainEntity {
                name: node.name.clone(),
                importance: importance_to_stars(*score, max_score),
                attributes,
                outgoing_rels,
                incoming_rels,
            }
        })
        .collect();

    let flows = detect_flows(classes);

    let external_deps: Vec<String> = node_by_id
        .values()
        .filter(|n| n.node_type == "external")
        .map(|n| n.name.clone())
        .collect();

    let integrations = detect_integrations(&external_deps);
    let tech_stack = detect_tech_stack(&external_deps);
    let domain_name = infer_domain_name(&entities, source_path);

    DomainOverview {
        domain_name,
        purpose: None,
        entities,
        flows,
        integrations,
        tech_stack,
    }
}

/// Load compressed codebase from source files (no graph data)
pub fn load_from_source(path: &Path) -> Result<CompressedCodebase> {
    use mu_core::parser::parse_files_parallel;
    use mu_core::scanner::scan_directory_sync;
    use mu_core::types::FileInfo;

    let path_str = path.to_string_lossy();
    let scan_result = scan_directory_sync(&path_str, None, None, false, false, false)
        .map_err(|e| anyhow::anyhow!("Scan failed: {}", e))?;

    let file_infos: Vec<FileInfo> = scan_result
        .files
        .iter()
        .filter_map(|f| {
            let full_path = path.join(&f.path);
            let source = std::fs::read_to_string(&full_path).ok()?;
            Some(FileInfo {
                path: full_path.to_string_lossy().to_string(),
                source,
                language: f.language.clone(),
            })
        })
        .collect();

    let parse_results = parse_files_parallel(file_infos, Some(4));

    let mut compressed_modules: Vec<CompressedModule> = Vec::new();
    let mut hot_paths: Vec<HotPath> = Vec::new();
    let mut total_classes = 0;
    let mut total_functions = 0;

    for result in &parse_results {
        if !result.success {
            continue;
        }
        if let Some(ref module) = result.module {
            let file_path = module.path.clone();

            let mut classes: Vec<CompressedClass> = Vec::new();
            for class in &module.classes {
                let methods: Vec<CompressedFunction> = class
                    .methods
                    .iter()
                    .map(|m| {
                        let complexity = m.body_complexity;
                        let is_hot = complexity > 20;

                        let sig = format_signature(&m.parameters, m.return_type.as_deref());

                        if is_hot {
                            hot_paths.push(HotPath {
                                qualified_name: format!("{}.{}", class.name, m.name),
                                complexity,
                                call_count: 0,
                                file_path: file_path.clone(),
                            });
                        }

                        CompressedFunction {
                            name: m.name.clone(),
                            qualified_name: format!("{}.{}", class.name, m.name),
                            signature: sig,
                            complexity,
                            call_count: 0,
                            is_hot,
                            docstring: m.docstring.clone(),
                        }
                    })
                    .collect();

                total_functions += methods.len();

                classes.push(CompressedClass {
                    name: class.name.clone(),
                    bases: class.bases.clone(),
                    uses: Vec::new(),
                    used_by: Vec::new(),
                    methods,
                    attributes: class.attributes.clone(),
                });
            }
            total_classes += classes.len();

            let functions: Vec<CompressedFunction> = module
                .functions
                .iter()
                .map(|f| {
                    let complexity = f.body_complexity;
                    let is_hot = complexity > 20;

                    let sig = format_signature(&f.parameters, f.return_type.as_deref());

                    if is_hot {
                        hot_paths.push(HotPath {
                            qualified_name: f.name.clone(),
                            complexity,
                            call_count: 0,
                            file_path: file_path.clone(),
                        });
                    }

                    CompressedFunction {
                        name: f.name.clone(),
                        qualified_name: f.name.clone(),
                        signature: sig,
                        complexity,
                        call_count: 0,
                        is_hot,
                        docstring: f.docstring.clone(),
                    }
                })
                .collect();
            total_functions += functions.len();

            let relative_path = file_path
                .strip_prefix(path.to_string_lossy().as_ref())
                .unwrap_or(&file_path)
                .trim_start_matches('/')
                .to_string();

            compressed_modules.push(CompressedModule {
                name: module.name.clone(),
                path: if relative_path.is_empty() {
                    file_path
                } else {
                    relative_path
                },
                classes,
                functions,
            });
        }
    }

    let tree = build_folder_tree(&compressed_modules);

    hot_paths.sort_by(|a, b| b.complexity.cmp(&a.complexity));
    hot_paths.truncate(20);

    let stats = CodebaseStats {
        total_modules: compressed_modules.len(),
        total_classes,
        total_functions,
        total_edges: 0,
        has_graph: false,
    };

    Ok(CompressedCodebase {
        source: path.to_string_lossy().to_string(),
        stats,
        domain: None,
        tree,
        hot_paths,
        relationship_clusters: Vec::new(),
    })
}

/// Format function signature from parameters
fn format_signature(params: &[mu_core::types::ParameterDef], return_type: Option<&str>) -> String {
    let param_str: String = params
        .iter()
        .filter(|p| p.name != "self" && p.name != "cls")
        .map(|p| {
            if let Some(ref t) = p.type_annotation {
                format!("{}: {}", p.name, t)
            } else {
                p.name.clone()
            }
        })
        .collect::<Vec<_>>()
        .join(", ");

    let ret = return_type
        .filter(|r| !r.is_empty())
        .map(|r| format!(" -> {}", r))
        .unwrap_or_default();

    format!("({}){}", param_str, ret)
}
