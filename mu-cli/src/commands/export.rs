//! Export command - Multi-format graph export
//!
//! Exports the code graph from MUbase to various formats:
//! - mu: MU sigil format
//! - json: JSON graph representation
//! - mermaid: Mermaid diagram syntax
//! - d2: D2 diagram syntax
//! - cytoscape: Cytoscape.js JSON format

use crate::output::{Output, OutputFormat, TableDisplay};
use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::Connection;
use serde::Serialize;
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::PathBuf;

/// Find the MUbase database in the given directory or its parents.
fn find_mubase(start_path: &str) -> Result<PathBuf> {
    let start = std::path::Path::new(start_path).canonicalize()?;
    let mut current = start.as_path();

    loop {
        // New standard path: .mu/mubase
        let mu_dir = current.join(".mu");
        let db_path = mu_dir.join("mubase");
        if db_path.exists() {
            return Ok(db_path);
        }

        // Legacy path: .mubase
        let legacy_path = current.join(".mubase");
        if legacy_path.exists() {
            return Ok(legacy_path);
        }

        // Move up to parent
        match current.parent() {
            Some(parent) => current = parent,
            None => {
                return Err(anyhow::anyhow!(
                    "No MUbase found. Run 'mu bootstrap' first to create the database."
                ))
            }
        }
    }
}

/// Export format
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExportFormat {
    Mu,
    Json,
    Mermaid,
    D2,
    Cytoscape,
}

impl ExportFormat {
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "mu" => Some(Self::Mu),
            "json" => Some(Self::Json),
            "mermaid" => Some(Self::Mermaid),
            "d2" => Some(Self::D2),
            "cytoscape" => Some(Self::Cytoscape),
            _ => None,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Mu => "mu",
            Self::Json => "json",
            Self::Mermaid => "mermaid",
            Self::D2 => "d2",
            Self::Cytoscape => "cytoscape",
        }
    }
}

/// Node data from MUbase
#[derive(Debug, Clone, Serialize)]
pub struct GraphNode {
    pub id: String,
    pub name: String,
    pub node_type: String,
    pub file_path: Option<String>,
    pub complexity: Option<i32>,
}

/// Edge data from MUbase
#[derive(Debug, Clone, Serialize)]
pub struct GraphEdge {
    pub source: String,
    pub target: String,
    pub edge_type: String,
}

/// Export result
#[derive(Debug, Serialize)]
pub struct ExportResult {
    pub format: String,
    pub node_count: usize,
    pub edge_count: usize,
    pub output_path: Option<String>,
    pub content: String,
}

impl TableDisplay for ExportResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        if let Some(ref path) = self.output_path {
            output.push_str(&format!(
                "{} Exported {} nodes, {} edges to {}\n",
                "SUCCESS:".green().bold(),
                self.node_count,
                self.edge_count,
                path.cyan()
            ));
        } else {
            // Content was printed to stdout, just show stats
            output.push_str(&self.content);
        }

        output
    }

    fn to_mu(&self) -> String {
        format!(
            ":: export format={} nodes={} edges={}\n{}",
            self.format, self.node_count, self.edge_count, self.content
        )
    }
}

/// Load nodes from the database
fn load_nodes(conn: &Connection, node_filter: Option<&str>) -> Result<Vec<GraphNode>> {
    let sql = if let Some(filter) = node_filter {
        format!(
            "SELECT id, name, type, file_path, complexity FROM nodes WHERE id LIKE '%{}%' OR name LIKE '%{}%'",
            filter.replace('\'', "''"),
            filter.replace('\'', "''")
        )
    } else {
        "SELECT id, name, type, file_path, complexity FROM nodes".to_string()
    };

    let mut stmt = conn.prepare(&sql)?;
    let mut rows = stmt.query([])?;
    let mut nodes = Vec::new();

    while let Some(row) = rows.next()? {
        nodes.push(GraphNode {
            id: row.get(0)?,
            name: row.get(1)?,
            node_type: row.get(2)?,
            file_path: row.get(3)?,
            complexity: row.get(4)?,
        });
    }

    Ok(nodes)
}

