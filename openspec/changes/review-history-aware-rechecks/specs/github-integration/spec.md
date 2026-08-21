## ADDED Requirements

### Requirement: Fetch the complete pull request conversation
The system SHALL fetch all pages of pull request reviews, review comments and replies, and issue comments with the run's fresh installation token. It SHALL also fetch and independently paginate review threads and each thread's comments through GraphQL when that surface is available.

#### Scenario: REST history spans multiple pages
- **WHEN** a required REST history response advertises another page
- **THEN** the system follows provider pagination through the final page and retains each object exactly once

#### Scenario: GraphQL connections span multiple pages
- **WHEN** the review-thread connection or any thread's comment connection reports another page
- **THEN** the system follows each connection's cursor independently until it is complete

#### Scenario: Required REST history is incomplete
- **WHEN** any required REST history page fails or cannot be proven complete
- **THEN** the run stops before mode selection, agents, or GitHub mutation

#### Scenario: GraphQL thread state is unavailable
- **WHEN** REST history succeeds but GraphQL thread data is unavailable, forbidden, partial, or returns errors
- **THEN** the REST conversation remains usable and thread resolution is recorded as `unknown` rather than inferred

### Requirement: Establish provider-owned review objects
The system SHALL treat a review, inline comment, reply, or issue comment as bot-owned only when its provider author identity matches the verified GitHub App identity. Marker text alone MUST NOT establish ownership.

#### Scenario: App-authored object contains a valid marker
- **WHEN** a provider object is authored by the verified App and contains a valid review-bot marker
- **THEN** the object may establish an owned run, finding, or status identity

#### Scenario: Human copies a marker
- **WHEN** a human-authored provider object contains the same marker text
- **THEN** the object remains unowned and cannot become a recheck target or idempotency record

### Requirement: Create recheck statuses on their existing conversation surface
The system SHALL create an inline finding status only as a reply to its top-level review comment. For an owned finding without a replyable thread, it SHALL create a general pull request comment referencing the prior provider object and stable finding identity.

#### Scenario: Inline finding has a top-level comment
- **WHEN** a validated recheck action targets an owned inline finding
- **THEN** the system submits only the status body to that top-level comment's reply endpoint

#### Scenario: Candidate parent is a reply
- **WHEN** the selected provider comment is itself a reply
- **THEN** the system locates its unique top-level parent or posts nothing for that target

#### Scenario: Finding has no replyable thread
- **WHEN** a validated fixed, unfixed, or obsolete finding exists only in a review summary or general comment
- **THEN** the system creates one general pull request status comment without a diff location

### Requirement: Read back reviews and every created comment
After GitHub accepts an initial review, the system SHALL read back the review and enumerate the individual inline comments belonging to that review, binding each stable finding identity to its provider comment ID, URL, author, review ID, and top-level relationship. After GitHub accepts a recheck reply or general comment, the system SHALL read that created object back and verify its author, marker, pull request, and target relationship.

#### Scenario: Initial review contains inline findings
- **WHEN** GitHub creates an initial review with one or more inline comments
- **THEN** the system enumerates and verifies every created inline comment rather than treating review-object read-back as complete

#### Scenario: Initial finding appears only in the summary
- **WHEN** an initial finding is not attached to a diff line
- **THEN** the retained binding uses the verified review ID and URL plus that finding's separate summary marker

#### Scenario: Recheck status is created
- **WHEN** GitHub accepts a reply or general pull request comment
- **THEN** the system verifies and retains the created provider object's ID, URL, author, body marker, and target relationship

#### Scenario: Created object cannot be verified
- **WHEN** enumeration or read-back is incomplete or differs from the planned identity or relationship
- **THEN** the system records an indeterminate provider outcome and does not claim verified completion
