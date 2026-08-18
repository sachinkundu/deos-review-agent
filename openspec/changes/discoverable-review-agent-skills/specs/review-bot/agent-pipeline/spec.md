## MODIFIED Requirements

### Requirement: Run review agents concurrently
The system SHALL select every valid registered reviewer for this change and run the selected reviewers with bounded concurrency. Execution order and result serialization SHALL follow registry order regardless of completion order.

#### Scenario: Registered reviewers start
- **WHEN** the agent pipeline begins with one or more valid registered reviewers
- **THEN** every registered reviewer is submitted for execution with its declared inputs and activated Agent Skill

#### Scenario: Registry exceeds the concurrency bound
- **WHEN** more reviewers are selected than the configured concurrency bound
- **THEN** no more than the bounded number run simultaneously and the remaining reviewers wait without being omitted

#### Scenario: Reviewers finish out of order
- **WHEN** concurrent reviewers complete in a different order from the registry
- **THEN** the raw result artifact preserves deterministic registry order

#### Scenario: One agent fails
- **WHEN** one review agent fails or returns invalid output
- **THEN** the pipeline reports the failure in the review summary, continues with findings from any successful agents, and does not stop the whole run

#### Scenario: Every agent fails
- **WHEN** every selected review agent fails or returns invalid output
- **THEN** the pipeline stops before coordination and GitHub posting and reports every failed registered agent

### Requirement: Feed all findings to the coordinator
The system SHALL pass the catalog entry and attributed result from every selected registered reviewer to the registered roster-agnostic coordinator. The coordinator SHALL apply the supplied per-agent coordination policy without requiring its Agent Skill or orchestration code to name every registered reviewer role.

#### Scenario: Registered agents emit findings
- **WHEN** any registered reviewers emit findings
- **THEN** the coordinator receives those findings with the source skill name, contract version, and matching coordination policy

#### Scenario: Successful agent produced no findings
- **WHEN** one or more successful registered reviewers returns a valid empty findings list
- **THEN** the coordinator still receives every successful agent result and processes the combined findings that remain

#### Scenario: One agent failed
- **WHEN** one registered reviewer fails and at least one other reviewer succeeds
- **THEN** the coordinator receives every successful result and the failed reviewer is identified in both coordinator input and the review summary

#### Scenario: New valid role is installed
- **WHEN** a new valid built-in review skill is added without changing coordinator or orchestration source code
- **THEN** the next run discovers, executes, attributes, and coordinates that role according to its declared contract

#### Scenario: Coordinator receives an unknown source
- **WHEN** a raw result names an agent absent from the generated catalog or does not match its declared contract
- **THEN** coordination fails before GitHub posting rather than treating the result as trusted

### Requirement: Preserve the Phase 2 built-in review coverage
The built-in registry SHALL contain correctness, API-reality, tests, safety, and coordinator Agent Skills with the Phase 2 input boundaries and shared structured-output behavior.

#### Scenario: Built-in registry is loaded
- **WHEN** the default registry is discovered
- **THEN** correctness, API-reality, and tests receive the filtered review diff, safety receives the complete provider diff, and the coordinator receives the generated catalog, raw results, shared context, and complete provider diff

#### Scenario: Built-in review completes
- **WHEN** the four migrated skills return valid results
- **THEN** their findings remain subject to the same shared review schema, coordinator filtering, full-provider-diff location validation, and GitHub posting behavior as Phase 2
