## Why

We need a fast, correctness-focused PR review step that catches real bugs and claim mismatches before human review. Existing ad-hoc review attempts (`cloglog`) showed that structured output, diff-aware line validation, and a coordinator that filters noisy agent output are the keys to useful bot reviews. This change builds the smallest version that can review a real PR and post comments as a GitHub App.

## What Changes

- Add a local CLI entrypoint that takes a PR URL and runs the review end-to-end.
- Add a GitHub App client that mints an installation token, fetches PR metadata and diff, and posts a PR review.
- Add workspace setup that invokes a consumer-provided bootstrap script to prepare the repository and PR branch in an isolated directory.
- Add a correctness review agent that uses an LLM to flag logic bugs, error paths, claim mismatches, and architecture-ordering bugs.
- Add an API-reality review agent that uses an LLM and web-fetch tooling to flag hallucinated or misused APIs and interfaces of any dependency.
- Add a coordinator that deduplicates and rewrites raw findings from both agents into the final review schema.
- Add a JSON schema for agent and coordinator output, with validation before any GitHub POST.
- Validate every `(path, line, side=RIGHT)` against the PR diff before posting; findings that cannot be attached go into the review summary body.
- Skip the review when the PR sender matches the GitHub App bot username to avoid loops.

## What correctness means in Phase 1

The correctness review agent flags only bugs and unsafe behavior, not opinions:

- **Logic bugs**: incorrect conditionals, off-by-one errors, wrong variables, race conditions.
- **Unhandled error paths**: missing validation, unhandled exceptions, silent failures, missing null checks.
- **Claim mismatches**: the PR description claims X but the code implements Y.
- **Architecture-ordering bugs**: wrong lifecycle, state-machine mistakes, cleanup-before-use, invalid event ordering.

The agent must ignore style, formatting, naming, and general refactoring suggestions.

## What API-reality means in Phase 1

The API-reality review agent flags hallucinated or misused provider interfaces:

- API methods, endpoints, request fields, response fields, or webhook headers that do not exist in the dependency's real documentation.
- Misused client libraries, SDK methods, or configuration options.
- Assumed contracts that are not grounded in the provider's published API.

The agent must verify claimed provider behavior by consulting the dependency's published API documentation (for example, through a web-fetch tool).

Out of scope for this change: tests or safety review agents beyond the correctness and API-reality agents, risk tiers, diff filtering beyond lockfiles, re-reviews, break-glass overrides, and integration with external orchestration systems.

## Capabilities

### New Capabilities

- `review-bot/github-integration`: GitHub App authentication, PR metadata/diff fetch, and PR review POST.
- `review-bot/local-workspace`: Clone a repository and check out a PR branch in an isolated workspace.
- `review-bot/correctness-review`: Run a correctness review agent that flags logic bugs, error paths, claim mismatches, and architecture-ordering bugs.
- `review-bot/api-reality`: Run an API-reality review agent that flags hallucinated or misused APIs and interfaces of any dependency.
- `review-bot/agent-pipeline`: Run both review agents concurrently, run a coordinator over their findings, and emit validated structured review output.
- `review-bot/review-posting`: Validate that every inline comment maps to a line in the PR diff and post exactly one issue per comment.

### Modified Capabilities

None.

## Impact

- Introduces a new Python package or module set under the repository root (e.g., `src/review_bot/` or `review_bot/`).
- Adds GitHub App credentials and workspace path configuration that must not be committed.
- Does not change any existing project being reviewed.
- Provides the validated core loop that later phases will extend.

## Non-goals

- Multi-provider model routing.
- Tests or safety review agents beyond the correctness and API-reality agents.
- Risk tiers, diff filtering beyond lockfiles, re-reviews, or break glass.
- Integration with external orchestration systems or persistent workflow state.
- Architecture or style review beyond correctness impact.
- Automated application of suggested fixes.
