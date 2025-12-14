//! Diff command - Semantic diff between git refs
//!
//! Compares two git refs (branches, commits, tags) and shows semantic changes
//! at the entity level (functions, classes, modules).

use std::path::Path;
use std::process::Command;
use std::time::Instant;

use colored::Colorize;
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

    fn to_mu(&self) -> String {
        let mut output = String::new();

        output.push_str(&format!(":: diff {}..{}\n", self.base_ref, self.head_ref));
        output.push_str(&format!("# changes: {}\n", self.changes.len()));
        output.push_str(&format!("# breaking: {}\n", self.breaking_changes.len()));
        output.push_str(&format!("# files: {}\n", self.files_changed));
        output.push_str(&format!("# duration: {}ms\n\n", self.duration_ms));

        // Breaking changes
        if !self.breaking_changes.is_empty() {
            output.push_str("## BREAKING\n");
            for change in &self.breaking_changes {
                output.push_str(&format!(
                    "! {} [{}] {}\n",
                    change.entity_name, change.entity_type, change.change_type
                ));
                if let Some(ref path) = change.file_path {
                    output.push_str(&format!("  | {}\n", path));
                }
            }
            output.push('\n');
        }

        // All changes
        output.push_str("## CHANGES\n");
        for change in &self.changes {
            let sigil = match change.change_type.as_str() {
                "added" => "+",
                "removed" => "-",
                _ => "~",
            };
            output.push_str(&format!(
                "{} {} [{}]\n",
                sigil, change.entity_name, change.entity_type
            ));
            if let Some(ref path) = change.file_path {
                output.push_str(&format!("  | {}\n", path));
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

/// Parse file and extract entity names using mu-core
fn extract_entities(content: &str, file_path: &str, language: &str) -> Vec<(String, String)> {
    // Use mu_core to parse and extract entities
    let result = mu_core::parser::parse_source(content, file_path, language);

    if !result.success {
        return Vec::new();
    }

    let Some(module) = result.module else {
        return Vec::new();
    };

    let mut entities = Vec::new();

    // Add module itself
    entities.push((module.name.clone(), "module".to_string()));

    // Add functions
    for func in &module.functions {
        entities.push((func.name.clone(), "function".to_string()));
    }

    // Add classes and their methods
    for class in &module.classes {
        entities.push((class.name.clone(), "class".to_string()));
        for method in &class.methods {
            entities.push((
                format!("{}.{}", class.name, method.name),
                "method".to_string(),
            ));
        }
    }

    entities
}

/// Compare entities between base and head versions
fn diff_entities(
    base_entities: &[(String, String)],
    head_entities: &[(String, String)],
    file_path: &str,
) -> Vec<SemanticChange> {
    let mut changes = Vec::new();

    let base_set: std::collections::HashSet<(&String, &String)> =
        base_entities.iter().map(|(a, b)| (a, b)).collect();
    let head_set: std::collections::HashSet<(&String, &String)> =
        head_entities.iter().map(|(a, b)| (a, b)).collect();

    // Find added entities
    for (name, entity_type) in head_entities {
        if !base_set.contains(&(name, entity_type)) {
            changes.push(SemanticChange {
                change_type: "added".to_string(),
                entity_type: entity_type.clone(),
                entity_name: name.clone(),
                file_path: Some(file_path.to_string()),
                is_breaking: false,
                description: None,
            });
        }
    }

    // Find removed entities
    for (name, entity_type) in base_entities {
        if !head_set.contains(&(name, entity_type)) {
            let is_breaking = matches!(entity_type.as_str(), "function" | "class" | "method");
            changes.push(SemanticChange {
                change_type: "removed".to_string(),
                entity_type: entity_type.clone(),
                entity_name: name.clone(),
                file_path: Some(file_path.to_string()),
                is_breaking,
                description: if is_breaking {
                    Some(format!("Removed {} may break dependents", entity_type))
                } else {
                    None
                },
            });
        }
    }

    changes
}

/// Run the diff command
pub async fn run(base_ref: &str, head_ref: &str, format: OutputFormat) -> anyhow::Result<()> {
    let start = Instant::now();

    // Get changed files
    let changed_files = get_changed_files(base_ref, head_ref)?;
    let files_changed = changed_files.len();

    if changed_files.is_empty() {
        let result = DiffResult {
            base_ref: base_ref.to_string(),
            head_ref: head_ref.to_string(),
            changes: Vec::new(),
            breaking_changes: Vec::new(),
            files_changed: 0,
            duration_ms: start.elapsed().as_millis() as u64,
        };
        return Output::new(result, format).render();
    }

    let mut all_changes = Vec::new();

    // Process each changed file
    for file_path in &changed_files {
        // Skip non-code files
        let Some(language) = detect_language(file_path) else {
            continue;
        };

        // Get file content at base and head
        let base_content = get_file_at_ref(file_path, base_ref)?;
        let head_content = get_file_at_ref(file_path, head_ref)?;

        match (&base_content, &head_content) {
            (None, Some(head)) => {
                // New file
                let entities = extract_entities(head, file_path, language);
                for (name, entity_type) in entities {
                    all_changes.push(SemanticChange {
                        change_type: "added".to_string(),
                        entity_type,
                        entity_name: name,
                        file_path: Some(file_path.clone()),
                        is_breaking: false,
                        description: Some("New file".to_string()),
                    });
                }
            }
            (Some(_base), None) => {
                // Deleted file - add as single removal
                all_changes.push(SemanticChange {
                    change_type: "removed".to_string(),
                    entity_type: "module".to_string(),
                    entity_name: file_path.clone(),
                    file_path: Some(file_path.clone()),
                    is_breaking: true,
                    description: Some("File deleted".to_string()),
                });
            }
            (Some(base), Some(head)) => {
                // Modified file - compare entities
                let base_entities = extract_entities(base, file_path, language);
                let head_entities = extract_entities(head, file_path, language);
                let file_changes = diff_entities(&base_entities, &head_entities, file_path);
                all_changes.extend(file_changes);
            }
            (None, None) => {
                // Both missing - shouldn't happen
            }
        }
    }

    // Separate breaking changes
    let breaking_changes: Vec<SemanticChange> = all_changes
        .iter()
        .filter(|c| c.is_breaking)
        .cloned()
        .collect();

    let duration_ms = start.elapsed().as_millis() as u64;

    let result = DiffResult {
        base_ref: base_ref.to_string(),
        head_ref: head_ref.to_string(),
        changes: all_changes,
        breaking_changes,
        files_changed,
        duration_ms,
    };

    Output::new(result, format).render()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_language() {
        assert_eq!(detect_language("test.py"), Some("python"));
        assert_eq!(detect_language("test.ts"), Some("typescript"));
        assert_eq!(detect_language("test.rs"), Some("rust"));
        assert_eq!(detect_language("test.txt"), None);
    }

    #[test]
    fn test_diff_entities() {
        let base = vec![
            ("foo".to_string(), "function".to_string()),
            ("bar".to_string(), "function".to_string()),
        ];
        let head = vec![
            ("foo".to_string(), "function".to_string()),
            ("baz".to_string(), "function".to_string()),
        ];

        let changes = diff_entities(&base, &head, "test.py");

        // Should have 2 changes: bar removed, baz added
        assert_eq!(changes.len(), 2);

        let added: Vec<_> = changes
            .iter()
            .filter(|c| c.change_type == "added")
            .collect();
        let removed: Vec<_> = changes
            .iter()
            .filter(|c| c.change_type == "removed")
            .collect();

        assert_eq!(added.len(), 1);
        assert_eq!(added[0].entity_name, "baz");

        assert_eq!(removed.len(), 1);
        assert_eq!(removed[0].entity_name, "bar");
        assert!(removed[0].is_breaking);
    }
}
