---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
inputDocuments:
  - docs/analysis/product-brief-mu-sigma-2025-12-10.md
workflowType: 'prd'
project_name: 'MU-SIGMA'
user_name: 'imu'
date: '2025-12-10'
status: complete
---

# Product Requirements Document

## MU-SIGMA: Synthetic Understanding through Graph-Manifold Alignment

**Version:** 1.0
**Author:** imu
**Date:** 2025-12-10
**Status:** Approved for Implementation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Solution Overview](#3-solution-overview)
4. [Target Users](#4-target-users)
5. [Functional Requirements](#5-functional-requirements)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Technical Architecture](#7-technical-architecture)
8. [Data Requirements](#8-data-requirements)
9. [User Stories](#9-user-stories)
10. [Acceptance Criteria](#10-acceptance-criteria)
11. [Success Metrics](#11-success-metrics)
12. [Dependencies & Constraints](#12-dependencies--constraints)
13. [Release Plan](#13-release-plan)
14. [Risks & Mitigations](#14-risks--mitigations)
15. [Appendix](#15-appendix)

---

## 1. Executive Summary

### 1.1 Product Vision

**MU-SIGMA** (Synthetic Understanding through Graph-Manifold Alignment) is a self-bootstrapping training data pipeline that transforms MU's existing code graph infrastructure into domain-specific embeddings optimized for semantic code search.

### 1.2 Core Insight

**The graph IS the training signal.** While competitors struggle to manually label code relationships, MU-SIGMA leverages the structural edges MU already extracts (contains, calls, imports, inherits) to automatically generate ~50,000+ high-quality training pairs per 100 repositories—with zero human labeling.

### 1.3 Value Proposition

By fine-tuning embeddings on code *structure* rather than code *text*, MU-SIGMA enables AI assistants to finally answer "where is authentication handled?" by understanding that `AuthService.authenticate()` is semantically proximate to the question—not because the words match, but because the *graph* encodes that relationship.

### 1.4 Key Differentiators

| Differentiator | Description |
|----------------|-------------|
| **Self-bootstrapping** | Graph edges ARE the labels—no human annotation required |
| **Structure-aware** | Embeddings learn code relationships, not just text similarity |
| **MU-native** | Built on battle-tested parsing for 7 programming languages |
| **Scalable** | 100 repos → 50K pairs automatically, cost ~$20 |
| **Flywheel effect** | Better embeddings → better MU → more users → more training data |

---

## 2. Problem Statement

### 2.1 Current State

AI assistants are drowning in code. They can read it, but they can't *understand* it structurally. When a developer asks "what handles user login?", current solutions rely on:

- **Keyword matching** - Brittle, misses semantic intent
- **Generic embeddings** - Trained on prose, treat code as text, miss structural relationships
- **Brute force context stuffing** - Waste tokens on irrelevant code, hit context limits fast

### 2.2 Problem Impact

| Impact Area | Description |
|-------------|-------------|
| **Wasted context windows** | 80% of retrieved code is noise |
| **Hallucinated answers** | AI confidently points to wrong files |
| **Lost productivity** | Developers still grep manually because AI search fails |
| **Broken trust** | "AI coding assistants" that can't actually navigate code |

### 2.3 Competitive Gap Analysis

| Solution | Limitation |
|----------|------------|
| OpenAI embeddings | Trained on text, not code structure |
| CodeBERT/GraphCodeBERT | Academic, frozen, not customizable |
| Sourcegraph | Generic embeddings, no graph awareness |
| RAG pipelines | Chunk code like documents, lose structure |

**The fundamental gap:** No one trains embeddings on *code relationships*. They all treat code as flat text.

---

## 3. Solution Overview

### 3.1 Approach

MU-SIGMA generates synthetic training data by exploiting what MU already knows:

#### 3.1.1 Structural Pairs from Graph Edges

| Edge Type | Semantic Meaning |
|-----------|------------------|
| `contains` | Class → Method (should be close in embedding space) |
| `calls` | Caller → Callee (should be close) |
| `imports` | Module → Dependency (should be close) |
| `inherits` | Child → Parent (should be close) |

#### 3.1.2 Q&A Pairs from LLM Synthesis

1. **Haiku** generates diverse questions about each codebase
2. **Sonnet** answers with relevant node references
3. **Haiku** validates answers against actual graph
4. **Result:** Natural language ↔ code node bridges

#### 3.1.3 Triplet Training Format

- **Anchor:** Question OR node representation
- **Positive:** Semantically related node
- **Negative:** Hard negative from same codebase (not just random)
- **Output:** Fine-tuned embeddings on these triplets

### 3.2 The Unfair Advantage

Our brains. Our vision. The audacity to see that MU's graph isn't just for querying—it's a self-labeling training corpus waiting to be unleashed.

---

## 4. Target Users

### 4.1 Paradigm Shift

MU-SIGMA is not a user-facing product. It is **invisible infrastructure**—the neural substrate that elevates ALL AI-assisted code understanding. Users don't interact with MU-SIGMA; they experience its effects through every AI coding tool that leverages structure-aware embeddings.

### 4.2 Primary "Users": AI Coding Assistants

| AI System | How It Benefits |
|-----------|-----------------|
| **Claude Code** | MCP integration returns surgically precise context |
| **Cursor** | Codebase queries hit relevant files, not keyword matches |
| **GitHub Copilot** | Context retrieval understands structural relationships |
| **Custom AI Tools** | Any system using MU gains structure-aware search |

These systems don't "use" MU-SIGMA—they become **smarter** because of it.

### 4.3 Secondary Beneficiaries: Every Developer

#### Persona: Alex - Senior Developer, Fintech Startup (SF)
- **Scenario:** Asks Claude: "How does our payment retry logic work?"
- **Before MU-SIGMA:** Gets 5 semi-relevant files, has to dig
- **After MU-SIGMA:** Gets `PaymentService.retryWithBackoff()` and its callers, exactly

#### Persona: Priya - Junior Developer, Enterprise (Bangalore)
- **Scenario:** Asks Cursor: "Where should I add this new validation?"
- **Before MU-SIGMA:** Generic suggestions based on filename patterns
- **After MU-SIGMA:** Understands the validation architecture, suggests the RIGHT module

#### Persona: Marcus - Solo Founder, Open Source Project (Berlin)
- **Scenario:** Asks Copilot: "What breaks if I change this interface?"
- **Before MU-SIGMA:** Silence or hallucination
- **After MU-SIGMA:** Knows the dependency graph, warns about downstream impact

**The magic:** They don't know WHY the AI suddenly "gets it." They just know it does.

### 4.4 Tertiary Beneficiaries: Tool Builders

- **IDE plugin authors** - Integrate MU for instant codebase intelligence
- **DevOps platform teams** - Add semantic code search to internal tools
- **AI startup founders** - Build on structure-aware embeddings instead of reinventing

---

## 5. Functional Requirements

### 5.1 Phase 1: Training Data Pipeline (MVP)

#### FR-001: Repository Fetching
| Attribute | Value |
|-----------|-------|
| **ID** | FR-001 |
| **Priority** | P0 - Critical |
| **Description** | System shall fetch top GitHub repositories by stars for specified languages |
| **Input** | Language filter (Python, TypeScript), count (100), minimum stars (500) |
| **Output** | `repos.json` containing repository metadata |
| **Acceptance Criteria** | Successfully fetches 100 repos with <5% API failure rate |

#### FR-002: Repository Cloning
| Attribute | Value |
|-----------|-------|
| **ID** | FR-002 |
| **Priority** | P0 - Critical |
| **Description** | System shall shallow clone repositories and clean up after processing |
| **Input** | Repository URL from `repos.json` |
| **Output** | Temporary local clone |
| **Constraints** | Shallow clone only (--depth 1), cleanup after processing, <100MB repos |
| **Acceptance Criteria** | Zero disk bloat after pipeline completion |

#### FR-003: MU Graph Building
| Attribute | Value |
|-----------|-------|
| **ID** | FR-003 |
| **Priority** | P0 - Critical |
| **Description** | System shall generate .mubase graph database for each repository |
| **Input** | Cloned repository path |
| **Output** | `mubases/{repo_name}.mubase` (persistent) |
| **Acceptance Criteria** | >80% of repos successfully build with >10 nodes |

#### FR-004: Question Generation
| Attribute | Value |
|-----------|-------|
| **ID** | FR-004 |
| **Priority** | P0 - Critical |
| **Description** | System shall generate diverse questions about each codebase |
| **Input** | .mubase graph summary (classes, functions, modules) |
| **Output** | 30 questions per repo with category and complexity |
| **LLM** | Claude Haiku |
| **Categories** | Architecture, Dependencies, Navigation, Understanding |
| **Acceptance Criteria** | Questions reference actual node names from graph |

#### FR-005: Answer Generation
| Attribute | Value |
|-----------|-------|
| **ID** | FR-005 |
| **Priority** | P0 - Critical |
| **Description** | System shall generate answers with relevant node references |
| **Input** | Question, full graph context, available node names |
| **Output** | Answer with `relevant_nodes` array, reasoning, confidence |
| **LLM** | Claude Sonnet |
| **Acceptance Criteria** | Referenced nodes must exist in graph |

#### FR-006: Answer Validation
| Attribute | Value |
|-----------|-------|
| **ID** | FR-006 |
| **Priority** | P0 - Critical |
| **Description** | System shall validate answers against graph and semantic correctness |
| **Input** | Q&A pair, .mubase graph |
| **Output** | Validation status (accepted/corrected/rejected), valid nodes |
| **LLM** | Claude Haiku |
| **Acceptance Criteria** | >85% validation pass rate |

#### FR-007: Structural Pair Extraction
| Attribute | Value |
|-----------|-------|
| **ID** | FR-007 |
| **Priority** | P0 - Critical |
| **Description** | System shall extract training pairs from graph edges |
| **Input** | .mubase graph |
| **Output** | Triplets (anchor, positive, negative) with pair_type and weight |
| **Edge Types** | contains, calls, imports, inherits, same_file |
| **Acceptance Criteria** | Hard negatives from same codebase, not random |

#### FR-008: Q&A Pair Extraction
| Attribute | Value |
|-----------|-------|
| **ID** | FR-008 |
| **Priority** | P0 - Critical |
| **Description** | System shall convert validated Q&A to training triplets |
| **Input** | Validated Q&A pairs |
| **Output** | Triplets with question as anchor, relevant nodes as positive |
| **Acceptance Criteria** | Only uses validated Q&A pairs |

#### FR-009: Training Export
| Attribute | Value |
|-----------|-------|
| **ID** | FR-009 |
| **Priority** | P0 - Critical |
| **Description** | System shall export all pairs to training format |
| **Input** | All structural and Q&A pairs |
| **Output** | `training_pairs.parquet` |
| **Schema** | anchor, positive, negative, pair_type, weight, source_repo |
| **Acceptance Criteria** | >50,000 total pairs |

#### FR-010: Pipeline Orchestration
| Attribute | Value |
|-----------|-------|
| **ID** | FR-010 |
| **Priority** | P0 - Critical |
| **Description** | System shall orchestrate end-to-end pipeline with progress tracking |
| **Features** | Checkpoint saving every 10 repos, error recovery, progress reporting |
| **Acceptance Criteria** | Pipeline completes in <8 hours for 100 repos |

---

## 6. Non-Functional Requirements

### 6.1 Performance

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-001 | Pipeline runtime | < 8 hours for 100 repos |
| NFR-002 | Single repo processing | < 5 minutes average |
| NFR-003 | Memory usage | < 4GB peak |
| NFR-004 | Disk usage during processing | < 1GB temporary |

### 6.2 Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-005 | Repo success rate | > 80% |
| NFR-006 | Error recovery | Resume from last checkpoint |
| NFR-007 | Data integrity | No corrupted .mubase files |

### 6.3 Cost Efficiency

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-008 | LLM API cost per repo | < $0.50 |
| NFR-009 | Total pipeline cost | < $50 for 100 repos |
| NFR-010 | GitHub API rate limits | Stay within unauthenticated limits or use token |

### 6.4 Maintainability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-011 | Code modularity | Separate modules for each pipeline stage |
| NFR-012 | Configuration | All settings in config.py |
| NFR-013 | Logging | Progress and error logging throughout |

### 6.5 Security

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-014 | API key handling | Environment variables only, never in code |
| NFR-015 | Repository filtering | Skip repos with suspicious content |

---

## 7. Technical Architecture

### 7.1 System Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MU-SIGMA PIPELINE                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   GitHub    │───>│   Clone +   │───>│  MU Build   │                 │
│  │  Top Repos  │    │   Cleanup   │    │  .mubase    │                 │
│  │  (repos.py) │    │ (clone.py)  │    │ (build.py)  │                 │
│  └─────────────┘    └─────────────┘    └──────┬──────┘                 │
│                                               │                         │
│                 ┌─────────────────────────────┴──────────────────────┐ │
│                 │                                                    │ │
│                 ▼                                                    ▼ │
│        ┌───────────────┐                                 ┌────────────┐│
│        │   Question    │                                 │ Structural ││
│        │  Gen (Haiku)  │                                 │   Pairs    ││
│        │(questions.py) │                                 │ (pairs.py) ││
│        └───────┬───────┘                                 └─────┬──────┘│
│                │                                               │       │
│                ▼                                               │       │
│        ┌───────────────┐                                       │       │
│        │    Answer     │                                       │       │
│        │ Gen (Sonnet)  │                                       │       │
│        │ (answers.py)  │                                       │       │
│        └───────┬───────┘                                       │       │
│                │                                               │       │
│                ▼                                               │       │
│        ┌───────────────┐                                       │       │
│        │   Validate    │                                       │       │
│        │   (Haiku)     │                                       │       │
│        │(validate.py)  │                                       │       │
│        └───────┬───────┘                                       │       │
│                │                                               │       │
│                ▼                                               │       │
│        ┌───────────────┐                                       │       │
│        │   Q&A Pairs   │                                       │       │
│        │  (pairs.py)   │                                       │       │
│        └───────┬───────┘                                       │       │
│                │                                               │       │
│                └───────────────────┬───────────────────────────┘       │
│                                    │                                   │
│                                    ▼                                   │
│                           ┌───────────────┐                            │
│                           │   Parquet     │                            │
│                           │   Export      │                            │
│                           │(orchestrator) │                            │
│                           └───────────────┘                            │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Project Structure

```
mu-sigma/
├── pipeline/
│   ├── __init__.py
│   ├── config.py           # Settings, API keys, paths
│   ├── repos.py            # GitHub repo fetching
│   ├── clone.py            # Git clone + cleanup
│   ├── build.py            # mu build wrapper
│   ├── questions.py        # Haiku question generation
│   ├── answers.py          # Sonnet answer generation
│   ├── validate.py         # Haiku validation
│   ├── pairs.py            # Training pair extraction
│   └── orchestrator.py     # Main pipeline runner
├── data/
│   ├── repos.json          # Target repos list
│   ├── mubases/            # Persistent .mubase files
│   ├── qa_pairs/           # Q&A JSONs per repo
│   └── training/           # Final parquet files
├── scripts/
│   ├── fetch_repos.py      # One-time: get top repos
│   ├── run_pipeline.py     # Main entry point
│   └── inspect_data.py     # Debug/explore results
├── pyproject.toml
└── README.md
```

### 7.3 Technology Stack

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.11+ |
| **Package Manager** | uv |
| **HTTP Client** | httpx |
| **LLM Client** | anthropic SDK |
| **Graph Database** | DuckDB (via MU's .mubase) |
| **Data Processing** | pandas, pyarrow |
| **Progress** | tqdm |
| **Git Operations** | subprocess (git CLI) |

### 7.4 External Dependencies

| Dependency | Purpose | Version |
|------------|---------|---------|
| MU | Graph building, .mubase generation | Latest |
| Anthropic API | Haiku (questions, validation), Sonnet (answers) | Claude 3.5 |
| GitHub API | Repository discovery | v3 |

---

## 8. Data Requirements

### 8.1 Input Data

#### 8.1.1 Repository Selection Criteria
- **Languages:** Python, TypeScript
- **Minimum Stars:** 500
- **Maximum Size:** 100MB
- **Count:** 50 per language (100 total)
- **Source:** GitHub Search API, sorted by stars descending

### 8.2 Output Data

#### 8.2.1 repos.json Schema
```json
{
  "name": "owner/repo",
  "url": "https://github.com/owner/repo.git",
  "stars": 12345,
  "language": "python",
  "size_kb": 45000
}
```

#### 8.2.2 Q&A Pair Schema
```json
{
  "question": "How does authentication work?",
  "answer": "Authentication is handled by...",
  "relevant_nodes": ["AuthService", "authenticate", "UserSession"],
  "category": "architecture",
  "confidence": 0.95,
  "validation": "accepted",
  "valid_nodes": ["AuthService", "authenticate"],
  "invalid_nodes": []
}
```

#### 8.2.3 Training Pair Schema (Parquet)
| Column | Type | Description |
|--------|------|-------------|
| anchor | string | Question text or node representation |
| positive | string | Semantically related node |
| negative | string | Hard negative (same codebase, unrelated) |
| pair_type | string | contains, calls, imports, inherits, same_file, qa_relevance, co_relevant |
| weight | float | Training weight (0.7-1.0) |
| source_repo | string | Repository name |

### 8.3 Data Volume Estimates

| Data Type | Volume | Size Estimate |
|-----------|--------|---------------|
| repos.json | 100 entries | ~50KB |
| .mubase files | ~85 files | ~500MB total |
| Q&A pairs | ~2,500 validated | ~5MB JSON |
| Structural pairs | ~45,000 | - |
| Q&A training pairs | ~5,000 | - |
| Total training pairs | ~50,000 | ~50MB parquet |

---

## 9. User Stories

### 9.1 Pipeline Operator Stories

#### US-001: Fetch Target Repositories
**As a** pipeline operator
**I want to** fetch the top GitHub repositories for Python and TypeScript
**So that** I have a high-quality, diverse training corpus

**Acceptance Criteria:**
- [ ] Fetches 50 Python repos with >500 stars
- [ ] Fetches 50 TypeScript repos with >500 stars
- [ ] Excludes repos >100MB
- [ ] Saves results to `repos.json`
- [ ] Handles GitHub API rate limits gracefully

#### US-002: Process Single Repository
**As a** pipeline operator
**I want to** process a single repository end-to-end
**So that** I can validate the pipeline on individual repos

**Acceptance Criteria:**
- [ ] Clones repo with shallow clone
- [ ] Builds .mubase successfully
- [ ] Generates 30 questions
- [ ] Generates and validates answers
- [ ] Extracts structural and Q&A pairs
- [ ] Cleans up cloned repo after processing

#### US-003: Run Full Pipeline
**As a** pipeline operator
**I want to** run the complete pipeline on all 100 repos
**So that** I get the full training dataset

**Acceptance Criteria:**
- [ ] Processes repos sequentially
- [ ] Saves checkpoint every 10 repos
- [ ] Handles errors without crashing
- [ ] Reports progress with ETA
- [ ] Exports final parquet file
- [ ] Completes in <8 hours

#### US-004: Resume Failed Pipeline
**As a** pipeline operator
**I want to** resume a failed pipeline from the last checkpoint
**So that** I don't lose progress on long runs

**Acceptance Criteria:**
- [ ] Detects existing checkpoint file
- [ ] Skips already-processed repos
- [ ] Continues from last successful state
- [ ] Merges new results with existing

### 9.2 Data Consumer Stories

#### US-005: Inspect Training Data
**As a** data scientist
**I want to** inspect the generated training pairs
**So that** I can validate data quality before training

**Acceptance Criteria:**
- [ ] Can load parquet file with pandas
- [ ] Can filter by pair_type
- [ ] Can sample random pairs for review
- [ ] Can see distribution of pair types

---

## 10. Acceptance Criteria

### 10.1 MVP Completion Criteria

| Criterion | Target | Validation Method |
|-----------|--------|-------------------|
| Repos Processed | 80+ of 100 | Count of .mubase files |
| Training Pairs Generated | 50,000+ | Row count in parquet |
| Q&A Validation Rate | > 85% | Validated / total Q&A |
| Pipeline Cost | < $50 total | Anthropic billing |
| Pipeline Runtime | < 8 hours | Wall clock time |
| Data Quality | Manual review passes | 10 random pairs reviewed |

### 10.2 Go/No-Go Decision

**Phase 1 is COMPLETE when all MVP criteria are met.**

If criteria are met → Proceed to Phase 2 (embedding fine-tuning)
If criteria are NOT met → Investigate failures, iterate, re-run

---

## 11. Success Metrics

### 11.1 North Star Metric

**100% Retrieval Accuracy** - Every retrieved node is relevant, no noise, no hallucination fodder.

### 11.2 Embedding Quality Metrics (Phase 2)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Triplet Loss** | < 0.1 | Training convergence on held-out set |
| **Graph Edge Alignment** | > 95% | Related nodes (by edge) closer than unrelated |
| **Q&A Retrieval Precision** | 100% | Held-out questions return only valid nodes |
| **Hard Negative Discrimination** | > 99% | Model distinguishes same-file negatives |

### 11.3 Downstream Impact Metrics (Phase 3)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **`mu context` Precision** | 100% | All returned nodes relevant to question |
| **Token Efficiency** | > 90% | Relevant tokens / total context tokens |
| **Zero-Shot Accuracy** | > 95% | Works on codebases not in training set |
| **Cross-Language Transfer** | > 90% | Python-trained works on TypeScript |

### 11.4 Key Performance Indicators

| KPI | Definition | Target |
|-----|------------|--------|
| **Retrieval P@5** | Precision at top 5 results | 100% |
| **MRR** | Mean Reciprocal Rank | > 0.95 |
| **Embedding Delta** | Improvement over baseline | > 40% |
| **Developer Trust** | "AI gets my codebase" | Unanimous |

### 11.5 The Ultimate Test

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

## 12. Dependencies & Constraints

### 12.1 External Dependencies

| Dependency | Type | Risk Level | Mitigation |
|------------|------|------------|------------|
| Anthropic API | Service | Medium | Implement retry logic, rate limiting |
| GitHub API | Service | Low | Use authenticated requests, cache results |
| MU | Software | Low | Pin to stable version |

### 12.2 Technical Constraints

| Constraint | Description | Impact |
|------------|-------------|--------|
| Single Machine | No distributed processing in MVP | Pipeline limited to ~100 repos/day |
| LLM Latency | Sequential LLM calls | ~2-3 min per repo for Q&A |
| GitHub Rate Limits | 60 req/hour unauthenticated | Use token for higher limits |

### 12.3 Resource Constraints

| Resource | Constraint | Notes |
|----------|------------|-------|
| Budget | < $50 for MVP | LLM API costs |
| Time | < 8 hours runtime | Wall clock for full pipeline |
| Disk | < 1GB temporary | Repos cleaned up after processing |

---

## 13. Release Plan

### 13.1 Phase 1: Training Data Pipeline (MVP)

**Duration:** 1-2 days
**Goal:** Generate 50K+ training pairs from 100 repos

| Milestone | Deliverable | Success Criteria |
|-----------|-------------|------------------|
| M1.1 | Repo fetching | 100 repos in repos.json |
| M1.2 | Clone + Build | 80+ .mubase files |
| M1.3 | Q&A Generation | 2,500+ validated Q&A pairs |
| M1.4 | Pair Extraction | 50K+ training pairs |
| M1.5 | Export | training_pairs.parquet ready |

### 13.2 Phase 2: Embedding Training

**Duration:** 1 week
**Goal:** Fine-tune embeddings, benchmark against baselines

| Milestone | Deliverable |
|-----------|-------------|
| M2.1 | Training script with sentence-transformers |
| M2.2 | Trained model checkpoint |
| M2.3 | Benchmark results vs OpenAI/Cohere |
| M2.4 | Validation on held-out test set |

### 13.3 Phase 3: MU Integration

**Duration:** 1-2 weeks
**Goal:** Ship fine-tuned embeddings as MU default

| Milestone | Deliverable |
|-----------|-------------|
| M3.1 | Integration with `mu context` |
| M3.2 | A/B testing infrastructure |
| M3.3 | Production deployment |
| M3.4 | Documentation and release notes |

### 13.4 Phase 4: The Flywheel

**Duration:** Ongoing
**Goal:** Community growth, continuous improvement

| Milestone | Deliverable |
|-----------|-------------|
| M4.1 | Open-source pipeline |
| M4.2 | Community contribution guide |
| M4.3 | Automated retraining pipeline |
| M4.4 | Multi-language expansion |

---

## 14. Risks & Mitigations

### 14.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| MU build failures on some repos | High | Low | Skip failed repos, target 80% success |
| LLM generates invalid node references | Medium | Medium | Validation step filters bad data |
| Training pairs too homogeneous | Medium | High | Diverse question categories, hard negatives |
| Embeddings don't improve retrieval | Low | Critical | Validate on held-out set before integration |

### 14.2 Resource Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| LLM costs exceed budget | Low | Medium | Monitor costs, use Haiku where possible |
| Pipeline takes too long | Medium | Low | Checkpoint saves, can resume |
| GitHub rate limiting | Low | Low | Use authenticated requests |

### 14.3 Quality Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Training data quality issues | Medium | High | Manual spot checks, validation step |
| Overfitting to specific repos | Medium | Medium | Diverse repo selection, held-out test |

---

## 15. Appendix

### 15.1 Glossary

| Term | Definition |
|------|------------|
| **Anchor** | The query text or node representation in a training triplet |
| **Positive** | A semantically related item that should be close in embedding space |
| **Negative** | An unrelated item that should be far in embedding space |
| **Hard Negative** | A negative from the same codebase (harder to distinguish) |
| **Triplet** | Training format: (anchor, positive, negative) |
| **MU** | Machine Understanding - semantic code compression tool |
| **MUBASE** | MU's graph database format (DuckDB-based) |
| **SIGMA** | Synthetic Understanding through Graph-Manifold Alignment |

### 15.2 References

- Product Brief: `docs/analysis/product-brief-mu-sigma-2025-12-10.md`
- MU Documentation: `CLAUDE.md`
- MU Graph Schema: `src/mu/kernel/CLAUDE.md`

### 15.3 Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-10 | imu | Initial PRD |

---

## Document Status

**Status:** Approved for Implementation
**Approved By:** imu
**Approval Date:** 2025-12-10

---

*El. Psy. Congroo.* 🍌
