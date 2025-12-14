//! Integration tests for MU CLI
//!
//! Tests end-to-end command behavior using the CLI binary.
//! Uses tempfile for isolated test directories.

use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};
use tempfile::TempDir;

// ============================================================================
// Test Utilities
// ============================================================================

/// Get the path to the mu binary (built by cargo)
fn mu_binary() -> Command {
    Command::new(env!("CARGO_BIN_EXE_mu"))
}

/// Run mu command with the given args in the specified directory
fn run_mu(dir: &std::path::Path, args: &[&str]) -> Output {
    mu_binary()
        .current_dir(dir)
        .args(args)
        .output()
        .expect("Failed to execute mu command")
}

/// Get stdout as string
fn stdout(output: &Output) -> String {
    String::from_utf8_lossy(&output.stdout).to_string()
}

/// Get stderr as string
fn stderr(output: &Output) -> String {
    String::from_utf8_lossy(&output.stderr).to_string()
}

/// Create a sample Python file for testing
fn create_sample_python_file(dir: &std::path::Path, name: &str, content: &str) -> PathBuf {
    let path = dir.join(name);
    fs::write(&path, content).expect("Failed to write sample file");
    path
}

/// Create a minimal Python project in the temp directory
fn setup_sample_project(dir: &std::path::Path) {
    // Create a simple Python file
    create_sample_python_file(
        dir,
        "main.py",
        r#"
"""Main module for sample project."""

from typing import List

class Calculator:
    """A simple calculator class."""

    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    def multiply(self, a: int, b: int) -> int:
        """Multiply two numbers."""
        return a * b


def greet(name: str) -> str:
    """Return a greeting message."""
    return f"Hello, {name}!"


def main():
    """Entry point."""
    calc = Calculator()
    print(calc.add(1, 2))
    print(greet("World"))
"#,
    );

    // Create another module
    create_sample_python_file(
        dir,
        "utils.py",
        r#"
"""Utility functions."""

def helper_function(x: int) -> int:
    """A helper function."""
    return x * 2
"#,
    );
}

// ============================================================================
// Status Command Tests
// ============================================================================

#[test]
fn test_status_uninitialized() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    let output = run_mu(temp_dir.path(), &["status"]);

    assert!(output.status.success(), "status command should succeed");

    let stdout_str = stdout(&output);
    // Should indicate not initialized
    assert!(
        stdout_str.contains("Not initialized")
            || stdout_str.contains("not initialized")
            || stdout_str.contains("No .mu/mubase"),
        "Should show not initialized message, got: {}",
        stdout_str
    );
}

#[test]
fn test_status_json_format_uninitialized() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    let output = run_mu(temp_dir.path(), &["status", "--format", "json"]);

    assert!(
        output.status.success(),
        "status --format json should succeed"
    );

    let stdout_str = stdout(&output);
    // Should be valid JSON
    let parsed: Result<serde_json::Value, _> = serde_json::from_str(&stdout_str);
    assert!(
        parsed.is_ok(),
        "Output should be valid JSON: {}",
        stdout_str
    );

    let json = parsed.unwrap();
    // Check expected fields
    assert!(
        json.get("mubase_exists").is_some(),
        "Should have mubase_exists field"
    );
    assert!(
        json.get("config_exists").is_some(),
        "Should have config_exists field"
    );
    assert_eq!(
        json["mubase_exists"], false,
        "mubase_exists should be false"
    );
}

#[test]
fn test_status_after_bootstrap() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // Bootstrap first
    let bootstrap_output = run_mu(temp_dir.path(), &["bootstrap"]);
    assert!(
        bootstrap_output.status.success(),
        "bootstrap should succeed: {}",
        stderr(&bootstrap_output)
    );

    // Now check status
    let output = run_mu(temp_dir.path(), &["status"]);
    assert!(
        output.status.success(),
        "status should succeed after bootstrap"
    );

    let stdout_str = stdout(&output);
    // Should show ready status
    assert!(
        stdout_str.contains("Ready")
            || stdout_str.contains("ready")
            || stdout_str.contains("Nodes"),
        "Should show ready status or stats, got: {}",
        stdout_str
    );
}

