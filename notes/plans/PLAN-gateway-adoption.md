# MU: become the top-used gateway tool

Goal (Yavor, 2026-09-22): make MU the tool the gateway team and its agents reach for
first, so we ship fewer bugs and design better. Scope is gateway (C# microservices,
MassTransit). Other languages are best-effort.

## State on 2026-09-22

- Dormant since ~2026-08-10. Not by choice: `/usr/local/bin/mu` was a symlink into
  `target/release/`, a `cargo clean` deleted the binary, and every MCP start since
  failed silently. Fixed: installed via `cargo install --path mu-cli --locked`, MCP
  entry for gateway points at `~/.cargo/bin/mu`. Workspace-root MCP entry removed.
- Survey (Explore agent, full read): builds clean, 455 tests pass, no stubs. Real
  differentiators vs LSP: C# DI receiver resolution, MassTransit publish/consume
  edges, PageRank importance, budgeted overview. Puffery: README benchmark table is
  not reproducible (eval harness gitignored and gone), `mu_sus` claims "untested"
  but has no coverage check, Go/Java/Rust degrade to symbols.

## Defects found today

1. **C# grammar regression, silent.** `tree-sitter-c-sharp` is specified as `"0.23"`;
   the lockfile has 0.23.1, which works. An unlocked `cargo install` resolved 0.23.5,
   and with it every `.cs` file parses "successfully" into an EMPTY module. Fresh
   gateway index: 348 nodes (all Python scripts) from 9098 files, no warning.
   Repro: `mu bootstrap --force` on a dir with one trivial class -> Nodes: 0 with
   0.23.5, Nodes: 3 with 0.23.1.
2. **No per-language extraction report.** Bootstrap prints "Parsed: 8713" for files
   that yielded nothing. It must print nodes-by-language and warn when a language
   with N>0 files produced 0 classes/functions.
3. **Parse failures are discarded.** `ParseResult.error` is never logged in bootstrap.
4. **Install path fragile.** Symlink into target/. Document `cargo install --locked`.

## Work packages (in order)

- [ ] WP1 Fix defect 1 properly: make the C# walker work on 0.23.5 (see grammar diff
      note below), add a contract test that parses a file-scoped-namespace class with
      a primary constructor and a MassTransit consumer and asserts non-empty output.
      Pin with `=` only if the walker fix is not feasible today.
- [ ] WP2 Defects 2 and 3: per-language summary + zero-extraction warning + log parse
      errors. Contract test: bootstrap on a fixture with one .cs and one .py asserts
      the summary lists both languages with counts.
- [ ] WP3 Prove value on real gateway PRs: run `mu impact` / `mu review` on the 4
      candidate PRs (message contract changes) and record hits/misses vs the human
      review. Goes in `notes/evals/gateway-prs-2026-09.md`.
- [ ] WP4 Adoption lever: wire `mu review` output into the gateway PR review poller
      as extra context for the reviewing model (location TBD from poller survey).
- [ ] WP5 Restore an eval harness in-repo (the gitignored one is gone) so ranking and
      review-score tuning have ground truth. Honest README: remove the benchmark
      table until it is reproducible; fix the `mu_sus` "untested" claim.

## Open questions

- Which review poller and where is its plugin point? (agent survey in flight)
- Jev-style decision model: only plausible slot is reranking top-k search hits.
  Not planned; MU's value is local and deterministic.
