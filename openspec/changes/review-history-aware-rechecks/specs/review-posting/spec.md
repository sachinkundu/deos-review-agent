## MODIFIED Requirements

### Requirement: Post exactly one issue per inline comment
In `initial-review` mode, the system SHALL create one GitHub review comment per attachable finding and one separately identified summary entry per unattached finding; it SHALL NOT merge multiple findings into one prose item. Every inline comment and summary entry SHALL contain its stable finding identity.

#### Scenario: Multiple findings
- **WHEN** the initial-review coordinator produces several findings
- **THEN** each finding becomes a separately identified inline comment or a separately identified entry in the summary body

### Requirement: Set review event from severity
In `initial-review` mode, the system SHALL choose the GitHub review event based on the highest-severity finding according to the final rubric, regardless of whether the finding is attached to a diff line. Recheck mode SHALL report statuses through validated replies or general comments and SHALL NOT create another general defect-discovery review.

#### Scenario: No critical findings
- **WHEN** an initial review has no findings or only suggestions
- **THEN** the system posts the review with event `COMMENT` and includes a pass note in the summary body

#### Scenario: Critical findings
- **WHEN** an initial review has at least one critical or production-safety finding
- **THEN** the system posts the review with event `REQUEST_CHANGES`, even if the critical finding only appears in the summary body

#### Scenario: Recheck has completed classifications
- **WHEN** a recheck classifies its supplied prior finding targets
- **THEN** the system plans only the allowed per-finding status actions and does not post a new pull request review event

### Requirement: Validate output before posting
The system SHALL validate the mode-specific coordinator output and proposed action plan against their schemas before any GitHub mutation. It SHALL verify the initial review targets the fetched head SHA; for a recheck, it SHALL additionally verify that every action targets an owned prior finding and that the classified head SHA and conversation digest are still current.

#### Scenario: Payload is valid
- **WHEN** the initial-review output passes schema validation and targets the fetched head SHA
- **THEN** the system proceeds to the initial review freshness check and may post the validated review

#### Scenario: Recheck plan is valid
- **WHEN** the recheck output and action plan pass schema validation, every target is owned, and the exact head and history freshness checks pass
- **THEN** the system may execute the validated status actions

#### Scenario: Head SHA changed before posting
- **WHEN** the PR head SHA has changed between fetch and a planned initial review or recheck mutation
- **THEN** the system retains a stale result and stops without any GitHub mutation

#### Scenario: Conversation changed before recheck posting
- **WHEN** the complete normalized conversation digest changes after recheck classification
- **THEN** the system retains the stale classifications and plan and stops without any GitHub mutation

#### Scenario: Payload is invalid
- **WHEN** a mode-specific output or action plan fails schema validation
- **THEN** the system reports the validation errors and stops before any GitHub mutation

## ADDED Requirements

### Requirement: Separate classification, planning, and mutation
The system SHALL retain classification output and a proposed GitHub action plan as separate versioned artifacts before mutation. The planner SHALL accept only schema-valid classifications and provider-owned targets, and the mutator SHALL accept only a schema-valid plan that passed exact-head, exact-history, ownership, and idempotency checks.

#### Scenario: Classification completes
- **WHEN** the recheck coordinator returns valid target classifications
- **THEN** the system retains them without making a GitHub request that mutates provider state

#### Scenario: Planner rejects a target
- **WHEN** a classification refers to an unknown identity, non-owned provider object, reply-to-reply target, or unsupported action type
- **THEN** planning fails and no GitHub mutation occurs

#### Scenario: Mutation is disabled
- **WHEN** the CLI runs in dry-run mode
- **THEN** the validated classification and action plan are retained and displayed without creating, editing, deleting, replying to, or resolving any provider object

### Requirement: Mark initial runs, findings, and status actions
The system SHALL use versioned machine-readable markers for the initial-review record, each initial finding, and each recheck status action. Markers SHALL be deterministic for their represented identity, SHALL coexist with human-readable text, and SHALL exclude credentials, local paths, raw source content, and untrusted provider text.

#### Scenario: Initial review has no findings
- **WHEN** an initial review completes with a passing result
- **THEN** its summary contains an owned initial-run marker that causes later invocations to select recheck mode

#### Scenario: Inline and summary findings are rendered
- **WHEN** an initial review posts attachable and unattached findings
- **THEN** each human-readable finding item contains exactly one stable finding marker

#### Scenario: Recheck status is rendered
- **WHEN** the system plans a reply or general status comment
- **THEN** the human-readable status includes one action marker tied to the stable prior finding identity and classification inputs

### Requirement: Apply status actions without resolving or rewriting history
Recheck posting SHALL create only new replies to existing top-level owned review threads or new general pull request status comments for owned non-thread findings. It MUST NOT resolve or unresolve review threads, edit or delete earlier reviews or comments, or move a prior finding to a different diff line.

#### Scenario: Fixed inline finding is reported
- **WHEN** a fixed owned inline finding has a validated reply action
- **THEN** the system adds a status reply and leaves the thread's resolution state unchanged

#### Scenario: Prior finding moved to another line
- **WHEN** current-head evidence for a prior finding is found at a different location
- **THEN** the system retains the evidence in its status but does not create a new inline finding or relocate the old thread

#### Scenario: Provider thread is already resolved
- **WHEN** a fixed, unfixed, or obsolete owned finding belongs to a resolved thread
- **THEN** the system may add its validated status reply but does not change the resolution state

### Requirement: Prevent duplicate reviews and statuses
Before mutation, the system SHALL compare the planned initial-run, finding, and action identities with the complete provider conversation authored by the verified App. An identity already present SHALL be treated as an already completed action, while conflicting duplicate identities SHALL fail closed.

#### Scenario: Initial review is invoked identically twice
- **WHEN** the complete provider conversation already contains the same owned initial-run identity
- **THEN** the system does not create a duplicate review

#### Scenario: Recheck status is invoked identically twice
- **WHEN** the complete provider conversation already contains the same owned action identity
- **THEN** the system does not create a duplicate reply or general comment

#### Scenario: One identity appears with conflicting content
- **WHEN** verified App-authored provider objects contain the same machine identity but incompatible target, classification, or head data
- **THEN** the system records an integrity error and performs no GitHub mutation
