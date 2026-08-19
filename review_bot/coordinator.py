"""Coordinator: deduplicates, filters, and rewrites agent findings into the
final review, and assigns the final severity and overall verdict.

The coordinator runs as an agent over the raw findings written to
``raw-findings.json``. Unlike individual review agents (whose failure is
recorded and the run continues), a coordinator failure or invalid output stops
the review run: the coordinator output is the posting contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from .agents.registry import AgentRegistry
from .agents.runner import AgentResult, AgentRunner, AgentSpec

RAW_FINDINGS_NAME = "raw-findings.json"


class CoordinatorError(Exception):
    """The coordinator failed or produced invalid output; the run must stop."""

    def __init__(self, message: str, *, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


def write_raw_findings(workdir: Path, results: list[AgentResult]) -> Path:
    """Write the per-agent raw findings (with attribution) for the coordinator."""
    agents = []
    for result in results:
        entry: dict = {
            "agent": result.name,
            "contract_version": result.contract_version,
            "package_digest": result.package_digest,
            "status": "completed" if result.ok else "failed",
            "findings": [],
        }
        if result.ok and result.output is not None:
            for finding in result.output.get("findings", []):
                item = dict(finding)
                item["source_agent"] = result.name
                entry["findings"].append(item)
        else:
            entry["error"] = result.error or "no output"
        agents.append(entry)

    path = workdir / RAW_FINDINGS_NAME
    path.write_text(json.dumps({"agents": agents}, indent=2), encoding="utf-8")
    return path


def validate_result_identities(registry: AgentRegistry, results: list[AgentResult]) -> None:
    """Require a one-to-one identity match with every selected reviewer."""
    expected = {
        agent.name: (agent.contract_version, agent.package_digest) for agent in registry.reviewers
    }
    if [result.name for result in results] != [agent.name for agent in registry.reviewers]:
        raise CoordinatorError("raw result roster or order does not match the selected catalog")
    for result in results:
        identity = (result.contract_version, result.package_digest)
        if expected.get(result.name) != identity:
            raise CoordinatorError(
                f"raw result identity mismatch for agent {result.name!r}: {identity!r}"
            )


def run_coordinator(runner: AgentRunner, spec: AgentSpec, workdir: Path) -> dict:
    """Run the coordinator and return its validated output.

    Raises CoordinatorError when the coordinator fails or its output does not
    match the review schema (the run must stop without posting).
    """
    result = runner.run(spec, workdir)
    if (result.name, result.contract_version, result.package_digest) != (
        spec.name,
        spec.contract_version,
        spec.package_digest,
    ):
        raise CoordinatorError("coordinator result identity does not match its trusted package")
    if not result.ok or result.output is None:
        raise CoordinatorError(f"coordinator failed: {result.error}", timed_out=result.timed_out)
    # The `status` field must survive the coordinator rewrite (it is used by
    # callers to detect whether further review passes are expected).
    if result.output.get("status") not in ("no_further_concerns", "review_in_progress"):
        raise CoordinatorError(
            f"coordinator output lost a valid status field: {result.output.get('status')!r}"
        )
    return result.output
