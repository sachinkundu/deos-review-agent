# PR Review Bot — Proposal and Learnings

**Status:** Draft — exploration complete, implementation not started  
**Scope:** A correctness-focused PR review bot that posts line comments as a GitHub App, using specialized sub-agents and a final coordinator. This document captures what we learned from prior work and from Cloudflare's internal AI code review system, and it defines the first version we intend to build.

This proposal deliberately stays outside the existing `deos` orchestration architecture. Integration with Cloudflare Workers, Workflows, D1, R2, and the planned `code_review` agent node is a later step. The goal here is to design and validate the review experience locally first.

---

## 1. What we are building

A local-first review bot that:

1. Receives a PR URL (via CLI or, later, a GitHub webhook).
2. Fetches the PR diff and metadata using a GitHub App installation token.
3. Checks out the PR branch in an isolated workspace.
4. Runs specialized sub-agents concurrently to look for different classes of problems.
5. Runs a coordinator agent that deduplicates, filters, and rewrites the findings.
6. Posts the final review as line comments from a GitHub App.

The bot's single purpose is **correctness verification**. It is not an architecture reviewer, a style enforcer, or a general-purpose coding assistant.

---

## 2. Key learnings

### 2.1 From `cloglog`

`cloglog` had a two-stage review pipeline (local `opencode` first, cloud `codex` second) with persistent turn accounting in a dedicated `Review` bounded context. The parts that generalize cleanly:

- **Structured output beats freeform prose.** A fixed JSON schema with `title`, `body`, `priority`, `code_location`, and `suggested_fix` is much easier to post to GitHub than parsing Markdown.
- **Validate line numbers against the diff before posting.** GitHub rejects comments whose `(path, line, side=RIGHT)` is not in the PR diff. A small diff parser that maps each file to its new-side line numbers prevents the whole review from failing because of one bad line.
- **One finding = one GitHub comment.** Each finding becomes one inline comment. Findings that cannot be attached to a diff line go into the review summary body, not into another inline comment.
- **Persist turn state atomically.** `INSERT ... ON CONFLICT DO NOTHING` on `(pr_url, head_sha, stage, turn_number)` prevents double-posting on webhook re-fires. We will keep this pattern when we move to D1.
- **Author-skip is required.** A bot-authored PR must not trigger a review loop.
- **Preserve the `status` field through every parser rewrite.** Losing the explicit-consensus flag between agent output and orchestrator input silently breaks short-circuit logic.

What we are **not** carrying over from `cloglog`:

- The DDD bounded-context layout (`src/review` as a supporting domain).
- The two-stage opencode-then-codex pipeline.
- The per-project worktree resolution logic.

### 2.2 From Cloudflare's internal AI code review system

Cloudflare's system uses up to seven specialized agents managed by a coordinator agent, running inside CI via OpenCode. The concepts that fit our smaller scope:

- **Specialized sub-agents with "what to ignore" instructions.** The most valuable prompt engineering is telling the agent what *not* to flag. This dramatically reduces noise.
- **A coordinator that deduplicates, re-categorizes, and judges findings.** Raw sub-agent output is too noisy to post directly. A coordinator produces the final, clean review.
- **Risk tiers.** Small diffs do not need the full agent roster. This saves tokens and latency.
- **Bias toward approval.** A single warning should not block a merge; only critical/production-safety issues should request changes.
- **Shared context file.** Write PR metadata once to a file on disk and let each sub-agent read it, instead of duplicating context in every prompt.
- **Diff filtering.** Strip lockfiles, generated assets, and vendored dependencies before agents see the diff.
- **Re-reviews aware of prior findings.** On new pushes, the coordinator receives prior findings and user replies so it can drop fixed items and re-emit unfixed ones.
- **Break-glass escape hatch.** A human reviewer comment like `break glass` forces approval.

What we are **not** carrying over:

- The full plugin architecture.
- Multiple AI providers and model tiers.
- JSONL streaming pipeline.
- Circuit breakers and failback chains.
- Workers KV control plane.

### 2.3 From our own iteration on the prompt

