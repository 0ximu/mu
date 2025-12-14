//! MCP (Model Context Protocol) server for AI assistant integration.
//!
//! Implements the MCP protocol over stdio for use with Claude Code and other AI tools.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::io::{BufRead, Write};
use tracing::{debug, info};

use super::state::AppState;
use crate::build::BuildPipeline;
use crate::context::ContextExtractor;
use crate::muql;

/// Run the MCP server in stdio mode.
pub async fn run_stdio(state: AppState) -> Result<()> {
    info!("Starting MCP server on stdio");

    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();

    // Send server info
    let server_info = McpMessage::ServerInfo {
        name: "mu-daemon".to_string(),
        version: env!("CARGO_PKG_VERSION").to_string(),
        capabilities: vec![
            "query".to_string(),
            "context".to_string(),
            "deps".to_string(),
            "impact".to_string(),
            "cycles".to_string(),
            "build".to_string(),
            "status".to_string(),
        ],
    };
    write_message(&mut stdout, &server_info)?;

    // Process incoming messages
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }

        debug!("MCP received: {}", line);

        match serde_json::from_str::<McpRequest>(&line) {
            Ok(request) => {
                let response = handle_request(request, &state).await;
                write_message(&mut stdout, &response)?;
            }
            Err(e) => {
                let error = McpMessage::Error {
                    message: format!("Invalid request: {}", e),
                };
                write_message(&mut stdout, &error)?;
            }
        }
    }

    Ok(())
}

fn write_message(writer: &mut impl Write, msg: &impl Serialize) -> Result<()> {
    let json = serde_json::to_string(msg)?;
    writeln!(writer, "{}", json)?;
    writer.flush()?;
    Ok(())
}