#[test]
fn test_status_json_format_after_bootstrap() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // Bootstrap first
    let _ = run_mu(temp_dir.path(), &["bootstrap"]);

    // Check status with JSON format
    let output = run_mu(temp_dir.path(), &["status", "--format", "json"]);
    assert!(
        output.status.success(),
        "status --format json should succeed"
    );

    let stdout_str = stdout(&output);
    let json: serde_json::Value = serde_json::from_str(&stdout_str)
        .expect(&format!("Output should be valid JSON: {}", stdout_str));

    // Check expected fields
    assert_eq!(
        json["mubase_exists"], true,
        "mubase_exists should be true after bootstrap"
    );
    assert!(
        json.get("stats").is_some(),
        "Should have stats field after bootstrap"
    );

    // Stats should have node_count
    if let Some(stats) = json.get("stats") {
        assert!(
            stats.get("node_count").is_some(),
            "stats should have node_count"
        );
    }
}

// ============================================================================
// Bootstrap Command Tests
// ============================================================================

#[test]
fn test_bootstrap_creates_murc_toml() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    let output = run_mu(temp_dir.path(), &["bootstrap"]);
    assert!(
        output.status.success(),
        "bootstrap should succeed: {} {}",
        stdout(&output),
        stderr(&output)
    );

    // Check .murc.toml was created
    let config_path = temp_dir.path().join(".murc.toml");
    assert!(config_path.exists(), ".murc.toml should be created");

    // Check content is valid TOML
    let content = fs::read_to_string(&config_path).expect("Failed to read .murc.toml");
    let parsed: Result<toml::Value, _> = toml::from_str(&content);
    assert!(
        parsed.is_ok(),
        ".murc.toml should be valid TOML: {}",
        content
    );
}

#[test]
fn test_bootstrap_creates_mubase() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    let output = run_mu(temp_dir.path(), &["bootstrap"]);
    assert!(
        output.status.success(),
        "bootstrap should succeed: {} {}",
        stdout(&output),
        stderr(&output)
    );

    // Check .mu/mubase was created
    let mubase_path = temp_dir.path().join(".mu").join("mubase");
    assert!(mubase_path.exists(), ".mu/mubase should be created");
}

#[test]
fn test_bootstrap_force_rebuilds_database() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // First bootstrap
    let output1 = run_mu(temp_dir.path(), &["bootstrap"]);
    assert!(output1.status.success(), "first bootstrap should succeed");

    // Get initial mubase modification time
    let mubase_path = temp_dir.path().join(".mu").join("mubase");
    let initial_modified = fs::metadata(&mubase_path)
        .expect("mubase should exist")
        .modified()
        .expect("Should get modified time");

    // Wait a bit to ensure time difference
    std::thread::sleep(std::time::Duration::from_millis(100));

    // Second bootstrap with --force
    let output2 = run_mu(temp_dir.path(), &["bootstrap", "--force"]);
    assert!(output2.status.success(), "bootstrap --force should succeed");

    // Check mubase was rebuilt (modification time changed)
    let final_modified = fs::metadata(&mubase_path)
        .expect("mubase should exist")
        .modified()
        .expect("Should get modified time");

    assert!(
        final_modified > initial_modified,
        "mubase should be rebuilt with --force"
    );
}

#[test]
fn test_bootstrap_without_force_shows_info() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // First bootstrap
    let output1 = run_mu(temp_dir.path(), &["bootstrap"]);
    assert!(output1.status.success(), "first bootstrap should succeed");

    // Second bootstrap without --force
    let output2 = run_mu(temp_dir.path(), &["bootstrap"]);
    assert!(output2.status.success(), "second bootstrap should succeed");

    let stdout_str = stdout(&output2);
    // Should indicate already initialized
    assert!(
        stdout_str.contains("already initialized") || stdout_str.contains("--force"),
        "Should mention already initialized or --force, got: {}",
        stdout_str
    );
}

