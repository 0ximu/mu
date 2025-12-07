//! MUQL executor - executes query plans against MUbase.

use anyhow::{Context, Result};
use std::collections::{HashMap, HashSet, VecDeque};

use super::parser;
use super::planner::{self, AnalysisOperation, ExecutionPlan, GraphOpType, GraphOperation, SchemaOperation};
use crate::server::AppState;
use crate::storage::QueryResult;

/// Execute a MUQL query string and return results.
pub async fn execute(query_str: &str, state: &AppState) -> Result<QueryResult> {
    // Parse the query
    let query = parser::parse(query_str)
        .with_context(|| format!("Failed to parse query: {}", query_str))?;

    // Plan the query
    let plan = planner::plan(query);

    // Execute the plan
    execute_plan(plan, state).await
}

async fn execute_plan(plan: ExecutionPlan, state: &AppState) -> Result<QueryResult> {
    match plan {
        ExecutionPlan::Sql(sql) => execute_sql(&sql, state).await,
        ExecutionPlan::Graph(op) => execute_graph(op, state).await,
        ExecutionPlan::Analysis(op) => execute_analysis(op, state).await,
        ExecutionPlan::Schema(op) => execute_schema(op, state).await,
    }
}

async fn execute_sql(sql: &str, state: &AppState) -> Result<QueryResult> {
    let mubase = state.mubase.read().await;
    mubase.query(sql)
}

async fn execute_graph(op: GraphOperation, state: &AppState) -> Result<QueryResult> {
    // Load graph data
    let mubase = state.mubase.read().await;

    match op.op_type {
        GraphOpType::Cycles => {
            // Use mu-core's graph engine for cycle detection
            let graph = state.graph.read().await;
            let nodes = graph.get_nodes();
            let edges = graph.get_edges();

            // Build petgraph for cycle detection
            let cycles = find_cycles(nodes, edges, op.edge_types.as_deref());

            // Format as result
            Ok(QueryResult {
                columns: vec!["cycle".to_string()],
                rows: cycles
                    .into_iter()
                    .map(|c| vec![serde_json::Value::Array(
                        c.into_iter().map(serde_json::Value::String).collect()
                    )])
                    .collect(),
            })
        }

        GraphOpType::Impact => {
            // Find all nodes reachable FROM this node
            let graph = state.graph.read().await;
            let impacted = traverse_bfs(
                &op.target,
                graph.get_nodes(),
                graph.get_edges(),
                Direction::Outgoing,
                op.edge_types.as_deref(),
            );

            Ok(QueryResult {
                columns: vec!["id".to_string()],
                rows: impacted
                    .into_iter()
                    .map(|id| vec![serde_json::Value::String(id)])
                    .collect(),
            })
        }

        GraphOpType::Ancestors => {
            // Find all nodes that can REACH this node
            let graph = state.graph.read().await;
            let ancestors = traverse_bfs(
                &op.target,
                graph.get_nodes(),
                graph.get_edges(),
                Direction::Incoming,
                op.edge_types.as_deref(),
            );

            Ok(QueryResult {
                columns: vec!["id".to_string()],
                rows: ancestors
                    .into_iter()
                    .map(|id| vec![serde_json::Value::String(id)])
                    .collect(),
            })
        }

        GraphOpType::Dependents => {
            // Get direct dependents (who depends on this)
            let graph = state.graph.read().await;
            let deps = get_neighbors(
                &op.target,
                graph.get_edges(),
                Direction::Incoming,
                op.depth,
                op.edge_types.as_deref(),
            );

            // Get full node info from database
            let mut rows = Vec::new();
            for dep_id in deps {
                if let Ok(Some(node)) = mubase.get_node(&dep_id) {
                    rows.push(vec![
                        serde_json::Value::String(node.id),
                        serde_json::Value::String(node.node_type.as_str().to_string()),
                        serde_json::Value::String(node.name),
                        serde_json::json!(node.file_path),
                        serde_json::json!(node.complexity),
                    ]);
                }
            }

            Ok(QueryResult {
                columns: vec![
                    "id".to_string(),
                    "type".to_string(),
                    "name".to_string(),
                    "file_path".to_string(),
                    "complexity".to_string(),
                ],
                rows,
            })
        }

        GraphOpType::Dependencies | GraphOpType::Children => {
            // Get direct dependencies
            let graph = state.graph.read().await;
            let deps = get_neighbors(
                &op.target,
                graph.get_edges(),
                Direction::Outgoing,
                op.depth,
                op.edge_types.as_deref(),
            );

            // Get full node info from database
            let mut rows = Vec::new();
            for dep_id in deps {
                if let Ok(Some(node)) = mubase.get_node(&dep_id) {
                    rows.push(vec![
                        serde_json::Value::String(node.id),
                        serde_json::Value::String(node.node_type.as_str().to_string()),
                        serde_json::Value::String(node.name),
                        serde_json::json!(node.file_path),
                        serde_json::json!(node.complexity),
                    ]);
                }
            }

            Ok(QueryResult {
                columns: vec![
                    "id".to_string(),
                    "type".to_string(),
                    "name".to_string(),
                    "file_path".to_string(),
                    "complexity".to_string(),
                ],
                rows,
            })
        }

        GraphOpType::Path { to, via } => {
            let graph = state.graph.read().await;
            let path = find_shortest_path(
                &op.target,
                &to,
                graph.get_nodes(),
                graph.get_edges(),
                via.as_deref(),
            );

            match path {
                Some(p) => Ok(QueryResult {
                    columns: vec!["path".to_string()],
                    rows: vec![vec![serde_json::Value::Array(
                        p.into_iter().map(serde_json::Value::String).collect()
                    )]],
                }),
                None => Ok(QueryResult {
                    columns: vec!["path".to_string()],
                    rows: vec![],
                }),
            }
        }
    }
}

