//! BERT-based model for embedding generation.

use crate::error::{EmbeddingError, Result};
use crate::tokenizer::{EncodedInput, MuTokenizer};
use crate::{DEFAULT_EMBEDDING_DIM, MAX_SEQUENCE_LENGTH};
use candle_core::{DType, Device, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::bert::{BertModel, Config as BertConfig, HiddenAct};
use serde::{Deserialize, Serialize};
use std::path::Path;
use tracing::{debug, info};

/// Configuration for the mu-sigma-v2 model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelConfig {
    /// Hidden size (embedding dimension).
    pub hidden_size: usize,
    /// Number of attention heads.
    pub num_attention_heads: usize,
    /// Number of hidden layers.
    pub num_hidden_layers: usize,
    /// Intermediate size in feed-forward layers.
    pub intermediate_size: usize,
    /// Vocabulary size.
    pub vocab_size: usize,
    /// Maximum position embeddings.
    pub max_position_embeddings: usize,
    /// Hidden activation function.
    #[serde(default = "default_hidden_act")]
    pub hidden_act: String,
    /// Hidden dropout probability.
    #[serde(default = "default_dropout")]
    pub hidden_dropout_prob: f64,
    /// Attention dropout probability.
    #[serde(default = "default_dropout")]
    pub attention_probs_dropout_prob: f64,
    /// Type vocabulary size.
    #[serde(default = "default_type_vocab_size")]
    pub type_vocab_size: usize,
    /// Layer norm epsilon.
    #[serde(default = "default_layer_norm_eps")]
    pub layer_norm_eps: f64,
}

fn default_hidden_act() -> String {
    "gelu".to_string()
}

fn default_dropout() -> f64 {
    0.1
}

fn default_type_vocab_size() -> usize {
    2
}

fn default_layer_norm_eps() -> f64 {
    1e-12
}

impl Default for ModelConfig {
    fn default() -> Self {
        Self {
            hidden_size: DEFAULT_EMBEDDING_DIM,
            num_attention_heads: 12,
            num_hidden_layers: 6,
            intermediate_size: 1536,
            vocab_size: 30522,
            max_position_embeddings: MAX_SEQUENCE_LENGTH,
            hidden_act: default_hidden_act(),
            hidden_dropout_prob: default_dropout(),
            attention_probs_dropout_prob: default_dropout(),
            type_vocab_size: default_type_vocab_size(),
            layer_norm_eps: default_layer_norm_eps(),
        }
    }
}

impl ModelConfig {
    /// Load configuration from a JSON file.
    ///
    /// # Arguments
    ///
    /// * `path` - Path to config.json file
    ///
    /// # Errors
    ///
    /// Returns error if file cannot be read or parsed.
    pub fn from_file<P: AsRef<Path>>(path: P) -> Result<Self> {
        let path = path.as_ref();
        let content = std::fs::read_to_string(path)?;
        let config: Self = serde_json::from_str(&content)?;
        Ok(config)
    }

    /// Convert to candle BERT config.
    fn to_bert_config(&self) -> BertConfig {
        BertConfig {
            vocab_size: self.vocab_size,
            hidden_size: self.hidden_size,
            num_hidden_layers: self.num_hidden_layers,
            num_attention_heads: self.num_attention_heads,
            intermediate_size: self.intermediate_size,
            hidden_act: HiddenAct::Gelu,
            hidden_dropout_prob: self.hidden_dropout_prob,
            max_position_embeddings: self.max_position_embeddings,
            type_vocab_size: self.type_vocab_size,
            initializer_range: 0.02,
            layer_norm_eps: self.layer_norm_eps,
            pad_token_id: 0,
            position_embedding_type:
                candle_transformers::models::bert::PositionEmbeddingType::Absolute,
            use_cache: false,
            classifier_dropout: None,
            model_type: None,
        }
    }
}

/// Pooling strategy for generating sentence embeddings.
#[derive(Debug, Clone, Copy, Default)]
pub enum PoolingStrategy {
    /// Mean pooling over all token embeddings (default).
    #[default]
    Mean,
    /// Use the [CLS] token embedding.
    Cls,
    /// Max pooling over all token embeddings.
    Max,
}

/// MU-Sigma-V2 embedding model.
///
/// A BERT-based model for generating semantic embeddings from code and text.
pub struct MuSigmaModel {
    model: BertModel,
    tokenizer: MuTokenizer,
    config: ModelConfig,
    device: Device,
    pooling: PoolingStrategy,
}

