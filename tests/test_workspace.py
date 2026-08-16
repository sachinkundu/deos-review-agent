"""Deterministic tests for workspace clone, checkout, bootstrap, and cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from review_bot.workspace import (
    PRWorkspace,
    WorkspaceError,
    workspace_dir_for,
)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    """Create a local git repository with a couple of commits."""
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git(["init", "--quiet"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "--quiet", "-m", "initial"], repo)
    _git(["checkout", "--quiet", "-b", "feature"], repo)
    (repo / "main.py").write_text("print('hello world')\n", encoding="utf-8")
    _git(["commit", "--quiet", "-am", "feature commit"], repo)
    return repo


@pytest.fixture
def local_clone_url(local_repo: Path) -> str:
    return str(local_repo)


@pytest.fixture
def head_sha(local_repo: Path) -> str:
    result = _git(["rev-parse", "feature"], local_repo)
    return result.stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path) -> PRWorkspace:
    return PRWorkspace(tmp_path, "owner", "repo", 7)


def test_workspace_dir_for():
    assert workspace_dir_for(Path("/tmp"), "my-org", "repo-name", 42) == Path(
        "/tmp/my-org-repo-name-pr42"
    )


def test_setup_clones_and_checks_out(local_clone_url, head_sha, workspace):
    workdir = workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    assert workdir.exists()
    assert workdir.name == "owner-repo-pr7"
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == head_sha
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "feature"


def test_setup_fails_on_bad_sha(local_clone_url, workspace):
    with pytest.raises(WorkspaceError, match="head SHA"):
        workspace.setup(local_clone_url, "deadbeef", "feature", token="fake-token")


def test_setup_removes_stale_workspace(local_clone_url, head_sha, workspace):
    workspace.workdir.mkdir(parents=True)
    (workspace.workdir / "stale.txt").write_text("old")
    workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    assert not (workspace.workdir / "stale.txt").exists()
    assert (workspace.workdir / "main.py").exists()


def test_run_bootstrap_success(local_clone_url, head_sha, workspace):
    workdir = workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    script = workdir / ".review-bot"
    script.mkdir()
    (script / "bootstrap.sh").write_text(
        "#!/bin/bash\necho 'ready' > ready.txt\n", encoding="utf-8"
    )
    result = workspace.run_bootstrap(workdir)
    assert result.ran
    assert result.ok
    assert (workdir / "ready.txt").exists()


def test_run_bootstrap_failure(local_clone_url, head_sha, workspace):
    workdir = workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    script = workdir / ".review-bot"
    script.mkdir()
    (script / "bootstrap.sh").write_text("#!/bin/bash\necho 'nope' && exit 1\n", encoding="utf-8")
    result = workspace.run_bootstrap(workdir)
    assert result.ran
    assert not result.ok
    assert result.exit_code == 1
    assert "nope" in result.output_tail


def test_run_bootstrap_missing_is_noop(local_clone_url, head_sha, workspace):
    workdir = workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    result = workspace.run_bootstrap(workdir)
    assert not result.ran
    assert result.ok


def test_remove_cleans_workspace(local_clone_url, head_sha, workspace):
    workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    assert workspace.workdir.exists()
    workspace.remove()
    assert not workspace.workdir.exists()
