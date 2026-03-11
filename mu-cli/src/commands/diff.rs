//! Diff command - Semantic diff between git refs
//!
//! Compares two git refs (branches, commits, tags) and shows semantic changes
//! at the entity level (functions, classes, modules).

use std::path::Path;
use std::process::Command;
use std::time::Instant;

use colored::Colorize;
use mu_core::differ::SemanticDiffResult;
use mu_core::types::ModuleDef;
use serde::Serialize;

use crate::output::{Output, OutputFormat, TableDisplay};

/// A single semantic change
#[derive(Debug, Clone, Serialize)]
pub struct SemanticChange {
    pub change_type: String,
    pub entity_type: String,
    pub entity_name: String,
    pub file_path: Option<String>,
    pub is_breaking: bool,
    pub description: Option<String>,
}

/// Diff result collection
#[derive(Debug, Serialize)]
pub struct DiffResult {
    pub base_ref: String,
    pub head_ref: String,
    pub changes: Vec<SemanticChange>,
    pub breaking_changes: Vec<SemanticChange>,
    pub files_changed: usize,
    pub duration_ms: u64,
}

impl TableDisplay for DiffResult {
    fn to_table(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!(
            "{} {} -> {}\n",
            "DIFF:".cyan().bold(),
            self.base_ref.yellow(),
            self.head_ref.green()
        ));
        output.push_str(&format!(
            "Found {} changes ({} breaking) in {} files ({}ms)\n\n",
            self.changes.len().to_string().cyan(),
            self.breaking_changes.len().to_string().red(),
            self.files_changed,
            self.duration_ms
        ));

        // Breaking changes section
        if !self.breaking_changes.is_empty() {
            output.push_str(&format!("{}\n", "⚠️  BREAKING CHANGES:".red().bold()));
            output.push_str(&format!("{}\n", "-".repeat(60)));

            for change in &self.breaking_changes {
                let icon = match change.change_type.as_str() {
                    "removed" => "🗑️",
                    "modified" => "✏️",
                    "signature_changed" => "🔧",
                    _ => "⚠️",
                };

                output.push_str(&format!(
                    "  {} {} {} ({})\n",
                    icon,
                    change.entity_name.red().bold(),
                    format!("[{}]", change.entity_type).dimmed(),
                    change.change_type
                ));

                if let Some(ref path) = change.file_path {
                    output.push_str(&format!("     {}\n", path.dimmed()));
                }

                if let Some(ref desc) = change.description {
                    output.push_str(&format!("     {}\n", desc.dimmed()));
                }
            }
            output.push('\n');
        }

        // All changes section
        if self.changes.is_empty() {
            output.push_str(&format!("{}\n", "No semantic changes detected.".dimmed()));
            return output;
        }

        // Group changes by type
        let mut added: Vec<&SemanticChange> = Vec::new();
        let mut modified: Vec<&SemanticChange> = Vec::new();
        let mut removed: Vec<&SemanticChange> = Vec::new();

        for change in &self.changes {
            match change.change_type.as_str() {
                "added" => added.push(change),
                "modified" | "signature_changed" => modified.push(change),
                "removed" => removed.push(change),
                _ => modified.push(change),
            }
        }

        // Added
        if !added.is_empty() {
            output.push_str(&format!("{} ({}):\n", "ADDED".green().bold(), added.len()));
            for change in &added {
                output.push_str(&format!(
                    "  + {} [{}]\n",
                    change.entity_name.green(),
                    change.entity_type
                ));
                if let Some(ref path) = change.file_path {
                    output.push_str(&format!("    {}\n", path.dimmed()));
                }
            }
            output.push('\n');
        }

        // Modified
        if !modified.is_empty() {
            output.push_str(&format!(
                "{} ({}):\n",
                "MODIFIED".yellow().bold(),
                modified.len()
            ));
            for change in &modified {
                let marker = if change.is_breaking { "⚠" } else { "~" };
                output.push_str(&format!(
                    "  {} {} [{}]\n",
                    marker,
                    change.entity_name.yellow(),
                    change.entity_type
                ));
                if let Some(ref path) = change.file_path {
                    output.push_str(&format!("    {}\n", path.dimmed()));
                }
            }
            output.push('\n');
        }

