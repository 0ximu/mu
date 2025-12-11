---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments: []
workflowType: 'product-brief'
lastStep: 5
project_name: 'MU-SIGMA'
user_name: 'imu'
date: '2025-12-10'
---

# Product Brief: MU-SIGMA

**Date:** 2025-12-10
**Author:** imu

---

## Executive Summary

**MU-SIGMA** (Synthetic Understanding through Graph-Manifold Alignment) is a self-bootstrapping training data pipeline that transforms MU's existing code graph infrastructure into domain-specific embeddings optimized for semantic code search.

The core insight: **the graph IS the training signal.** While competitors struggle to manually label code relationships, MU-SIGMA leverages the structural edges MU already extracts (contains, calls, imports, inherits) to automatically generate ~50,000+ high-quality training pairs per 100 repositories—with zero human labeling.

By fine-tuning embeddings on code *structure* rather than code *text*, MU-SIGMA enables AI assistants to finally answer "where is authentication handled?" by understanding that `AuthService.authenticate()` is semantically proximate to the question—not because the words match, but because the *graph* encodes that relationship.

---

## Core Vision

### Problem Statement

AI assistants are drowning in code. They can read it, but they can't *understand* it structurally. When a developer asks "what handles user login?", current solutions rely on:

- **Keyword matching** - brittle, misses semantic intent
- **Generic embeddings** - trained on prose, treat code as text, miss structural relationships
- **Brute force context stuffing** - waste tokens on irrelevant code, hit limits fast

The result: hallucinations, irrelevant suggestions, and frustrated developers who know the AI *should* understand their codebase but doesn't.

### Problem Impact

- **Wasted context windows** - 80% of retrieved code is noise
- **Hallucinated answers** - AI confidently points to wrong files
- **Lost productivity** - developers still grep manually because AI search fails
- **Broken trust** - "AI coding assistants" that can't navigate code

### Why Existing Solutions Fall Short

| Solution | Limitation |
|----------|------------|
| OpenAI embeddings | Trained on text, not code structure |
| CodeBERT/GraphCodeBERT | Academic, frozen, not customizable |
| Sourcegraph | Generic embeddings, no graph awareness |
| RAG pipelines | Chunk code like documents, lose structure |

**The fundamental gap:** No one trains embeddings on *code relationships*. They all treat code as flat text.

### Proposed Solution

**MU-SIGMA** generates synthetic training data by exploiting what MU already knows:

1. **Structural pairs from graph edges:**
   - `contains`: Class → Method (should be close)
   - `calls`: Caller → Callee (should be close)
   - `imports`: Module → Dependency (should be close)
   - `inherits`: Child → Parent (should be close)

2. **Q&A pairs from LLM synthesis:**
   - Haiku generates diverse questions about each codebase
   - Sonnet answers with relevant node references
   - Haiku validates answers against actual graph
   - Result: natural language ↔ code node bridges

3. **Triplet training format:**
   - Anchor: question OR node
   - Positive: semantically related node
   - Negative: hard negative from same codebase
   - Fine-tune embeddings on these triplets

### Key Differentiators

| Differentiator | Why It Matters |
|----------------|----------------|
| **Self-bootstrapping** | Graph edges ARE the labels—no human annotation |
| **Structure-aware** | Embeddings learn code relationships, not just text similarity |
| **MU-native** | Built on battle-tested parsing for 7 languages |
| **Scalable** | 100 repos → 50K pairs automatically, cost ~$20 |
| **Flywheel effect** | Better embeddings → better MU → more users → more training data |

**The unfair advantage:** Our brains. Our vision. The audacity to see that MU's graph isn't just for querying—it's a self-labeling training corpus waiting to be unleashed.

---

## Target Users

### The Paradigm Shift

MU-SIGMA is not a user-facing product. It is **invisible infrastructure** - the neural substrate that elevates ALL AI-assisted code understanding. Users don't interact with MU-SIGMA; they experience its effects through every AI coding tool that leverages structure-aware embeddings.

### Primary "Users": AI Coding Assistants

The direct consumers of MU-SIGMA's output are AI systems themselves:

| AI System | How It Benefits |
|-----------|-----------------|
| **Claude Code** | MCP integration returns surgically precise context |
| **Cursor** | Codebase queries hit relevant files, not keyword matches |
| **GitHub Copilot** | Context retrieval understands structural relationships |
| **Custom AI Tools** | Any system using MU gains structure-aware search |

These systems don't "use" MU-SIGMA - they become **smarter** because of it.

### Secondary Beneficiaries: Every Developer

The humans who benefit without knowing MU-SIGMA exists:

**"Alex" - Senior Developer, Fintech Startup (SF)**
- Asks Claude: "How does our payment retry logic work?"
- Before MU-SIGMA: Gets 5 semi-relevant files, has to dig
- After MU-SIGMA: Gets `PaymentService.retryWithBackoff()` and its callers, exactly