async fn execute_analysis(op: AnalysisOperation, state: &AppState) -> Result<QueryResult> {
    let mubase = state.mubase.read().await;

    match op.analysis_type {
        parser::AnalysisType::Complexity => {
            // Get nodes ordered by complexity
            let sql = if let Some(target) = &op.target {
                format!(
                    "SELECT id, name, complexity FROM nodes WHERE file_path LIKE '%{}%' ORDER BY complexity DESC LIMIT 50",
                    target.replace('\'', "''")
                )
            } else {
                "SELECT id, name, complexity FROM nodes WHERE complexity > 0 ORDER BY complexity DESC LIMIT 50".to_string()
            };
            mubase.query(&sql)
        }

        parser::AnalysisType::Hotspots => {
            // Hotspots = high complexity + many connections
            let sql = "SELECT n.id, n.name, n.complexity, COUNT(e.id) as connections
                       FROM nodes n
                       LEFT JOIN edges e ON n.id = e.source_id OR n.id = e.target_id
                       WHERE n.complexity > 0
                       GROUP BY n.id, n.name, n.complexity
                       ORDER BY (n.complexity * COUNT(e.id)) DESC
                       LIMIT 50";
            mubase.query(sql)
        }

        parser::AnalysisType::Circular => {
            // Use cycle detection
            let graph = state.graph.read().await;
            let cycles = find_cycles(graph.get_nodes(), graph.get_edges(), None);

            Ok(QueryResult {
                columns: vec!["cycle".to_string()],
                rows: cycles
                    .into_iter()
                    .map(|c| vec![serde_json::Value::Array(
                        c.into_iter().map(serde_json::Value::String).collect()
                    )])
                    .collect(),
            })
        }

        parser::AnalysisType::Unused => {
            // Find nodes with no incoming edges
            let sql = "SELECT n.id, n.name, n.type FROM nodes n
                       WHERE n.id NOT IN (SELECT DISTINCT target_id FROM edges)
                       AND n.type != 'external'
                       ORDER BY n.name
                       LIMIT 100";
            mubase.query(sql)
        }

        parser::AnalysisType::Coupling => {
            // Find highly coupled modules
            let sql = "SELECT n.id, n.name,
                       (SELECT COUNT(*) FROM edges WHERE source_id = n.id) as outgoing,
                       (SELECT COUNT(*) FROM edges WHERE target_id = n.id) as incoming
                       FROM nodes n
                       WHERE n.type = 'module'
                       ORDER BY (outgoing + incoming) DESC
                       LIMIT 50";
            mubase.query(sql)
        }

        parser::AnalysisType::Cohesion | parser::AnalysisType::Impact => {
            // Placeholder for more complex analysis
            Ok(QueryResult {
                columns: vec!["message".to_string()],
                rows: vec![vec![serde_json::Value::String(
                    "Analysis not yet implemented".to_string()
                )]],
            })
        }
    }
}

