# PR Review Bot

A correctness-focused PR review bot that posts line comments as a GitHub App.

This repository contains the review bot itself. It is developed independently
from the projects it reviews (for example, `deos`). The current implementation
is a local CLI; later phases may add risk tiers, re-reviews, a webhook server,
and optional orchestration integration.

## Current phase

**Phase 2 — Four-agent local CLI with deterministic diff filtering**

- Fetch a PR diff via GitHub App installation token.
- Clone the repository and check out the exact PR head SHA.
- Preserve the complete provider diff while deterministically filtering
  generated, vendored, and lockfile sections from lower-noise review input.
- Run correctness, API-reality, tests, and safety agents concurrently on every
  review. Safety always receives the complete provider diff.
- Run a coordinator that deduplicates, filters, and rewrites findings.
- Validate every finding against the complete provider diff and current head SHA.
- Post the review as the GitHub App.

See `openspec/changes/review-bot-phase-2/` for the approved proposal,
specifications, design, and implementation tasks. Risk tiers and conditional
agent selection remain Phase 3 scope.

With `--keep-workspace`, operators can inspect:

- `provider-diff.diff` — the unchanged provider response used by safety,
  coordination, and final line validation;
- `review-diff.diff` — complete retained file sections used by correctness,
  API-reality, and tests;
- `diff-filter.json` — deterministic excluded path, category, and matched-rule
  records; and
- `raw-findings.json` — roster-ordered successes, empty results, and failures
  passed to the coordinator.

## Development notes

- Python project managed with `uv`, `pyproject.toml`, `ruff`, `pyright`, and
  `pytest`.
- GitHub App credentials and workspace paths live in the ignored local `.env`.
- Install dev dependencies with `uv sync --extra dev`.
- Run checks: `uv run pytest`, `uv run ruff check review_bot tests`,
  `uv run pyright review_bot tests`.