#[test]
fn test_bootstrap_empty_directory() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");

    // Bootstrap on empty directory
    let output = run_mu(temp_dir.path(), &["bootstrap"]);

    // Should succeed but show warning about no files
    let stdout_str = stdout(&output);
    let combined = format!("{} {}", stdout_str, stderr(&output));

    // Either succeeds with warning or shows no files found
    assert!(
        output.status.success()
            || combined.contains("No supported files")
            || combined.contains("No files"),
        "Should handle empty directory gracefully: {}",
        combined
    );
}

#[test]
fn test_bootstrap_json_format() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    let output = run_mu(temp_dir.path(), &["bootstrap", "--format", "json"]);
    assert!(
        output.status.success(),
        "bootstrap --format json should succeed: {}",
        stderr(&output)
    );

    let stdout_str = stdout(&output);
    let json: serde_json::Value = serde_json::from_str(&stdout_str)
        .expect(&format!("Output should be valid JSON: {}", stdout_str));

    // Check expected fields
    assert!(json.get("success").is_some(), "Should have success field");
    assert!(
        json.get("node_count").is_some(),
        "Should have node_count field"
    );
    assert!(
        json.get("edge_count").is_some(),
        "Should have edge_count field"
    );
    assert!(
        json.get("files_scanned").is_some(),
        "Should have files_scanned field"
    );
}

#[test]
fn test_bootstrap_updates_gitignore() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // Create an initial .gitignore
    let gitignore_path = temp_dir.path().join(".gitignore");
    fs::write(&gitignore_path, "*.pyc\n__pycache__/\n").expect("Failed to write .gitignore");

    let output = run_mu(temp_dir.path(), &["bootstrap"]);
    assert!(output.status.success(), "bootstrap should succeed");

    // Check .gitignore was updated
    let content = fs::read_to_string(&gitignore_path).expect("Failed to read .gitignore");
    assert!(
        content.contains(".mu/"),
        ".gitignore should contain .mu/: {}",
        content
    );
}

// ============================================================================
// Query Command Tests
// ============================================================================

#[test]
fn test_query_examples_no_daemon() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");

    // --examples should work without daemon
    let output = run_mu(temp_dir.path(), &["query", "--examples"]);
    assert!(output.status.success(), "query --examples should succeed");

    let stdout_str = stdout(&output);
    assert!(stdout_str.contains("MUQL"), "Should show MUQL examples");
    assert!(stdout_str.contains("SELECT"), "Should show SELECT examples");
    assert!(stdout_str.contains("SHOW"), "Should show SHOW examples");
}

#[test]
fn test_query_schema_no_daemon() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");

    // --schema should work without daemon
    let output = run_mu(temp_dir.path(), &["query", "--schema"]);
    assert!(output.status.success(), "query --schema should succeed");

    let stdout_str = stdout(&output);
    assert!(
        stdout_str.contains("Schema"),
        "Should show schema reference"
    );
    assert!(stdout_str.contains("nodes"), "Should mention nodes table");
    assert!(
        stdout_str.contains("functions"),
        "Should mention functions table"
    );
    assert!(
        stdout_str.contains("classes"),
        "Should mention classes table"
    );
}

#[test]
fn test_query_alias_works() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");

    // 'q' alias should work
    let output = run_mu(temp_dir.path(), &["q", "--examples"]);
    assert!(output.status.success(), "q alias should work");

    let stdout_str = stdout(&output);
    assert!(
        stdout_str.contains("MUQL"),
        "Should show MUQL examples via alias"
    );
}

// ============================================================================
// Output Format Tests
// ============================================================================