async fn execute_schema(op: SchemaOperation, state: &AppState) -> Result<QueryResult> {
    match op {
        SchemaOperation::ListTables => {
            Ok(QueryResult {
                columns: vec!["table_name".to_string(), "description".to_string()],
                rows: vec![
                    vec![
                        serde_json::Value::String("nodes".to_string()),
                        serde_json::Value::String("All code entities (modules, classes, functions)".to_string()),
                    ],
                    vec![
                        serde_json::Value::String("edges".to_string()),
                        serde_json::Value::String("Relationships between nodes".to_string()),
                    ],
                    vec![
                        serde_json::Value::String("metadata".to_string()),
                        serde_json::Value::String("Schema version and build info".to_string()),
                    ],
                ],
            })
        }

        SchemaOperation::ListColumns(node_type) => {
            Ok(QueryResult {
                columns: vec!["column_name".to_string(), "type".to_string(), "description".to_string()],
                rows: vec![
                    vec![
                        serde_json::Value::String("id".to_string()),
                        serde_json::Value::String("VARCHAR".to_string()),
                        serde_json::Value::String("Unique identifier".to_string()),
                    ],
                    vec![
                        serde_json::Value::String("type".to_string()),
                        serde_json::Value::String("VARCHAR".to_string()),
                        serde_json::Value::String("Node type (module, class, function)".to_string()),
                    ],
                    vec![
                        serde_json::Value::String("name".to_string()),
                        serde_json::Value::String("VARCHAR".to_string()),
                        serde_json::Value::String("Short name".to_string()),
                    ],
                    vec![
                        serde_json::Value::String("file_path".to_string()),
                        serde_json::Value::String("VARCHAR".to_string()),
                        serde_json::Value::String("File path".to_string()),
                    ],
                    vec![
                        serde_json::Value::String("complexity".to_string()),
                        serde_json::Value::String("INTEGER".to_string()),
                        serde_json::Value::String("Cyclomatic complexity".to_string()),
                    ],
                ],
            })
        }

        SchemaOperation::DescribeNodeType(node_type) => {
            // Get sample of this node type
            let mubase = state.mubase.read().await;
            mubase.query(&format!(
                "SELECT id, name, file_path, complexity FROM nodes WHERE type = '{}' LIMIT 10",
                node_type.to_sql_type()
            ))
        }
    }
}

// =============================================================================
// Graph Algorithms
// =============================================================================

#[derive(Clone, Copy)]
enum Direction {
    Outgoing,
    Incoming,
}

fn find_cycles(
    nodes: &[String],
    edges: &[(String, String, String)],
    edge_types: Option<&[String]>,
) -> Vec<Vec<String>> {
    // Build adjacency list
    let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();
    for node in nodes {
        adj.insert(node.as_str(), Vec::new());
    }

    for (src, dst, etype) in edges {
        if let Some(types) = edge_types {
            if !types.iter().any(|t| t == etype) {
                continue;
            }
        }
        if let Some(neighbors) = adj.get_mut(src.as_str()) {
            neighbors.push(dst.as_str());
        }
    }

    // Kosaraju's algorithm for SCCs
    let mut visited: HashSet<&str> = HashSet::new();
    let mut stack: Vec<&str> = Vec::new();

    // First DFS to fill stack
    fn dfs1<'a>(
        node: &'a str,
        adj: &HashMap<&'a str, Vec<&'a str>>,
        visited: &mut HashSet<&'a str>,
        stack: &mut Vec<&'a str>,
    ) {
        if visited.contains(node) {
            return;
        }
        visited.insert(node);
        if let Some(neighbors) = adj.get(node) {
            for &neighbor in neighbors {
                dfs1(neighbor, adj, visited, stack);
            }
        }
        stack.push(node);
    }

    for node in nodes {
        dfs1(node.as_str(), &adj, &mut visited, &mut stack);
    }

    // Build reverse graph
    let mut rev_adj: HashMap<&str, Vec<&str>> = HashMap::new();
    for node in nodes {
        rev_adj.insert(node.as_str(), Vec::new());
    }
    for (src, dst, etype) in edges {
        if let Some(types) = edge_types {
            if !types.iter().any(|t| t == etype) {
                continue;
            }
        }
        if let Some(neighbors) = rev_adj.get_mut(dst.as_str()) {
            neighbors.push(src.as_str());
        }
    }

    // Second DFS on reverse graph
    visited.clear();
    let mut sccs: Vec<Vec<String>> = Vec::new();

    fn dfs2<'a>(
        node: &'a str,
        adj: &HashMap<&'a str, Vec<&'a str>>,
        visited: &mut HashSet<&'a str>,
        component: &mut Vec<String>,
    ) {
        if visited.contains(node) {
            return;
        }
        visited.insert(node);
        component.push(node.to_string());
        if let Some(neighbors) = adj.get(node) {
            for &neighbor in neighbors {
                dfs2(neighbor, adj, visited, component);
            }
        }
    }

    while let Some(node) = stack.pop() {
        if !visited.contains(node) {
            let mut component = Vec::new();
            dfs2(node, &rev_adj, &mut visited, &mut component);
            if component.len() > 1 {
                sccs.push(component);
            }
        }
    }

    sccs
}

