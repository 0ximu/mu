# MU-Sigma-V2 Model Files

This directory should contain the mu-sigma-v2 model files for native embedding inference.

## Required Files

1. **config.json** - Model configuration (included)
2. **tokenizer.json** - HuggingFace tokenizer configuration
3. **model.safetensors** - Model weights in safetensors format

## How to Obtain Model Files

### Option 1: Download Pre-trained Model

```bash
# Download from HuggingFace (when available)
# huggingface-cli download dominaite/mu-sigma-v2 --local-dir .
```

### Option 2: Convert from PyTorch

If you have a PyTorch checkpoint:

```bash
# Install safetensors
pip install safetensors

# Convert weights
python -c "
from safetensors.torch import save_file
import torch

# Load your PyTorch model
state_dict = torch.load('pytorch_model.bin')
save_file(state_dict, 'model.safetensors')
"
```

### Option 3: Use Base BERT Model (for development)

For development/testing, you can use any BERT-like model with 384 hidden dimensions:

```bash
# Download a small BERT model
huggingface-cli download google/bert_uncased_L-6_H-384_A-12 --local-dir .
```

## File Descriptions

### config.json

Contains model architecture configuration:
- `hidden_size`: 384 (embedding dimension)
- `num_hidden_layers`: 6
- `num_attention_heads`: 12
- `intermediate_size`: 1536
- `vocab_size`: 30522
- `max_position_embeddings`: 512

### tokenizer.json

HuggingFace tokenizer configuration file. Should be compatible with BERT tokenization.

### model.safetensors

Model weights in safetensors format. This is the preferred format for:
- Faster loading
- Memory-mapped access
- Better security (no pickle)

## Embedding at Compile Time

For production use, model files can be embedded at compile time:

```rust
// In your build.rs or main code
const CONFIG: &str = include_str!("models/mu-sigma-v2/config.json");
const TOKENIZER: &str = include_str!("models/mu-sigma-v2/tokenizer.json");
const WEIGHTS: &[u8] = include_bytes!("models/mu-sigma-v2/model.safetensors");

let model = MuSigmaModel::from_embedded(CONFIG, TOKENIZER, WEIGHTS)?;
```

Note: This increases binary size by ~50MB but eliminates runtime file dependencies.
