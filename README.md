# PR Review Bot

A correctness-focused PR review bot that posts line comments as a GitHub App.

This repository contains the review bot itself. It is developed independently
from the projects it reviews (for example, `deos`). The first phase is a local
CLI; later phases may add a webhook server, additional review agents, and
optional orchestration integration.

## Current phase

**Phase 1 — Local CLI with one correctness agent**

- Fetch a PR diff via GitHub App installation token.
- Clone the repository and check out the PR branch.
- Run a correctness sub-agent and a coordinator.
- Validate that every finding maps to a line in the PR diff.
- Post the review as the GitHub App.

See `openspec/changes/review-bot-phase-1/proposal.md` for the approved-scope
proposal and `docs/review-bot-proposal.md` for background and learnings.

## Repository layout

```text
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
