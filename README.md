# PR Review Bot

A correctness-focused PR review bot that posts line comments as a GitHub App.

This repository contains the review bot itself. It is developed independently
from the projects it reviews (for example, `deos`). The first phase is a local
CLI; later phases may add a webhook server, additional review agents, and
optional orchestration integration.

## Current phase

**Phase 1 — Local CLI with correctness and API-reality agents**

- Fetch a PR diff via GitHub App installation token.
- Clone the repository and check out the PR branch.
- Run a correctness sub-agent and an API-reality sub-agent concurrently.
- Run a coordinator that deduplicates, filters, and rewrites findings.
- Validate that every finding maps to a line in the PR diff.
- Post the review as the GitHub App.

See `openspec/changes/review-bot-phase-1/proposal.md` for the approved-scope
proposal and `docs/review-bot-proposal.md` for background and learnings.

## Development notes

- Python project managed with `uv`, `pyproject.toml`, `ruff`, `pyright`, and
  `pytest`.
- GitHub App credentials and workspace paths live in the ignored local `.env`.
- Install dev dependencies with `uv sync --extra dev`.
- Run checks: `uv run pytest`, `uv run ruff check review_bot tests`,
  `uv run pyright review_bot tests`.
