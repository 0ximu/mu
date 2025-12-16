//! History command - Show change history for a node
//!
//! Uses git log to find commits that touched a node's file and shows
//! the history of changes with hash, date, author, and change type.

use crate::output::{Output, OutputFormat, TableDisplay};
use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::{params, Connection};
use serde::Serialize;
use std::path::PathBuf;
use std::process::Command;

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

/// A single commit in the history
#[derive(Debug, Clone, Serialize)]
pub struct HistoryCommit {
    /// Short commit hash
    pub hash: String,
    /// Full commit hash
    pub full_hash: String,
    /// Commit date (YYYY-MM-DD format)
    pub date: String,
    /// Author name
    pub author: String,
    /// Commit subject/message
    pub message: String,
    /// Type of change detected
    pub change_type: String,
    /// Additional details about the change
    pub details: Option<String>,
}

/// Node history result
#[derive(Debug, Serialize)]
pub struct NodeHistory {
    /// Node ID
    pub node_id: String,
    /// Node name
    pub node_name: String,
    /// File path
    pub file_path: String,
    /// Node type
    pub node_type: String,
    /// History commits
    pub commits: Vec<HistoryCommit>,
    /// Total commits found
    pub total_commits: usize,
}

impl TableDisplay for NodeHistory {
    fn to_table(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!(
            "{} {} ({})\n",
            "HISTORY:".cyan().bold(),
            self.node_name.yellow(),
            self.file_path.dimmed()
        ));
        output.push_str(&format!("{}\n\n", "-".repeat(70)));

        if self.commits.is_empty() {
            output.push_str(&"  No git history found.\n".dimmed().to_string());
            return output;
        }

        for commit in &self.commits {
            // Commit header
            let hash_colored = commit.hash.cyan();
            let date_colored = format!("({})", commit.date).dimmed();
            let author_colored = commit.author.green();

            output.push_str(&format!(
                "{} {} {}\n",
                hash_colored, date_colored, author_colored
            ));

            // Change indicator
            let change_icon = match commit.change_type.as_str() {
                "added" => "+".green(),
                "modified" => "~".yellow(),
                "removed" => "-".red(),
                _ => "?".normal(),
            };

            let message_preview = if commit.message.len() > 60 {
                format!("{}...", &commit.message[..57])
            } else {
                commit.message.clone()
            };

            output.push_str(&format!(
                "  {} {}: {}\n",
                change_icon,
                commit.change_type.bold(),
                message_preview
            ));

            if let Some(ref details) = commit.details {
                output.push_str(&format!("    {}\n", details.dimmed()));
            }

            output.push('\n');
        }

        if self.total_commits > self.commits.len() {
            output.push_str(&format!(
                "{}\n",
                format!(
                    "... and {} more commits (use --limit to show more)",
                    self.total_commits - self.commits.len()
                )
                .dimmed()
            ));
        }

        output
    }

    fn to_mu(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!(
            ":: history {} [{}]\n",
            self.node_id, self.node_type
        ));
        output.push_str(&format!("| {}\n", self.file_path));
        output.push_str(&format!("# total: {}\n\n", self.total_commits));

        for commit in &self.commits {
            let sigil = match commit.change_type.as_str() {
                "added" => "+",
                "modified" => "~",
                "removed" => "-",
                _ => "?",
            };
            output.push_str(&format!(
                "{} {} ({}) {} - {}\n",
                sigil, commit.hash, commit.date, commit.author, commit.message
            ));
            if let Some(ref details) = commit.details {
                output.push_str(&format!("  | {}\n", details));
            }
        }

        output
    }
}

/// Node information from MUbase
struct NodeInfo {
    id: String,
    name: String,
    node_type: String,
    file_path: String,
}

/// Resolve a node identifier to full node info
fn resolve_node(conn: &Connection, node_id: &str) -> Result<NodeInfo> {
    // Try exact match first
    let mut stmt =
        conn.prepare("SELECT id, name, type, file_path FROM nodes WHERE id = ? OR name = ?")?;
    let mut rows = stmt.query(params![node_id, node_id])?;

    if let Some(row) = rows.next()? {
        let file_path: Option<String> = row.get(3)?;
        return Ok(NodeInfo {
            id: row.get(0)?,
            name: row.get(1)?,
            node_type: row.get(2)?,
            file_path: file_path.ok_or_else(|| anyhow::anyhow!("Node has no file path"))?,
        });
    }

    // Try partial match
    let pattern = format!("%{}%", node_id);
    let mut stmt = conn.prepare(
        "SELECT id, name, type, file_path FROM nodes WHERE id LIKE ? OR name LIKE ? LIMIT 10",
    )?;
    let mut rows = stmt.query(params![pattern, pattern])?;

    let mut matches = Vec::new();
    while let Some(row) = rows.next()? {
        let file_path: Option<String> = row.get(3)?;
        if let Some(fp) = file_path {
            matches.push(NodeInfo {
                id: row.get(0)?,
                name: row.get(1)?,
                node_type: row.get(2)?,
                file_path: fp,
            });
        }
    }

    match matches.len() {
        0 => Err(anyhow::anyhow!("Node not found: {}", node_id)),
        1 => Ok(matches.remove(0)),
        _ => {
            // Prefer exact name match
            if let Some(exact) = matches.iter().find(|m| m.name == node_id) {
                return Ok(NodeInfo {
                    id: exact.id.clone(),
                    name: exact.name.clone(),
                    node_type: exact.node_type.clone(),
                    file_path: exact.file_path.clone(),
                });
            }

            // Sort matches by type priority (class > module > function) then by name
            matches.sort_by(|a, b| {
                let type_priority = |t: &str| match t {
                    "class" => 0,
                    "module" => 1,
                    "function" => 2,
                    _ => 3,
                };
                type_priority(&a.node_type)
                    .cmp(&type_priority(&b.node_type))
                    .then_with(|| a.name.cmp(&b.name))
            });

            eprintln!(
                "{}: Multiple matches found. Using first match. Candidates:",
                "Warning".yellow()
            );
            for m in matches.iter().take(5) {
                eprintln!("  - {} ({})", m.name, m.id);
            }
            Ok(matches.remove(0))
        }
    }
}

