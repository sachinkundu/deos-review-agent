"""Deterministic history, cycle, closed-world, and action-plan tests."""

from __future__ import annotations

import json

import pytest

from review_bot.history import (
    HistoryError,
    action_identity,
    action_marker,
    build_history_snapshot,
    build_reviewer_view,
    canonical_digest,
    finding_identity,
    finding_marker,
    run_identity,
    run_marker,
    select_review_mode,
    without_expected_actions,
)
from review_bot.recheck import (
    RecheckError,
    coordinator_prompt,
    plan_recheck_actions,
    reviewer_prompt,
    validate_closed_world,
)
from tests.conftest import make_finding

BOT = "review-bot[bot]"
OLD_HEAD = "a" * 40
NEW_HEAD = "b" * 40


def _review(review_id: int, body: str, author: str = BOT) -> dict:
    return {
        "id": review_id,
        "node_id": f"R_{review_id}",
        "body": body,
        "state": "COMMENTED",
        "commit_id": OLD_HEAD,
        "submitted_at": "2026-08-21T00:00:00Z",
        "html_url": f"https://github.test/review/{review_id}",
        "user": {"login": author},
    }


def _comment(
    comment_id: int,
    body: str,
    *,
    author: str = BOT,
    review_id: int = 1,
    reply_to: int | None = None,
    path: str | None = "src/a.py",
) -> dict:
    return {
        "id": comment_id,
        "node_id": f"C_{comment_id}",
        "body": body,
        "pull_request_review_id": review_id,
        "in_reply_to_id": reply_to,
        "path": path,
        "line": 3,
        "side": "RIGHT",
        "created_at": f"2026-08-21T00:00:{comment_id:02d}Z",
        "updated_at": f"2026-08-21T00:00:{comment_id:02d}Z",
        "html_url": f"https://github.test/comment/{comment_id}",
        "user": {"login": author},
    }


def _snapshot(
    *,
    head: str = NEW_HEAD,
    reviews: list[dict] | None = None,
    comments: list[dict] | None = None,
) -> dict:
    return build_history_snapshot(
        repository="owner/repo",
        pull_number=7,
        head_sha=head,
        reviews=reviews or [],
        review_comments=comments or [],
        issue_comments=[],
        review_threads=[],
        resolution_source="graphql",
        fetched_at="2026-08-21T01:00:00Z",
    )


def _owned_cycle() -> tuple[dict, str, str]:
    run_id = run_identity("owner/repo", 7, OLD_HEAD)
    finding = make_finding(title="Concrete bug", path="src/a.py", body="Fails for input 7")
    finding_id = finding_identity(finding, OLD_HEAD, "correctness")
    snapshot = _snapshot(
        reviews=[_review(1, f"summary\n\n{run_marker(run_id, OLD_HEAD)}")],
        comments=[
            _comment(
                10,
                f"Concrete bug\n\n{finding_marker(finding_id, OLD_HEAD, 'correctness')}",
            )
        ],
    )
    return snapshot, run_id, finding_id


def test_canonical_digest_ignores_fetch_time_and_is_order_deterministic():
    first = _snapshot(comments=[_comment(11, "second"), _comment(10, "first")])
    second = build_history_snapshot(
        repository="owner/repo",
        pull_number=7,
        head_sha=NEW_HEAD,
        reviews=[],
        review_comments=[_comment(10, "first"), _comment(11, "second")],
        issue_comments=[],
        review_threads=[],
        resolution_source="graphql",
        fetched_at="2027-01-01T00:00:00Z",
    )
    assert first["digest"] == second["digest"]
    assert first["review_comments"] == second["review_comments"]
    assert canonical_digest(first) == first["digest"]


def test_conflicting_duplicate_provider_identity_is_rejected():
    with pytest.raises(HistoryError, match="conflicting values"):
        _snapshot(comments=[_comment(10, "first"), _comment(10, "changed")])


def test_human_copied_run_and_finding_markers_do_not_establish_ownership():
    run_id = run_identity("owner/repo", 7, OLD_HEAD)
    finding_id = "rbf_" + "1" * 32
    snapshot = _snapshot(
        reviews=[_review(1, run_marker(run_id, OLD_HEAD), author="human")],
        comments=[
            _comment(
                10,
                finding_marker(finding_id, OLD_HEAD, "correctness"),
                author="human",
            )
        ],
    )
    selection = select_review_mode(snapshot, BOT, NEW_HEAD)
    assert selection.mode == "initial"
    assert selection.targets == ()


