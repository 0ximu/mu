//! Error types for mu-embeddings.

use thiserror::Error;

/// Result type alias for mu-embeddings operations.
pub type Result<T> = std::result::Result<T, EmbeddingError>;

/// Errors that can occur during embedding operations.
#[derive(Error, Debug)]
pub enum EmbeddingError {
    /// Model file not found at the specified path.
    #[error("Model file not found: {path}")]
    ModelNotFound {
        /// Path that was searched for the model.
        path: String,
    },

    /// Tokenizer file not found or invalid.
    #[error("Tokenizer error: {message}")]
    TokenizerError {
        /// Description of the tokenizer error.
        message: String,
    },

    /// Error loading model weights.
    #[error("Failed to load model weights: {message}")]
    WeightLoadError {
        /// Description of the weight loading error.
        message: String,
    },

    /// Error during model inference.
    #[error("Inference error: {message}")]
    InferenceError {
        /// Description of the inference error.
        message: String,
    },

    /// Invalid model configuration.
    #[error("Invalid model configuration: {message}")]
    ConfigError {
        /// Description of the configuration error.
        message: String,
    },

    /// Input text exceeds maximum sequence length.
    #[error("Input too long: {length} tokens exceeds maximum {max_length}")]
    InputTooLong {
        /// Actual length of the input.
        length: usize,
        /// Maximum allowed length.
        max_length: usize,
    },

    /// Empty input provided.
    #[error("Empty input: at least one text must be provided")]
    EmptyInput,

    /// Device error (CUDA/Metal not available).
    #[error("Device error: {message}")]
    DeviceError {
        /// Description of the device error.
        message: String,
    },

    /// IO error reading model files.
    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),

    /// JSON parsing error for config files.
    #[error("JSON parse error: {0}")]
    JsonError(#[from] serde_json::Error),

    /// Candle tensor operation error.
    #[error("Tensor error: {message}")]
    TensorError {
        /// Description of the tensor error.
        message: String,
    },
}

impl From<candle_core::Error> for EmbeddingError {
    fn from(err: candle_core::Error) -> Self {
        EmbeddingError::TensorError {
            message: err.to_string(),
        }
    }
}

impl From<tokenizers::Error> for EmbeddingError {
    fn from(err: tokenizers::Error) -> Self {
        EmbeddingError::TokenizerError {
            message: err.to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_display() {
        let err = EmbeddingError::ModelNotFound {
            path: "/path/to/model".to_string(),
        };
        assert!(err.to_string().contains("/path/to/model"));

        let err = EmbeddingError::InputTooLong {
            length: 1000,
            max_length: 512,
        };
        assert!(err.to_string().contains("1000"));
        assert!(err.to_string().contains("512"));
    }
}
