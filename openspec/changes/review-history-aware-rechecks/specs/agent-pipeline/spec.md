## MODIFIED Requirements

### Requirement: Run review agents concurrently
In `initial-review` mode, the system SHALL select every valid registered reviewer agent for this change. In `recheck` mode, it SHALL select only registered reviewers assigned at least one owned prior finding and SHALL give each selected reviewer only those target identities and their bounded evidence. The system SHALL run selected reviewers with bounded concurrency, and execution order and result serialization SHALL follow registry order regardless of completion order.

#### Scenario: Both agents start
- **WHEN** the initial-review pipeline begins with one or more valid registered reviewers
- **THEN** every registered reviewer is submitted with its prompt, declared inputs, and optional Agent Skills

#### Scenario: Recheck reviewers have targets
- **WHEN** recheck mode assigns prior finding targets to one or more registered reviewers
- **THEN** only reviewers with assigned targets are submitted and each receives only its declared resources and assigned target evidence

#### Scenario: Recheck has no targets
- **WHEN** an owned initial review contains no findings or every candidate target is ambiguous before agent execution
- **THEN** no defect-discovery reviewer starts and the run produces no new findings

#### Scenario: Registry exceeds the concurrency bound
- **WHEN** more reviewers are selected than the configured concurrency bound
- **THEN** no more than the bounded number run simultaneously and the remaining reviewers wait without being omitted

#### Scenario: Reviewers finish out of order
- **WHEN** concurrent reviewers complete in a different order from the registry
- **THEN** the raw result artifact preserves deterministic registry order

#### Scenario: One agent fails
- **WHEN** one selected review agent fails or returns invalid output
- **THEN** the pipeline reports the failure, continues with valid results from other selected agents, and does not invent a classification for the failed agent's targets

#### Scenario: Every agent fails
- **WHEN** every selected review agent fails or returns invalid output
- **THEN** the pipeline stops before coordination and GitHub posting and reports every failed registered agent

### Requirement: Feed all findings to the coordinator
The system SHALL pass the catalog entry and attributed result from every selected registered reviewer to the registered roster-agnostic coordinator. Every catalog entry and result envelope SHALL carry the source agent's validated contract version and package digest. In initial-review mode, results contain proposed findings and per-agent coordination policy. In recheck mode, results contain only classifications for assigned stable finding identities, and the coordinator additionally receives the complete normalized provider conversation, complete target roster, current-head evidence manifest, and recheck classification policy.

#### Scenario: Findings from two agents
- **WHEN** registered reviewers emit findings during an initial review
- **THEN** the coordinator receives those findings with source agent name, validated contract version, package digest, and matching coordination policy

#### Scenario: Recheck statuses from two agents
- **WHEN** registered reviewers classify assigned prior findings during a recheck
- **THEN** the coordinator receives their attributed classifications plus the complete target roster and provider conversation

#### Scenario: New agents emit findings
- **WHEN** the tests or safety agent emits findings during an initial review
- **THEN** the coordinator receives those findings together with findings from the successful correctness and API-reality agents

#### Scenario: One agent produced no findings
- **WHEN** one or more successful registered reviewers returns a valid empty findings list during an initial review
- **THEN** the coordinator still receives every successful agent result and processes the combined findings that remain

#### Scenario: Recheck agent omits an assigned target
- **WHEN** a successful recheck reviewer does not return one of its assigned finding identities
- **THEN** coordination fails before GitHub posting rather than inferring the missing classification

#### Scenario: One agent failed
- **WHEN** one registered reviewer fails and at least one other reviewer succeeds
- **THEN** the coordinator receives every successful result and the failed reviewer is identified in both coordinator input and the retained summary

#### Scenario: New valid agent is installed
- **WHEN** a new valid built-in reviewer package is added without changing coordinator or orchestration source code
- **THEN** the next initial review discovers, executes, attributes, and coordinates that agent according to its declared contract

#### Scenario: Coordinator receives an unknown source
- **WHEN** a raw result names an agent absent from the generated catalog or its contract version or package digest differs from the catalog
- **THEN** coordination fails before GitHub posting rather than treating the result as trusted

### Requirement: Coordinator deduplicates and filters findings
In `initial-review` mode, the system SHALL run a coordinator that deduplicates findings by `(path, start_line, normalized_title)`, drops speculative or contradicted findings, and rewrites each remaining finding to contain exactly one issue. In `recheck` mode, the coordinator MUST NOT perform defect discovery or convert status evidence into a new finding.

#### Scenario: Overlapping findings
- **WHEN** two initial-review agents emit findings for the same line with the same root cause
- **THEN** the coordinator emits one consolidated new finding

