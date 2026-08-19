## Why

Long-running review runs can remain silent while concurrent model agents are active, so an operator cannot distinguish useful work from a stalled process. The real PR #10 dry run and the discovery handoff at `/Users/sachin/Documents/Codex/2026-08-18/outputs/review-bot-progress-indicator-handoff.md` establish the need for truthful phase and reviewer state without fabricated percentages or model ETAs.

## What Changes

- Add operator-selectable progress output with automatic TTY presentation plus stable plain, versioned JSON, and disabled modes.
- Expose pipeline phases, registry-ordered reviewer states, elapsed durations, configured timeouts, partial failures, and final outcomes as they occur.
- Atomically retain a sanitized progress snapshot beside the other host artifacts and add a read-only command for inspecting retained run state.
- Report reviewer completion immediately while preserving deterministic registry-ordered results for coordination and artifacts.
- Keep existing final output, exit codes, model prompts, GitHub requests, review payloads, and exact-head posting safeguards compatible.

## Capabilities

### New Capabilities

- `review-bot/progress-observability`: Truthful terminal and machine-readable progress events, durable sanitized run state, and read-only retained-status inspection for review runs.

### Modified Capabilities

None.

## Impact

- Affects the Python CLI, review orchestration, concurrent agent runner, and host-artifact lifecycle.
- Adds deterministic renderer, persistence, concurrency-ordering, interruption, and sanitization coverage plus a real no-post harness proof.
- May add a terminal-rendering dependency while keeping plain and JSON output independent of terminal control sequences.
- Does not add a web dashboard, remote telemetry, model-output streaming, percentages, ETAs, reviewer-selection changes, coordinator changes, or new GitHub integration behavior.
