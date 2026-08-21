## Shared rules for all review agents

### Inputs

- Your invocation explicitly assigns every input file for this role. Read every
  assigned file before reviewing.
- `shared-context.md` contains PR title, body, head/base SHA, sender, the complete
  provider-reported changed-file list, linked issue references, validation results,
  and descriptions of the review artifacts.
- When assigned, `review-diff.diff` is a deterministic filtered view containing
  complete retained file patches. It can be empty.
- When assigned, `provider-diff.diff` is the complete provider-originated unified
  diff and is the source of truth for comment locations.
- `diff-filter.json` is an operator audit artifact and is not an agent input.

Read other files in the `repository/` directory only when you need context to
judge your assigned review scope. Host-generated artifacts are available only
through the explicitly assigned `inputs/` paths.

### Architecture context

Architecture documents may be present in the repository. Read them when they
help verify whether the diff honors an intended lifecycle, boundary, or
state-machine contract. Do not drift into opinions without a concrete bug.

### Rules for every finding

- Exactly one issue per finding.
- `title`: at most 80 characters, states the problem.
- `body`: evidence, the problem, and a concrete failure scenario.
- `code_location.absolute_file_path`: the repository-relative path exactly as
  it appears in the assigned diff. Use new-file right-side line numbers present
  in the complete provider diff, with `start <= end`.
- `suggested_fix.description`: how to fix it; `replacement`: concrete code
  when known, otherwise an empty string.
- `priority`: 0 = suggestion, 1 = warning, 2 = critical.
- `confidence_score`: honest confidence from 0 through 1.

### Verdict

- `overall_correctness`: "patch is incorrect" if you emitted any finding, else
  "patch is correct".
- `overall_explanation`: one paragraph summarizing what you checked and found.
- `overall_confidence_score`: honest confidence from 0 through 1.
- `status`: "no_further_concerns" for this single-pass review.

### Output

Respond with only the JSON object matching the provided schema. The top-level
object must contain exactly `findings`, `overall_correctness`,
`overall_explanation`, `overall_confidence_score`, and `status`.
Coordinator findings may additionally preserve the trusted `source_agent`
attribution supplied by `raw-findings.json`.
