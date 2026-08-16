## Why

We need a fast, correctness-focused PR review step that catches real bugs and claim mismatches before human review. Existing ad-hoc review attempts (`cloglog`) showed that structured output, diff-aware line validation, and a coordinator that filters noisy agent output are the keys to useful bot reviews. This change builds the smallest version that can review a real PR and post comments as a GitHub App.

## What Changes

- Add a local CLI entrypoint that takes a PR URL and runs the review end-to-end.
- Add a GitHub App client that mints an installation token, fetches PR metadata and diff, and posts a PR review.
- Add workspace setup that clones the repository and checks out the PR branch in an isolated directory.
- Add a correctness sub-agent prompt and a coordinator that rewrites raw findings into the final review schema.
- Add a JSON schema for agent and coordinator output, with validation before any GitHub POST.
- Validate every `(path, line, side=RIGHT)` against the PR diff before posting; findings that cannot be attached go into the review summary body.
- Skip the review when the PR sender matches the GitHub App bot username to avoid loops.

Out of scope for this change: tests/safety sub-agents, risk tiers, diff filtering beyond lockfiles, re-reviews, break-glass overrides, and Cloudflare/deos integration.

## Capabilities

### New Capabilities

- `review-bot/github-integration`: GitHub App authentication, PR metadata/diff fetch, and PR review POST.
- `review-bot/local-workspace`: Clone a repository and check out a PR branch in an isolated workspace.
- `review-bot/agent-pipeline`: Run a correctness sub-agent, run a coordinator over its findings, and emit validated structured review output.
- `review-bot/review-posting`: Validate that every inline comment maps to a line in the PR diff and post exactly one issue per comment.

### Modified Capabilities

None.

## Impact

- Introduces a new Python package or module set under the repository root (e.g., `src/review_bot/` or `review_bot/`).
- Adds GitHub App credentials and workspace path configuration that must not be committed.
- Does not change the existing `deos` Workers, Queue consumer, D1 schema, or Linear workflow.
- Provides the validated core loop that later phases will extend.

## Non-goals

- Multi-provider model routing.
- Tests or safety sub-agents beyond the single correctness agent.
- Risk tiers, diff filtering beyond lockfiles, re-reviews, or break glass.
- Integration with Linear, Cloudflare Workers, D1, R2, or the planned `code_review` agent node.
- Architecture or style review beyond correctness impact.
- Automated application of suggested fixes.
