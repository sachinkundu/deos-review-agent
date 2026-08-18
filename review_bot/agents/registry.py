"""Trusted discovery and validation for self-contained review-agent packages."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from skills_ref import read_properties as read_skill_properties
from skills_ref import validate as validate_skill

AGENT_CONTRACT_VERSION = "review-bot/v1"
REVIEW_OUTPUT_SCHEMA = "review-result/v1"
BUILTIN_AGENT_ROOT = Path(__file__).parent / "builtin"


class RegistryError(RuntimeError):
    """A trusted agent package is invalid and no agent may be launched."""


class InputResource(StrEnum):
    PR_CONTEXT = "pr-context"
    REVIEW_DIFF = "review-diff"
    PROVIDER_DIFF = "provider-diff"
    AGENT_CATALOG = "agent-catalog"
    RAW_FINDINGS = "raw-findings"


@dataclass(frozen=True)
class AgentSkill:
    name: str
    skill_dir: Path
    digest: str


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    kind: Literal["reviewer", "coordinator"]
    contract_version: str
    description: str
    package_dir: Path
    prompt: Path
    inputs: tuple[InputResource, ...]
    output_schema: str
    order: int
    coordinator_policy: Path | None
    skills: tuple[AgentSkill, ...]
    package_digest: str

    def prompt_text(self) -> str:
        text = self.prompt.read_text(encoding="utf-8")
        marker = "{{shared_rules}}"
        if marker not in text:
            return text
        shared = _declared_file(self.package_dir, "shared-rules.md", "shared_rules")
        return text.replace(marker, shared.read_text(encoding="utf-8"))

    def verify_unchanged(self) -> None:
        current = package_digest(self.package_dir)
        if current != self.package_digest:
            raise RegistryError(
                f"agent package {self.name!r} changed after discovery: "
                f"expected {self.package_digest}, found {current}"
            )


@dataclass(frozen=True)
class AgentRegistry:
    reviewers: tuple[AgentDefinition, ...]
    coordinator: AgentDefinition

    @property
    def all_agents(self) -> tuple[AgentDefinition, ...]:
        return (*self.reviewers, self.coordinator)


_MANIFEST_FIELDS = {
    "version",
    "name",
    "kind",
    "description",
    "prompt",
    "inputs",
    "output_schema",
    "order",
    "coordinator_policy",
}


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _package_files(package_dir: Path) -> tuple[tuple[str, Path], ...]:
    """Return every logical package file after containment and cycle checks."""
    root = package_dir.resolve(strict=True)
    files: list[tuple[str, Path]] = []

    def walk(directory: Path, resolved_stack: tuple[Path, ...]) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise RegistryError(f"cannot read agent package directory {directory}: {exc}") from exc
        for entry in entries:
            try:
                resolved = entry.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise RegistryError(f"cannot resolve agent package entry {entry}: {exc}") from exc
            if not _contained(resolved, root):
                raise RegistryError(
                    f"agent package entry escapes its package: {entry} -> {resolved}"
                )
            if entry.is_dir():
                if resolved in resolved_stack:
                    raise RegistryError(
                        f"agent package contains a directory symlink cycle: {entry}"
                    )
                walk(entry, (*resolved_stack, resolved))
            elif entry.is_file():
                if not os.access(resolved, os.R_OK):
                    raise RegistryError(f"agent package file is not readable: {entry}")
                files.append((entry.relative_to(package_dir).as_posix(), entry))
            else:
                raise RegistryError(
                    f"agent package entry is not a regular file or directory: {entry}"
                )

    walk(package_dir, (root,))
    return tuple(sorted(files, key=lambda item: item[0]))


def package_digest(package_dir: Path) -> str:
    """Hash logical paths and bytes for every contained package file."""
    digest = hashlib.sha256()
    for relative, path in _package_files(package_dir):
        path_bytes = relative.encode("utf-8")
        content = path.read_bytes()
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _declared_file(package_dir: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise RegistryError(f"{package_dir.name}: {field} must be a non-empty relative path")
    path = package_dir / value
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RegistryError(f"{package_dir.name}: cannot resolve {field} {value!r}: {exc}") from exc
    root = package_dir.resolve(strict=True)
    if not _contained(resolved, root):
        raise RegistryError(f"{package_dir.name}: {field} escapes its agent package: {value!r}")
    if not path.is_file() or not os.access(resolved, os.R_OK):
        raise RegistryError(
            f"{package_dir.name}: {field} is not a readable regular file: {value!r}"
        )
    return path


def _skills(
    package_dir: Path, package_files: tuple[tuple[str, Path], ...]
) -> tuple[AgentSkill, ...]:
    skill_dirs = {
        path.parent
        for relative, path in package_files
        if relative.startswith("skills/") and Path(relative).name == "SKILL.md"
    }
    skills: list[AgentSkill] = []
    names: set[str] = set()
    for skill_dir in sorted(skill_dirs, key=lambda path: path.as_posix()):
        errors = validate_skill(skill_dir)
        if errors:
            joined = "; ".join(errors)
            raise RegistryError(f"{package_dir.name}: invalid Agent Skill at {skill_dir}: {joined}")
        try:
            properties = read_skill_properties(skill_dir)
        except Exception as exc:
            raise RegistryError(
                f"{package_dir.name}: cannot read Agent Skill at {skill_dir}: {exc}"
            ) from exc
        if properties.name in names:
            raise RegistryError(
                f"{package_dir.name}: duplicate Agent Skill name {properties.name!r}"
            )
        names.add(properties.name)
        skills.append(
            AgentSkill(
                name=properties.name,
                skill_dir=skill_dir,
                digest=package_digest(skill_dir),
            )
        )
    return tuple(sorted(skills, key=lambda skill: skill.name))


def _load_manifest(package_dir: Path) -> dict[str, object]:
    manifest_path = package_dir / "agent.yaml"
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RegistryError(f"{package_dir.name}: cannot parse agent.yaml: {exc}") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise RegistryError(f"{package_dir.name}: agent.yaml must contain a mapping")
    unknown = sorted(set(raw) - _MANIFEST_FIELDS)
    if unknown:
        raise RegistryError(f"{package_dir.name}: unsupported agent.yaml fields: {unknown}")
    return raw


def load_agent_package(package_dir: Path) -> AgentDefinition:
    package_dir = Path(package_dir)
    manifest = _load_manifest(package_dir)
    required = _MANIFEST_FIELDS - {"coordinator_policy"}
    missing = sorted(required - set(manifest))
    if missing:
        raise RegistryError(f"{package_dir.name}: missing agent.yaml fields: {missing}")

    version = manifest["version"]
    if not isinstance(version, str) or version != AGENT_CONTRACT_VERSION:
        raise RegistryError(f"{package_dir.name}: unsupported agent contract version {version!r}")
    name = manifest["name"]
    if not isinstance(name, str) or name != package_dir.name:
        raise RegistryError(
            f"{package_dir.name}: manifest name must match parent directory, found {name!r}"
        )
    kind = manifest["kind"]
    if kind not in ("reviewer", "coordinator"):
        raise RegistryError(f"{name}: kind must be 'reviewer' or 'coordinator'")
    description = manifest["description"]
    if not isinstance(description, str) or not description.strip():
        raise RegistryError(f"{name}: description must be a non-empty string")
    output_schema = manifest["output_schema"]
    if not isinstance(output_schema, str) or output_schema != REVIEW_OUTPUT_SCHEMA:
        raise RegistryError(f"{name}: unsupported output schema {output_schema!r}")
    order = manifest["order"]
    if not isinstance(order, int) or isinstance(order, bool):
        raise RegistryError(f"{name}: order must be an integer")

    raw_inputs = manifest["inputs"]
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise RegistryError(f"{name}: inputs must be a non-empty list")
    try:
        inputs = tuple(InputResource(value) for value in raw_inputs)
    except (TypeError, ValueError) as exc:
        raise RegistryError(f"{name}: unsupported symbolic input in {raw_inputs!r}") from exc
    if len(inputs) != len(set(inputs)):
        raise RegistryError(f"{name}: symbolic inputs must not contain duplicates")

    prompt = _declared_file(package_dir, manifest["prompt"], "prompt")
    policy_value = manifest.get("coordinator_policy")
    if kind == "reviewer":
        if policy_value is None:
            raise RegistryError(f"{name}: reviewer must declare coordinator_policy")
        coordinator_policy = _declared_file(package_dir, policy_value, "coordinator_policy")
    else:
        if policy_value is not None:
            raise RegistryError(f"{name}: coordinator must not declare coordinator_policy")
        coordinator_policy = None

    package_files = _package_files(package_dir)
    skills = _skills(package_dir, package_files)
    return AgentDefinition(
        name=name,
        kind=kind,
        contract_version=version,
        description=description.strip(),
        package_dir=package_dir,
        prompt=prompt,
        inputs=inputs,
        output_schema=output_schema,
        order=order,
        coordinator_policy=coordinator_policy,
        skills=skills,
        package_digest=package_digest(package_dir),
    )


def discover_agent_registry(
    root: Path | Sequence[Path] = BUILTIN_AGENT_ROOT,
) -> AgentRegistry:
    """Discover direct child packages under application-owned registry roots."""
    roots = (Path(root),) if isinstance(root, (str, Path)) else tuple(map(Path, root))
    manifests: list[Path] = []
    for registry_root in roots:
        if not registry_root.is_dir():
            raise RegistryError(f"trusted agent registry root does not exist: {registry_root}")
        manifests.extend(registry_root.glob("*/agent.yaml"))
    manifests.sort(key=lambda path: (path.parent.name, path.as_posix()))
    agents = [load_agent_package(path.parent) for path in manifests]

    by_name: dict[str, AgentDefinition] = {}
    duplicates: list[str] = []
    for agent in agents:
        if agent.name in by_name:
            duplicates.append(agent.name)
        by_name[agent.name] = agent
    if duplicates:
        raise RegistryError(f"duplicate registered agent names: {sorted(set(duplicates))}")

    reviewers = tuple(
        sorted(
            (agent for agent in agents if agent.kind == "reviewer"),
            key=lambda agent: (agent.order, agent.name),
        )
    )
    coordinators = tuple(agent for agent in agents if agent.kind == "coordinator")
    if not reviewers:
        raise RegistryError("no trusted reviewer agents are available")
    if len(coordinators) != 1:
        paths = [str(agent.package_dir) for agent in coordinators]
        raise RegistryError(
            f"trusted registry requires exactly one coordinator, found {len(coordinators)}: {paths}"
        )
    return AgentRegistry(reviewers=reviewers, coordinator=coordinators[0])


def catalog_document(registry: AgentRegistry) -> dict[str, object]:
    agents: list[dict[str, object]] = []
    for agent in registry.reviewers:
        if agent.coordinator_policy is None:  # pragma: no cover - enforced by registry
            raise RegistryError(f"reviewer {agent.name!r} has no coordinator policy")
        agents.append(
            {
                "name": agent.name,
                "contract_version": agent.contract_version,
                "package_digest": agent.package_digest,
                "description": agent.description,
                "skills": [skill.name for skill in agent.skills],
                "status": "selected",
                "coordinator_policy": agent.coordinator_policy.read_text(encoding="utf-8").strip(),
            }
        )
    return {"contract": "review-agent-catalog/v1", "agents": agents}


def run_manifest_document(registry: AgentRegistry, harness: str) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for agent in registry.all_agents:
        entries.append(
            {
                "name": agent.name,
                "kind": agent.kind,
                "contract_version": agent.contract_version,
                "order": agent.order,
                "inputs": [value.value for value in agent.inputs],
                "package_digest": agent.package_digest,
                "skills": [skill.name for skill in agent.skills],
                "status": "selected",
                "harness": harness,
            }
        )
    return {"contract": "review-run-manifest/v1", "agents": entries}
