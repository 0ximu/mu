//! Embedding model trait for semantic search.
//!
//! This module defines a trait that external crates (like mu-embeddings)
//! can implement to provide embedding functionality without creating
//! circular dependencies.

use std::future::Future;
use std::pin::Pin;

/// Error type for embedding operations.
#[derive(Debug, thiserror::Error)]
pub enum EmbeddingError {
    /// Model not loaded or initialized
    #[error("model not loaded: {0}")]
    ModelNotLoaded(String),

    /// Failed to generate embedding
    #[error("embedding failed: {0}")]
    EmbeddingFailed(String),

    /// Input text too long
    #[error("input too long: {len} chars, max {max}")]
    InputTooLong { len: usize, max: usize },

    /// Other errors
    #[error("{0}")]
    Other(String),
}

/// Result type for embedding operations.
pub type EmbeddingResult<T> = Result<T, EmbeddingError>;

/// Trait for embedding models that can convert text to vectors.
///
/// This trait is defined in mu-daemon to avoid circular dependencies
/// between mu-daemon and mu-embeddings. Implementations live in mu-embeddings
/// or mu-cli.
///
/// # Example
///
/// ```ignore
/// use mu_daemon::embeddings::{EmbeddingModel, EmbeddingResult};
///
/// struct MyEmbedder { /* ... */ }
///
/// impl EmbeddingModel for MyEmbedder {
///     fn embed(&self, text: &str) -> EmbeddingResult<Vec<f32>> {
///         // Generate embedding vector
///         Ok(vec![0.1, 0.2, 0.3])
///     }
///
///     fn embed_batch(&self, texts: &[&str]) -> EmbeddingResult<Vec<Vec<f32>>> {
///         texts.iter().map(|t| self.embed(t)).collect()
///     }
///
///     fn dimension(&self) -> usize {
///         384
///     }
///
///     fn model_name(&self) -> &str {
///         "my-embedder"
///     }
/// }
/// ```
pub trait EmbeddingModel: Send + Sync {
    /// Generate an embedding vector for the given text.
    fn embed(&self, text: &str) -> EmbeddingResult<Vec<f32>>;

    /// Generate embeddings for multiple texts (batch operation).
    ///
    /// Default implementation calls `embed` for each text.
    fn embed_batch(&self, texts: &[&str]) -> EmbeddingResult<Vec<Vec<f32>>> {
        texts.iter().map(|t| self.embed(t)).collect()
    }

    /// Async version of embed for use in async contexts.
    ///
    /// Default implementation wraps the sync version.
    fn embed_async<'a>(
        &'a self,
        text: &'a str,
    ) -> Pin<Box<dyn Future<Output = EmbeddingResult<Vec<f32>>> + Send + 'a>> {
        Box::pin(async move { self.embed(text) })
    }

    /// Get the dimension of the embedding vectors.
    fn dimension(&self) -> usize;

    /// Get the model name/identifier.
    fn model_name(&self) -> &str;

    /// Check if the model is ready to generate embeddings.
    fn is_ready(&self) -> bool {
        true
    }
}
