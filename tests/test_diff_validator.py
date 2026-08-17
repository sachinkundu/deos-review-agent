"""Deterministic tests for unified-diff parsing and location validation."""

from __future__ import annotations

from review_bot.diff_validator import FileDiff, parse_unified_diff, validate_findings_locations
from tests.conftest import SAMPLE_DIFF, make_finding


def test_parses_added_and_context_lines(sample_diff):
    files = parse_unified_diff(sample_diff)
    py = files["src/widget/paginate.py"]
    # Right-side lines of the first hunk: new file lines 8..17
    # (context lines 8,13; added lines 9,10,11,12,14,15,16,17)
    assert py.added_lines == {9, 10, 11, 12, 14, 15, 16, 17}
    assert py.right_lines == {8, 9, 10, 11, 12, 13, 14, 15, 16, 17}
    assert py.old_path is None

    readme = files["README.md"]
    assert readme.added_lines == {2, 3}
    assert readme.right_lines == {1, 2, 3, 4}


def test_removed_lines_are_not_right_side():
    diff = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -1,4 +1,3 @@\n"
        " keep one\n"
        "-removed left only\n"
        "-also removed\n"
        "+added line\n"
        " keep two\n"
    )
    files = parse_unified_diff(diff)
    a = files["a.py"]
    # right side: line 1 (context), 2 (added), 3 (context)
    assert a.right_lines == {1, 2, 3}
    assert a.added_lines == {2}


def test_multiple_hunks_continue_line_numbers():
    diff = (
        "diff --git a/m.py b/m.py\n"
        "--- a/m.py\n"
        "+++ b/m.py\n"
        "@@ -1,3 +1,4 @@\n"
        " one\n"
        "+inserted near top\n"
        " two\n"
        " three\n"
        "@@ -10,2 +11,3 @@\n"
        " ten\n"
        "+second hunk addition\n"
        " eleven\n"
    )
    files = parse_unified_diff(diff)
    m = files["m.py"]
    assert m.added_lines == {2, 12}
    assert m.right_lines == {1, 2, 3, 4, 11, 12, 13}


def test_new_file():
    diff = (
        "diff --git a/new.py b/new.py\n"
        "new file mode 100644\n"
        "index 0000000..1234567\n"
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+first\n"
        "+second\n"
        "+third\n"
    )
    files = parse_unified_diff(diff)
    n = files["new.py"]
    assert n.is_new
    assert not n.is_deleted
    assert n.right_lines == {1, 2, 3}
    assert n.added_lines == {1, 2, 3}


def test_deleted_file_is_not_attachable():
    diff = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "index 1234567..0000000\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-bye\n"
        "-bye again\n"
    )
    files = parse_unified_diff(diff)
    # The file maps under its (absent) new path; ensure no attachable lines.
    assert all(not f.covers_range(1, 1) for f in files.values())


def test_rename_rekeys_to_new_path():
    diff = (
        "diff --git a/old/path.py b/new/path.py\n"
        "similarity index 90%\n"
        "rename from old/path.py\n"
        "rename to new/path.py\n"
        "--- a/old/path.py\n"
        "+++ b/new/path.py\n"
        "@@ -1,2 +1,3 @@\n"
        " same\n"
        "+changed\n"
        " same too\n"
    )
    files = parse_unified_diff(diff)
    assert "new/path.py" in files
    assert "old/path.py" not in files
    renamed = files["new/path.py"]
    assert renamed.old_path == "old/path.py"
    assert renamed.added_lines == {2}


def test_binary_file_has_no_lines():
    diff = (
        "diff --git a/img.png b/img.png\n"
        "index 123..456 100644\n"
        "Binary files a/img.png and b/img.png differ\n"
    )
    files = parse_unified_diff(diff)
    img = files["img.png"]
    assert img.is_binary
    assert img.right_lines == set()
    assert not img.covers_range(1, 1)