#[test]
fn test_format_json_produces_valid_json() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");

    // Test with status command
    let output = run_mu(temp_dir.path(), &["status", "--format", "json"]);
    assert!(
        output.status.success(),
        "status --format json should succeed"
    );

    let stdout_str = stdout(&output);
    let parsed: Result<serde_json::Value, _> = serde_json::from_str(&stdout_str);
    assert!(
        parsed.is_ok(),
        "JSON output should be valid: {}",
        stdout_str
    );
}

#[test]
fn test_format_table_produces_readable_output() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // Bootstrap with table format
    let output = run_mu(temp_dir.path(), &["bootstrap", "--format", "table"]);
    assert!(
        output.status.success(),
        "bootstrap --format table should succeed"
    );

    let stdout_str = stdout(&output);
    // Table format should have human-readable text
    assert!(
        stdout_str.contains("SUCCESS")
            || stdout_str.contains("success")
            || stdout_str.contains("MU"),
        "Table output should have readable status text: {}",
        stdout_str
    );
}

#[test]
fn test_format_mu_produces_sigil_output() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // Bootstrap first
    let _ = run_mu(temp_dir.path(), &["bootstrap"]);

    // Status with MU format
    let output = run_mu(temp_dir.path(), &["status", "--format", "mu"]);
    assert!(output.status.success(), "status --format mu should succeed");

    let stdout_str = stdout(&output);
    // MU format should have sigil markers
    assert!(
        stdout_str.contains("::") || stdout_str.contains("#"),
        "MU output should have sigil markers: {}",
        stdout_str
    );
}

// ============================================================================
// CLI Flag Tests
// ============================================================================

#[test]
fn test_help_flag() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    let output = run_mu(temp_dir.path(), &["--help"]);

    assert!(output.status.success(), "--help should succeed");

    let stdout_str = stdout(&output);
    assert!(stdout_str.contains("MU"), "Help should mention MU");
    assert!(
        stdout_str.contains("bootstrap"),
        "Help should list bootstrap command"
    );
    assert!(
        stdout_str.contains("status"),
        "Help should list status command"
    );
    assert!(
        stdout_str.contains("query"),
        "Help should list query command"
    );
}

#[test]
fn test_version_flag() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    let output = run_mu(temp_dir.path(), &["--version"]);

    assert!(output.status.success(), "--version should succeed");

    let stdout_str = stdout(&output);
    // Should contain version number
    assert!(
        stdout_str.contains("mu") || stdout_str.contains("0."),
        "Version output should contain version info: {}",
        stdout_str
    );
}

#[test]
fn test_verbose_flag() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // Run with verbose flag
    let output = run_mu(temp_dir.path(), &["--verbose", "status"]);
    assert!(output.status.success(), "--verbose status should succeed");

    // Note: verbose output may go to stderr or stdout depending on logging setup
    // Just verify command succeeds with the flag
}

#[test]
fn test_quiet_flag() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // Run with quiet flag
    let output = run_mu(temp_dir.path(), &["--quiet", "status"]);
    assert!(output.status.success(), "--quiet status should succeed");

    // Just verify command succeeds with the flag
}

// ============================================================================
// Command Alias Tests
// ============================================================================

#[test]
fn test_status_alias_st() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");

    // 'st' alias should work for status
    let output = run_mu(temp_dir.path(), &["st"]);
    assert!(output.status.success(), "st alias should work for status");

    // Should produce same type of output as status
    let stdout_str = stdout(&output);
    assert!(
        stdout_str.contains("initialized")
            || stdout_str.contains("Status")
            || stdout_str.contains("mubase"),
        "st should show status info: {}",
        stdout_str
    );
}

#[test]
fn test_bootstrap_alias_bs() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    // 'bs' alias should work for bootstrap
    let output = run_mu(temp_dir.path(), &["bs"]);
    assert!(
        output.status.success(),
        "bs alias should work for bootstrap: {}",
        stderr(&output)
    );

    // Should create .mu/mubase
    let mubase_path = temp_dir.path().join(".mu").join("mubase");
    assert!(
        mubase_path.exists(),
        ".mu/mubase should be created via bs alias"
    );
}

