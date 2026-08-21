## 1. History contract and deterministic state

- [x] 1.1 Add strict versioned schemas and validators for canonical history, reviewer recheck output, classifications, and action plans.
- [x] 1.2 Implement marker creation/parsing, stable finding/action identities, canonical ordering and digest calculation with ownership checks.
- [x] 1.3 Implement review-cycle selection, pending-target reconstruction, conservative legacy handling, and identical-head no-op behavior.
- [x] 1.4 Implement deterministic reviewer history filtering and count/byte bounds without truncating target identity or relationships.

## 2. GitHub provider operations

- [x] 2.1 Add Link-header REST pagination for reviews, review comments, and issue comments with completeness and duplicate checks.
- [x] 2.2 Add independently paginated GraphQL review-thread reads with explicit `unknown` fallback.
- [x] 2.3 Add top-level reply, general-comment, review/comment read-back, and created-object verification operations.

## 3. Pipeline and trusted agent inputs

- [x] 3.1 Add host-owned recheck resources, audited assignments, and isolation checks to the trusted resource registry.
- [x] 3.2 Add mode-specific strict output validation and closed-world reviewer/coordinator identity checks while preserving roster, concurrency, ordering, and failure behavior.
- [x] 3.3 Integrate history fetch and mode selection before agent execution, including clean-cycle and completed-cycle transitions.
- [x] 3.4 Mark initial runs/findings, retain the proposed payload, and bind all accepted initial findings through provider read-back.
- [x] 3.5 Run recheck classification, retain the action plan, guard head plus conversation before each write, post only status updates, and read each result back.

## 4. Deterministic verification

- [x] 4.1 Add provider contract tests for REST/GraphQL pagination, nullable fields, ownership, reply targeting, and read-back failures.
- [x] 4.2 Add history, cycle, filtering, classification, freshness, idempotency, prompt-injection, and no-new-defect tests.
- [x] 4.3 Add initial/recheck pipeline tests for dry-run artifacts, exact-head/history staleness, partial multi-action stops, no-op reruns, and secret-free retained evidence.
- [x] 4.4 Run formatting, lint, type, unit, and strict OpenSpec validation and record the results.

## 5. Real GitHub proof

- [ ] 5.1 Run the CLI locally against a real PR without posting and retain exact-head history, classification, plan, and no-mutation evidence.
- [ ] 5.2 Use a disposable real PR to post an initial marked finding, advance the head, post a recheck status to the accepted top-level thread, and verify provider IDs, URLs, and diff-line acceptance.
- [ ] 5.3 Repeat the exact-head action to prove no duplicate mutation, capture GitHub App/review/comment screenshots, and retain a redacted proof manifest.
