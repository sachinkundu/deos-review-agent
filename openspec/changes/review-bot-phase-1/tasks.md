# Tasks: review-bot-phase-1

Implements the approved proposal, specs, and design for the Phase 1 local CLI
review bot. Order is by dependency; deterministic tests land before live
GitHub integration.

## 1. Project setup

- [x] 1.1 Create `pyproject.toml` (uv-managed, Python >=3.11) with runtime deps (requests, PyJWT, cryptography, jsonschema) and dev deps (pytest, ruff, pyright), plus a `review-bot` console entrypoint
- [x] 1.2 Create the `review_bot/` package layout per design (review.py, github.py, workspace.py, shared_context.py, agents/, coordinator.py, schema.py, schema.json, diff_validator.py, prompts/)
- [x] 1.3 Add `.env.example` and confirm `.env` / `.env.*` are gitignored; never commit credentials

## 2. Review output schema and validation

- [x] 2.1 Write `schema.json` (strict, additionalProperties:false) for the review output contract: findings (title <=80, body, confidence_score, priority 0-2, code_location with line_range, suggested_fix), overall_correctness, overall_explanation, overall_confidence_score, status
- [x] 2.2 Implement `schema.py` load + validate helpers with actionable error messages
- [x] 2.3 Add deterministic tests: valid output passes; each invalid shape (missing field, bad priority, bad enum, >80-char title, wrong line_range) fails with a clear error

## 3. GitHub App client (github.py)

