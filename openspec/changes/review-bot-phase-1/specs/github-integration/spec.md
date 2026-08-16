## Purpose

Authenticate as a GitHub App and use short-lived installation tokens to fetch pull request metadata and post reviews.

## ADDED Requirements

### Requirement: Mint installation token
The system SHALL derive a short-lived GitHub App installation token from the configured App private key, App ID, and installation ID at the start of every review run.

#### Scenario: Token minting succeeds
- **WHEN** the CLI starts a review with valid GitHub App credentials
- **THEN** the system obtains an installation token that is scoped to the target repository and usable for the duration of the review run

#### Scenario: Token minting fails
- **WHEN** the App private key, App ID, or installation ID is missing or invalid
- **THEN** the review run fails fast with a clear error before any repository operation is attempted

### Requirement: Fetch pull request metadata
The system SHALL fetch pull request metadata including title, body, head SHA, base SHA, sender login, and changed file list.

#### Scenario: Metadata fetch succeeds
- **WHEN** the system requests the PR metadata for a valid PR URL
- **THEN** it receives the title, body, head SHA, base SHA, sender login, and the list of changed files

#### Scenario: Metadata fetch fails
- **WHEN** the PR URL is invalid, the PR does not exist, or the App lacks access
- **THEN** the system reports a fetch error and stops the review run

### Requirement: Fetch pull request diff
The system SHALL fetch the PR diff in a format that can be parsed per file and per changed line range.

#### Scenario: Diff fetch succeeds
- **WHEN** the system requests the diff for a valid PR
- **THEN** it receives a diff that maps added lines to right-side line numbers and removed lines to left-side line numbers per file

### Requirement: Post pull request review bound to head SHA
The system SHALL post a pull request review containing inline comments and a summary body under the GitHub App identity, targeting the fetched head SHA.

#### Scenario: Review posts successfully
- **WHEN** the system submits a review with valid inline comments, a summary body, and the fetched head SHA as `commit_id`
- **THEN** GitHub creates the review against that exact commit and returns a stable review ID

#### Scenario: Head SHA changed after fetch
- **WHEN** the PR head SHA has changed between metadata fetch and review POST
- **THEN** the system re-fetches metadata and diff, or fails the run rather than posting against a stale head

#### Scenario: Review post fails
- **WHEN** GitHub rejects the review payload
- **THEN** the system surfaces the provider error without silently dropping findings

### Requirement: Skip bot-authored pull requests
The system SHALL skip the review when the PR sender login matches the GitHub App bot username.

#### Scenario: Bot opens a pull request
- **WHEN** the PR sender login equals the configured bot username
- **THEN** the system exits successfully without posting a review

### Requirement: Capture linked issue references
The system SHALL extract any linked issue references from the PR title and body and include them in the shared context for review agents.

#### Scenario: PR links to an issue
- **WHEN** the PR title or body contains a reference such as `Fixes #123` or `SAC-87`
- **THEN** the shared context includes those references so agents can correlate intent
