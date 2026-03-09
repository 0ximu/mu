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

/// Result of encoding with a token budget.
#[derive(Debug, Clone)]
pub struct BudgetEncoding {
    /// The encoded tokens (possibly truncated to fit the budget).
    pub encoded: EncodedInput,
    /// Actual token count after encoding.
    pub token_count: usize,
    /// Whether the input was truncated to fit.
    pub truncated: bool,
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

    /// Estimate the number of tokens in a text without allocating a full EncodedInput.
    ///
    /// Falls back to a heuristic (len / 4) if tokenization fails.
    pub fn estimate_tokens(&self, text: &str) -> usize {
        self.tokenizer
            .encode(text, false)
            .map(|enc| enc.get_ids().len())
            .unwrap_or(text.len() / 4)
    }

    /// Encode text with a token budget, truncating the input string to fit.
    ///
    /// Uses binary search on the char boundary to find the longest prefix
    /// that fits within `token_budget` tokens, then returns the encoded
    /// result and whether truncation occurred.
    pub fn encode_with_budget(&self, text: &str, token_budget: usize) -> Result<BudgetEncoding> {
        // Fast path: text already fits
        let full_tokens = self.estimate_tokens(text);
        if full_tokens <= token_budget {
            let encoded = self.encode(text)?;
            return Ok(BudgetEncoding {
                encoded,
                token_count: full_tokens,
                truncated: false,
            });
        }

        // Binary search for the longest char prefix that fits within budget.
        // Start with a proportional estimate to narrow the range quickly.
        let char_count = text.chars().count();
        let ratio = token_budget as f64 / full_tokens.max(1) as f64;
        let estimate = ((char_count as f64) * ratio * 0.95) as usize; // slightly conservative

        let mut lo = estimate.min(char_count).saturating_sub(50);
        let mut hi = (estimate + 50).min(char_count);

        // Verify bounds: lo must fit, hi must exceed (or we widen)
        let lo_text: String = text.chars().take(lo).collect();
        if self.estimate_tokens(&lo_text) > token_budget {
            lo = 0;
        }
        let hi_text: String = text.chars().take(hi).collect();
        if self.estimate_tokens(&hi_text) <= token_budget {
            hi = char_count;
        }

        while lo + 1 < hi {
            let mid = (lo + hi) / 2;
            let prefix: String = text.chars().take(mid).collect();
            if self.estimate_tokens(&prefix) <= token_budget {
                lo = mid;
            } else {
                hi = mid;
            }
        }

        let truncated_text: String = text.chars().take(lo).collect();
        let token_count = self.estimate_tokens(&truncated_text);
        let encoded = self.encode(&truncated_text)?;

        Ok(BudgetEncoding {
            encoded,
            token_count,
            truncated: true,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn load_tokenizer() -> MuTokenizer {
        let json = std::str::from_utf8(crate::embedded::TOKENIZER_BYTES).unwrap();
        MuTokenizer::from_json(json).unwrap()
    }

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

    #[test]
    fn test_estimate_tokens_returns_reasonable_values() {
        let tok = load_tokenizer();
        // Short text
        let count = tok.estimate_tokens("fn hello() {}");
        assert!(count > 0 && count < 20, "got {} tokens", count);

        // Longer text should have more tokens
        let long = "function ".repeat(100);
        let long_count = tok.estimate_tokens(&long);
        assert!(long_count > count);
    }

    #[test]
    fn test_estimate_tokens_empty_string() {
        let tok = load_tokenizer();
        let count = tok.estimate_tokens("");
        // Might be 0 or a small number for special tokens; just shouldn't panic
        assert!(count <= 2);
    }

    #[test]
    fn test_encode_with_budget_no_truncation() {
        let tok = load_tokenizer();
        let result = tok.encode_with_budget("fn hello() {}", 480).unwrap();
        assert!(!result.truncated);
        assert!(result.token_count <= 480);
        assert!(!result.encoded.input_ids.is_empty());
    }

    #[test]
    fn test_encode_with_budget_truncates() {
        let tok = load_tokenizer();
        let long_text = "fn process_data() { let x = 42; } ".repeat(200);
        let result = tok.encode_with_budget(&long_text, 50).unwrap();
        assert!(result.truncated);
        assert!(result.token_count <= 50, "got {} tokens", result.token_count);
    }

    #[test]
    fn test_encode_with_budget_binary_search_converges() {
        let tok = load_tokenizer();
        // Test with various budgets to ensure binary search works
        for budget in [10, 50, 100, 200, 480] {
            let text = "impl Iterator for MyStruct { fn next(&mut self) -> Option<Self::Item> { None } } ".repeat(50);
            let result = tok.encode_with_budget(&text, budget).unwrap();
            assert!(
                result.token_count <= budget,
                "budget={}, got {} tokens",
                budget,
                result.token_count
            );
        }
    }
}
