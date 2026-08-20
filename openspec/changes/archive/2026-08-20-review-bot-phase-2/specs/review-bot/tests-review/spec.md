## Purpose

Provide a focused review pass that identifies concrete regression-coverage gaps introduced by changed behavior without requesting broad or speculative tests.

## ADDED Requirements

### Requirement: Tests review agent produces structured findings
The system SHALL run a tests review agent that reads the shared review context and filtered diff and emits output matching the shared review schema.

#### Scenario: Tests review completes
- **WHEN** the tests review agent finishes analyzing a pull request
- **THEN** it returns structured findings, an overall verdict and explanation, confidence scores, and a status field

#### Scenario: Tests review output is invalid
- **WHEN** the tests review agent returns output that does not match the shared review schema
- **THEN** the agent pipeline applies its existing partial-failure behavior and does not treat the invalid output as successful findings

### Requirement: Flag concrete missing regression coverage
The tests review agent SHALL emit a finding when changed behavior has a credible failure path that the available tests do not exercise.

#### Scenario: Changed branch lacks coverage
- **WHEN** a changed branch can produce an incorrect result for a specific input or state and no test exercises that behavior
- **THEN** the agent emits one finding that identifies the untested behavior and its concrete regression scenario

#### Scenario: Existing test covers the changed behavior
- **WHEN** an existing test would fail if the changed behavior regressed
- **THEN** the agent does not emit a missing-coverage finding for that behavior

### Requirement: Flag ineffective regression tests
The tests review agent SHALL emit a finding when a changed or existing test reaches the relevant behavior but cannot detect the concrete regression it claims to cover.

#### Scenario: Assertion cannot detect the regression
- **WHEN** a test executes the changed path but its assertions still pass for a specific incorrect outcome
- **THEN** the agent emits one finding explaining the undetected outcome and the assertion needed to observe it

### Requirement: Avoid speculative test requests
The tests review agent SHALL NOT request tests based only on coverage quantity, test style, or a hypothetical failure without a concrete changed behavior and credible failure scenario.

#### Scenario: Broad coverage improvement only
- **WHEN** additional tests could improve general coverage but no concrete regression path is identified in the changed behavior
- **THEN** the agent emits no finding

#### Scenario: Test organization preference
- **WHEN** the tests cover the changed behavior but could be reorganized or renamed
- **THEN** the agent emits no finding

### Requirement: Every tests finding is actionable
Every tests review finding SHALL identify the changed behavior, the concrete regression that can escape detection, and a targeted test or assertion that would detect it.

#### Scenario: Valid missing-test finding
- **WHEN** the agent reports a regression-coverage gap
- **THEN** the finding contains one issue, a diff-valid location, a concrete failure scenario, confidence and priority values, and a suggested test fix
