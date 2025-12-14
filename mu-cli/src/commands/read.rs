//! Read command - Read and display node source code with syntax highlighting
//!
//! This command can read source code either by file path or by node ID.
//! When given a node ID, it resolves to the file and line range from the MUbase.
//! Provides syntax highlighting and optional line numbers.

use crate::output::{Output, OutputFormat, TableDisplay};
use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::{params, Connection};
use serde::Serialize;
use std::path::PathBuf;
use syntect::easy::HighlightLines;
use syntect::highlighting::{Style, ThemeSet};
use syntect::parsing::SyntaxSet;
use syntect::util::{as_24_bit_terminal_escaped, LinesWithEndings};

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

/// Get the root directory of the MUbase (where .mu/ exists)
fn get_mubase_root(db_path: &PathBuf) -> Result<PathBuf> {
    // The db_path is either .mu/mubase or .mubase
    let parent = db_path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("Invalid database path"))?;

    if parent.file_name().and_then(|s| s.to_str()) == Some(".mu") {
        // .mu/mubase -> go up one more level
        Ok(parent
            .parent()
            .ok_or_else(|| anyhow::anyhow!("Invalid .mu directory structure"))?
            .to_path_buf())
    } else {
        // .mubase -> parent is the root
        Ok(parent.to_path_buf())
    }
}

/// Node information from the database
#[derive(Debug)]
struct NodeInfo {
    id: String,
    name: String,
    node_type: String,
    file_path: String,
    line_start: Option<u32>,
    line_end: Option<u32>,
}

/// Try to resolve a partial node ID to full node info
fn resolve_node(conn: &Connection, partial: &str) -> Result<NodeInfo> {
    // First try exact match
    let mut stmt = conn.prepare(
        "SELECT id, name, type, file_path, line_start, line_end
         FROM nodes
         WHERE id = ?",
    )?;
    let mut rows = stmt.query(params![partial])?;

    if let Some(row) = rows.next()? {
        return Ok(NodeInfo {
            id: row.get(0)?,
            name: row.get(1)?,
            node_type: row.get(2)?,
            file_path: row.get(3)?,
            line_start: row.get(4)?,
            line_end: row.get(5)?,
        });
    }

    // Try prefix match
    let pattern = format!("%{}%", partial);
    let mut stmt = conn.prepare(
        "SELECT id, name, type, file_path, line_start, line_end
         FROM nodes
         WHERE id LIKE ?
         LIMIT 10",
    )?;
    let mut rows = stmt.query(params![pattern])?;

    let mut matches = Vec::new();
    while let Some(row) = rows.next()? {
        matches.push(NodeInfo {
            id: row.get(0)?,
            name: row.get(1)?,
            node_type: row.get(2)?,
            file_path: row.get(3)?,
            line_start: row.get(4)?,
            line_end: row.get(5)?,
        });
    }

    match matches.len() {
        0 => Err(anyhow::anyhow!("Node not found: {}", partial)),
        1 => Ok(matches.into_iter().next().unwrap()),
        _ => {
            // Try to find best match
            for m in &matches {
                if m.id.ends_with(partial) || m.id.contains(&format!(":{}", partial)) {
                    return Ok(m.clone());
                }
            }
            // Multiple matches - warn and use first
            eprintln!(
                "{}: Multiple matches found. Using first match. Candidates:",
                "Warning".yellow()
            );
            for m in matches.iter().take(5) {
                eprintln!("  - {} ({})", m.id, m.node_type);
            }
            Ok(matches.into_iter().next().unwrap())
        }
    }
}

impl Clone for NodeInfo {
    fn clone(&self) -> Self {
        Self {
            id: self.id.clone(),
            name: self.name.clone(),
            node_type: self.node_type.clone(),
            file_path: self.file_path.clone(),
            line_start: self.line_start,
            line_end: self.line_end,
        }
    }
}

/// Source code read result
#[derive(Debug, Serialize)]
pub struct SourceCode {
    /// Source identifier (file path or node ID)
    pub source: String,
    /// File path
    pub file_path: String,
    /// Start line (1-indexed, inclusive)
    pub line_start: u32,
    /// End line (1-indexed, inclusive)
    pub line_end: u32,
    /// Total lines read
    pub total_lines: usize,
    /// The source code content
    pub content: String,
    /// Node information if resolved from node ID
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_type: Option<String>,
}

