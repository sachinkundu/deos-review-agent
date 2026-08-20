## 1. Registry contract and built-in packages

- [x] 1.1 Add typed agent, skill, symbolic-input, catalog, result-envelope, and run-manifest models plus strict manifest parsing.
- [x] 1.2 Discover trusted direct-child agent packages deterministically and fail closed on duplicate names, invalid cardinality, unsupported inputs, path escapes, unreadable files, and invalid Agent Skills packages.
- [x] 1.3 Compute deterministic package digests over all contained agent-package files and verify the package is unchanged before launch.
- [x] 1.4 Migrate correctness, API-reality, tests, safety, and coordinator prompts into content-equivalent built-in agent packages with validated manifests and coordinator policies.

## 2. Workspace and resource isolation

- [x] 2.1 Split each pull-request workspace into an exact-head `source/` checkout and sibling `host-artifacts/` directory, then migrate all host-generated artifacts outside the source tree.
- [x] 2.2 Add symbolic resource resolution and per-agent invocation capsules that expose the clean source plus only assigned host artifacts.
- [x] 2.3 Write deterministic run manifest, agent catalog, and identity-bearing raw result artifacts without secrets or arbitrary skill-resource contents.

## 3. Native harness adapters

- [x] 3.1 Detect supported Pi and Codex commands before reviewer execution and reject unsupported harness commands.
- [x] 3.2 Add a Pi adapter that disables ambient skill discovery and passes only the owning agent's skills through Pi's native explicit skill arguments.
- [x] 3.3 Add a Codex adapter that uses clean temporary `HOME` and `CODEX_HOME`, forwards only minimum authentication material, stages only the owning agent's skills in a trusted isolated location, disables ambient rules/configuration, and cleans up after capture.
- [x] 3.4 Prove prompt-only, one-skill, and multiple-skill native loading plus exclusion of ambient, pull-request, and unassigned resources with real installed Pi and Codex harnesses.

## 4. Registry-driven review pipeline

- [x] 4.1 Replace the fixed reviewer roster with trusted registry discovery, select-all reviewer policy, singleton coordinator selection, and bounded concurrent execution in registry order.
- [x] 4.2 Carry agent name, contract version, and package digest through results; preserve partial failures and stop before coordination when every reviewer fails.
- [x] 4.3 Generate roster-agnostic coordinator inputs from the agent catalog, coordination policies, attributed results, shared context, and provider diff, rejecting any catalog/result identity mismatch.
- [x] 4.4 Preserve the Phase 2 review schema, complete-provider-diff line validation, exact head-SHA freshness check, GitHub posting behavior, and built-in reviewer coverage.

## 5. Verification and delivery evidence

- [x] 5.1 Add deterministic tests for registry/schema validation, digest changes, package containment, Agent Skills validation, workspace/resource isolation, selection, ordering, concurrency, identity checks, and failure handling.
- [x] 5.2 Run formatting, type checking, the complete deterministic test suite, strict OpenSpec validation, and diff hygiene checks.
- [x] 5.3 Run both real harness adapters locally against a real pull request without posting, retaining the source/artifact split, run manifest, catalog, raw results, effective skill evidence, and unposted payload as local proof.
- [x] 5.4 If posting-path regression evidence is needed, run the real GitHub App on a controlled pull request, read back accepted line comments, and capture GitHub App, PR review, and posted-comment screenshots as provider-originated and visual proof.
