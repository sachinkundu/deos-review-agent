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

Read other files in the repository only when you need context to judge your
assigned review scope (for example, a helper the diff calls, dependency manifests
for version checking, tests covering changed behavior, or architecture documents
for lifecycle context).

### Architecture context

Architecture documents (e.g. `current-architecture.md`, `docs/`,
`openspec/changes/*/design.md`) may be present in the workspace. Read them
when they help you verify whether the diff honors the intended lifecycle,
boundary, or state-machine contract. Do not drift into architecture opinions
that do not translate into a concrete bug.

### Rules for every finding

- Exactly one issue per finding.
- `title`: at most 80 characters, states the problem.
- `body`: evidence (what the code does), the problem, and a **concrete
  failure scenario** (specific input/state that produces the wrong behavior).
- `code_location.absolute_file_path`: the repository-relative path exactly as
  it appears in the assigned diff. `line_range`: line numbers in the **new**
  (right-side) file, pointing at lines that are present in the complete provider
  diff. `start` <= `end`.
- `suggested_fix.description`: how to fix it; `replacement`: concrete code when
  you know it, otherwise an empty string.
- `priority`: 0 = suggestion only, 1 = warning (potential issue),
  2 = critical (definite bug or production-safety risk).
- `confidence_score`: your honest 0–1 confidence the finding is real.

### Verdict

- `overall_correctness`: "patch is incorrect" if you emitted any finding, else
  "patch is correct".
- `overall_explanation`: one paragraph summarizing what you checked and found.
- `overall_confidence_score`: your honest 0–1 confidence in the overall verdict.
- `status`: "no_further_concerns" for this single-pass review.

### Output

Respond with **only** the JSON object matching the provided schema. The
top-level object must contain exactly these fields: `findings`,
`overall_correctness`, `overall_explanation`, `overall_confidence_score`, and
`status`. No prose before or after.
