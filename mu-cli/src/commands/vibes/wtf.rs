//! Wtf command - Git archaeology (why does this code exist?)
//!
//! Analyzes git history to understand the origin and evolution of code:
//! - Who introduced it and when
//! - The commit message and context
//! - What typically changes with this code
//! - Whether it's been stable or frequently modified

use anyhow::{Context, Result};
use colored::Colorize;
use duckdb::{params, Connection};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::output::OutputFormat;

/// Information about a commit
#[derive(Debug, Clone, serde::Serialize)]
pub struct CommitInfo {
    pub hash: String,
    pub author: String,
    pub date: String,
    pub message: String,
}

/// Result of git archaeology analysis
#[derive(Debug, serde::Serialize)]
pub struct WtfResult {
    pub target: String,
    pub file_path: Option<String>,
    pub line_range: Option<(usize, usize)>,
    pub origin_commit: Option<CommitInfo>,
    pub origin_reason: Option<String>,
    pub total_commits: usize,
    pub contributors: Vec<String>,
    pub primary_author: Option<String>,
    pub evolution_summary: Option<String>,
    pub frequently_changed_with: Vec<String>,
    pub issue_refs: Vec<String>,
    pub pr_refs: Vec<String>,
    pub analysis_time_ms: f64,
}

/// Run the wtf command - git archaeology with personality
pub async fn run(target: Option<&str>, format: OutputFormat) -> anyhow::Result<()> {
    let start = std::time::Instant::now();
    let target_str = target.unwrap_or(".");

    // Check if we're in a git repository
    if !is_git_repo()? {
        print_not_a_repo();
        return Ok(());
    }

    // Try to parse target as node ID or file path
    let (file_path, line_range) = if let Some(target) = target {
        if target.contains(':') && !target.contains('/') {
            // Looks like a node ID - try to resolve it
            match resolve_node_to_file(target) {
                Ok((path, range)) => (Some(path), range),
                Err(_) => {
                    // Not a node ID, treat as file path
                    (Some(PathBuf::from(target)), None)
                }
            }
        } else {
            // Treat as file path
            (Some(PathBuf::from(target)), None)
        }
    } else {
        // No target specified, analyze current directory
        (None, None)
    };

    // Perform git analysis
    let result = if let Some(path) = file_path.as_ref() {
        analyze_file(&path, line_range)?
    } else {
        analyze_repository()?
    };

    let elapsed = start.elapsed().as_secs_f64() * 1000.0;
    let final_result = WtfResult {
        target: target_str.to_string(),
        file_path: file_path.map(|p| p.display().to_string()),
        line_range,
        analysis_time_ms: elapsed,
        ..result
    };

    match format {
        OutputFormat::Json => {
            println!("{}", serde_json::to_string_pretty(&final_result)?);
        }
        _ => {
            print_wtf_output(&final_result);
        }
    }

    Ok(())
}

/// Check if current directory is inside a git repository
fn is_git_repo() -> Result<bool> {
    let output = Command::new("git")
        .args(["rev-parse", "--is-inside-work-tree"])
        .output()?;

    Ok(output.status.success())
}

/// Find the MUbase database in the given directory or its parents
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

/// Resolve a node ID to its file path and line range
fn resolve_node_to_file(node_id: &str) -> Result<(PathBuf, Option<(usize, usize)>)> {
    let db_path = find_mubase(".")?;
    let conn = Connection::open_with_flags(
        &db_path,
        duckdb::Config::default().access_mode(duckdb::AccessMode::ReadOnly)?,
    )
    .with_context(|| format!("Failed to open database: {:?}", db_path))?;

    // Try exact match first
    let mut stmt = conn.prepare(
        "SELECT file_path, line_start, line_end FROM nodes WHERE id = ? AND file_path IS NOT NULL",
    )?;
    let mut rows = stmt.query(params![node_id])?;

    if let Some(row) = rows.next()? {
        let file_path: String = row.get(0)?;
        let line_start: Option<i64> = row.get(1)?;
        let line_end: Option<i64> = row.get(2)?;

        let range = match (line_start, line_end) {
            (Some(start), Some(end)) => Some((start as usize, end as usize)),
            _ => None,
        };

        return Ok((PathBuf::from(file_path), range));
    }

    // Try partial match
    let pattern = format!("%{}%", node_id);
    let mut stmt = conn.prepare(
        "SELECT file_path, line_start, line_end FROM nodes WHERE id LIKE ? AND file_path IS NOT NULL LIMIT 1",
    )?;
    let mut rows = stmt.query(params![pattern])?;

    if let Some(row) = rows.next()? {
        let file_path: String = row.get(0)?;
        let line_start: Option<i64> = row.get(1)?;
        let line_end: Option<i64> = row.get(2)?;

        let range = match (line_start, line_end) {
            (Some(start), Some(end)) => Some((start as usize, end as usize)),
            _ => None,
        };

        return Ok((PathBuf::from(file_path), range));
    }

    Err(anyhow::anyhow!("Node not found: {}", node_id))
}

