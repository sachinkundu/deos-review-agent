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
- Show truthful pipeline and reviewer progress as work starts and settles while
  preserving registry-ordered results for coordination and artifacts.
- Load only an agent's own application-provided optional skills through Pi or
  Codex native Agent Skills support. User and pull-request skill discovery is
  disabled, and Codex runs fail closed if the container has admin skills under
  `/etc/codex/skills`. OpenAI-bundled system skills remain part of the trusted
  Codex harness rather than the per-agent application registry.
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
  posting; and
- `progress.json` — the latest complete, sanitized
  `review-progress-snapshot/v1` state, atomically replaced after each observable
  transition.

## Progress and retained status

Review runs accept `--progress auto|plain|json|off` and default to `auto`:

- `auto` uses a colorful Rich live view when standard error is an interactive
  terminal and stable plain lines otherwise;
- `plain` writes one human-readable transition per standard-error line;
- `json` writes only `review-progress-event/v1` JSON objects to standard error,
  one per line; existing diagnostics are preserved on standard output so the
  event stream remains independently parseable; and
- `off` suppresses all new progress output without changing review behavior.

Progress shows pipeline phases, every selected reviewer in registry order,
immediate settlement, elapsed time, configured timeouts, partial failures, and
handled interruption. It never shows percentages or model ETAs, and it does not
retain credentials, prompts, model input/output, finding bodies, repository
contents, or subprocess commands.

Inspect a retained workspace without GitHub authentication, model execution,
posting, or file mutation:

```bash
review-bot status https://github.com/OWNER/REPO/pull/NUMBER
review-bot status https://github.com/OWNER/REPO/pull/NUMBER --json
```

Use `--workspace-root PATH` when the run used a non-default root. A normal run
still removes the entire PR workspace, including `progress.json`; use
`--keep-workspace` when retained status is required.

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
  rules, only the owning agent's staged application skills, and a fail-closed
  check for container-admin skills. Codex-bundled system skills are trusted as
  part of the selected harness binary.