- Repeating "read files outside the diff" became a mantra that diluted the prompt. The instruction should be: "read files outside the diff only when you need context to judge correctness."
- Boundary/DDD language is not relevant to the correctness task. The prompt should focus on bugs, claim verification, test coverage, and error paths.
- Every finding must include a concrete failure scenario and a suggested fix.
- Each GitHub comment must contain exactly one issue. Multiple findings must not be merged into one prose comment.

---

## 3. Proposed architecture

```text
PR URL / webhook
  |
  v
GitHub App client  ---->  fetch PR metadata + diff
  |
  v
Workspace setup    ---->  clone repo, checkout PR branch
  |
  v
Diff filtering     ---->  remove lockfiles, generated files, noise
  |
  v
Shared context     ---->  write pr.json + changed-files + validation results
  |
  v
Sub-agents (concurrent, per risk tier)
  - correctness agent
  - tests agent
  - safety agent (full tier only)
  |
  v
Coordinator agent  ---->  dedupe, filter, rewrite, assign severity, verdict
  |
  v
GitHub review POST ---->  line comments + summary body as the GitHub App
```

### 3.1 Components

| Component | Responsibility |
|---|---|
| `github.py` | App JWT, installation token, fetch PR/diff, post review. |
| `workspace.py` | Clone/checkout PR branch, run validation commands. |
| `diff_filter.py` | Strip noise files from diff. |
| `shared_context.py` | Assemble `shared-context.md` from PR metadata. |
| `agents/` | Prompts for correctness, tests, safety sub-agents. |
| `coordinator.py` + `prompts/coordinator.md` | Run coordinator agent with sub-agent findings. |
| `schema.py` / `schema.json` | Validate agent and coordinator output. |
| `review.py` | CLI entrypoint that wires everything together. |

### 3.2 Risk tiers

| Tier | Trigger | Agents |
|---|---|---|
| Trivial | ≤10 changed lines, ≤2 files | Coordinator + Correctness |
| Lite | ≤100 changed lines, ≤10 files | Coordinator + Correctness + Tests |
| Full | >100 lines, >10 files, or security-sensitive path | Coordinator + Correctness + Tests + Safety |

Security-sensitive paths always trigger the safety agent, regardless of size:
- `src/deos/ingress.py`
- any file under `auth/`, `crypto/`, `secrets/`
- `wrangler.jsonc`, `.env` handling
- files matching `*secret*`, `*credential*`, `*token*`

---

## 4. Data flow

### 4.1 Inputs to each sub-agent

- `shared-context.md` (PR title, body, head SHA, base SHA, changed files, validation command results)
- filtered diff (per-file patches)
- agent-specific prompt

### 4.2 Sub-agent output

A JSON object matching `review-schema.json`:

```json
{
  "findings": [
    {
      "title": "<=80 chars",
      "body": "evidence + problem + failure scenario",
      "confidence_score": 0.85,
      "priority": 2,
      "code_location": {
        "absolute_file_path": "src/deos/ingress.py",
        "line_range": {"start": 42, "end": 42}
      },
      "suggested_fix": {
        "description": "Add a None guard before the dict access.",
        "replacement": "if payload is None:\n    return Response(...)"
      }
    }
  ],
  "overall_correctness": "patch is correct" | "patch is incorrect",
  "overall_explanation": "one paragraph",
  "overall_confidence_score": 0.85,
  "status": "no_further_concerns" | "review_in_progress"
}
```

### 4.3 Coordinator output

Same schema. The coordinator's job is to:

1. Read sub-agent findings.
2. Deduplicate by `(file, start_line, normalized_title)`.
3. Drop speculative, stylistic, or contradicted findings.
4. Rewrite each remaining finding so it contains exactly one issue.
5. Assign final severity and verdict using the rubric below.

### 4.4 Final rubric

| Condition | `verdict` | GitHub `event` |
|---|---|---|
| No findings, or only suggestions | `patch is correct` | `COMMENT` (with pass note) |
| Any warning, no critical/production risk | `patch is incorrect` | `COMMENT` |
| Any critical finding, or production-safety risk | `patch is incorrect` | `REQUEST_CHANGES` |

The bot is biased toward approval. Warnings are surfaced as comments, not blocks.

---

## 5. Prompt design principles