impl TableDisplay for SourceCode {
    fn to_table(&self) -> String {
        let mut output = String::new();

        // Header
        if let (Some(name), Some(node_type)) = (&self.node_name, &self.node_type) {
            let type_badge = match node_type.as_str() {
                "module" => "[mod]".blue(),
                "class" => "[cls]".yellow(),
                "function" => "[fn]".green(),
                _ => format!("[{}]", node_type).normal(),
            };
            output.push_str(&format!(
                "{} {} {}\n",
                type_badge,
                name.cyan().bold(),
                format!("({}:{})", self.file_path, self.line_start).dimmed()
            ));
        } else {
            output.push_str(&format!("{}\n", self.file_path.cyan().bold()));
        }

        output.push_str(&format!("{}\n", "-".repeat(80)));

        // Content (already syntax highlighted or plain)
        output.push_str(&self.content);

        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();

        if let (Some(name), Some(node_type)) = (&self.node_name, &self.node_type) {
            output.push_str(&format!(
                ":: read {} [{}] {}:{}-{}\n",
                self.source, node_type, self.file_path, self.line_start, self.line_end
            ));
            output.push_str(&format!("# {}\n", name));
        } else {
            output.push_str(&format!(
                ":: read {} {}:{}-{}\n",
                self.file_path, self.file_path, self.line_start, self.line_end
            ));
        }

        output.push_str(&self.content);
        output
    }
}

/// Read source code from file with optional line range
fn read_source_file(
    file_path: &str,
    line_start: Option<u32>,
    line_end: Option<u32>,
    show_line_numbers: bool,
    use_colors: bool,
) -> Result<String> {
    let content = std::fs::read_to_string(file_path)
        .with_context(|| format!("Failed to read file: {}", file_path))?;

    let lines: Vec<&str> = content.lines().collect();
    let total_lines = lines.len();

    // Determine line range (1-indexed)
    let start = line_start.unwrap_or(1).saturating_sub(1) as usize;
    let end = line_end
        .map(|e| (e as usize).min(total_lines))
        .unwrap_or(total_lines);

    if start >= total_lines {
        return Err(anyhow::anyhow!(
            "Start line {} exceeds file length ({})",
            start + 1,
            total_lines
        ));
    }

    // Extract the lines
    let selected_lines: Vec<&str> = lines[start..end].to_vec();
    let selected_content = selected_lines.join("\n");

    // Apply syntax highlighting if colors are enabled
    if use_colors {
        highlight_code(
            &selected_content,
            file_path,
            start as u32 + 1,
            show_line_numbers,
        )
    } else {
        // Plain text with optional line numbers
        Ok(format_with_line_numbers(
            &selected_content,
            start as u32 + 1,
            show_line_numbers,
        ))
    }
}

/// Highlight code using syntect
fn highlight_code(
    code: &str,
    file_path: &str,
    line_start: u32,
    show_line_numbers: bool,
) -> Result<String> {
    let ps = SyntaxSet::load_defaults_newlines();
    let ts = ThemeSet::load_defaults();

    // Detect syntax from file extension
    let syntax = ps
        .find_syntax_for_file(file_path)
        .ok()
        .flatten()
        .or_else(|| Some(ps.find_syntax_plain_text()))
        .ok_or_else(|| anyhow::anyhow!("Could not determine syntax"))?;

    let theme = &ts.themes["base16-ocean.dark"];
    let mut highlighter = HighlightLines::new(syntax, theme);

    let mut output = String::new();
    let mut line_num = line_start;

    for line in LinesWithEndings::from(code) {
        let ranges: Vec<(Style, &str)> = highlighter
            .highlight_line(line, &ps)
            .context("Failed to highlight line")?;

        if show_line_numbers {
            // Calculate line number width (at least 4 characters)
            let num_width = 4.max(format!("{}", line_num).len());
            output.push_str(&format!(
                "{:>width$} │ ",
                line_num.to_string().dimmed(),
                width = num_width
            ));
        }

        let escaped = as_24_bit_terminal_escaped(&ranges[..], false);
        output.push_str(&escaped);

        // Only increment if the line actually had a newline
        if line.ends_with('\n') {
            line_num += 1;
        }
    }

    Ok(output)
}

