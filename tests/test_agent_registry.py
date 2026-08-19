"""Deterministic validation for trusted registered agent packages."""

from __future__ import annotations

from pathlib import Path

import pytest

from review_bot.agents.registry import (
    BUILTIN_AGENT_ROOT,
    InputResource,
    RegistryError,
    catalog_document,
    discover_agent_registry,
    load_agent_package,
    package_digest,
    run_manifest_document,
)


def _write_package(
    root: Path,
    name: str,
    *,
    kind: str = "reviewer",
    inputs: tuple[str, ...] = ("pr-context", "review-diff"),
    order: int = 10,
) -> Path:
    package = root / name
    package.mkdir(parents=True)
    policy = "coordinator_policy: coordinator-policy.md\n" if kind == "reviewer" else ""
    (package / "agent.yaml").write_text(
        "version: review-bot/v1\n"
        f"name: {name}\n"
        f"kind: {kind}\n"
        f"description: Review role {name}.\n"
        "prompt: prompt.md\n"
        "inputs:\n"
        + "".join(f"  - {value}\n" for value in inputs)
        + "output_schema: review-result/v1\n"
        + f"order: {order}\n"
        + policy,
        encoding="utf-8",
    )
    (package / "prompt.md").write_text(f"# {name}\n", encoding="utf-8")
    if kind == "reviewer":
        (package / "coordinator-policy.md").write_text("Keep real findings.\n")
    return package


def _valid_root(tmp_path: Path) -> Path:
    root = tmp_path / "agents"
    _write_package(root, "reviewer", order=20)
    _write_package(
        root,
        "coordinator",
        kind="coordinator",
        inputs=("pr-context", "agent-catalog", "raw-findings", "provider-diff"),
        order=100,
    )
    return root


def test_builtin_registry_preserves_expected_coverage_and_inputs():
    registry = discover_agent_registry()
    assert [agent.name for agent in registry.reviewers] == [
        "correctness",
        "api-reality",
        "tests",
        "safety",
    ]
    assert registry.coordinator.name == "coordinator"
    assert registry.reviewers[0].inputs == (
        InputResource.PR_CONTEXT,
        InputResource.REVIEW_DIFF,
    )
    assert registry.reviewers[-1].inputs == (
        InputResource.PR_CONTEXT,
        InputResource.PROVIDER_DIFF,
    )
    assert "Shared rules" in registry.reviewers[0].prompt_text()
    assert "fixed reviewer roster" in registry.coordinator.prompt_text()


def test_registry_ignores_nested_and_non_manifest_directories(tmp_path: Path):
    root = _valid_root(tmp_path)
    nested = root / "group" / "hidden"
    nested.mkdir(parents=True)
    (nested / "agent.yaml").write_text("not: loaded\n")
    (root / "notes").mkdir()
    registry = discover_agent_registry(root)
    assert [agent.name for agent in registry.all_agents] == ["reviewer", "coordinator"]


@pytest.mark.parametrize(
    ("replacement", "match"),
    [
        ("version: made-up/v2", "unsupported agent contract"),
        ("name: another", "must match parent"),
        ("  - review-diff\noutput_schema", "must not contain duplicates"),
        ("  - arbitrary-file\noutput_schema", "unsupported symbolic input"),
    ],
)
def test_manifest_validation_fails_closed(tmp_path: Path, replacement: str, match: str):
    package = _write_package(tmp_path, "reviewer")
    text = (package / "agent.yaml").read_text()
    if replacement.startswith("version"):
        text = text.replace("version: review-bot/v1", replacement)
    elif replacement.startswith("name"):
        text = text.replace("name: reviewer", replacement)
    else:
        text = text.replace("output_schema", replacement)
    (package / "agent.yaml").write_text(text)
    with pytest.raises(RegistryError, match=match):
        load_agent_package(package)


