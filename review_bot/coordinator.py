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

from .agents.runner import AgentResult, AgentRunner, AgentSpec
from .diff_filter import PROVIDER_DIFF_NAME
from .shared_context import SHARED_CONTEXT_NAME

RAW_FINDINGS_NAME = "raw-findings.json"
PROMPTS_DIR = Path(__file__).parent / "prompts"


class CoordinatorError(Exception):
    """The coordinator failed or produced invalid output; the run must stop."""


def write_raw_findings(workdir: Path, results: list[AgentResult]) -> Path:
    """Write the per-agent raw findings (with attribution) for the coordinator."""
    agents = []
    for result in results:
        entry: dict = {
            "agent": result.name,
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


def load_coordinator_prompt() -> str:
    text = (PROMPTS_DIR / "coordinator.md").read_text(encoding="utf-8")
    shared = (PROMPTS_DIR / "shared-rules.md").read_text(encoding="utf-8")
    return text.replace("{{shared_rules}}", shared)


def run_coordinator(runner: AgentRunner, workdir: Path) -> dict:
    """Run the coordinator and return its validated output.

    Raises CoordinatorError when the coordinator fails or its output does not
    match the review schema (the run must stop without posting).
    """
    spec = AgentSpec(
        name="coordinator",
        prompt=load_coordinator_prompt(),
        input_files=(SHARED_CONTEXT_NAME, RAW_FINDINGS_NAME, PROVIDER_DIFF_NAME),
    )
    result = runner.run(spec, workdir)
    if not result.ok or result.output is None:
        raise CoordinatorError(f"coordinator failed: {result.error}")
    # The `status` field must survive the coordinator rewrite (it is used by
    # callers to detect whether further review passes are expected).
    if result.output.get("status") not in ("no_further_concerns", "review_in_progress"):
        raise CoordinatorError(
            f"coordinator output lost a valid status field: {result.output.get('status')!r}"
        )
    return result.output
