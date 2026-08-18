## MODIFIED Requirements

### Requirement: Run review agents concurrently
The system SHALL run the correctness, API-reality, tests, and safety review agents concurrently for every review.

#### Scenario: All Phase 2 agents start
- **WHEN** the agent pipeline begins
- **THEN** the correctness, API-reality, tests, and safety agents all receive their inputs and run in parallel

#### Scenario: Pull request size or path varies
- **WHEN** the pull request has any diff size or changed-file path composition
- **THEN** the pipeline runs all four agents without assigning a risk tier or conditionally selecting an agent roster

#### Scenario: One agent fails
- **WHEN** one review agent fails or returns invalid output
- **THEN** the pipeline reports the failure in the review summary, continues with findings from any successful agents, and does not stop the whole run

### Requirement: Feed all findings to the coordinator
The system SHALL pass the findings from every successful correctness, API-reality, tests, and safety review agent to the coordinator with the source agent identified.

#### Scenario: Findings from all four agents
- **WHEN** all four review agents emit findings
- **THEN** the coordinator receives the combined set with each finding attributed to its source agent

#### Scenario: Successful agent produced no findings
- **WHEN** one or more successful review agents returns a valid empty findings list
- **THEN** the coordinator still receives every successful agent result and processes the combined findings that remain

#### Scenario: One agent failed
- **WHEN** one agent fails and at least one other agent succeeds
- **THEN** the coordinator receives findings from every successful agent and the failed agent is identified for the review summary
