"""Deterministic tests for the coordinator."""

from __future__ import annotations

from pathlib import Path

import pytest

from review_bot.agents.registry import discover_agent_registry
from review_bot.agents.runner import AgentResult, AgentSpec
from review_bot.coordinator import (
    CoordinatorError,
    attribute_final_findings,
    run_coordinator,
    validate_result_identities,
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


def _coordinator_spec() -> AgentSpec:
    return AgentSpec(
        "coordinator",
        "prompt",
        (
            "inputs/shared-context.md",
            "inputs/agent-catalog.json",
            "inputs/raw-findings.json",
            "inputs/provider-diff.diff",
            "input-manifest.json",
        ),
        "review-bot/v1",
        "sha256:coordinator",
    )


def test_run_coordinator_success(tmp_path: Path):
    final = make_review(findings=[make_finding(priority=1)])
    runner = FakeAgentRunner({"coordinator": final})
    review = run_coordinator(runner, _coordinator_spec(), tmp_path)
    validate_review_output(review)
    assert review["findings"][0]["priority"] == 1
    assert runner.specs[0].input_files == _coordinator_spec().input_files


def test_run_coordinator_failure(tmp_path: Path):
    runner = FakeAgentRunner(
        {"coordinator": AgentResult(name="coordinator", ok=False, error="bad output")}
    )
    with pytest.raises(CoordinatorError, match="coordinator failed"):
        run_coordinator(runner, _coordinator_spec(), tmp_path)


def test_run_coordinator_requires_status(tmp_path: Path):
    bad = make_review(findings=[])
    bad.pop("status")
    runner = FakeAgentRunner({"coordinator": bad})
    with pytest.raises(CoordinatorError, match="status"):
        run_coordinator(runner, _coordinator_spec(), tmp_path)


def test_run_coordinator_invalid_status(tmp_path: Path):
    bad = make_review(findings=[], status="done")
    runner = FakeAgentRunner({"coordinator": bad})
    with pytest.raises(CoordinatorError, match="status"):
        run_coordinator(runner, _coordinator_spec(), tmp_path)


def test_result_identities_must_match_selected_registry():
    registry = discover_agent_registry()
    results = [
        AgentResult(
            name=agent.name,
            contract_version=agent.contract_version,
            package_digest=agent.package_digest,
            ok=True,
            output=make_review(findings=[]),
        )
        for agent in registry.reviewers
    ]
    validate_result_identities(registry, results)
    results[0].package_digest = "sha256:tampered"
    with pytest.raises(CoordinatorError, match="identity mismatch"):
        validate_result_identities(registry, results)


def test_final_finding_source_is_derived_from_raw_reviewer_result():
    raw = make_finding(title="Concrete bug", path="src/a.py", start=4, end=4)
    final = make_finding(title="Concrete bug", path="src/a.py", start=4, end=4)
    final["source_agent"] = "safety"
    review = make_review(findings=[final])
    results = [
        AgentResult(name="correctness", ok=True, output=make_review(findings=[raw])),
        AgentResult(name="safety", ok=True, output=make_review(findings=[])),
    ]

    attribute_final_findings(review, results)

    assert review["findings"][0]["source_agent"] == "correctness"


def test_duplicate_raw_sources_use_trusted_result_order():
    raw = make_finding(title="Concrete bug", path="src/a.py", start=4, end=4)
    final = make_finding(title="Concrete bug", path="src/a.py", start=4, end=4)
    final["source_agent"] = "safety"
    review = make_review(findings=[final])
    results = [
        AgentResult(name="correctness", ok=True, output=make_review(findings=[raw])),
        AgentResult(name="safety", ok=True, output=make_review(findings=[raw])),
    ]

    attribute_final_findings(review, results)

    assert review["findings"][0]["source_agent"] == "correctness"


def test_final_finding_without_raw_reviewer_source_is_rejected():
    final = make_finding(title="Invented bug", path="src/missing.py", start=9, end=9)
    final["source_agent"] = "correctness"
    review = make_review(findings=[final])
    results = [
        AgentResult(name="correctness", ok=True, output=make_review(findings=[])),
    ]

    with pytest.raises(CoordinatorError, match="no raw reviewer source"):
        attribute_final_findings(review, results)
