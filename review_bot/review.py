"""review_bot CLI entrypoint: wires the Phase 2 review pipeline.

Usage:
    review-bot <PR_URL> [--dry-run] [--keep-workspace] [--no-agent-session] [options]
    review-bot cleanup <PR_URL>

Flow: load credentials -> mint installation token (one per run) -> fetch PR
metadata + diff -> skip bot-authored PRs -> clone/checkout/bootstrap the
workspace -> build full/filtered diff artifacts and shared context -> run the
correctness, API-reality, tests, and safety agents concurrently -> coordinator
-> schema validation -> full-diff line validation -> head-SHA freshness
re-check -> post the review (or dry-run) -> session cleanup.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .agents.registry import RegistryError, discover_agent_registry
from .agents.runner import (
    DEFAULT_AGENT_TIMEOUT,
    DEFAULT_MAX_CONCURRENCY,
    AgentRunner,
    AgentSpec,
    CodexAgentRunner,
    HarnessError,
    PiAgentRunner,
    run_agents_concurrently,
    verify_harness_command,
)
from .coordinator import (
    CoordinatorError,
    run_coordinator,
    validate_result_identities,
    write_raw_findings,
)
from .diff_filter import (
    DiffFilterError,
    write_diff_artifacts,
)
from .diff_validator import parse_unified_diff, validate_findings_locations
from .github import (
    Credentials,
    CredentialsError,
    GitHubAppClient,
    GitHubError,
    build_inline_comments,
    event_for_findings,
    parse_pr_url,
)
from .resources import (
    ResourceError,
    ResourceResolver,
    validate_workspace_isolation,
    write_registry_artifacts,
)
from .schema import SchemaError, validate_review_output
from .shared_context import write_shared_context
from .workspace import DEFAULT_BOOTSTRAP_TIMEOUT, PRWorkspace, WorkspaceError

DEFAULT_WORKSPACE_ROOT = Path.home() / "review-bot-workspaces"
UNPOSTED_REVIEW_NAME = "unposted-review.json"

# Exit codes: 0 ok/skip, 1 usage/credentials, 2 workspace, 3 all agents failed,
# 4 coordinator failed, 5 stale head, 6 GitHub API error, 7 schema error.


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from .env without overriding existing variables."""
    path = path or Path(os.environ.get("REVIEW_ENV_FILE", ".env"))
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def build_credentials() -> Credentials:
    """Read GitHub App credentials from the environment; fail fast if missing."""
    load_dotenv()
    missing = [
        name
        for name in ("GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY")
        if not os.environ.get(name)
    ]
    if missing:
        raise CredentialsError(
            "missing required environment variables: " + ", ".join(missing) + " (see .env.example)"
        )
    key_path = os.environ["GITHUB_APP_PRIVATE_KEY"]
    if not Path(key_path).is_file():
        raise CredentialsError(f"GITHUB_APP_PRIVATE_KEY does not point to a file: {key_path!r}")

    bot_username = os.environ.get("GITHUB_APP_BOT_USERNAME")
    if not bot_username:
        slug = os.environ.get("GITHUB_APP_SLUG")
        if slug:
            bot_username = f"{slug}[bot]"
    return Credentials(
        app_id=os.environ["GITHUB_APP_ID"],
        installation_id=os.environ["GITHUB_APP_INSTALLATION_ID"],
        private_key_path=key_path,
        bot_username=bot_username,
    )


