# MU Eval Harness

Execution-ready eval harness for MU improvement tracking.

## Files

- `data/eval/tasks.v1.json`: task dataset (50-100 tasks across multiple repos)
- `data/eval/tasks.sigma.v1.json`: sigma-only slice for stable cross-ref A/B runs
- `data/eval/tasks.ci.v1.json`: lightweight local slice for CI regression warnings
- `data/eval/trust_suite.v1.json`: MCP trust regression suite definition
- `tools/eval/run_mu.py`: runs tasks against MU CLI and captures raw outputs
- `tools/eval/score.py`: computes evaluation metrics from run outputs
- `tools/eval/report.py`: renders markdown reports and baseline/candidate diffs
- `tools/eval/run_trust_suite.py`: runs fixture-based MCP trust checks
- `tools/eval/generate_graph_context_pairs.py`: builds sigma training pairs with graph neighborhood summaries
- `tools/eval/run_sigma_ablation.py`: runs baseline vs graph-context pairwise embedding ablation

## Baseline Capture

Run from repo root:

```bash
python3 tools/eval/run_mu.py \
  --tasks data/eval/tasks.v1.json \
  --mu-bin target/debug/mu \
  --runs 3 \
  --retries 1 \
  --timeout-s 25 \
  --name mu_baseline
```

Notes:

- Sigma tasks are executed via `mu q` (`tool: muql`) so they run against sigma mubases even when an `embeddings` table is unavailable.
- Local MU tasks still exercise `search/grok/impact/wtf/sus`.

## Cross-Ref A/B (Pre vs Post)

1) Generate datasets:

```bash
python3 tools/eval/generate_tasks_v1.py
```

2) Build pre-fix binary from a clean ref (example: `HEAD` in temp worktree):

```bash
git worktree add /tmp/mu-pre-phase1 HEAD
(cd /tmp/mu-pre-phase1 && cargo build -p mu-cli)
```

3) Run pre and post on sigma-only tasks:

```bash
python3 tools/eval/run_mu.py \
  --tasks data/eval/tasks.sigma.v1.json \
  --mu-bin /tmp/mu-pre-phase1/target/debug/mu \
  --name mu_pre_phase1_ref

python3 tools/eval/run_mu.py \
  --tasks data/eval/tasks.sigma.v1.json \
  --mu-bin target/debug/mu \
  --name mu_post_phase1_ref
```

4) Compare:

```bash
python3 tools/eval/report.py \
  --baseline data/eval/results/<commit>/mu_pre_phase1_ref.json \
  --candidate data/eval/results/<commit>/mu_post_phase1_ref.json \
  --baseline-label pre \
  --candidate-label post \
  --out data/eval/results/<commit>/pre_vs_post.md
```

## Trust Regression Suite (MCP)

Run post-fix trust checks:

```bash
python3 tools/eval/run_trust_suite.py \
  --mu-bin target/debug/mu \
  --name trust_suite_post_phase1
```

Run pre-fix trust checks:

```bash
python3 tools/eval/run_trust_suite.py \
  --mu-bin /tmp/mu-pre-phase1/target/debug/mu \
  --name trust_suite_pre_phase1
```

Outputs:

- `data/eval/results/<commit>/mu_baseline.raw.json`
- `data/eval/results/<commit>/mu_baseline.json`

## Metric Definitions

`score.py` computes:

- `recall_at_1`
- `recall_at_5`
- `first_correct_rank`
- `artifact_noise_ratio`
- `p50_latency_ms`
- `p95_latency_ms`
- `avg_output_tokens`

## Re-score Existing Run

```bash
python3 tools/eval/score.py \
  --run-file data/eval/results/<commit>/mu_baseline.raw.json \
  --out data/eval/results/<commit>/mu_baseline.json
```

## Report

Single summary:

```bash
python3 tools/eval/report.py \
  --summary data/eval/results/<commit>/mu_baseline.json \
  --label baseline
```

Diff baseline vs candidate:

```bash
python3 tools/eval/report.py \
  --baseline data/eval/results/<commit>/mu_baseline.json \
  --candidate data/eval/results/<commit>/mu_after_phase1.json \
  --baseline-label baseline \
  --candidate-label phase1 \
  --out data/eval/results/<commit>/comparison.md
```

## Phase 2.3: Sigma Graph-Context Ablation

1) Build graph-context pairs from sigma triplets:

```bash
python3 tools/eval/generate_graph_context_pairs.py \
  --pairs data/sigma/training/training_pairs.json \
  --mu-bin target/debug/mu \
  --max-pairs 4000 \
  --out data/sigma/training/training_pairs.graph.v1.json
```

2) Run embedding ablation (`baseline` text vs `graph_context` text):

```bash
python3 tools/eval/run_sigma_ablation.py \
  --pairs-file data/sigma/training/training_pairs.graph.v1.json \
  --name sigma_ablation_phase2_3
```

Outputs:
- `data/eval/results/<commit>/sigma_ablation_phase2_3.json`
- `data/eval/results/<commit>/sigma_ablation_phase2_3.md`
