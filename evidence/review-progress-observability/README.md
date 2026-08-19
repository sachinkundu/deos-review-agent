# Review progress observability verification

Verified on 2026-08-19 (Europe/Helsinki) with implementation commit
`7fcd883e27a75b4c336a314016c7ae83b6d6539d`.

## Claim boundaries

- **Deterministic local proof:** the complete repository test and static-analysis
  gates pass, including mode equivalence, atomic reads, sanitization,
  interruption, immediate reviewer settlement, and side-effect-free status.
- **Real-provider no-post proof:** the GitHub App minted a fresh installation
  token, fetched PR #14 metadata and diff, cloned and checked out its exact head,
  ran the real Pi reviewer/coordinator harness, rechecked the provider head, and
  retained the final payload. `--dry-run` skipped the review POST.
- **Provider-originated posting proof:** not claimed for this feature. GitHub
  reported zero reviews and zero comments on the proof PR after the run.
- **Visual proof:** `github-pr14-exact-head.jpg` shows the real draft fixture PR,
  one commit, branch identity, and short head `7d507cf` in GitHub's UI;
  `status-terminal.jpg` shows the provider-free retained-status command with all
  reviewers and the coordinator succeeded, posting skipped, and exit `0`;
  `github-app-installation.jpg` shows the signed-in GitHub Applications page
  with `deos-review-agent` installed. No private key, token, or other credential
  material is shown.

## Real run

Target: <https://github.com/sachinkundu/deos-review-agent/pull/14>

- Provider head: `7d507cf2c647069c0490553c3edca105bb2bac91`
- Run ID: `3daf0d4a96a449079f2e85b52ea6b7b3`
- Started: `2026-08-19T10:30:29.653Z`
- Finished: `2026-08-19T10:32:49.036Z`
- Exit code: `0`
- Mode: `dry-run`
- Harness: Pi `0.84.2`
- review-bot: `0.1.0`
- Python: `3.13.15` under `uv`
- OpenSpec CLI: `1.8.0`

Command (the ignored environment file was referenced in place; no credential
values were copied or printed):

```bash
REVIEW_ENV_FILE=/Users/sachin/code/deos-review/.env \
  rtk uv run review-bot \
  https://github.com/sachinkundu/deos-review-agent/pull/14 \
  --dry-run --keep-workspace --no-agent-session --progress json \
  --workspace-root /Users/sachin/review-bot-workspaces-progress-proof
```

Observed transitions:

- 42 independently parseable `review-progress-event/v1` stderr records with
  sequence numbers `1..42`;
- all four reviewer identities were queued before any reviewer started;
- completion became visible in order `safety`, `api-reality`, `tests`,
  `correctness` while `progress.json` retained registry order `correctness`,
  `api-reality`, `tests`, `safety`;
- during partial settlement, `overall` remained `reviewers/running`;
- the coordinator succeeded, schema/diff/head checks succeeded, payload
  retention succeeded, posting was skipped, and cleanup was skipped because the
  workspace was intentionally retained;
- `unposted-review.json.commit_id` matched the provider head exactly; and
- `review_url` remained `null`.

`event-checkpoints.jsonl` retains representative exact events, including the
out-of-order settlements and final no-post/retention states. `progress-final.json`
is the validated final snapshot.

## Status read-back

Both human and JSON status commands returned the retained v1 snapshot without
provider authentication, model work, posting, or mutation:

```bash
rtk uv run review-bot status \
  https://github.com/sachinkundu/deos-review-agent/pull/14 \
  --workspace-root /Users/sachin/review-bot-workspaces-progress-proof

rtk uv run review-bot status \
  https://github.com/sachinkundu/deos-review-agent/pull/14 \
  --workspace-root /Users/sachin/review-bot-workspaces-progress-proof --json
```

The file remained 1,837 bytes with identical timestamp and SHA-256 before and
after both reads:

```text
cc901155757cee0f46c5967834d38e20f45d2ca50a3a6daf4ae4cd837a7d121e
```

## Deterministic gates

```text
uv run pytest                                      210 passed
uv run ruff format --check review_bot tests        41 files formatted
uv run ruff check review_bot tests                 passed
uv run pyright review_bot tests                    0 errors
openspec validate review-progress-observability --strict  valid
git diff --check                                   passed
uv build                                           sdist and wheel built
wheel resource inspection                         progress schema present
```

The first live run exposed two truthfulness defects before evidence acceptance:
premature aggregate reviewer success and stale active elapsed time in human
status. Commit `7fcd883` fixed both, added regressions, and the clean run above
is the rerun after those fixes. Subsequent GitHub review feedback added coverage
for terminal event publication, interrupted queued reviewers, cleanup failures,
JSON-stream purity, negative timeouts, and interrupt cleanup ordering; the full
210-test gate above includes those regressions.
