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

## Repository layout

```text
review_bot/               Python package for the review bot
  review.py               CLI entrypoint and end-to-end pipeline
  github.py               GitHub App auth, PR fetch, review POST
  workspace.py            Clone/checkout/bootstrap/cleanup
  shared_context.py       Assemble shared-context.md for agents
  diff_validator.py       Parse diff and validate finding locations
  schema.py / schema.json Review output schema and validation
  coordinator.py          Coordinator agent wiring
  agents/
    runner.py             Agent runner abstraction and codex driver
  prompts/
    correctness.md        Correctness agent prompt
    api-reality.md        API-reality agent prompt
    coordinator.md        Coordinator prompt
tests/                    Deterministic pytest suite
openspec/                 OpenSpec planning artifacts
  config.yaml             Project context and artifact rules
  changes/review-bot-phase-1/
    proposal.md
    specs/                (created in the specs gate)
    design.md             (created in the design gate)
    tasks.md              (created in the implementation gate)
docs/                     Background docs and learnings
```

## Development notes

- Python project managed with `uv`, `pyproject.toml`, `ruff`, `pyright`, and
  `pytest`.
- GitHub App credentials and workspace paths live in the ignored local `.env`.
- Install dev dependencies with `uv sync --extra dev`.
- Run checks: `uv run pytest`, `uv run ruff check review_bot tests`,
  `uv run pyright review_bot tests`.
