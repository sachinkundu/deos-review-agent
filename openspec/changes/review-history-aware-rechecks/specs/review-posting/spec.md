## ADDED Requirements

### Requirement: Mark initial review runs and findings for later recheck
Every initial review SHALL contain a versioned run marker bound to its reviewed head. Every initial finding SHALL contain one stable finding identity, whether GitHub accepts it as an inline comment or it appears as a separate review-summary entry. Markers SHALL be human-readable alongside the finding and MUST NOT contain credentials, local paths, or untrusted provider text.

#### Scenario: Initial review has inline findings
- **WHEN** the initial review posts attachable findings
- **THEN** each inline comment contains exactly one stable finding marker

#### Scenario: Initial review has summary findings
- **WHEN** an initial finding cannot attach to an accepted right-side diff line
- **THEN** its separate summary entry contains exactly one stable finding marker

#### Scenario: Initial review has no findings
- **WHEN** an initial review completes without a finding
- **THEN** its summary contains a run marker for duplicate detection but creates no recheck target

### Requirement: Separate recheck classification from GitHub mutation
The system SHALL retain schema-valid recheck classifications and a proposed action plan before mutation. Dry-run mode SHALL expose those artifacts without creating, editing, deleting, replying to, resolving, or unresolving any provider object.

#### Scenario: Recheck classification completes
- **WHEN** the coordinator returns every applicable prior target exactly once
- **THEN** the system retains the classifications before planning any provider write

#### Scenario: Planner receives an invalid target
- **WHEN** a classification targets an unknown, unowned, ambiguous, or non-top-level provider object
- **THEN** the planner emits no GitHub mutation for that target

#### Scenario: Dry run completes
- **WHEN** mutation is disabled
- **THEN** the system retains the validated plan and posts nothing

### Requirement: Restrict recheck posting to status updates
Fixed, unfixed, and obsolete inline findings SHALL plan one reply to their existing top-level threads. Equivalent non-thread findings SHALL plan one general pull request status comment. Ambiguous findings SHALL plan no mutation. A recheck MUST NOT create a new defect review, move a prior finding, edit or delete history, or change thread resolution.

#### Scenario: Inline target has a settled classification
- **WHEN** an owned inline finding is fixed, unfixed, or obsolete
- **THEN** the plan contains one status reply and no new inline finding

#### Scenario: Non-thread target has a settled classification
- **WHEN** an owned summary or general-comment finding is fixed, unfixed, or obsolete
- **THEN** the plan contains one general status comment referencing that prior provider object

#### Scenario: Target is ambiguous
- **WHEN** available evidence does not settle a prior finding
- **THEN** the plan records no GitHub mutation for it

### Requirement: Guard and deduplicate recheck mutations
Immediately before each planned mutation, the system SHALL verify that the pull request head and complete conversation still match the classification inputs plus any earlier provider-verified actions from the same plan. Each action identity SHALL derive only from stable inputs: contract version, target finding identity, classified head SHA, and classification. Generated evidence text MUST NOT affect the identity.

#### Scenario: Head or conversation changed before the first action
- **WHEN** the current head or conversation differs from the classified snapshot
- **THEN** the system retains a stale plan and posts nothing

#### Scenario: Conversation changes during a multi-action plan
- **WHEN** a later guard observes a change other than an earlier verified action from the same plan
- **THEN** the system retains completed actions and stops all remaining mutations

#### Scenario: Equivalent evidence is worded differently
- **WHEN** repeated evaluation returns the same target, head, and classification with different evidence wording or ordering
- **THEN** both evaluations derive the same action identity

#### Scenario: Action identity already exists
- **WHEN** the complete App-authored conversation already contains the planned action identity
- **THEN** the system treats the action as complete and creates no duplicate reply or general comment
