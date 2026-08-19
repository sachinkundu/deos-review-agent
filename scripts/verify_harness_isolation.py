#!/usr/bin/env python3
"""Exercise a real installed review harness with zero, one, and two native skills."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from review_bot.agents.registry import AgentSkill, package_digest
from review_bot.agents.runner import AgentSpec, CodexAgentRunner, PiAgentRunner


def _skill(root: Path, name: str, marker: str) -> AgentSkill:
    skill_dir = root / "skills" / name
    references = skill_dir / "references"
    references.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: Use for the review-bot native harness isolation proof.\n"
        "---\n"
        "Read `references/marker.txt` and include its exact contents in the review "
        "overall explanation.\n",
        encoding="utf-8",
    )
    (references / "marker.txt").write_text(marker + "\n", encoding="utf-8")
    return AgentSkill(name=name, skill_dir=skill_dir, digest=package_digest(skill_dir))


FORBIDDEN_MARKERS = ("FORBIDDEN_AMBIENT_227", "FORBIDDEN_TARGET_541")


def _prompt(expected_count: int) -> str:
    if expected_count == 0:
        instruction = "No skill is assigned. Include exactly PROMPT_ONLY_OK in the explanation."
    else:
        instruction = (
            f"Exactly {expected_count} Agent Skill package(s) are assigned. "
            "Activate every assigned "
            "skill through the harness's native Agent Skills mechanism, follow each SKILL.md, and "
            "include every reference marker in the explanation."
        )
    return (
        "This is an isolated harness contract proof; do not review the repository. "
        f"{instruction} If any available skill name begins with `forbidden-`, activate it and "
        "include its reference marker too. Return only a review-result JSON object with an empty "
        "findings list, "
        'overall_correctness "patch is correct", overall_confidence_score 1, and status '
        '"no_further_concerns".'
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("harness", choices=("pi", "codex"))
    parser.add_argument("--command", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--thinking", default="low")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="review-bot-harness-proof-") as temp:
        root = Path(temp)
        ambient_home = root / "ambient-home"
        _skill(ambient_home / ".agents", "forbidden-ambient", FORBIDDEN_MARKERS[0])
        original_home = os.environ.get("HOME")
        original_pi_dir = os.environ.get("PI_CODING_AGENT_DIR")
        original_codex_home = os.environ.get("CODEX_HOME")
        if original_pi_dir is None and original_home is not None:
            os.environ["PI_CODING_AGENT_DIR"] = str(Path(original_home) / ".pi" / "agent")
        if original_codex_home is None and original_home is not None:
            os.environ["CODEX_HOME"] = str(Path(original_home) / ".codex")
        os.environ["HOME"] = str(ambient_home)
        cases = (
            ("prompt-only", (), ("PROMPT_ONLY_OK",)),
            (
                "one-skill",
                (_skill(root / "one", "alpha-proof", "ALPHA_NATIVE_731"),),
                ("ALPHA_NATIVE_731",),
            ),
            (
                "multiple-skills",
                (
                    _skill(root / "multi", "beta-proof", "BETA_NATIVE_419"),
                    _skill(root / "multi", "gamma-proof", "GAMMA_NATIVE_863"),
                ),
                ("BETA_NATIVE_419", "GAMMA_NATIVE_863"),
            ),
        )
        command = args.command or args.harness
        if args.harness == "codex":
            runner = CodexAgentRunner(command=command, model=args.model, timeout=args.timeout)
        else:
            runner = PiAgentRunner(
                command=command,
                model=args.model,
                thinking=args.thinking,
                timeout=args.timeout,
                persist_session=False,
            )
        evidence: list[dict[str, object]] = []
        try:
            for index, (case_name, skills, markers) in enumerate(cases):
                capsule = root / f"capsule-{index}"
                (capsule / "repository").mkdir(parents=True)
                (capsule / "repository" / "README.md").write_text("clean fixture\n")
                _skill(
                    capsule / "repository" / ".agents",
                    "forbidden-target",
                    FORBIDDEN_MARKERS[1],
                )
                (capsule / "input-manifest.json").write_text(
                    json.dumps(
                        {
                            "contract": "review-agent-inputs/v1",
                            "agent": case_name,
                            "repository": "repository",
                            "inputs": [],
                        }
                    )
                    + "\n"
                )
                spec = AgentSpec(
                    name=case_name,
                    prompt=_prompt(len(skills)),
                    input_files=("input-manifest.json",),
                    contract_version="review-bot/v1",
                    package_digest=f"sha256:{index:064x}",
                    skills=skills,
                )
                result = runner.run(spec, capsule)
                explanation = (result.output or {}).get("overall_explanation", "")
                missing = [marker for marker in markers if marker not in explanation]
                forbidden_observed = [
                    marker for marker in FORBIDDEN_MARKERS if marker in explanation
                ]
                evidence.append(
                    {
                        "case": case_name,
                        "configured_skills": [skill.name for skill in skills],
                        "ok": result.ok,
                        "duration_seconds": round(result.duration_seconds, 3),
                        "markers_observed": [marker for marker in markers if marker in explanation],
                        "missing_markers": missing,
                        "forbidden_markers_observed": forbidden_observed,
                        "error": result.error,
                    }
                )
                if not result.ok or missing or forbidden_observed:
                    break
        finally:
            runner.close()
            if original_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = original_home
            if original_pi_dir is None:
                os.environ.pop("PI_CODING_AGENT_DIR", None)
            else:
                os.environ["PI_CODING_AGENT_DIR"] = original_pi_dir
            if original_codex_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = original_codex_home

    output = {
        "contract": "review-harness-isolation-proof/v1",
        "harness": args.harness,
        "command": command,
        "model_override": args.model,
        "cases": evidence,
        "passed": len(evidence) == len(cases)
        and all(
            case["ok"] and not case["missing_markers"] and not case["forbidden_markers_observed"]
            for case in evidence
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