/// Load edges from the database
fn load_edges(conn: &Connection, node_ids: Option<&[String]>) -> Result<Vec<GraphEdge>> {
    let sql = if let Some(ids) = node_ids {
        let id_list: Vec<String> = ids
            .iter()
            .map(|id| format!("'{}'", id.replace('\'', "''")))
            .collect();
        format!(
            "SELECT source_id, target_id, type FROM edges WHERE source_id IN ({}) OR target_id IN ({})",
            id_list.join(","),
            id_list.join(",")
        )
    } else {
        "SELECT source_id, target_id, type FROM edges".to_string()
    };

    let mut stmt = conn.prepare(&sql)?;
    let mut rows = stmt.query([])?;
    let mut edges = Vec::new();

    while let Some(row) = rows.next()? {
        edges.push(GraphEdge {
            source: row.get(0)?,
            target: row.get(1)?,
            edge_type: row.get(2)?,
        });
    }

    Ok(edges)
}

/// Export to MU sigil format
fn export_mu_format(nodes: &[GraphNode], edges: &[GraphEdge]) -> String {
    let mut output = String::new();

    output.push_str(":: MU Graph Export\n");
    output.push_str(&format!("# nodes: {}\n", nodes.len()));
    output.push_str(&format!("# edges: {}\n\n", edges.len()));

    // Group nodes by type
    let mut by_type: HashMap<&str, Vec<&GraphNode>> = HashMap::new();
    for node in nodes {
        by_type.entry(&node.node_type).or_default().push(node);
    }

    // Export modules
    if let Some(modules) = by_type.get("module") {
        output.push_str("## Modules\n");
        for node in modules {
            output.push_str(&format!("! {}\n", node.name));
            if let Some(ref path) = node.file_path {
                output.push_str(&format!("  | {}\n", path));
            }
        }
        output.push('\n');
    }

    // Export classes
    if let Some(classes) = by_type.get("class") {
        output.push_str("## Classes\n");
        for node in classes {
            output.push_str(&format!("$ {}\n", node.name));
            if let Some(ref path) = node.file_path {
                output.push_str(&format!("  | {}\n", path));
            }
        }
        output.push('\n');
    }

    // Export functions
    if let Some(functions) = by_type.get("function") {
        output.push_str("## Functions\n");
        for node in functions {
            let complexity_str = node
                .complexity
                .map(|c| format!(" c={}", c))
                .unwrap_or_default();
            output.push_str(&format!("# {}{}\n", node.name, complexity_str));
        }
        output.push('\n');
    }

    // Export edges
    output.push_str("## Dependencies\n");
    for edge in edges {
        output.push_str(&format!(
            "@ {} -> {} [{}]\n",
            edge.source, edge.target, edge.edge_type
        ));
    }

    output
}

/// Export to JSON format
fn export_json_format(nodes: &[GraphNode], edges: &[GraphEdge]) -> Result<String> {
    #[derive(Serialize)]
    struct JsonGraph {
        nodes: Vec<GraphNode>,
        edges: Vec<GraphEdge>,
        metadata: JsonMetadata,
    }

    #[derive(Serialize)]
    struct JsonMetadata {
        node_count: usize,
        edge_count: usize,
        generated_by: String,
    }

    let graph = JsonGraph {
        metadata: JsonMetadata {
            node_count: nodes.len(),
            edge_count: edges.len(),
            generated_by: "mu export".to_string(),
        },
        nodes: nodes.to_vec(),
        edges: edges.to_vec(),
    };

    serde_json::to_string_pretty(&graph)
        .map_err(|e| anyhow::anyhow!("JSON serialization failed: {}", e))
}

/// Export to Mermaid diagram format
fn export_mermaid_format(nodes: &[GraphNode], edges: &[GraphEdge]) -> String {
    let mut output = String::new();

    output.push_str("flowchart TD\n");
    output.push_str("    %% MU Graph Export\n\n");

    // Create node ID mapping (Mermaid needs clean IDs)
    let mut id_map: HashMap<&str, String> = HashMap::new();
    for (i, node) in nodes.iter().enumerate() {
        let clean_id = format!("n{}", i);
        id_map.insert(&node.id, clean_id);
    }

    // Define nodes with shapes based on type
    output.push_str("    %% Nodes\n");
    for node in nodes {
        if let Some(clean_id) = id_map.get(node.id.as_str()) {
            let shape = match node.node_type.as_str() {
                "module" => format!("{}[[\"{}\n📦 module\"]]", clean_id, node.name),
                "class" => format!("{}[/\"{}\n📦 class\"/]", clean_id, node.name),
                "function" => format!("{}(\"{}\n⚙️ function\")", clean_id, node.name),
                _ => format!("{}[\"{}\"]", clean_id, node.name),
            };
            output.push_str(&format!("    {}\n", shape));
        }
    }

    output.push('\n');

    // Define edges
    output.push_str("    %% Edges\n");
    for edge in edges {
        if let (Some(source_id), Some(target_id)) = (
            id_map.get(edge.source.as_str()),
            id_map.get(edge.target.as_str()),
        ) {
            let arrow = match edge.edge_type.as_str() {
                "imports" => "-->",
                "calls" => "-.->",
                "inherits" => "==>",
                _ => "-->",
            };
            output.push_str(&format!(
                "    {} {}|{}| {}\n",
                source_id, arrow, edge.edge_type, target_id
            ));
        }
    }

    output
}

