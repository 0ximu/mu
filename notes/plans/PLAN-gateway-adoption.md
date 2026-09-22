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

## 2026-09-22 smoke test on the gateway index (after the grammar fix)

Index at gateway origin/dev 584214ee1: 92,690 nodes, 229,770 edges, 10,912 classes
(before the fix: 0 C# classes).

`mu impact RegistrationActivatedDTO` against `git grep IConsumer<RegistrationActivatedDTO>`:

| query | result | verdict |
|---|---|---|
| `-e subscribes -d 1` | 4 consumers (api, payments, crm, notifications) | exact match with grep |
| `-e publishes -d 1` | 1 real publisher (Shift4PostApprovalService.ExecuteAsync) + 4 test helpers | correct; tests should be labelled or split |
| `--cross-service -d 1` | consumers + publisher + tests + 2 services that pass the DTO | usable |
| `--cross-service` (unbounded) | ~40 nodes, most of companyadmin | noise, unusable in a review |

Design consequence for WP4: the review output for a changed message contract should be
the depth-1 publishers/consumers grouped by service with the edge type shown, test
nodes listed separately, and no transitive walk by default. Unbounded depth stays
opt-in.

## Defects found by the 2026-09-22 PR eval (see notes/evals/gateway-prs-2026-09.md)

5. **Name-only symbol resolution in `mu review` impact** (fixed on this branch).
   `lookup_impact` matched `nodes WHERE name = ?1` ignoring the file, so any changed `Id`
   or `Amount` property collected dependents of every `Id` in gateway. Payments PRs listed
   commerce files as top affected. Now scoped to the changed symbol's file (exact or
   suffix match), pinned by `impact_scope_tests`.
6. **Review noise** (open). `R1-orphan` flags C# properties and EF `DbSet`s as dead code;
   BREAKING lists removed test methods with 0 dependents; CHANGED SYMBOLS is an unranked
   dump of every added property and import. None of this belongs in a PR comment.

## WP4 shape, informed by the eval

Output for a gateway PR is one section, "Message contracts touched": for each changed
type under `contracts/Events/**` or any type that has publishes/subscribes edges, the
depth-1 publishers and consumers grouped by service with the edge type, tests listed
separately. Nothing else from today's `mu review` output goes into the comment until
defect 6 is fixed.

Poller plug-in point (verified by poller-find, 2026-09-22): dominaite-tools crate
`crates/review-core/src/review.rs`, `extra_context` accumulator at line ~1271, prompt
assembled at ~1605; providers are plain `fn(...) -> String` returning a markdown section.
Inputs there: detached worktree at PR head (`setup_worktree`, ~612), `changed_files`,
`pr.head_sha`, `prev_sha`. Caveat: the poller is not currently running on this machine
(`target/` absent, LaunchAgents not loaded), so wiring it in also means rebuilding and
reloading it.

## WP4 progress (2026-09-22)

Done on this branch: `mu review` prints `MESSAGE CONTRACTS TOUCHED` (depth-1 publishers
and consumers by service, tests counted separately) and `CONSTRUCTOR CHANGES` (explicit
`new T(`, target-typed `new(` on lines naming T, DI registrations, and files with
construction sites the diff does not touch). Module `mu-cli/src/commands/review_sections.rs`,
end-to-end test `test_review_reports_contract_parties_and_constructor_sites`.

Open, in priority order:
1. Poller wiring (dominaite-tools): `mu bootstrap` then `mu review --base <base> --format json`
   in the PR worktree; render only the two sections into `extra_context`. Poller is not
   running on this machine; rebuild + reload the LaunchAgents as part of the change.
2. Detect `Publish(new T(...))` (non-generic) as a publish edge. Check how many gateway
   publishers use that form before deciding.
3. Parse primary constructors as constructors (5 uses in gateway today).
4. Defect 6: drop `R1-orphan` for properties, drop test methods from BREAKING, and stop
   printing the CHANGED SYMBOLS dump by default.
5. Risk score still counts the old signals; recompute from the two sections once 4 lands.