Prompts will be created during implementation. They should follow these principles:

- Short and scoped to one agent.
- Explicit "What to flag" and "What NOT to flag" sections.
- Require a concrete failure scenario for every finding.
- Require a suggested fix for every finding.
- Enforce one issue per finding.
- Output only the JSON object matching `review-schema.json`.
- Avoid architecture/DDD boundary language; focus on correctness.
- Avoid repeating instructions as mantras.

Agents needed:

- Correctness agent
- Tests agent
- Safety agent
- Coordinator agent (deduplicates, filters, rewrites, assigns final severity)

---

## 6. GitHub App setup

The bot posts as a GitHub App, not as a personal user.

1. Create a GitHub App under the target account/organization.
2. Permissions:
   - **Pull requests**: Read & write (to post reviews and comments)
   - **Contents**: Read (to clone/checkout)
   - **Metadata**: Read
3. Subscribe to `pull_request` events (`opened`, `synchronize`, `reopened`).
4. Generate and download a private key (`.pem`).
5. Install the app on the target repository and record the installation ID.
6. Store the PEM securely; never commit it.
7. At runtime, mint a JWT from the PEM and exchange it for a short-lived installation token.

The bot skips any PR whose `sender` matches the app's bot username, to avoid review loops.

---

## 7. Phased implementation plan

### Phase 1 — Local CLI with one agent (correctness)

Goal: validate the core loop quickly.

- `review.py` CLI that takes a PR URL.
- GitHub App auth + diff fetch.
- Workspace clone/checkout.
- Correctness sub-agent only.
- Coordinator that rewrites findings and posts the review.
- No risk tiers, no diff filtering beyond basic lockfile skip.

Success criteria:
- Bot can review a real PR and post comments as the app.
- Comments are one issue per comment.
- Each comment includes a suggested fix.

### Phase 2 — Add tests and safety agents + risk tiers

- Add tests and safety prompts.
- Implement trivial / lite / full risk tier logic.
- Run sub-agents concurrently.
- Diff filtering for generated/lockfile noise.
- Shared context file optimization.

Success criteria:
- Cost and latency scale down for small PRs.
- Safety agent catches hardcoded secrets and obvious injection paths.

### Phase 3 — Re-reviews and break glass

- On `pull_request.synchronize`, fetch prior bot comments.
- Feed prior findings and user replies into the coordinator.
- Drop fixed findings, re-emit unfixed ones.
- Implement `break glass` override.

### Phase 4 — Cloudflare / deos integration

- Move the bot into the `deos` orchestration graph as the `code_review` agent node.
- Use the GitHub capability gateway instead of direct token access.
- Use D1 for turn accounting and R2 for review artifacts.
- This phase should not start until the local bot is producing reliable reviews.

---

## 8. Open questions to validate through experimentation

1. **Prompt length vs. signal.** Does adding more "what NOT to flag" instructions reduce noise, or does it make the agent overly cautious?
2. **Coordinator necessity.** With only one sub-agent, is a coordinator still useful? With three agents, is it essential?
3. **Risk tier thresholds.** Are the line/file thresholds right for `deos`-sized PRs?
4. **Line precision.** How often does the agent emit a `code_location` that is not in the diff? Do we need to nudge it to use diff-relative lines?
5. **Suggested fix quality.** Are the suggested fixes concrete enough for authors to act on? Do we need to constrain the `replacement` field more tightly?
6. **Cost/latency trade-off.** What is the median cost and duration for a `deos` PR with the full three-agent setup?
7. **False positive rate.** On a sample of already-merged PRs, how many findings does the bot produce, and how many are real?
8. **Claim verification accuracy.** Can the bot reliably detect when a PR description claims something the code does not implement?

---

## 9. Files introduced by this proposal

```text
docs/review-bot-proposal.md
```

Implementation files — prompts, schemas, and Python modules — will be added in Phase 1.

---

## 10. Non-goals for the first version

- Multi-provider model routing.
- Circuit breakers / failback chains.
- Real-time JSONL streaming.
- Integration with Linear or the existing `deos` workflow graph.
- Architecture/style review beyond correctness impact.
- Automated application of suggested fixes.