// ============================================================================
// Edge Case Tests
// ============================================================================

#[test]
fn test_nonexistent_path() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    let nonexistent = temp_dir.path().join("does_not_exist");

    let output = run_mu(
        temp_dir.path(),
        &["bootstrap", nonexistent.to_str().unwrap()],
    );

    // Should fail or error
    let combined = format!("{} {}", stdout(&output), stderr(&output));
    assert!(
        !output.status.success()
            || combined.to_lowercase().contains("error")
            || combined.to_lowercase().contains("not exist"),
        "Should report error for nonexistent path: {}",
        combined
    );
}

#[test]
fn test_file_instead_of_directory() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    let file_path = temp_dir.path().join("test.txt");
    fs::write(&file_path, "test content").expect("Failed to create file");

    let output = run_mu(temp_dir.path(), &["bootstrap", file_path.to_str().unwrap()]);

    // Should fail or error for file path
    let combined = format!("{} {}", stdout(&output), stderr(&output));
    assert!(
        !output.status.success()
            || combined.to_lowercase().contains("directory")
            || combined.to_lowercase().contains("not a"),
        "Should report error when path is file not directory: {}",
        combined
    );
}

// ============================================================================
// Cleanup and Isolation Tests
// ============================================================================

#[test]
fn test_parallel_execution_isolation() {
    // Create multiple temp directories and run commands in parallel
    // This tests that temp directories are properly isolated

    let handles: Vec<_> = (0..3)
        .map(|i| {
            std::thread::spawn(move || {
                let temp_dir = TempDir::new().expect("Failed to create temp dir");

                // Create different content in each
                let content = format!(
                    r#"
def func_{}():
    return {}
"#,
                    i, i
                );
                create_sample_python_file(temp_dir.path(), "module.py", &content);

                // Bootstrap
                let output = run_mu(temp_dir.path(), &["bootstrap"]);
                assert!(output.status.success(), "bootstrap {} should succeed", i);

                // Verify isolation - mubase exists only in this temp dir
                let mubase_path = temp_dir.path().join(".mu").join("mubase");
                assert!(
                    mubase_path.exists(),
                    "mubase should exist in temp dir {}",
                    i
                );

                // temp_dir is dropped here, cleaning up
            })
        })
        .collect();

    for handle in handles {
        handle.join().expect("Thread should complete");
    }
}

// ============================================================================
// JSON Output Validation Tests
// ============================================================================

#[test]
fn test_status_json_has_required_fields() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    let output = run_mu(temp_dir.path(), &["status", "--format", "json"]);

    let stdout_str = stdout(&output);
    let json: serde_json::Value = serde_json::from_str(&stdout_str).expect("Should be valid JSON");

    // Required fields
    let required_fields = ["config_exists", "mubase_exists", "message"];
    for field in required_fields {
        assert!(
            json.get(field).is_some(),
            "JSON should have '{}' field",
            field
        );
    }
}

#[test]
fn test_bootstrap_json_has_required_fields() {
    let temp_dir = TempDir::new().expect("Failed to create temp dir");
    setup_sample_project(temp_dir.path());

    let output = run_mu(temp_dir.path(), &["bootstrap", "--format", "json"]);
    assert!(output.status.success(), "bootstrap should succeed");

    let stdout_str = stdout(&output);
    let json: serde_json::Value = serde_json::from_str(&stdout_str).expect("Should be valid JSON");

    // Required fields for bootstrap result
    let required_fields = [
        "success",
        "node_count",
        "edge_count",
        "files_scanned",
        "files_parsed",
    ];
    for field in required_fields {
        assert!(
            json.get(field).is_some(),
            "Bootstrap JSON should have '{}' field: {}",
            field,
            stdout_str
        );
    }
}
