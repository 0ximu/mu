//! Zen command - Cache cleanup to achieve zen
//!
//! Clears caches and temporary files, providing a clean slate
//! for the codebase analysis tools.
//!
//! With `--reset`, removes ALL MU-generated files for a fresh start.

use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

use colored::Colorize;

use crate::output::OutputFormat;

/// Statistics about what was cleaned
#[derive(Debug, serde::Serialize)]
pub struct ZenStats {
    pub cache_entries_removed: usize,
    pub bytes_freed: usize,
    pub temp_files_removed: usize,
    /// Whether this was a full reset (--reset flag)
    pub reset_mode: bool,
}

impl ZenStats {
    fn is_already_clean(&self) -> bool {
        self.cache_entries_removed == 0 && self.temp_files_removed == 0
    }

    fn bytes_freed_mb(&self) -> f64 {
        self.bytes_freed as f64 / 1_000_000.0
    }
}

/// Find all cache directories and temp files
fn find_cache_targets(root: &Path) -> Vec<PathBuf> {
    let mut targets = Vec::new();

    // Project-local .mu-cache
    let mu_cache = root.join(".mu-cache");
    if mu_cache.exists() {
        targets.push(mu_cache);
    }

    // Project-local .mu/ directory (may contain temp files)
    let mu_dir = root.join(".mu");
    if mu_dir.exists() {
        // Look for .tmp files in .mu/
        if let Ok(entries) = fs::read_dir(&mu_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.extension().and_then(|s| s.to_str()) == Some("tmp") {
                    targets.push(path);
                }
            }
        }
    }

    targets
}

/// Find ALL MU-generated files for full reset
fn find_reset_targets(root: &Path) -> Vec<PathBuf> {
    let mut targets = Vec::new();

    // .mu/ directory (contains mubase, cache, etc.)
    let mu_dir = root.join(".mu");
    if mu_dir.exists() {
        targets.push(mu_dir);
    }

    // .mu-cache/ directory
    let mu_cache = root.join(".mu-cache");
    if mu_cache.exists() {
        targets.push(mu_cache);
    }

    // .murc.toml config file
    let murc = root.join(".murc.toml");
    if murc.exists() {
        targets.push(murc);
    }

    // Legacy .mubase file (old database location)
    let mubase_legacy = root.join(".mubase");
    if mubase_legacy.exists() {
        targets.push(mubase_legacy);
    }

    targets
}

/// Calculate total size of a directory or file
fn calculate_size(path: &Path) -> u64 {
    if path.is_file() {
        return path.metadata().map(|m| m.len()).unwrap_or(0);
    }

    if path.is_dir() {
        let mut total = 0u64;
        if let Ok(entries) = fs::read_dir(path) {
            for entry in entries.flatten() {
                total += calculate_size(&entry.path());
            }
        }
        return total;
    }

    0
}

/// Count files in a directory recursively
fn count_files(path: &Path) -> usize {
    if path.is_file() {
        return 1;
    }

    if path.is_dir() {
        let mut count = 0;
        if let Ok(entries) = fs::read_dir(path) {
            for entry in entries.flatten() {
                count += count_files(&entry.path());
            }
        }
        return count;
    }

    0
}

/// Delete a path (file or directory)
fn delete_path(path: &Path) -> Result<(), std::io::Error> {
    if path.is_dir() {
        fs::remove_dir_all(path)
    } else {
        fs::remove_file(path)
    }
}

