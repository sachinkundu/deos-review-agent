# Progress Observability Specification

## Purpose

Give operators truthful live and retained visibility into long-running review runs without exposing sensitive model data or changing review outcomes.

## Requirements

### Requirement: Select the progress presentation
The system SHALL accept `--progress auto|plain|json|off` for review runs and SHALL default to `auto`. All new review-run progress output SHALL be written to standard error so existing final output on standard output remains compatible. `auto` SHALL use a live terminal presentation when standard error is an interactive terminal and SHALL otherwise emit newline-delimited plain progress events to standard error. An unsupported progress value MUST fail as a usage error before GitHub authentication or model execution begins.

#### Scenario: Interactive automatic mode
- **WHEN** an operator starts a review with the default progress mode and standard error is an interactive terminal
- **THEN** the system displays a live terminal presentation on standard error

#### Scenario: Redirected automatic mode
- **WHEN** an operator starts a review with the default progress mode and standard error is not an interactive terminal
- **THEN** the system emits stable newline-delimited plain progress to standard error without terminal control sequences

#### Scenario: Explicit presentation mode
- **WHEN** an operator selects `plain`, `json`, or `off`
- **THEN** the system uses exactly the selected progress behavior regardless of terminal detection

#### Scenario: Invalid presentation mode
- **WHEN** an operator supplies a progress value outside `auto`, `plain`, `json`, and `off`
- **THEN** the command reports a usage error without authenticating to GitHub or starting a model harness

### Requirement: Render useful human progress
The live terminal presentation SHALL use rich, colorful formatting wherever the terminal supports it and SHALL distinguish queued, active, successful, failed, timed-out, skipped, and interrupted work without claiming a completion percentage or model ETA. Plain progress SHALL represent the same state transitions as stable human-readable lines. Both presentations SHALL show elapsed time for active work and configured timeouts for active reviewer invocations.

The live terminal presentation SHALL render individual reviewers as visually
indented tree children of an aggregate `reviewers` row. When coordinator work
is visible, it SHALL render as a visually indented child of a separate
`coordination` row. Reviewer and coordinator children MUST NOT appear as peers
of their aggregate phase or as children of an unrelated current phase.

#### Scenario: Terminal supports rich color
- **WHEN** live progress is active in a terminal that supports color and live updates
- **THEN** the system uses color and live visual state to distinguish pipeline and reviewer status

#### Scenario: Color is disabled
- **WHEN** `NO_COLOR` is present or the terminal does not support color
- **THEN** progress remains visible and understandable without color

#### Scenario: Reviewer remains active
- **WHEN** a reviewer invocation is still running
- **THEN** the human presentation shows an indeterminate active state, its elapsed duration, and its configured timeout without showing a percentage or ETA

#### Scenario: Reviewer hierarchy is visible
- **WHEN** the live presentation shows the reviewer roster
- **THEN** `reviewers` is shown as the parent row and each registry-ordered reviewer is visually indented beneath it with tree connectors

#### Scenario: Coordinator hierarchy is visible
- **WHEN** the live presentation shows coordinator work
- **THEN** `coordination` is shown as a separate parent row and the coordinator is visually indented beneath it

#### Scenario: Plain progress is redirected
- **WHEN** plain progress is written to a file or non-interactive stream
- **THEN** each state transition is retained as one human-readable line with no cursor movement or color escape sequence

### Requirement: Emit a versioned machine-readable event stream
JSON progress SHALL emit exactly one complete JSON object per progress event on standard error, with no terminal control sequences or non-JSON progress text in that stream. Every event SHALL identify the progress contract version, opaque run identifier, monotonically increasing sequence number, UTC record time, non-negative elapsed seconds, phase, optional subject, state, sanitized message, and configured timeout when applicable.

The `review-progress-event/v1` contract SHALL support these phases: `credentials`, `pr-metadata`, `provider-diff`, `workspace`, `bootstrap`, `registry`, `reviewers`, `coordination`, `schema-validation`, `diff-validation`, `head-freshness`, `payload`, `posting`, and `cleanup`. It SHALL support these states: `queued`, `running`, `succeeded`, `failed`, `timed-out`, `skipped`, and `interrupted`.

#### Scenario: JSON progress is selected
- **WHEN** a review run changes progress state in JSON mode
- **THEN** the system emits one independently parseable `review-progress-event/v1` JSON object for that transition

#### Scenario: Events are consumed incrementally
- **WHEN** an automation reads JSON progress one line at a time
- **THEN** each line can be parsed without waiting for the run to finish and sequence numbers increase in emission order

#### Scenario: A phase has no applicable timeout
- **WHEN** a progress event describes work without a configured timeout
- **THEN** the event remains valid without inventing a timeout value

### Requirement: Expose truthful pipeline transitions
The system SHALL report the current pipeline phase before beginning potentially long-running provider, workspace, bootstrap, model, coordination, validation, posting, or cleanup work. It SHALL emit a final state for each started phase as soon as that state is known and SHALL represent inapplicable work as skipped rather than successful.

