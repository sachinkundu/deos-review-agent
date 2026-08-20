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


def test_workspace_normalizes_relative_root(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    workspace = PRWorkspace(Path("relative-root"), "owner", "repo", 7)
    assert workspace.root == tmp_path / "relative-root"
    assert workspace.source_dir.is_absolute()


def test_setup_clones_and_checks_out(local_clone_url, head_sha, workspace):
    workdir = workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    assert workdir.exists()
    assert workdir == workspace.source_dir
    assert workdir.name == "source"
    assert workspace.artifact_dir.is_dir()
    assert workspace.artifact_dir.parent == workspace.workdir
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
    assert (workspace.source_dir / "main.py").exists()


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


def test_run_bootstrap_sanitizes_env(local_clone_url, head_sha, workspace, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "/secret/key.pem")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("REVIEW_PR_URL", "https://example.com/pr/1")
    workdir = workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    script = workdir / ".review-bot"
    script.mkdir()
    (script / "bootstrap.sh").write_text(
        "#!/bin/bash\n"
        'echo "PRIVATE_KEY=$GITHUB_APP_PRIVATE_KEY"\n'
        'echo "OPENAI_API_KEY=$OPENAI_API_KEY"\n'
        'echo "PR_URL=$REVIEW_PR_URL"\n',
        encoding="utf-8",
    )
    result = workspace.run_bootstrap(workdir)
    assert result.ok
    assert "PRIVATE_KEY=" in result.output_tail
    assert "sk-secret" not in result.output_tail
    assert "PR_URL=https://example.com/pr/1" in result.output_tail


def test_setup_passes_auth_env_to_all_fetches(local_clone_url, head_sha, workspace):
    calls = []

    def _capture_git(args, cwd, env=None):
        calls.append((args, env))
        stdout = ""
        if args == ["rev-parse", "HEAD"]:
            stdout = head_sha
        return subprocess.CompletedProcess(args, returncode=0, stdout=stdout, stderr="")

    from review_bot import workspace as workspace_mod

    original_git = workspace_mod._git
    workspace_mod._git = _capture_git
    try:
        workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    finally:
        workspace_mod._git = original_git

    fetch_calls = [c for c in calls if c[0][:2] == ["fetch", "--quiet"]]
    assert len(fetch_calls) >= 1
    for _args, env in fetch_calls:
        assert env is not None
        assert env.get("GIT_ASKPASS")
        assert env.get("RB_GIT_TOKEN") == "fake-token"


def test_remove_cleans_workspace(local_clone_url, head_sha, workspace):
    workspace.setup(local_clone_url, head_sha, "feature", token="fake-token")
    assert workspace.workdir.exists()
    workspace.remove()
    assert not workspace.workdir.exists()


def test_remove_surfaces_filesystem_failure(workspace, monkeypatch):
    workspace.workdir.mkdir(parents=True)

    def fail_remove(path: Path) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr("review_bot.workspace.shutil.rmtree", fail_remove)
    with pytest.raises(OSError, match="permission denied"):
        workspace.remove()

    assert workspace.workdir.exists()
