## Why

Each review run currently treats the latest pull request diff as a fresh event, so repeated runs can duplicate findings and cannot explain whether an earlier finding is fixed, still present, obsolete, or ambiguous. The bot needs an auditable view of the real GitHub conversation before it can support the intended review, fix, and re-review loop safely.

## What Changes

- Fetch the complete, fully paginated pull request review history, including reviews, inline comments and replies, general comments, and review-thread resolution state when GitHub exposes it to the App.
- Normalize and retain the provider conversation as a versioned snapshot with stable provider identities, deterministic ordering, and a canonical digest; record thread resolution as `unknown` instead of inferring it when GraphQL is unavailable.
- Give each file-scoped reviewer a deterministic filtered history view and give the coordinator the complete history, while treating every provider-authored text field as untrusted task data.
- Add stable identities for new bot findings and conservative matching for unmarked legacy findings.
- Classify prior and current findings as fixed, unfixed, obsolete, new, or ambiguous, with evidence and strictly validated reply or new-comment actions.
- Plan GitHub mutations separately from classification: new findings create comments, owned fixed/unfixed/obsolete findings reply to their existing top-level threads, and ambiguous findings do not mutate GitHub.
- Re-fetch both the exact head and complete conversation immediately before posting; if either the head SHA or history digest changed, retain a stale result and post nothing.
- Read every created provider object back, retain its ID and URL, prevent duplicate comments or replies on identical reruns, and never resolve a review thread automatically.

## Capabilities

### New Capabilities

- `review-bot/review-rechecks`: Complete review-history snapshots, stable finding identity, conservative prior/current matching, five-state classification, and deterministic recheck planning.

### Modified Capabilities

- `github-integration`: Add paginated review, review-comment, issue-comment, and GraphQL review-thread reads; verified bot identity; top-level review-thread replies; and provider read-back.
- `review-posting`: Separate proposed writes from mutation, add stable finding markers and reply actions, guard both head and conversation freshness, and make identical reruns idempotent without resolving threads.
- `agent-pipeline`: Supply bounded history views to reviewers and complete history plus classification rules to the coordinator while preserving attributed, schema-validated results.
- `review-bot/agent-skill-registry`: Add host-owned symbolic review-history resources and prevent pull request content from shadowing or expanding them.
- `review-bot/diff-filtering`: Apply existing path exclusions to file-scoped history views without removing excluded conversations from the complete audit snapshot or final safety checks.

## Impact

- Affects the Python GitHub client, review-run ordering, history and recheck schemas, coordinator contract, trusted agent resources, diff/history filtering, posting planner, retained artifacts, and CLI summaries.
- Requires real GitHub App contract inspection before specs and design are finalized, including REST pagination, reply targeting, GraphQL thread resolution, App identity, permissions, nullable fields, and provider error shapes.
- Adds deterministic provider, normalization, filtering, matching, concurrency, idempotency, and no-secret-leakage tests plus a local real-PR dry run and disposable provider-posting proof.
- Preserves fresh installation tokens, exact-head right-side diff validation, bot-authored PR skipping, current risk-tier behavior, and fail-closed trusted agent validation.

## Non-goals

- Cloudflare Sandbox packaging or deployment, DEOS Workflow integration, D1 or R2 persistence, or capability routing.
- Running coding agents, changing approval or risk-tier policy, or supporting arbitrary public repositories.
- Automatically resolving review threads, editing or deleting earlier comments, or treating absence from the latest diff as proof that a finding is fixed.
