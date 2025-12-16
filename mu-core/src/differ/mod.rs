//! Semantic diff engine for comparing ModuleDef structures.
//!
//! This module provides high-performance comparison of parsed code structures,
//! producing meaningful change descriptions suitable for code review and analysis.
//!
//! # Features
//!
//! - **Entity-level diffing**: Functions, classes, methods, parameters
//! - **Breaking change detection**: Identifies API-breaking changes
//! - **Summary generation**: Human-readable change summaries
//! - **Parallel processing**: Diffs multiple modules concurrently via Rayon
//!
//! # Example
//!
//! ```python
//! from mu import _core
//!
//! # Diff two sets of modules
//! result = _core.semantic_diff(base_modules, head_modules)
//!
//! # Access changes
//! for change in result.changes:
//!     print(f"{change.change_type}: {change.entity_type} {change.entity_name}")
//!
//! # Check for breaking changes
//! for breaking in result.breaking_changes:
//!     print(f"BREAKING: {breaking.entity_name}")
//! ```

pub mod changes;
pub mod comparator;

// Re-export types for lib.rs
pub use changes::{DiffSummary, EntityChange, SemanticDiffResult};
pub use comparator::{semantic_diff, semantic_diff_files, semantic_diff_modules};