def test_declared_path_escape_is_rejected(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    package = _write_package(tmp_path, "reviewer")
    (package / "agent.yaml").write_text(
        (package / "agent.yaml").read_text().replace("prompt: prompt.md", "prompt: ../outside.md")
    )
    with pytest.raises(RegistryError, match="escapes"):
        load_agent_package(package)


def test_symlink_escape_anywhere_in_package_is_rejected(tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    package = _write_package(tmp_path, "reviewer")
    (package / "leak.txt").symlink_to(outside)
    with pytest.raises(RegistryError, match="escapes"):
        load_agent_package(package)


def test_agent_skill_standard_and_deterministic_order(tmp_path: Path):
    package = _write_package(tmp_path, "reviewer")
    for name in ("zeta", "alpha"):
        skill = package / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Use {name} for focused review work.\n---\nDo it.\n"
        )
    agent = load_agent_package(package)
    assert [skill.name for skill in agent.skills] == ["alpha", "zeta"]


def test_invalid_agent_skill_reports_owner_and_path(tmp_path: Path):
    package = _write_package(tmp_path, "reviewer")
    skill = package / "skills" / "Bad"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: Bad\ndescription: invalid\n---\n")
    with pytest.raises(RegistryError, match=r"reviewer: invalid Agent Skill.*Bad"):
        load_agent_package(package)


def test_package_digest_changes_for_prompt_policy_and_skill_resource(tmp_path: Path):
    package = _write_package(tmp_path, "reviewer")
    skill = package / "skills" / "helper"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: helper\ndescription: Helps when reviewing.\n---\nRead the reference.\n"
    )
    reference = skill / "references" / "guide.md"
    reference.write_text("one")
    initial = package_digest(package)
    reference.write_text("two")
    assert package_digest(package) != initial


def test_verify_unchanged_detects_post_discovery_mutation(tmp_path: Path):
    package = _write_package(tmp_path, "reviewer")
    agent = load_agent_package(package)
    (package / "prompt.md").write_text("changed")
    with pytest.raises(RegistryError, match="changed after discovery"):
        agent.verify_unchanged()


def test_duplicate_names_across_trusted_roots_are_rejected(tmp_path: Path):
    first = _valid_root(tmp_path / "first")
    second = tmp_path / "second" / "agents"
    _write_package(second, "reviewer")
    with pytest.raises(RegistryError, match="duplicate registered agent"):
        discover_agent_registry((first, second))


@pytest.mark.parametrize("coordinator_count", [0, 2])
def test_coordinator_cardinality_is_strict(tmp_path: Path, coordinator_count: int):
    root = tmp_path / "agents"
    _write_package(root, "reviewer")
    for index in range(coordinator_count):
        _write_package(
            root,
            f"coordinator-{index}",
            kind="coordinator",
            inputs=("pr-context", "agent-catalog", "raw-findings", "provider-diff"),
        )
    with pytest.raises(RegistryError, match="exactly one coordinator"):
        discover_agent_registry(root)


def test_no_reviewers_is_rejected(tmp_path: Path):
    root = tmp_path / "agents"
    _write_package(
        root,
        "coordinator",
        kind="coordinator",
        inputs=("pr-context", "agent-catalog", "raw-findings", "provider-diff"),
    )
    with pytest.raises(RegistryError, match="no trusted reviewer"):
        discover_agent_registry(root)


def test_catalog_and_run_manifest_are_identity_bearing_and_deterministic():
    registry = discover_agent_registry(BUILTIN_AGENT_ROOT)
    catalog = catalog_document(registry)
    manifest = run_manifest_document(registry, "pi")
    assert catalog == catalog_document(registry)
    assert manifest == run_manifest_document(registry, "pi")
    catalog_agents = catalog["agents"]
    manifest_agents = manifest["agents"]
    assert isinstance(catalog_agents, list)
    assert isinstance(manifest_agents, list)
    first = catalog_agents[0]
    assert isinstance(first, dict)
    assert first["contract_version"] == "review-bot/v1"
    assert str(first["package_digest"]).startswith("sha256:")
    assert manifest_agents[-1]["kind"] == "coordinator"
    assert all("skill_dir" not in entry for entry in manifest_agents)
