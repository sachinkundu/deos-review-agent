## Purpose

Provide auditable, history-aware review runs that discover defects once and then recheck only those prior findings against the current pull request head.

## ADDED Requirements

### Requirement: Select initial-review or recheck mode from owned history
The system SHALL select exactly one review mode from the complete provider conversation. A pull request with no completed initial review owned by the configured GitHub App SHALL use `initial-review` mode. A pull request with a completed owned initial review SHALL use `recheck` mode, including when that initial review reported no findings. Ownership SHALL require verified provider authorship and SHALL NOT be established by marker text alone.

#### Scenario: Pull request has no owned initial review
- **WHEN** the complete provider conversation contains no completed initial-review record authored by the configured GitHub App
- **THEN** the run selects `initial-review` mode and may discover new defects

#### Scenario: Pull request has an owned initial review with findings
- **WHEN** the complete provider conversation contains a completed initial-review record authored by the configured GitHub App and one or more owned findings
- **THEN** the run selects `recheck` mode and targets only those prior findings

#### Scenario: Pull request has an owned passing initial review
- **WHEN** the complete provider conversation contains a completed initial-review record authored by the configured GitHub App with no findings
- **THEN** the run selects `recheck` mode with no finding targets and does not start a new defect-discovery pass

#### Scenario: Mode evidence is incomplete or contradictory
- **WHEN** provider history cannot establish a single trustworthy initial-review record or the record conflicts with verified provider identities
- **THEN** the run fails closed before agents or GitHub mutations and retains the ambiguity for audit

### Requirement: Retain a canonical provider conversation snapshot
The system SHALL normalize every fetched review, review comment and reply, issue comment, and review thread into a versioned conversation snapshot. The snapshot SHALL preserve stable provider object identities, authorship, timestamps, raw untrusted text, relationships, nullable locations, thread state, and source surface; SHALL order records deterministically; and SHALL include a canonical digest that changes when any normalized conversation value changes.

#### Scenario: Provider surfaces return the complete conversation
- **WHEN** all paginated provider reads succeed
- **THEN** the retained snapshot contains every fetched object exactly once in deterministic order with a reproducible digest

#### Scenario: Provider text contains instructions
- **WHEN** a review body or comment contains text that resembles a system instruction, resource name, or agent directive
- **THEN** the text remains attributed untrusted task data and does not alter run mode, resources, tools, or agent instructions

#### Scenario: Provider location is nullable
- **WHEN** GitHub returns a null current or original line, side, range, author, body, or timestamp field allowed by the provider contract
- **THEN** normalization preserves an explicit null or documented unknown value rather than fabricating a location or identity

#### Scenario: GraphQL thread state is unavailable
- **WHEN** REST history succeeds but GraphQL review threads are unavailable, forbidden, incomplete, or return errors
- **THEN** the snapshot retains the REST conversation, records thread resolution as `unknown`, records a sanitized provider failure, and does not infer resolution from comment content

### Requirement: Assign stable identities to owned initial findings
Every finding emitted in `initial-review` mode SHALL receive a stable finding identity and an owned provider marker, whether the finding is posted inline or rendered only in the review summary. A marker SHALL be accepted as an owned identity only when the containing provider object is authored by the verified GitHub App identity.

#### Scenario: Inline finding is posted
- **WHEN** an initial finding maps to an accepted right-side diff line
- **THEN** its top-level review comment contains its stable finding identity and the retained record binds that identity to the returned provider comment ID and URL

#### Scenario: Finding is rendered in the review summary
- **WHEN** an initial finding cannot be attached to an accepted right-side diff line
- **THEN** its separate summary entry contains its stable finding identity and the retained record binds that identity to the returned provider review ID and URL

#### Scenario: User copies a finding marker
- **WHEN** a human-authored review or comment contains text that matches the bot's marker format
- **THEN** the system does not treat that object as an owned finding

### Requirement: Match unmarked legacy findings conservatively
The system SHALL consider only provider objects authored by the verified GitHub App when matching an unmarked legacy finding. It SHALL match a legacy finding only when provider identity, source surface, path and location where present, normalized title and body evidence, and conversation relationships identify exactly one prior finding; otherwise it SHALL classify the candidate as ambiguous.

#### Scenario: One legacy finding matches exactly
- **WHEN** one bot-authored legacy finding uniquely matches the available provider and content evidence
- **THEN** the recheck assigns it a retained derived identity and may evaluate it

#### Scenario: Multiple legacy findings could match
- **WHEN** more than one bot-authored legacy object satisfies the available matching evidence
- **THEN** the system records an ambiguous match and plans no GitHub mutation for that candidate

#### Scenario: Human finding resembles a bot finding
- **WHEN** a human-authored comment has matching path, title, or body text
- **THEN** it is never adopted as an owned legacy finding

### Requirement: Rechecks evaluate prior findings without discovering new defects
In `recheck` mode, the system SHALL evaluate only the stable identities supplied from the owned initial review. Reviewers and the coordinator MUST NOT emit, accept, or post a defect whose identity is absent from that target set. Initial-review mode MAY classify newly discovered findings as `new`; recheck mode SHALL NOT use `new` as a finding state.

#### Scenario: Reviewer notices an unrelated defect during recheck
- **WHEN** a recheck reviewer encounters a possible issue that is not one of its supplied prior finding identities
- **THEN** the reviewer output omits that issue and the run creates no comment or status for it

