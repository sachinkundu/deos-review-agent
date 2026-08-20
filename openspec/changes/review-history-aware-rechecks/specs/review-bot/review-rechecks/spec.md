## Purpose

Provide auditable review cycles that discover defects on an initial head and then evaluate only those prior findings on later fix submissions.

## ADDED Requirements

### Requirement: Select review mode from the reviewed head and pending findings
The system SHALL bind every owned review run to its reviewed head and finding identities. A recheck SHALL occur only when an earlier head in the current review cycle produced one or more owned findings, at least one target remains pending, and a different head is submitted. Repeating a head already evaluated in that cycle SHALL be a no-op.

#### Scenario: Pull request has no owned review cycle
- **WHEN** no completed owned initial review exists for the pull request
- **THEN** the current head receives an initial defect-discovery review

#### Scenario: Initial review has no findings
- **WHEN** the owned initial review for a head contains no finding identities
- **THEN** that head has no recheck target and an identical invocation is a no-op

#### Scenario: New head follows a clean review
- **WHEN** the prior reviewed head had no findings and the pull request advances to a different head
- **THEN** the new head begins a new initial defect-discovery cycle rather than a zero-target recheck

#### Scenario: New head follows a review with findings
- **WHEN** the prior reviewed head produced one or more pending findings and the pull request advances to a different head
- **THEN** the new head receives a recheck limited to those prior finding identities

#### Scenario: Recheck leaves pending findings
- **WHEN** a recheck classifies any target as unfixed or ambiguous and a later head is submitted
- **THEN** the later head receives another recheck of the same pending identities and no new defect discovery

#### Scenario: Review cycle is complete
- **WHEN** every target is fixed or obsolete
- **THEN** the current cycle ends and a later changed head begins a new initial defect-discovery cycle

### Requirement: Retain a canonical provider conversation snapshot
The system SHALL normalize the complete fetched conversation into a versioned snapshot with deterministic ordering and a canonical digest. The snapshot SHALL preserve provider object identities, authorship, timestamps, raw untrusted text, reply and review relationships, nullable locations, source surface, and thread state.

#### Scenario: Complete provider reads succeed
- **WHEN** every required provider history page is fetched
- **THEN** the snapshot contains each fetched object exactly once and repeated normalization produces the same digest

#### Scenario: Provider location is nullable
- **WHEN** GitHub returns a null field allowed by its review or thread contract
- **THEN** normalization preserves an explicit null or `unknown` state instead of fabricating a location

#### Scenario: Provider text resembles instructions
- **WHEN** a review body or comment contains instructions, resource names, or marker-like text
- **THEN** it remains attributed untrusted data and cannot change mode, targets, tools, or resource access

### Requirement: Assign stable identities to initial findings
Every finding emitted by an initial review SHALL receive a stable finding identity tied to the reviewed head. A finding identity SHALL become an owned recheck target only when its provider object is authored by the verified GitHub App.

#### Scenario: Inline finding is created
- **WHEN** an initial finding is accepted on a right-side diff line
- **THEN** its stable identity is bound to the verified top-level provider comment

#### Scenario: Summary finding is created
- **WHEN** an initial finding cannot attach to a right-side diff line
- **THEN** its stable identity is bound to its separate entry in the verified review summary

#### Scenario: Human copies a finding marker
- **WHEN** a human-authored object contains a valid-looking finding marker
- **THEN** it does not become an owned target

### Requirement: Match unmarked legacy findings conservatively
The system SHALL consider only objects authored by the verified GitHub App when matching an unmarked legacy finding. A match SHALL require enough provider identity, conversation relationship, location where present, and normalized content evidence to identify exactly one prior finding; otherwise the candidate SHALL remain ambiguous and receive no mutation.

#### Scenario: One legacy finding matches
- **WHEN** exactly one App-authored legacy object satisfies the available evidence
- **THEN** the system assigns a retained derived identity and may recheck it

#### Scenario: Legacy match is not unique
- **WHEN** zero or multiple App-authored objects satisfy the available evidence
- **THEN** the candidate remains ambiguous and no GitHub action is planned

### Requirement: Rechecks classify only prior findings
For each owned target, the system SHALL return exactly one of `fixed`, `unfixed`, `obsolete`, or `ambiguous` with current-head evidence. Recheck output MUST NOT contain a newly discovered defect. Absence from the latest diff, movement of a line, a reply claiming a fix, or thread resolution alone MUST NOT prove a classification.

#### Scenario: Prior failure cannot occur on the current head
- **WHEN** current source and relevant conversation directly show that the reported failure is addressed
- **THEN** the target is classified `fixed`

#### Scenario: Prior failure remains reproducible
- **WHEN** current source directly shows that the reported failure still occurs
- **THEN** the target is classified `unfixed`

#### Scenario: Prior finding no longer applies
- **WHEN** current source directly shows that the reviewed behavior was intentionally removed or superseded
- **THEN** the target is classified `obsolete`

#### Scenario: Evidence does not settle the target
- **WHEN** available evidence cannot distinguish fixed, unfixed, or obsolete
- **THEN** the target is classified `ambiguous`

#### Scenario: Reviewer notices an unrelated defect
- **WHEN** a recheck reviewer notices a possible issue outside its target identities
- **THEN** the recheck output omits that issue and creates no comment for it

### Requirement: Guard and replay recheck plans safely
Immediately before a planned status mutation, the system SHALL re-fetch the exact head and complete conversation. A stale head or unexpected history change SHALL stop that mutation. Each action identity SHALL use only stable provider-independent inputs: contract version, target finding identity, classified head SHA, and classification.

#### Scenario: Head or conversation is stale
- **WHEN** the pre-mutation head or conversation differs from the classification inputs
- **THEN** the system retains the stale result and posts nothing further

#### Scenario: Equivalent evidence differs in wording
- **WHEN** repeated evaluation produces the same target, head, and classification with different evidence text
- **THEN** both plans derive the same action identity

#### Scenario: Identical action already exists
- **WHEN** an App-authored provider object already contains the planned action identity
- **THEN** the system treats the action as complete and does not post a duplicate
