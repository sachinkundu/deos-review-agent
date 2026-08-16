"""Parse PR diffs and validate finding locations against right-side diff lines.

GitHub rejects review comments whose ``(path, line, side=RIGHT)`` does not map
to a line that is part of the PR diff, and one bad line rejects the entire
review payload. So every finding location is validated here before posting.

Attachable lines are the right-hand (new file) lines present in the diff:
added lines (``+``) and context lines (`` ``) inside hunks. Removed-only lines
(``-``) and lines outside the diff are not attachable; findings pointing there
are moved to the review summary body instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_DIFF_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_RENAME_FROM_RE = re.compile(r"^rename from (.+)$")
_RENAME_TO_RE = re.compile(r"^rename to (.+)$")
_MODE_RE = re.compile(
    r"^(new file|deleted file|old mode|new mode|similarity index|"
    r"deleted file mode|new file mode|copy from|copy to) .*"
)


@dataclass
class FileDiff:
    """Parsed diff for one file, with right-side (new file) line numbers."""

    path: str
    old_path: str | None = None
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False
    right_lines: set[int] = field(default_factory=set)
    added_lines: set[int] = field(default_factory=set)

    def covers_range(self, start: int, end: int) -> bool:
        """True when every line in [start, end] is a right-side diff line."""
        if self.is_binary or self.is_deleted:
            return False
        return all(line in self.right_lines for line in range(start, end + 1))


def _clean_quoted_path(path: str) -> str:
    """Strip git's C-style quoting around paths that need it."""
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        try:
            return bytes(path[1:-1], "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            return path[1:-1]
    return path


def parse_unified_diff(diff_text: str) -> dict[str, FileDiff]:
    """Parse a raw unified diff (as GitHub returns for a PR) into per-file data.

    Handles renames, new/deleted files, binary files, and multiple hunks.
    Returns a map keyed by the file's new (right-side) path.
    """
    files: dict[str, FileDiff] = {}
    current: FileDiff | None = None
    new_line = 0

    for raw in diff_text.splitlines():
        if m := _GIT_DIFF_RE.match(raw):
            old = _clean_quoted_path(m.group(1))
            new = _clean_quoted_path(m.group(2))
            if new == "/dev/null":
                continue  # deletion handled via the deleted-file marker below
            current = FileDiff(path=new, old_path=old if old != new else None)
            files[new] = current
            new_line = 0
            continue

        if current is None:
            continue

        if m := _RENAME_FROM_RE.match(raw):
            current.old_path = _clean_quoted_path(m.group(1))
            continue
        if m := _RENAME_TO_RE.match(raw):
            # Re-key the file under its new path.
            new_path = _clean_quoted_path(m.group(1))
            files.pop(current.path, None)
            current.path = new_path
            files[new_path] = current
            continue
        if raw.startswith("new file"):
            current.is_new = True
            continue
        if raw.startswith("deleted file"):
            current.is_deleted = True
            continue
        if raw.startswith("Binary files ") and raw.endswith(" differ"):
            current.is_binary = True
            continue
        if _MODE_RE.match(raw) or raw.startswith("--- ") or raw.startswith("+++ "):
            continue

        if m := _HUNK_RE.match(raw):
            new_line = int(m.group(3))
            continue

        if current.is_binary:
            continue

        if raw.startswith("+"):
            current.right_lines.add(new_line)
            current.added_lines.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            pass  # left-side only
        elif raw.startswith("\\"):
            pass  # "\ No newline at end of file"
        elif raw.startswith(" ") or raw == "":
            current.right_lines.add(new_line)
            new_line += 1

    return files


@dataclass
class ValidationOutcome:
    """Result of validating every finding location against the diff.

    ``attachable`` items are ``(finding, original_index)`` tuples in original
    order; ``unattachable`` items are ``(finding, reason)`` tuples.
    """

    attachable: list[tuple[dict, int]]
    unattachable: list[tuple[dict, str]]


def validate_findings_locations(
    findings: list[dict], files: dict[str, FileDiff]
) -> ValidationOutcome:
    """Split findings into attachable inline comments and summary-body entries.

    A finding is attachable when its path is in the diff and every line of
    ``line_range`` is a right-side diff line. Otherwise it is unattachable
    (removed-only line, deleted file, unknown path, or out of range) and is
    returned with a reason for the review summary.
    """
    attachable: list[tuple[dict, int]] = []
    unattachable: list[tuple[dict, str]] = []

    for index, finding in enumerate(findings):
        location = finding.get("code_location", {})
        path = location.get("absolute_file_path", "")
        line_range = location.get("line_range", {})
        start, end = line_range.get("start"), line_range.get("end")

        file_diff = files.get(path)
        if file_diff is None:
            unattachable.append((finding, f"file `{path}` is not in the PR diff"))
            continue
        if not isinstance(start, int) or not isinstance(end, int) or end < start:
            unattachable.append((finding, f"invalid line range {start}-{end} for `{path}`"))
            continue
        if not file_diff.covers_range(start, end):
            missing = [line for line in range(start, end + 1) if line not in file_diff.right_lines]
            unattachable.append(
                (finding, f"line(s) {missing} of `{path}` are not on the right side of the diff")
            )
            continue
        attachable.append((finding, index))

    return ValidationOutcome(attachable=attachable, unattachable=unattachable)
