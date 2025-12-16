//! Command implementations for MU CLI
//!
//! Each command module provides a `run` function that executes the command logic.

pub mod bootstrap;
pub mod completions;
pub mod compress;
pub mod deps;
pub mod diff;
pub mod doctor;
pub mod embed;
pub mod export;
pub mod graph;
pub mod grok;
pub mod history;
pub mod mcp;
pub mod patterns;
pub mod query;
pub mod read;
pub mod search;
pub mod status;
pub mod vibes;
