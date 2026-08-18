## Why

Phase 2 proves a fixed four-agent review pipeline, but adding or changing a review role still requires edits to orchestration code and to a coordinator prompt that names every role. Review agents should instead be self-describing, portable Agent Skills packages that the trusted host discovers and that supported coding harnesses load through their native Agent Skills mechanisms.

## What Changes

- Replace the fixed reviewer roster with deterministic discovery of trusted review-agent directories containing Agent Skills-standard `SKILL.md` files.
- Express every reviewer and the coordinator in `SKILL.md` and use namespaced Agent Skills `metadata` strings to declare the review-bot kind, input profile, output contract, ordering, and per-reviewer coordinator-policy reference.
- Validate every discovered skill against the Agent Skills standard and the review-bot metadata contract before any agent runs; reject duplicate names, unsupported resources, escaping references, and invalid definitions.
- Adapt each supported coding harness to load only the selected trusted Agent Skill through a harness-native mechanism, with no implicit activation of skills supplied by the pull-request repository.
- Make scheduling and coordination roster-agnostic: require one registered coordinator, run every selected registered reviewer with bounded concurrency, preserve deterministic result order and partial failures, and give the coordinator a generated catalog plus attributed results rather than a hard-coded role list.
- Retain the current four reviewer roles and coordinator as built-in Agent Skills with behavior equivalent to Phase 2.

This change does not add risk tiers, re-reviews, break glass, hosted execution, or new review categories. Registration discovers eligible agents; later selection policy may choose a subset, but this change selects every valid built-in reviewer.

## Capabilities

### New Capabilities

- `review-bot/agent-skill-registry`: Trusted discovery, validation, metadata, native harness loading, and auditable registration of review agents packaged according to the Agent Skills standard.

### Modified Capabilities

- `review-bot/agent-pipeline`: Replace the fixed named roster and coordinator role list with deterministic execution and coordination of the dynamically discovered reviewer set while preserving bounded concurrency and partial-failure behavior.

## Impact

- Replaces role prompt files and hard-coded `AgentSpec` construction with built-in Agent Skills packages, a registry loader, harness adapters, and generated run/catalog artifacts.
- Changes the runner contract for Pi and Codex so selected skills are activated natively and untrusted target-repository skills are not available to review runs.
- Updates coordinator inputs and instructions to interpret any validated registered role from its supplied coordination policy.
- Adds an Agent Skills reference validator dependency or an equivalent standards-conformance check, plus deterministic and real-harness integration evidence.
- Does not change GitHub App authentication, provider diff handling, final location validation, head-SHA freshness checks, review schema, or GitHub posting semantics.

## Non-goals

- Loading review agents from the pull-request checkout, user-global skill directories, remote registries, or arbitrary command-line paths.
- Inventing a private skill format or requiring harness-specific copies of a review role.
- Allowing a skill to select arbitrary filesystem paths, tools, models, timeouts, or posting behavior.
- Unbounded process fan-out merely because more skills are registered.