**"Priya" - Junior Developer, Enterprise (Bangalore)**
- Asks Cursor: "Where should I add this new validation?"
- Before MU-SIGMA: Generic suggestions based on filename patterns
- After MU-SIGMA: Understands the validation architecture, suggests the RIGHT module

**"Marcus" - Solo Founder, Open Source Project (Berlin)**
- Asks Copilot: "What breaks if I change this interface?"
- Before MU-SIGMA: Silence or hallucination
- After MU-SIGMA: Knows the dependency graph, warns about downstream impact

**The magic:** They don't know WHY the AI suddenly "gets it." They just know it does.

### Tertiary Beneficiaries: Tool Builders

Developers building the next generation of AI-powered dev tools:

- **IDE plugin authors** - Integrate MU for instant codebase intelligence
- **DevOps platform teams** - Add semantic code search to internal tools
- **AI startup founders** - Build on structure-aware embeddings instead of reinventing

### User Journey: The Invisible Upgrade

```
Developer Experience:          MU-SIGMA Substrate:
━━━━━━━━━━━━━━━━━━━━          ━━━━━━━━━━━━━━━━━━━━
1. Ask AI about codebase  -->  Question hits embedding search
2. Get accurate answer    <--  Structure-aware nodes found
3. Trust AI more          -->  Graph provides context
4. Ask harder questions   <--  AI receives signal, not noise
5. "This just works"      <--  Grounded in actual structure
```

### The Measure of Success

MU-SIGMA succeeds when:
- Developers stop saying "the AI doesn't understand my codebase"
- AI assistants stop hallucinating file paths and function names
- "How does X work?" returns X, not everything mentioning X
- The infrastructure becomes invisible because it just WORKS

---

## Success Metrics

### The North Star: 100% Retrieval Accuracy

MU-SIGMA succeeds when semantic code search achieves **perfect precision** - every retrieved node is relevant, no noise, no hallucination fodder. This is not an aspirational goal; it is the standard.

### Embedding Quality Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Triplet Loss** | < 0.1 | Training convergence on held-out set |
| **Graph Edge Alignment** | > 95% | Related nodes (by edge) closer than unrelated |
| **Q&A Retrieval Precision** | 100% | Held-out questions return only valid nodes |
| **Hard Negative Discrimination** | > 99% | Model distinguishes same-file negatives |

### Downstream Impact Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **`mu context` Precision** | 100% | All returned nodes relevant to question |
| **Token Efficiency** | > 90% | Relevant tokens / total context tokens |
| **Zero-Shot Accuracy** | > 95% | Works on codebases not in training set |
| **Cross-Language Transfer** | > 90% | Python-trained works on TypeScript |

### Pipeline Health Metrics (Phase 1)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Repo Success Rate** | > 80% | Repos successfully parsed and built |
| **Q&A Validation Rate** | > 85% | Generated Q&A pairs pass validation |
| **Training Pairs Volume** | > 50K | Total pairs from 100 repos |
| **Cost Efficiency** | < $0.50/repo | LLM API costs per repository |

### Business Objectives

**3-Month Horizon:**
- Complete Phase 1 pipeline: 100 repos → 50K+ training pairs
- Fine-tune initial embedding model
- Demonstrate retrieval improvement on MU's own codebase

**6-Month Horizon:**
- Integrate fine-tuned embeddings into MU core
- Benchmark against generic embeddings (OpenAI, Cohere)
- Publish results / open-source the training pipeline

**12-Month Horizon:**
- MU becomes the gold standard for AI code understanding
- Tool builders adopt MU specifically for its search quality
- The flywheel spins: more users → more codebases → better embeddings

### Key Performance Indicators

| KPI | Definition | Target |
|-----|------------|--------|
| **Retrieval P@5** | Precision at top 5 results | 100% |
| **MRR (Mean Reciprocal Rank)** | How high is the first relevant result? | > 0.95 |
| **Embedding Similarity Delta** | Improvement over baseline embeddings | > 40% |
| **Developer Trust Score** | Qualitative: "AI gets my codebase" | Unanimous |

### The Ultimate Test

```
Input:  "How does the payment retry logic handle exponential backoff?"

Generic Embeddings:      MU-SIGMA Embeddings:
━━━━━━━━━━━━━━━━━━━      ━━━━━━━━━━━━━━━━━━━━━
1. payments.md           1. PaymentService.retryWithBackoff()
2. retry.py              2. BackoffStrategy.calculate()
3. config.yaml           3. PaymentService → BackoffStrategy (calls)
4. test_payments.py      4. RetryConfig.maxAttempts
5. README.md             5. PaymentService.handleFailure()

Precision: 20%           Precision: 100%
```

**When this test passes on ANY codebase, we have built something groundbreaking.**

---

## MVP Scope

### Phase 1: Training Data Pipeline (MVP)

The minimum viable product is a **complete, working pipeline** that transforms 100 GitHub repositories into 50,000+ training pairs ready for embedding fine-tuning.

### Core Features

