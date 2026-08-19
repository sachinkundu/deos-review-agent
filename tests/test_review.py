"""Deterministic tests for the review CLI wiring."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from review_bot.agents.registry import AgentRegistry, discover_agent_registry, load_agent_package
from review_bot.diff_filter import DiffFilterError
from review_bot.github import Credentials, GitHubAppClient, GitHubError, PRInfo
from review_bot.review import build_review_body, run_review, run_status
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
        return {
            "id": 99,
            "state": event,
            "html_url": "https://github.com/owner/repo/pull/7#pullrequestreview-99",
        }


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


def test_run_review_bot_skip(tmp_path: Path, capsys):
    pr = _make_pr(sender_login="review-bot[bot]")
    posted = []
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--progress",
            "json",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(pr, "", posted),
        runner_factory=_make_runner_factory(make_review(findings=[])),
        workspace_factory=lambda root, owner, repo, number, bootstrap_timeout=600: FakeWorkspace(
            root, owner, repo, number, bootstrap_timeout=bootstrap_timeout
        ),
        diff_artifact_writer=_fake_diff_artifact_writer,
    )
    assert exit_code == 0
    assert posted == []
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert any(event["phase"] == "cleanup" and event["state"] == "skipped" for event in events)
    assert events[-1]["message"] == "run finished"


def test_bot_identity_failure_stays_in_pr_metadata_phase(monkeypatch, tmp_path: Path, capsys):
    monkeypatch.delenv("GITHUB_APP_BOT_USERNAME")

    class IdentityFailureClient(FakeGitHubClient):
        def bot_username(self) -> str:
            raise GitHubError("identity lookup unavailable")

    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--progress",
            "json",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=lambda creds: IdentityFailureClient(creds, _make_pr(), "", []),
        workspace_factory=lambda *args, **kwargs: workspace,
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    events = [json.loads(line) for line in captured.err.splitlines()]
    metadata_states = [event["state"] for event in events if event["phase"] == "pr-metadata"]
    assert metadata_states == ["running", "failed", "failed"]
    assert not workspace.workdir.exists()


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


def test_retained_post_success_records_provider_review_url(tmp_path: Path, sample_diff):
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--keep-workspace",
            "--progress",
            "off",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=_make_runner_factory(make_review(findings=[])),
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )

    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert exit_code == 0
    assert snapshot["overall"] == {"phase": "posting", "state": "succeeded"}
    assert snapshot["review_url"] == ("https://github.com/owner/repo/pull/7#pullrequestreview-99")


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
    tmp_path: Path, sample_diff, keep: bool, removed: bool, capsys
):
    pr = _make_pr()
    posted: list[dict] = []
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    args = [
        "https://github.com/owner/repo/pull/7",
        "--dry-run",
        "--progress",
        "json",
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
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert events[-2]["phase"] == "cleanup"
    assert events[-1]["message"] == "run finished"
    assert workspace.removed is removed
    assert (workspace.artifact_dir / "provider-diff.diff").read_text() == sample_diff
    assert (workspace.artifact_dir / "diff-filter.json").exists()
    assert (workspace.artifact_dir / "run-manifest.json").exists()
    assert (workspace.artifact_dir / "agent-catalog.json").exists()
    assert (workspace.artifact_dir / "raw-findings.json").exists()
    assert (workspace.artifact_dir / "unposted-review.json").exists()
    assert not (workspace.source_dir / "provider-diff.diff").exists()
    if keep:
        snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
        assert snapshot["final_exit_code"] == 0
        assert snapshot["overall"] == {"phase": "posting", "state": "skipped"}


def test_progress_modes_preserve_stdout_payload_artifacts_and_provider_calls(
    tmp_path: Path, sample_diff, capsys
):
    finding = make_finding(path="src/widget/paginate.py", start=9, end=9, priority=1)
    final = make_review(findings=[finding], overall_correctness="patch is incorrect")
    observations: dict[str, tuple[str, str, list[dict], dict, str]] = {}

    for mode in ("off", "plain", "json", "auto"):
        posted: list[dict] = []
        workspace = FakeWorkspace(tmp_path / mode, "owner", "repo", 7)
        exit_code = run_review(
            [
                "https://github.com/owner/repo/pull/7",
                "--dry-run",
                "--keep-workspace",
                "--progress",
                mode,
                "--workspace-root",
                str(tmp_path / mode),
            ],
            client_factory=_make_client_factory(_make_pr(), sample_diff, posted),
            runner_factory=_make_runner_factory(final),
            workspace_factory=lambda *args, _workspace=workspace, **kwargs: _workspace,
            diff_artifact_writer=_fake_diff_artifact_writer,
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        manifest = json.loads((workspace.artifact_dir / "run-manifest.json").read_text())
        payload = (workspace.artifact_dir / "unposted-review.json").read_text()
        observations[mode] = (captured.out, captured.err, posted, manifest, payload)

    baseline = observations["off"]
    for mode in ("plain", "json", "auto"):
        assert observations[mode][0] == baseline[0]
        assert observations[mode][2:] == baseline[2:]
    assert baseline[1] == ""
    assert "registry running" in observations["plain"][1]
    assert "\x1b" not in observations["plain"][1]
    assert "\x1b" not in observations["auto"][1]
    json_events = [json.loads(line) for line in observations["json"][1].splitlines()]
    assert json_events
    assert all(event["contract"] == "review-progress-event/v1" for event in json_events)


def test_invalid_progress_fails_before_registry_credentials_or_provider(
    monkeypatch, tmp_path: Path
):
    called: list[str] = []
    monkeypatch.setattr(
        "review_bot.review.discover_agent_registry", lambda: called.append("registry")
    )

    with pytest.raises(SystemExit) as exc_info:
        run_review(
            ["https://github.com/owner/repo/pull/7", "--progress", "percent"],
            client_factory=lambda creds: called.append("provider"),  # type: ignore[arg-type]
        )
    assert exc_info.value.code == 2
    assert called == []


def test_malformed_url_fails_before_progress_registry_credentials_or_provider(
    monkeypatch, tmp_path: Path, capsys
):
    called: list[str] = []
    monkeypatch.setattr(
        "review_bot.review.discover_agent_registry", lambda: called.append("registry")
    )
    workspace_root = tmp_path / "workspaces"

    exit_code = run_review(
        [
            "not-a-pull-request-url",
            "--progress",
            "json",
            "--workspace-root",
            str(workspace_root),
        ],
        client_factory=lambda creds: called.append("provider"),  # type: ignore[arg-type]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert called == []
    assert captured.err == ""
    assert "not a GitHub pull request URL" in captured.out
    assert not workspace_root.exists()


def test_negative_agent_timeout_fails_before_provider_work(tmp_path: Path):
    provider_calls: list[str] = []

    class UnusedClient(FakeGitHubClient):
        def mint_app_jwt(self):
            provider_calls.append("mint")
            return super().mint_app_jwt()

    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--agent-timeout",
            "-1",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=lambda creds: UnusedClient(creds, _make_pr(), "", []),
    )

    assert exit_code == 1
    assert provider_calls == []
    assert not (tmp_path / "owner-repo-pr7").exists()


def test_bot_skip_reports_every_inapplicable_phase(tmp_path: Path, capsys):
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--progress",
            "json",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(sender_login="review-bot[bot]"), "", []),
        runner_factory=_make_runner_factory(make_review(findings=[])),
        workspace_factory=lambda *args, **kwargs: FakeWorkspace(tmp_path, "owner", "repo", 7),
        diff_artifact_writer=_fake_diff_artifact_writer,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    events = [json.loads(line) for line in captured.err.splitlines()]
    skipped = {event["phase"] for event in events if event["state"] == "skipped"}
    assert skipped == {
        "provider-diff",
        "workspace",
        "bootstrap",
        "reviewers",
        "coordination",
        "schema-validation",
        "diff-validation",
        "head-freshness",
        "payload",
        "posting",
        "cleanup",
    }


def test_all_reviewer_failures_are_retained_and_later_phases_skipped(tmp_path: Path, sample_diff):
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    runner = FakeAgentRunner(
        {
            "correctness": Exception("model secret one"),
            "api-reality": Exception("model secret two"),
            "tests": Exception("model secret three"),
            "safety": Exception("model secret four"),
        }
    )
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--keep-workspace",
            "--progress",
            "off",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )
    snapshot_text = (workspace.artifact_dir / "progress.json").read_text()
    snapshot = json.loads(snapshot_text)
    assert exit_code == 3
    assert [item["state"] for item in snapshot["reviewers"]] == ["failed"] * 4
    assert all(item["error_summary"] == "reviewer failed" for item in snapshot["reviewers"])
    assert snapshot["coordinator"]["state"] == "skipped"
    assert snapshot["overall"] == {"phase": "reviewers", "state": "failed"}
    assert "model secret" not in snapshot_text
    assert snapshot["final_exit_code"] == 3


def test_unexpected_exception_finalizes_retained_progress(tmp_path: Path, sample_diff):
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)

    def broken_writer(workdir: Path, diff_text: str):
        raise OSError("disk unavailable")

    with pytest.raises(OSError, match="disk unavailable"):
        run_review(
            [
                "https://github.com/owner/repo/pull/7",
                "--keep-workspace",
                "--progress",
                "off",
                "--workspace-root",
                str(tmp_path),
            ],
            client_factory=_make_client_factory(_make_pr(), sample_diff, []),
            workspace_factory=lambda *args, **kwargs: workspace,
            diff_artifact_writer=broken_writer,
        )

    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert snapshot["overall"] == {"phase": "provider-diff", "state": "failed"}
    assert snapshot["finished_at"] is not None
    assert snapshot["final_exit_code"] == 1


def test_raw_findings_write_failure_is_attributed_to_coordination(
    tmp_path: Path, sample_diff, monkeypatch
):
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)

    def broken_writer(workdir: Path, results: list[object]):
        raise OSError("disk unavailable")

    monkeypatch.setattr("review_bot.review.write_raw_findings", broken_writer)
    with pytest.raises(OSError, match="disk unavailable"):
        run_review(
            [
                "https://github.com/owner/repo/pull/7",
                "--keep-workspace",
                "--progress",
                "off",
                "--workspace-root",
                str(tmp_path),
            ],
            client_factory=_make_client_factory(_make_pr(), sample_diff, []),
            runner_factory=_make_runner_factory(make_review(findings=[])),
            workspace_factory=lambda *args, **kwargs: workspace,
            diff_artifact_writer=_fake_diff_artifact_writer,
        )

    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert snapshot["overall"] == {"phase": "coordination", "state": "failed"}
    assert [item["state"] for item in snapshot["reviewers"]] == ["succeeded"] * 4
    assert snapshot["coordinator"]["state"] == "failed"
    assert snapshot["final_exit_code"] == 1


def test_json_unexpected_exception_keeps_stderr_jsonl(tmp_path: Path, sample_diff, capsys):
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)

    def broken_writer(workdir: Path, diff_text: str):
        raise OSError("disk unavailable")

    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--keep-workspace",
            "--progress",
            "json",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=broken_writer,
    )
    captured = capsys.readouterr()

    events = [json.loads(line) for line in captured.err.splitlines()]
    assert exit_code == 1
    assert events[-1]["state"] == "failed"
    assert "unexpected failure: OSError" in captured.out
    assert "Traceback" not in captured.err


def test_schema_failure_finalizes_retained_progress(tmp_path: Path, sample_diff):
    valid = make_review(findings=[], overall_correctness="patch is correct")
    invalid = dict(valid)
    invalid.pop("overall_confidence_score")
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    runner = FakeAgentRunner(
        {
            "correctness": valid,
            "api-reality": valid,
            "tests": valid,
            "safety": valid,
            "coordinator": invalid,
        }
    )
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--keep-workspace",
            "--progress",
            "off",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )

    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert exit_code == 7
    assert snapshot["overall"] == {"phase": "schema-validation", "state": "failed"}
    assert snapshot["final_exit_code"] == 7


@pytest.mark.parametrize("failure_phase", ["head-freshness", "posting"])
def test_provider_failure_finalizes_retained_progress(
    tmp_path: Path, sample_diff, failure_phase: str
):
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)

    class FailingClient(FakeGitHubClient):
        def __init__(self, creds, pr, diff, posted):
            super().__init__(creds, pr, diff, posted)
            self.fetch_count = 0

        def fetch_pr(self, owner, repo, number, token=None):
            self.fetch_count += 1
            if failure_phase == "head-freshness" and self.fetch_count == 2:
                raise GitHubError("head read failed")
            return self.pr

        def post_review(self, owner, repo, number, commit_id, event, body, comments, token=None):
            if failure_phase == "posting":
                raise GitHubError("post failed")
            return super().post_review(owner, repo, number, commit_id, event, body, comments, token)

    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--keep-workspace",
            "--progress",
            "off",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=lambda creds: FailingClient(creds, _make_pr(), sample_diff, []),
        runner_factory=_make_runner_factory(make_review(findings=[])),
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )

    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert exit_code == 6
    assert snapshot["overall"] == {"phase": failure_phase, "state": "failed"}
    assert snapshot["final_exit_code"] == 6


def test_reviewer_timeout_wiring_is_retained_end_to_end(tmp_path: Path, sample_diff):
    from review_bot.agents.runner import AgentResult

    final = make_review(findings=[], overall_correctness="patch is correct")
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    runner = FakeAgentRunner(
        {
            "correctness": AgentResult(
                name="correctness", ok=False, error="agent timed out after 30s"
            ),
            "api-reality": final,
            "tests": final,
            "safety": final,
            "coordinator": final,
        }
    )
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--dry-run",
            "--keep-workspace",
            "--progress",
            "off",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )

    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert exit_code == 0
    assert snapshot["reviewers"][0]["state"] == "timed-out"
    assert snapshot["reviewers"][0]["error_summary"] == "reviewer timed out"


def test_coordinator_timeout_wiring_is_retained_end_to_end(tmp_path: Path, sample_diff):
    final = make_review(findings=[], overall_correctness="patch is correct")
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    runner = FakeAgentRunner(
        {
            "correctness": final,
            "api-reality": final,
            "tests": final,
            "safety": final,
            "coordinator": Exception("agent timed out after 30s"),
        }
    )
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--keep-workspace",
            "--progress",
            "off",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )

    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert exit_code == 4
    assert snapshot["coordinator"]["state"] == "timed-out"
    assert snapshot["coordinator"]["error_summary"] == "coordinator timed out"


def test_json_progress_stderr_stays_parseable_when_existing_diagnostics_are_emitted(
    tmp_path: Path, sample_diff, capsys
):
    runner = FakeAgentRunner(
        {
            "correctness": Exception("failed"),
            "api-reality": Exception("failed"),
            "tests": Exception("failed"),
            "safety": Exception("failed"),
        }
    )
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--progress",
            "json",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=lambda **kwargs: runner,
        workspace_factory=lambda *args, **kwargs: FakeWorkspace(tmp_path, "owner", "repo", 7),
        diff_artifact_writer=_fake_diff_artifact_writer,
    )
    captured = capsys.readouterr()
    assert exit_code == 3
    assert "warning: agent" in captured.out
    assert "all review agents failed" in captured.out
    events = [json.loads(line) for line in captured.err.splitlines()]
    assert events
    assert all(event["contract"] == "review-progress-event/v1" for event in events)


def test_status_reads_snapshot_without_provider_or_file_mutation(
    tmp_path: Path, sample_diff, capsys
):
    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--dry-run",
            "--keep-workspace",
            "--progress",
            "off",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=_make_runner_factory(make_review(findings=[])),
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )
    assert exit_code == 0
    capsys.readouterr()
    path = workspace.artifact_dir / "progress.json"
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    assert (
        run_status(["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)]) == 0
    )
    human = capsys.readouterr()
    assert "review-bot status: owner/repo#7" in human.out
    assert human.err == ""
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before

    assert (
        run_status(
            [
                "https://github.com/owner/repo/pull/7",
                "--workspace-root",
                str(tmp_path),
                "--json",
            ]
        )
        == 0
    )
    machine = capsys.readouterr()
    assert json.loads(machine.out)["contract"] == "review-progress-snapshot/v1"
    assert machine.err == ""
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_status_missing_snapshot_is_a_read_only_error(tmp_path: Path, capsys):
    assert (
        run_status(["https://github.com/owner/repo/pull/7", "--workspace-root", str(tmp_path)]) == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "progress snapshot not found" in captured.err
    assert not (tmp_path / "owner-repo-pr7").exists()


def test_handled_interrupt_retains_interrupted_state_and_reraises(tmp_path: Path, sample_diff):
    from review_bot.agents.runner import AgentResult, AgentRunner, AgentSpec

    class InterruptingRunner(AgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            if spec.name == "correctness":
                raise KeyboardInterrupt
            return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    with pytest.raises(KeyboardInterrupt):
        run_review(
            [
                "https://github.com/owner/repo/pull/7",
                "--keep-workspace",
                "--progress",
                "off",
                "--workspace-root",
                str(tmp_path),
            ],
            client_factory=_make_client_factory(_make_pr(), sample_diff, []),
            runner_factory=lambda **kwargs: InterruptingRunner(),
            workspace_factory=lambda *args, **kwargs: workspace,
            diff_artifact_writer=_fake_diff_artifact_writer,
        )
    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert snapshot["overall"]["state"] == "interrupted"
    assert snapshot["final_exit_code"] == 130
    assert any(item["state"] == "interrupted" for item in snapshot["reviewers"])
    assert all(item["state"] != "queued" for item in snapshot["reviewers"])
    assert workspace.removed is False


def test_interrupt_preserves_active_phase_through_cleanup(tmp_path: Path, sample_diff, capsys):
    from review_bot.agents.runner import AgentResult, AgentRunner, AgentSpec

    class InterruptingRunner(AgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            if spec.name == "correctness":
                raise KeyboardInterrupt
            return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

    workspace = FakeWorkspace(tmp_path, "owner", "repo", 7)
    exit_code = run_review(
        [
            "https://github.com/owner/repo/pull/7",
            "--progress",
            "json",
            "--workspace-root",
            str(tmp_path),
        ],
        client_factory=_make_client_factory(_make_pr(), sample_diff, []),
        runner_factory=lambda **kwargs: InterruptingRunner(),
        workspace_factory=lambda *args, **kwargs: workspace,
        diff_artifact_writer=_fake_diff_artifact_writer,
    )
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.err.splitlines()]
    assert exit_code == 130
    assert events[-1]["phase"] == "reviewers"
    assert events[-1]["state"] == "interrupted"
    assert "KeyboardInterrupt" not in captured.err
    assert workspace.removed is True


def test_cleanup_failure_finalizes_surviving_snapshot(tmp_path: Path, sample_diff):
    class FailingRemovalWorkspace(FakeWorkspace):
        def remove(self) -> None:
            raise OSError("permission denied")

    workspace = FailingRemovalWorkspace(tmp_path, "owner", "repo", 7)
    with pytest.raises(OSError, match="permission denied"):
        run_review(
            [
                "https://github.com/owner/repo/pull/7",
                "--dry-run",
                "--progress",
                "off",
                "--workspace-root",
                str(tmp_path),
            ],
            client_factory=_make_client_factory(_make_pr(), sample_diff, []),
            runner_factory=_make_runner_factory(make_review(findings=[])),
            workspace_factory=lambda *args, **kwargs: workspace,
            diff_artifact_writer=_fake_diff_artifact_writer,
        )
    snapshot = json.loads((workspace.artifact_dir / "progress.json").read_text())
    assert snapshot["overall"] == {"phase": "cleanup", "state": "failed"}
    assert snapshot["final_exit_code"] == 1


def test_real_cleanup_removes_progress_snapshot(tmp_path: Path, sample_diff, capsys):
    class RemovingWorkspace(FakeWorkspace):
        def remove(self) -> None:
            self.removed = True
            shutil.rmtree(self.workdir, ignore_errors=True)

    workspace = RemovingWorkspace(tmp_path, "owner", "repo", 7)
    assert (
        run_review(
            [
                "https://github.com/owner/repo/pull/7",
                "--dry-run",
                "--progress",
                "json",
                "--workspace-root",
                str(tmp_path),
            ],
            client_factory=_make_client_factory(_make_pr(), sample_diff, []),
            runner_factory=_make_runner_factory(make_review(findings=[])),
            workspace_factory=lambda *args, **kwargs: workspace,
            diff_artifact_writer=_fake_diff_artifact_writer,
        )
        == 0
    )
    events = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert all(event["message"] != "progress snapshot persistence disabled" for event in events)
    assert events[-2]["phase"] == "cleanup"
    assert events[-2]["state"] == "succeeded"
    assert events[-1]["message"] == "run finished"
    assert not workspace.workdir.exists()
