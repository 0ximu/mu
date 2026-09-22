# Eval: `mu review` on four merged gateway PRs (2026-09-22)

Setup: gateway worktree at origin/dev 584214ee1, index built with the fixed binary
(92,690 nodes). For each PR the worktree was checked out at the squash-merge commit and
`mu review --base <merge>^1` was run. Note the index is post-merge for all four, so impact
data leaks slightly forward; the semantic diff itself reads both refs via `git show`.

| PR | what changed | human review outcome | `mu review` verdict | did MU help? |
|---|---|---|---|---|
| #3364 recurring R12 | 3 new subscription events, 3 new consumers, ServiceBusTopics | 3 rounds, nothing missed | CRITICAL, 707 symbols, 220 downstream | no |
| #3387 subscription link | TransactionRefundFailedConsumer, payment link models | 2 rounds, clean | CRITICAL, 283 symbols, 8 "breaking" | no |
| #3360 supplier identity feed | new outbox + SupplierIdentity events | caught a publish/erasure PII race | HIGH, 334 symbols, 3 "breaking" | no |
| #3416 POS order sync | OrderSyncEventV1 contract + entity + validator | 9 rounds, two HIGHs deferred | HIGH, 196 symbols, 1 "breaking" | no |

## What the output actually contained

- Every "breaking change" was a removed test method or a private helper with 0 dependents.
  Real contract changes (the new event types and their consumers) never appear as a
  distinct section.
- The CHANGED SYMBOLS table is an unranked dump of every added property, import and
  method (707 rows on #3364). Nobody reads that in a PR.
- AUDIT FINDINGS: `R1-orphan` flags EF `DbSet` properties and DTO properties as "possibly
  dead code" because properties have no call edges. `R3-complexity` and `R14-params` are
  generic lint the C# analyzers already cover.
- BLAST RADIUS is wrong. #3387 and #3364 (payments) list
  `commerce/Entities/ProductSupplier.cs` and `ProductSupplierLinkModel.cs` as top affected
  files; neither PR touches commerce. Cause: `lookup_impact` in
  `mu-cli/src/commands/review.rs` resolves changed symbols by bare name
  (`WHERE name = ?1`, file path ignored), so a changed property called `Id` or `Amount`
  pulls in dependents of every `Id` in the codebase, capped at 50. The risk score is
  built on that number, so HIGH/CRITICAL is meaningless.

## What did work

`mu impact <Event> -e publishes,subscribes -d 1` against `git grep IConsumer<Event>`:

| contract | MU consumers | grep consumers | MU also found |
|---|---|---|---|
| SubscriptionChargeOutcomeEvent | notifications, webhooks | same 2 | publisher PublishCoreAsync |
| SubscriptionAgreementStatusChangedEvent | notifications, webhooks | same 2 | publisher TryPublishAsync |
| SubscriptionCustomerNotificationEvent | notifications | same 1 | publisher NotifyAsync |
| RegistrationActivatedDTO | api, payments, crm, notifications | same 4 | publisher + 4 test helpers |

Exact match on every contract tried, plus the publisher, which grep does not give you.
That is the one output a reviewer of #3364 or #3416 would have pasted into the PR.

## Verdict

`mu review` as shipped would not have changed the outcome of any of the four reviews and
would have added noise to all of them. The graph underneath is accurate for message
contracts. The work is to make the review print the contract blast radius and drop the
rest, not to improve the graph.

## Follow-ups (tracked in notes/plans/PLAN-gateway-adoption.md)

- Defect 5: name-only symbol resolution in `lookup_impact` / `lookup_dependent_names`.
- Defect 6: `R1-orphan` fires on properties; breaking-change list includes test methods.
- WP4 shape: "Message contracts touched" section, depth 1, grouped by service, tests
  separate, publishers and consumers labelled.
