//! Tokenizer wrapper for mu-sigma-v2 model.

use crate::error::{EmbeddingError, Result};
use crate::MAX_SEQUENCE_LENGTH;
use std::path::Path;
use tokenizers::Tokenizer;

/// Wrapper around HuggingFace tokenizer for mu-sigma-v2.
pub struct MuTokenizer {
    tokenizer: Tokenizer,
    max_length: usize,
}

/// Encoded input ready for model inference.
#[derive(Debug, Clone)]
pub struct EncodedInput {
    /// Token IDs.
    pub input_ids: Vec<u32>,
    /// Attention mask (1 for real tokens, 0 for padding).
    pub attention_mask: Vec<u32>,
    /// Token type IDs (all 0 for single sequence).
    pub token_type_ids: Vec<u32>,
}

impl MuTokenizer {
    /// Load tokenizer from a file path.
    ///
    /// # Arguments
    ///
    /// * `path` - Path to tokenizer.json file
    ///
    /// # Errors
    ///
    /// Returns error if tokenizer file cannot be loaded.
    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<Self> {
        let path = path.as_ref();
        if !path.exists() {
            return Err(EmbeddingError::TokenizerError {
                message: format!("Tokenizer file not found: {}", path.display()),
            });
        }

        let tokenizer = Tokenizer::from_file(path)?;

        Ok(Self {
            tokenizer,
            max_length: MAX_SEQUENCE_LENGTH,
        })
    }

    /// Load tokenizer from JSON string.
    ///
    /// # Arguments
    ///
    /// * `json` - JSON string containing tokenizer configuration
    ///
    /// # Errors
    ///
    /// Returns error if JSON is invalid.
    pub fn from_json(json: &str) -> Result<Self> {
        let tokenizer =
            Tokenizer::from_bytes(json.as_bytes()).map_err(|e| EmbeddingError::TokenizerError {
                message: format!("Failed to parse tokenizer JSON: {}", e),
            })?;

        Ok(Self {
            tokenizer,
            max_length: MAX_SEQUENCE_LENGTH,
        })
    }

    /// Set maximum sequence length for tokenization.
    ///
    /// # Arguments
    ///
    /// * `max_length` - Maximum number of tokens (default: 512)
    pub fn with_max_length(mut self, max_length: usize) -> Self {
        self.max_length = max_length;
        self
    }

    /// Encode a single text into tokens.
    ///
    /// # Arguments
    ///
    /// * `text` - Text to encode
    ///
    /// # Returns
    ///
    /// EncodedInput with token IDs, attention mask, and token type IDs.
    ///
    /// # Errors
    ///
    /// Returns error if encoding fails.
    pub fn encode(&self, text: &str) -> Result<EncodedInput> {
        let encoding =
            self.tokenizer
                .encode(text, true)
                .map_err(|e| EmbeddingError::TokenizerError {
                    message: format!("Encoding failed: {}", e),
                })?;

        let mut input_ids: Vec<u32> = encoding.get_ids().to_vec();
        let mut attention_mask: Vec<u32> = encoding.get_attention_mask().to_vec();
        let mut token_type_ids: Vec<u32> = encoding.get_type_ids().to_vec();

        // Truncate if too long
        if input_ids.len() > self.max_length {
            input_ids.truncate(self.max_length);
            attention_mask.truncate(self.max_length);
            token_type_ids.truncate(self.max_length);
        }

        Ok(EncodedInput {
            input_ids,
            attention_mask,
            token_type_ids,
        })
    }

    /// Encode multiple texts into tokens with padding.
    ///
    /// # Arguments
    ///
    /// * `texts` - Slice of texts to encode
    ///
    /// # Returns
    ///
    /// Vector of EncodedInputs, all padded to the same length.
    ///
    /// # Errors
    ///
    /// Returns error if encoding fails for any text.
    pub fn encode_batch(&self, texts: &[&str]) -> Result<Vec<EncodedInput>> {
        if texts.is_empty() {
            return Err(EmbeddingError::EmptyInput);
        }

        // Encode all texts
        let mut encodings: Vec<EncodedInput> = texts
            .iter()
            .map(|text| self.encode(text))
            .collect::<Result<Vec<_>>>()?;

        // Find max length for padding
        let max_len = encodings
            .iter()
            .map(|e| e.input_ids.len())
            .max()
            .unwrap_or(0)
            .min(self.max_length);

        // Pad all sequences to max length
        for encoding in &mut encodings {
            let current_len = encoding.input_ids.len();
            if current_len < max_len {
                let padding_len = max_len - current_len;
                // Pad with 0 (PAD token)
                encoding.input_ids.extend(vec![0u32; padding_len]);
                encoding.attention_mask.extend(vec![0u32; padding_len]);
                encoding.token_type_ids.extend(vec![0u32; padding_len]);
            }
        }

        Ok(encodings)
    }

    /// Get the vocabulary size.
    pub fn vocab_size(&self) -> usize {
        self.tokenizer.get_vocab_size(true)
    }

    /// Get the maximum sequence length.
    pub fn max_length(&self) -> usize {
        self.max_length
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_encoded_input_fields() {
        let input = EncodedInput {
            input_ids: vec![101, 2023, 2003, 1037, 3231, 102],
            attention_mask: vec![1, 1, 1, 1, 1, 1],
            token_type_ids: vec![0, 0, 0, 0, 0, 0],
        };

        assert_eq!(input.input_ids.len(), 6);
        assert_eq!(input.attention_mask.len(), 6);
        assert_eq!(input.token_type_ids.len(), 6);
    }
}