def test_no_newline_marker_does_not_shift_lines():
    diff = (
        "diff --git a/n.py b/n.py\n"
        "--- a/n.py\n"
        "+++ b/n.py\n"
        "@@ -1,2 +1,2 @@\n"
        " one\n"
        "-two with newline\n"
        "+two without newline\n"
        "\\ No newline at end of file\n"
    )
    files = parse_unified_diff(diff)
    n = files["n.py"]
    assert n.right_lines == {1, 2}
    assert n.added_lines == {2}


def test_hunk_without_counts_defaults_to_one():
    diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    files = parse_unified_diff(diff)
    assert files["x.py"].right_lines == {1}


def test_validate_locations_attachable_and_unattachable(sample_diff):
    files = parse_unified_diff(sample_diff)
    findings = [
        make_finding(
            title="added line", path="src/widget/paginate.py", start=9, end=9
        ),  # attachable
        make_finding(
            title="context line", path="src/widget/paginate.py", start=8, end=8
        ),  # attachable (context)
        make_finding(
            title="range", path="src/widget/paginate.py", start=14, end=17
        ),  # attachable range
        make_finding(title="unknown file", path="src/nope.py", start=1, end=1),  # unattachable
        make_finding(
            title="out of range", path="src/widget/paginate.py", start=500, end=500
        ),  # unattachable
        make_finding(title="readme", path="README.md", start=2, end=3),  # attachable
    ]
    outcome = validate_findings_locations(findings, files)
    assert [f["title"] for f, _ in outcome.attachable] == [
        "added line",
        "context line",
        "range",
        "readme",
    ]
    assert [i for _, i in outcome.attachable] == [0, 1, 2, 5]
    assert [f["title"] for f, _ in outcome.unattachable] == ["unknown file", "out of range"]
    assert "not in the PR diff" in outcome.unattachable[0][1]
    assert "not on the right side" in outcome.unattachable[1][1]


def test_range_crossing_non_diff_line_is_unattachable():
    diff = (
        "diff --git a/c.py b/c.py\n--- a/c.py\n+++ b/c.py\n@@ -1,3 +1,4 @@\n a\n+b\n-removed\n c\n"
    )
    files = parse_unified_diff(diff)
    # right side is lines 1,2,3; a range of 2..4 crosses the missing line 4
    outcome = validate_findings_locations([make_finding(path="c.py", start=2, end=4)], files)
    assert outcome.attachable == []
    assert (
        outcome.unattachable[0][1] == "line(s) [4] of `c.py` are not on the right side of the diff"
    )


def test_deleted_only_line_is_unattachable():
    # First diff verifies a removed-only hunk leaves a right line unattachable.
    diff = "diff --git a/d.py b/d.py\n--- a/d.py\n+++ b/d.py\n@@ -1,2 +1,2 @@\n kept\n-gone\n+new\n"
    parse_unified_diff(diff)
    # Then verify a removed-only file has no right line 2 in a removed-only hunk:
    # points at right line 2 while the diff only has line 3 as context...
    # instead verify the removed-only file has no right line 2 in a removed-only hunk:
    diff2 = "diff --git a/e.py b/e.py\n--- a/e.py\n+++ b/e.py\n@@ -1,2 +1,1 @@\n kept\n-gone\n"
    files2 = parse_unified_diff(diff2)
    outcome = validate_findings_locations([make_finding(path="e.py", start=2, end=2)], files2)
    assert outcome.attachable == []
    assert "not on the right side" in outcome.unattachable[0][1]


def test_invalid_range_end_before_start_unattachable():
    files = parse_unified_diff(SAMPLE_DIFF)
    outcome = validate_findings_locations([make_finding(start=9, end=8)], files)
    assert outcome.attachable == []
    assert "invalid line range" in outcome.unattachable[0][1]


def test_file_diff_covers_range_requires_every_line():
    f = FileDiff(path="f.py", right_lines={1, 2, 4})
    assert f.covers_range(1, 2)
    assert not f.covers_range(2, 4)