#### Scenario: Review starts normally
- **WHEN** valid review arguments have been accepted
- **THEN** the operator sees the first pipeline transition before credential or provider work can become a long silent operation

#### Scenario: Dry run reaches payload retention
- **WHEN** a dry run produces and retains its final review payload
- **THEN** payload retention is reported as succeeded and posting is reported as skipped

#### Scenario: Review is posted
- **WHEN** GitHub accepts the final review
- **THEN** posting is reported as succeeded and the final retained state includes the provider review URL when GitHub supplies one

#### Scenario: Bot-authored pull request is ignored
- **WHEN** the existing loop-prevention rule skips a pull request opened by the GitHub App bot
- **THEN** all work not performed after sender inspection is reported as skipped and the command retains its successful skip outcome

#### Scenario: Phase fails
- **WHEN** a started pipeline phase fails or times out
- **THEN** that phase is reported with the matching terminal state and a sanitized failure summary before the run returns its existing exit outcome

### Requirement: Show every reviewer and immediate settlement
Before any reviewer model invocation starts, the system SHALL expose every selected reviewer in deterministic registry order with its queued state and configured timeout. It SHALL expose each reviewer as running when its invocation starts and SHALL report its final state as soon as it settles, without waiting for slower reviewers. Downstream reviewer results and retained review artifacts MUST remain ordered by registry order even when progress reports a different completion order.

#### Scenario: Reviewers start concurrently
- **WHEN** the selected reviewer roster begins execution
- **THEN** every selected reviewer is visible in registry order before any one of them starts model work

#### Scenario: Later reviewer finishes first
- **WHEN** a reviewer later in registry order finishes before an earlier reviewer
- **THEN** its completion becomes visible immediately while the final result collection and raw findings remain in registry order

#### Scenario: Concurrency leaves reviewers waiting
- **WHEN** the selected roster is larger than the configured concurrency bound
- **THEN** waiting reviewers remain visibly queued and are not presented as running

#### Scenario: One reviewer fails
- **WHEN** one reviewer fails or times out while another reviewer succeeds
- **THEN** the failed reviewer remains visibly distinct, successful results can continue to coordination under the existing partial-failure contract, and the whole run is not presented as failed solely because of that reviewer

#### Scenario: Every reviewer fails
- **WHEN** every selected reviewer fails or times out
- **THEN** every reviewer outcome is visible and the run stops before coordination and posting with its existing all-reviewers-failed outcome

### Requirement: Retain an atomic progress snapshot
After a review workspace exists, the system SHALL atomically maintain `host-artifacts/progress.json` as a complete snapshot of the latest observable run state. A reader MUST observe either the previous complete snapshot or the next complete snapshot, never partial JSON.

The snapshot SHALL satisfy the `review-progress-snapshot/v1` contract with exactly these top-level fields and types:

- `contract`: the string `review-progress-snapshot/v1`;
- `run_id`: a non-empty opaque string that matches the run's event stream;
- `repository`: a non-empty `owner/name` string;
- `pull_request`: a positive integer;
- `head_sha`: the non-empty exact provider head SHA string checked out in the workspace;
- `mode`: either `dry-run` or `post`;
- `harness`: a non-empty harness identity string;
- `max_concurrency`: an integer of at least one;
- `overall`: an object with exactly `phase` and `state` string fields using the event contract's phase and state values;
- `started_at` and `updated_at`: UTC RFC 3339 timestamp strings ending in `Z`;
- `finished_at`: either a UTC RFC 3339 timestamp string ending in `Z` or `null` while unfinished;
- `reviewers`: an array in registry order whose items satisfy the work-item contract below;
- `coordinator`: either `null` before coordinator identity is available or a work-item object;
- `final_exit_code`: either an integer or `null` until an exit outcome is known; and
- `review_url`: either a non-empty provider review URL string or `null` when no accepted review URL is available.

Each reviewer and coordinator work-item object SHALL contain exactly `name`, `state`, `started_at`, `finished_at`, `elapsed_seconds`, `timeout_seconds`, and `error_summary`. `name` SHALL be a non-empty string; `state` SHALL use an event-contract state; each timestamp SHALL be a UTC RFC 3339 string ending in `Z` or `null` when that transition has not occurred; `elapsed_seconds` SHALL be a non-negative number; `timeout_seconds` SHALL be a non-negative number; and `error_summary` SHALL be a sanitized string or `null`. Before registry discovery completes, `reviewers` SHALL be empty and `coordinator` SHALL be `null` rather than containing invented identities.

#### Scenario: Workspace has been created
- **WHEN** progress changes after the host-artifacts directory exists
- **THEN** `progress.json` is atomically replaced with a valid `review-progress-snapshot/v1` object representing the latest state

#### Scenario: Reader races with an update
- **WHEN** a status reader opens the snapshot while the review process is updating it
- **THEN** the reader receives complete valid JSON from either side of the atomic replacement

