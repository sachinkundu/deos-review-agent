# Discoverable review-agent evidence

This directory keeps the evidence for the registered-agent implementation. The
three proof levels are intentionally separate.

## Native harness isolation

- `harness-isolation-pi.json` exercises the installed Pi harness with zero, one,
  and two explicitly assigned Agent Skills packages.
- `harness-isolation-codex.json` exercises the installed Codex harness with the
  same cases.
- Both proofs require every assigned reference marker and reject markers from an
  ambient home skill or a pull-request-owned skill.

## Local proof against a real pull request

`local-real-pr-pi/` and `local-real-pr-codex/` contain no-post review runs against
real pull request #8 at its exact provider head SHA. Each run used a freshly
minted GitHub App installation token to fetch pull-request metadata and the real
provider diff, then retained its sibling `host-artifacts/` directory: run
manifest, agent catalog, raw attributed results, provider and review diffs,
shared context, filter record, and unposted payload.

The exact-head `source/` clones remain locally beside `host-artifacts/` during
proof but are ignored because they duplicate the repository and contain Git
metadata. This is local proof only: neither run posted to GitHub.

## Provider-originated and visual proof

The real GitHub App reviewed controlled pull request
[`#9`](https://github.com/sachinkundu/deos-review-agent/pull/9) at exact head
`222bc619927b31107d8a3d8b3711347b1b1646e4`. GitHub accepted review
`4960012428` as `CHANGES_REQUESTED` and accepted inline comment `3803231147` on
`provider-proof/insecure_shell_fixture.py`, line 8, side `RIGHT`. The structured
provider read-back is in `provider-originated/read-back.json`; the review run's
host artifacts are retained below it. The controlled proof PR was closed
without merge after capture.

Visual evidence:

- `provider-originated/github-app-configuration.png` — the installed GitHub App
  page and configuration entry point;
- `provider-originated/pr-review-state.png` — the draft proof PR, App-authored
  requested-changes review, diff hunk, and accepted comment; and
- `provider-originated/posted-inline-comment.png` — the App-authored comment
  visibly attached to changed line 8.