- [x] 3.1 Parse PR URLs (https://github.com/{owner}/{repo}/pull/{number}) and reject anything else
- [x] 3.2 Implement App JWT minting (RS256, iss=App ID, iat=now, exp<=10min) from the configured private key, and installation-token exchange (`POST /app/installations/{id}/access_tokens`, Bearer JWT) with repository-scoped tokens; fail fast on missing/invalid credentials; never log tokens
- [x] 3.3 Implement PR metadata fetch (title, body, head SHA, base SHA, sender login, head repo clone URL, changed files) and diff fetch (raw unified diff via `application/vnd.github.v3.diff`)
- [x] 3.4 Implement bot-self-skip (sender login == configured bot username -> exit successfully without posting) and linked-issue-reference extraction (e.g. `Fixes #123`, `SAC-87`) into shared context inputs
- [x] 3.5 Implement review POST bound to the fetched head SHA (`commit_id`, event, body, inline comments with path + side=RIGHT + line), re-checking head SHA before posting (re-fetch or fail, never post against a stale head); surface provider errors without dropping findings
- [x] 3.6 Add deterministic tests (no network): URL parsing, JWT claims/algorithm/expiration bounds against a generated keypair, credential fail-fast, bot-skip, event mapping from priority rubric (0/1->COMMENT, 2->REQUEST_CHANGES, no findings->COMMENT with pass note), payload construction with commit_id and side/line comments, head-SHA-stale handling

## 4. Local workspace (workspace.py)

- [x] 4.1 Clone the PR head repo into `{workspace_root}/{owner}-{repo}-pr{number}` (workspace root from env or CLI option) using the installation token via git askpass (token never on the command line)
- [x] 4.2 Check out the PR branch at exactly the head SHA reported by GitHub; verify HEAD equals the head SHA
- [x] 4.3 Run the consumer-provided bootstrap script (`.review-bot/bootstrap.sh`) in the workspace when present, with a timeout; bootstrap failure stops the run
- [x] 4.4 Implement session cleanup: retain workspace during the run; delete after posting for single-turn sessions; `--keep-workspace` to retain; explicit `cleanup` CLI command removes the PR workspace regardless of session state
- [x] 4.5 Add deterministic tests: clone/checkout against a real local git fixture at a fixed SHA, bootstrap success/failure paths, cleanup behaviors

## 5. Shared context (shared_context.py)

- [x] 5.1 Write `shared-context.md` into the workspace from PR metadata (title, body, head/base SHA, sender, changed files, linked issue references) plus bootstrap/validation results; write the raw diff to `review-diff.diff`
- [x] 5.2 Add deterministic tests for shared-context content (all required sections present, linked references included)

## 6. Review agents and pipeline

- [x] 6.1 Implement the agent runner abstraction (subprocess-driven, provider-agnostic in wiring): default driver `codex exec` with read-only sandbox, `--output-schema`, last-message file output, configurable timeout and model; runner injectable for tests
- [x] 6.2 Write `prompts/correctness.md` (flag logic bugs, unhandled error paths, claim mismatches, architecture-ordering bugs; never style/formatting/naming/refactors; every finding needs a concrete failure scenario + suggested fix; one issue per finding; locations must be right-side diff lines; read outside the diff only when needed for correctness)
- [x] 6.3 Write `prompts/api-reality.md` (flag only hallucinated/misused dependency APIs grounded in published documentation; every finding cites the documentation URL, a concrete failure scenario, and a suggested fix; respect declared dependency versions; never flag logic/style)
- [x] 6.4 Run the correctness and API-reality agents concurrently (both receive shared context + diff); one agent failing or returning invalid JSON is reported in the review summary while the run continues with the other agent's findings
- [x] 6.5 Implement the coordinator (`coordinator.py` + `prompts/coordinator.md`): receives all findings with agent attribution, deduplicates by (path, start_line, normalized_title), drops speculative/contradicted findings, rewrites each remaining finding to exactly one issue, assigns final priority and overall verdict per the rubric
- [x] 6.6 Fail the run (non-zero, no post) when coordinator output fails schema validation; preserve the `status` field through agent output to coordinator output
- [x] 6.7 Add deterministic tests with an injected fake agent runner: concurrency, one-agent-failure continuation with summary note, coordinator input contains combined findings, coordinator invalid output stops the run, status preservation

## 7. Diff validation and review posting (diff_validator.py)

- [x] 7.1 Parse the raw unified diff per file (renames, new/deleted files, multiple hunks, no-newline markers) into right-side line sets
- [x] 7.2 Validate every finding's `(path, line_range, side=RIGHT)` against the parsed diff; attachable findings become one inline comment each; unattachable findings move to the review summary body as separate entries (one issue per entry)
- [x] 7.3 Build the final review body (overall explanation, pass note or agent-failure notes, unattached findings) and inline comment bodies (evidence, problem, failure scenario, suggested fix description + replacement)
- [x] 7.4 Add deterministic tests: attachable vs unattachable mapping (added lines, context lines, removed-line-only, deleted files, out-of-range), one-comment-per-finding, event chosen from highest severity regardless of attachment, summary-body fallback content

## 8. CLI wiring (review.py)

- [x] 8.1 Wire the end-to-end flow: load .env credentials -> mint token -> fetch metadata/diff -> bot-skip check -> workspace clone/checkout/bootstrap -> shared context -> concurrent agents -> coordinator -> schema validation -> diff validation -> head-SHA re-check -> post (or dry-run print) -> session cleanup
- [x] 8.2 Add `--dry-run` (full pipeline, print the final review payload, no GitHub POST) and `--keep-workspace` / `cleanup` commands; top-level errors exit non-zero with a clear message
- [x] 8.3 Add deterministic tests for the CLI flow with injected fakes: happy path, bot-skip exits 0 with no post, dry-run posts nothing, agent failure surfaces in summary, stale head fails without posting

## 9. Provider-contract verification and local proof

- [x] 9.1 Verify the real GitHub provider contract against live docs/API (App JWT + installation token exchange, PR diff media type, review POST with side/line semantics) and record the exact wire formats in code comments/tests
- [ ] 9.2 Create the e2e test repository and a real PR with seeded defects (a logic bug on an added line, a hallucinated dependency API with published docs, a PR-body claim the code does not honor, linked issue references)
- [ ] 9.3 Register and install the GitHub App (permissions: pull requests read+write, contents read, metadata read) on the e2e repository; store App ID, installation ID, and private key in gitignored `.env` / outside the repo
- [ ] 9.4 Local proof: run the CLI end-to-end with `--dry-run` against the real PR (real token minting, real diff, real agents) and capture the would-be review payload without posting

## 10. Provider-origin proof and visual evidence

- [ ] 10.1 Run the CLI without `--dry-run` so the GitHub App posts the review on the real PR; confirm inline comments map to diff lines exactly as GitHub accepts them
- [ ] 10.2 Capture screenshots of the GitHub App configuration, the PR review state, and the posted comments; attach the strongest available visual proof to the implementation PR
- [ ] 10.3 Keep `.env` and the App private key out of the repository; verify no secret appears in the diff, logs, or committed files

## 11. Final PR

- [ ] 11.1 Update all task checkboxes, cite the approved planning PR (#1), task IDs, and spec requirements in the PR body; include tests, evidence (local proof, provider-origin proof, screenshots), and mark ready for review
