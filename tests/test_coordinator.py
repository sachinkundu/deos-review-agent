"""Deterministic tests for the coordinator."""

from __future__ import annotations

from pathlib import Path

import pytest

from review_bot.agents.runner import AgentResult
from review_bot.coordinator import (
    CoordinatorError,
    load_coordinator_prompt,
    run_coordinator,
    write_raw_findings,
)
from review_bot.schema import validate_review_output
from tests.conftest import FakeAgentRunner, make_finding, make_review


def test_write_raw_findings(tmp_path: Path):
    results = [
        AgentResult(name="correctness", ok=True, output=make_review(findings=[make_finding()])),
        AgentResult(name="api-reality", ok=False, error="timeout"),
    ]
    path = write_raw_findings(tmp_path, results)
    assert path == tmp_path / "raw-findings.json"
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert len(data["agents"]) == 2
    assert data["agents"][0]["agent"] == "correctness"
    assert data["agents"][0]["findings"][0]["source_agent"] == "correctness"
    assert data["agents"][1]["status"] == "failed"
    assert data["agents"][1]["error"] == "timeout"


def test_load_coordinator_prompt_exists():
    text = load_coordinator_prompt()
    assert "coordinator" in text.lower()
    assert "raw-findings.json" in text


def test_run_coordinator_success(tmp_path: Path):
    final = make_review(findings=[make_finding(priority=1)])
    runner = FakeAgentRunner({"coordinator": final})
    review = run_coordinator(runner, tmp_path)
    validate_review_output(review)
    assert review["findings"][0]["priority"] == 1


def test_run_coordinator_failure(tmp_path: Path):
    runner = FakeAgentRunner(
        {"coordinator": AgentResult(name="coordinator", ok=False, error="bad output")}
    )
    with pytest.raises(CoordinatorError, match="coordinator failed"):
        run_coordinator(runner, tmp_path)


def test_run_coordinator_requires_status(tmp_path: Path):
    bad = make_review(findings=[])
    bad.pop("status")
    runner = FakeAgentRunner({"coordinator": bad})
    with pytest.raises(CoordinatorError, match="status"):
        run_coordinator(runner, tmp_path)


def test_run_coordinator_invalid_status(tmp_path: Path):
    bad = make_review(findings=[], status="done")
    runner = FakeAgentRunner({"coordinator": bad})
    with pytest.raises(CoordinatorError, match="status"):
        run_coordinator(runner, tmp_path)
