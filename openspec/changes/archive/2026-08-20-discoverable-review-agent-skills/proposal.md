## Why

Phase 2 proves a fixed four-reviewer pipeline, but adding or changing an agent still requires orchestration edits and a coordinator prompt that names every role. Review agents should instead be registered, self-contained folders with their own prompts and optional portable skills, so the coordinator can handle any validated roster without equating an agent with a skill.

## What Changes

- Replace the fixed reviewer roster with deterministic discovery of trusted agent packages. Each package is an agent folder with an `agent.yaml` contract, a prompt, and zero or more optional skills.
- Treat agents and skills as different concepts: the host launches agents, while an agent may use one or several skills to perform specialized work.
- Require every skill bundled with an agent to follow the Agent Skills `SKILL.md` standard and load through the configured coding harness's native Agent Skills support.
- Validate agent manifests, prompt and policy paths, optional Agent Skills packages, assigned symbolic inputs, and roster cardinality before any agent runs.
- Require one registered coordinator, run every selected registered reviewer with bounded concurrency, and give the coordinator a generated agent catalog plus attributed results instead of a hard-coded role list.
- Keep host-produced diff and context artifacts outside the checked-out repository and expose only each agent's assigned resources.
- Retain correctness, API-reality, tests, safety, and coordinator as built-in agents with behavior equivalent to Phase 2.

This change does not add risk tiers, re-reviews, break glass, hosted execution, or new review categories. Registration discovers eligible agents; later selection policy may choose a subset, but this change selects every valid built-in reviewer.

## Capabilities

### New Capabilities

- `review-bot/agent-skill-registry`: Trusted discovery and validation of prompt-driven agent packages, optional Agent Skills-standard capabilities, native harness loading, and auditable registration.

### Modified Capabilities

- `agent-pipeline`: Replace the fixed named roster and coordinator role list with deterministic execution and coordination of dynamically discovered agents while preserving bounded concurrency and partial-failure behavior.

## Impact

- Replaces top-level role prompt files and hard-coded `AgentSpec` construction with built-in agent packages, a registry loader, harness adapters, and generated run/catalog artifacts.
- Changes Pi and Codex runner setup so an agent's optional skills are loaded natively while target-repository and ambient skills remain unavailable.
- Separates the source checkout from host-produced review artifacts to preserve per-agent input assignments.
- Carries each agent's validated contract version and package digest through catalog, result, and coordinator inputs.
- Does not change GitHub App authentication, provider diff provenance, final location validation, head-SHA freshness checks, review schema, or GitHub posting semantics.

## Non-goals

- Treating an agent as an Agent Skill or requiring every agent to have a skill.
- Loading agents or skills from the pull-request checkout, user-global locations, remote registries, or arbitrary command-line paths.
- Allowing an agent or skill to select arbitrary filesystem paths, tools, models, timeouts, or posting behavior.
- Unbounded process fan-out merely because more agents are registered.
