//! Security module for secret detection and redaction.

pub mod patterns;
pub mod redact;

pub use redact::redact_secrets;
