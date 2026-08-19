"""Deterministic tests for progress contracts, rendering, and retention."""

from __future__ import annotations

import io
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from review_bot.progress import (
    AtomicSnapshotStore,
    JsonProgressRenderer,
    NullProgressRenderer,
    Phase,
    PlainProgressRenderer,
    ProgressController,
    ProgressError,
    RichProgressRenderer,
    State,
    create_renderer,
    curated_message,
    format_status,
    read_snapshot,
    validate_snapshot,
)


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
        self.monotonic = 100.0

    def wall_now(self) -> datetime:
        return self.wall

    def monotonic_now(self) -> float:
        return self.monotonic

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.monotonic += seconds


class TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def _controller(
    mode: str, stream: io.StringIO, clock: Clock, artifact_dir: Path | None = None
) -> ProgressController:
    controller = ProgressController(
        mode,
        stream=stream,
        wall_clock=clock.wall_now,
        monotonic_clock=clock.monotonic_now,
        run_id="run-123",
    )
    if artifact_dir is not None:
        controller.bind_workspace(
            artifact_dir,
            repository="owner/repo",
            pull_request=7,
            head_sha="abc123",
            dry_run=True,
            harness="pi",
            max_concurrency=2,
            reviewer_names=["correctness", "tests"],
            coordinator_name="coordinator",
            timeout_seconds=30,
        )
    return controller


def test_json_events_are_one_per_line_versioned_and_monotonic(tmp_path: Path):
    stream = io.StringIO()
    clock = Clock()
    controller = _controller("json", stream, clock, tmp_path)
    controller.phase(Phase.REGISTRY, State.RUNNING, "registry discovery running")
    clock.advance(1.25)
    controller.phase(Phase.REGISTRY, State.SUCCEEDED, "registry discovery succeeded")
    controller.close()

    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [event["sequence"] for event in events] == [1, 2]
    assert all(event["contract"] == "review-progress-event/v1" for event in events)
    assert events[1]["elapsed_seconds"] == 1.25
    assert all("\x1b" not in line for line in stream.getvalue().splitlines())


def test_plain_events_are_stable_lines_without_terminal_controls(tmp_path: Path):
    stream = io.StringIO()
    clock = Clock()
    controller = _controller("plain", stream, clock, tmp_path)
    controller.reviewer_queued("correctness", 30)
    controller.reviewer_started("correctness", 30)
    clock.advance(2)
    controller.reviewer_settled("correctness", ok=True)
    controller.close()

    lines = stream.getvalue().splitlines()
    assert len(lines) == 3
    assert "reviewers/correctness queued" in lines[0]
    assert "elapsed=2.0s" in lines[-1]
    assert "\x1b" not in stream.getvalue()


def test_renderer_selection_uses_stderr_tty_and_honors_explicit_modes(monkeypatch):
    assert isinstance(create_renderer("off", io.StringIO()), NullProgressRenderer)
    assert isinstance(create_renderer("plain", TTYBuffer()), PlainProgressRenderer)
    assert isinstance(create_renderer("json", TTYBuffer()), JsonProgressRenderer)
    rich = create_renderer("auto", TTYBuffer())
    assert isinstance(rich, RichProgressRenderer)
    rich.close()
    assert isinstance(create_renderer("auto", io.StringIO()), PlainProgressRenderer)

    monkeypatch.setenv("NO_COLOR", "1")
    no_color = create_renderer("auto", TTYBuffer())
    assert isinstance(no_color, RichProgressRenderer)
    no_color.close()


def test_snapshot_is_exact_schema_and_tracks_registry_order(tmp_path: Path):
    stream = io.StringIO()
    clock = Clock()
    controller = _controller("off", stream, clock, tmp_path)
    controller.reviewer_started("tests", 30)
    clock.advance(4.5)
    controller.reviewer_settled("tests", ok=False)
    controller.finish(3)
    controller.close()

    snapshot = read_snapshot(tmp_path / "progress.json")
    assert list(snapshot) == [
        "contract",
        "run_id",
        "repository",
        "pull_request",
        "head_sha",
        "mode",
        "harness",
        "max_concurrency",
        "overall",
        "started_at",
        "updated_at",
        "finished_at",
        "reviewers",
        "coordinator",
        "final_exit_code",
        "review_url",
    ]
    assert [item["name"] for item in snapshot["reviewers"]] == ["correctness", "tests"]
    assert snapshot["reviewers"][1]["elapsed_seconds"] == 4.5
    assert snapshot["reviewers"][1]["error_summary"] == "reviewer failed"
    assert snapshot["final_exit_code"] == 3