        // Removed
        if !removed.is_empty() {
            output.push_str(&format!(
                "{} ({}):\n",
                "REMOVED".red().bold(),
                removed.len()
            ));
            for change in &removed {
                let marker = if change.is_breaking { "⚠" } else { "-" };
                output.push_str(&format!(
                    "  {} {} [{}]\n",
                    marker,
                    change.entity_name.red(),
                    change.entity_type
                ));
                if let Some(ref path) = change.file_path {
                    output.push_str(&format!("    {}\n", path.dimmed()));
                }
            }
        }

        output
    }

}

/// Get the list of changed files between two git refs
fn get_changed_files(base_ref: &str, head_ref: &str) -> anyhow::Result<Vec<String>> {
    let output = Command::new("git")
        .args([
            "diff",
            "--name-only",
            &format!("{}...{}", base_ref, head_ref),
        ])
        .output()?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("git diff failed: {}", stderr);
    }

    let files: Vec<String> = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|l| !l.is_empty())
        .map(|s| s.to_string())
        .collect();

    Ok(files)
}

/// Get file content at a specific git ref
fn get_file_at_ref(file_path: &str, git_ref: &str) -> anyhow::Result<Option<String>> {
    let output = Command::new("git")
        .args(["show", &format!("{}:{}", git_ref, file_path)])
        .output()?;

    if !output.status.success() {
        // File might not exist at this ref
        return Ok(None);
    }

    Ok(Some(String::from_utf8_lossy(&output.stdout).to_string()))
}

/// Detect language from file extension
fn detect_language(file_path: &str) -> Option<&'static str> {
    let ext = Path::new(file_path).extension()?.to_str()?;
    match ext {
        "py" => Some("python"),
        "ts" | "tsx" => Some("typescript"),
        "js" | "jsx" => Some("javascript"),
        "go" => Some("go"),
        "rs" => Some("rust"),
        "java" => Some("java"),
        "cs" => Some("csharp"),
        _ => None,
    }
}

/// Parse file content into a ModuleDef, returning None on failure.
fn parse_to_module(content: &str, file_path: &str, language: &str) -> Option<ModuleDef> {
    let result = mu_core::parser::parse_source(content, file_path, language);
    result.module
}

/// Create an empty ModuleDef for a file path (used when file doesn't exist at a ref).
fn empty_module(file_path: &str, language: &str) -> ModuleDef {
    ModuleDef::new(
        file_path.to_string(),
        file_path.to_string(),
        language.to_string(),
        vec![],
        vec![],
        vec![],
        None,
        0,
        None,
    )
}

/// Convert core EntityChange to CLI SemanticChange.
fn convert_core_change(change: &mu_core::differ::EntityChange) -> SemanticChange {
    let description = match (&change.details, &change.old_signature, &change.new_signature) {
        (Some(details), _, _) => Some(details.clone()),
        (None, Some(old), Some(new)) => Some(format!("{} -> {}", old, new)),
        (None, None, Some(sig)) => Some(sig.clone()),
        (None, Some(sig), None) => Some(sig.clone()),
        (None, None, None) => None,
    };

    SemanticChange {
        change_type: change.change_type.clone(),
        entity_type: change.entity_type.clone(),
        entity_name: change.full_name(),
        file_path: Some(change.file_path.clone()),
        is_breaking: change.is_breaking,
        description,
    }
}

/// Convert a core SemanticDiffResult into the CLI DiffResult.
fn convert_diff_result(
    core: &SemanticDiffResult,
    base_ref: &str,
    head_ref: &str,
    files_changed: usize,
    duration_ms: u64,
) -> DiffResult {
    let changes: Vec<SemanticChange> = core.changes.iter().map(convert_core_change).collect();
    let breaking_changes: Vec<SemanticChange> = changes.iter().filter(|c| c.is_breaking).cloned().collect();

    DiffResult {
        base_ref: base_ref.to_string(),
        head_ref: head_ref.to_string(),
        changes,
        breaking_changes,
        files_changed,
        duration_ms,
    }
}

