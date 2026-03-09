//! UniXcoder embedding quality spike test.
//!
//! Compares microsoft/unixcoder-base against mu-sigma-v2 on code-related
//! semantic similarity pairs. Uses Candle's XLMRobertaModel since UniXcoder
//! is RoBERTa-based.

use candle_core::{DType, Device, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::xlm_roberta::{Config as XLMConfig, XLMRobertaModel};
use mu_embeddings::{MuSigmaModel, MuTokenizer};
use std::path::Path;

// ---------- test data ----------

const TEST_STRINGS: &[&str] = &[
    "soft delete query",
    "user.DeletedAt = DateTime.UtcNow",
    "authentication middleware",
    "app.UseAuthentication()",
    "database connection pool",
    "new SqlConnection(connectionString)",
    "error handling pattern",
    "try { } catch (Exception ex) { logger.LogError(ex); }",
    "unit test assertion",
    "Assert.Equal(expected, actual)",
];

const PAIRS: &[(usize, usize)] = &[(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)];

// ---------- helpers ----------

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    dot / (norm_a * norm_b)
}

fn mean_pool(hidden_states: &Tensor, attention_mask: &Tensor) -> anyhow::Result<Tensor> {
    let mask = attention_mask.unsqueeze(2)?.to_dtype(DType::F32)?;
    let masked = hidden_states.broadcast_mul(&mask)?;
    let sum = masked.sum(1)?;
    let count = mask.sum(1)?;
    Ok(sum.broadcast_div(&count)?)
}

// ---------- UniXcoder loading ----------

struct UniXcoderModel {
    model: XLMRobertaModel,
    tokenizer: MuTokenizer,
    device: Device,
}

impl UniXcoderModel {
    fn load(model_dir: &Path) -> anyhow::Result<Self> {
        let device = Device::Cpu;

        // Load config
        let config_str = std::fs::read_to_string(model_dir.join("config.json"))?;
        let raw: serde_json::Value = serde_json::from_str(&config_str)?;

        let config = XLMConfig {
            hidden_size: raw["hidden_size"].as_u64().unwrap() as usize,
            layer_norm_eps: raw["layer_norm_eps"].as_f64().unwrap(),
            attention_probs_dropout_prob: raw["attention_probs_dropout_prob"].as_f64().unwrap()
                as f32,
            hidden_dropout_prob: raw["hidden_dropout_prob"].as_f64().unwrap() as f32,
            num_attention_heads: raw["num_attention_heads"].as_u64().unwrap() as usize,
            position_embedding_type: raw["position_embedding_type"]
                .as_str()
                .unwrap_or("absolute")
                .to_string(),
            intermediate_size: raw["intermediate_size"].as_u64().unwrap() as usize,
            hidden_act: candle_nn::Activation::Gelu,
            num_hidden_layers: raw["num_hidden_layers"].as_u64().unwrap() as usize,
            vocab_size: raw["vocab_size"].as_u64().unwrap() as usize,
            max_position_embeddings: raw["max_position_embeddings"].as_u64().unwrap() as usize,
            type_vocab_size: raw["type_vocab_size"].as_u64().unwrap() as usize,
            pad_token_id: raw["pad_token_id"].as_u64().unwrap_or(1) as u32,
        };

        // Load tokenizer
        let tokenizer = MuTokenizer::from_file(model_dir.join("tokenizer.json"))?;

        // Load weights
        let weights_path = model_dir.join("model.safetensors");
        let data = std::fs::read(&weights_path)?;
        let tensors = candle_core::safetensors::load_buffer(&data, &device)?;
        let vb = VarBuilder::from_tensors(tensors, DType::F32, &device);

        let model = XLMRobertaModel::new(&config, vb)?;

        Ok(Self {
            model,
            tokenizer,
            device,
        })
    }

    fn embed(&self, texts: &[&str]) -> anyhow::Result<Vec<Vec<f32>>> {
        let encodings = self.tokenizer.encode_batch(texts)?;

        let batch_size = encodings.len();
        let seq_len = encodings[0].input_ids.len();
        let shape = (batch_size, seq_len);

        let mut ids_flat = Vec::with_capacity(batch_size * seq_len);
        let mut mask_flat = Vec::with_capacity(batch_size * seq_len);
        let mut types_flat = Vec::with_capacity(batch_size * seq_len);

        for enc in &encodings {
            ids_flat.extend(enc.input_ids.iter().map(|&x| x as i64));
            mask_flat.extend(enc.attention_mask.iter().map(|&x| x as i64));
            types_flat.extend(enc.token_type_ids.iter().map(|&x| x as i64));
        }

        let input_ids = Tensor::from_vec(ids_flat, shape, &self.device)?;
        let attention_mask = Tensor::from_vec(mask_flat.clone(), shape, &self.device)?;
        let token_type_ids = Tensor::from_vec(types_flat, shape, &self.device)?;

        let hidden = self.model.forward(
            &input_ids,
            &attention_mask,
            &token_type_ids,
            None,
            None,
            None,
        )?;

        let mask_tensor = Tensor::from_vec(mask_flat, shape, &self.device)?;
        let pooled = mean_pool(&hidden, &mask_tensor)?;

        // Convert to vecs
        let flat: Vec<f32> = pooled.flatten_all()?.to_vec1()?;
        let dim = flat.len() / batch_size;
        let mut result = Vec::with_capacity(batch_size);
        for i in 0..batch_size {
            result.push(flat[i * dim..(i + 1) * dim].to_vec());
        }
        Ok(result)
    }
}

// ---------- main ----------

