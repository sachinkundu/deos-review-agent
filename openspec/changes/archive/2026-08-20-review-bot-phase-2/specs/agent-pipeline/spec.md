## MODIFIED Requirements

This delta expands the existing Phase 1 pipeline rather than introducing a new pipeline. Unchanged concurrency and partial-failure scenarios are repeated because an OpenSpec modified requirement replaces the complete existing requirement block when archived.

### Requirement: Run review agents concurrently
The system SHALL run the correctness, API-reality, tests, and safety review agents concurrently for every review.

#### Scenario: Both agents start
- **WHEN** the agent pipeline begins
- **THEN** the correctness, API-reality, tests, and safety agents all receive their inputs and run in parallel

#### Scenario: One agent fails
- **WHEN** one review agent fails or returns invalid output
- **THEN** the pipeline reports the failure in the review summary, continues with findings from any successful agents, and does not stop the whole run

### Requirement: Feed all findings to the coordinator
The system SHALL pass the findings from every successful correctness, API-reality, tests, and safety review agent to the coordinator.

#### Scenario: Findings from two agents
- **WHEN** both the correctness agent and the API-reality agent emit findings
- **THEN** the coordinator receives the combined set

#### Scenario: New agents emit findings
- **WHEN** the tests or safety agent emits findings
- **THEN** the coordinator receives those findings together with findings from the successful correctness and API-reality agents

#### Scenario: One agent produced no findings
- **WHEN** one or more successful review agents returns a valid empty findings list
- **THEN** the coordinator still receives every successful agent result and processes the combined findings that remain

#### Scenario: One agent failed
- **WHEN** one agent fails and at least one other agent succeeds
- **THEN** the coordinator receives findings from every successful agent and the failed agent is identified for the review summary
