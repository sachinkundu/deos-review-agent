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


def test_write_raw_findings_keeps_roster_order_and_empty_successes(tmp_path: Path):
    empty = make_review(findings=[])
    results = [
        AgentResult(name="correctness", ok=True, output=empty),
        AgentResult(name="api-reality", ok=False, error="timeout"),
        AgentResult(name="tests", ok=True, output=empty),
        AgentResult(name="safety", ok=True, output=empty),
    ]
    data = __import__("json").loads(write_raw_findings(tmp_path, results).read_text())
    assert [entry["agent"] for entry in data["agents"]] == [
        "correctness",
        "api-reality",
        "tests",
        "safety",
    ]
    assert data["agents"][0]["findings"] == []
    assert data["agents"][2]["findings"] == []


def test_load_coordinator_prompt_exists():
    text = load_coordinator_prompt()
    assert "coordinator" in text.lower()
    assert "raw-findings.json" in text


def test_load_coordinator_prompt_expands_shared_output_contract():
    text = load_coordinator_prompt()
    assert "{{shared_rules}}" not in text
    assert "Shared rules for all review agents" in text
    assert "`overall_confidence_score`" in text


def test_run_coordinator_success(tmp_path: Path):
    final = make_review(findings=[make_finding(priority=1)])
    runner = FakeAgentRunner({"coordinator": final})
    review = run_coordinator(runner, tmp_path)
    validate_review_output(review)
    assert review["findings"][0]["priority"] == 1
    assert runner.specs[0].input_files == (
        "shared-context.md",
        "raw-findings.json",
        "provider-diff.diff",
    )


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