/// MCP request types.
#[derive(Debug, Deserialize)]
#[serde(tag = "method", content = "params")]
enum McpRequest {
    #[serde(rename = "mu/status")]
    Status {
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/query")]
    Query {
        muql: String,
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/context")]
    Context {
        question: String,
        #[serde(default = "default_max_tokens")]
        max_tokens: usize,
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/deps")]
    Deps {
        node: String,
        #[serde(default = "default_depth")]
        depth: usize,
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/impact")]
    Impact {
        node: String,
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/ancestors")]
    Ancestors {
        node: String,
        #[serde(default = "default_depth")]
        depth: usize,
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/cycles")]
    Cycles {
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/build")]
    Build {
        #[serde(default)]
        path: Option<String>,
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/node")]
    Node {
        id: String,
        #[serde(default)]
        cwd: Option<String>,
    },

    #[serde(rename = "mu/search")]
    Search {
        pattern: String,
        #[serde(default)]
        cwd: Option<String>,
    },
}

fn default_max_tokens() -> usize {
    8000
}

fn default_depth() -> usize {
    2
}

/// MCP response types.
#[derive(Debug, Serialize)]
#[serde(untagged)]
enum McpMessage {
    ServerInfo {
        name: String,
        version: String,
        capabilities: Vec<String>,
    },
    Success {
        success: bool,
        data: serde_json::Value,
    },
    Error {
        message: String,
    },
}

/// Handle an MCP request.
async fn handle_request(request: McpRequest, state: &AppState) -> McpMessage {
    match request {
        McpRequest::Status { cwd } => {
            // Get project-specific graph if cwd provided
            let (graph, _) = match state.projects.get_project(cwd.as_deref()).await {
                Ok((_, graph, path)) => (graph, path),
                Err(_) => (
                    state.graph.clone(),
                    state.projects.default_path().to_path_buf(),
                ),
            };
            let graph = graph.read().await;
            McpMessage::Success {
                success: true,
                data: serde_json::json!({
                    "node_count": graph.node_count(),
                    "edge_count": graph.edge_count(),
                    "root": state.root.display().to_string(),
                }),
            }
        }

        McpRequest::Query { muql, cwd: _ } => {
            // Note: MUQL execution uses default project for now
            // Full cwd routing would require passing cwd through muql::execute
            match muql::execute(&muql, state).await {
                Ok(result) => McpMessage::Success {
                    success: true,
                    data: serde_json::json!({
                        "columns": result.columns,
                        "rows": result.rows,
                        "count": result.rows.len(),
                    }),
                },
                Err(e) => McpMessage::Error {
                    message: e.to_string(),
                },
            }
        }

        McpRequest::Context {
            question,
            max_tokens,
            cwd: _,
        } => {
            // Note: Context extraction uses default project for now
            let extractor = ContextExtractor::new(state);
            match extractor.extract(&question, max_tokens).await {
                Ok(ctx) => McpMessage::Success {
                    success: true,
                    data: serde_json::json!({
                        "mu_output": ctx.mu_output,
                        "nodes": ctx.nodes,
                        "tokens": ctx.tokens,
                    }),
                },
                Err(e) => McpMessage::Error {
                    message: e.to_string(),
                },
            }
        }

        McpRequest::Deps {
            node,
            depth,
            cwd: _,
        } => {
            let query = format!(
                "SHOW dependencies OF '{}' DEPTH {}",
                node.replace('\'', "''"),
                depth
            );
            match muql::execute(&query, state).await {
                Ok(result) => {
                    let nodes: Vec<String> = result
                        .rows
                        .iter()
                        .filter_map(|row| row.first().and_then(|v| v.as_str().map(String::from)))
                        .collect();
                    McpMessage::Success {
                        success: true,
                        data: serde_json::json!(nodes),
                    }
                }
                Err(e) => McpMessage::Error {
                    message: e.to_string(),
                },
            }
        }

        McpRequest::Impact { node, cwd: _ } => {
            let query = format!("SHOW impact OF '{}'", node.replace('\'', "''"));
            match muql::execute(&query, state).await {
                Ok(result) => {
                    let nodes: Vec<String> = result
                        .rows
                        .iter()
                        .filter_map(|row| row.first().and_then(|v| v.as_str().map(String::from)))
                        .collect();
                    McpMessage::Success {
                        success: true,
                        data: serde_json::json!(nodes),
                    }
                }
                Err(e) => McpMessage::Error {
                    message: e.to_string(),
                },
            }
        }

        McpRequest::Ancestors {
            node,
            depth,
            cwd: _,
        } => {
            let query = format!(
                "SHOW ancestors OF '{}' DEPTH {}",
                node.replace('\'', "''"),
                depth
            );
            match muql::execute(&query, state).await {
                Ok(result) => {
                    let nodes: Vec<String> = result
                        .rows
                        .iter()
                        .filter_map(|row| row.first().and_then(|v| v.as_str().map(String::from)))
                        .collect();
                    McpMessage::Success {
                        success: true,
                        data: serde_json::json!(nodes),
                    }
                }
                Err(e) => McpMessage::Error {
                    message: e.to_string(),
                },
            }
        }

        McpRequest::Cycles { cwd: _ } => match muql::execute("FIND CYCLES", state).await {
            Ok(result) => McpMessage::Success {
                success: true,
                data: serde_json::json!(result.rows),
            },
            Err(e) => McpMessage::Error {
                message: e.to_string(),
            },
        },

        McpRequest::Build { path, cwd } => {
            // Use cwd if path not provided
            let root = path
                .map(std::path::PathBuf::from)
                .or_else(|| cwd.map(std::path::PathBuf::from))
                .unwrap_or_else(|| state.root.clone());

            let pipeline = BuildPipeline::new(state.clone());
            match pipeline.build(&root).await {
                Ok(result) => McpMessage::Success {
                    success: true,
                    data: serde_json::json!({
                        "node_count": result.node_count,
                        "edge_count": result.edge_count,
                        "duration_ms": result.duration.as_millis(),
                    }),
                },
                Err(e) => McpMessage::Error {
                    message: e.to_string(),
                },
            }
        }

        McpRequest::Node { id, cwd } => {
            // Get project-specific mubase
            let mubase = match state.projects.get_mubase(cwd.as_deref()).await {
                Ok(m) => m,
                Err(e) => {
                    return McpMessage::Error {
                        message: e.to_string(),
                    }
                }
            };
            let mubase = mubase.read().await;
            match mubase.get_node(&id) {
                Ok(Some(node)) => McpMessage::Success {
                    success: true,
                    data: serde_json::json!({
                        "id": node.id,
                        "name": node.name,
                        "type": node.node_type.as_str(),
                        "file_path": node.file_path,
                        "line_start": node.line_start,
                        "line_end": node.line_end,
                        "complexity": node.complexity,
                    }),
                },
                Ok(None) => McpMessage::Error {
                    message: format!("Node not found: {}", id),
                },
                Err(e) => McpMessage::Error {
                    message: e.to_string(),
                },
            }
        }

        McpRequest::Search { pattern, cwd: _ } => {
            // Use parameterized query to prevent SQL injection
            let mubase = state.mubase.read().await;
            let sql = "SELECT id, type, name, qualified_name, file_path, line_start, line_end, complexity FROM nodes WHERE name LIKE ? LIMIT 50";
            match mubase.query_with_params(sql, &[&pattern]) {
                Ok(result) => McpMessage::Success {
                    success: true,
                    data: serde_json::json!({
                        "columns": result.columns,
                        "rows": result.rows,
                        "count": result.rows.len(),
                    }),
                },
                Err(e) => McpMessage::Error {
                    message: e.to_string(),
                },
            }
        }
    }
}