/// Format code with line numbers (no syntax highlighting)
fn format_with_line_numbers(code: &str, line_start: u32, show_line_numbers: bool) -> String {
    if !show_line_numbers {
        return code.to_string();
    }

    let mut output = String::new();
    let mut line_num = line_start;

    for line in code.lines() {
        let num_width = 4.max(format!("{}", line_num).len());
        output.push_str(&format!(
            "{:>width$} │ {}\n",
            line_num,
            line,
            width = num_width
        ));
        line_num += 1;
    }

    output
}

/// Run the read command
pub async fn run(path_or_node: &str, line_numbers: bool, format: OutputFormat) -> Result<()> {
    // Try to interpret as a file path first
    let file_path = std::path::Path::new(path_or_node);

    if file_path.exists() && file_path.is_file() {
        // Direct file read
        let content = read_source_file(
            path_or_node,
            None,
            None,
            line_numbers,
            format == OutputFormat::Table, // Only colorize for table format
        )?;

        let file_lines = std::fs::read_to_string(path_or_node)?.lines().count();

        let result = SourceCode {
            source: path_or_node.to_string(),
            file_path: path_or_node.to_string(),
            line_start: 1,
            line_end: file_lines as u32,
            total_lines: file_lines,
            content,
            node_name: None,
            node_type: None,
        };

        Output::new(result, format).render()
    } else {
        // Try to resolve as node ID from MUbase
        let db_path = find_mubase(".")?;
        let conn = Connection::open_with_flags(
            &db_path,
            duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
        )
        .with_context(|| format!("Failed to open database: {:?}", db_path))?;

        let node = resolve_node(&conn, path_or_node)?;

        // Get the root directory to construct absolute path
        let root = get_mubase_root(&db_path)?;
        let absolute_path = root.join(&node.file_path);

        if !absolute_path.exists() {
            return Err(anyhow::anyhow!(
                "File not found: {} (resolved from node {})",
                absolute_path.display(),
                node.id
            ));
        }

        // Read the file with the node's line range
        let content = read_source_file(
            absolute_path.to_str().unwrap(),
            node.line_start,
            node.line_end,
            line_numbers,
            format == OutputFormat::Table,
        )?;

        let line_count = if let (Some(start), Some(end)) = (node.line_start, node.line_end) {
            (end - start + 1) as usize
        } else {
            content.lines().count()
        };

        let result = SourceCode {
            source: path_or_node.to_string(),
            file_path: node.file_path.clone(),
            line_start: node.line_start.unwrap_or(1),
            line_end: node.line_end.unwrap_or(1),
            total_lines: line_count,
            content,
            node_name: Some(node.name),
            node_type: Some(node.node_type),
        };

        Output::new(result, format).render()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_format_with_line_numbers() {
        let code = "fn main() {\n    println!(\"Hello\");\n}";
        let result = format_with_line_numbers(code, 1, true);
        assert!(result.contains("   1 │"));
        assert!(result.contains("   2 │"));
        assert!(result.contains("   3 │"));
    }

    #[test]
    fn test_format_without_line_numbers() {
        let code = "fn main() {\n    println!(\"Hello\");\n}";
        let result = format_with_line_numbers(code, 1, false);
        assert_eq!(result, code);
    }

    #[tokio::test]
    async fn test_read_file_direct() {
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, "line 1").unwrap();
        writeln!(temp_file, "line 2").unwrap();
        writeln!(temp_file, "line 3").unwrap();
        temp_file.flush().unwrap();

        let path = temp_file.path().to_str().unwrap();
        let result = read_source_file(path, None, None, false, false);

        assert!(result.is_ok());
        let content = result.unwrap();
        assert!(content.contains("line 1"));
        assert!(content.contains("line 2"));
        assert!(content.contains("line 3"));
    }

    #[tokio::test]
    async fn test_read_file_with_range() {
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, "line 1").unwrap();
        writeln!(temp_file, "line 2").unwrap();
        writeln!(temp_file, "line 3").unwrap();
        writeln!(temp_file, "line 4").unwrap();
        temp_file.flush().unwrap();

        let path = temp_file.path().to_str().unwrap();
        let result = read_source_file(path, Some(2), Some(3), false, false);

        assert!(result.is_ok());
        let content = result.unwrap();
        assert!(!content.contains("line 1"));
        assert!(content.contains("line 2"));
        assert!(content.contains("line 3"));
        assert!(!content.contains("line 4"));
    }
}