fn main() -> anyhow::Result<()> {
    println!("=== UniXcoder Embedding Quality Spike ===\n");

    // Load mu-sigma-v2
    let mu_sigma_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("models/mu-sigma-v2");
    println!("Loading mu-sigma-v2 from {} ...", mu_sigma_dir.display());
    let mu_sigma = MuSigmaModel::load(&mu_sigma_dir)?;
    println!(
        "  mu-sigma-v2: dim={}, loaded OK\n",
        mu_sigma.embedding_dim()
    );

    // Load UniXcoder
    let unixcoder_dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("models/unixcoder-base");
    println!("Loading UniXcoder from {} ...", unixcoder_dir.display());
    let unixcoder = UniXcoderModel::load(&unixcoder_dir)?;
    println!("  UniXcoder: dim=768, loaded OK\n");

    // Embed with mu-sigma-v2
    println!("Embedding {} test strings with mu-sigma-v2...", TEST_STRINGS.len());
    let mu_embeddings = mu_sigma.embed(TEST_STRINGS)?;
    println!("  Done.\n");

    // Embed with UniXcoder
    println!("Embedding {} test strings with UniXcoder...", TEST_STRINGS.len());
    let ux_embeddings = unixcoder.embed(TEST_STRINGS)?;
    println!("  Done.\n");

    // Compare
    println!(
        "{:<55} {:>12} {:>12} {:>8}",
        "Pair", "mu-sigma-v2", "UniXcoder", "Delta"
    );
    println!("{}", "-".repeat(90));

    let mut mu_total = 0.0f32;
    let mut ux_total = 0.0f32;

    for &(a, b) in PAIRS {
        let mu_sim = cosine_similarity(&mu_embeddings[a], &mu_embeddings[b]);
        let ux_sim = cosine_similarity(&ux_embeddings[a], &ux_embeddings[b]);
        let delta = ux_sim - mu_sim;

        mu_total += mu_sim;
        ux_total += ux_sim;

        let label = format!("\"{}\" vs \"{}\"", TEST_STRINGS[a], TEST_STRINGS[b]);
        let label_truncated = if label.len() > 53 {
            format!("{}...", &label[..50])
        } else {
            label
        };

        println!(
            "{:<55} {:>12.4} {:>12.4} {:>+8.4}",
            label_truncated, mu_sim, ux_sim, delta
        );
    }

    let n = PAIRS.len() as f32;
    let mu_avg = mu_total / n;
    let ux_avg = ux_total / n;
    let avg_delta = ux_avg - mu_avg;

    println!("{}", "-".repeat(90));
    println!(
        "{:<55} {:>12.4} {:>12.4} {:>+8.4}",
        "AVERAGE", mu_avg, ux_avg, avg_delta
    );

    // Also compute cross-pair similarities (negative pairs) for discrimination
    println!("\n--- Negative pairs (should be LOW similarity) ---");
    println!(
        "{:<55} {:>12} {:>12}",
        "Pair", "mu-sigma-v2", "UniXcoder"
    );
    println!("{}", "-".repeat(82));

    // Compare each description with a non-matching code snippet
    let neg_pairs = &[(0, 3), (2, 5), (4, 7), (6, 9), (8, 1)];
    let mut mu_neg_total = 0.0f32;
    let mut ux_neg_total = 0.0f32;

    for &(a, b) in neg_pairs {
        let mu_sim = cosine_similarity(&mu_embeddings[a], &mu_embeddings[b]);
        let ux_sim = cosine_similarity(&ux_embeddings[a], &ux_embeddings[b]);

        mu_neg_total += mu_sim;
        ux_neg_total += ux_sim;

        let label = format!("\"{}\" vs \"{}\"", TEST_STRINGS[a], TEST_STRINGS[b]);
        let label_truncated = if label.len() > 53 {
            format!("{}...", &label[..50])
        } else {
            label
        };

        println!(
            "{:<55} {:>12.4} {:>12.4}",
            label_truncated, mu_sim, ux_sim
        );
    }

    let mu_neg_avg = mu_neg_total / neg_pairs.len() as f32;
    let ux_neg_avg = ux_neg_total / neg_pairs.len() as f32;

    println!("{}", "-".repeat(82));
    println!(
        "{:<55} {:>12.4} {:>12.4}",
        "AVG NEGATIVE", mu_neg_avg, ux_neg_avg
    );

    // Discrimination = positive avg - negative avg
    let mu_disc = mu_avg - mu_neg_avg;
    let ux_disc = ux_avg - ux_neg_avg;

    println!("\n--- Summary ---");
    println!("mu-sigma-v2:  pos_avg={:.4}, neg_avg={:.4}, discrimination={:.4}", mu_avg, mu_neg_avg, mu_disc);
    println!("UniXcoder:    pos_avg={:.4}, neg_avg={:.4}, discrimination={:.4}", ux_avg, ux_neg_avg, ux_disc);
    println!("Delta (UniXcoder - mu-sigma-v2): pos={:+.4}, disc={:+.4}", avg_delta, ux_disc - mu_disc);

    println!("\n--- Recommendation ---");
    if avg_delta > 0.05 {
        println!("GO: UniXcoder is consistently >0.05 better on code pairs.");
        println!("Recommend swapping mu-sigma-v2 for UniXcoder.");
    } else if avg_delta > 0.0 {
        println!("MAYBE: UniXcoder is slightly better ({:+.4}) but under 0.05 threshold.", avg_delta);
        println!("Consider if the 4x model size (501MB vs 91MB) is worth the marginal gain.");
    } else {
        println!("NO-GO: UniXcoder is not better than mu-sigma-v2 on these pairs ({:+.4}).", avg_delta);
        println!("Stick with mu-sigma-v2.");
    }

    Ok(())
}