impl MuSigmaModel {
    /// Load model from a directory containing model files.
    ///
    /// The directory should contain:
    /// - `config.json`: Model configuration
    /// - `model.safetensors` or `pytorch_model.bin`: Model weights
    /// - `tokenizer.json`: Tokenizer configuration
    ///
    /// # Arguments
    ///
    /// * `model_dir` - Path to directory containing model files
    ///
    /// # Errors
    ///
    /// Returns error if model files cannot be loaded.
    pub fn load<P: AsRef<Path>>(model_dir: P) -> Result<Self> {
        let model_dir = model_dir.as_ref();
        info!("Loading model from: {}", model_dir.display());

        // Check directory exists
        if !model_dir.exists() {
            return Err(EmbeddingError::ModelNotFound {
                path: model_dir.display().to_string(),
            });
        }

        // Load config
        let config_path = model_dir.join("config.json");
        let config =
            ModelConfig::from_file(&config_path).map_err(|e| EmbeddingError::ConfigError {
                message: format!(
                    "Failed to load config from {}: {}",
                    config_path.display(),
                    e
                ),
            })?;
        debug!("Loaded config: hidden_size={}", config.hidden_size);

        // Load tokenizer
        let tokenizer_path = model_dir.join("tokenizer.json");
        let tokenizer = MuTokenizer::from_file(&tokenizer_path)?;
        debug!("Loaded tokenizer: vocab_size={}", tokenizer.vocab_size());

        // Determine device
        let device = Self::get_device()?;
        info!("Using device: {:?}", device);

        // Load model weights
        let weights_path = model_dir.join("model.safetensors");
        let weights_path = if weights_path.exists() {
            weights_path
        } else {
            let alt_path = model_dir.join("pytorch_model.bin");
            if !alt_path.exists() {
                return Err(EmbeddingError::WeightLoadError {
                    message: format!(
                        "No weights file found. Expected model.safetensors or pytorch_model.bin in {}",
                        model_dir.display()
                    ),
                });
            }
            alt_path
        };

        let vb = Self::load_weights(&weights_path, &device)?;
        let bert_config = config.to_bert_config();
        let model =
            BertModel::load(vb, &bert_config).map_err(|e| EmbeddingError::WeightLoadError {
                message: format!("Failed to load BERT model: {}", e),
            })?;

        info!("Model loaded successfully");

        Ok(Self {
            model,
            tokenizer,
            config,
            device,
            pooling: PoolingStrategy::default(),
        })
    }

    /// Create a model with embedded weights (zero-config, single-binary deployment).
    ///
    /// This is the recommended constructor for production use. It loads the mu-sigma-v2
    /// model from weights embedded at compile time, requiring no external files.
    ///
    /// # Example
    ///
    /// ```rust,no_run
    /// use mu_embeddings::MuSigmaModel;
    ///
    /// let model = MuSigmaModel::embedded()?;
    /// let embedding = model.embed_one("def hello(): pass")?;
    /// # Ok::<(), mu_embeddings::EmbeddingError>(())
    /// ```
    ///
    /// # Errors
    ///
    /// Returns error if model cannot be loaded from embedded data.
    pub fn embedded() -> Result<Self> {
        use crate::embedded::{CONFIG_BYTES, MODEL_BYTES, TOKENIZER_BYTES};

        Self::from_embedded(
            std::str::from_utf8(CONFIG_BYTES).map_err(|e| EmbeddingError::ConfigError {
                message: format!("Invalid UTF-8 in embedded config: {}", e),
            })?,
            std::str::from_utf8(TOKENIZER_BYTES).map_err(|e| EmbeddingError::TokenizerError {
                message: format!("Invalid UTF-8 in embedded tokenizer: {}", e),
            })?,
            MODEL_BYTES,
        )
    }

    /// Create a model with embedded weights (for compile-time embedding).
    ///
    /// # Arguments
    ///
    /// * `config_json` - Model configuration as JSON string
    /// * `tokenizer_json` - Tokenizer configuration as JSON string
    /// * `weights` - Safetensors weights as bytes
    ///
    /// # Errors
    ///
    /// Returns error if model cannot be created.
    pub fn from_embedded(config_json: &str, tokenizer_json: &str, weights: &[u8]) -> Result<Self> {
        info!("Loading model from embedded data");

        // Parse config
        let config: ModelConfig = serde_json::from_str(config_json)?;
        debug!("Loaded config: hidden_size={}", config.hidden_size);

        // Load tokenizer
        let tokenizer = MuTokenizer::from_json(tokenizer_json)?;
        debug!("Loaded tokenizer: vocab_size={}", tokenizer.vocab_size());

        // Determine device
        let device = Self::get_device()?;
        info!("Using device: {:?}", device);

        // Load weights from bytes
        let vb = Self::load_weights_from_bytes(weights, &device)?;
        let bert_config = config.to_bert_config();
        let model =
            BertModel::load(vb, &bert_config).map_err(|e| EmbeddingError::WeightLoadError {
                message: format!("Failed to load BERT model: {}", e),
            })?;

        info!("Model loaded successfully");

        Ok(Self {
            model,
            tokenizer,
            config,
            device,
            pooling: PoolingStrategy::default(),
        })
    }

