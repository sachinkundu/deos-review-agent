## Purpose

Run a correctness sub-agent over the pull request diff and shared context, then run a coordinator that deduplicates, filters, and rewrites the findings into a validated structured review output.

## ADDED Requirements

### Requirement: Assemble shared context
The system SHALL assemble a shared context document containing PR metadata, changed files, and any validation command results, and make it available to the sub-agent.

#### Scenario: Shared context is complete
- **WHEN** the system prepares inputs for the correctness agent
- **THEN** the shared context includes PR title, body, head SHA, base SHA, changed files, and validation results

### Requirement: Correctness agent produces structured findings
The system SHALL run a correctness sub-agent that reads the shared context and diff and emits findings matching the review output schema.

#### Scenario: Findings are emitted
- **WHEN** the correctness agent finishes analyzing the diff
- **THEN** it returns a JSON object containing findings, an overall correctness verdict, an explanation, confidence scores, and a status field

#### Scenario: Agent output is invalid
- **WHEN** the correctness agent returns JSON that does not match the schema
- **THEN** the system reports a schema validation error and stops the review run

### Requirement: Coordinator filters and rewrites findings
The system SHALL run a coordinator that reads the sub-agent output, drops speculative or contradicted findings, deduplicates by file and line, and rewrites each remaining finding to contain exactly one issue.

#### Scenario: Noisy findings are reduced
- **WHEN** the coordinator receives multiple overlapping or low-confidence findings
- **THEN** the coordinator output contains only distinct, well-supported findings with one issue per finding

### Requirement: Every finding includes a concrete failure scenario
The system SHALL require every finding to describe a concrete failure scenario and a suggested fix.

#### Scenario: Valid finding
- **WHEN** a finding is accepted by the coordinator
- **THEN** it includes a title, body with failure scenario, code location, confidence score, priority, and suggested fix

### Requirement: Preserve status field through the pipeline
The system SHALL preserve the explicit `status` field from the sub-agent output through the coordinator so the caller can detect whether further review passes are expected.

#### Scenario: Status is forwarded
- **WHEN** the coordinator emits final findings
- **THEN** the output retains a status field indicating whether review is complete or in progress