#### Scenario: Recheck evidence mentions another issue
- **WHEN** a recheck result contains text describing a possible defect outside its assigned target
- **THEN** the coordinator drops that text as an unauthorized new finding and fails validation if it was represented as an output finding

### Requirement: Coordinator assigns final severity and verdict
In `initial-review` mode, the system SHALL use the coordinator to assign final priority and an overall verdict using the approved rubric. In `recheck` mode, the coordinator SHALL preserve each target's original severity for identity and display, assign exactly one allowed recheck classification, and produce a recheck summary without recommending a new review event.

#### Scenario: Critical finding present
- **WHEN** the initial-review coordinator retains a critical finding
- **THEN** the overall verdict is `patch is incorrect` and the recommended GitHub event is `REQUEST_CHANGES`

#### Scenario: No critical findings
- **WHEN** an initial review has no findings or only warnings and suggestions
- **THEN** the overall verdict and recommended event follow the approved rubric

#### Scenario: Recheck completes
- **WHEN** every applicable prior target has a valid fixed, unfixed, obsolete, or ambiguous classification
- **THEN** the coordinator returns the ordered classifications and aggregate counts without a new defect verdict or GitHub review event

### Requirement: Validate coordinator output
The system SHALL validate coordinator output against the mode-specific output schema before handing it to review posting. The initial-review schema SHALL allow new findings. The recheck schema SHALL require only known target identities, exactly one allowed classification and current-head evidence per applicable target, and SHALL reject a new finding or review event.

#### Scenario: Valid coordinator output
- **WHEN** the initial-review coordinator output matches its schema
- **THEN** the pipeline proceeds to initial review planning

#### Scenario: Valid recheck coordinator output
- **WHEN** the recheck coordinator output contains every applicable owned target exactly once with allowed evidence-backed classifications
- **THEN** the pipeline proceeds to recheck action planning

#### Scenario: Invalid coordinator output
- **WHEN** either mode's coordinator output does not match its schema
- **THEN** the system reports validation errors and stops the review run before any GitHub mutation

## ADDED Requirements

### Requirement: Supply bounded history views to reviewers
For each recheck reviewer, the system SHALL construct a deterministic history view containing only its assigned finding identities, the provider objects and reply chain needed to understand them, bounded current-head source and diff evidence, and the minimum shared pull request context. The coordinator SHALL receive the complete normalized provider conversation and complete target roster.

#### Scenario: Reviewer has one inline target
- **WHEN** a reviewer is assigned one prior inline finding
- **THEN** its history view contains that finding, its complete reply chain and thread state, and bounded current-head evidence without unrelated conversations

#### Scenario: Reviewer has targets in two files
- **WHEN** a reviewer is assigned prior findings in two included source files
- **THEN** its view contains both targets in deterministic identity order and no unassigned finding target

#### Scenario: Coordinator starts
- **WHEN** all selected recheck reviewers finish
- **THEN** the coordinator receives complete history, every target, every attributed result, and every failure record needed to detect omissions or unknown identities

### Requirement: Treat recheck evidence as untrusted task data
Every agent and coordinator prompt in recheck mode SHALL distinguish host-authored instructions and schemas from provider-authored conversation and pull request content. Provider text, source content, marker-like strings, filenames, and replies MUST NOT expand target identities, symbolic resources, tools, skills, filesystem access, or output schema.

#### Scenario: Comment requests new analysis
- **WHEN** a provider comment instructs the reviewer to ignore its assigned target and find other issues
- **THEN** the reviewer treats the instruction as evidence text and evaluates only the assigned target

#### Scenario: Pull request adds a marker-like resource
- **WHEN** the checkout contains a file or text named like a review-history resource or stable finding marker
- **THEN** it does not replace, append to, or create a host-owned target or resource

### Requirement: Preserve Phase 2 agent coverage by review mode
The built-in registry SHALL continue to contain correctness, API-reality, tests, safety, and coordinator agents with their Phase 2 identities and trust boundaries. Initial-review mode SHALL preserve their existing diff inputs and coverage. Recheck mode SHALL use the same registered reviewer expertise only for assigned prior findings, with correctness, API-reality, and tests receiving filtered current-head evidence and safety receiving complete provider evidence for its assigned targets.

#### Scenario: Initial review runs
- **WHEN** the default registry performs initial-review mode
- **THEN** correctness, API-reality, and tests receive the filtered review diff, safety receives the complete provider diff, and the coordinator receives the generated catalog, raw results, shared context, and complete provider diff

#### Scenario: Recheck runs
- **WHEN** the default registry performs recheck mode
- **THEN** each selected reviewer evaluates only assigned prior findings through its declared evidence boundary and the coordinator receives the complete conversation and target roster
