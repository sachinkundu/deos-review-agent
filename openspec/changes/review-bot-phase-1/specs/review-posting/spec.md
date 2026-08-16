## Purpose

Validate structured findings against the pull request diff and post them as GitHub review comments, sending unattached findings to the review summary body.

## ADDED Requirements

### Requirement: Validate code locations against the diff
The system SHALL verify that every inline comment's `(path, line, side=RIGHT)` maps to a changed line in the PR diff before posting.

#### Scenario: Location is in the diff
- **WHEN** a finding points to a line that exists on the right-hand side of the diff
- **THEN** the system marks it as attachable and includes it in the inline comments list

#### Scenario: Location is not in the diff
- **WHEN** a finding points to a line that is not on the right-hand side of the diff
- **THEN** the system moves the finding to the review summary body and does not attempt an inline comment

### Requirement: Post exactly one issue per inline comment
The system SHALL create one GitHub review comment per finding; it SHALL NOT merge multiple findings into a single prose comment.

#### Scenario: Multiple findings
- **WHEN** the coordinator produces several findings
- **THEN** each finding becomes a separate inline comment or a separate entry in the summary body

### Requirement: Set review event from severity
The system SHALL choose the GitHub review event based on the highest-severity finding according to the final rubric.

#### Scenario: No critical findings
- **WHEN** there are no findings or only suggestions
- **THEN** the system posts the review with event `COMMENT` and includes a pass note in the summary body

#### Scenario: Critical findings
- **WHEN** there is at least one critical or production-safety finding
- **THEN** the system posts the review with event `REQUEST_CHANGES`

### Requirement: Validate output before posting
The system SHALL validate the final review payload against the review output schema before calling the GitHub API.

#### Scenario: Payload is valid
- **WHEN** the final review payload passes schema validation
- **THEN** the system proceeds to post the review to GitHub

#### Scenario: Payload is invalid
- **WHEN** the final review payload fails schema validation
- **THEN** the system reports the validation errors and stops before any GitHub API call

### Requirement: Include suggested fixes in comments
The system SHALL include the suggested fix description in each inline comment body so the PR author can act on it.

#### Scenario: Comment with fix
- **WHEN** a finding includes a suggested fix
- **THEN** the posted comment body contains the evidence, problem, failure scenario, and suggested fix
