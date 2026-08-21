"""Host artifact storage and least-privilege per-agent invocation capsules."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .agents.registry import (
    AgentDefinition,
    AgentRegistry,
    InputResource,
    catalog_document,
    run_manifest_document,
)
from .coordinator import RAW_FINDINGS_NAME
from .diff_filter import PROVIDER_DIFF_NAME, REVIEW_DIFF_NAME
from .history import HEAD_EVIDENCE_NAME, HISTORY_NAME, TARGETS_NAME
from .shared_context import SHARED_CONTEXT_NAME

RUN_MANIFEST_NAME = "run-manifest.json"
AGENT_CATALOG_NAME = "agent-catalog.json"
INPUT_MANIFEST_NAME = "input-manifest.json"

_RESOURCE_FILENAMES = {
    InputResource.PR_CONTEXT: SHARED_CONTEXT_NAME,
    InputResource.REVIEW_DIFF: REVIEW_DIFF_NAME,
    InputResource.PROVIDER_DIFF: PROVIDER_DIFF_NAME,
    InputResource.AGENT_CATALOG: AGENT_CATALOG_NAME,
    InputResource.RAW_FINDINGS: RAW_FINDINGS_NAME,
    InputResource.REVIEW_HISTORY: HISTORY_NAME,
    InputResource.RECHECK_HISTORY: "reviewer-history.json",
    InputResource.RECHECK_TARGETS: "assigned-targets.json",
    InputResource.CURRENT_HEAD_EVIDENCE: HEAD_EVIDENCE_NAME,
    InputResource.TARGET_CATALOG: TARGETS_NAME,
}


class ResourceError(RuntimeError):
    """A resource assignment or invocation capsule violated isolation."""


@dataclass(frozen=True)
class InvocationCapsule:
    agent: AgentDefinition
    root: Path
    repository: Path
    input_files: tuple[str, ...]

    def stage_codex_skills(self) -> tuple[Path, ...]:
        """Stage only this agent's skills in Codex's repository skill location."""
        if not self.agent.skills:
            return ()
        destination_root = self.root / ".agents" / "skills"
        destinations: list[Path] = []
        for skill in self.agent.skills:
            destination = destination_root / skill.name
            shutil.copytree(skill.skill_dir, destination)
            destinations.append(destination)
        return tuple(destinations)


class ResourceResolver:
    """Build isolated invocation views from validated symbolic resources."""

    def __init__(self, source_dir: Path, artifact_dir: Path):
        self.source_dir = Path(source_dir).resolve(strict=True)
        self.artifact_dir = Path(artifact_dir).resolve(strict=True)
        if self.source_dir == self.artifact_dir or self.artifact_dir.is_relative_to(
            self.source_dir
        ):
            raise ResourceError("host artifact directory must be outside the source checkout")
        self._tmp_root = Path(tempfile.mkdtemp(prefix="review-bot-invocations-"))
        self._capsules: dict[str, InvocationCapsule] = {}

    def close(self) -> None:
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def _artifact_for(self, resource: InputResource, agent: AgentDefinition) -> Path:
        if resource in {InputResource.RECHECK_HISTORY, InputResource.RECHECK_TARGETS}:
            path = self.artifact_dir / "recheck-inputs" / agent.name / _RESOURCE_FILENAMES[resource]
        else:
            path = self.artifact_dir / _RESOURCE_FILENAMES[resource]
        if not path.is_file():
            raise ResourceError(f"assigned resource {resource.value!r} does not exist: {path}")
        return path

    @staticmethod
    def _link_or_copy(source: str, destination: str) -> str:
        """Hard-link source files when possible, copying across filesystems."""
        try:
            os.link(source, destination)
            return destination
        except OSError:
            return shutil.copy2(source, destination)

    def create_capsule(self, agent: AgentDefinition) -> InvocationCapsule:
        if agent.name in self._capsules:
            raise ResourceError(f"invocation capsule already exists for agent {agent.name!r}")
        agent.verify_unchanged()
        root = self._tmp_root / agent.name
        inputs_dir = root / "inputs"
        inputs_dir.mkdir(parents=True)
        repository = root / "repository"
        shutil.copytree(
            self.source_dir,
            repository,
            symlinks=True,
            copy_function=self._link_or_copy,
        )

        assigned: list[dict[str, str]] = []
        input_files: list[str] = []
        for resource in agent.inputs:
            source = self._artifact_for(resource, agent)
            relative = Path("inputs") / source.name
            destination = root / relative
            shutil.copy2(source, destination)
            assigned.append({"resource": resource.value, "path": relative.as_posix()})
            input_files.append(relative.as_posix())

        manifest = {
            "contract": "review-agent-inputs/v1",
            "agent": agent.name,
            "contract_version": agent.contract_version,
            "package_digest": agent.package_digest,
            "repository": "repository",
            "inputs": assigned,
        }
        manifest_path = root / INPUT_MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        input_files.append(INPUT_MANIFEST_NAME)
        capsule = InvocationCapsule(
            agent=agent,
            root=root,
            repository=repository,
            input_files=tuple(input_files),
        )
        self._capsules[agent.name] = capsule
        return capsule


def validate_workspace_isolation(source_dir: Path, artifact_dir: Path) -> None:
    source = Path(source_dir).resolve(strict=True)
    artifacts = Path(artifact_dir).resolve(strict=True)
    if source == artifacts or artifacts.is_relative_to(source):
        raise ResourceError("host artifacts are nested inside the source checkout")
    forbidden = set(_RESOURCE_FILENAMES.values()) | {RUN_MANIFEST_NAME}
    present = sorted(name for name in forbidden if (source / name).exists())
    if present:
        raise ResourceError(f"host artifact names are present at source root: {present}")


def write_registry_artifacts(
    artifact_dir: Path, registry: AgentRegistry, harness: str
) -> tuple[Path, Path]:
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_manifest = artifact_dir / RUN_MANIFEST_NAME
    catalog = artifact_dir / AGENT_CATALOG_NAME
    run_manifest.write_text(
        json.dumps(run_manifest_document(registry, harness), indent=2) + "\n",
        encoding="utf-8",
    )
    catalog.write_text(json.dumps(catalog_document(registry), indent=2) + "\n", encoding="utf-8")
    return run_manifest, catalog


def write_recheck_resources(
    artifact_dir: Path,
    reviewer_views: dict[str, dict[str, object]],
    reviewer_targets: dict[str, list[dict[str, object]]],
    head_evidence: dict[str, object],
) -> None:
    """Persist host-owned recheck inputs and audit only identities/digests."""
    artifact_dir = Path(artifact_dir)
    (artifact_dir / HEAD_EVIDENCE_NAME).write_text(
        json.dumps(head_evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    manifest_path = artifact_dir / RUN_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assignments: list[dict[str, object]] = []
    for reviewer, view in reviewer_views.items():
        root = artifact_dir / "recheck-inputs" / reviewer
        root.mkdir(parents=True, exist_ok=True)
        target_document = {
            "contract": "review-assigned-targets/v1",
            "reviewer": reviewer,
            "targets": reviewer_targets.get(reviewer, []),
        }
        values = {
            "recheck-history": ("reviewer-history.json", view),
            "recheck-targets": ("assigned-targets.json", target_document),
        }
        resources: list[dict[str, object]] = []
        for symbolic_name, (filename, document) in values.items():
            encoded = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
            (root / filename).write_text(encoded, encoding="utf-8")
            resources.append(
                {
                    "symbolic_name": symbolic_name,
                    "schema_version": document.get("contract"),
                    "digest": "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                    "target_identities": [
                        target["finding_id"] for target in reviewer_targets.get(reviewer, [])
                    ],
                }
            )
        assignments.append({"agent": reviewer, "resources": resources})
    manifest["recheck_resources"] = assignments
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
