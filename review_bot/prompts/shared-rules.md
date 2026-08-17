## Shared rules for all review agents

### Inputs

- `shared-context.md` — PR title, body, head/base SHA, sender, changed files,
  linked issue references, validation results.
- `review-diff.diff` — the full unified diff of the PR.

Read both files first. Read other files in the repository only when you need
context to judge correctness (for example, a helper the diff calls, dependency
manifests for version checking, or architecture documents for lifecycle
context).

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
  it appears in the diff. `line_range`: line numbers in the **new** (right-side)
  file, pointing at lines that are present in the diff. `start` <= `end`.
- `suggested_fix.description`: how to fix it; `replacement`: concrete code when
  you know it, otherwise an empty string.
- `priority`: 0 = suggestion only, 1 = warning (potential issue),
  2 = critical (definite bug or production-safety risk).
- `confidence_score`: your honest 0–1 confidence the finding is real.

### Verdict

- `overall_correctness`: "patch is incorrect" if you emitted any finding, else
  "patch is correct".
- `overall_explanation`: one paragraph summarizing what you checked and found.
- `status`: "no_further_concerns" for this single-pass review.

### Output

Respond with **only** the JSON object matching the provided schema. No prose
before or after.
