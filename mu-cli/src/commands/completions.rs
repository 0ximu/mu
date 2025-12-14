//! Shell completions command - Generate shell completion scripts
//!
//! Generates completion scripts for various shells:
//! - bash: Add to ~/.bashrc or ~/.bash_completion
//! - zsh: Add to ~/.zshrc or put in fpath
//! - fish: Add to ~/.config/fish/completions/
//! - powershell: Add to $PROFILE
//! - elvish: Add to ~/.elvish/rc.elv

use std::io;

use clap::Command;
use clap_complete::{generate, shells};
use colored::Colorize;
use serde::Serialize;

use crate::output::{Output, OutputFormat, TableDisplay};

/// Supported shells for completion generation
#[derive(Debug, Clone, Copy, clap::ValueEnum)]
#[allow(clippy::enum_variant_names)]
pub enum Shell {
    Bash,
    Zsh,
    Fish,
    PowerShell,
    Elvish,
}

impl std::fmt::Display for Shell {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Shell::Bash => write!(f, "bash"),
            Shell::Zsh => write!(f, "zsh"),
            Shell::Fish => write!(f, "fish"),
            Shell::PowerShell => write!(f, "powershell"),
            Shell::Elvish => write!(f, "elvish"),
        }
    }
}

/// Instructions for installing completions
#[derive(Debug, Serialize)]
pub struct CompletionInstructions {
    pub shell: String,
    pub instructions: Vec<String>,
}

impl TableDisplay for CompletionInstructions {
    fn to_table(&self) -> String {
        let mut output = String::new();
        output.push_str(&format!(
            "{} completions for {}\n\n",
            "MU".cyan().bold(),
            self.shell.yellow()
        ));
        output.push_str(&format!("{}\n", "Installation:".cyan().bold()));
        for instruction in &self.instructions {
            output.push_str(&format!("  {}\n", instruction));
        }
        output
    }

    fn to_mu(&self) -> String {
        let mut lines = vec![format!(":: completions {}", self.shell)];
        for instruction in &self.instructions {
            lines.push(format!("# {}", instruction));
        }
        lines.join("\n")
    }
}

/// Get installation instructions for a shell
fn get_instructions(shell: Shell) -> Vec<String> {
    match shell {
        Shell::Bash => vec![
            "# Add to ~/.bashrc:".to_string(),
            "eval \"$(mu completions bash)\"".to_string(),
            "".to_string(),
            "# Or save to a file:".to_string(),
            "mu completions bash > ~/.local/share/bash-completion/completions/mu".to_string(),
        ],
        Shell::Zsh => vec![
            "# Add to ~/.zshrc:".to_string(),
            "eval \"$(mu completions zsh)\"".to_string(),
            "".to_string(),
            "# Or save to a file in fpath:".to_string(),
            "mu completions zsh > ~/.zfunc/_mu".to_string(),
            "# Then add to ~/.zshrc before compinit:".to_string(),
            "fpath=(~/.zfunc $fpath)".to_string(),
        ],
        Shell::Fish => vec![
            "# Save to fish completions directory:".to_string(),
            "mu completions fish > ~/.config/fish/completions/mu.fish".to_string(),
        ],
        Shell::PowerShell => vec![
            "# Add to $PROFILE:".to_string(),
            "Invoke-Expression (& mu completions powershell | Out-String)".to_string(),
        ],
        Shell::Elvish => vec![
            "# Add to ~/.elvish/rc.elv:".to_string(),
            "eval (mu completions elvish | slurp)".to_string(),
        ],
    }
}

/// Generate completions and write to stdout using provided Command
pub fn generate_completions_with_cmd(shell: Shell, cmd: &mut Command) {
    match shell {
        Shell::Bash => generate(shells::Bash, cmd, "mu", &mut io::stdout()),
        Shell::Zsh => generate(shells::Zsh, cmd, "mu", &mut io::stdout()),
        Shell::Fish => generate(shells::Fish, cmd, "mu", &mut io::stdout()),
        Shell::PowerShell => generate(shells::PowerShell, cmd, "mu", &mut io::stdout()),
        Shell::Elvish => generate(shells::Elvish, cmd, "mu", &mut io::stdout()),
    }
}

/// Run the completions command
pub fn run(shell: Shell, show_instructions: bool, format: OutputFormat) -> anyhow::Result<()> {
    if show_instructions {
        let instructions = CompletionInstructions {
            shell: shell.to_string(),
            instructions: get_instructions(shell),
        };
        Output::new(instructions, format).render()
    } else {
        // We need to get the command from main, but we can't import it here
        // So we use a simplified approach - the actual generation happens in main.rs
        // For now, just return an error with instructions
        anyhow::bail!(
            "Generate completions using: mu completions <shell>\n\
             To see installation instructions: mu completions <shell> --instructions"
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_shell_display() {
        assert_eq!(Shell::Bash.to_string(), "bash");
        assert_eq!(Shell::Zsh.to_string(), "zsh");
        assert_eq!(Shell::Fish.to_string(), "fish");
        assert_eq!(Shell::PowerShell.to_string(), "powershell");
        assert_eq!(Shell::Elvish.to_string(), "elvish");
    }

    #[test]
    fn test_get_instructions() {
        let bash_instructions = get_instructions(Shell::Bash);
        assert!(!bash_instructions.is_empty());
        assert!(bash_instructions.iter().any(|i| i.contains("bashrc")));

        let zsh_instructions = get_instructions(Shell::Zsh);
        assert!(!zsh_instructions.is_empty());
        assert!(zsh_instructions.iter().any(|i| i.contains("zshrc")));
    }
}
