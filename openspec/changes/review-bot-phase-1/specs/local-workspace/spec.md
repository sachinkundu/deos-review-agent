## Purpose

Prepare an isolated local workspace containing the pull request branch so the review agents can read files outside the diff when context is needed.

## ADDED Requirements

### Requirement: Clone repository into isolated workspace
The system SHALL clone the target repository into a dedicated workspace directory that is separate from the review-bot source tree.

#### Scenario: Clone succeeds
- **WHEN** the system creates a workspace for a PR
- **THEN** it clones the repository and the workspace contains a clean working copy

#### Scenario: Clone target is unreachable
- **WHEN** the repository URL is invalid or the App token cannot read the repository
- **THEN** the system reports a workspace setup error and stops the review run

### Requirement: Check out pull request branch
The system SHALL check out the pull request branch at exactly the head SHA reported by GitHub.

#### Scenario: Checkout succeeds
- **WHEN** the system checks out the PR branch at the head SHA
- **THEN** the working copy is at that exact commit and the branch name matches the PR branch

#### Scenario: Checkout fails
- **WHEN** the head SHA cannot be fetched or the branch does not exist
- **THEN** the system reports a checkout error and stops the review run

### Requirement: Keep workspace path configurable
The system SHALL allow the operator to configure the root workspace directory via environment variable or CLI option.

#### Scenario: Custom workspace root
- **WHEN** the operator supplies a workspace root path
- **THEN** the system creates the PR-specific workspace under that root

### Requirement: Clean up workspace
The system SHALL remove the PR-specific workspace after the review run completes, unless the operator configures it to be retained.

#### Scenario: Default cleanup
- **WHEN** the review run completes
- **THEN** the system deletes the PR-specific workspace

#### Scenario: Retain workspace for debugging
- **WHEN** the operator enables workspace retention
- **THEN** the system leaves the workspace intact after the review run