/// Run the zen command - cache cleanup with personality
pub async fn run(path: &str, yes: bool, reset: bool, format: OutputFormat) -> anyhow::Result<()> {
    let root = Path::new(path)
        .canonicalize()
        .unwrap_or_else(|_| Path::new(path).to_path_buf());

    if !root.exists() {
        anyhow::bail!("Path does not exist: {}", root.display());
    }

    if !root.is_dir() {
        anyhow::bail!("Path is not a directory: {}", root.display());
    }

    // Find targets based on mode
    let targets = if reset {
        find_reset_targets(&root)
    } else {
        find_cache_targets(&root)
    };

    if targets.is_empty() {
        let stats = ZenStats {
            cache_entries_removed: 0,
            bytes_freed: 0,
            temp_files_removed: 0,
            reset_mode: reset,
        };

        match format {
            OutputFormat::Json => {
                println!("{}", serde_json::to_string_pretty(&stats)?);
            }
            _ => {
                print_zen_output(&stats);
            }
        }

        return Ok(());
    }

    // Calculate what will be cleaned
    let mut total_size = 0u64;
    let mut total_files = 0;

    for target in &targets {
        total_size += calculate_size(target);
        let files = count_files(target);
        total_files += files;
    }

    // Show what will be cleaned if not --yes
    if !yes && format != OutputFormat::Json {
        println!();
        if reset {
            println!("{}", "Zen - Full Reset".red().bold());
            println!();
            println!(
                "{}",
                "WARNING: This will remove ALL MU files including the database!".yellow()
            );
        } else {
            println!("{}", "Zen - Cache Cleanup".cyan().bold());
        }
        println!();
        println!("{}", "Will clean:".yellow());

        for target in &targets {
            let size = calculate_size(target);
            let size_mb = size as f64 / 1_000_000.0;
            let rel_path = target.strip_prefix(&root).unwrap_or(target);

            if target.is_dir() {
                println!(
                    "  {} {} ({:.1}MB)",
                    "[DIR]".dimmed(),
                    rel_path.display(),
                    size_mb
                );
            } else {
                println!(
                    "  {} {} ({:.1}MB)",
                    "[FILE]".dimmed(),
                    rel_path.display(),
                    size_mb
                );
            }
        }

        println!();
        println!(
            "{} {} files, {:.1}MB total",
            "Total:".yellow(),
            total_files,
            total_size as f64 / 1_000_000.0
        );
        println!();

        print!("{} Continue? [y/N] ", "?".cyan().bold());
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;
        let input = input.trim().to_lowercase();

        if input != "y" && input != "yes" {
            println!("{}", "Cancelled.".dimmed());
            return Ok(());
        }
    }

    // Perform cleanup
    let mut cleaned_size = 0u64;
    let mut cleaned_files = 0;
    let mut cleaned_temp_files = 0;

    for target in &targets {
        let size = calculate_size(target);
        let files = count_files(target);
        let is_temp_file = target.is_file();

        if let Err(e) = delete_path(target) {
            eprintln!("Failed to delete {}: {}", target.display(), e);
            continue;
        }

        cleaned_size += size;
        cleaned_files += files;

        if is_temp_file {
            cleaned_temp_files += 1;
        }
    }

    let stats = ZenStats {
        cache_entries_removed: cleaned_files,
        bytes_freed: cleaned_size as usize,
        temp_files_removed: cleaned_temp_files,
        reset_mode: reset,
    };

    match format {
        OutputFormat::Json => {
            println!("{}", serde_json::to_string_pretty(&stats)?);
        }
        _ => {
            print_zen_output(&stats);
        }
    }

    Ok(())
}

fn print_zen_output(stats: &ZenStats) {
    println!();
    if stats.reset_mode {
        println!("{}", "Zen - Full Reset".red().bold());
    } else {
        println!("{}", "Zen".cyan().bold());
    }
    println!();

    if stats.is_already_clean() {
        println!("{}", "[OK] Already clean.".green());
        println!();
        if stats.reset_mode {
            println!("{}", "No MU files found. Nothing to reset.".dimmed());
        } else {
            println!(
                "{}",
                "Nothing to clean. Your codebase has achieved zen.".dimmed()
            );
        }
        println!();
        println!("{}", "What zen cleans:".cyan());
        println!("  {} .mu-cache/ directory", "*".dimmed());
        println!("  {} Temporary .tmp files in .mu/", "*".dimmed());
        println!();
        println!("{}", "What zen --reset removes:".cyan());
        println!("  {} .mu/ directory (database + cache)", "*".dimmed());
        println!("  {} .murc.toml config file", "*".dimmed());
        println!("  {} .mubase (legacy database)", "*".dimmed());
        println!();
        println!("{}", "Usage:".cyan());
        println!("  {} mu zen              # Clean caches only", "$".dimmed());
        println!(
            "  {} mu zen --reset      # Full reset (removes database)",
            "$".dimmed()
        );
        println!("  {} mu zen --yes        # Skip confirmation", "$".dimmed());
    } else {
        if stats.reset_mode {
            println!("{}", "Resetting...".bold());
        } else {
            println!("{}", "Cleaning...".bold());
        }
        println!();

        if stats.cache_entries_removed > 0 {
            println!(
                "{} Removed {} {}",
                "[OK]".green(),
                stats.cache_entries_removed,
                if stats.reset_mode {
                    "files"
                } else {
                    "cached entries"
                }
            );
        }

        if stats.temp_files_removed > 0 {
            println!(
                "{} Removed {} temp files",
                "[OK]".green(),
                stats.temp_files_removed
            );
        }

        let mb_freed = stats.bytes_freed_mb();
        if mb_freed > 0.01 {
            println!("{} Freed {:.1}MB", "[OK]".green(), mb_freed);
        }

        println!();
        if stats.reset_mode {
            println!(
                "{}",
                "Full reset complete. Run 'mu bootstrap' to rebuild.".dimmed()
            );
        } else {
            println!("{}", "Zen achieved.".dimmed());
        }
    }

    println!();
}