/// Analyze a specific file's git history
fn analyze_file(path: &Path, line_range: Option<(usize, usize)>) -> Result<WtfResult> {
    let path_str = path.display().to_string();

    // Get origin commit (first commit that added this file)
    let origin_commit = get_origin_commit(&path_str)?;

    // Get all commits touching this file
    let all_commits = get_file_commits(&path_str)?;

    // Get contributors
    let contributors = get_contributors(&all_commits);
    let primary_author = get_primary_author(&all_commits);

    // Extract issue/PR references
    let (issue_refs, pr_refs) = extract_references(&all_commits);

    // Get frequently co-changed files
    let frequently_changed_with = get_cochanged_files(&path_str, 5)?;

    // Generate evolution summary
    let evolution_summary = generate_evolution_summary(&all_commits);

    // Extract origin reason from commit message
    let origin_reason = origin_commit.as_ref().map(|c| extract_reason(&c.message));

    Ok(WtfResult {
        target: path_str.clone(),
        file_path: Some(path_str),
        line_range,
        origin_commit,
        origin_reason,
        total_commits: all_commits.len(),
        contributors,
        primary_author,
        evolution_summary,
        frequently_changed_with,
        issue_refs,
        pr_refs,
        analysis_time_ms: 0.0, // Will be set by caller
    })
}

/// Analyze repository-level git history
fn analyze_repository() -> Result<WtfResult> {
    // Get all commits in the repository
    let all_commits = get_all_commits()?;

    // Get contributors
    let contributors = get_contributors(&all_commits);
    let primary_author = get_primary_author(&all_commits);

    // Extract issue/PR references
    let (issue_refs, pr_refs) = extract_references(&all_commits);

    // Generate evolution summary
    let evolution_summary = generate_evolution_summary(&all_commits);

    Ok(WtfResult {
        target: ".".to_string(),
        file_path: None,
        line_range: None,
        origin_commit: all_commits.first().cloned(),
        origin_reason: all_commits.first().map(|c| extract_reason(&c.message)),
        total_commits: all_commits.len(),
        contributors,
        primary_author,
        evolution_summary,
        frequently_changed_with: vec![],
        issue_refs,
        pr_refs,
        analysis_time_ms: 0.0,
    })
}