def build_review_body(
    review: dict,
    agent_failures: list,
    unattachable: list[tuple[dict, str]],
    finding_count: int,
) -> str:
    """Assemble the review summary body (pass note, failures, unattached)."""
    lines: list[str] = ["## review-bot — automated correctness review", ""]
    lines.append(review["overall_explanation"])
    lines.append("")
    verdict = review["overall_correctness"]
    confidence = review["overall_confidence_score"]
    if finding_count == 0:
        lines.append("**Result:** No correctness, API-reality, tests, or safety issues found. ✔")
    else:
        critical = sum(1 for f in review["findings"] if f.get("priority") == 2)
        parts = [f"{finding_count} finding(s)"]
        if critical:
            parts.append(f"{critical} critical")
        lines.append(f"**Result:** {verdict} (confidence {confidence}) — {'; '.join(parts)}.")
    lines.append("")

    if agent_failures:
        lines.append("### Review agent failures")
        for failure in agent_failures:
            lines.append(f"- The `{failure.name}` agent did not complete: {failure.error}")
        lines.append("")

    if unattachable:
        lines.append("### Findings that could not be attached to a diff line")
        lines.append("")
        for finding, reason in unattachable:
            location = finding["code_location"]
            line_range = location["line_range"]
            lines.append(f"#### {finding['title']}")
            lines.append(
                f"`{location['absolute_file_path']}:{line_range['start']}-{line_range['end']}` "
                f"(not attachable: {reason})"
            )
            lines.append("")
            lines.append(finding["body"])
            fix = finding.get("suggested_fix") or {}
            if fix.get("description"):
                lines.append("")
                lines.append(f"**Suggested fix:** {fix['description']}")
                if fix.get("replacement"):
                    lines.append("")
                    lines.append(f"```\n{fix['replacement']}\n```")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


class RunOptions:
    def __init__(self, args: argparse.Namespace):
        self.dry_run: bool = args.dry_run
        self.keep_workspace: bool = args.keep_workspace
        self.workspace_root: Path = Path(
            args.workspace_root or os.environ.get("REVIEW_WORKSPACE_ROOT") or DEFAULT_WORKSPACE_ROOT
        )
        self.agent_timeout: int = int(
            args.agent_timeout
            or os.environ.get("REVIEW_AGENT_TIMEOUT_SECONDS")
            or DEFAULT_AGENT_TIMEOUT
        )
        self.bootstrap_timeout: int = int(
            args.bootstrap_timeout
            or os.environ.get("REVIEW_BOOTSTRAP_TIMEOUT_SECONDS")
            or DEFAULT_BOOTSTRAP_TIMEOUT
        )
        self.model: str | None = args.model or os.environ.get("REVIEW_AGENT_MODEL") or None
        self.agent_command: str = (
            args.agent_command or os.environ.get("REVIEW_AGENT_COMMAND") or "pi"
        )
        self.agent_thinking: str | None = (
            args.agent_thinking or os.environ.get("REVIEW_AGENT_THINKING") or "high"
        )
        self.persist_agent_session: bool = not args.no_agent_session
        self.max_agent_concurrency: int = int(
            args.max_agent_concurrency
            or os.environ.get("REVIEW_MAX_AGENT_CONCURRENCY")
            or DEFAULT_MAX_CONCURRENCY
        )


def build_agent_runner(
    command: str,
    model: str | None,
    thinking: str | None,
    timeout: int,
    persist_session: bool = True,
) -> AgentRunner:
    """Construct the agent runner for ``command``."""
    harness = Path(command).name
    verify_harness_command(command, harness)
    if harness == "codex":
        return CodexAgentRunner(command=command, model=model, timeout=timeout)
    if harness == "pi":
        return PiAgentRunner(
            command=command,
            model=model,
            thinking=thinking,
            timeout=timeout,
            persist_session=persist_session,
        )
    raise HarnessError(f"unsupported review harness command: {command!r}")


