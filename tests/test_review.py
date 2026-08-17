"""Deterministic tests for the review CLI wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from review_bot.github import Credentials, GitHubAppClient, PRInfo
from review_bot.review import _load_prompt, build_review_body, run_review
from review_bot.workspace import PRWorkspace
from tests.conftest import FakeAgentRunner, make_finding, make_review


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path: Path):
    key = tmp_path / "app.pem"
    key.write_text("fake-key-not-used-because-client-is-fake")
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "456")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", str(key))
    monkeypatch.setenv("GITHUB_APP_BOT_USERNAME", "review-bot[bot]")


def test_load_prompt_includes_shared_rules():
    text = _load_prompt("correctness.md")
    assert "Shared rules for all review agents" in text
    assert "Exactly one issue per finding" in text
    assert "Correctness review agent" in text


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


class FakeGitHubClient(GitHubAppClient):
    def __init__(self, creds: Credentials, pr: PRInfo, diff: str, posted: list):
        self._creds = creds
        self.pr = pr
        self.diff = diff
        self.posted = posted
        self._token = "install-token"

    def mint_app_jwt(self) -> str:
        return "jwt"

    def mint_installation_token(self, repository: str | None = None) -> str:
        return self._token

    def fetch_pr(self, owner: str, repo: str, number: int, token: str | None = None) -> PRInfo:
        return self.pr

    def fetch_pr_diff(self, owner: str, repo: str, number: int, token: str | None = None) -> str:
        return self.diff

    def post_review(self, owner, repo, number, commit_id, event, body, comments, token=None):
        self.posted.append(
            {"event": event, "body": body, "comments": comments, "commit_id": commit_id}
        )
        return {"id": 99, "state": event}


class FakeWorkspace(PRWorkspace):
    def __init__(
        self, root: Path, owner: str, repo: str, number: int, bootstrap_timeout: int = 600
    ):
        super().__init__(root, owner, repo, number, bootstrap_timeout=bootstrap_timeout)
        self.removed = False
        self.bootstrapped = False

    def setup(self, clone_url: str, head_sha: str, branch: str, token: str) -> Path:
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.workdir / SHARED_CONTEXT_NAME).write_text("context")
        (self.workdir / DIFF_NAME).write_text("diff")
        return self.workdir

    def run_bootstrap(self, workdir: Path, extra_env=None):
        self.bootstrapped = True
        from review_bot.workspace import BootstrapResult

        return BootstrapResult(ran=False, ok=True)

    def remove(self) -> None:
        self.removed = True


SHARED_CONTEXT_NAME = "shared-context.md"
DIFF_NAME = "review-diff.diff"


def _make_client_factory(pr: PRInfo, diff: str, posted: list):
    def factory(creds: Credentials) -> GitHubAppClient:
        return FakeGitHubClient(creds, pr, diff, posted)

    return factory


def _make_runner_factory(final: dict, api_reality: dict | None = None):
    def factory(**kwargs) -> FakeAgentRunner:
        results: dict[str, object] = {
            "correctness": final,
            "api-reality": api_reality if api_reality is not None else final,
            "coordinator": final,
        }
        return FakeAgentRunner(results)

    return factory


def test_build_review_body_with_unattached_finding():
    review = make_review(findings=[make_finding(priority=1)])
    unattachable = [(make_finding(priority=1), "line not in diff")]
    body = build_review_body(review, [], unattachable, 1)
    assert "not be attached" in body
    assert "line not in diff" in body


def test_build_review_body_pass_note():
    review = make_review(findings=[], overall_correctness="patch is correct")
    body = build_review_body(review, [], [], 0)
    assert "No correctness" in body


def test_build_review_body_includes_agent_failures():
    from review_bot.agents.runner import AgentResult

    review = make_review(findings=[])
    failures = [AgentResult(name="api-reality", ok=False, error="timeout")]
    body = build_review_body(review, failures, [], 0)
    assert "api-reality" in body
    assert "timeout" in body


def test_run_review_happy_path(tmp_path: Path, sample_diff):
    pr = _make_pr()
    posted = []
    finding = make_finding(path="src/widget/paginate.py", start=9, end=9, priority=1)
    final = make_review(findings=[finding], overall_correctness="patch is incorrect")
    exit_code = run_review(
        ["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)],
        client_factory=_make_client_factory(pr, sample_diff, posted),
        runner_factory=_make_runner_factory(final),
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
    )
    assert exit_code == 0
    assert len(posted) == 1
    assert posted[0]["event"] == "COMMENT"
    assert posted[0]["comments"][0]["path"] == "src/widget/paginate.py"
    assert posted[0]["comments"][0]["line"] == 9


def test_run_review_bot_skip(tmp_path: Path):
    pr = _make_pr(sender_login="review-bot[bot]")
    posted = []
    exit_code = run_review(
        ["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)],
        client_factory=_make_client_factory(pr, "", posted),
        runner_factory=_make_runner_factory(make_review(findings=[])),
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
    )
    assert exit_code == 0
    assert posted == []


def test_run_review_dry_run_does_not_post(tmp_path: Path, sample_diff):
    pr = _make_pr()
    posted = []
    finding = make_finding(path="src/widget/paginate.py", start=9, end=9, priority=2)
    final = make_review(findings=[finding], overall_correctness="patch is incorrect")
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--dry-run",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(pr, sample_diff, posted),
        runner_factory=_make_runner_factory(final),
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
    )
    assert exit_code == 0
    assert posted == []


def test_run_review_agent_failure_surfaces_in_summary(tmp_path: Path, sample_diff):
    pr = _make_pr()
    posted = []
    finding = make_finding(path="src/widget/paginate.py", start=9, end=9, priority=1)
    final = make_review(findings=[finding], overall_correctness="patch is incorrect")

    def runner_factory(**kwargs):
        return FakeAgentRunner(
            {"correctness": final, "api-reality": Exception("boom"), "coordinator": final}
        )

    exit_code = run_review(
        ["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)],
        client_factory=_make_client_factory(pr, sample_diff, posted),
        runner_factory=runner_factory,
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
    )
    assert exit_code == 0
    assert "boom" in posted[0]["body"]


def test_run_review_stale_head_fails_without_post(tmp_path: Path, sample_diff):
    pr = _make_pr(head_sha="abc123")
    posted = []

    class StaleClient(FakeGitHubClient):
        def __init__(self, creds, pr, diff, posted):
            super().__init__(creds, pr, diff, posted)
            self.fetch_count = 0

        def fetch_pr(self, owner, repo, number, token=None):
            self.fetch_count += 1
            if self.fetch_count == 1:
                return self.pr
            return _make_pr(head_sha="newsha")

    def client_factory(creds: Credentials):
        return StaleClient(creds, pr, sample_diff, posted)

    exit_code = run_review(
        ["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)],
        client_factory=client_factory,
        runner_factory=_make_runner_factory(make_review(findings=[])),
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
    )
    assert exit_code == 5
    assert posted == []