#### Scenario: Recheck output introduces an unknown identity
- **WHEN** a reviewer or coordinator returns a finding identity absent from the owned target set
- **THEN** schema validation fails and the run stops before any GitHub mutation

#### Scenario: Initial review discovers a defect
- **WHEN** an initial-review coordinator retains a new valid finding
- **THEN** the finding is classified as `new`, receives a stable identity, and follows initial posting rules

### Requirement: Classify every recheck target with current-head evidence
The system SHALL classify every applicable recheck target as exactly one of `fixed`, `unfixed`, `obsolete`, or `ambiguous` and SHALL retain current-head evidence and reasoning for the classification. Absence from the latest diff, movement of a line, a reply claiming a fix, or review-thread resolution alone MUST NOT prove that a finding is fixed or obsolete.

#### Scenario: Finding is fixed
- **WHEN** current-head source and relevant provider context provide direct evidence that the reported failure can no longer occur
- **THEN** the target is classified `fixed` with that evidence

#### Scenario: Finding remains reproducible
- **WHEN** current-head source provides direct evidence that the reported failure still occurs
- **THEN** the target is classified `unfixed` with that evidence

#### Scenario: Finding no longer applies
- **WHEN** current-head source provides direct evidence that the reviewed behavior or requirement was intentionally removed or superseded so the original claim is no longer applicable
- **THEN** the target is classified `obsolete` with that evidence

#### Scenario: Evidence does not settle the finding
- **WHEN** available source and conversation evidence cannot distinguish fixed, unfixed, or obsolete
- **THEN** the target is classified `ambiguous` and no GitHub mutation is planned for it

#### Scenario: Thread was resolved manually
- **WHEN** GitHub reports the finding's thread as resolved but current-head evidence does not prove a classification
- **THEN** thread resolution is retained as context and the target remains `ambiguous`

### Requirement: Plan recheck mutations deterministically
The system SHALL derive GitHub actions only after all target classifications validate. Owned inline findings classified `fixed`, `unfixed`, or `obsolete` SHALL plan one status reply to the existing top-level review thread. Equivalent owned non-thread findings SHALL plan one general pull request status comment referencing the prior provider object and stable finding identity. Ambiguous findings SHALL plan no mutation, and no recheck action SHALL create a new defect finding or resolve a thread.

#### Scenario: Inline finding receives a status
- **WHEN** an owned inline finding is classified fixed, unfixed, or obsolete and has a replyable top-level comment
- **THEN** the plan contains one reply targeting that top-level provider comment ID

#### Scenario: Summary-only finding receives a status
- **WHEN** an owned summary finding is classified fixed, unfixed, or obsolete and has no replyable review thread
- **THEN** the plan contains one idempotent general pull request comment referencing its provider review ID or URL and stable finding identity

#### Scenario: Finding is ambiguous
- **WHEN** an owned finding is classified ambiguous
- **THEN** the retained plan records no GitHub action for that identity

#### Scenario: Candidate target is a reply
- **WHEN** a matched inline provider object is itself a reply rather than a top-level review comment
- **THEN** the system traces it to exactly one top-level comment or records the action as ambiguous instead of replying to a reply

### Requirement: Guard recheck actions with exact-head and exact-history freshness
Immediately before the first planned GitHub mutation, the system SHALL re-fetch the pull request head and complete provider conversation using a fresh run-scoped installation token. It SHALL require both the head SHA and canonical conversation digest to equal the values used for classification. Before every later mutation in the same plan, it SHALL require the head to remain equal and the conversation to equal the classified snapshot plus only the plan's earlier provider-verified actions. If either guard fails, the system SHALL retain the stale or partial result and stop further mutations.

#### Scenario: Head and conversation remain unchanged
- **WHEN** the pre-mutation head SHA and history digest equal the classified snapshot
- **THEN** the system may execute the validated action plan

#### Scenario: Pull request head changed
- **WHEN** the pre-mutation head SHA differs from the classified head SHA
- **THEN** the system marks the run stale, retains both SHAs, and performs no GitHub mutation

#### Scenario: Conversation changed
- **WHEN** the pre-mutation conversation digest differs from the classified digest
- **THEN** the system marks the run stale, retains both digests, and performs no GitHub mutation

#### Scenario: Conversation changes during a multi-action plan
- **WHEN** a later pre-mutation conversation contains any change other than earlier provider-verified actions from the same plan
- **THEN** the system retains the completed actions, marks the remaining plan stale, and performs no further GitHub mutation

### Requirement: Make recheck mutations replay safe
Every planned recheck action SHALL carry a deterministic action identity derived from the run mode, target finding identity, classification, classified head SHA, and normalized classification evidence. The action identity MUST NOT depend on conversation fields changed by creating that action. Before creating an action, the system SHALL search the complete provider conversation for an owned object with that action identity; after creation, it SHALL read the provider object back and retain its ID and URL.

#### Scenario: Identical recheck is repeated
- **WHEN** an identical action identity already exists in a provider object authored by the verified App
- **THEN** the system treats the action as already complete and does not create a duplicate reply or general comment

#### Scenario: Provider accepts a status action
- **WHEN** GitHub creates a planned reply or general comment
- **THEN** the system reads that object back and retains its stable provider ID, URL, authorship, body, and relationship to the target

#### Scenario: Provider fails during a multi-action plan
- **WHEN** one action fails after earlier actions were read back successfully
- **THEN** the system retains the partial outcome, stops further mutations, and a later identical run skips the completed action identities before retrying remaining actions
