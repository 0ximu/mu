# UniXcoder Embedding Quality Spike Results

**Date**: 2026-03-09
**Branch**: spike/unixcoder
**Verdict**: NO-GO

## Models Compared

| Property | mu-sigma-v2 | UniXcoder-base |
|----------|-------------|----------------|
| Architecture | BERT (6-layer) | RoBERTa (12-layer) |
| Hidden dim | 384 | 768 |
| Vocab size | 30,522 | 51,416 |
| Model size | 91 MB | 501 MB |
| Candle module | `models::bert::BertModel` | `models::xlm_roberta::XLMRobertaModel` |

## Candle Compatibility

UniXcoder loads cleanly via `candle-transformers::models::xlm_roberta::XLMRobertaModel`.
Weight names from HuggingFace already match the XLMRoberta module expectations
(no prefix stripping needed). Tokenizer works via the standard `tokenizers` crate
after converting from HF slow tokenizer format to `tokenizer.json`.

No RoBERTa-specific issues encountered.

## Positive Pair Similarity (higher = better)

| Pair | mu-sigma-v2 | UniXcoder | Delta |
|------|-------------|-----------|-------|
| "soft delete query" vs code | -0.1820 | 0.2049 | +0.3869 |
| "authentication middleware" vs code | 0.5916 | 0.3686 | -0.2230 |
| "database connection pool" vs code | 0.1360 | 0.3343 | +0.1983 |
| "error handling pattern" vs code | 0.5389 | 0.0764 | -0.4625 |
| "unit test assertion" vs code | 0.8491 | 0.3387 | -0.5104 |
| **Average** | **0.3867** | **0.2646** | **-0.1221** |

## Discrimination (positive avg - negative avg)

| Model | Pos Avg | Neg Avg | Discrimination |
|-------|---------|---------|----------------|
| mu-sigma-v2 | 0.3867 | 0.0041 | **0.3826** |
| UniXcoder | 0.2646 | 0.2004 | **0.0642** |

## Analysis

mu-sigma-v2 wins on both absolute similarity and discrimination:

1. **Better positive pairs**: mu-sigma-v2 averages 0.39 vs UniXcoder's 0.26 on matched description/code pairs
2. **Much better discrimination**: mu-sigma-v2 clearly separates related (0.39) from unrelated (0.004) pairs.
   UniXcoder barely distinguishes them (0.26 vs 0.20), giving near-random discrimination.
3. **Size efficiency**: mu-sigma-v2 is 5.5x smaller (91 MB vs 501 MB) while performing better.

UniXcoder was pretrained as a general code model (code completion, generation) rather than
fine-tuned for semantic similarity. The base model's embeddings aren't well-calibrated
for retrieval tasks without fine-tuning. mu-sigma-v2 was specifically trained for
code search similarity, which explains the gap.

## Recommendation

**NO-GO**. Do not swap UniXcoder-base for mu-sigma-v2. The current model is both
smaller and significantly better at the task we care about (code semantic search).

If we want to explore better embeddings, the right path would be fine-tuning
UniXcoder (or another code model) on code search pairs -- not using the base model directly.
