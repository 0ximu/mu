//! Smart context extraction for LLM questions.
//!
//! Extracts relevant code context based on natural language questions.

mod extractor;

pub use extractor::{ContextExtractor, ContextResult};