def test_unique_app_authored_unmarked_inline_comment_becomes_legacy_target():
    snapshot = _snapshot(
        reviews=[_review(1, "Legacy bot review without markers")],
        comments=[_comment(10, "Concrete legacy defect on this path")],
    )
    selection = select_review_mode(snapshot, BOT, NEW_HEAD)
    assert selection.mode == "recheck"
    assert len(selection.targets) == 1
    assert selection.targets[0]["provider_id"] == 10
    assert selection.targets[0]["legacy"] is True


def test_cycle_selects_recheck_then_same_head_noop_after_owned_action():
    snapshot, _run_id, finding_id = _owned_cycle()
    selection = select_review_mode(snapshot, BOT, NEW_HEAD)
    assert selection.mode == "recheck"
    assert [target["finding_id"] for target in selection.targets] == [finding_id]

    action_id = action_identity(finding_id, NEW_HEAD, "unfixed")
    raw_comments = [
        _comment(
            10,
            f"Concrete bug\n\n{finding_marker(finding_id, OLD_HEAD, 'correctness')}",
        ),
        _comment(
            11,
            action_marker(action_id, finding_id, NEW_HEAD, "unfixed"),
            reply_to=10,
        ),
    ]
    run_id = run_identity("owner/repo", 7, OLD_HEAD)
    evaluated = _snapshot(reviews=[_review(1, run_marker(run_id, OLD_HEAD))], comments=raw_comments)
    repeated = select_review_mode(evaluated, BOT, NEW_HEAD)
    assert repeated.mode == "noop"
    assert "already evaluated" in repeated.reason


def test_same_head_noop_ignores_older_terminal_target_actions():
    intermediate_head = "c" * 40
    run_id = run_identity("owner/repo", 7, OLD_HEAD)
    first_id = finding_identity(
        make_finding(title="First bug", path="src/a.py", body="First failure"),
        OLD_HEAD,
        "correctness",
    )
    second_id = finding_identity(
        make_finding(title="Second bug", path="src/b.py", body="Second failure"),
        OLD_HEAD,
        "tests",
    )
    comments = [
        _comment(10, finding_marker(first_id, OLD_HEAD, "correctness")),
        _comment(11, finding_marker(second_id, OLD_HEAD, "tests"), path="src/b.py"),
        _comment(
            12,
            action_marker(
                action_identity(first_id, intermediate_head, "fixed"),
                first_id,
                intermediate_head,
                "fixed",
            ),
            reply_to=10,
        ),
        _comment(
            13,
            action_marker(
                action_identity(second_id, NEW_HEAD, "unfixed"),
                second_id,
                NEW_HEAD,
                "unfixed",
            ),
            reply_to=11,
            path="src/b.py",
        ),
    ]
    snapshot = _snapshot(
        reviews=[_review(1, run_marker(run_id, OLD_HEAD))],
        comments=comments,
    )

    selection = select_review_mode(snapshot, BOT, NEW_HEAD)

    assert selection.mode == "noop"
    assert "already evaluated" in selection.reason


def test_clean_cycle_new_head_starts_initial_and_same_head_is_noop():
    run_id = run_identity("owner/repo", 7, OLD_HEAD)
    old = _snapshot(reviews=[_review(1, run_marker(run_id, OLD_HEAD))], comments=[])
    assert select_review_mode(old, BOT, OLD_HEAD).mode == "noop"
    assert select_review_mode(old, BOT, NEW_HEAD).mode == "initial"


def test_action_identity_excludes_generated_evidence_text():
    finding_id = "rbf_" + "2" * 32
    first = action_identity(finding_id, NEW_HEAD, "fixed")
    second = action_identity(finding_id, NEW_HEAD, "fixed")
    assert first == second
    assert first != action_identity(finding_id, NEW_HEAD, "unfixed")


def test_reviewer_view_filters_optional_objects_but_keeps_target_identity():
    snapshot, _run_id, _finding_id = _owned_cycle()
    target = select_review_mode(snapshot, BOT, NEW_HEAD).targets[0]
    view = build_reviewer_view(
        snapshot,
        [target],
        reviewer="correctness",
        excluded_paths={"src/a.py"},
    )
    assert view["targets"] == [target]
    assert str(target["provider_id"]) in view["omitted_provider_ids"]


