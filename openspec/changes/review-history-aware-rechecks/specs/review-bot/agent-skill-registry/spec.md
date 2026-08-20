## MODIFIED Requirements

### Requirement: Isolate assigned review resources
The system SHALL keep host-produced review artifacts outside the checked-out repository and SHALL expose to each agent only its declared symbolic resources plus the clean source checkout. Unassigned diff, history, target, catalog, and result artifacts MUST NOT appear within that agent's repository or invocation view. Pull request files and provider text MUST NOT shadow, append to, or name an additional host-owned symbolic resource.

#### Scenario: Filtered reviewer runs
- **WHEN** a reviewer is assigned `review-diff` but not `provider-diff`
- **THEN** its invocation contains the filtered diff and clean source checkout but no path to the complete provider diff artifact

#### Scenario: Safety reviewer runs
- **WHEN** safety is assigned `provider-diff`
- **THEN** its invocation contains the complete provider diff without making that artifact visible to filtered reviewers

#### Scenario: Recheck reviewer runs
- **WHEN** a recheck reviewer is assigned a bounded history view and target roster
- **THEN** its invocation contains only those host-produced history and target resources and no complete provider conversation or another reviewer's targets

#### Scenario: Pull request shadows a symbolic resource
- **WHEN** the checkout contains a file, directory, symlink, or manifest entry whose name matches a history or target symbolic resource
- **THEN** the host-owned resource remains authoritative and the pull request object is not exposed as that symbolic input

## ADDED Requirements

### Requirement: Support host-owned recheck resources
The approved symbolic input contract SHALL include a bounded reviewer history view, assigned recheck target roster, current-head evidence manifest, and complete provider conversation. Reviewer packages MAY request only the bounded resources applicable to their role. Only the coordinator MAY request the complete provider conversation and complete target roster.

#### Scenario: Reviewer declares bounded recheck inputs
- **WHEN** a valid reviewer package declares the approved history-view, assigned-target, and evidence resources
- **THEN** registry validation accepts those symbolic names and the runner supplies the matching host-owned artifacts in recheck mode

#### Scenario: Reviewer requests complete provider conversation
- **WHEN** a reviewer package rather than the coordinator requests the complete provider conversation or complete target roster
- **THEN** registry construction fails before any agent starts

#### Scenario: Initial-review run has no recheck resources
- **WHEN** the pipeline is in initial-review mode
- **THEN** recheck-only symbolic resources are absent rather than populated with provider-controlled placeholders

### Requirement: Bind recheck resources to the retained run manifest
For every selected recheck agent, the run manifest SHALL record the run mode, classified head SHA, canonical history digest, ordered assigned finding identities, symbolic resource names, and digests of host-produced resource contents without recording arbitrary provider text, source content, or secrets in the manifest.

#### Scenario: Identical recheck inputs are repeated
- **WHEN** two runs use the same head, conversation snapshot, targets, agent package, and bounded evidence
- **THEN** their ordered resource assignments and resource digests are identical

#### Scenario: Conversation or target assignment changes
- **WHEN** the normalized provider conversation or an agent's assigned targets change
- **THEN** the affected history or target resource digest changes and the manifest identifies the changed assignment

### Requirement: Enforce resource size and identity bounds before agents start
Every host-owned recheck resource SHALL validate against a versioned schema and configured count and byte limits before it is exposed to an agent. Truncation MUST preserve complete target identities and relationships and SHALL be explicit and deterministic; if required evidence cannot fit without losing those identities or relationships, the run SHALL fail before agent execution.

#### Scenario: History view is within bounds
- **WHEN** a reviewer's assigned conversation and evidence fit the configured schema and limits
- **THEN** the complete bounded view is supplied with its schema version and digest

#### Scenario: Optional context exceeds a bound
- **WHEN** unrelated or lower-priority context exceeds the configured limit
- **THEN** deterministic truncation removes only allowed optional context and records that truncation in the resource metadata

#### Scenario: Required target evidence exceeds a bound
- **WHEN** a target identity, reply relationship, or required evidence cannot fit within the configured limits
- **THEN** the run fails closed before the agent starts rather than supplying an incomplete target contract
