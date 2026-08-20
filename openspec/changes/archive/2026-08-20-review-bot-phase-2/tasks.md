# Tasks: review-bot-phase-2

Implements the approved Phase 2 proposal, specifications, and design. Work is
ordered so deterministic contracts and tests land before live GitHub proof.

## 1. Provider contract and implementation baseline

- [x] 1.1 Re-verify the current GitHub App installation-token, pull-request diff, review creation, and right-side line-comment contracts against official GitHub documentation and a real repository without changing the Phase 1 posting API
- [x] 1.2 Record the Phase 1 baseline behavior and add or preserve deterministic regression coverage for unchanged authentication, head-SHA freshness, diff validation, and review posting

## 2. Deterministic diff filtering

- [x] 2.1 Add ordered raw file-section splitting that preserves complete provider patch text and canonical right-side paths, failing closed on unattributable sections
- [x] 2.2 Implement exact lockfile, vendored path-segment, generated path/filename, and first-20-non-blank-line marker classification with the approved precedence and stable rule identifiers
- [x] 2.3 Write unchanged `provider-diff.diff`, retained-file `review-diff.diff`, and deterministic versioned `diff-filter.json` artifacts while reading marker content from the checked-out Git blob without following worktree symlinks
- [x] 2.4 Add deterministic filtering tests for exact matching, case sensitivity, separator normalization, precedence, marker windows, binary/gitlink/read-failure behavior, empty filtered diffs, mixed diff forms, stable ordering, and manifest output

## 3. Explicit agent inputs and four-agent pipeline

- [x] 3.1 Add an explicit `AgentSpec` contract and update Codex and Pi runners so orchestration declares each agent's input filenames
- [x] 3.2 Register correctness, API-reality, tests, and safety in fixed order and run all four concurrently on every review, including when the filtered diff is empty
- [x] 3.3 Preserve roster-ordered successful and failed results, pass every successful result including empty findings to the coordinator, and stop only when all four agents fail
- [x] 3.4 Add deterministic tests for explicit role inputs, four-agent concurrency, empty filtered input, partial failures, all-agent failure, and complete coordinator attribution

## 4. Tests and safety review roles

- [x] 4.1 Add the tests-agent prompt for concrete changed-behavior regression gaps and ineffective assertions, excluding broad or speculative test requests
- [x] 4.2 Add the safety-agent prompt for evidence-backed usable hardcoded secrets and obvious source-to-sink injection paths, excluding general security commentary
- [x] 4.3 Update shared rules and coordinator guidance for assigned diff views, four distinct evidence standards, full-provider location verification, and the unchanged shared output schema
- [x] 4.4 Add prompt and pipeline tests proving tests/safety schema validation, scope boundaries, full-diff safety visibility, and filtered-file findings surviving full-diff validation

## 5. Review orchestration and operator artifacts

- [x] 5.1 Update shared context to describe `provider-diff.diff`, `review-diff.diff`, and `diff-filter.json` while retaining every provider-reported changed path
- [x] 5.2 Wire artifact construction before agent execution, use the complete in-memory provider diff for final line validation, and keep the unchanged current-head check and GitHub payload path
- [x] 5.3 Update review summaries, CLI text, and documentation to report all four Phase 2 agents, filtered-input audit behavior, and `--keep-workspace` artifact retention accurately
- [x] 5.4 Add deterministic end-to-end CLI tests for artifact failures, four-agent success and partial failure, safety findings on filtered files, unchanged posting semantics, and workspace cleanup/retention

## 6. Deterministic validation and local proof

- [x] 6.1 Run formatting, lint, type checks, the full deterministic test suite, OpenSpec strict validation, and repository secret/diff hygiene checks
- [x] 6.2 Local proof: run the CLI with `--dry-run --keep-workspace` against a real GitHub PR using a newly minted installation token and real agents; inspect both diff views, the manifest, all four raw agent records, and the would-be review payload without posting

## 7. Provider-originated and visual proof

- [x] 7.1 Provider-originated proof: run the real GitHub App against a controlled real PR with a freshly minted installation token and current `head_sha`; confirm GitHub accepts every inline `(path, line, side=RIGHT)` comment and that a safety finding can survive filtering of its file for other agents
- [x] 7.2 Visual proof: capture screenshots of the GitHub App configuration, PR review state, and accepted posted comments, and retain or attach the strongest available evidence for the final implementation PR
- [x] 7.3 Verify credentials and private keys remain ignored and absent from committed files, diffs, captured logs, and screenshots

## 8. Final implementation PR

- [x] 8.1 Complete all task checkboxes and open one ready-for-review implementation PR citing planning PRs #4, #5, and #6, the implemented requirements, deterministic validation, distinctly labeled local/provider/visual proof, and rollback scope
