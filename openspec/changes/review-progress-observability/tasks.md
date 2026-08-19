## 1. Progress Contract and State

- [x] 1.1 Add the Rich runtime dependency and package an exact JSON Schema for `review-progress-snapshot/v1`.
- [x] 1.2 Implement typed progress phases, states, events, work items, UTC/monotonic timing, and bounded curated messages.
- [x] 1.3 Implement plain, JSON, Rich live, and disabled stderr renderers with `auto` TTY selection and `NO_COLOR` support.
- [x] 1.4 Implement the thread-safe progress controller, atomic same-directory snapshot replacement, schema validation, and observer-failure isolation.
- [x] 1.5 Add deterministic unit tests for rendering, sequencing, elapsed timing, schema strictness, atomic reads, sanitization, and observer failures.

## 2. Immediate Reviewer Settlement

- [x] 2.1 Replace buffered executor mapping with indexed futures and immediate start/settlement callbacks while preserving registry-ordered results.
- [x] 2.2 Test queued versus running state under bounded concurrency, out-of-order completion, stable result order, partial failure, and callback isolation.

## 3. CLI Lifecycle and Retained Status

- [x] 3.1 Add `--progress auto|plain|json|off` validation before external work and instrument every specified pipeline phase with truthful terminal/skipped states.
- [x] 3.2 Bind complete retained state after workspace creation, track reviewer/coordinator outcomes and provider review URL, and finalize existing exit outcomes without changing cleanup.
- [x] 3.3 Add handled-interruption finalization that restores live rendering, records interrupted active work when possible, and preserves interruption semantics.
- [x] 3.4 Add provider-free `review-bot status <PR_URL> [--workspace-root PATH] [--json]` with exact snapshot validation and stable human output.
- [x] 3.5 Add deterministic CLI tests for mode equivalence, stdout/stderr separation, early failures, skip/partial/all-failure paths, status side-effect freedom, retention/cleanup, and interruption.

## 4. Documentation and Deterministic Verification

- [x] 4.1 Document progress modes, JSON stderr, retained `progress.json`, status inspection, sanitization, and cleanup behavior in README/operator guidance.
- [x] 4.2 Run the complete pytest, Ruff format/lint, Pyright, strict OpenSpec, package-resource, and diff checks; resolve every failure.

## 5. Real Exact-Head Proof and PR Evidence

- [x] 5.1 Run the implementation against a real pull request at its current head with the ignored environment file referenced in place, using no-post retained-workspace proof before any provider posting.
- [x] 5.2 Validate retained JSON events and `progress.json`, inspect status without mutation, and capture truthful terminal/status visual evidence with exact command, versions, target head, timestamps, and scope.
- [ ] 5.3 Attach deterministic and real-run evidence to the final ready-for-review implementation PR, verify the PR head and provider-visible evidence, and complete the checklist.
