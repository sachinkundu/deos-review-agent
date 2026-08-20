## MODIFIED Requirements

### Requirement: Mint installation token
The system SHALL derive a new short-lived GitHub App installation token from the configured App private key, App ID, and installation ID at the start of every review run. It SHALL request access only to the target repository using the provider's repository name or ID contract and SHALL request no repository permission broader than the review workflow needs. It SHALL verify the returned repository selection and permissions before using the token and MUST NOT fall back to a broader installation token when a scoped request is rejected.

#### Scenario: Token minting succeeds
- **WHEN** the CLI starts a review with valid GitHub App credentials and the target repository is accessible to the installation
- **THEN** the system obtains and verifies a fresh token restricted to that repository with metadata read, contents read, pull-request write, and issue write access for the duration of the review run

#### Scenario: Token minting fails
- **WHEN** the App private key, App ID, installation ID, target repository name, requested permission, or returned scope is missing, invalid, inaccessible, or broader than requested
- **THEN** the review run fails fast with a sanitized provider error before any repository read, clone, agent execution, or GitHub mutation is attempted

#### Scenario: Provider rejects repository scope
- **WHEN** GitHub rejects the requested repository name or ID with a validation error
- **THEN** the system reports that scoped token failure and does not retry by minting an all-repositories token

### Requirement: Post pull request review bound to head SHA
In `initial-review` mode, the system SHALL post a pull request review containing inline comments and a summary body under the verified GitHub App identity, targeting the fetched head SHA, and SHALL read the created review back before recording the operation as complete.

#### Scenario: Review posts successfully
- **WHEN** the system submits a review with valid inline comments, a summary body, and the fetched head SHA as `commit_id`
- **THEN** GitHub creates the review against that exact commit and the system retains its stable review ID, URL, state, author, and body from provider read-back

#### Scenario: Head SHA changed after fetch
- **WHEN** the PR head SHA has changed between metadata fetch and review POST
- **THEN** the system re-fetches metadata and diff, or fails the run rather than posting against a stale head

#### Scenario: Review post fails
- **WHEN** GitHub rejects the review payload or provider read-back does not match the created review
- **THEN** the system surfaces the provider error without silently dropping findings or claiming the operation is complete

## ADDED Requirements

### Requirement: Verify the GitHub App provider identity
The system SHALL fetch the authenticated App identity with App JWT authentication and derive the bot username used for ownership and loop prevention from the provider App slug unless an explicitly configured username is verified against provider-authored objects. Pull request text or marker text MUST NOT define the App identity.

#### Scenario: App identity is available
- **WHEN** GitHub returns the authenticated App slug
- **THEN** the system derives the bot username in the provider's App-bot form and retains the verified identity without retaining credentials

#### Scenario: App identity cannot be verified
- **WHEN** the App identity request fails or lacks a usable slug and no configured identity can be verified
- **THEN** the run fails before history ownership decisions, agent execution, or GitHub mutations

### Requirement: Fetch complete paginated review history
The system SHALL use the run's fresh installation token to fetch all pages of pull request reviews, pull request review comments including replies, and issue comments on the pull request. It SHALL follow provider pagination until no next page remains and SHALL NOT infer completeness from a short page when a provider next link exists.

#### Scenario: One page exists on every surface
- **WHEN** each REST history endpoint returns one page without a next link
- **THEN** the system includes every returned review, review comment, reply, and issue comment in the provider conversation

#### Scenario: A REST surface has more than one page
- **WHEN** a history response includes a provider next-page link
- **THEN** the system follows provider pagination through the final page and retains each object exactly once

#### Scenario: A later page fails
- **WHEN** any required REST history page returns a transport, authentication, permission, rate-limit, or provider error
- **THEN** the system marks the history incomplete and stops before mode selection, agents, or GitHub mutations

### Requirement: Fetch complete GraphQL review threads when available
The system SHALL query review-thread state with the installation token and independently paginate both the pull request's review-thread connection and every thread's comment connection through their final cursors. It SHALL retain thread ID, resolution and outdated state, nullable current and original locations, diff sides, and comment relationships.

#### Scenario: Review threads span multiple pages
- **WHEN** the GraphQL review-thread connection reports another page
- **THEN** the system follows its end cursor until `hasNextPage` is false

#### Scenario: A thread has multiple comment pages
- **WHEN** a thread's comment connection reports another page
- **THEN** the system follows that thread's comment cursor independently until its `hasNextPage` is false

#### Scenario: GraphQL returns partial data with errors
- **WHEN** the GraphQL response includes errors, missing nodes, or an incomplete connection
- **THEN** the system does not treat the partial thread state as complete and records thread resolution as unknown in the normalized snapshot

### Requirement: Create replies only on top-level review comments
The system SHALL create a recheck reply only through GitHub's top-level review-comment reply contract using the pull request number and the numeric provider ID of the top-level comment. It MUST NOT target a reply as the parent and MUST NOT send path, line, side, or commit fields in a reply request.

#### Scenario: Top-level review comment is replyable
- **WHEN** a validated recheck action identifies one owned top-level review comment
- **THEN** the system submits only the reply body to that comment's provider reply endpoint

#### Scenario: Candidate parent is itself a reply
- **WHEN** the selected provider comment has a reply relationship
- **THEN** the system locates its unique top-level parent or stops without posting rather than attempting a reply-to-reply mutation

#### Scenario: Reply is rejected
- **WHEN** GitHub returns a not-found, permission, validation, rate-limit, or other provider error
- **THEN** the system retains a sanitized status and provider error shape and does not report the action as complete

### Requirement: Create general pull request status comments
The system SHALL create recheck statuses for owned findings without a replyable review thread as issue comments on the pull request, using an installation token with pull-request or issue write permission. The system MUST NOT attempt to attach these statuses to a diff line.

#### Scenario: Summary finding has a validated status action
- **WHEN** a fixed, unfixed, or obsolete owned finding exists only in a review summary or general comment
- **THEN** the system creates one general pull request comment containing the validated status, prior provider reference, stable finding identity, and action identity

#### Scenario: General comment is rejected
- **WHEN** GitHub returns a permission, validation, rate-limit, not-found, gone, or other provider error
- **THEN** the system retains a sanitized status and provider error shape and does not report the action as complete

### Requirement: Read every created provider object back
After GitHub accepts an initial review, review-comment reply, or general pull request comment, the system SHALL fetch that created object using its returned provider identity and verify its author, body marker, relationships, and pull request before retaining its provider ID and URL as durable run evidence.

#### Scenario: Created object matches the action
- **WHEN** provider read-back returns an object authored by the verified App with the expected action marker and target relationship
- **THEN** the system records the action as complete with the provider ID and URL

#### Scenario: Created object cannot be verified
- **WHEN** read-back fails or the returned author, marker, pull request, or relationship differs from the planned action
- **THEN** the system records an indeterminate provider outcome and does not claim verified completion

### Requirement: Preserve sanitized provider failures
For every GitHub REST or GraphQL operation used by history-aware reviews, the system SHALL retain the operation, HTTP or GraphQL status, request correlation metadata when returned, provider message and structured errors, and retry-relevant headers without retaining installation tokens, App JWTs, private keys, authorization headers, or arbitrary secret-bearing request data.

#### Scenario: REST returns a structured error
- **WHEN** GitHub returns a non-success response with message, status, documentation URL, or structured errors
- **THEN** the run artifact retains those sanitized fields and the failed operation

#### Scenario: GraphQL returns errors with partial data
- **WHEN** GitHub returns GraphQL errors alongside partial data
- **THEN** the run artifact retains sanitized errors and marks affected data incomplete rather than silently accepting it
