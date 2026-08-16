## Purpose

Run a correctness review agent that flags logic bugs, unhandled error paths, claim mismatches, and architecture-ordering bugs in the changed code.

## ADDED Requirements

### Requirement: Assemble shared context
The system SHALL assemble a shared context document containing PR metadata, linked issue references, changed files, and any validation command results, and make it available to the correctness agent.

#### Scenario: Shared context is complete
- **WHEN** the system prepares inputs for the correctness agent
- **THEN** the shared context includes PR title, body, head SHA, base SHA, linked issue references, changed files, and validation results

### Requirement: Correctness agent produces structured findings
The system SHALL run a correctness review agent that reads the shared context and diff and emits findings matching the review output schema.

#### Scenario: Findings are emitted
- **WHEN** the correctness agent finishes analyzing the diff
- **THEN** it returns a JSON object containing findings, an overall correctness verdict, an explanation, confidence scores, and a status field

#### Scenario: Agent output is invalid
- **WHEN** the correctness agent returns JSON that does not match the schema
- **THEN** the system reports a schema validation error and stops the review run

### Requirement: Correctness findings are limited to bugs and unsafe behavior
The correctness agent SHALL flag only logic bugs, unhandled error paths, claim mismatches, and architecture-ordering bugs. It SHALL NOT flag style, formatting, naming, or general refactoring suggestions.

#### Scenario: Logic bug found
- **WHEN** the changed code contains an incorrect conditional that leads to a wrong result
- **THEN** the agent emits a finding with a concrete failure scenario and suggested fix

#### Scenario: Style suggestion
- **WHEN** the changed code could be reformatted or renamed without changing behavior
- **THEN** the agent does not emit a finding

### Requirement: Every correctness finding includes a concrete failure scenario
The system SHALL require every correctness finding to describe a concrete failure scenario and a suggested fix.

#### Scenario: Valid finding
- **WHEN** a correctness finding is accepted by the coordinator
- **THEN** it includes a title, body with failure scenario, code location, confidence score, priority, and suggested fix

### Requirement: Architecture-ordering bugs are in scope
The correctness agent SHALL flag architecture-ordering bugs such as wrong lifecycle, invalid state transitions, and cleanup-before-use mistakes.

#### Scenario: Cleanup before use
- **WHEN** the changed code releases a resource before all consumers have finished using it
- **THEN** the agent emits a finding describing the resulting failure

### Requirement: Preserve status field through the agent
The system SHALL preserve the explicit `status` field from the correctness agent output so the caller can detect whether further review passes are expected.

#### Scenario: Status is forwarded
- **WHEN** the correctness agent emits findings
- **THEN** the output retains a status field indicating whether review is complete or in progress
