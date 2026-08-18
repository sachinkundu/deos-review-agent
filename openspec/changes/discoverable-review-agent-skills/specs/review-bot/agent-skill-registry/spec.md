## Purpose

Provide a trusted, portable registry in which review roles are self-describing Agent Skills packages that supported coding harnesses can load without hard-coded role wiring.

## ADDED Requirements

### Requirement: Discover trusted review Agent Skills
The system SHALL discover review agents only from configured application-owned roots by finding skill directories that contain a file named exactly `SKILL.md`. It MUST NOT register skills discovered from the pull-request checkout, user-global skill locations, or other harness-default locations.

#### Scenario: Built-in skills are present
- **WHEN** the review run starts with valid skill directories under the built-in registry root
- **THEN** the system registers every eligible review skill in deterministic order

#### Scenario: Pull request contains a skill
- **WHEN** the checked-out pull request contains `.agents/skills/untrusted/SKILL.md`
- **THEN** that skill is absent from the review-agent registry and from every review harness skill catalog

#### Scenario: No reviewers are registered
- **WHEN** discovery produces no valid reviewer skills
- **THEN** the system stops before starting an agent or posting to GitHub and reports that no trusted reviewers are available

#### Scenario: Coordinator cardinality is invalid
- **WHEN** discovery produces zero or more than one valid coordinator skill
- **THEN** the system stops before starting an agent and reports the coordinator cardinality error

### Requirement: Conform to the Agent Skills standard
Every registered review agent SHALL be a valid Agent Skills directory whose `SKILL.md` contains standards-conformant YAML frontmatter and Markdown instructions. The skill name SHALL match its parent directory, and optional `scripts/`, `references/`, `assets/`, and other bundled resources SHALL retain their Agent Skills-relative path semantics.

#### Scenario: Valid portable skill
- **WHEN** a skill passes the Agent Skills reference validation and the review-bot contract validation
- **THEN** the same directory is eligible for native loading by every configured coding harness that supports the Agent Skills standard

#### Scenario: Invalid Agent Skills frontmatter
- **WHEN** a discovered `SKILL.md` violates a normative Agent Skills constraint
- **THEN** registry construction fails with the skill path and validation error before any agent starts

#### Scenario: Optional resources are present
- **WHEN** a registered skill references a file beneath its own `scripts/`, `references/`, or `assets/` directory
- **THEN** the selected harness can load that resource relative to the skill directory without eagerly adding every resource to model context

### Requirement: Declare the review-bot contract in namespaced metadata
Every registered review skill SHALL declare string values for `review-bot-contract`, `review-bot-kind`, `review-bot-inputs`, `review-bot-output-schema`, and `review-bot-order` in the Agent Skills `metadata` map. Contract version `v1` SHALL accept kinds `reviewer` and `coordinator`, kind-appropriate approved symbolic input resources, output schema `review-result/v1`, and an integer ordering value. Each reviewer SHALL additionally declare `review-bot-coordinator-policy` as a path contained within the same skill directory.

#### Scenario: Complete review metadata
- **WHEN** a skill declares a valid `v1` metadata contract
- **THEN** the system derives its identity from the Agent Skills name and derives its kind, assigned inputs, output validation, optional per-reviewer coordinator policy, and deterministic order from the declared metadata

#### Scenario: Unsupported symbolic input
- **WHEN** `review-bot-inputs` requests an input resource outside the approved contract
- **THEN** registry construction fails before the skill can read an arbitrary workspace path

#### Scenario: Coordinator policy escapes the skill
- **WHEN** the coordinator-policy reference is absolute, traverses outside the skill directory, is a symlink resolving outside the skill directory, or does not name a regular readable file
- **THEN** registry construction fails before any agent starts

#### Scenario: Duplicate Agent Skills names
- **WHEN** two discovered skills declare the same Agent Skills name
- **THEN** registry construction fails explicitly rather than shadowing or merging either skill

#### Scenario: Skill declares allowed tools
- **WHEN** a registered `SKILL.md` contains the experimental Agent Skills `allowed-tools` field
- **THEN** the field does not expand the tools or filesystem permissions granted by the review-bot runner

### Requirement: Load selected skills through the coding harness
For each selected reviewer and the registered coordinator, the system SHALL make only that trusted Agent Skill available through the configured harness's native Agent Skills loading mechanism and SHALL explicitly activate it for the invocation. The system MUST NOT simulate skill activation by concatenating the `SKILL.md` body into an unrelated private prompt contract.

#### Scenario: Pi reviewer starts
- **WHEN** a selected reviewer runs through Pi
- **THEN** Pi loads the selected skill through its native explicit skill mechanism with ambient skill discovery disabled

#### Scenario: Codex reviewer starts
- **WHEN** a selected reviewer runs through Codex
- **THEN** Codex discovers the selected skill from an isolated trusted Agent Skills location, activates that skill, and does not discover skills from the pull-request repository

#### Scenario: Unsupported harness is selected
- **WHEN** the configured command has no adapter that can provide isolated native Agent Skills loading
- **THEN** the run fails before starting any reviewer and identifies the unsupported harness

### Requirement: Preserve a registry and selection audit record
The system SHALL write a deterministic run manifest containing each discovered skill's name, kind, contract version, ordering value, assigned symbolic inputs, content digest, selection status, and harness identity without recording secrets or arbitrary skill resource contents.

#### Scenario: Registry is unchanged across runs
- **WHEN** two runs use byte-identical skills and the same harness configuration
- **THEN** their ordered registry entries and skill content digests are identical

#### Scenario: Skill instructions change
- **WHEN** a `SKILL.md` file or referenced coordinator-policy file changes
- **THEN** the corresponding audit digest changes even if the skill name and order stay the same
