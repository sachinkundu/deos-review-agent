"""Deterministic tests for the agent runner and concurrent execution."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from review_bot.agents.runner import (
    AgentResult,
    CodexAgentRunner,
    PiAgentRunner,
    run_agents_concurrently,
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
        [("correctness", "p1"), ("api-reality", "p2")],
        Path("/tmp"),
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
        [("correctness", "p1"), ("api-reality", "p2")],
        Path("/tmp"),
    )
    assert results[0].ok
    assert not results[1].ok
    assert results[1].error is not None
    assert "boom" in results[1].error


def test_run_agents_empty_list():
    runner = FakeAgentRunner({})
    assert run_agents_concurrently(runner, [], Path("/tmp")) == []


def test_codex_runner_command_builds(tmp_path: Path):
    from review_bot.schema import load_schema

    schema = load_schema()
    runner = CodexAgentRunner(command="codex", model="gpt-4o", timeout=60, schema=schema)
    try:
        assert runner._schema_file.exists()
        assert json.loads(runner._schema_file.read_text(encoding="utf-8")) == schema
    finally:
        runner.close()


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

    monkeypatch.setattr("review_bot.agents.runner.subprocess.run", fake_run)
    runner = PiAgentRunner(command="pi", thinking="high")
    try:
        result = runner.run("coordinator", "original prompt", tmp_path)
        repair_prompt = Path(
            commands[1][commands[1].index("--system-prompt") + 1]
        ).read_text(encoding="utf-8")
    finally:
        runner.close()

    assert result.ok
    assert len(commands) == 2
    assert "--no-session" not in commands[0]
    assert commands[0][commands[0].index("--name") + 1] == "review-bot-coordinator"
    assert "Schema repair" in repair_prompt
    assert "is too long" in repair_prompt
    assert "x" * 81 in repair_prompt


def test_pi_runner_can_disable_session_persistence(monkeypatch, tmp_path: Path):
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout=json.dumps(make_review()), stderr=""
        )

    monkeypatch.setattr("review_bot.agents.runner.subprocess.run", fake_run)
    runner = PiAgentRunner(command="pi", persist_session=False)
    try:
        result = runner.run("correctness", "prompt", tmp_path)
    finally:
        runner.close()

    assert result.ok
    assert "--no-session" in commands[0]
    assert "--name" not in commands[0]


def test_codex_runner_validates_output(tmp_path: Path):
    from review_bot.schema import load_schema

    out_file = tmp_path / "correctness.json"
    out_file.write_text(json.dumps(make_review(findings=[])))

    class FixedCodexRunner(CodexAgentRunner):
        def run(self, name: str, prompt: str, workdir: Path) -> AgentResult:
            from review_bot.schema import validate_review_output

            data = json.loads(out_file.read_text(encoding="utf-8"))
            validate_review_output(data)
            return AgentResult(name=name, ok=True, output=data)

    runner = FixedCodexRunner(schema=load_schema())
    try:
        result = runner.run("correctness", "prompt", tmp_path)
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
        def run(self, name: str, prompt: str, workdir: Path) -> AgentResult:
            from review_bot.schema import validate_review_output

            data = json.loads(out_file.read_text(encoding="utf-8"))
            try:
                validate_review_output(data)
            except SchemaError as e:
                return AgentResult(
                    name=name, ok=False, error=f"agent output failed schema validation: {e}"
                )
            return AgentResult(name=name, ok=True, output=data)

    runner = FixedCodexRunner(schema=load_schema())
    try:
        result = runner.run("correctness", "prompt", tmp_path)
        assert not result.ok
        assert result.error is not None
        assert "schema validation" in result.error
    finally:
        runner.close()