def test_reviewer_view_fails_instead_of_truncating_required_target():
    snapshot, _run_id, _finding_id = _owned_cycle()
    target = select_review_mode(snapshot, BOT, NEW_HEAD).targets[0]
    with pytest.raises(HistoryError, match="required target data"):
        build_reviewer_view(
            snapshot,
            [target | {"prior_body": "x" * 1000}],
            reviewer="correctness",
            max_bytes=100,
        )


def test_closed_world_rejects_unknown_missing_and_duplicate_targets():
    finding_id = "rbf_" + "3" * 32
    valid = {
        "contract": "review-recheck-result/v1",
        "classifications": [
            {
                "finding_id": finding_id,
                "status": "fixed",
                "evidence": "The failing branch now returns the expected value.",
                "confidence_score": 0.9,
            }
        ],
    }
    validate_closed_world(valid, {finding_id}, require_complete=True)
    with pytest.raises(RecheckError, match="unassigned"):
        validate_closed_world(valid, {"rbf_" + "4" * 32}, require_complete=False)
    with pytest.raises(RecheckError, match="omits"):
        validate_closed_world(
            {"contract": "review-recheck-result/v1", "classifications": []},
            {finding_id},
            require_complete=True,
        )
    with pytest.raises(RecheckError, match="more than once"):
        validate_closed_world(
            {
                "contract": "review-recheck-result/v1",
                "classifications": [valid["classifications"][0]] * 2,
            },
            {finding_id},
            require_complete=True,
        )


def test_recheck_coordinator_prompt_forbids_discovery_shape():
    finding_id = "rbf_" + "3" * 32
    prompt = coordinator_prompt([finding_id])
    assert f'"finding_id": "{finding_id}"' in prompt
    assert '"contract": "review-recheck-result/v1"' in prompt
    assert "Never\nreturn `findings`" in prompt


def test_recheck_reviewer_prompt_names_exact_schema_fields():
    finding_id = "rbf_" + "4" * 32
    prompt = reviewer_prompt("correctness", [finding_id])
    assert f'"finding_id": "{finding_id}"' in prompt
    assert '"status": "fixed"' in prompt
    assert '"confidence_score": 0.95' in prompt
    assert "not `classification` or `confidence`" in prompt


def test_plan_uses_reply_for_settled_inline_and_no_action_for_ambiguous():
    snapshot, _run_id, finding_id = _owned_cycle()
    target = select_review_mode(snapshot, BOT, NEW_HEAD).targets[0]
    fixed = {
        "contract": "review-recheck-result/v1",
        "classifications": [
            {
                "finding_id": finding_id,
                "status": "fixed",
                "evidence": "Current code handles the original failing input.",
                "confidence_score": 0.95,
            }
        ],
    }
    plan = plan_recheck_actions(
        repository="owner/repo",
        pull_number=7,
        head_sha=NEW_HEAD,
        history_digest=snapshot["digest"],
        targets=[target],
        result=fixed,
    )
    assert plan["actions"][0]["surface"] == "review_reply"
    assert plan["actions"][0]["target_provider_id"] == 10

    ambiguous = json.loads(json.dumps(fixed))
    ambiguous["classifications"][0]["status"] = "ambiguous"
    ambiguous_plan = plan_recheck_actions(
        repository="owner/repo",
        pull_number=7,
        head_sha=NEW_HEAD,
        history_digest=snapshot["digest"],
        targets=[target],
        result=ambiguous,
    )
    assert ambiguous_plan["actions"] == []


def test_expected_plan_actions_can_be_removed_for_freshness_comparison():
    snapshot, _run_id, finding_id = _owned_cycle()
    action_id = action_identity(finding_id, NEW_HEAD, "fixed")
    action_comment = _comment(
        11,
        action_marker(action_id, finding_id, NEW_HEAD, "fixed"),
        reply_to=10,
    )
    with_action = build_history_snapshot(
        repository="owner/repo",
        pull_number=7,
        head_sha=NEW_HEAD,
        reviews=[_review(1, run_marker(run_identity("owner/repo", 7, OLD_HEAD), OLD_HEAD))],
        review_comments=[
            _comment(
                10,
                finding_marker(finding_id, OLD_HEAD, "correctness"),
            ),
            action_comment,
        ],
        issue_comments=[],
        review_threads=[{"node_id": "T_1", "is_resolved": False, "comments": ["C_10", "C_11"]}],
        resolution_source="graphql",
        fetched_at="2026-08-21T01:00:00Z",
    )
    stripped = without_expected_actions(with_action, {action_id})
    assert all(item["id"] != 11 for item in stripped["review_comments"])
    assert stripped["review_threads"][0]["comments"] == ["C_10"]