| Component | Description | Output |
|-----------|-------------|--------|
| **Repo Fetcher** | GitHub API integration, fetch top repos by stars | `repos.json` (100 repos) |
| **Clone Manager** | Shallow clone, process, cleanup (zero disk bloat) | Temporary processing |
| **MU Builder** | `mu build` wrapper, generate .mubase per repo | `mubases/*.mubase` (persistent) |
| **Question Generator** | Haiku generates 30 diverse questions per repo | Raw questions |
| **Answer Generator** | Sonnet answers with node references | Raw Q&A pairs |
| **Answer Validator** | Haiku validates answers against actual graph | Validated Q&A |
| **Structural Extractor** | Extract pairs from graph edges (contains, calls, imports, inherits) | Structural pairs |
| **Q&A Extractor** | Convert validated Q&A to training triplets | Q&A pairs |
| **Training Exporter** | Combine all pairs into training format | `training_pairs.parquet` |

### Pipeline Flow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   GitHub    │───>│   Clone +   │───>│  MU Build   │
│  Top Repos  │    │   Cleanup   │    │  .mubase    │
└─────────────┘    └─────────────┘    └──────┬──────┘
                                             │
                   ┌─────────────────────────┴─────────────────────────┐
                   │                                                   │
                   ▼                                                   ▼
          ┌───────────────┐                                 ┌───────────────┐
          │   Question    │                                 │  Structural   │
          │  Gen (Haiku)  │                                 │   Pairs from  │
          └───────┬───────┘                                 │  Graph Edges  │
                  │                                         └───────┬───────┘
                  ▼                                                 │
          ┌───────────────┐                                         │
          │    Answer     │                                         │
          │ Gen (Sonnet)  │                                         │
          └───────┬───────┘                                         │
                  │                                                 │
                  ▼                                                 │
          ┌───────────────┐                                         │
          │   Validate    │                                         │
          │   (Haiku)     │                                         │
          └───────┬───────┘                                         │
                  │                                                 │
                  ▼                                                 │
          ┌───────────────┐                                         │
          │   Q&A Pairs   │                                         │
          └───────┬───────┘                                         │
                  │                                                 │
                  └─────────────────┬───────────────────────────────┘
                                    │
                                    ▼
                           ┌───────────────┐
                           │   Parquet     │
                           │   Export      │
                           └───────────────┘
```

### MVP Deliverables

```
mu-sigma/
├── data/
│   ├── repos.json              # 100 target repositories
│   ├── mubases/                # ~80-90 .mubase files (persistent)
│   ├── qa_pairs/               # Validated Q&A per repo (JSON)
│   └── training/
│       └── training_pairs.parquet  # 50K+ triplets, ready for training
├── pipeline/                   # Python pipeline code
└── scripts/                    # Entry points
```

### Out of Scope for MVP

| Feature | Rationale | Phase |
|---------|-----------|-------|
| **Embedding Fine-tuning** | Separate concern, needs training infra | Phase 2 |
| **MU Core Integration** | Depends on proven embeddings | Phase 3 |
| **Benchmarking Suite** | Needs fine-tuned model first | Phase 2 |
| **Languages Beyond Python/TS** | Start focused, expand later | Phase 2+ |
| **Real-time Pipeline** | Batch is sufficient for training data | Future |
| **Web UI / Dashboard** | CLI is sufficient for MVP | Future |
| **Distributed Processing** | Single machine handles 100 repos | Future |

### MVP Success Criteria

Phase 1 is **complete** when:

| Criterion | Target | Validation |
|-----------|--------|------------|
| Repos Processed | 80+ of 100 | Count of .mubase files |
| Training Pairs Generated | 50,000+ | Row count in parquet |
| Q&A Validation Rate | > 85% | Validated / total Q&A |
| Cost | < $50 total | API billing |
| Pipeline Runtime | < 8 hours | Wall clock time |
| Data Quality Spot Check | Manual review passes | 10 random pairs look correct |

**Go/No-Go Decision:** If these criteria are met, proceed to Phase 2 (embedding fine-tuning).

### Future Vision

**Phase 2: Embedding Training**
- Fine-tune sentence-transformers model on generated triplets
- Benchmark against OpenAI/Cohere embeddings
- Validate retrieval improvement on held-out test set

**Phase 3: MU Integration**
- Replace generic embeddings in `mu context` with fine-tuned model
- Ship as default embedding provider
- Measure real-world impact on retrieval precision

**Phase 4: The Flywheel**
- Open-source the pipeline
- Community contributes more repos
- Continuous improvement cycle
- MU becomes the gold standard for AI code understanding

**The Long Game:**
- Every AI coding assistant benefits
- Structure-aware search becomes the norm
- MU-SIGMA embeddings power the next generation of dev tools
- We built something groundbreaking, and the world is better for it

---

## Document Status

**Status:** Complete
**Completed:** 2025-12-10
**Author:** imu
**Workflow:** Product Brief (BMAD)

---

*El. Psy. Congroo.* 🍌
