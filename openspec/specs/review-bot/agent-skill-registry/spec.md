# Agent Skill Registry Specification

## Purpose

Provide a trusted registry of self-contained review agents whose prompts and optional Agent Skills packages can be loaded without hard-coded role wiring.

## Requirements

### Requirement: Discover trusted agent packages
The system SHALL discover review agents only from configured application-owned roots by finding agent directories that contain a file named exactly `agent.yaml`. It MUST NOT register agents or skills discovered from the pull-request checkout, user-global locations, or other harness-default locations.

#### Scenario: Built-in agents are present
- **WHEN** the review run starts with valid agent directories under the built-in registry root
- **THEN** the system registers every eligible agent in deterministic order

#### Scenario: Pull request contains an agent or skill
- **WHEN** the checked-out pull request contains an `agent.yaml` or `.agents/skills/untrusted/SKILL.md`
- **THEN** neither definition is present in the review registry or any review harness catalog

#### Scenario: No reviewers are registered
- **WHEN** discovery produces no valid reviewer agents
- **THEN** the system stops before starting an agent or posting to GitHub and reports that no trusted reviewers are available

#### Scenario: Coordinator cardinality is invalid
- **WHEN** discovery produces zero or more than one valid coordinator agent
- **THEN** the system stops before starting an agent and reports the coordinator cardinality error

### Requirement: Validate the agent package contract
Every registered agent SHALL have a valid `review-bot/v1` manifest containing its name, kind, description, prompt path, symbolic inputs, output schema, and integer order. The agent name SHALL match its parent directory. Reviewer agents SHALL additionally declare a coordinator-policy path. All declared files SHALL be regular readable files contained within the agent directory after symlink resolution.

#### Scenario: Complete reviewer package
- **WHEN** a reviewer manifest satisfies the `review-bot/v1` contract
- **THEN** the system derives its identity, prompt, assigned inputs, output validation, coordinator policy, deterministic order, and contract version from that package

#### Scenario: Complete coordinator package
- **WHEN** a coordinator manifest satisfies the `review-bot/v1` contract
- **THEN** the system registers it as the singleton coordinator with its own prompt and assigned coordinator inputs

#### Scenario: Unsupported symbolic input
- **WHEN** an agent requests an input resource outside the approved contract
- **THEN** registry construction fails before the agent can read an arbitrary workspace path

#### Scenario: Declared path escapes the package
- **WHEN** the prompt or coordinator-policy path is absolute, traverses outside the agent directory, resolves through a symlink outside it, or does not name a regular readable file
- **THEN** registry construction fails before any agent starts

#### Scenario: Duplicate agent names
- **WHEN** two discovered packages declare the same agent name
- **THEN** registry construction fails explicitly rather than shadowing or merging either package

### Requirement: Support optional Agent Skills-standard capabilities
An agent SHALL have its own prompt and MAY contain zero or more skill directories beneath its `skills/` directory. Every bundled skill SHALL conform to the Agent Skills standard, including a standards-valid `SKILL.md`, and SHALL preserve the standard relative semantics of optional `scripts/`, `references/`, and `assets/` resources. A skill is a capability available to its owning agent and is not itself a registered review agent.

#### Scenario: Prompt-only agent
- **WHEN** an agent package contains no skills
- **THEN** the harness runs the agent using its prompt without requiring a `SKILL.md`

#### Scenario: Agent has one skill
- **WHEN** a package contains one valid Agent Skill
- **THEN** the harness makes that skill available natively to the owning agent

#### Scenario: Agent has multiple skills
- **WHEN** a package contains multiple valid Agent Skills
- **THEN** the harness exposes all and only those application-provided skills in deterministic skill-name order for that agent invocation

#### Scenario: Invalid Agent Skill
- **WHEN** a bundled `SKILL.md` violates a normative Agent Skills constraint
- **THEN** registry construction fails with the owning agent, skill path, and validation error before any agent starts

#### Scenario: Skill declares allowed tools
- **WHEN** a bundled `SKILL.md` contains the experimental Agent Skills `allowed-tools` field
- **THEN** the field does not expand the tools or filesystem permissions granted by the review-bot runner

### Requirement: Isolate native harness loading
For each selected agent, the system SHALL supply the agent prompt normally and make only that agent's application-provided bundled skills available through the configured harness's native Agent Skills mechanism. The system MUST NOT simulate skill activation by concatenating `SKILL.md` bodies into the agent prompt, and it MUST NOT expose user, admin, or pull-request-provided skills. Capabilities bundled into the selected harness binary by its provider are part of the trusted harness boundary, not application-provided agent skills.

#### Scenario: Pi agent starts
- **WHEN** a selected agent runs through Pi
- **THEN** Pi receives the agent prompt and loads only the agent's optional skills through native explicit skill paths with ambient discovery disabled

#### Scenario: Codex agent starts
- **WHEN** a selected agent runs through Codex
- **THEN** Codex uses clean temporary `HOME` and `CODEX_HOME` roots, receives only the minimum forwarded authentication material, discovers only the agent's application-provided optional skills from an isolated trusted Agent Skills location, fails closed if the container has admin skills, and does not discover user or pull-request skills

#### Scenario: Unsupported harness is selected
- **WHEN** the configured command has no adapter that can provide isolated native Agent Skills loading
- **THEN** the run fails before starting any reviewer and identifies the unsupported harness

### Requirement: Isolate assigned review resources
The system SHALL keep host-produced review artifacts outside the checked-out repository and SHALL expose to each agent only its declared symbolic resources plus the clean source checkout. Unassigned diff, catalog, and result artifacts MUST NOT appear within that agent's repository or invocation view.

#### Scenario: Filtered reviewer runs
- **WHEN** a reviewer is assigned `review-diff` but not `provider-diff`
- **THEN** its invocation contains the filtered diff and clean source checkout but no path to the complete provider diff artifact

#### Scenario: Safety reviewer runs
- **WHEN** safety is assigned `provider-diff`
- **THEN** its invocation contains the complete provider diff without making that artifact visible to filtered reviewers

### Requirement: Preserve an agent registry and selection audit record
The system SHALL write a deterministic run manifest containing each discovered agent's name, kind, validated contract version, ordering value, assigned symbolic inputs, package digest, selected skill names, selection status, and harness identity without recording secrets or arbitrary skill resource contents.

#### Scenario: Registry is unchanged across runs
- **WHEN** two runs use byte-identical agent packages and the same harness configuration
- **THEN** their ordered registry entries and package digests are identical

#### Scenario: Agent package changes
- **WHEN** an agent manifest, prompt, coordinator policy, or bundled skill resource changes
- **THEN** the corresponding package digest changes even if the agent name and order stay the same
