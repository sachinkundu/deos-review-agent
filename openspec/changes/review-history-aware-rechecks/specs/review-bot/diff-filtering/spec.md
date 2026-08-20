## ADDED Requirements

### Requirement: Apply existing path exclusions to reviewer history views
When a recheck history object is reliably associated with a file path, the system SHALL apply the existing lockfile, vendored, and generated classifications while constructing reviewer-scoped history views. This change MUST NOT alter classification rules, precedence, the reviewer roster, or the complete provider diff.

#### Scenario: Prior conversation belongs to an excluded path
- **WHEN** a path-bound conversation matches an existing exclusion rule
- **THEN** it is omitted from correctness, API-reality, and tests history views and remains available to safety and the coordinator

#### Scenario: Prior conversation belongs to an included path
- **WHEN** a path-bound conversation matches no exclusion rule
- **THEN** it may appear in the bounded view of a reviewer assigned that target

#### Scenario: Provider object has no reliable path
- **WHEN** a summary, issue comment, or legacy object cannot be associated with one trustworthy path
- **THEN** the system does not invent a path classification

### Requirement: Preserve complete history outside filtered reviewer views
History filtering SHALL derive reviewer views without removing or rewriting objects in the canonical provider conversation. Every omitted object SHALL remain available for ownership, coordinator completeness, freshness, idempotency, final action validation, safety review, and operator audit.

#### Scenario: Filtered conversation changes before posting
- **WHEN** a provider object omitted from a reviewer view changes after classification
- **THEN** the canonical conversation digest changes and the freshness guard prevents stale actions

#### Scenario: Reviewer history is filtered repeatedly
- **WHEN** the same conversation, target assignment, and existing path rules are processed again
- **THEN** the reviewer view and its omitted provider identities are identical
