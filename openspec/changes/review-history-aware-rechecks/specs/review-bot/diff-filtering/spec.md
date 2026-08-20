## ADDED Requirements

### Requirement: Apply path exclusions to file-scoped recheck history
The system SHALL apply the existing lockfile, vendored, and generated path classifications to path-bound provider conversations when constructing recheck history views for correctness, API-reality, and tests reviewers. A conversation bound only to excluded paths SHALL be absent from those file-scoped views. The safety reviewer SHALL retain complete provider evidence for its assigned targets.

#### Scenario: Prior finding belongs to an excluded file
- **WHEN** a prior inline finding's provider path is classified as lockfile, vendored, or generated
- **THEN** its conversation is absent from correctness, API-reality, and tests history views and remains available to safety and the coordinator

#### Scenario: Prior finding belongs to an ordinary source file
- **WHEN** a prior inline finding's provider path matches no exclusion rule
- **THEN** its conversation may appear in the bounded history view of a reviewer assigned that finding

#### Scenario: Provider object has no reliable path
- **WHEN** a review summary, issue comment, or legacy object has no trustworthy path association
- **THEN** the system does not invent a path classification and assigns or withholds it according to validated finding identity and reviewer scope

### Requirement: Preserve complete conversation for audit and safety
History filtering SHALL create derived reviewer views and SHALL NOT remove or rewrite any object in the canonical provider conversation snapshot. The complete snapshot SHALL remain authoritative for mode selection, ownership, legacy matching, coordinator completeness checks, freshness digests, idempotency checks, final action validation, and operator audit.

#### Scenario: Conversation is omitted from every file-scoped view
- **WHEN** a provider conversation is excluded from correctness, API-reality, and tests history views
- **THEN** it remains byte-for-byte represented in normalized form in the canonical snapshot and contributes to its digest

#### Scenario: Excluded finding has a planned status
- **WHEN** safety or the coordinator produces a validated status for an owned finding whose path is excluded
- **THEN** ownership, target relationship, freshness, and idempotency are validated against the complete conversation before mutation

#### Scenario: Excluded conversation changes
- **WHEN** a provider object omitted from file-scoped views changes before mutation
- **THEN** the complete conversation digest changes and the stale-history guard prevents all planned actions

### Requirement: Record deterministic history-view exclusions
For every recheck reviewer view, the system SHALL retain a deterministic exclusion manifest containing each omitted provider object or conversation identity, its associated path when known, assigned exclusion category, and exact matched rule. The manifest MUST NOT copy arbitrary provider-authored body text.

#### Scenario: History objects are excluded
- **WHEN** one or more path-bound conversations are omitted from a reviewer view
- **THEN** an operator can determine which provider identities were omitted and which existing path rule caused each omission

#### Scenario: No history objects are excluded
- **WHEN** every path-bound conversation relevant to the reviewer uses included source paths
- **THEN** the reviewer history exclusion manifest contains no exclusion records

#### Scenario: Identical history is filtered repeatedly
- **WHEN** the same canonical snapshot, target assignments, and path rules are processed more than once
- **THEN** the derived history views and exclusion manifests are byte-identical

### Requirement: History filtering does not authorize new recheck targets
The system SHALL use history filtering only to reduce assigned evidence. It MUST NOT create a target from an unowned conversation, assign a target absent from the owned initial review, or reinterpret a filtered conversation as a new finding.

#### Scenario: Included human comment resembles a finding
- **WHEN** an included path-bound human comment resembles an owned bot finding
- **THEN** history filtering does not add it to the recheck target roster

#### Scenario: Excluded bot conversation is visible to coordinator
- **WHEN** the coordinator receives an owned conversation omitted from a file-scoped view
- **THEN** it may validate completeness and ownership but does not create an additional target beyond the initial-review finding identities