    /// Set the pooling strategy for embedding generation.
    ///
    /// # Arguments
    ///
    /// * `strategy` - Pooling strategy to use
    pub fn with_pooling(mut self, strategy: PoolingStrategy) -> Self {
        self.pooling = strategy;
        self
    }

    /// Generate embeddings for a slice of texts.
    ///
    /// # Arguments
    ///
    /// * `texts` - Slice of text strings to embed
    ///
    /// # Returns
    ///
    /// Vector of embeddings, one per input text. Each embedding has dimension
    /// equal to `hidden_size` (384 for mu-sigma-v2).
    ///
    /// # Errors
    ///
    /// Returns error if encoding or inference fails.
    pub fn embed(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Err(EmbeddingError::EmptyInput);
        }

        debug!("Embedding {} texts", texts.len());

        // Tokenize all inputs
        let encodings = self.tokenizer.encode_batch(texts)?;

        // Convert to tensors
        let (input_ids, attention_mask, token_type_ids) = self.encodings_to_tensors(&encodings)?;

        // Forward pass
        let output = self
            .model
            .forward(&input_ids, &token_type_ids, Some(&attention_mask))
            .map_err(|e| EmbeddingError::InferenceError {
                message: format!("Forward pass failed: {}", e),
            })?;

        // Pool embeddings
        let pooled = self.pool_embeddings(&output, &attention_mask)?;