#### Scenario: Workspace is retained
- **WHEN** a run uses `--keep-workspace`
- **THEN** its final progress snapshot remains beside the other host artifacts for later inspection

#### Scenario: Workspace is cleaned up
- **WHEN** ordinary session cleanup or the explicit cleanup command removes the PR workspace
- **THEN** the progress snapshot is removed as part of that workspace rather than retained elsewhere

#### Scenario: Failure occurs before workspace creation
- **WHEN** a run fails before a host-artifacts directory exists
- **THEN** terminal or stream progress reports the failure without creating a separate retained-state location

### Requirement: Inspect retained status without side effects
The CLI SHALL provide `review-bot status <PR_URL> [--workspace-root PATH] [--json]` to read the retained progress snapshot for that pull request. Status inspection MUST NOT authenticate to GitHub, contact a model harness, post a review, change the snapshot, or otherwise mutate the retained workspace.

#### Scenario: Human-readable status is requested
- **WHEN** an operator runs `review-bot status` for a workspace containing a valid snapshot
- **THEN** the command reports the retained pipeline, reviewer, timing, timeout, and final outcome information in human-readable form

#### Scenario: JSON status is requested
- **WHEN** an operator adds `--json` to a valid status request
- **THEN** the command emits the retained `review-progress-snapshot/v1` object on standard output as parseable JSON without terminal control sequences

#### Scenario: Custom workspace root is requested
- **WHEN** an operator supplies `--workspace-root`
- **THEN** status inspection resolves the same PR-specific workspace mapping used by review runs under that root

#### Scenario: Snapshot is absent or invalid
- **WHEN** the requested workspace has no progress snapshot or the snapshot does not satisfy its declared contract
- **THEN** the command reports a clear read error and performs no provider, model, posting, or workspace mutation

### Requirement: Sanitize progress data
Progress events, human renderings, failure summaries, and retained snapshots MUST NOT contain credentials; values or paths from explicitly sensitive environment variables, including names that identify tokens, secrets, keys, passwords, or credentials; prompts; model input or output; finding bodies; repository file contents; or subprocess command lines that could reveal sensitive arguments. Required non-sensitive progress metadata such as repository identity, pull request number, and head SHA SHALL remain permitted even when the same value was also supplied through a benign environment variable. Failure information SHALL be bounded and SHALL identify the affected phase or reviewer without copying untrusted raw output.

#### Scenario: Model returns sensitive output
- **WHEN** a reviewer fails after writing model output or prompt material to its captured process streams
- **THEN** progress identifies the reviewer and failure category without including that captured content

#### Scenario: Provider authentication fails
- **WHEN** credentials or token minting fails
- **THEN** progress reports the credentials phase failure without recording credential values or private-key paths

#### Scenario: Benign review metadata is supplied through the environment
- **WHEN** the pull request number or head SHA is also available through a non-sensitive review environment variable
- **THEN** the required snapshot metadata may contain that value without copying unrelated environment data

#### Scenario: Untrusted repository data causes a failure
- **WHEN** a repository path, file content, bootstrap output, or finding body contributes to an error
- **THEN** progress emits only a bounded sanitized summary and does not copy repository content into the event or snapshot

### Requirement: Preserve review behavior and outcomes
Progress mode and status retention MUST NOT change reviewer selection, harness prompts or model inputs, result ordering, coordinator behavior, final review schema, diff-line validation, exact-head safeguards, GitHub requests or payloads, final operator output, cleanup policy, or command exit codes. `off` SHALL suppress all new progress output while preserving existing warnings, errors, and final output.

#### Scenario: Progress modes review the same head
- **WHEN** equivalent review runs use different progress modes against the same exact pull request head and receive the same agent results
- **THEN** they produce equivalent review payloads, GitHub operations, retained non-progress artifacts, and exit outcomes

#### Scenario: Progress is disabled
- **WHEN** an operator selects `--progress off`
- **THEN** no new progress presentation or event stream is emitted and the command retains its pre-feature warnings, errors, final output, artifacts, and behavior

#### Scenario: Final output is produced with JSON progress
- **WHEN** a run uses JSON progress and also produces existing final operator output
- **THEN** standard error remains independently parseable as JSON progress lines and existing final output remains compatible on standard output

### Requirement: Record handled interruption truthfully
When the process can handle an operator interruption or termination signal, the system SHALL stop live rendering cleanly, mark active work and the overall run as interrupted, retain that final state if the workspace still exists, and preserve the command's established interruption semantics. The system SHALL NOT claim a final retained update when abrupt process or machine termination makes one impossible.

#### Scenario: Operator interrupts an active reviewer run
- **WHEN** the process handles an interruption while reviewers are running
- **THEN** active work is presented as interrupted, terminal control is restored, and the retained snapshot records the interrupted run when its workspace remains available

#### Scenario: Process cannot perform finalization
- **WHEN** the process or machine stops in a way that prevents cleanup handlers from running
- **THEN** the last complete atomic snapshot remains readable and no later final state is fabricated
