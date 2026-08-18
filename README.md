# PR Review Bot

A correctness-focused PR review bot that posts line comments as a GitHub App.

This repository contains the review bot itself. It is developed independently
from the projects it reviews (for example, `deos`). The current implementation
is a local CLI; later phases may add risk tiers, re-reviews, a webhook server,
and optional orchestration integration.

## Current phase

**Registered-agent local CLI with deterministic diff filtering**

- Fetch a PR diff via GitHub App installation token.
- Clone the repository and check out the exact PR head SHA.
- Preserve the complete provider diff while deterministically filtering
  generated, vendored, and lockfile sections from lower-noise review input.
- Discover correctness, API-reality, tests, safety, and coordinator from
  application-owned agent packages under `review_bot/agents/builtin/`.
- Strictly validate each `agent.yaml`, prompt, coordination policy, optional
  Agent Skills package, containment boundary, and deterministic package digest
  before inspecting a pull request.
- Run every registered reviewer with bounded concurrency. Safety receives the
  complete provider diff; filtered reviewers receive only the filtered diff.
- Load only an agent's own optional skills through Pi or Codex native Agent
  Skills support, with ambient and pull-request skill discovery disabled.
- Run the registered roster-agnostic coordinator with an identity-bearing agent
  catalog and attributed results.
- Validate every finding against the complete provider diff and current head SHA.
- Post the review as the GitHub App.

See `openspec/changes/discoverable-review-agent-skills/` for the approved
proposal, specifications, design, and implementation tasks. Risk tiers and
conditional agent selection remain later scope.

With `--keep-workspace`, operators can inspect the exact checkout under
`source/` and these sibling `host-artifacts/` files:

- `provider-diff.diff` — the unchanged provider response used by safety,
  coordination, and final line validation;
- `review-diff.diff` — complete retained file sections used by correctness,
  API-reality, and tests;
- `diff-filter.json` — deterministic excluded path, category, and matched-rule
  records; and
- `run-manifest.json` — validated registry identity, selection, ordering,
  symbolic inputs, package digests, skills, and harness;
- `agent-catalog.json` — the coordinator's trusted roster and per-agent policy;
- `raw-findings.json` — roster-ordered, identity-bearing successes, empty
  results, and failures passed to the coordinator; and
- `unposted-review.json` — the exact review payload retained before dry-run or
  posting.

## Development notes

- Python project managed with `uv`, `pyproject.toml`, `ruff`, `pyright`, and
  `pytest`.
- GitHub App credentials and workspace paths live in the ignored local `.env`.
- Install dev dependencies with `uv sync --extra dev`.
- Run checks: `uv run pytest`, `uv run ruff check review_bot tests`,
  `uv run pyright review_bot tests`.
- Supported harnesses are detected explicitly. Pi is launched with ambient
  resources disabled and explicit `--skill` paths. Codex is launched from an
  isolated capsule with clean `HOME` and `CODEX_HOME`, ignored user config and
  rules, and only the owning agent's staged skills.