/// Get the origin commit (first commit) for a file
fn get_origin_commit(file_path: &str) -> Result<Option<CommitInfo>> {
    let output = Command::new("git")
        .args([
            "log",
            "--follow",
            "--format=%H|%an|%ai|%s",
            "--diff-filter=A",
            "--",
            file_path,
        ])
        .output()?;

    if !output.status.success() {
        return Ok(None);
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let lines: Vec<&str> = stdout.trim().lines().collect();

    // Get the last commit (oldest)
    if let Some(line) = lines.last() {
        if let Some(commit) = parse_commit_line(line) {
            return Ok(Some(commit));
        }
    }

    Ok(None)
}

/// Get all commits that touched a specific file
fn get_file_commits(file_path: &str) -> Result<Vec<CommitInfo>> {
    let output = Command::new("git")
        .args(["log", "--follow", "--format=%H|%an|%ai|%s", "--", file_path])
        .output()?;

    if !output.status.success() {
        return Ok(vec![]);
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let commits: Vec<CommitInfo> = stdout
        .trim()
        .lines()
        .filter_map(parse_commit_line)
        .collect();

    Ok(commits)
}

/// Get all commits in the repository
fn get_all_commits() -> Result<Vec<CommitInfo>> {
    let output = Command::new("git")
        .args(["log", "--format=%H|%an|%ai|%s", "--reverse"])
        .output()?;

    if !output.status.success() {
        return Ok(vec![]);
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let commits: Vec<CommitInfo> = stdout
        .trim()
        .lines()
        .filter_map(parse_commit_line)
        .collect();

    Ok(commits)
}

/// Parse a git log line in format: hash|author|date|message
fn parse_commit_line(line: &str) -> Option<CommitInfo> {
    let parts: Vec<&str> = line.splitn(4, '|').collect();
    if parts.len() == 4 {
        Some(CommitInfo {
            hash: parts[0].to_string(),
            author: parts[1].to_string(),
            date: parts[2].to_string(),
            message: parts[3].to_string(),
        })
    } else {
        None
    }
}

/// Get list of unique contributors
fn get_contributors(commits: &[CommitInfo]) -> Vec<String> {
    let mut unique: HashSet<String> = commits.iter().map(|c| c.author.clone()).collect();
    let mut list: Vec<String> = unique.drain().collect();
    list.sort();
    list
}

/// Get the primary author (most commits)
fn get_primary_author(commits: &[CommitInfo]) -> Option<String> {
    let mut counts: HashMap<String, usize> = HashMap::new();

    for commit in commits {
        *counts.entry(commit.author.clone()).or_insert(0) += 1;
    }

    counts
        .into_iter()
        .max_by_key(|(_, count)| *count)
        .map(|(author, _)| author)
}

/// Extract issue and PR references from commit messages
fn extract_references(commits: &[CommitInfo]) -> (Vec<String>, Vec<String>) {
    let mut issues = HashSet::new();
    let mut prs = HashSet::new();

    for commit in commits {
        let msg = &commit.message;

        // Match #123, fixes #456, closes #789, etc.
        for cap in regex::Regex::new(r"(?i)(?:fix(?:es)?|close(?:s)?|resolve(?:s)?)\s+#(\d+)")
            .unwrap()
            .captures_iter(msg)
        {
            if let Some(num) = cap.get(1) {
                issues.insert(format!("#{}", num.as_str()));
            }
        }

        // Match standalone #123
        for cap in regex::Regex::new(r"#(\d+)").unwrap().captures_iter(msg) {
            if let Some(num) = cap.get(1) {
                issues.insert(format!("#{}", num.as_str()));
            }
        }

        // Match PR references (pull/123, PR #123)
        for cap in regex::Regex::new(r"(?i)(?:pr|pull)\s*#?(\d+)")
            .unwrap()
            .captures_iter(msg)
        {
            if let Some(num) = cap.get(1) {
                prs.insert(num.as_str().to_string());
            }
        }
    }

    let mut issue_list: Vec<String> = issues.into_iter().collect();
    let mut pr_list: Vec<String> = prs.into_iter().collect();

    issue_list.sort();
    pr_list.sort();

    (issue_list, pr_list)
}

/// Get files that frequently change together with the target file
fn get_cochanged_files(file_path: &str, limit: usize) -> Result<Vec<String>> {
    // Get commits that touched this file
    let output = Command::new("git")
        .args(["log", "--format=%H", "--", file_path])
        .output()?;

    if !output.status.success() {
        return Ok(vec![]);
    }

    let commits: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .trim()
        .lines()
        .map(|s| s.to_string())
        .collect();

    // For each commit, get the files changed
    let mut file_counts: HashMap<String, usize> = HashMap::new();

    for commit_hash in commits.iter().take(50) {
        // Limit to last 50 commits for performance
        let output = Command::new("git")
            .args(["show", "--name-only", "--format=", commit_hash])
            .output()?;

        if output.status.success() {
            let files = String::from_utf8_lossy(&output.stdout);
            for file in files.trim().lines() {
                let file = file.trim();
                if !file.is_empty() && file != file_path {
                    *file_counts.entry(file.to_string()).or_insert(0) += 1;
                }
            }
        }
    }

    // Sort by frequency
    let mut sorted: Vec<(String, usize)> = file_counts.into_iter().collect();
    sorted.sort_by(|a, b| b.1.cmp(&a.1));

    Ok(sorted.into_iter().take(limit).map(|(f, _)| f).collect())
}

/// Generate a brief evolution summary
fn generate_evolution_summary(commits: &[CommitInfo]) -> Option<String> {
    if commits.is_empty() {
        return None;
    }

    let recent_count = commits.len().min(10);
    let recent_commits = &commits[0..recent_count];

    // Categorize recent changes
    let mut features = 0;
    let mut fixes = 0;
    let mut refactors = 0;
    let mut docs = 0;
    let mut _other = 0;

    for commit in recent_commits {
        let msg = commit.message.to_lowercase();
        if msg.contains("feat") || msg.contains("add") || msg.contains("implement") {
            features += 1;
        } else if msg.contains("fix") || msg.contains("bug") {
            fixes += 1;
        } else if msg.contains("refactor") || msg.contains("clean") {
            refactors += 1;
        } else if msg.contains("doc") || msg.contains("comment") {
            docs += 1;
        } else {
            _other += 1;
        }
    }

    let mut parts = vec![];
    if features > 0 {
        parts.push(format!("{} features", features));
    }
    if fixes > 0 {
        parts.push(format!("{} fixes", fixes));
    }
    if refactors > 0 {
        parts.push(format!("{} refactors", refactors));
    }
    if docs > 0 {
        parts.push(format!("{} docs", docs));
    }

    if parts.is_empty() {
        Some(format!("{} changes in recent history", recent_count))
    } else {
        Some(format!("Recent: {}", parts.join(", ")))
    }
}

/// Extract reason from commit message (first line)
fn extract_reason(message: &str) -> String {
    message.lines().next().unwrap_or(message).to_string()
}

fn print_not_a_repo() {
    println!();
    println!("{}", "Not a git repository".red().bold());
    println!();
    println!(
        "{}",
        "WTF requires git history to analyze code origin and evolution.".dimmed()
    );
    println!(
        "{}",
        "Navigate to a git repository or initialize one with 'git init'.".dimmed()
    );
    println!();
}

fn print_wtf_output(result: &WtfResult) {
    println!();
    println!("{} {}", "WTF:".red().bold(), result.target.bold());

    if let Some(line_range) = result.line_range {
        println!(
            "  {} Lines {}-{}",
            "Range:".dimmed(),
            line_range.0,
            line_range.1
        );
    }

    println!();

    if result.origin_commit.is_none() && result.total_commits == 0 {
        println!("{}", "No git history found for this target.".yellow());
        println!();
        return;
    }

    // Origin info
    if let Some(origin) = &result.origin_commit {
        println!(
            "{} {}",
            "Origin".yellow(),
            origin.hash[..7.min(origin.hash.len())].yellow().bold()
        );
        println!(
            "  {} @{} {}",
            "Author:".dimmed(),
            origin.author,
            format!("({})", origin.date).dimmed()
        );
        println!("  {} \"{}\"", "Message:".dimmed(), origin.message);
    }

    // Origin reason
    if let Some(reason) = &result.origin_reason {
        println!();
        println!("{} {}", "Reason:".dimmed(), reason);
    }

    // Evolution info
    if result.total_commits > 0 {
        println!();
        println!("{}", "Evolution".cyan());
        println!(
            "  {} commits by {} contributors",
            result.total_commits,
            result.contributors.len()
        );
        if let Some(summary) = &result.evolution_summary {
            println!("  {}", summary);
        }
    }

    // Primary author
    if let Some(author) = &result.primary_author {
        println!("{} @{}", "  Owner:".dimmed(), author);
    }

    // Co-changes
    if !result.frequently_changed_with.is_empty() {
        println!();
        println!(
            "{} {}",
            "Co-changes".cyan(),
            "(files that change together)".dimmed()
        );
        for file in result.frequently_changed_with.iter().take(5) {
            println!("  {} {}", "*".dimmed(), file);
        }
    }

    // References
    if !result.issue_refs.is_empty() || !result.pr_refs.is_empty() {
        println!();
        println!("{}", "References".cyan());
        for issue in &result.issue_refs {
            println!("  {} {}", "*".dimmed(), issue);
        }
        for pr in &result.pr_refs {
            println!("  {} PR#{}", "*".dimmed(), pr);
        }
    }

    println!();
    println!(
        "{}",
        format!("Analysis time: {:.1}ms", result.analysis_time_ms).dimmed()
    );

    println!();
}
