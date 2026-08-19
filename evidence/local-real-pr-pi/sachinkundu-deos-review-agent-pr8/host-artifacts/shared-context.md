# Shared context: PR 8 — Plan discoverable review agents with Agent Skills

## Pull request
- URL: https://github.com/sachinkundu/deos-review-agent/pull/8
- Repository: sachinkundu/deos-review-agent
- Sender: sachinkundu
- Head SHA: 9cbc0c2a4e41737740a6f5fc86b9b0bcd011ee32
- Base SHA: 6feaa0a498712704ed4c75012bb0e9b3974886f0

## PR body
## Approval requested

Approve the combined proposal, specifications, and design for OpenSpec change `discoverable-review-agent-skills`.

The single reviewer decision is whether the registered-agent contract, optional Agent Skills capability model, and trusted discovery architecture are correct before tasks or implementation are generated.

This combined planning PR uses the explicitly requested all-planning-artifacts fast path. The normal separate proposal/specification/design gates are intentionally collapsed for this change.

## Reading order

1. `openspec/changes/discoverable-review-agent-skills/proposal.md`
2. `openspec/changes/discoverable-review-agent-skills/specs/review-bot/agent-skill-registry/spec.md`
3. `openspec/changes/discoverable-review-agent-skills/specs/review-bot/agent-pipeline/spec.md`
4. `openspec/changes/discoverable-review-agent-skills/design.md`

## What is proposed

- Register correctness, API-reality, tests, safety, and coordinator as agent folders with `agent.yaml`, a prompt, and zero or more optional skills.
- Keep agents and skills distinct: agents are scheduled actors; skills are specialized capabilities available within an agent session.
- Require every bundled skill to follow the portable Agent Skills `SKILL.md` standard and load through native Pi or Codex support.
- Discover and strictly validate the trusted built-in agent set without a Python roster.
- Load only an agent's own optional skills with clean harness homes while excluding pull-request and ambient skills.
- Keep the exact source checkout separate from host diff, context, catalog, and result artifacts so each agent sees only its assigned review resources.
- Run any selected reviewer set with bounded concurrency and give the registered coordinator a generated catalog plus attributed results instead of a hard-coded role list.
- Carry agent contract version and package digest through catalog and result identity.
- Preserve the Phase 2 review schema, partial failures, provider-diff validation, and GitHub posting behavior.

The Agent Skills portion is grounded in the current [Agent Skills specification](https://agentskills.io/specification), [client integration guidance](https://agentskills.io/client-implementation/adding-skills-support), [Codex skill loading documentation](https://developers.openai.com/codex/skills/), and [Pi Agent Skills documentation](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/skills.md).

## Approved predecessor

- Phase 2 implementation: #7, merged as `6feaa0a`

## Deliberately absent

- `tasks.md`
- runtime code or dependencies
- migrated agent packages or Agent Skills
- deterministic, real-harness, provider-originated, or visual implementation evidence
- risk tiers, re-reviews, break glass, hosted execution, and new review categories

Tasks and implementation remain blocked on approval and merge of this planning contract.

## Validation

- `openspec validate discoverable-review-agent-skills --strict` — valid after review-feedback revision
- `git diff --cached --check` — passed before each commit
- review feedback revision: `9cbc0c2`

## Tracking

- OpenSpec change: `discoverable-review-agent-skills`
- Linear issue: none required or linked for this repository change

## Linked issue references
- #7

## Changed files
- openspec/changes/discoverable-review-agent-skills/.openspec.yaml
- openspec/changes/discoverable-review-agent-skills/design.md
- openspec/changes/discoverable-review-agent-skills/proposal.md
- openspec/changes/discoverable-review-agent-skills/specs/review-bot/agent-pipeline/spec.md
- openspec/changes/discoverable-review-agent-skills/specs/review-bot/agent-skill-registry/spec.md

## Validation results
- Bootstrap: no bootstrap script found

## Inputs for this review
- This file: `shared-context.md`
- Complete provider-originated PR diff: `provider-diff.diff` (safety, coordination, and line validation)
- Filtered agent-review diff: `review-diff.diff` (correctness, API-reality, and tests)
- Operator-only exclusion audit manifest: `diff-filter.json` (not assigned to review agents)
- The clean repository is available separately as `repository/`.
