//! Shared constants for the MU CLI.
//!
//! Centralizes magic numbers to make them discoverable and maintainable.
//! Path-related constants are in `mubase.rs` instead.

/// Spinner tick interval in milliseconds.
///
/// How often the progress spinner updates.
pub const SPINNER_TICK_MS: u64 = 100;

// Note: TOKENS_PER_NODE, TOKENS_PER_EDGE, SCHEMA_SEED_TOKENS are defined
// locally in vibes/omg.rs as they're specific to that (deprecated) command.
