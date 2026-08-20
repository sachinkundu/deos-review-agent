# Agent Pipeline Specification

## Purpose

Run multiple specialized review agents concurrently, feed their findings into a coordinator, and emit a single validated structured review output.

## Requirements

### Requirement: Run review agents concurrently
The system SHALL run the correctness review agent and the API-reality review agent concurrently.

#### Scenario: Both agents start
- **WHEN** the agent pipeline begins
- **THEN** the correctness agent and the API-reality agent both receive their inputs and run in parallel

#### Scenario: One agent fails
- **WHEN** one review agent fails or returns invalid output
- **THEN** the pipeline reports the failure in the review summary, continues with findings from any successful agents, and does not stop the whole run

### Requirement: Feed all findings to the coordinator
The system SHALL pass the findings from every successful review agent to the coordinator.

#### Scenario: Findings from two agents
- **WHEN** both the correctness agent and the API-reality agent emit findings
- **THEN** the coordinator receives the combined set

#### Scenario: One agent produced no findings
- **WHEN** only one agent emits findings
- **THEN** the coordinator still processes those findings and the summary notes any agent that failed or produced no output

### Requirement: Coordinator deduplicates and filters findings
The system SHALL run a coordinator that deduplicates findings by `(path, start_line, normalized_title)`, drops speculative or contradicted findings, and rewrites each remaining finding to contain exactly one issue.

#### Scenario: Overlapping findings
- **WHEN** two agents emit findings for the same line with the same root cause
- **THEN** the coordinator emits one consolidated finding

### Requirement: Coordinator assigns final severity and verdict
The system SHALL use the coordinator to assign final priority and an overall verdict using the approved rubric.

#### Scenario: Critical finding present
- **WHEN** the coordinator retains a critical finding
- **THEN** the overall verdict is `patch is incorrect` and the recommended GitHub event is `REQUEST_CHANGES`

#### Scenario: No critical findings
- **WHEN** there are no findings or only warnings and suggestions
- **THEN** the overall verdict and recommended event follow the approved rubric

### Requirement: Validate coordinator output
The system SHALL validate the coordinator output against the review output schema before handing it to the review-posting step.

#### Scenario: Valid coordinator output
- **WHEN** the coordinator output matches the schema
- **THEN** the pipeline proceeds to review posting

#### Scenario: Invalid coordinator output
- **WHEN** the coordinator output does not match the schema
- **THEN** the system reports validation errors and stops the review run
