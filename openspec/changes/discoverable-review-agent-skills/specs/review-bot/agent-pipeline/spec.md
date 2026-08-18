## MODIFIED Requirements

### Requirement: Run review agents concurrently
The system SHALL select every valid registered reviewer agent for this change and run the selected reviewers with bounded concurrency. Execution order and result serialization SHALL follow registry order regardless of completion order.

#### Scenario: Registered reviewers start
- **WHEN** the agent pipeline begins with one or more valid registered reviewers
- **THEN** every registered reviewer is submitted with its prompt, declared inputs, and optional Agent Skills

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
The system SHALL pass the catalog entry and attributed result from every selected registered reviewer to the registered roster-agnostic coordinator. Every catalog entry and result envelope SHALL carry the source agent's validated contract version and package digest. The coordinator SHALL apply the supplied per-agent coordination policy without requiring its prompt or orchestration code to name every registered reviewer role.

#### Scenario: Registered agents emit findings
- **WHEN** any registered reviewers emit findings
- **THEN** the coordinator receives those findings with the source agent name, validated contract version, package digest, and matching coordination policy

#### Scenario: Successful agent produced no findings
- **WHEN** one or more successful registered reviewers returns a valid empty findings list
- **THEN** the coordinator still receives every successful agent result and processes the combined findings that remain

#### Scenario: One agent failed
- **WHEN** one registered reviewer fails and at least one other reviewer succeeds
- **THEN** the coordinator receives every successful result and the failed reviewer is identified in both coordinator input and the review summary

#### Scenario: New valid agent is installed
- **WHEN** a new valid built-in reviewer package is added without changing coordinator or orchestration source code
- **THEN** the next run discovers, executes, attributes, and coordinates that agent according to its declared contract

#### Scenario: Coordinator receives an unknown source
- **WHEN** a raw result names an agent absent from the generated catalog or its contract version or package digest differs from the catalog
- **THEN** coordination fails before GitHub posting rather than treating the result as trusted

### Requirement: Preserve the Phase 2 built-in review coverage
The built-in registry SHALL contain correctness, API-reality, tests, safety, and coordinator agents with their Phase 2 prompts, input boundaries, and shared structured-output behavior. Built-in agents MAY add Agent Skills later without changing their identity as agents.

#### Scenario: Built-in registry is loaded
- **WHEN** the default registry is discovered
- **THEN** correctness, API-reality, and tests receive the filtered review diff, safety receives the complete provider diff, and the coordinator receives the generated catalog, raw results, shared context, and complete provider diff

#### Scenario: Built-in review completes
- **WHEN** the four migrated reviewer agents return valid results
- **THEN** their findings remain subject to the same shared review schema, coordinator filtering, full-provider-diff location validation, and GitHub posting behavior as Phase 2