/// Export to D2 diagram format
fn export_d2_format(nodes: &[GraphNode], edges: &[GraphEdge]) -> String {
    let mut output = String::new();

    output.push_str("# MU Graph Export\n\n");

    // Create node ID mapping (D2 needs clean IDs)
    let mut id_map: HashMap<&str, String> = HashMap::new();
    for (i, node) in nodes.iter().enumerate() {
        let clean_id = format!("n{}", i);
        id_map.insert(&node.id, clean_id.clone());
    }

    // Define nodes with shapes based on type
    for node in nodes {
        if let Some(clean_id) = id_map.get(node.id.as_str()) {
            let shape = match node.node_type.as_str() {
                "module" => "rectangle",
                "class" => "class",
                "function" => "oval",
                _ => "rectangle",
            };
            output.push_str(&format!("{}: {} {{\n", clean_id, node.name));
            output.push_str(&format!("  shape: {}\n", shape));
            if let Some(ref path) = node.file_path {
                output.push_str(&format!("  tooltip: {}\n", path));
            }
            output.push_str("}\n\n");
        }
    }

    // Define edges
    for edge in edges {
        if let (Some(source_id), Some(target_id)) = (
            id_map.get(edge.source.as_str()),
            id_map.get(edge.target.as_str()),
        ) {
            let style = match edge.edge_type.as_str() {
                "imports" => "->",
                "calls" => "-->",
                "inherits" => "->",
                _ => "->",
            };
            output.push_str(&format!(
                "{} {} {}: {}\n",
                source_id, style, target_id, edge.edge_type
            ));
        }
    }

    output
}

/// Export to Cytoscape.js JSON format
fn export_cytoscape_format(nodes: &[GraphNode], edges: &[GraphEdge]) -> Result<String> {
    #[derive(Serialize)]
    struct CytoscapeGraph {
        elements: CytoscapeElements,
    }

    #[derive(Serialize)]
    struct CytoscapeElements {
        nodes: Vec<CytoscapeNode>,
        edges: Vec<CytoscapeEdge>,
    }

    #[derive(Serialize)]
    struct CytoscapeNode {
        data: CytoscapeNodeData,
    }

    #[derive(Serialize)]
    struct CytoscapeNodeData {
        id: String,
        label: String,
        #[serde(rename = "type")]
        node_type: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        file_path: Option<String>,
        #[serde(skip_serializing_if = "Option::is_none")]
        complexity: Option<i32>,
    }

    #[derive(Serialize)]
    struct CytoscapeEdge {
        data: CytoscapeEdgeData,
    }

    #[derive(Serialize)]
    struct CytoscapeEdgeData {
        id: String,
        source: String,
        target: String,
        #[serde(rename = "type")]
        edge_type: String,
    }

    let cytoscape_nodes: Vec<CytoscapeNode> = nodes
        .iter()
        .map(|n| CytoscapeNode {
            data: CytoscapeNodeData {
                id: n.id.clone(),
                label: n.name.clone(),
                node_type: n.node_type.clone(),
                file_path: n.file_path.clone(),
                complexity: n.complexity,
            },
        })
        .collect();

    let cytoscape_edges: Vec<CytoscapeEdge> = edges
        .iter()
        .enumerate()
        .map(|(i, e)| CytoscapeEdge {
            data: CytoscapeEdgeData {
                id: format!("e{}", i),
                source: e.source.clone(),
                target: e.target.clone(),
                edge_type: e.edge_type.clone(),
            },
        })
        .collect();

    let graph = CytoscapeGraph {
        elements: CytoscapeElements {
            nodes: cytoscape_nodes,
            edges: cytoscape_edges,
        },
    };

    serde_json::to_string_pretty(&graph)
        .map_err(|e| anyhow::anyhow!("JSON serialization failed: {}", e))
}

/// Run the export command
pub async fn run(
    export_format: &str,
    output_path: Option<&str>,
    node_filter: Option<&str>,
    limit: Option<usize>,
    format: OutputFormat,
) -> Result<()> {
    // Parse export format
    let exp_format = ExportFormat::from_str(export_format).ok_or_else(|| {
        anyhow::anyhow!(
            "Unknown export format: {}. Valid formats: mu, json, mermaid, d2, cytoscape",
            export_format
        )
    })?;

    run_direct(exp_format, output_path, node_filter, limit, format).await
}

