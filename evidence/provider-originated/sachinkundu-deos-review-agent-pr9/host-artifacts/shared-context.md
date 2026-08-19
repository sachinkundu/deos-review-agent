# Shared context: PR 9 — Add controlled provider review fixture

## Pull request
- URL: https://github.com/sachinkundu/deos-review-agent/pull/9
- Repository: sachinkundu/deos-review-agent
- Sender: sachinkundu
- Head SHA: 222bc619927b31107d8a3d8b3711347b1b1646e4
- Base SHA: d34e1a304bc729d82671b2d7cd3e787805413899

## PR body
## Purpose

Controlled, deliberately unsafe fixture for provider-originated review-bot proof. This PR must not be merged.

The expected result is a GitHub App review with an inline comment on the changed `subprocess.run` line, accepted against this PR's exact head SHA.

## Validation boundary

- Real GitHub App installation token
- Real GitHub pull request metadata and provider diff
- Real registered-agent pipeline
- Real GitHub review POST and comment read-back

After screenshots and API read-back are retained in the implementation PR, this proof PR will be closed without merge.

## Linked issue references
- (none found)

## Changed files
- provider-proof/insecure_shell_fixture.py

## Validation results
- Bootstrap: no bootstrap script found

## Inputs for this review
- This file: `shared-context.md`
- Complete provider-originated PR diff: `provider-diff.diff` (safety, coordination, and line validation)
- Filtered agent-review diff: `review-diff.diff` (correctness, API-reality, and tests)
- Operator-only exclusion audit manifest: `diff-filter.json` (not assigned to review agents)
- The clean repository is available separately as `repository/`.
