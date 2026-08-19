"""Deterministic tests for the agent runner and concurrent execution."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import review_bot.agents.runner as runner_module
from review_bot.agents.registry import AgentSkill, package_digest
from review_bot.agents.runner import (
    AgentResult,
    AgentRunner,
    AgentSpec,
    CodexAgentRunner,
    HarnessError,
    PiAgentRunner,
    run_agents_concurrently,
    verify_harness_command,
)
from tests.conftest import FakeAgentRunner, make_review


def test_run_agents_concurrently_preserves_order():
    runner = FakeAgentRunner(
        {
            "correctness": make_review(findings=[]),
            "api-reality": make_review(findings=[]),
        }
    )
    results = run_agents_concurrently(
        runner,
        [
            (
                AgentSpec("correctness", "p1", ("shared-context.md", "review-diff.diff")),
                Path("/tmp/correctness"),
            ),
            (
                AgentSpec("api-reality", "p2", ("shared-context.md", "review-diff.diff")),
                Path("/tmp/api-reality"),
            ),
        ],
    )
    assert [r.name for r in results] == ["correctness", "api-reality"]
    assert all(r.ok for r in results)


def test_run_agents_concurrently_isolates_failures():
    runner = FakeAgentRunner(
        {
            "correctness": make_review(findings=[]),
            "api-reality": Exception("boom"),
        }
    )
    results = run_agents_concurrently(
        runner,
        [
            (
                AgentSpec("correctness", "p1", ("shared-context.md", "review-diff.diff")),
                Path("/tmp/correctness"),
            ),
            (
                AgentSpec("api-reality", "p2", ("shared-context.md", "review-diff.diff")),
                Path("/tmp/api-reality"),
            ),
        ],
    )
    assert results[0].ok
    assert not results[1].ok
    assert results[1].error is not None
    assert "boom" in results[1].error


def test_run_agents_empty_list():
    runner = FakeAgentRunner({})
    assert run_agents_concurrently(runner, []) == []


def test_all_four_review_agents_reach_concurrent_execution():
    barrier = threading.Barrier(4, timeout=2)

    class BarrierRunner(AgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            barrier.wait()
            return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

    specs = [
        AgentSpec(name, "prompt", ("shared-context.md", "review-diff.diff"))
        for name in ("correctness", "api-reality", "tests", "safety")
    ]
    results = run_agents_concurrently(
        BarrierRunner(), [(spec, Path("/tmp") / spec.name) for spec in specs]
    )
    assert [result.name for result in results] == [
        "correctness",
        "api-reality",
        "tests",
        "safety",
    ]


def test_concurrency_is_bounded_and_result_order_is_stable():
    lock = threading.Lock()
    active = 0
    peak = 0

    class BoundedRunner(AgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

    specs = [AgentSpec(f"agent-{index}", "prompt", ()) for index in range(6)]
    results = run_agents_concurrently(
        BoundedRunner(),
        [(spec, Path("/tmp") / spec.name) for spec in specs],
        max_concurrency=2,
    )
    assert peak == 2
    assert [result.name for result in results] == [spec.name for spec in specs]


def test_concurrent_callbacks_show_all_queued_then_immediate_settlement():
    release_first = threading.Event()
    second_finished = threading.Event()
    events: list[tuple[str, str]] = []
    lock = threading.Lock()

    class OutOfOrderRunner(AgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            if spec.name == "first":
                assert release_first.wait(timeout=2)
            else:
                second_finished.set()
            return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

    def record(kind: str, name: str) -> None:
        with lock:
            events.append((kind, name))

    invocations = [
        (AgentSpec("first", "prompt", ()), Path("/tmp/first")),
        (AgentSpec("second", "prompt", ()), Path("/tmp/second")),
    ]

    def release_after_second() -> None:
        assert second_finished.wait(timeout=2)
        release_first.set()

    releaser = threading.Thread(target=release_after_second)
    releaser.start()
    results = run_agents_concurrently(
        OutOfOrderRunner(),
        invocations,
        max_concurrency=2,
        on_queued=lambda spec: record("queued", spec.name),
        on_started=lambda spec: record("started", spec.name),
        on_settled=lambda result: record("settled", result.name),
    )
    releaser.join()

    assert events[:2] == [("queued", "first"), ("queued", "second")]
    assert events.index(("settled", "second")) < events.index(("settled", "first"))
    assert [result.name for result in results] == ["first", "second"]


def test_waiting_reviewers_remain_queued_until_worker_is_available():
    first_started = threading.Event()
    release_first = threading.Event()
    events: list[tuple[str, str]] = []

    class BlockingRunner(AgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            if spec.name == "first":
                first_started.set()
                assert release_first.wait(timeout=2)
            return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

    invocations = [
        (AgentSpec("first", "prompt", ()), Path("/tmp/first")),
        (AgentSpec("second", "prompt", ()), Path("/tmp/second")),
    ]
    completed: list[list[AgentResult]] = []

    thread = threading.Thread(
        target=lambda: completed.append(
            run_agents_concurrently(
                BlockingRunner(),
                invocations,
                max_concurrency=1,
                on_queued=lambda spec: events.append(("queued", spec.name)),
                on_started=lambda spec: events.append(("started", spec.name)),
            )
        )
    )
    thread.start()
    assert first_started.wait(timeout=2)
    assert events[:2] == [("queued", "first"), ("queued", "second")]
    assert ("started", "first") in events
    assert ("started", "second") not in events
    release_first.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert [result.name for result in completed[0]] == ["first", "second"]


def test_interrupt_cancels_queued_reviewers_without_waiting_for_active_one(monkeypatch):
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    interrupt_called = threading.Event()

    class BlockingRunner(AgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            if spec.name == "first":
                first_started.set()
                assert release_first.wait(timeout=2)
            else:
                second_started.set()
            return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

        def interrupt(self) -> None:
            interrupt_called.set()

    class InterruptingCompletionIterator:
        def __iter__(self):
            return self

        def __next__(self):
            assert first_started.wait(timeout=2)
            raise KeyboardInterrupt

    monkeypatch.setattr(
        runner_module,
        "as_completed",
        lambda futures: InterruptingCompletionIterator(),
    )
    invocations = [
        (AgentSpec("first", "prompt", ()), Path("/tmp/first")),
        (AgentSpec("second", "prompt", ()), Path("/tmp/second")),
    ]

    try:
        started = time.monotonic()
        with pytest.raises(KeyboardInterrupt):
            run_agents_concurrently(BlockingRunner(), invocations, max_concurrency=1)
        assert time.monotonic() - started < 1.0
        assert interrupt_called.is_set()
        assert not release_first.is_set()
        assert not second_started.is_set()
    finally:
        release_first.set()
    time.sleep(0.05)
    assert not second_started.is_set()


def test_pi_interrupt_terminates_active_subprocess_promptly():
    runner = PiAgentRunner(command="pi")
    completed: list[subprocess.CompletedProcess[str]] = []
    thread = threading.Thread(
        target=lambda: completed.append(
            runner._run_process(  # type: ignore[reportPrivateUsage]
                [sys.executable, "-c", "import time; time.sleep(30)"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        )
    )
    thread.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if runner._active_processes:  # type: ignore[reportPrivateUsage]
            break
        time.sleep(0.01)
    assert runner._active_processes  # type: ignore[reportPrivateUsage]

    runner.interrupt()
    thread.join(timeout=2)
    runner.close()

    assert not thread.is_alive()
    assert completed[0].returncode != 0


def test_process_registered_during_interrupt_is_terminated(monkeypatch):
    runner = PiAgentRunner(command="pi")
    real_popen = subprocess.Popen
    process_created = threading.Event()
    release_registration = threading.Event()
    spawned: list[subprocess.Popen[str]] = []
    completed: list[subprocess.CompletedProcess[str]] = []

    def delayed_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        spawned.append(process)
        process_created.set()
        assert release_registration.wait(timeout=2)
        return process

    monkeypatch.setattr(runner_module.subprocess, "Popen", delayed_popen)
    thread = threading.Thread(
        target=lambda: completed.append(
            runner._run_process(  # type: ignore[reportPrivateUsage]
                [sys.executable, "-c", "import time; time.sleep(30)"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        )
    )
    thread.start()
    assert process_created.wait(timeout=2)
    runner.interrupt()
    release_registration.set()
    thread.join(timeout=2)
    runner.close()

    assert not thread.is_alive()
    assert spawned[0].returncode != 0
    assert completed[0].returncode != 0


def test_non_interrupt_exception_waits_for_active_reviewer_before_cleanup():
    second_started = threading.Event()
    release_second = threading.Event()
    captured: list[BaseException] = []
    settled: list[str] = []

    class ExceptionalRunner(AgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            if spec.name == "first":
                assert second_started.wait(timeout=2)
                raise OSError("disk unavailable")
            second_started.set()
            assert release_second.wait(timeout=2)
            return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

    def run() -> None:
        try:
            run_agents_concurrently(
                ExceptionalRunner(),
                [
                    (AgentSpec("first", "prompt", ()), Path("/tmp/first")),
                    (AgentSpec("second", "prompt", ()), Path("/tmp/second")),
                ],
                max_concurrency=2,
                on_settled=lambda result: settled.append(result.name),
            )
        except BaseException as exc:
            captured.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert second_started.wait(timeout=2)
    time.sleep(0.05)
    assert thread.is_alive()
    release_second.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(captured) == 1
    assert isinstance(captured[0], OSError)
    assert settled == ["second"]


def test_progress_callback_failures_do_not_change_agent_results():
    runner = FakeAgentRunner(
        {
            "first": make_review(findings=[]),
            "second": Exception("agent failed"),
        }
    )

    def broken_callback(value) -> None:
        raise OSError("observer unavailable")

    results = run_agents_concurrently(
        runner,
        [
            (AgentSpec("first", "prompt", ()), Path("/tmp/first")),
            (AgentSpec("second", "prompt", ()), Path("/tmp/second")),
        ],
        on_queued=broken_callback,
        on_started=broken_callback,
        on_settled=broken_callback,
    )
    assert [result.name for result in results] == ["first", "second"]
    assert results[0].ok
    assert not results[1].ok


def test_package_mutation_blocks_launch_before_any_runner_starts(tmp_path: Path):
    package = tmp_path / "agent"
    package.mkdir()
    prompt = package / "prompt.md"
    prompt.write_text("original")
    spec = AgentSpec(
        "reviewer",
        "prompt",
        (),
        "review-bot/v1",
        package_digest(package),
        (),
        package,
    )
    prompt.write_text("mutated")
    runner = FakeAgentRunner({"reviewer": make_review(findings=[])})
    with pytest.raises(HarnessError, match="changed before launch"):
        run_agents_concurrently(runner, [(spec, tmp_path)])
    assert runner.calls == []


def test_codex_runner_command_builds(tmp_path: Path):
    from review_bot.schema import load_schema

    schema = load_schema()
    runner = CodexAgentRunner(command="codex", model="gpt-4o", timeout=60, schema=schema)
    try:
        assert runner._schema_file.exists()
        assert json.loads(runner._schema_file.read_text(encoding="utf-8")) == schema
    finally:
        runner.close()


def test_codex_runner_prompt_names_only_explicit_inputs(monkeypatch, tmp_path: Path):
    from review_bot.schema import load_schema

    captured_input: list[str] = []

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        captured_input.append(kwargs["input"])
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(json.dumps(make_review(findings=[])))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("review_bot.agents.runner._run_agent_process", fake_run)
    runner = CodexAgentRunner(command="codex", schema=load_schema())
    try:
        result = runner.run(
            AgentSpec("safety", "prompt", ("shared-context.md", "provider-diff.diff")),
            tmp_path,
        )
    finally:
        runner.close()

    assert result.ok
    assert "`shared-context.md`" in captured_input[0]
    assert "`provider-diff.diff`" in captured_input[0]
    assert "review-diff.diff" not in captured_input[0]


def test_codex_runner_uses_clean_homes_minimal_auth_and_only_owned_skills(
    monkeypatch, tmp_path: Path
):
    from review_bot.schema import load_schema

    real_codex_home = tmp_path / "real-codex"
    real_codex_home.mkdir()
    (real_codex_home / "auth.json").write_text('{"token":"not-printed"}')
    ambient_skill = tmp_path / "real-home" / ".agents" / "skills" / "ambient"
    ambient_skill.mkdir(parents=True)
    (ambient_skill / "SKILL.md").write_text("FORBIDDEN_AMBIENT_SKILL")
    monkeypatch.setenv("HOME", str(tmp_path / "real-home"))
    monkeypatch.setenv("CODEX_HOME", str(real_codex_home))
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-forward")
    package = tmp_path / "package"
    skill_dir = package / "skills" / "owned"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: owned\ndescription: Use for owned review work.\n---\nUse it.\n"
    )
    skill = AgentSkill("owned", skill_dir, "sha256:owned")
    capsule = tmp_path / "capsule"
    capsule.mkdir()
    repository_skill = capsule / "repository" / ".agents" / "skills" / "target"
    repository_skill.mkdir(parents=True)
    (repository_skill / "SKILL.md").write_text("FORBIDDEN_TARGET_SKILL")
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        captured["auth_mode"] = (
            Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
        ).stat().st_mode & 0o777
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_text(json.dumps(make_review(findings=[])))
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("review_bot.agents.runner._run_agent_process", fake_run)
    runner = CodexAgentRunner(command="codex", schema=load_schema())
    try:
        result = runner.run(AgentSpec("reviewer", "prompt", (), skills=(skill,)), capsule)
    finally:
        runner.close()

    assert result.ok
    cmd = captured["cmd"]
    env = captured["env"]
    assert isinstance(cmd, list)
    assert isinstance(env, dict)
    assert "--ignore-user-config" in cmd
    assert "--ignore-rules" in cmd
    assert "--skip-git-repo-check" in cmd
    assert env["HOME"] != str(Path.home())
    assert env["CODEX_HOME"] != str(real_codex_home)
    assert "GITHUB_TOKEN" not in env
    assert captured["auth_mode"] == 0o600
    assert (Path(env["CODEX_HOME"]) / "auth.json").exists() is False  # cleaned on close
    staged_root = capsule / ".agents" / "skills"
    assert [path.name for path in staged_root.iterdir()] == ["owned"]
    staged_text = (staged_root / "owned" / "SKILL.md").read_text()
    assert "FORBIDDEN_AMBIENT_SKILL" not in staged_text
    assert "FORBIDDEN_TARGET_SKILL" not in staged_text


def test_pi_runner_command_builds():
    runner = PiAgentRunner(command="pi", model="hetzner/kimi-k2.7-code", thinking="high")
    try:
        assert runner.command == "pi"
        assert runner.model == "hetzner/kimi-k2.7-code"
        assert runner.thinking == "high"
        assert runner.persist_session
    finally:
        runner.close()


def test_pi_runner_extracts_json_from_markdown():
    from review_bot.agents.runner import _extract_json

    text = "Here is the review:\n```json\n" + json.dumps(make_review(findings=[])) + "\n```"
    data = _extract_json(text)
    assert data["status"] == "no_further_concerns"


def test_pi_runner_repairs_schema_invalid_json_once(monkeypatch, tmp_path: Path):
    invalid = make_review()
    invalid["findings"][0]["title"] = "x" * 81
    repaired = make_review()
    repaired["findings"][0]["title"] = "x" * 80
    responses = iter([invalid, repaired])
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout=json.dumps(next(responses)), stderr=""
        )

    monkeypatch.setattr("review_bot.agents.runner._run_agent_process", fake_run)
    runner = PiAgentRunner(command="pi", thinking="high")
    try:
        result = runner.run(
            AgentSpec(
                "coordinator",
                "original prompt",
                ("shared-context.md", "raw-findings.json", "provider-diff.diff"),
            ),
            tmp_path,
        )
        repair_prompt = Path(commands[1][commands[1].index("--system-prompt") + 1]).read_text(
            encoding="utf-8"
        )
    finally:
        runner.close()

    assert result.ok
    assert len(commands) == 2
    assert "--no-session" not in commands[0]
    assert commands[0][commands[0].index("--name") + 1] == "review-bot-coordinator"
    assert "Schema repair" in repair_prompt
    assert "is too long" in repair_prompt
    assert "x" * 81 in repair_prompt


def test_pi_schema_repair_shares_the_agent_timeout_budget(monkeypatch, tmp_path: Path):
    clock = [100.0]
    timeouts: list[float | None] = []
    invalid = make_review()

    def fake_run_once(spec, prompt_file, workdir, *, timeout=None):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            clock[0] += 7.0
            return AgentResult(
                name=spec.name,
                ok=False,
                error="schema invalid",
                extra={"invalid_output": invalid},
            )
        clock[0] += 3.0
        return AgentResult(name=spec.name, ok=True, output=make_review(findings=[]))

    monkeypatch.setattr("review_bot.agents.runner.time.monotonic", lambda: clock[0])
    runner = PiAgentRunner(command="pi", timeout=10)
    monkeypatch.setattr(runner, "_run_once", fake_run_once)
    try:
        result = runner.run(AgentSpec("tests", "prompt", ()), tmp_path)
    finally:
        runner.close()

    assert result.ok
    assert timeouts == [10, 3.0]
    assert result.duration_seconds == 10.0


def test_pi_runner_can_disable_session_persistence(monkeypatch, tmp_path: Path):
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout=json.dumps(make_review()), stderr=""
        )

    monkeypatch.setattr("review_bot.agents.runner._run_agent_process", fake_run)
    runner = PiAgentRunner(command="pi", persist_session=False)
    try:
        result = runner.run(
            AgentSpec("correctness", "prompt", ("shared-context.md", "review-diff.diff")),
            tmp_path,
        )
    finally:
        runner.close()

    assert result.ok
    assert "--no-session" in commands[0]
    assert "--name" not in commands[0]
    assert "--no-skills" in commands[0]
    assert "--no-extensions" in commands[0]
    assert "--no-prompt-templates" in commands[0]
    assert "--no-themes" in commands[0]
    assert "--no-context-files" in commands[0]
    assert "--no-approve" in commands[0]
    assert commands[0][commands[0].index("--tools") + 1] == "read,grep,find,ls"
    assert commands[0][-2:] == ["@shared-context.md", "@review-diff.diff"]


def test_pi_runner_passes_only_explicit_owned_skills(monkeypatch, tmp_path: Path):
    commands: list[list[str]] = []
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "SKILL.md").write_text(
        "---\nname: owned\ndescription: Use for owned work.\n---\nUse it.\n"
    )

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout=json.dumps(make_review()), stderr=""
        )

    monkeypatch.setattr("review_bot.agents.runner._run_agent_process", fake_run)
    runner = PiAgentRunner(command="pi", persist_session=False)
    try:
        result = runner.run(
            AgentSpec(
                "correctness",
                "prompt",
                ("input-manifest.json",),
                skills=(AgentSkill("owned", owned, "sha256:owned"),),
            ),
            tmp_path,
        )
    finally:
        runner.close()
    assert result.ok
    assert commands[0][commands[0].index("--skill") + 1] == str(owned)
    assert commands[0].count("--skill") == 1


def test_verify_harness_command_accepts_required_contract(monkeypatch):
    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="pi 1.0", stderr="")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="--no-skills --skill --no-extensions --no-context-files",
            stderr="",
        )

    monkeypatch.setattr("review_bot.agents.runner.subprocess.run", fake_run)
    assert verify_harness_command("pi", "pi") == "pi 1.0"


def test_verify_harness_command_rejects_unknown_and_missing_flags(monkeypatch):
    with pytest.raises(HarnessError, match="unsupported"):
        verify_harness_command("other", "other")

    monkeypatch.setattr(
        "review_bot.agents.runner.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout="codex", stderr=""),
    )
    with pytest.raises(HarnessError, match="lacks required"):
        verify_harness_command("codex", "codex")


def test_verify_harness_command_rejects_codex_admin_skills(monkeypatch, tmp_path: Path):
    admin_root = tmp_path / "etc-codex-skills"
    admin_skill = admin_root / "admin"
    admin_skill.mkdir(parents=True)
    (admin_skill / "SKILL.md").write_text("admin instructions")
    monkeypatch.setattr(runner_module, "CODEX_ADMIN_SKILLS_ROOT", admin_root)

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        output = (
            "codex 1.0"
            if "--version" in cmd
            else "--ignore-user-config --ignore-rules --sandbox --ephemeral"
        )
        return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")

    monkeypatch.setattr("review_bot.agents.runner.subprocess.run", fake_run)
    with pytest.raises(HarnessError, match="admin skill scope must be empty"):
        verify_harness_command("codex", "codex")


def test_verify_harness_command_wraps_os_errors(monkeypatch):
    monkeypatch.setattr(
        "review_bot.agents.runner.subprocess.run",
        lambda cmd, **kwargs: (_ for _ in ()).throw(PermissionError("not executable")),
    )
    with pytest.raises(HarnessError, match="cannot inspect pi harness"):
        verify_harness_command("pi", "pi")


@pytest.mark.parametrize("runner_kind", ["codex", "pi"])
def test_agent_runner_returns_failure_when_command_cannot_start(
    monkeypatch, tmp_path: Path, runner_kind: str
):
    from review_bot.schema import load_schema

    monkeypatch.setattr(
        "review_bot.agents.runner._run_agent_process",
        lambda cmd, **kwargs: (_ for _ in ()).throw(PermissionError("not executable")),
    )
    runner: AgentRunner
    if runner_kind == "codex":
        runner = CodexAgentRunner(command="codex", schema=load_schema())
    else:
        runner = PiAgentRunner(command="pi")
    try:
        result = runner.run(AgentSpec("reviewer", "prompt", ()), tmp_path)
    finally:
        runner.close()

    assert not result.ok
    assert result.error is not None
    assert "could not be started" in result.error


@pytest.mark.parametrize("read_failure", ["unicode", "oserror"])
def test_codex_runner_returns_failure_for_unreadable_output(
    monkeypatch, tmp_path: Path, read_failure: str
):
    from review_bot.schema import load_schema

    original_read_text = Path.read_text

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        output_path = Path(cmd[cmd.index("-o") + 1])
        output_path.write_bytes(b"\xff" if read_failure == "unicode" else b"{}")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    def fake_read_text(path: Path, *args, **kwargs) -> str:
        if read_failure == "oserror" and path.name == "reviewer.json":
            raise OSError("unreadable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr("review_bot.agents.runner._run_agent_process", fake_run)
    monkeypatch.setattr(Path, "read_text", fake_read_text)
    runner = CodexAgentRunner(command="codex", schema=load_schema())
    try:
        result = runner.run(AgentSpec("reviewer", "prompt", ()), tmp_path)
    finally:
        runner.close()

    assert not result.ok
    assert result.error is not None
    assert "not readable JSON" in result.error


def test_codex_runner_validates_output(tmp_path: Path):
    from review_bot.schema import load_schema

    out_file = tmp_path / "correctness.json"
    out_file.write_text(json.dumps(make_review(findings=[])))

    class FixedCodexRunner(CodexAgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            from review_bot.schema import validate_review_output

            data = json.loads(out_file.read_text(encoding="utf-8"))
            validate_review_output(data)
            return AgentResult(name=spec.name, ok=True, output=data)

    runner = FixedCodexRunner(schema=load_schema())
    try:
        result = runner.run(
            AgentSpec("correctness", "prompt", ("shared-context.md", "review-diff.diff")),
            tmp_path,
        )
        assert result.ok
        assert result.output is not None
        assert result.output["status"] == "no_further_concerns"
    finally:
        runner.close()


def test_codex_runner_rejects_invalid_output(tmp_path: Path):
    from review_bot.schema import SchemaError, load_schema

    out_file = tmp_path / "correctness.json"
    out_file.write_text(json.dumps({"invalid": True}))

    class FixedCodexRunner(CodexAgentRunner):
        def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
            from review_bot.schema import validate_review_output

            data = json.loads(out_file.read_text(encoding="utf-8"))
            try:
                validate_review_output(data)
            except SchemaError as e:
                return AgentResult(
                    name=spec.name,
                    ok=False,
                    error=f"agent output failed schema validation: {e}",
                )
            return AgentResult(name=spec.name, ok=True, output=data)

    runner = FixedCodexRunner(schema=load_schema())
    try:
        result = runner.run(
            AgentSpec("correctness", "prompt", ("shared-context.md", "review-diff.diff")),
            tmp_path,
        )
        assert not result.ok
        assert result.error is not None
        assert "schema validation" in result.error
    finally:
        runner.close()