def test_individual_settlement_does_not_claim_roster_success_early(tmp_path: Path):
    controller = _controller("off", io.StringIO(), Clock(), tmp_path)
    controller.phase(Phase.REVIEWERS, State.RUNNING, "reviewer roster running")
    controller.reviewer_started("correctness", 30)
    controller.reviewer_started("tests", 30)
    controller.reviewer_settled("correctness", ok=True)

    snapshot = read_snapshot(tmp_path / "progress.json")
    assert snapshot["reviewers"][0]["state"] == "succeeded"
    assert snapshot["reviewers"][1]["state"] == "running"
    assert snapshot["overall"] == {"phase": "reviewers", "state": "running"}
    controller.interrupt()
    controller.close()


def test_human_status_advances_elapsed_time_for_active_work(monkeypatch, tmp_path: Path):
    clock = Clock()
    controller = _controller("off", io.StringIO(), clock, tmp_path)
    controller.coordinator_started()
    snapshot = read_snapshot(tmp_path / "progress.json")
    monkeypatch.setattr("review_bot.progress.utc_now", lambda: clock.wall + timedelta(seconds=12))

    status = format_status(snapshot)
    assert "coordinator coordinator: running elapsed=12.0s/30s" in status
    controller.interrupt()
    controller.close()


def test_snapshot_schema_rejects_extra_fields_and_bad_timestamps(tmp_path: Path):
    controller = _controller("off", io.StringIO(), Clock(), tmp_path)
    controller.finish(0)
    controller.close()
    snapshot = read_snapshot(tmp_path / "progress.json")
    snapshot["unexpected"] = True
    with pytest.raises(ProgressError, match="Additional properties"):
        validate_snapshot(snapshot)
    snapshot.pop("unexpected")
    snapshot["started_at"] = "not-a-time"
    with pytest.raises(ProgressError, match="does not match"):
        validate_snapshot(snapshot)


def test_atomic_store_never_exposes_partial_json(tmp_path: Path):
    controller = _controller("off", io.StringIO(), Clock(), tmp_path)
    controller.finish(0)
    controller.close()
    initial = read_snapshot(tmp_path / "progress.json")
    store = AtomicSnapshotStore(tmp_path)
    failures: list[Exception] = []

    def reader() -> None:
        for _ in range(100):
            try:
                read_snapshot(tmp_path / "progress.json")
            except Exception as exc:  # pragma: no cover - assertion captures race failures
                failures.append(exc)

    thread = threading.Thread(target=reader)
    thread.start()
    for exit_code in range(100):
        snapshot = dict(initial)
        snapshot["final_exit_code"] = exit_code
        store.write(snapshot)
    thread.join()
    assert failures == []
    assert read_snapshot(tmp_path / "progress.json")["final_exit_code"] == 99
    assert list(tmp_path.glob(".progress-*.tmp")) == []


def test_curated_messages_reject_multiline_and_unbounded_values():
    with pytest.raises(ValueError, match="control characters"):
        curated_message("secret\nsecond line")
    with pytest.raises(ValueError, match="1-160"):
        curated_message("x" * 161)


def test_progress_uses_safe_failure_class_not_agent_error(tmp_path: Path):
    sentinel = "MODEL_OUTPUT_SECRET_SENTINEL"
    stream = io.StringIO()
    controller = _controller("json", stream, Clock(), tmp_path)
    controller.reviewer_started("correctness", 30)
    # The controller deliberately has no API that accepts the raw agent error.
    controller.reviewer_settled("correctness", ok=False)
    controller.finish(3)
    controller.close()

    assert sentinel not in stream.getvalue()
    assert sentinel not in (tmp_path / "progress.json").read_text()
    assert "reviewer failed" in stream.getvalue()


def test_renderer_and_store_failures_do_not_change_control_flow(tmp_path: Path):
    class BrokenRenderer:
        def render(self, event, snapshot):
            raise OSError("closed")

        def close(self):
            return

    class BrokenStore:
        def write(self, snapshot):
            raise OSError("disk full")

    controller = _controller("off", io.StringIO(), Clock())
    controller._renderer = BrokenRenderer()  # type: ignore[reportPrivateUsage]
    controller._store = BrokenStore()  # type: ignore[reportPrivateUsage]
    controller._bound = {  # type: ignore[reportPrivateUsage]
        "repository": "owner/repo",
        "pull_request": 7,
        "head_sha": "abc",
        "mode": "dry-run",
        "harness": "pi",
        "max_concurrency": 1,
    }
    controller.phase(Phase.REGISTRY, State.RUNNING, "registry running")
    controller.phase(Phase.REGISTRY, State.SUCCEEDED, "registry succeeded")
    controller.finish(0)
    controller.close()