fn traverse_bfs(
    start: &str,
    nodes: &[String],
    edges: &[(String, String, String)],
    direction: Direction,
    edge_types: Option<&[String]>,
) -> Vec<String> {
    let node_set: HashSet<&str> = nodes.iter().map(|s| s.as_str()).collect();
    if !node_set.contains(start) {
        return vec![];
    }

    // Build adjacency based on direction
    let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();
    for node in nodes {
        adj.insert(node.as_str(), Vec::new());
    }

    for (src, dst, etype) in edges {
        if let Some(types) = edge_types {
            if !types.iter().any(|t| t == etype) {
                continue;
            }
        }

        match direction {
            Direction::Outgoing => {
                if let Some(neighbors) = adj.get_mut(src.as_str()) {
                    neighbors.push(dst.as_str());
                }
            }
            Direction::Incoming => {
                if let Some(neighbors) = adj.get_mut(dst.as_str()) {
                    neighbors.push(src.as_str());
                }
            }
        }
    }

    // BFS
    let mut visited: HashSet<&str> = HashSet::new();
    let mut result = Vec::new();
    let mut queue = VecDeque::new();

    visited.insert(start);
    queue.push_back(start);

    while let Some(node) = queue.pop_front() {
        if let Some(neighbors) = adj.get(node) {
            for &neighbor in neighbors {
                if !visited.contains(neighbor) {
                    visited.insert(neighbor);
                    result.push(neighbor.to_string());
                    queue.push_back(neighbor);
                }
            }
        }
    }

    result
}

fn get_neighbors(
    start: &str,
    edges: &[(String, String, String)],
    direction: Direction,
    depth: usize,
    edge_types: Option<&[String]>,
) -> Vec<String> {
    let mut current: HashSet<String> = HashSet::new();
    current.insert(start.to_string());

    let mut all_neighbors: HashSet<String> = HashSet::new();

    for _ in 0..depth {
        let mut next: HashSet<String> = HashSet::new();

        for (src, dst, etype) in edges {
            if let Some(types) = edge_types {
                if !types.iter().any(|t| t == etype) {
                    continue;
                }
            }

            match direction {
                Direction::Outgoing => {
                    if current.contains(src) && !all_neighbors.contains(dst) && dst != start {
                        next.insert(dst.clone());
                    }
                }
                Direction::Incoming => {
                    if current.contains(dst) && !all_neighbors.contains(src) && src != start {
                        next.insert(src.clone());
                    }
                }
            }
        }

        all_neighbors.extend(next.clone());
        current = next;
    }

    all_neighbors.into_iter().collect()
}

fn find_shortest_path(
    from: &str,
    to: &str,
    nodes: &[String],
    edges: &[(String, String, String)],
    via_edge: Option<&str>,
) -> Option<Vec<String>> {
    let node_set: HashSet<&str> = nodes.iter().map(|s| s.as_str()).collect();
    if !node_set.contains(from) || !node_set.contains(to) {
        return None;
    }

    if from == to {
        return Some(vec![from.to_string()]);
    }

    // Build adjacency
    let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();
    for node in nodes {
        adj.insert(node.as_str(), Vec::new());
    }

    for (src, dst, etype) in edges {
        if let Some(via) = via_edge {
            if etype != via {
                continue;
            }
        }
        if let Some(neighbors) = adj.get_mut(src.as_str()) {
            neighbors.push(dst.as_str());
        }
    }

    // BFS with parent tracking
    let mut visited: HashSet<&str> = HashSet::new();
    let mut parent: HashMap<&str, &str> = HashMap::new();
    let mut queue = VecDeque::new();

    visited.insert(from);
    queue.push_back(from);

    while let Some(node) = queue.pop_front() {
        if let Some(neighbors) = adj.get(node) {
            for &neighbor in neighbors {
                if !visited.contains(neighbor) {
                    visited.insert(neighbor);
                    parent.insert(neighbor, node);

                    if neighbor == to {
                        // Reconstruct path
                        let mut path = vec![to.to_string()];
                        let mut curr = to;
                        while let Some(&p) = parent.get(curr) {
                            path.push(p.to_string());
                            curr = p;
                        }
                        path.reverse();
                        return Some(path);
                    }

                    queue.push_back(neighbor);
                }
            }
        }
    }

    None
}
