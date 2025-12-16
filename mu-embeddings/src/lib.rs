//! MU Embeddings - Native embedding inference for semantic search.
//!
//! This crate provides high-performance embedding generation using the mu-sigma-v2 model,
//! a BERT-based model optimized for code understanding and semantic search.
//!
//! # Features
//!
//! - **Native inference**: No Python dependency, pure Rust using Candle
//! - **CPU and GPU support**: Works on CPU by default, with optional CUDA/Metal acceleration
//! - **Batch processing**: Efficient batched embedding generation
//! - **Compile-time model embedding**: Model weights can be embedded at compile time
//!
//! # Usage
//!
//! ```rust,no_run
//! use mu_embeddings::MuSigmaModel;
//!
//! // Load model from embedded weights (zero-config)
//! let model = MuSigmaModel::embedded()?;
//!
//! // Or load from files
//! let model = MuSigmaModel::load("path/to/model")?;
//!
//! // Generate embeddings
//! let texts = vec!["def hello(): pass", "function greet() {}"];
//! let embeddings = model.embed(&texts)?;
//!
//! // Each embedding is a Vec<f32> with dimension 384 (for mu-sigma-v2)
//! assert_eq!(embeddings[0].len(), 384);
//! # Ok::<(), mu_embeddings::EmbeddingError>(())
//! ```

#![warn(missing_docs)]
#![warn(clippy::all)]

mod error;
mod model;
mod tokenizer;

pub use error::{EmbeddingError, Result};
pub use model::{ModelConfig, MuSigmaModel};
pub use tokenizer::MuTokenizer;

/// Embedded model weights for mu-sigma-v2 (compile-time inclusion).
pub mod embedded {
    /// Model weights (safetensors format).
    pub const MODEL_BYTES: &[u8] = include_bytes!("../models/mu-sigma-v2/model.safetensors");

    /// Model configuration (JSON).
    pub const CONFIG_BYTES: &[u8] = include_bytes!("../models/mu-sigma-v2/config.json");

    /// Tokenizer configuration (JSON).
    pub const TOKENIZER_BYTES: &[u8] = include_bytes!("../models/mu-sigma-v2/tokenizer.json");
}

/// Default embedding dimension for mu-sigma-v2 model.
pub const DEFAULT_EMBEDDING_DIM: usize = 384;

/// Maximum sequence length supported by the model.
pub const MAX_SEQUENCE_LENGTH: usize = 512;

/// Model name for mu-sigma-v2.
pub const MODEL_NAME: &str = "mu-sigma-v2";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_constants() {
        assert_eq!(DEFAULT_EMBEDDING_DIM, 384);
        assert_eq!(MAX_SEQUENCE_LENGTH, 512);
        assert_eq!(MODEL_NAME, "mu-sigma-v2");
    }
}
