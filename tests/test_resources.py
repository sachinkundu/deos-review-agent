"""Tests for artifact placement and least-privilege invocation capsules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from review_bot.agents.registry import (
    AgentDefinition,
    AgentSkill,
    InputResource,
    RegistryError,
)
from review_bot.resources import (
    AGENT_CATALOG_NAME,
    INPUT_MANIFEST_NAME,
    RUN_MANIFEST_NAME,
    ResourceError,
    ResourceResolver,
    validate_workspace_isolation,
)


def _agent(
    package: Path,
    *,
    name: str = "reviewer",
    inputs: tuple[InputResource, ...] = (InputResource.PR_CONTEXT,),
    skills: tuple[AgentSkill, ...] = (),
) -> AgentDefinition:
    prompt = package / "prompt.md"
    prompt.write_text("Review it.")
    policy = package / "coordinator-policy.md"
    policy.write_text("Keep it.")
    return AgentDefinition(
        name=name,
        kind="reviewer",
        contract_version="review-bot/v1",
        description="Reviewer",
        package_dir=package,
        prompt=prompt,
        inputs=inputs,
        output_schema="review-result/v1",
        order=10,
        coordinator_policy=policy,
        skills=skills,
        package_digest=__import__(
            "review_bot.agents.registry", fromlist=["package_digest"]
        ).package_digest(package),
    )


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "workspace" / "source"
    artifacts = tmp_path / "workspace" / "host-artifacts"
    source.mkdir(parents=True)
    artifacts.mkdir()
    (source / "code.py").write_text("print('clean')\n")
    (artifacts / "shared-context.md").write_text("context")
    (artifacts / "review-diff.diff").write_text("filtered")
    (artifacts / "provider-diff.diff").write_text("complete")
    return source, artifacts


def test_capsule_contains_clean_source_and_only_assigned_resources(tmp_path: Path):
    source, artifacts = _workspace(tmp_path)
    package = tmp_path / "package"
    package.mkdir()
    agent = _agent(
        package,
        inputs=(InputResource.PR_CONTEXT, InputResource.REVIEW_DIFF),
    )
    resolver = ResourceResolver(source, artifacts)
    try:
        capsule = resolver.create_capsule(agent)
        assert capsule.repository.resolve() != source.resolve()
        assert (capsule.repository / "code.py").read_text() == "print('clean')\n"
        assert (capsule.root / "inputs" / "shared-context.md").read_text() == "context"
        assert (capsule.root / "inputs" / "review-diff.diff").read_text() == "filtered"
        assert not (capsule.root / "inputs" / "provider-diff.diff").exists()
        assert not (capsule.repository / "provider-diff.diff").exists()
        assert not (capsule.repository / ".." / "host-artifacts").exists()
        manifest = json.loads((capsule.root / INPUT_MANIFEST_NAME).read_text())
        assert [entry["resource"] for entry in manifest["inputs"]] == [
            "pr-context",
            "review-diff",
        ]
    finally:
        root = resolver._tmp_root
        resolver.close()
    assert not root.exists()


def test_safety_capsule_gets_provider_diff_not_filtered_diff(tmp_path: Path):
    source, artifacts = _workspace(tmp_path)
    package = tmp_path / "safety"
    package.mkdir()
    agent = _agent(
        package,
        name="safety",
        inputs=(InputResource.PR_CONTEXT, InputResource.PROVIDER_DIFF),
    )
    resolver = ResourceResolver(source, artifacts)
    try:
        capsule = resolver.create_capsule(agent)
        assert (capsule.root / "inputs" / "provider-diff.diff").read_text() == "complete"
        assert not (capsule.root / "inputs" / "review-diff.diff").exists()
    finally:
        resolver.close()


def test_missing_assigned_artifact_fails_before_launch(tmp_path: Path):
    source, artifacts = _workspace(tmp_path)
    package = tmp_path / "package"
    package.mkdir()
    agent = _agent(package, inputs=(InputResource.AGENT_CATALOG,))
    resolver = ResourceResolver(source, artifacts)
    try:
        with pytest.raises(ResourceError, match=AGENT_CATALOG_NAME):
            resolver.create_capsule(agent)
    finally:
        resolver.close()


def test_capsule_refuses_package_changed_after_discovery(tmp_path: Path):
    source, artifacts = _workspace(tmp_path)
    package = tmp_path / "package"
    package.mkdir()
    agent = _agent(package)
    (package / "prompt.md").write_text("mutated")
    resolver = ResourceResolver(source, artifacts)
    try:
        with pytest.raises(RegistryError, match="changed after discovery"):
            resolver.create_capsule(agent)
    finally:
        resolver.close()


def test_codex_skill_staging_includes_only_owning_agent_skills(tmp_path: Path):
    source, artifacts = _workspace(tmp_path)
    package = tmp_path / "package"
    package.mkdir()
    skill_dir = package / "skills" / "helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: helper\ndescription: Helps review code.\n---\nUse it.\n"
    )
    skill = AgentSkill(name="helper", skill_dir=skill_dir, digest="sha256:test")
    agent = _agent(package, skills=(skill,))
    resolver = ResourceResolver(source, artifacts)
    try:
        capsule = resolver.create_capsule(agent)
        staged = capsule.stage_codex_skills()
        assert [path.name for path in staged] == ["helper"]
        assert (staged[0] / "SKILL.md").is_file()
        assert not (capsule.root / ".agents" / "skills" / "ambient").exists()
    finally:
        resolver.close()


def test_workspace_isolation_rejects_nested_artifacts_and_source_collisions(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    nested = source / "host-artifacts"
    nested.mkdir()
    with pytest.raises(ResourceError, match="nested"):
        validate_workspace_isolation(source, nested)

    sibling = tmp_path / "host-artifacts"
    sibling.mkdir()
    (source / RUN_MANIFEST_NAME).write_text("untrusted collision")
    with pytest.raises(ResourceError, match="source root"):
        validate_workspace_isolation(source, sibling)
