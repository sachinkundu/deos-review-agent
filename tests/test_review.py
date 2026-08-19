"""Deterministic tests for the review CLI wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from review_bot.agents.registry import AgentRegistry, discover_agent_registry, load_agent_package
from review_bot.diff_filter import DiffFilterError
from review_bot.github import Credentials, GitHubAppClient, PRInfo
from review_bot.review import build_review_body, run_review
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
        self.source_dir.mkdir()
        self.artifact_dir.mkdir()
        (self.source_dir / "reviewed.py").write_text("value = 1\n")
        return self.source_dir

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
            "tests": final,
            "safety": final,
            "coordinator": final,
        }
        return FakeAgentRunner(results)

    return factory


def _fake_diff_artifact_writer(workdir: Path, diff_text: str):
    (workdir / "provider-diff.diff").write_text(diff_text)
    (workdir / "review-diff.diff").write_text(diff_text)
    (workdir / "diff-filter.json").write_text('{"version": 1, "exclusions": []}\n')


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
        diff_artifact_writer=_fake_diff_artifact_writer,
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
        diff_artifact_writer=_fake_diff_artifact_writer,
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
        diff_artifact_writer=_fake_diff_artifact_writer,
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
            {
                "correctness": final,
                "api-reality": Exception("boom"),
                "tests": final,
                "safety": final,
                "coordinator": final,
            }
        )

    exit_code = run_review(
        ["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)],
        client_factory=_make_client_factory(pr, sample_diff, posted),
        runner_factory=runner_factory,
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
        diff_artifact_writer=_fake_diff_artifact_writer,
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
        diff_artifact_writer=_fake_diff_artifact_writer,
    )
    assert exit_code == 5
    assert posted == []


def test_run_review_uses_registered_agent_inputs_even_when_filtered_diff_empty(
    tmp_path: Path, sample_diff
):
    pr = _make_pr()
    posted: list[dict] = []
    final = make_review(findings=[], overall_correctness="patch is correct")
    runner = FakeAgentRunner(
        {
            "correctness": final,
            "api-reality": final,
            "tests": final,
            "safety": final,
            "coordinator": final,
        }
    )

    def empty_writer(workdir: Path, diff_text: str):
        _fake_diff_artifact_writer(workdir, diff_text)
        (workdir / "review-diff.diff").write_text("")

    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--dry-run",
            "--keep-workspace",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(pr, sample_diff, posted),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
        diff_artifact_writer=empty_writer,
    )

    assert exit_code == 0
    assert sorted(runner.calls[:4]) == ["api-reality", "correctness", "safety", "tests"]
    assert runner.calls[-1] == "coordinator"
    inputs_by_name = {spec.name: spec.input_files for spec in runner.specs}
    assert inputs_by_name["correctness"] == (
        "inputs/shared-context.md",
        "inputs/review-diff.diff",
        "input-manifest.json",
    )
    assert inputs_by_name["api-reality"] == inputs_by_name["correctness"]
    assert inputs_by_name["tests"] == inputs_by_name["correctness"]
    assert inputs_by_name["safety"] == (
        "inputs/shared-context.md",
        "inputs/provider-diff.diff",
        "input-manifest.json",
    )


def test_run_review_all_agents_failed_stops_before_coordinator(tmp_path: Path, sample_diff):
    pr = _make_pr()
    posted: list[dict] = []
    runner = FakeAgentRunner(
        {
            "correctness": Exception("failed"),
            "api-reality": Exception("failed"),
            "tests": Exception("failed"),
            "safety": Exception("failed"),
            "coordinator": make_review(findings=[]),
        }
    )
    exit_code = run_review(
        ["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)],
        client_factory=_make_client_factory(pr, sample_diff, posted),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
        diff_artifact_writer=_fake_diff_artifact_writer,
    )
    assert exit_code == 3
    assert sorted(runner.calls) == ["api-reality", "correctness", "safety", "tests"]
    assert "coordinator" not in runner.calls
    assert posted == []


def test_new_registered_reviewer_runs_without_orchestration_or_coordinator_edits(
    monkeypatch, tmp_path: Path, sample_diff
):
    package = tmp_path / "packages" / "fifth-reviewer"
    package.mkdir(parents=True)
    (package / "agent.yaml").write_text(
        "version: review-bot/v1\n"
        "name: fifth-reviewer\n"
        "kind: reviewer\n"
        "description: A dynamically installed fifth reviewer.\n"
        "prompt: prompt.md\n"
        "inputs:\n"
        "  - pr-context\n"
        "  - review-diff\n"
        "output_schema: review-result/v1\n"
        "order: 50\n"
        "coordinator_policy: coordinator-policy.md\n"
    )
    (package / "prompt.md").write_text("Review this change.")
    (package / "coordinator-policy.md").write_text("Keep concrete findings.")
    added = load_agent_package(package)
    builtin = discover_agent_registry()
    registry = AgentRegistry(reviewers=(*builtin.reviewers, added), coordinator=builtin.coordinator)
    monkeypatch.setattr("review_bot.review.discover_agent_registry", lambda: registry)

    final = make_review(findings=[], overall_correctness="patch is correct")
    runner = FakeAgentRunner({agent.name: final for agent in registry.all_agents})
    workspace = FakeWorkspace(tmp_path / "run", "owner", "repo", 7)
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--dry-run",
            "--keep-workspace",
            "--workspace-root",
            str(tmp_path / "run"),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )

    assert exit_code == 0
    assert runner.calls[-1] == "coordinator"
    assert "fifth-reviewer" in runner.calls[:-1]
    catalog = __import__("json").loads((workspace.artifact_dir / "agent-catalog.json").read_text())
    assert [agent["name"] for agent in catalog["agents"]][-1] == "fifth-reviewer"


def test_run_review_safety_finding_on_filtered_file_uses_provider_diff(tmp_path: Path):
    diff = (
        "diff --git a/uv.lock b/uv.lock\n"
        "index 1111111..2222222 100644\n"
        "--- a/uv.lock\n"
        "+++ b/uv.lock\n"
        "@@ -0,0 +1 @@\n"
        '+token = "live-looking-value"\n'
    )
    pr = _make_pr(changed_files=["uv.lock"])
    posted: list[dict] = []
    finding = make_finding(path="uv.lock", start=1, end=1, priority=2)
    final = make_review(findings=[finding])

    def filtered_writer(workdir: Path, diff_text: str):
        _fake_diff_artifact_writer(workdir, diff_text)
        (workdir / "review-diff.diff").write_text("")

    exit_code = run_review(
        ["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)],
        client_factory=_make_client_factory(pr, diff, posted),
        runner_factory=_make_runner_factory(final),
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
        diff_artifact_writer=filtered_writer,
    )
    assert exit_code == 0
    assert posted[0]["comments"][0]["path"] == "uv.lock"
    assert posted[0]["comments"][0]["side"] == "RIGHT"


def test_run_review_artifact_failure_stops_before_agents(tmp_path: Path, sample_diff):
    pr = _make_pr()
    posted: list[dict] = []
    runner = FakeAgentRunner({})

    def broken_writer(workdir: Path, diff_text: str):
        raise DiffFilterError("unattributable section")

    exit_code = run_review(
        ["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)],
        client_factory=_make_client_factory(pr, sample_diff, posted),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
        diff_artifact_writer=broken_writer,
    )
    assert exit_code == 2
    assert runner.calls == []
    assert posted == []


@pytest.mark.parametrize(("keep", "removed"), [(False, True), (True, False)])
def test_run_review_workspace_cleanup_and_artifact_retention(
    tmp_path: Path, sample_diff, keep: bool, removed: bool
):
    pr = _make_pr()
    posted: list[dict] = []
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    args = [
        "https://github.com/owner/repo/pull/7",
        "--dry-run",
        "--workspace-root",
        str(tmp_path),
    ]
    if keep:
        args.append("--keep-workspace")

    exit_code = run_review(
        args,
        client_factory=_make_client_factory(pr, sample_diff, posted),
        runner_factory=_make_runner_factory(make_review(findings=[])),
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )

    assert exit_code == 0
    assert workspace.removed is removed
    assert (workspace.artifact_dir / "provider-diff.diff").read_text() == sample_diff
    assert (workspace.artifact_dir / "diff-filter.json").exists()
    assert (workspace.artifact_dir / "run-manifest.json").exists()
    assert (workspace.artifact_dir / "agent-catalog.json").exists()
    assert (workspace.artifact_dir / "raw-findings.json").exists()
    assert (workspace.artifact_dir / "unposted-review.json").exists()
    assert not (workspace.source_dir / "provider-diff.diff").exists()
