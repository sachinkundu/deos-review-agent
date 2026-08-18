## Why

Phase 1 proves that the bot can fetch and review a real pull request with correctness and API-reality agents, but it does not independently inspect regression coverage or common security hazards. Phase 2 adds those focused review passes and removes low-signal diff noise while preserving the same local CLI and GitHub posting flow.

## What Changes

- Add a tests review agent that flags missing or ineffective regression coverage only when a changed behavior has a concrete, credible failure path.
- Add a safety review agent that flags high-confidence hardcoded-secret exposure and obvious injection paths, with a concrete exploit or failure scenario and suggested fix.
- Run the tests and safety agents alongside the existing correctness and API-reality agents on every review, using the existing concurrent pipeline and partial-failure behavior.
- Filter generated files, vendored dependencies, and lockfiles from agent inputs while retaining the original GitHub diff for right-side line validation and review posting.
- Reuse the existing shared context and structured review schema across all four review agents and the coordinator.

Risk classification and trivial/lite/full agent-selection tiers are explicitly out of scope for Phase 2. Phase 2 does not classify a pull request before review and does not select agents based on diff size, path, or inferred risk; those decisions are deferred to Phase 3.

## Capabilities

### New Capabilities

- `review-bot/tests-review`: Focused review of whether changed behavior has effective regression coverage, without requesting broad or speculative tests.
- `review-bot/safety-review`: Focused review for hardcoded secrets and obvious injection paths, with high-confidence evidence requirements.
- `review-bot/diff-filtering`: Deterministically exclude generated, vendored, and lockfile noise from agent inputs while preserving the full provider diff for validation and posting.

### Modified Capabilities

None. The Phase 1 agent runner, shared context, coordinator, schema, and concurrent pipeline are extended by implementation but retain their existing external contracts.

## Impact

- Adds tests and safety prompt definitions and registers both agents in the local review run.
- Adds deterministic diff-filtering logic and tests around filtered versus full-diff handling.
- Updates coordinator context so findings from four named agents are interpreted consistently.
- Does not change GitHub App authentication, review payload semantics, CLI invocation, or the provider-originated proof boundary established in Phase 1.

## Non-goals

- Pull-request risk classification or trivial/lite/full tiers.
- Conditional agent selection based on diff size, file paths, or security sensitivity.
- Re-reviews, prior-comment reconciliation, or break-glass handling.
- Webhook or hosted-service execution.
- External orchestration, persistence, or automated fix application.
