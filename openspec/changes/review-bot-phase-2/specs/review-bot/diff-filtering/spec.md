## Purpose

Reduce low-signal agent input deterministically while preserving the complete provider diff required for accurate GitHub review validation and posting.

## ADDED Requirements

### Requirement: Filter low-signal files before agent review
The system SHALL create an agent-review diff that excludes lockfiles, generated files, and vendored dependencies according to documented deterministic rules before any review agent runs.

#### Scenario: Lockfile changes are present
- **WHEN** the provider diff contains a file identified by the documented lockfile rules
- **THEN** that file's patch is absent from the agent-review diff

#### Scenario: Generated or vendored changes are present
- **WHEN** the provider diff contains a file identified by documented generated-file or vendored-path rules
- **THEN** that file's patch is absent from the agent-review diff

#### Scenario: Ordinary source changes are present
- **WHEN** a changed file matches none of the documented exclusion rules
- **THEN** its complete patch remains in the agent-review diff

#### Scenario: Identical input is filtered repeatedly
- **WHEN** the same provider diff and filter rules are processed more than once
- **THEN** the resulting agent-review diff and exclusion records are identical

### Requirement: Disclose every filtered file
The system SHALL make every excluded path and its matched exclusion reason available in the shared review context.

#### Scenario: Agent input omits files
- **WHEN** one or more file patches are excluded from the agent-review diff
- **THEN** the shared context lists each excluded path and whether it matched a lockfile, generated-file, or vendored-path rule

#### Scenario: No files are filtered
- **WHEN** no changed file matches an exclusion rule
- **THEN** the shared context explicitly records that no files were excluded

### Requirement: Preserve the provider diff for validation and posting
The system SHALL retain the complete, unmodified provider-originated diff separately from the agent-review diff and SHALL use the complete diff for right-side line validation and GitHub review posting.

#### Scenario: A file is filtered from agent input
- **WHEN** a changed file is excluded from the agent-review diff
- **THEN** its patch remains present in the complete provider diff used by downstream line validation

#### Scenario: Finding locations are validated
- **WHEN** the coordinator emits final findings
- **THEN** every location is validated against the complete provider diff rather than the filtered agent-review diff

### Requirement: Filtering does not select the agent roster
The system SHALL treat diff filtering only as input reduction and SHALL NOT use file exclusions, diff size, paths, or inferred pull-request risk to skip a Phase 2 review agent.

#### Scenario: Every changed file is filtered
- **WHEN** all changed file patches match exclusion rules
- **THEN** the correctness, API-reality, tests, and safety agents still run with the shared context and the empty agent-review diff
