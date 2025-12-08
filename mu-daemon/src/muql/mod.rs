//! MUQL (MU Query Language) parser and executor.
//!
//! A SQL-like query language for exploring codebases:
//! - SELECT: Query nodes with filters
//! - SHOW: Explore relationships (deps, impact, cycles)
//! - FIND: Pattern-based search
//! - PATH: Find paths between nodes
//! - ANALYZE: Built-in analysis queries

mod executor;
mod parser;
mod planner;

pub use executor::execute;
pub use parser::{parse, Query};
