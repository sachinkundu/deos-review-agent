"""Assemble the shared context document for review agents.

The shared context is written once so each role can reuse PR metadata while
receiving its explicitly assigned full or filtered diff artifact.
"""

from __future__ import annotations

from pathlib import Path

from .diff_filter import FILTER_MANIFEST_NAME, PROVIDER_DIFF_NAME, REVIEW_DIFF_NAME
from .github import PRInfo, extract_linked_issue_references
from .workspace import BootstrapResult

SHARED_CONTEXT_NAME = "shared-context.md"


def write_shared_context(
    artifact_dir: Path,
    pr: PRInfo,
    bootstrap: BootstrapResult | None = None,
    linked_references: list[str] | None = None,
) -> Path:
    """Write shared PR metadata and describe the separately built diff views."""
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
    lines.append(
        f"- Complete provider-originated PR diff: `{PROVIDER_DIFF_NAME}` "
        "(safety, coordination, and line validation)"
    )
    lines.append(
        f"- Filtered agent-review diff: `{REVIEW_DIFF_NAME}` (correctness, API-reality, and tests)"
    )
    lines.append(
        f"- Operator-only exclusion audit manifest: `{FILTER_MANIFEST_NAME}` "
        "(not assigned to review agents)"
    )
    lines.append("- The clean repository is available separately as `repository/`.")
    lines.append("")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    context_path = artifact_dir / SHARED_CONTEXT_NAME
    context_path.write_text("\n".join(lines), encoding="utf-8")
    return context_path
