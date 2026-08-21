"""Canonical provider history, owned markers, review cycles, and scoped views."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .schema import validate_history_snapshot

HISTORY_NAME = "review-history.json"
TARGETS_NAME = "review-targets.json"
HEAD_EVIDENCE_NAME = "current-head-evidence.json"
HISTORY_CONTRACT = "review-history/v1"
TARGETS_CONTRACT = "review-targets/v1"
VIEW_CONTRACT = "review-history-view/v1"

_HEX = r"[0-9a-f]{6,64}"
_RUN_RE = re.compile(rf"<!--\s*review-bot-run:v1\s+run=(rbr_[0-9a-f]{{32}})\s+head=({_HEX})\s*-->")
_FINDING_RE = re.compile(
    rf"<!--\s*review-bot-finding:v1\s+id=(rbf_[0-9a-f]{{32}})\s+"
    rf"head=({_HEX})\s+agent=([a-z0-9][a-z0-9-]{{0,63}})\s*-->"
)
_ACTION_RE = re.compile(
    rf"<!--\s*review-bot-action:v1\s+id=(rba_[0-9a-f]{{32}})\s+"
    rf"finding=(rbf_[0-9a-f]{{32}})\s+head=({_HEX})\s+"
    r"status=(fixed|unfixed|obsolete|ambiguous)\s*-->"
)
_ANY_MARKER_RE = re.compile(r"<!--\s*review-bot-(?:run|finding|action):v1\b.*?-->", re.DOTALL)


class HistoryError(RuntimeError):
    """Provider history is incomplete, contradictory, or unsafe to use."""


@dataclass(frozen=True)
class ReviewSelection:
    mode: Literal["initial", "recheck", "noop"]
    targets: tuple[dict[str, Any], ...]
    reason: str
    run_id: str | None = None


def _author(item: dict[str, Any]) -> str:
    user = item.get("user") or item.get("author") or {}
    if isinstance(user, dict):
        return str(user.get("login") or "")
    return str(user or "")


def _normalize_common(item: dict[str, Any], surface: str) -> dict[str, Any]:
    return {
        "id": item.get("id") if item.get("id") is not None else item.get("node_id", ""),
        "node_id": item.get("node_id"),
        "author": _author(item),
        "body": str(item.get("body") or ""),
        "created_at": item.get("created_at") or item.get("submitted_at"),
        "updated_at": item.get("updated_at") or item.get("submitted_at"),
        "url": item.get("html_url") or item.get("url"),
        "surface": surface,
    }


def _normalize_review(item: dict[str, Any]) -> dict[str, Any]:
    value = _normalize_common(item, "review")
    value.update(
        {
            "state": item.get("state"),
            "commit_id": item.get("commit_id"),
        }
    )
    return value


def _normalize_review_comment(item: dict[str, Any]) -> dict[str, Any]:
    value = _normalize_common(item, "review_comment")
    value.update(
        {
            "review_id": item.get("pull_request_review_id"),
            "in_reply_to_id": item.get("in_reply_to_id"),
            "path": item.get("path"),
            "diff_hunk": item.get("diff_hunk"),
            "line": item.get("line"),
            "original_line": item.get("original_line"),
            "side": item.get("side"),
            "original_side": item.get("original_side"),
            "commit_id": item.get("commit_id"),
            "original_commit_id": item.get("original_commit_id"),
        }
    )
    return value


def _normalize_issue_comment(item: dict[str, Any]) -> dict[str, Any]:
    return _normalize_common(item, "issue_comment")


def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("created_at") or ""), str(item.get("id") or ""))


def _dedupe(items: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        identity = str(item.get("id") or "")
        if not identity:
            raise HistoryError(f"{label} object has no provider identity")
        prior = by_id.get(identity)
        if prior is not None and prior != item:
            raise HistoryError(f"{label} provider identity {identity!r} has conflicting values")
        by_id[identity] = item
    return sorted(by_id.values(), key=_sort_key)


def _normalize_threads(threads: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for thread in threads or []:
        node_id = str(thread.get("node_id") or thread.get("id") or "")
        if not node_id:
            raise HistoryError("review thread has no node identity")
        comments = thread.get("comments") or []
        comment_ids = [
            str(comment.get("node_id") or comment.get("id") or "")
            if isinstance(comment, dict)
            else str(comment)
            for comment in comments
        ]
        if any(not value for value in comment_ids):
            raise HistoryError(f"review thread {node_id!r} contains an unidentified comment")
        resolved = thread.get("is_resolved", thread.get("isResolved", "unknown"))
        if resolved not in (True, False, "unknown"):
            resolved = "unknown"
        normalized.append({"node_id": node_id, "is_resolved": resolved, "comments": comment_ids})
    return sorted(normalized, key=lambda item: item["node_id"])


def canonical_digest(snapshot: dict[str, Any]) -> str:
    content = {key: value for key, value in snapshot.items() if key not in {"digest", "fetched_at"}}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_history_snapshot(
    *,
    repository: str,
    pull_number: int,
    head_sha: str,
    reviews: list[dict[str, Any]],
    review_comments: list[dict[str, Any]],
    issue_comments: list[dict[str, Any]],
    review_threads: list[dict[str, Any]] | None,
    resolution_source: Literal["graphql", "unknown"],
    fetched_at: str | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "contract": HISTORY_CONTRACT,
        "repository": repository,
        "pull_number": pull_number,
        "head_sha": head_sha,
        "fetched_at": fetched_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "resolution_source": resolution_source,
        "reviews": _dedupe([_normalize_review(item) for item in reviews], "review"),
        "review_comments": _dedupe(
            [_normalize_review_comment(item) for item in review_comments], "review comment"
        ),
        "issue_comments": _dedupe(
            [_normalize_issue_comment(item) for item in issue_comments], "issue comment"
        ),
        "review_threads": _normalize_threads(review_threads),
        "digest": "",
    }
    snapshot["digest"] = canonical_digest(snapshot)
    validate_history_snapshot(snapshot)
    return snapshot


def write_history_snapshot(artifact_dir: Path, snapshot: dict[str, Any]) -> Path:
    path = Path(artifact_dir) / HISTORY_NAME
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _fingerprint(prefix: str, values: list[str]) -> str:
    canonical = "\x1f".join(value.strip() for value in values)
    return prefix + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _normalize_text(value: str) -> str:
    without_markers = _ANY_MARKER_RE.sub("", value)
    return " ".join(without_markers.casefold().split())


def finding_identity(finding: dict[str, Any], head_sha: str, source_agent: str) -> str:
    location = finding.get("code_location") or {}
    return _fingerprint(
        "rbf_",
        [
            "review-bot-finding/v1",
            head_sha.lower(),
            source_agent,
            str(location.get("absolute_file_path") or "").strip(),
            _normalize_text(str(finding.get("title") or "")),
            _normalize_text(str(finding.get("body") or "")),
        ],
    )


def run_identity(repository: str, pull_number: int, head_sha: str) -> str:
    return _fingerprint(
        "rbr_", ["review-bot-run/v1", repository.casefold(), str(pull_number), head_sha.lower()]
    )


def action_identity(finding_id: str, head_sha: str, classification: str) -> str:
    return _fingerprint(
        "rba_",
        ["review-bot-action/v1", finding_id, head_sha.lower(), classification],
    )


def run_marker(run_id: str, head_sha: str) -> str:
    return f"<!-- review-bot-run:v1 run={run_id} head={head_sha.lower()} -->"


def finding_marker(finding_id: str, head_sha: str, source_agent: str) -> str:
    return (
        f"<!-- review-bot-finding:v1 id={finding_id} "
        f"head={head_sha.lower()} agent={source_agent} -->"
    )


def action_marker(action_id: str, finding_id: str, head_sha: str, classification: str) -> str:
    return (
        f"<!-- review-bot-action:v1 id={action_id} finding={finding_id} "
        f"head={head_sha.lower()} status={classification} -->"
    )


def parse_run_markers(body: str) -> tuple[tuple[str, str], ...]:
    return tuple((match.group(1), match.group(2)) for match in _RUN_RE.finditer(body or ""))


def parse_finding_markers(body: str) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (match.group(1), match.group(2), match.group(3))
        for match in _FINDING_RE.finditer(body or "")
    )


def parse_action_markers(body: str) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (match.group(1), match.group(2), match.group(3), match.group(4))
        for match in _ACTION_RE.finditer(body or "")
    )


def _owned(item: dict[str, Any], bot_login: str) -> bool:
    return str(item.get("author") or "").casefold() == bot_login.casefold()


def _target_from_marker(
    marker: tuple[str, str, str], provider: dict[str, Any], run_id: str
) -> dict[str, Any]:
    finding_id, head_sha, source_agent = marker
    provider_id = provider["id"]
    in_reply_to = provider.get("in_reply_to_id")
    return {
        "finding_id": finding_id,
        "run_id": run_id,
        "reviewed_head": head_sha,
        "source_agent": source_agent,
        "surface": provider["surface"],
        "provider_id": provider_id,
        "top_level_comment_id": provider_id
        if provider["surface"] == "review_comment" and in_reply_to is None
        else None,
        "path": provider.get("path"),
        "prior_body": provider.get("body") or "",
        "provider_url": provider.get("url"),
    }


def select_review_mode(
    snapshot: dict[str, Any], bot_login: str, current_head: str
) -> ReviewSelection:
    """Select an initial review, closed-world recheck, or safe no-op."""
    owned_reviews = [item for item in snapshot["reviews"] if _owned(item, bot_login)]
    runs: list[tuple[dict[str, Any], str, str]] = []
    for review in owned_reviews:
        for run_id, head_sha in parse_run_markers(review["body"]):
            runs.append((review, run_id, head_sha))
    if not runs:
        legacy_reviews = sorted(owned_reviews, key=_sort_key)
        if legacy_reviews:
            legacy_review = legacy_reviews[-1]
            legacy_head = str(legacy_review.get("commit_id") or "").lower()
            legacy_comments = [
                item
                for item in snapshot["review_comments"]
                if _owned(item, bot_login)
                and str(item.get("review_id")) == str(legacy_review["id"])
                and item.get("in_reply_to_id") is None
                and item.get("path")
                and not parse_finding_markers(item.get("body") or "")
            ]
            if legacy_head and legacy_comments:
                if legacy_head == current_head.lower():
                    return ReviewSelection(
                        "noop", (), "current head already received an owned legacy review"
                    )
                legacy_run_id = run_identity(
                    snapshot["repository"], snapshot["pull_number"], legacy_head
                )
                legacy_targets = []
                for provider in sorted(legacy_comments, key=_sort_key):
                    finding_id = _fingerprint(
                        "rbf_",
                        [
                            "review-bot-legacy/v1",
                            str(provider["id"]),
                            str(provider.get("path") or ""),
                            _normalize_text(provider.get("body") or ""),
                        ],
                    )
                    legacy_targets.append(
                        {
                            "finding_id": finding_id,
                            "run_id": legacy_run_id,
                            "reviewed_head": legacy_head,
                            "source_agent": "correctness",
                            "surface": "review_comment",
                            "provider_id": provider["id"],
                            "top_level_comment_id": provider["id"],
                            "path": provider.get("path"),
                            "prior_body": provider.get("body") or "",
                            "provider_url": provider.get("url"),
                            "legacy": True,
                        }
                    )
                return ReviewSelection(
                    "recheck",
                    tuple(legacy_targets),
                    "a changed head has uniquely identified App-authored legacy findings",
                    legacy_run_id,
                )
        return ReviewSelection("initial", (), "no completed owned initial review")

    review, run_id, reviewed_head = sorted(runs, key=lambda item: _sort_key(item[0]))[-1]
    if reviewed_head == current_head.lower():
        return ReviewSelection(
            "noop", (), "current head already received its initial review", run_id
        )

    candidates: list[dict[str, Any]] = [review]
    candidates.extend(
        item
        for item in snapshot["review_comments"]
        if str(item.get("review_id")) == str(review["id"])
    )
    targets: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for provider in candidates:
        if not _owned(provider, bot_login):
            continue
        for marker in parse_finding_markers(provider["body"]):
            finding_id, marker_head, _agent = marker
            if marker_head != reviewed_head:
                continue
            if finding_id in targets:
                duplicate_ids.add(finding_id)
                continue
            targets[finding_id] = _target_from_marker(marker, provider, run_id)
    for finding_id in duplicate_ids:
        targets.pop(finding_id, None)

    if not targets:
        return ReviewSelection("initial", (), "latest completed cycle has no owned findings")

    latest_actions: dict[str, tuple[tuple[str, str], str, str]] = {}
    action_objects = [*snapshot["review_comments"], *snapshot["issue_comments"]]
    for provider in action_objects:
        if not _owned(provider, bot_login):
            continue
        for _action_id, finding_id, action_head, status in parse_action_markers(provider["body"]):
            if finding_id not in targets:
                continue
            key = _sort_key(provider)
            previous = latest_actions.get(finding_id)
            if previous is None or key > previous[0]:
                latest_actions[finding_id] = (key, action_head, status)

    pending: list[dict[str, Any]] = []
    pending_evaluated_on_current = True
    terminal_evaluated_on_current = False
    for finding_id, target in sorted(targets.items()):
        latest = latest_actions.get(finding_id)
        if latest is None:
            pending_evaluated_on_current = False
            pending.append(target)
            continue
        _key, action_head, status = latest
        if status in {"unfixed", "ambiguous"}:
            pending.append(target)
            if action_head != current_head.lower():
                pending_evaluated_on_current = False
        elif action_head == current_head.lower():
            terminal_evaluated_on_current = True

    if pending and pending_evaluated_on_current:
        return ReviewSelection(
            "noop", (), "every target was already evaluated on this head", run_id
        )
    if not pending:
        if terminal_evaluated_on_current:
            return ReviewSelection(
                "noop", (), "every target was already evaluated on this head", run_id
            )
        return ReviewSelection("initial", (), "the prior cycle is complete", run_id)
    return ReviewSelection(
        "recheck",
        tuple(pending),
        "a changed head has pending owned findings",
        run_id,
    )


def targets_document(selection: ReviewSelection, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": TARGETS_CONTRACT,
        "repository": snapshot["repository"],
        "pull_number": snapshot["pull_number"],
        "head_sha": snapshot["head_sha"],
        "history_digest": snapshot["digest"],
        "run_id": selection.run_id,
        "targets": list(selection.targets),
    }


def write_targets(artifact_dir: Path, document: dict[str, Any]) -> Path:
    path = Path(artifact_dir) / TARGETS_NAME
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def build_reviewer_view(
    snapshot: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    reviewer: str,
    excluded_paths: set[str] | None = None,
    include_excluded: bool = False,
    max_objects: int = 200,
    max_bytes: int = 131_072,
) -> dict[str, Any]:
    assigned = [target for target in targets if target.get("source_agent") == reviewer]
    base: dict[str, Any] = {
        "contract": VIEW_CONTRACT,
        "reviewer": reviewer,
        "head_sha": snapshot["head_sha"],
        "history_digest": snapshot["digest"],
        "targets": assigned,
        "objects": [],
        "omitted_provider_ids": [],
        "bounds": {"max_objects": max_objects, "max_bytes": max_bytes, "truncated": False},
    }
    required_size = len(
        json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    if required_size > max_bytes:
        raise HistoryError(f"required target data for {reviewer!r} exceeds the byte bound")

    excluded_paths = excluded_paths or set()
    objects = [*snapshot["reviews"], *snapshot["review_comments"], *snapshot["issue_comments"]]
    for item in sorted(objects, key=_sort_key):
        provider_id = str(item["id"])
        path = item.get("path")
        if path and path in excluded_paths and not include_excluded:
            base["omitted_provider_ids"].append(provider_id)
            continue
        candidate = dict(base)
        candidate["objects"] = [*base["objects"], item]
        encoded_size = len(
            json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )
        if len(base["objects"]) >= max_objects or encoded_size > max_bytes:
            base["omitted_provider_ids"].append(provider_id)
            base["bounds"]["truncated"] = True
            continue
        base["objects"].append(item)
    return base


def without_expected_actions(snapshot: dict[str, Any], action_ids: set[str]) -> dict[str, Any]:
    """Return a comparable snapshot with verified plan actions removed."""
    copy = json.loads(json.dumps(snapshot))
    removed_node_ids: set[str] = set()
    for collection in ("review_comments", "issue_comments"):
        retained = []
        for item in copy[collection]:
            if any(marker[0] in action_ids for marker in parse_action_markers(item["body"])):
                if item.get("node_id"):
                    removed_node_ids.add(str(item["node_id"]))
                continue
            retained.append(item)
        copy[collection] = retained
    for thread in copy["review_threads"]:
        thread["comments"] = [
            node_id for node_id in thread["comments"] if node_id not in removed_node_ids
        ]
    copy["digest"] = canonical_digest(copy)
    return copy
