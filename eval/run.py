"""Regression runner for review-bot eval cases.

Usage:
    uv run python eval/run.py

Runs the review-bot CLI in --dry-run mode against each eval case and verifies
that the produced review payload contains the expected findings on the
expected diff lines.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASES_PATH = Path(__file__).parent / "cases.json"
CLI = ["uv", "run", "review-bot"]


@dataclass
class ExpectedFinding:
    path: str
    line: int
    side: str
    priority: int
    concepts: list[str]
    min_concepts: int
    line_tolerance: int = 0


@dataclass
class Case:
    name: str
    url: str
    description: str
    expected_findings: list[ExpectedFinding]
    max_findings: int


def load_cases() -> list[Case]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases: list[Case] = []
    for item in data["cases"]:
        cases.append(
            Case(
                name=item["name"],
                url=item["url"],
                description=item["description"],
                expected_findings=[
                    ExpectedFinding(
                        path=f["path"],
                        line=f["line"],
                        side=f["side"],
                        priority=f["priority"],
                        concepts=[c.lower() for c in f["concepts"]],
                        min_concepts=f["min_concepts"],
                        line_tolerance=f.get("line_tolerance", 0),
                    )
                    for f in item["expected_findings"]
                ],
                max_findings=item.get("max_findings", 10),
            )
        )
    return cases


def run_review(url: str) -> dict[str, Any]:
    """Run review-bot --dry-run and return the final review payload."""
    cmd = [*CLI, url, "--dry-run"]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"review-bot exited {result.returncode}")

    marker = "dry-run: final review payload (not posted):\n"
    marker_index = result.stdout.find(marker)
    if marker_index == -1:
        print(result.stdout)
        raise RuntimeError("could not find dry-run payload marker in output")

    json_text = result.stdout[marker_index + len(marker) :]
    return json.loads(json_text)


def check_case(case: Case) -> list[str]:
    """Run a case and return a list of failure messages (empty if passed)."""
    payload = run_review(case.url)
    comments = payload.get("comments", [])
    failures: list[str] = []

    if len(comments) > case.max_findings:
        failures.append(
            f"too many findings: expected at most {case.max_findings}, got {len(comments)}"
        )

    for expected in case.expected_findings:
        matches = [
            c
            for c in comments
            if c.get("path") == expected.path
            and c.get("side") == expected.side
            and abs(c.get("line", 0) - expected.line) <= expected.line_tolerance
        ]
        if not matches:
            available = [f"{c.get('path')}:{c.get('side')}:{c.get('line')}" for c in comments]
            failures.append(
                f"missing expected finding near {expected.path}:{expected.side}:{expected.line} "
                f"(available: {available})"
            )
            continue

        body = matches[0].get("body", "").replace("`", "").lower()
        match_line = matches[0].get("line")
        found_concepts = [c for c in expected.concepts if c in body]
        if len(found_concepts) < expected.min_concepts:
            failures.append(
                f"finding at {expected.path}:{match_line} is missing expected concepts "
                f"(found {len(found_concepts)}/{expected.min_concepts}: {found_concepts})"
            )

    return failures


def main() -> int:
    cases = load_cases()
    overall_failures: list[tuple[str, list[str]]] = []

    for case in cases:
        print(f"\n=== Case: {case.name} ===")
        print(case.description)
        failures = check_case(case)
        if failures:
            overall_failures.append((case.name, failures))
            for f in failures:
                print(f"  FAIL: {f}")
        else:
            print("  PASS")

    print()
    if overall_failures:
        print("Eval regression FAILED")
        for name, failures in overall_failures:
            print(f"\n{name}:")
            for f in failures:
                print(f"  - {f}")
        return 1

    print(f"All {len(cases)} eval case(s) passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