        // Convert to Vec<Vec<f32>>
        self.tensor_to_vecs(&pooled)
    }

    /// Generate embedding for a single text.
    ///
    /// # Arguments
    ///
    /// * `text` - Text to embed
    ///
    /// # Returns
    ///
    /// Embedding vector with dimension equal to `hidden_size`.
    ///
    /// # Errors
    ///
    /// Returns error if encoding or inference fails.
    pub fn embed_one(&self, text: &str) -> Result<Vec<f32>> {
        let embeddings = self.embed(&[text])?;
        Ok(embeddings.into_iter().next().unwrap())
    }

    /// Get the embedding dimension.
    pub fn embedding_dim(&self) -> usize {
        self.config.hidden_size
    }

    /// Get the model configuration.
    pub fn config(&self) -> &ModelConfig {
        &self.config
    }

    /// Get the device being used for inference.
    pub fn device(&self) -> &Device {
        &self.device
    }

    // Private helper methods

    fn get_device() -> Result<Device> {
        // Try CUDA first
        #[cfg(feature = "cuda")]
        {
            if let Ok(device) = Device::new_cuda(0) {
                return Ok(device);
            }
        }

        // Try Metal on Apple Silicon
        #[cfg(feature = "metal")]
        {
            if let Ok(device) = Device::new_metal(0) {
                return Ok(device);
            }
        }

        // Fall back to CPU
        Ok(Device::Cpu)
    }

    fn load_weights<P: AsRef<Path>>(path: P, device: &Device) -> Result<VarBuilder<'static>> {
        let path = path.as_ref();
        debug!("Loading weights from: {}", path.display());

        if path.extension().map_or(false, |ext| ext == "safetensors") {
            let data = std::fs::read(path)?;
            let tensors = candle_core::safetensors::load_buffer(&data, device).map_err(|e| {
                EmbeddingError::WeightLoadError {
                    message: format!("Failed to load safetensors: {}", e),
                }
            })?;
            Ok(VarBuilder::from_tensors(tensors, DType::F32, device))
        } else {
            Err(EmbeddingError::WeightLoadError {
                message: "Only safetensors format is supported".to_string(),
            })
        }
    }

    fn load_weights_from_bytes(data: &[u8], device: &Device) -> Result<VarBuilder<'static>> {
        debug!("Loading weights from bytes ({} bytes)", data.len());
        let tensors = candle_core::safetensors::load_buffer(data, device).map_err(|e| {
            EmbeddingError::WeightLoadError {
                message: format!("Failed to load safetensors from bytes: {}", e),
            }
        })?;
        Ok(VarBuilder::from_tensors(tensors, DType::F32, device))
    }

    fn encodings_to_tensors(&self, encodings: &[EncodedInput]) -> Result<(Tensor, Tensor, Tensor)> {
        let batch_size = encodings.len();
        let seq_len = encodings[0].input_ids.len();

        // Flatten all encodings into contiguous arrays
        let mut input_ids_flat = Vec::with_capacity(batch_size * seq_len);
        let mut attention_mask_flat = Vec::with_capacity(batch_size * seq_len);
        let mut token_type_ids_flat = Vec::with_capacity(batch_size * seq_len);

        for encoding in encodings {
            input_ids_flat.extend(encoding.input_ids.iter().map(|&x| x as i64));
            attention_mask_flat.extend(encoding.attention_mask.iter().map(|&x| x as i64));
            token_type_ids_flat.extend(encoding.token_type_ids.iter().map(|&x| x as i64));
        }

        let shape = (batch_size, seq_len);

        let input_ids = Tensor::from_vec(input_ids_flat, shape, &self.device)?;
        let attention_mask = Tensor::from_vec(attention_mask_flat, shape, &self.device)?;
        let token_type_ids = Tensor::from_vec(token_type_ids_flat, shape, &self.device)?;

        Ok((input_ids, attention_mask, token_type_ids))
    }

    fn pool_embeddings(&self, hidden_states: &Tensor, attention_mask: &Tensor) -> Result<Tensor> {
        match self.pooling {
            PoolingStrategy::Cls => {
                // Take the first token ([CLS]) embedding
                hidden_states
                    .narrow(1, 0, 1)?
                    .squeeze(1)
                    .map_err(Into::into)
            }
            PoolingStrategy::Mean => {
                // Mean pooling: sum(hidden_states * mask) / sum(mask)
                let mask = attention_mask.unsqueeze(2)?.to_dtype(DType::F32)?;
                let masked = hidden_states.broadcast_mul(&mask)?;
                let sum = masked.sum(1)?;
                let count = mask.sum(1)?;
                sum.broadcast_div(&count).map_err(Into::into)
            }
            PoolingStrategy::Max => {
                // Max pooling over sequence dimension
                // Set padding positions to large negative value before max
                let mask = attention_mask.unsqueeze(2)?.to_dtype(DType::F32)?;
                let neg_inf = Tensor::new(-1e9f32, &self.device)?;
                let inverse_mask = mask.neg()?.add(&Tensor::new(1.0f32, &self.device)?)?;
                let masked = hidden_states.add(&inverse_mask.broadcast_mul(&neg_inf)?)?;
                masked.max(1).map_err(Into::into)
            }
        }
    }

    fn tensor_to_vecs(&self, tensor: &Tensor) -> Result<Vec<Vec<f32>>> {
        let (batch_size, hidden_size) =
            tensor.dims2().map_err(|e| EmbeddingError::TensorError {
                message: format!("Unexpected tensor shape: {}", e),
            })?;

        // Flatten the 2D tensor to 1D for extraction
        let flat: Vec<f32> =
            tensor
                .flatten_all()?
                .to_vec1()
                .map_err(|e| EmbeddingError::TensorError {
                    message: format!("Failed to convert tensor to vec: {}", e),
                })?;

        // Reshape flat vector into batch of embeddings
        let mut result = Vec::with_capacity(batch_size);
        for i in 0..batch_size {
            let start = i * hidden_size;
            let end = start + hidden_size;
            result.push(flat[start..end].to_vec());
        }

        Ok(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_model_config_default() {
        let config = ModelConfig::default();
        assert_eq!(config.hidden_size, 384);
        assert_eq!(config.num_hidden_layers, 6);
        assert_eq!(config.num_attention_heads, 12);
    }

    #[test]
    fn test_model_config_serde() {
        let json = r#"{
            "hidden_size": 384,
            "num_attention_heads": 12,
            "num_hidden_layers": 6,
            "intermediate_size": 1536,
            "vocab_size": 30522,
            "max_position_embeddings": 512
        }"#;

        let config: ModelConfig = serde_json::from_str(json).unwrap();
        assert_eq!(config.hidden_size, 384);
        assert_eq!(config.num_hidden_layers, 6);
    }

    #[test]
    fn test_pooling_strategy_default() {
        let strategy = PoolingStrategy::default();
        assert!(matches!(strategy, PoolingStrategy::Mean));
    }
}
