## Purpose

Prepare an isolated local workspace containing the pull request branch so the review agents can read files outside the diff when context is needed.

## ADDED Requirements

### Requirement: Clone repository into isolated workspace
The system SHALL clone the target repository into a dedicated workspace directory that is separate from the review-bot source tree, then invoke a consumer-provided bootstrap script to prepare the environment.

#### Scenario: Clone and bootstrap succeed
- **WHEN** the system creates a workspace for a PR
- **THEN** it clones the repository, checks out the PR branch, runs the configured bootstrap script if present, and the workspace contains a prepared working copy

#### Scenario: Bootstrap script fails
- **WHEN** the configured bootstrap script exits with an error
- **THEN** the system reports the bootstrap failure and stops the review run

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

### Requirement: Clean up workspace at end of review session
The system SHALL retain the PR-specific workspace for the duration of the review session and remove it only when the session ends or when the operator explicitly requests cleanup.

#### Scenario: Single-turn session cleanup
- **WHEN** the review run completes in a single-turn session
- **THEN** the system deletes the PR-specific workspace after posting the review

#### Scenario: Session retention for multi-turn reviews
- **WHEN** the operator configures the session to span multiple review turns
- **THEN** the system retains the workspace until the session ends

#### Scenario: Explicit cleanup
- **WHEN** the operator invokes a cleanup command
- **THEN** the system removes the PR-specific workspace regardless of session state
