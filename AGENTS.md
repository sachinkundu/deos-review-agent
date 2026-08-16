# Agent guidance

## Demo-first delivery

Before implementing the GitHub integration, inspect the real GitHub provider
contract (GitHub App auth, installation tokens, pull request review API, and
diff line validation) and test against a real repository. Do not infer the wire
format, signature construction, timestamp units, or response contract from a fake
payload.

Separate these claims explicitly:

- **Local proof:** deterministic tests and a locally run CLI review against a
  real PR, without posting to GitHub.
- **Provider-originated proof:** the real GitHub App posts a review on a real
  PR, and the bot's line comments map to diff lines exactly as GitHub accepts
  them.
- **Visual proof:** screenshots of the GitHub App configuration, the PR review
  state, and the posted comments.

Do not describe local-only execution as end-to-end GitHub verification.

## Tool selection

- Use the GitHub CLI (`gh`) or the GitHub REST API for repository, PR, and
  review operations. Prefer API tokens loaded from the ignored local `.env`;
  never print or commit them.
- Use Codex Browser only when a screenshot is needed for visual proof of the
  GitHub web UI.
- For every implementation PR, attach the strongest visual proof available:
  screenshots of the GitHub App configuration, PR review state, and posted
  comments.

## GitHub App invariants

- Mint a short-lived installation token from the App private key for every
  review run; do not reuse tokens across runs.
- Validate every `(path, line, side=RIGHT)` against the PR diff before posting;
  GitHub rejects comments that do not map to a changed line.
- Treat the PR `head_sha` as the review target; do not post against a stale SHA.
- Skip any PR whose `sender` matches the GitHub App bot username to avoid
  review loops.
- Return success for accepted, ignored, and duplicate deliveries when the bot
  is invoked via webhook later; GitHub treats non-2xx responses as failures.