/// Get git history for a file
fn get_git_history(file_path: &str, limit: usize) -> Result<(Vec<HistoryCommit>, usize)> {
    // First get the total count
    let count_output = Command::new("git")
        .args(["rev-list", "--count", "HEAD", "--", file_path])
        .output()?;

    let total_commits = if count_output.status.success() {
        String::from_utf8_lossy(&count_output.stdout)
            .trim()
            .parse::<usize>()
            .unwrap_or(0)
    } else {
        0
    };

    // Get the log entries
    // Format: hash|full_hash|date|author|subject
    let output = Command::new("git")
        .args([
            "log",
            &format!("-{}", limit),
            "--format=%h|%H|%ad|%an|%s",
            "--date=short",
            "--follow",
            "--",
            file_path,
        ])
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(anyhow::anyhow!("git log failed: {}", stderr));
    }

    let commits: Vec<HistoryCommit> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|line| {
            let parts: Vec<&str> = line.splitn(5, '|').collect();
            if parts.len() >= 5 {
                Some(HistoryCommit {
                    hash: parts[0].to_string(),
                    full_hash: parts[1].to_string(),
                    date: parts[2].to_string(),
                    author: parts[3].to_string(),
                    message: parts[4].to_string(),
                    change_type: "modified".to_string(), // Will be refined below
                    details: None,
                })
            } else {
                None
            }
        })
        .collect();

    // Refine change types by checking if file was added or deleted
    let refined_commits: Vec<HistoryCommit> = commits
        .into_iter()
        .map(|mut commit| {
            // Check the diff stat for this commit
            let stat_output = Command::new("git")
                .args([
                    "diff-tree",
                    "--no-commit-id",
                    "--name-status",
                    "-r",
                    &commit.full_hash,
                    "--",
                    file_path,
                ])
                .output();

            if let Ok(stat) = stat_output {
                let stat_str = String::from_utf8_lossy(&stat.stdout);
                let first_char = stat_str.chars().next();

                commit.change_type = match first_char {
                    Some('A') => "added".to_string(),
                    Some('D') => "removed".to_string(),
                    Some('M') => "modified".to_string(),
                    Some('R') => "renamed".to_string(),
                    _ => "modified".to_string(),
                };
            }

            commit
        })
        .collect();

    Ok((refined_commits, total_commits))
}

/// Run the history command
pub async fn run(node: &str, limit: usize, format: OutputFormat) -> Result<()> {
    // Find the MUbase database
    let db_path = find_mubase(".")?;

    // Open the database in read-only mode
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    // Resolve the node
    let node_info = resolve_node(&conn, node)?;

    // Get git history
    let (commits, total_commits) = get_git_history(&node_info.file_path, limit)?;

    let history = NodeHistory {
        node_id: node_info.id,
        node_name: node_info.name,
        file_path: node_info.file_path,
        node_type: node_info.node_type,
        commits,
        total_commits,
    };

    Output::new(history, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_history_commit_table_display() {
        let history = NodeHistory {
            node_id: "fn:test".to_string(),
            node_name: "test_func".to_string(),
            file_path: "src/test.py".to_string(),
            node_type: "function".to_string(),
            commits: vec![
                HistoryCommit {
                    hash: "abc1234".to_string(),
                    full_hash: "abc1234567890".to_string(),
                    date: "2024-01-15".to_string(),
                    author: "John Doe".to_string(),
                    message: "Add test function".to_string(),
                    change_type: "added".to_string(),
                    details: None,
                },
                HistoryCommit {
                    hash: "def5678".to_string(),
                    full_hash: "def567890123".to_string(),
                    date: "2024-01-10".to_string(),
                    author: "Jane Smith".to_string(),
                    message: "Initial commit".to_string(),
                    change_type: "modified".to_string(),
                    details: Some("Refactored implementation".to_string()),
                },
            ],
            total_commits: 2,
        };

        let output = history.to_table();

        assert!(output.contains("HISTORY:"));
        assert!(output.contains("test_func"));
        assert!(output.contains("src/test.py"));
        assert!(output.contains("abc1234"));
        assert!(output.contains("John Doe"));
        assert!(output.contains("Add test function"));
    }

    #[test]
    fn test_history_mu_format() {
        let history = NodeHistory {
            node_id: "fn:test".to_string(),
            node_name: "test".to_string(),
            file_path: "src/test.py".to_string(),
            node_type: "function".to_string(),
            commits: vec![HistoryCommit {
                hash: "abc1234".to_string(),
                full_hash: "abc1234567890".to_string(),
                date: "2024-01-15".to_string(),
                author: "John Doe".to_string(),
                message: "Add feature".to_string(),
                change_type: "added".to_string(),
                details: None,
            }],
            total_commits: 1,
        };

        let output = history.to_mu();

        assert!(output.contains(":: history fn:test [function]"));
        assert!(output.contains("| src/test.py"));
        assert!(output.contains("+ abc1234"));
    }
}
