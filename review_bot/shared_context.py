"""Assemble the shared context document for review agents.

The shared context is written to a file in the workspace so agent prompts can
reference it instead of embedding large context in every prompt (design
decision: shared context file).
"""

from __future__ import annotations

from pathlib import Path

from .github import PRInfo, extract_linked_issue_references
from .workspace import BootstrapResult

SHARED_CONTEXT_NAME = "shared-context.md"
DIFF_NAME = "review-diff.diff"


def write_shared_context(
    workdir: Path,
    pr: PRInfo,
    diff_text: str,
    bootstrap: BootstrapResult | None = None,
    linked_references: list[str] | None = None,
) -> Path:
    """Write ``shared-context.md`` and ``review-diff.diff`` into the workspace."""
    linked = (
        linked_references
        if linked_references is not None
        else extract_linked_issue_references(pr.title, pr.body)
    )

    lines: list[str] = []
    lines.append(f"# Shared context: PR {pr.number} — {pr.title}")
    lines.append("")
    lines.append("## Pull request")
    lines.append(f"- URL: https://github.com/{pr.owner}/{pr.repo}/pull/{pr.number}")
    lines.append(f"- Repository: {pr.owner}/{pr.repo}")
    lines.append(f"- Sender: {pr.sender_login}")
    lines.append(f"- Head SHA: {pr.head_sha}")
    lines.append(f"- Base SHA: {pr.base_sha}")
    lines.append("")
    lines.append("## PR body")
    lines.append(pr.body.strip() if pr.body.strip() else "(empty)")
    lines.append("")

    lines.append("## Linked issue references")
    if linked:
        lines.extend(f"- {ref}" for ref in linked)
    else:
        lines.append("- (none found)")
    lines.append("")

    lines.append("## Changed files")
    if pr.changed_files:
        lines.extend(f"- {f}" for f in pr.changed_files)
    else:
        lines.append("- (none reported)")
    lines.append("")

    lines.append("## Validation results")
    if bootstrap is not None:
        lines.append(f"- Bootstrap: {bootstrap.summary}")
    else:
        lines.append("- (no validation commands run)")
    lines.append("")

    lines.append("## Inputs for this review")
    lines.append(f"- This file: `{SHARED_CONTEXT_NAME}`")
    lines.append(f"- Full PR diff (unified): `{DIFF_NAME}`")
    lines.append("- The repository is checked out at the PR head commit in this directory.")
    lines.append("")

    context_path = workdir / SHARED_CONTEXT_NAME
    context_path.write_text("\n".join(lines), encoding="utf-8")
    (workdir / DIFF_NAME).write_text(diff_text, encoding="utf-8")
    return context_path
