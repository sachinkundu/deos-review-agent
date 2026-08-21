"""review_bot CLI entrypoint: wires the Phase 2 review pipeline.

Usage:
    review-bot <PR_URL> [--dry-run] [--keep-workspace] [--no-agent-session] [options]
    review-bot status <PR_URL> [--workspace-root PATH] [--json]
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
from contextlib import nullcontext, redirect_stderr
from dataclasses import replace
from pathlib import Path

from . import __version__
from .agents.registry import InputResource, RegistryError, discover_agent_registry
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
    attribute_final_findings,
    run_coordinator,
    validate_result_identities,
    write_raw_classifications,
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
    PRInfo,
    build_inline_comments,
    event_for_findings,
    parse_pr_url,
)
from .history import (
    HistoryError,
    build_reviewer_view,
    parse_action_markers,
    run_identity,
    run_marker,
    select_review_mode,
    targets_document,
    without_expected_actions,
    write_history_snapshot,
    write_targets,
)
from .progress import (
    SNAPSHOT_NAME,
    Phase,
    ProgressController,
    ProgressError,
    State,
    format_status,
    read_snapshot,
)
from .recheck import (
    PROVIDER_READBACK_NAME,
    RECHECK_PLAN_NAME,
    RECHECK_RESULT_NAME,
    RecheckError,
    coordinator_prompt,
    mark_initial_findings,
    plan_recheck_actions,
    reviewer_prompt,
    validate_closed_world,
    verify_action_readback,
    verify_initial_readback,
    write_json_artifact,
)
from .resources import (
    ResourceError,
    ResourceResolver,
    validate_workspace_isolation,
    write_recheck_resources,
    write_registry_artifacts,
)
from .schema import SchemaError, load_named_schema, validate_review_output
from .shared_context import write_shared_context
from .workspace import (
    DEFAULT_BOOTSTRAP_TIMEOUT,
    PRWorkspace,
    WorkspaceError,
    workspace_dir_for,
)

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
    run_marker_text: str | None = None,
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
            if finding.get("_finding_marker"):
                lines.append("")
                lines.append(finding["_finding_marker"])
            lines.append("")

    if run_marker_text:
        lines.extend(["", run_marker_text])

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


def _review_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review-bot", description="Review a GitHub PR (Phase 2).", allow_abbrev=False
    )
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
    parser.add_argument(
        "--progress",
        choices=("auto", "plain", "json", "off"),
        default="auto",
        help="progress presentation on stderr (default: auto)",
    )
    return parser


def _json_progress_requested(argv: list[str]) -> bool:
    return any(
        argument == "--progress=json"
        or (argument == "--progress" and index + 1 < len(argv) and argv[index + 1] == "json")
        for index, argument in enumerate(argv)
    )


def _skip_phases(
    progress: ProgressController,
    phases: tuple[Phase, ...],
    message: str,
    *,
    update_overall: bool = True,
) -> None:
    for phase in phases:
        progress.phase(phase, State.SKIPPED, message, update_overall=update_overall)


def _owned_action_ids(history: dict, bot_username: str) -> set[str]:
    identities: set[str] = set()
    for item in [*history["review_comments"], *history["issue_comments"]]:
        if str(item.get("author") or "").casefold() != bot_username.casefold():
            continue
        identities.update(marker[0] for marker in parse_action_markers(item.get("body") or ""))
    return identities


def _finish_recheck(
    *,
    args: argparse.Namespace,
    opts: RunOptions,
    progress: ProgressController,
    client: GitHubAppClient,
    token: str,
    pr: PRInfo,
    owner: str,
    repo: str,
    number: int,
    bot_username: str,
    history: dict,
    targets: list[dict],
    result: dict,
    artifact_dir: Path,
) -> int:
    progress.phase(Phase.SCHEMA_VALIDATION, State.RUNNING, "recheck schema validation running")
    try:
        validate_closed_world(
            result,
            {target["finding_id"] for target in targets},
            require_complete=True,
        )
        write_json_artifact(artifact_dir, RECHECK_RESULT_NAME, result)
        plan = plan_recheck_actions(
            repository=f"{owner}/{repo}",
            pull_number=number,
            head_sha=pr.head_sha,
            history_digest=history["digest"],
            targets=targets,
            result=result,
        )
        write_json_artifact(artifact_dir, RECHECK_PLAN_NAME, plan)
    except RecheckError as e:
        progress.phase(Phase.SCHEMA_VALIDATION, State.FAILED, "recheck schema invalid")
        _skip_phases(
            progress,
            (Phase.DIFF_VALIDATION, Phase.HEAD_FRESHNESS, Phase.PAYLOAD, Phase.POSTING),
            "recheck result invalid",
            update_overall=False,
        )
        print(f"error: {e}", file=sys.stderr)
        return 7
    progress.phase(Phase.SCHEMA_VALIDATION, State.SUCCEEDED, "recheck schema valid")
    progress.phase(
        Phase.DIFF_VALIDATION,
        State.SKIPPED,
        "recheck creates no new diff-line comments",
    )

    progress.phase(Phase.HEAD_FRESHNESS, State.RUNNING, "head and conversation recheck running")
    try:
        fresh_pr = client.fetch_pr(owner, repo, number, token)
        fresh_history = client.fetch_complete_history(owner, repo, number, fresh_pr.head_sha, token)
    except GitHubError as e:
        progress.phase(Phase.HEAD_FRESHNESS, State.FAILED, "freshness recheck failed")
        _skip_phases(
            progress,
            (Phase.PAYLOAD, Phase.POSTING),
            "freshness unavailable",
            update_overall=False,
        )
        print(f"error: freshness re-check failed: {e}", file=sys.stderr)
        return 6
    if fresh_pr.head_sha != pr.head_sha or fresh_history["digest"] != history["digest"]:
        progress.phase(Phase.HEAD_FRESHNESS, State.FAILED, "head or conversation changed")
        _skip_phases(
            progress,
            (Phase.PAYLOAD, Phase.POSTING),
            "recheck inputs changed",
            update_overall=False,
        )
        stale = {
            "contract": "review-stale-result/v1",
            "expected_head": pr.head_sha,
            "actual_head": fresh_pr.head_sha,
            "expected_history_digest": history["digest"],
            "actual_history_digest": fresh_history["digest"],
        }
        write_json_artifact(artifact_dir, "stale-result.json", stale)
        print("error: PR head or conversation changed before recheck posting; posted nothing.")
        return 5
    progress.phase(Phase.HEAD_FRESHNESS, State.SUCCEEDED, "head and conversation unchanged")
    progress.phase(Phase.PAYLOAD, State.RUNNING, "recheck plan retention running")
    progress.phase(Phase.PAYLOAD, State.SUCCEEDED, "recheck plan retained")
    print(
        f"recheck ready: targets={len(targets)} actions={len(plan['actions'])} "
        f"ambiguous={len(targets) - len(plan['actions'])}"
    )
    if opts.dry_run:
        progress.phase(Phase.POSTING, State.SKIPPED, "dry run does not post")
        print("dry-run: recheck classification and action plan retained; no GitHub mutation.")
        return 0
    if not plan["actions"]:
        progress.phase(Phase.POSTING, State.SKIPPED, "ambiguous recheck has no mutation")
        print("recheck complete: every target was ambiguous; no GitHub mutation permitted.")
        return 0

    progress.phase(Phase.POSTING, State.RUNNING, "recheck status posting running")
    completed_ids: set[str] = set()
    readbacks: list[dict] = []
    for action in plan["actions"]:
        try:
            guard_pr = client.fetch_pr(owner, repo, number, token)
            guard_history = client.fetch_complete_history(
                owner, repo, number, guard_pr.head_sha, token
            )
        except GitHubError as e:
            progress.phase(Phase.POSTING, State.FAILED, "per-action freshness failed")
            print(f"error: per-action freshness failed: {e}", file=sys.stderr)
            return 6
        existing_ids = _owned_action_ids(guard_history, bot_username)
        if action["action_id"] in existing_ids:
            completed_ids.add(action["action_id"])
            readbacks.append(
                {
                    "action_id": action["action_id"],
                    "finding_id": action["finding_id"],
                    "outcome": "already_verified",
                }
            )
            continue
        comparable = without_expected_actions(guard_history, completed_ids)
        if guard_pr.head_sha != pr.head_sha or comparable["digest"] != history["digest"]:
            progress.phase(Phase.POSTING, State.FAILED, "conversation changed during plan")
            write_json_artifact(
                artifact_dir,
                PROVIDER_READBACK_NAME,
                {
                    "contract": "review-provider-readback/v1",
                    "outcome": "partial_stale",
                    "actions": readbacks,
                },
            )
            print("error: conversation changed during recheck plan; stopped remaining actions.")
            return 5
        try:
            if action["surface"] == "review_reply":
                created = client.post_review_reply(
                    owner,
                    repo,
                    number,
                    action["target_provider_id"],
                    action["body"],
                    token,
                )
                provider = client.fetch_review_comment(owner, repo, created["id"], token)
            else:
                created = client.post_issue_comment(owner, repo, number, action["body"], token)
                provider = client.fetch_issue_comment(owner, repo, created["id"], token)
            verified = verify_action_readback(
                provider=provider,
                bot_login=bot_username,
                action=action,
                pull_number=number,
            )
        except (GitHubError, KeyError, RecheckError) as e:
            readbacks.append(
                {
                    "action_id": action["action_id"],
                    "finding_id": action["finding_id"],
                    "outcome": "indeterminate",
                    "error": str(e),
                }
            )
            write_json_artifact(
                artifact_dir,
                PROVIDER_READBACK_NAME,
                {
                    "contract": "review-provider-readback/v1",
                    "outcome": "indeterminate",
                    "actions": readbacks,
                },
            )
            progress.phase(Phase.POSTING, State.FAILED, "provider read-back indeterminate")
            print(
                f"error: provider accepted or attempted an action that could not be verified: {e}"
            )
            return 6
        completed_ids.add(action["action_id"])
        readbacks.append(verified)
        write_json_artifact(
            artifact_dir,
            PROVIDER_READBACK_NAME,
            {
                "contract": "review-provider-readback/v1",
                "outcome": "verified",
                "actions": readbacks,
            },
        )
    progress.phase(Phase.POSTING, State.SUCCEEDED, "recheck statuses verified")
    print(f"recheck posted and verified: actions={len(readbacks)} on {args.pr_url}")
    return 0


def run_review(
    argv: list[str],
    client_factory: Callable[[Credentials], GitHubAppClient] = GitHubAppClient,
    runner_factory: Callable[..., AgentRunner] = build_agent_runner,
    workspace_factory: Callable[..., PRWorkspace] = PRWorkspace,
    diff_artifact_writer: Callable[..., object] = write_diff_artifacts,
) -> int:
    parse_diagnostics = (
        redirect_stderr(sys.stdout) if _json_progress_requested(argv) else nullcontext()
    )
    with parse_diagnostics:
        args = _review_parser().parse_args(argv)
    try:
        target = parse_pr_url(args.pr_url)
    except ValueError as exc:
        destination = sys.stdout if args.progress == "json" else sys.stderr
        print(f"error: {exc}", file=destination)
        return 1
    progress = ProgressController(args.progress)
    diagnostics = redirect_stderr(sys.stdout) if args.progress == "json" else nullcontext()
    try:
        with diagnostics:
            try:
                exit_code = _run_review_pipeline(
                    args,
                    progress,
                    target,
                    client_factory=client_factory,
                    runner_factory=runner_factory,
                    workspace_factory=workspace_factory,
                    diff_artifact_writer=diff_artifact_writer,
                )
                progress.finish(exit_code)
                return exit_code
            except KeyboardInterrupt:
                progress.interrupt()
                if args.progress == "json":
                    return 130
                raise
            except Exception as exc:
                progress.finish(1)
                if args.progress == "json":
                    print(
                        f"error: unexpected failure: {type(exc).__name__}",
                        file=sys.stderr,
                    )
                    return 1
                raise
    finally:
        progress.close()


def _run_review_pipeline(
    args: argparse.Namespace,
    progress: ProgressController,
    target: tuple[str, str, int],
    client_factory: Callable[[Credentials], GitHubAppClient] = GitHubAppClient,
    runner_factory: Callable[..., AgentRunner] = build_agent_runner,
    workspace_factory: Callable[..., PRWorkspace] = PRWorkspace,
    diff_artifact_writer: Callable[..., object] = write_diff_artifacts,
) -> int:
    owner, repo, number = target

    progress.phase(Phase.REGISTRY, State.RUNNING, "agent registry discovery running")
    try:
        registry = discover_agent_registry()
    except RegistryError as e:
        progress.phase(Phase.REGISTRY, State.FAILED, "agent registry invalid")
        print(f"error: agent registry invalid: {e}", file=sys.stderr)
        return 1
    progress.phase(Phase.REGISTRY, State.SUCCEEDED, "agent registry discovered")

    progress.phase(Phase.CREDENTIALS, State.RUNNING, "provider credentials loading")
    try:
        creds = build_credentials()
    except CredentialsError as e:
        progress.phase(Phase.CREDENTIALS, State.FAILED, "provider credentials unavailable")
        print(f"error: {e}", file=sys.stderr)
        return 1

    client = client_factory(creds)
    opts = RunOptions(args)
    if opts.max_agent_concurrency < 1:
        progress.phase(Phase.CREDENTIALS, State.SKIPPED, "provider authentication not attempted")
        print("error: max agent concurrency must be at least 1", file=sys.stderr)
        return 1
    if opts.agent_timeout < 0:
        progress.phase(Phase.CREDENTIALS, State.SKIPPED, "provider authentication not attempted")
        print("error: agent timeout must be non-negative", file=sys.stderr)
        return 1
    workspace = workspace_factory(
        opts.workspace_root, owner, repo, number, bootstrap_timeout=opts.bootstrap_timeout
    )

    try:
        # Fail fast on bad credentials before any repository operation.
        client.mint_app_jwt()
        token = client.mint_installation_token(f"{owner}/{repo}")
    except (CredentialsError, GitHubError) as e:
        progress.phase(Phase.CREDENTIALS, State.FAILED, "provider authentication failed")
        print(f"error: {e}", file=sys.stderr)
        return 1
    progress.phase(Phase.CREDENTIALS, State.SUCCEEDED, "provider authentication succeeded")

    progress.phase(Phase.PR_METADATA, State.RUNNING, "pull request metadata loading")
    try:
        pr = client.fetch_pr(owner, repo, number, token)
        bot_username = creds.bot_username or client.bot_username()
    except GitHubError as e:
        progress.phase(Phase.PR_METADATA, State.FAILED, "pull request metadata unavailable")
        print(f"error: {e}", file=sys.stderr)
        return 1
    progress.phase(Phase.PR_METADATA, State.SUCCEEDED, "pull request metadata loaded")

    if pr.sender_login == bot_username:
        _skip_phases(
            progress,
            (
                Phase.PROVIDER_DIFF,
                Phase.WORKSPACE,
                Phase.BOOTSTRAP,
                Phase.REVIEWERS,
                Phase.COORDINATION,
                Phase.SCHEMA_VALIDATION,
                Phase.DIFF_VALIDATION,
                Phase.HEAD_FRESHNESS,
                Phase.PAYLOAD,
                Phase.POSTING,
                Phase.CLEANUP,
            ),
            "bot-authored pull request ignored",
        )
        print(
            f"skip: PR {pr.number} was opened by the bot ({bot_username}); "
            "not reviewing our own PRs."
        )
        return 0

    progress.phase(Phase.PROVIDER_DIFF, State.RUNNING, "provider diff loading")
    try:
        diff_text = client.fetch_pr_diff(owner, repo, number, token)
        history = client.fetch_complete_history(owner, repo, number, pr.head_sha, token)
        selection = select_review_mode(history, bot_username, pr.head_sha)
    except GitHubError as e:
        progress.phase(Phase.PROVIDER_DIFF, State.FAILED, "provider diff or history unavailable")
        print(f"error: {e}", file=sys.stderr)
        return 1
    except HistoryError as e:
        progress.phase(Phase.PROVIDER_DIFF, State.FAILED, "provider history invalid")
        print(f"error: provider history invalid: {e}", file=sys.stderr)
        return 1
    if selection.mode == "noop":
        progress.phase(Phase.PROVIDER_DIFF, State.SUCCEEDED, "provider history selected no-op")
        _skip_phases(
            progress,
            (
                Phase.WORKSPACE,
                Phase.BOOTSTRAP,
                Phase.REVIEWERS,
                Phase.COORDINATION,
                Phase.SCHEMA_VALIDATION,
                Phase.DIFF_VALIDATION,
                Phase.HEAD_FRESHNESS,
                Phase.PAYLOAD,
                Phase.POSTING,
                Phase.CLEANUP,
            ),
            "review head already evaluated",
        )
        print(f"no-op: {selection.reason}; no GitHub mutation planned.")
        return 0
    provider_diff_settled = False
    try:
        progress.phase(Phase.WORKSPACE, State.RUNNING, "exact-head workspace setup running")
        try:
            workspace.setup(pr.head_repo_clone_url, pr.head_sha, pr.head_ref, token)
        except WorkspaceError as e:
            progress.phase(Phase.WORKSPACE, State.FAILED, "exact-head workspace setup failed")
            print(f"error: workspace setup failed: {e}", file=sys.stderr)
            return 2
        progress.bind_workspace(
            workspace.artifact_dir,
            repository=f"{owner}/{repo}",
            pull_request=number,
            head_sha=pr.head_sha,
            dry_run=opts.dry_run,
            harness=Path(opts.agent_command).name,
            max_concurrency=opts.max_agent_concurrency,
            reviewer_names=[agent.name for agent in registry.reviewers],
            coordinator_name=registry.coordinator.name,
            timeout_seconds=opts.agent_timeout,
        )
        write_history_snapshot(workspace.artifact_dir, history)
        progress.phase(Phase.WORKSPACE, State.SUCCEEDED, "exact-head workspace ready")

        progress.phase(Phase.BOOTSTRAP, State.RUNNING, "repository bootstrap running")
        bootstrap = workspace.run_bootstrap(
            workspace.source_dir,
            extra_env={
                "REVIEW_PR_URL": args.pr_url,
                "REVIEW_HEAD_SHA": pr.head_sha,
                "REVIEW_PR_NUMBER": str(number),
            },
        )
        if not bootstrap.ok:
            bootstrap_state = State.TIMED_OUT if bootstrap.exit_code is None else State.FAILED
            progress.phase(Phase.BOOTSTRAP, bootstrap_state, "repository bootstrap failed")
            _skip_phases(
                progress,
                (
                    Phase.REVIEWERS,
                    Phase.COORDINATION,
                    Phase.SCHEMA_VALIDATION,
                    Phase.DIFF_VALIDATION,
                    Phase.HEAD_FRESHNESS,
                    Phase.PAYLOAD,
                    Phase.POSTING,
                ),
                "bootstrap unavailable",
                update_overall=False,
            )
            print(f"error: bootstrap failed: {bootstrap.summary}", file=sys.stderr)
            return 2
        progress.phase(
            Phase.BOOTSTRAP,
            State.SUCCEEDED if bootstrap.ran else State.SKIPPED,
            "repository bootstrap succeeded" if bootstrap.ran else "no bootstrap configured",
        )

        try:
            if diff_artifact_writer is write_diff_artifacts:
                _diff_artifacts = diff_artifact_writer(
                    workspace.artifact_dir,
                    diff_text,
                    repository=workspace.source_dir,
                )
            else:
                _diff_artifacts = diff_artifact_writer(workspace.artifact_dir, diff_text)
            write_shared_context(workspace.artifact_dir, pr, bootstrap)
        except DiffFilterError as e:
            progress.phase(Phase.PROVIDER_DIFF, State.FAILED, "diff artifact construction failed")
            provider_diff_settled = True
            _skip_phases(
                progress,
                (
                    Phase.REVIEWERS,
                    Phase.COORDINATION,
                    Phase.SCHEMA_VALIDATION,
                    Phase.DIFF_VALIDATION,
                    Phase.HEAD_FRESHNESS,
                    Phase.PAYLOAD,
                    Phase.POSTING,
                ),
                "diff artifacts unavailable",
                update_overall=False,
            )
            print(f"error: diff artifact construction failed: {e}", file=sys.stderr)
            return 2
        except OSError:
            progress.phase(Phase.PROVIDER_DIFF, State.FAILED, "diff artifact persistence failed")
            provider_diff_settled = True
            raise
        progress.phase(Phase.PROVIDER_DIFF, State.SUCCEEDED, "diff artifacts ready")
        provider_diff_settled = True

        progress.phase(Phase.REVIEWERS, State.RUNNING, "review harness setup running")
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
            progress.phase(Phase.REVIEWERS, State.FAILED, "review harness setup failed")
            _skip_phases(
                progress,
                (
                    Phase.COORDINATION,
                    Phase.SCHEMA_VALIDATION,
                    Phase.DIFF_VALIDATION,
                    Phase.HEAD_FRESHNESS,
                    Phase.PAYLOAD,
                    Phase.POSTING,
                ),
                "review harness unavailable",
                update_overall=False,
            )
            print(f"error: review harness setup failed: {e}", file=sys.stderr)
            return 2

        harness = Path(opts.agent_command).name
        resolver = ResourceResolver(workspace.source_dir, workspace.artifact_dir)
        try:
            write_registry_artifacts(workspace.artifact_dir, registry, harness)
            reviewer_assignments: dict[str, list[dict]] = {
                agent.name: [] for agent in registry.reviewers
            }
            invocation_agents = registry.reviewers
            recheck_schema = load_named_schema("recheck_schema.json")
            if selection.mode == "recheck":
                target_doc = targets_document(selection, history)
                write_targets(workspace.artifact_dir, target_doc)
                reviewer_names = set(reviewer_assignments)
                fallback_reviewer = registry.reviewers[0].name
                for target_item in selection.targets:
                    assigned_name = str(target_item.get("source_agent") or fallback_reviewer)
                    if assigned_name not in reviewer_names:
                        assigned_name = fallback_reviewer
                    reviewer_assignments[assigned_name].append(target_item)
                try:
                    filter_manifest = json.loads(
                        (workspace.artifact_dir / "diff-filter.json").read_text(encoding="utf-8")
                    )
                    excluded_paths = {
                        item["path"] for item in filter_manifest.get("exclusions", [])
                    }
                    reviewer_views = {
                        agent.name: build_reviewer_view(
                            history,
                            list(selection.targets),
                            reviewer=agent.name,
                            excluded_paths=excluded_paths,
                            include_excluded=agent.name == "safety",
                        )
                        for agent in registry.reviewers
                    }
                except (OSError, ValueError, KeyError, HistoryError) as e:
                    raise ResourceError(f"recheck history view construction failed: {e}") from e
                head_evidence = {
                    "contract": "review-current-head/v1",
                    "repository": f"{owner}/{repo}",
                    "pull_number": number,
                    "head_sha": pr.head_sha,
                    "history_digest": history["digest"],
                    "provider_diff": "provider-diff.diff",
                }
                write_recheck_resources(
                    workspace.artifact_dir,
                    reviewer_views,
                    reviewer_assignments,
                    head_evidence,
                )
                invocation_agents = tuple(
                    replace(
                        agent,
                        inputs=(
                            InputResource.RECHECK_HISTORY,
                            InputResource.RECHECK_TARGETS,
                            InputResource.CURRENT_HEAD_EVIDENCE,
                        ),
                    )
                    for agent in registry.reviewers
                )
            invocations: list[tuple[AgentSpec, Path]] = []
            for agent in invocation_agents:
                capsule = resolver.create_capsule(agent)
                target_ids = [
                    target_item["finding_id"]
                    for target_item in reviewer_assignments.get(agent.name, [])
                ]
                invocations.append(
                    (
                        AgentSpec(
                            name=agent.name,
                            prompt=agent.prompt_text()
                            if selection.mode == "initial"
                            else reviewer_prompt(agent.name, target_ids),
                            input_files=capsule.input_files,
                            contract_version=agent.contract_version,
                            package_digest=agent.package_digest,
                            skills=agent.skills,
                            package_dir=agent.package_dir,
                            output_schema=None if selection.mode == "initial" else recheck_schema,
                        ),
                        capsule.root,
                    )
                )
            agent_results = run_agents_concurrently(
                runner,
                invocations,
                max_concurrency=opts.max_agent_concurrency,
                on_queued=lambda agent_spec: progress.reviewer_queued(
                    agent_spec.name, opts.agent_timeout
                ),
                on_started=lambda agent_spec: progress.reviewer_started(
                    agent_spec.name, opts.agent_timeout
                ),
                on_settled=lambda result: progress.reviewer_settled(
                    result.name,
                    result.ok,
                    timed_out=result.timed_out,
                ),
            )

            try:
                validate_result_identities(registry, agent_results)
                if selection.mode == "recheck":
                    for result in agent_results:
                        if result.ok and result.output is not None:
                            validate_closed_world(
                                result.output,
                                {item["finding_id"] for item in reviewer_assignments[result.name]},
                                require_complete=True,
                            )
            except (CoordinatorError, RecheckError) as e:
                progress.phase(Phase.REVIEWERS, State.FAILED, "reviewer identity validation failed")
                _skip_phases(
                    progress,
                    (
                        Phase.COORDINATION,
                        Phase.SCHEMA_VALIDATION,
                        Phase.DIFF_VALIDATION,
                        Phase.HEAD_FRESHNESS,
                        Phase.PAYLOAD,
                        Phase.POSTING,
                    ),
                    "reviewer results unavailable",
                    update_overall=False,
                )
                print(f"error: {e}", file=sys.stderr)
                return 4

            failures = [r for r in agent_results if not r.ok]
            successful = [r for r in agent_results if r.ok]
            for failure in failures:
                print(f"warning: agent {failure.name} {failure.summary}", file=sys.stderr)
            if not successful:
                progress.phase(Phase.REVIEWERS, State.FAILED, "all reviewers failed")
                _skip_phases(
                    progress,
                    (
                        Phase.COORDINATION,
                        Phase.SCHEMA_VALIDATION,
                        Phase.DIFF_VALIDATION,
                        Phase.HEAD_FRESHNESS,
                        Phase.PAYLOAD,
                        Phase.POSTING,
                    ),
                    "no successful reviewer result",
                    update_overall=False,
                )
                print(
                    "error: all review agents failed; nothing to review, no review posted.",
                    file=sys.stderr,
                )
                return 3
            progress.phase(
                Phase.REVIEWERS,
                State.SUCCEEDED,
                "reviewers settled with partial failures" if failures else "reviewers succeeded",
            )

            try:
                progress.coordinator_started()
                if selection.mode == "initial":
                    write_raw_findings(workspace.artifact_dir, agent_results)
                    coordinator = registry.coordinator
                else:
                    write_raw_classifications(workspace.artifact_dir, agent_results)
                    coordinator = replace(
                        registry.coordinator,
                        inputs=(
                            InputResource.CURRENT_HEAD_EVIDENCE,
                            InputResource.REVIEW_HISTORY,
                            InputResource.TARGET_CATALOG,
                            InputResource.AGENT_CATALOG,
                            InputResource.RAW_FINDINGS,
                        ),
                    )
                capsule = resolver.create_capsule(coordinator)
                spec = AgentSpec(
                    name=coordinator.name,
                    prompt=coordinator.prompt_text()
                    if selection.mode == "initial"
                    else coordinator_prompt(
                        [target_item["finding_id"] for target_item in selection.targets]
                    ),
                    input_files=capsule.input_files,
                    contract_version=coordinator.contract_version,
                    package_digest=coordinator.package_digest,
                    skills=coordinator.skills,
                    package_dir=coordinator.package_dir,
                    output_schema=None if selection.mode == "initial" else recheck_schema,
                )
                review = run_coordinator(
                    runner, spec, capsule.root, recheck=selection.mode == "recheck"
                )
                if selection.mode == "recheck":
                    validate_closed_world(
                        review,
                        {target_item["finding_id"] for target_item in selection.targets},
                        require_complete=True,
                    )
                else:
                    attribute_final_findings(review, agent_results)
                progress.coordinator_settled(ok=True)
            except (
                CoordinatorError,
                HarnessError,
                RecheckError,
                ResourceError,
                RegistryError,
            ) as e:
                progress.coordinator_settled(
                    ok=False, timed_out=isinstance(e, CoordinatorError) and e.timed_out
                )
                _skip_phases(
                    progress,
                    (
                        Phase.SCHEMA_VALIDATION,
                        Phase.DIFF_VALIDATION,
                        Phase.HEAD_FRESHNESS,
                        Phase.PAYLOAD,
                        Phase.POSTING,
                    ),
                    "coordinator result unavailable",
                    update_overall=False,
                )
                print(f"error: {e}", file=sys.stderr)
                return 4
        except (HarnessError, ResourceError, RegistryError) as e:
            progress.phase(Phase.REVIEWERS, State.FAILED, "isolated reviewer invocation failed")
            _skip_phases(
                progress,
                (
                    Phase.COORDINATION,
                    Phase.SCHEMA_VALIDATION,
                    Phase.DIFF_VALIDATION,
                    Phase.HEAD_FRESHNESS,
                    Phase.PAYLOAD,
                    Phase.POSTING,
                ),
                "reviewer results unavailable",
                update_overall=False,
            )
            print(f"error: isolated agent invocation failed: {e}", file=sys.stderr)
            return 2
        finally:
            resolver.close()
            if hasattr(runner, "close"):
                runner.close()

        if selection.mode == "recheck":
            return _finish_recheck(
                args=args,
                opts=opts,
                progress=progress,
                client=client,
                token=token,
                pr=pr,
                owner=owner,
                repo=repo,
                number=number,
                bot_username=bot_username,
                history=history,
                targets=list(selection.targets),
                result=review,
                artifact_dir=workspace.artifact_dir,
            )

        # Final payload validation before any GitHub POST.
        progress.phase(Phase.SCHEMA_VALIDATION, State.RUNNING, "review schema validation running")
        try:
            validate_review_output(review)
        except SchemaError as e:
            progress.phase(Phase.SCHEMA_VALIDATION, State.FAILED, "review schema invalid")
            _skip_phases(
                progress,
                (
                    Phase.DIFF_VALIDATION,
                    Phase.HEAD_FRESHNESS,
                    Phase.PAYLOAD,
                    Phase.POSTING,
                ),
                "review schema invalid",
                update_overall=False,
            )
            print(f"error: {e}", file=sys.stderr)
            return 7
        progress.phase(Phase.SCHEMA_VALIDATION, State.SUCCEEDED, "review schema valid")
        try:
            marked_findings = mark_initial_findings(review, pr.head_sha)
        except RecheckError as e:
            progress.phase(Phase.SCHEMA_VALIDATION, State.FAILED, "finding identity invalid")
            _skip_phases(
                progress,
                (
                    Phase.DIFF_VALIDATION,
                    Phase.HEAD_FRESHNESS,
                    Phase.PAYLOAD,
                    Phase.POSTING,
                ),
                "finding identity invalid",
                update_overall=False,
            )
            print(f"error: {e}", file=sys.stderr)
            return 7
        posting_review = dict(review)
        posting_review["findings"] = marked_findings
        current_run_id = run_identity(f"{owner}/{repo}", number, pr.head_sha)
        current_run_marker = run_marker(current_run_id, pr.head_sha)

        progress.phase(Phase.DIFF_VALIDATION, State.RUNNING, "diff line validation running")
        outcome = validate_findings_locations(marked_findings, parse_unified_diff(diff_text))
        progress.phase(Phase.DIFF_VALIDATION, State.SUCCEEDED, "diff line validation succeeded")

        # Re-check the head SHA so we never post against a stale head.
        progress.phase(Phase.HEAD_FRESHNESS, State.RUNNING, "pull request head recheck running")
        try:
            fresh = client.fetch_pr(owner, repo, number, token)
            fresh_history = client.fetch_complete_history(
                owner, repo, number, fresh.head_sha, token
            )
        except GitHubError as e:
            progress.phase(Phase.HEAD_FRESHNESS, State.FAILED, "pull request head recheck failed")
            _skip_phases(
                progress,
                (Phase.PAYLOAD, Phase.POSTING),
                "head freshness unavailable",
                update_overall=False,
            )
            print(f"error: head re-check failed: {e}", file=sys.stderr)
            return 6
        if fresh.head_sha != pr.head_sha or fresh_history["digest"] != history["digest"]:
            progress.phase(
                Phase.HEAD_FRESHNESS,
                State.FAILED,
                "pull request head or conversation changed",
            )
            _skip_phases(
                progress,
                (Phase.PAYLOAD, Phase.POSTING),
                "pull request head or conversation changed",
                update_overall=False,
            )
            print(
                "error: PR head or provider conversation changed before posting; "
                "refuse to post stale review output. Re-run the review.",
                file=sys.stderr,
            )
            write_json_artifact(
                workspace.artifact_dir,
                "stale-result.json",
                {
                    "contract": "review-stale-result/v1",
                    "expected_head": pr.head_sha,
                    "actual_head": fresh.head_sha,
                    "expected_history_digest": history["digest"],
                    "actual_history_digest": fresh_history["digest"],
                    "review": review,
                },
            )
            return 5
        progress.phase(
            Phase.HEAD_FRESHNESS,
            State.SUCCEEDED,
            "pull request head and conversation unchanged",
        )

        progress.phase(Phase.PAYLOAD, State.RUNNING, "review payload retention running")
        event = event_for_findings(marked_findings)
        comments = build_inline_comments(outcome.attachable)
        body = build_review_body(
            posting_review,
            failures,
            outcome.unattachable,
            len(marked_findings),
            run_marker_text=current_run_marker,
        )
        payload = {"commit_id": pr.head_sha, "event": event, "body": body, "comments": comments}
        (workspace.artifact_dir / UNPOSTED_REVIEW_NAME).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        progress.phase(Phase.PAYLOAD, State.SUCCEEDED, "review payload retained")

        print(
            f"review ready: event={event} findings={len(marked_findings)} "
            f"inline={len(comments)} unattached={len(outcome.unattachable)} "
            f"agents_failed={len(failures)}"
        )

        if opts.dry_run:
            progress.phase(Phase.POSTING, State.SKIPPED, "dry run does not post")
            print("dry-run: final review payload (not posted):")
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        progress.phase(Phase.POSTING, State.RUNNING, "provider review posting running")
        try:
            posted = client.post_review(
                owner, repo, number, pr.head_sha, event, body, comments, token
            )
            provider_review = client.fetch_review(owner, repo, number, posted["id"], token)
            provider_comments = client.fetch_review_comments_for_review(
                owner, repo, number, posted["id"], token
            )
            readback = verify_initial_readback(
                review=provider_review,
                comments=provider_comments,
                bot_login=bot_username,
                run_id=current_run_id,
                head_sha=pr.head_sha,
                expected_finding_ids={item["_finding_id"] for item in marked_findings},
            )
            write_json_artifact(workspace.artifact_dir, PROVIDER_READBACK_NAME, readback)
        except (GitHubError, KeyError, RecheckError) as e:
            progress.phase(Phase.POSTING, State.FAILED, "provider review posting failed")
            write_json_artifact(
                workspace.artifact_dir,
                PROVIDER_READBACK_NAME,
                {
                    "contract": "review-provider-readback/v1",
                    "outcome": "indeterminate",
                    "error": str(e),
                },
            )
            print(f"error: provider review posting/read-back failed: {e}", file=sys.stderr)
            return 6
        progress.set_review_url(posted.get("html_url"))
        progress.phase(Phase.POSTING, State.SUCCEEDED, "provider review accepted and verified")
        print(f"posted review {posted.get('id')} ({posted.get('state')}) on {args.pr_url}")
        print(f"review URL: {posted.get('html_url')}")
        return 0
    finally:
        active_exception = sys.exc_info()[0]
        if not provider_diff_settled:
            _active_phase, active_state = progress.current_overall()
            provider_diff_state = (
                State.INTERRUPTED
                if active_exception is KeyboardInterrupt
                else State.TIMED_OUT
                if active_state == State.TIMED_OUT
                else State.FAILED
            )
            progress.phase(
                Phase.PROVIDER_DIFF,
                provider_diff_state,
                "diff artifact construction aborted",
                update_overall=False,
            )
        cleanup_started_normally = active_exception is None
        prior_overall = progress.current_overall()
        if opts.keep_workspace:
            progress.phase(
                Phase.CLEANUP,
                State.SKIPPED,
                "workspace retained",
                update_overall=False,
            )
        else:
            progress.phase(
                Phase.CLEANUP,
                State.RUNNING,
                "workspace cleanup running",
                update_overall=cleanup_started_normally,
            )
            try:
                workspace.remove()
            except Exception:
                progress.phase(Phase.CLEANUP, State.FAILED, "workspace cleanup failed")
                raise
            progress.detach_store()
            progress.phase(
                Phase.CLEANUP,
                State.SUCCEEDED,
                "workspace cleanup succeeded",
                update_overall=False,
            )
            if cleanup_started_normally:
                progress.restore_overall(*prior_overall)


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
    try:
        workspace.remove()
    except OSError as e:
        print(f"error: workspace cleanup failed: {e}", file=sys.stderr)
        return 1
    print(f"{'removed' if removed else 'already absent'}: {workspace.workdir}")
    return 0


def run_status(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="review-bot status", description="Read a retained review progress snapshot."
    )
    parser.add_argument("pr_url", help="GitHub pull request URL")
    parser.add_argument("--workspace-root", default=None)
    parser.add_argument("--json", action="store_true", help="print the exact snapshot as JSON")
    args = parser.parse_args(argv)
    try:
        owner, repo, number = parse_pr_url(args.pr_url)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    root = (
        Path(
            args.workspace_root or os.environ.get("REVIEW_WORKSPACE_ROOT") or DEFAULT_WORKSPACE_ROOT
        )
        .expanduser()
        .resolve()
    )
    snapshot_path = workspace_dir_for(root, owner, repo, number) / "host-artifacts" / SNAPSHOT_NAME
    try:
        snapshot = read_snapshot(snapshot_path)
    except ProgressError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        print(format_status(snapshot))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "cleanup":
        return run_cleanup(argv[1:])
    if argv and argv[0] == "status":
        return run_status(argv[1:])
    return run_review(argv)


if __name__ == "__main__":
    raise SystemExit(main())
