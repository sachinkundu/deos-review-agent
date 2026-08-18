"""Deterministic tests for shared context assembly."""

from __future__ import annotations

from pathlib import Path

from review_bot.github import PRInfo
from review_bot.shared_context import SHARED_CONTEXT_NAME, write_shared_context
from review_bot.workspace import BootstrapResult


def _make_pr(**overrides) -> PRInfo:
    defaults = {
        "number": 7,
        "title": "Fix pagination",
        "body": "Closes #42",
        "head_sha": "abc123",
        "base_sha": "def456",
        "head_ref": "fix-page",
        "sender_login": "human",
        "head_repo_full_name": "owner/repo",
        "head_repo_clone_url": "https://github.com/owner/repo.git",
        "owner": "owner",
        "repo": "repo",
        "url": "https://api.github.com/repos/owner/repo/pulls/7",
        "changed_files": ["src/paginate.py"],
    }
    defaults.update(overrides)
    return PRInfo(**defaults)


def test_write_shared_context(tmp_path: Path):
    pr = _make_pr()
    bootstrap = BootstrapResult(ran=True, ok=True)
    context_path = write_shared_context(tmp_path, pr, bootstrap)
    assert context_path == tmp_path / SHARED_CONTEXT_NAME
    text = context_path.read_text(encoding="utf-8")
    assert "Fix pagination" in text
    assert "Closes #42" in text
    assert "abc123" in text
    assert "src/paginate.py" in text
    assert "bootstrap succeeded" in text
    assert "provider-diff.diff" in text
    assert "review-diff.diff" in text
    assert "diff-filter.json" in text
    assert not (tmp_path / "review-diff.diff").exists()


def test_linked_issue_references_included(tmp_path: Path):
    pr = _make_pr(body="Fixes #123, resolves SAC-87")
    write_shared_context(tmp_path, pr)
    text = (tmp_path / SHARED_CONTEXT_NAME).read_text(encoding="utf-8")
    assert "#123" in text
    assert "SAC-87" in text


def test_bootstrap_failure_recorded(tmp_path: Path):
    pr = _make_pr()
    bootstrap = BootstrapResult(ran=True, ok=False, exit_code=2, output_tail="missing dep")
    write_shared_context(tmp_path, pr, bootstrap)
    text = (tmp_path / SHARED_CONTEXT_NAME).read_text(encoding="utf-8")
    assert "bootstrap failed" in text
    assert "missing dep" in text


def test_no_bootstrap_recorded(tmp_path: Path):
    pr = _make_pr()
    write_shared_context(tmp_path, pr)
    text = (tmp_path / SHARED_CONTEXT_NAME).read_text(encoding="utf-8")
    assert "no validation commands run" in text