def run_review(
    argv: list[str],
    client_factory: Callable[[Credentials], GitHubAppClient] = GitHubAppClient,
    runner_factory: Callable[..., AgentRunner] = build_agent_runner,
    workspace_factory: Callable[..., PRWorkspace] = PRWorkspace,
    diff_artifact_writer: Callable[..., object] = write_diff_artifacts,
) -> int:
    parser = argparse.ArgumentParser(prog="review-bot", description="Review a GitHub PR (Phase 2).")
    parser.add_argument("--version", action="version", version=f"review-bot {__version__}")
    parser.add_argument("pr_url", help="GitHub pull request URL")
    parser.add_argument(
        "--dry-run", action="store_true", help="run the full pipeline but do not post the review"
    )
    parser.add_argument(
        "--keep-workspace", action="store_true", help="retain the PR workspace after the run"
    )
    parser.add_argument(
        "--no-agent-session",
        action="store_true",
        help="do not persist Pi agent session transcripts",
    )
    parser.add_argument(
        "--workspace-root", default=None, help=f"workspace root (default {DEFAULT_WORKSPACE_ROOT})"
    )
    parser.add_argument("--agent-timeout", type=int, default=None, help="agent timeout in seconds")
    parser.add_argument(
        "--bootstrap-timeout", type=int, default=None, help="bootstrap timeout in seconds"
    )
    parser.add_argument("--model", default=None, help="model override for the agent driver")
    parser.add_argument(
        "--agent-thinking",
        default=None,
        help="thinking level for pi driver (off/minimal/low/medium/high/xhigh/max)",
    )
    parser.add_argument("--agent-command", default=None, help="agent CLI command (default: pi)")
    parser.add_argument(
        "--max-agent-concurrency",
        type=int,
        default=None,
        help=f"maximum concurrent reviewers (default: {DEFAULT_MAX_CONCURRENCY})",
    )
    args = parser.parse_args(argv)

    try:
        owner, repo, number = parse_pr_url(args.pr_url)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        registry = discover_agent_registry()
    except RegistryError as e:
        print(f"error: agent registry invalid: {e}", file=sys.stderr)
        return 1

    try:
        creds = build_credentials()
    except CredentialsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    client = client_factory(creds)
    opts = RunOptions(args)
    if opts.max_agent_concurrency < 1:
        print("error: max agent concurrency must be at least 1", file=sys.stderr)
        return 1
    workspace = workspace_factory(
        opts.workspace_root, owner, repo, number, bootstrap_timeout=opts.bootstrap_timeout
    )

    try:
        # Fail fast on bad credentials before any repository operation.
        client.mint_app_jwt()
        token = client.mint_installation_token(f"{owner}/{repo}")
    except (CredentialsError, GitHubError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        pr = client.fetch_pr(owner, repo, number, token)
    except GitHubError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    bot_username = creds.bot_username or client.bot_username()
    if pr.sender_login == bot_username:
        print(
            f"skip: PR {pr.number} was opened by the bot ({bot_username}); "
            "not reviewing our own PRs."
        )
        return 0

    try:
        diff_text = client.fetch_pr_diff(owner, repo, number, token)
    except GitHubError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        workspace.setup(pr.head_repo_clone_url, pr.head_sha, pr.head_ref, token)
    except WorkspaceError as e:
        print(f"error: workspace setup failed: {e}", file=sys.stderr)
        return 2

    try:
        bootstrap = workspace.run_bootstrap(
            workspace.source_dir,
            extra_env={
                "REVIEW_PR_URL": args.pr_url,
                "REVIEW_HEAD_SHA": pr.head_sha,
                "REVIEW_PR_NUMBER": str(number),
            },
        )
        if not bootstrap.ok:
            print(f"error: bootstrap failed: {bootstrap.summary}", file=sys.stderr)
            return 2

        try:
            if diff_artifact_writer is write_diff_artifacts:
                diff_artifact_writer(
                    workspace.artifact_dir,
                    diff_text,
                    repository=workspace.source_dir,
                )
            else:
                diff_artifact_writer(workspace.artifact_dir, diff_text)
        except DiffFilterError as e:
            print(f"error: diff artifact construction failed: {e}", file=sys.stderr)
            return 2
        write_shared_context(workspace.artifact_dir, pr, bootstrap)

        try:
            validate_workspace_isolation(workspace.source_dir, workspace.artifact_dir)
            runner = runner_factory(
                command=opts.agent_command,
                model=opts.model,
                thinking=opts.agent_thinking,
                timeout=opts.agent_timeout,
                persist_session=opts.persist_agent_session,
            )
        except (HarnessError, ResourceError) as e:
            print(f"error: review harness setup failed: {e}", file=sys.stderr)
            return 2

        harness = Path(opts.agent_command).name
        resolver = ResourceResolver(workspace.source_dir, workspace.artifact_dir)
        try:
            write_registry_artifacts(workspace.artifact_dir, registry, harness)
            invocations: list[tuple[AgentSpec, Path]] = []
            for agent in registry.reviewers:
                capsule = resolver.create_capsule(agent)
                invocations.append(
                    (
                        AgentSpec(
                            name=agent.name,
                            prompt=agent.prompt_text(),
                            input_files=capsule.input_files,
                            contract_version=agent.contract_version,
                            package_digest=agent.package_digest,
                            skills=agent.skills,
                            package_dir=agent.package_dir,
                        ),
                        capsule.root,
                    )
                )
            agent_results = run_agents_concurrently(
                runner,
                invocations,
                max_concurrency=opts.max_agent_concurrency,
            )

            try:
                validate_result_identities(registry, agent_results)
            except CoordinatorError as e:
                print(f"error: {e}", file=sys.stderr)
                return 4

            failures = [r for r in agent_results if not r.ok]
            successful = [r for r in agent_results if r.ok]
            for failure in failures:
                print(f"warning: agent {failure.name} {failure.summary}", file=sys.stderr)
            if not successful:
                print(
                    "error: all review agents failed; nothing to review, no review posted.",
                    file=sys.stderr,
                )
                return 3

            write_raw_findings(workspace.artifact_dir, agent_results)
            try:
                coordinator = registry.coordinator
                capsule = resolver.create_capsule(coordinator)
                spec = AgentSpec(
                    name=coordinator.name,
                    prompt=coordinator.prompt_text(),
                    input_files=capsule.input_files,
                    contract_version=coordinator.contract_version,
                    package_digest=coordinator.package_digest,
                    skills=coordinator.skills,
                    package_dir=coordinator.package_dir,
                )
                review = run_coordinator(runner, spec, capsule.root)
            except (CoordinatorError, HarnessError, ResourceError, RegistryError) as e:
                print(f"error: {e}", file=sys.stderr)
                return 4
        except (HarnessError, ResourceError, RegistryError) as e:
            print(f"error: isolated agent invocation failed: {e}", file=sys.stderr)
            return 2
        finally:
            resolver.close()
            if hasattr(runner, "close"):
                runner.close()

        # Final payload validation before any GitHub POST.
        try:
            validate_review_output(review)
        except SchemaError as e:
            print(f"error: {e}", file=sys.stderr)
            return 7

        outcome = validate_findings_locations(review["findings"], parse_unified_diff(diff_text))

        # Re-check the head SHA so we never post against a stale head.
        try:
            fresh = client.fetch_pr(owner, repo, number, token)
        except GitHubError as e:
            print(f"error: head re-check failed: {e}", file=sys.stderr)
            return 6
        if fresh.head_sha != pr.head_sha:
            print(
                f"error: PR head changed from {pr.head_sha} to {fresh.head_sha} before posting; "
                "refuse to post against a stale head. Re-run the review.",
                file=sys.stderr,
            )
            return 5

        event = event_for_findings(review["findings"])
        comments = build_inline_comments(outcome.attachable)
        body = build_review_body(review, failures, outcome.unattachable, len(review["findings"]))
        payload = {"commit_id": pr.head_sha, "event": event, "body": body, "comments": comments}
        (workspace.artifact_dir / UNPOSTED_REVIEW_NAME).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        print(
            f"review ready: event={event} findings={len(review['findings'])} "
            f"inline={len(comments)} unattached={len(outcome.unattachable)} "
            f"agents_failed={len(failures)}"
        )

        if opts.dry_run:
            print("dry-run: final review payload (not posted):")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        try:
            posted = client.post_review(
                owner, repo, number, pr.head_sha, event, body, comments, token
            )
        except GitHubError as e:
            print(f"error: {e}", file=sys.stderr)
            return 6
        print(f"posted review {posted.get('id')} ({posted.get('state')}) on {args.pr_url}")
        print(f"review URL: {posted.get('html_url')}")
        return 0
    finally:
        if not opts.keep_workspace:
            workspace.remove()


def run_cleanup(
    argv: list[str], workspace_factory: Callable[..., PRWorkspace] = PRWorkspace
) -> int:
    parser = argparse.ArgumentParser(
        prog="review-bot cleanup", description="Remove a PR workspace."
    )
    parser.add_argument("pr_url", help="GitHub pull request URL")
    parser.add_argument("--workspace-root", default=None)
    args = parser.parse_args(argv)
    try:
        owner, repo, number = parse_pr_url(args.pr_url)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    root = Path(
        args.workspace_root or os.environ.get("REVIEW_WORKSPACE_ROOT") or DEFAULT_WORKSPACE_ROOT
    )
    workspace = workspace_factory(root, owner, repo, number)
    removed = workspace.workdir.exists()
    workspace.remove()
    print(f"{'removed' if removed else 'already absent'}: {workspace.workdir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "cleanup":
        return run_cleanup(argv[1:])
    return run_review(argv)


if __name__ == "__main__":
    raise SystemExit(main())