/// Run a semantic diff between two git refs and return the result.
///
/// This is the reusable core logic — called by both the CLI command and MCP tools.
pub fn semantic_diff(base_ref: &str, head_ref: &str) -> anyhow::Result<DiffResult> {
    let start = Instant::now();

    let changed_files = get_changed_files(base_ref, head_ref)?;
    let files_changed = changed_files.len();

    if changed_files.is_empty() {
        return Ok(DiffResult {
            base_ref: base_ref.to_string(),
            head_ref: head_ref.to_string(),
            changes: Vec::new(),
            breaking_changes: Vec::new(),
            files_changed: 0,
            duration_ms: start.elapsed().as_millis() as u64,
        });
    }

    let mut base_modules = Vec::new();
    let mut head_modules = Vec::new();

    for file_path in &changed_files {
        let Some(language) = detect_language(file_path) else {
            continue;
        };

        let base_content = get_file_at_ref(file_path, base_ref)?;
        let head_content = get_file_at_ref(file_path, head_ref)?;

        let base_mod = match base_content {
            Some(ref content) => parse_to_module(content, file_path, language)
                .unwrap_or_else(|| empty_module(file_path, language)),
            None => empty_module(file_path, language),
        };
        let head_mod = match head_content {
            Some(ref content) => parse_to_module(content, file_path, language)
                .unwrap_or_else(|| empty_module(file_path, language)),
            None => empty_module(file_path, language),
        };

        base_modules.push(base_mod);
        head_modules.push(head_mod);
    }

    let core_result = mu_core::differ::semantic_diff_modules(&base_modules, &head_modules);
    let duration_ms = start.elapsed().as_millis() as u64;

    Ok(convert_diff_result(
        &core_result,
        base_ref,
        head_ref,
        files_changed,
        duration_ms,
    ))
}

/// Detect the default branch name from git.
pub fn detect_default_branch() -> String {
    let result = Command::new("git")
        .args(["symbolic-ref", "refs/remotes/origin/HEAD"])
        .output();

    result
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .and_then(|s| s.trim().rsplit('/').next().map(|s| s.to_string()))
        .unwrap_or_else(|| "main".to_string())
}

/// Run the diff command (CLI entry point)
pub async fn run(base_ref: &str, head_ref: &str, format: OutputFormat) -> anyhow::Result<()> {
    let result = semantic_diff(base_ref, head_ref)?;
    Output::new(result, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;
    use mu_core::differ::EntityChange;

    #[test]
    fn test_detect_language() {
        assert_eq!(detect_language("test.py"), Some("python"));
        assert_eq!(detect_language("test.ts"), Some("typescript"));
        assert_eq!(detect_language("test.rs"), Some("rust"));
        assert_eq!(detect_language("test.txt"), None);
    }

    #[test]
    fn test_convert_core_change_simple() {
        let change = EntityChange::new(
            "added".to_string(),
            "function".to_string(),
            "my_func".to_string(),
            "src/lib.py".to_string(),
            None,
            None,
            None,
            None,
            false,
        );

        let converted = convert_core_change(&change);
        assert_eq!(converted.change_type, "added");
        assert_eq!(converted.entity_type, "function");
        assert_eq!(converted.entity_name, "my_func");
        assert_eq!(converted.file_path, Some("src/lib.py".to_string()));
        assert!(!converted.is_breaking);
        assert!(converted.description.is_none());
    }

    #[test]
    fn test_convert_core_change_with_parent() {
        let change = EntityChange::new(
            "removed".to_string(),
            "method".to_string(),
            "do_thing".to_string(),
            "src/lib.py".to_string(),
            Some("MyClass".to_string()),
            None,
            Some("do_thing(self, x: int)".to_string()),
            None,
            true,
        );

        let converted = convert_core_change(&change);
        assert_eq!(converted.entity_name, "MyClass.do_thing");
        assert!(converted.is_breaking);
        assert_eq!(
            converted.description,
            Some("do_thing(self, x: int)".to_string())
        );
    }

    #[test]
    fn test_convert_core_change_with_details() {
        let change = EntityChange::new(
            "modified".to_string(),
            "function".to_string(),
            "process".to_string(),
            "src/lib.py".to_string(),
            None,
            Some("return: str -> int, complexity: 3 -> 7".to_string()),
            Some("process(x: str) -> str".to_string()),
            Some("process(x: str) -> int".to_string()),
            true,
        );

        let converted = convert_core_change(&change);
        assert_eq!(converted.change_type, "modified");
        // details takes priority over signatures
        assert_eq!(
            converted.description,
            Some("return: str -> int, complexity: 3 -> 7".to_string())
        );
    }

    #[test]
    fn test_empty_module() {
        let m = empty_module("src/foo.py", "python");
        assert_eq!(m.path, "src/foo.py");
        assert_eq!(m.language, "python");
        assert!(m.functions.is_empty());
        assert!(m.classes.is_empty());
    }
}