/// Run export command with direct database access
async fn run_direct(
    exp_format: ExportFormat,
    output_path: Option<&str>,
    node_filter: Option<&str>,
    limit: Option<usize>,
    format: OutputFormat,
) -> Result<()> {
    // Find the MUbase database
    let db_path = find_mubase(".")?;

    // Open the database in read-only mode
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    // Load nodes
    let mut nodes = load_nodes(&conn, node_filter)?;

    // Apply limit if specified
    if let Some(max_nodes) = limit {
        nodes.truncate(max_nodes);
    }

    // Load edges (filtered if we have a node filter)
    let node_ids: Option<Vec<String>> = if node_filter.is_some() {
        Some(nodes.iter().map(|n| n.id.clone()).collect())
    } else {
        None
    };
    let edges = load_edges(&conn, node_ids.as_deref())?;

    // Generate export content
    let content = match exp_format {
        ExportFormat::Mu => export_mu_format(&nodes, &edges),
        ExportFormat::Json => export_json_format(&nodes, &edges)?,
        ExportFormat::Mermaid => export_mermaid_format(&nodes, &edges),
        ExportFormat::D2 => export_d2_format(&nodes, &edges),
        ExportFormat::Cytoscape => export_cytoscape_format(&nodes, &edges)?,
    };

    // Write to file or stdout
    let output_file = if let Some(path) = output_path {
        let mut file = fs::File::create(path)?;
        file.write_all(content.as_bytes())?;
        Some(path.to_string())
    } else {
        None
    };

    let result = ExportResult {
        format: exp_format.as_str().to_string(),
        node_count: nodes.len(),
        edge_count: edges.len(),
        output_path: output_file,
        content: if output_path.is_some() {
            String::new()
        } else {
            content
        },
    };

    Output::new(result, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_export_format_from_str() {
        assert_eq!(ExportFormat::from_str("mu"), Some(ExportFormat::Mu));
        assert_eq!(ExportFormat::from_str("json"), Some(ExportFormat::Json));
        assert_eq!(
            ExportFormat::from_str("mermaid"),
            Some(ExportFormat::Mermaid)
        );
        assert_eq!(ExportFormat::from_str("d2"), Some(ExportFormat::D2));
        assert_eq!(
            ExportFormat::from_str("cytoscape"),
            Some(ExportFormat::Cytoscape)
        );
        assert_eq!(
            ExportFormat::from_str("MERMAID"),
            Some(ExportFormat::Mermaid)
        );
        assert_eq!(ExportFormat::from_str("unknown"), None);
    }

    #[test]
    fn test_mermaid_export() {
        let nodes = vec![
            GraphNode {
                id: "mod:src/main.py".to_string(),
                name: "main".to_string(),
                node_type: "module".to_string(),
                file_path: Some("src/main.py".to_string()),
                complexity: None,
            },
            GraphNode {
                id: "fn:src/main.py:hello".to_string(),
                name: "hello".to_string(),
                node_type: "function".to_string(),
                file_path: Some("src/main.py".to_string()),
                complexity: Some(2),
            },
        ];

        let edges = vec![GraphEdge {
            source: "mod:src/main.py".to_string(),
            target: "fn:src/main.py:hello".to_string(),
            edge_type: "contains".to_string(),
        }];

        let output = export_mermaid_format(&nodes, &edges);

        assert!(output.contains("flowchart TD"));
        assert!(output.contains("main"));
        assert!(output.contains("hello"));
    }

    #[test]
    fn test_d2_export() {
        let nodes = vec![GraphNode {
            id: "mod:test".to_string(),
            name: "test".to_string(),
            node_type: "module".to_string(),
            file_path: None,
            complexity: None,
        }];

        let edges = vec![];

        let output = export_d2_format(&nodes, &edges);

        assert!(output.contains("test"));
        assert!(output.contains("shape: rectangle"));
    }

    #[test]
    fn test_cytoscape_export() {
        let nodes = vec![GraphNode {
            id: "mod:test".to_string(),
            name: "test".to_string(),
            node_type: "module".to_string(),
            file_path: None,
            complexity: None,
        }];

        let edges = vec![];

        let output = export_cytoscape_format(&nodes, &edges).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&output).unwrap();

        assert!(parsed["elements"]["nodes"].is_array());
        assert_eq!(parsed["elements"]["nodes"][0]["data"]["label"], "test");
    }
}
