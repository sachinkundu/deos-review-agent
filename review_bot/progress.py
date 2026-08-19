"""Truthful local progress rendering and retained run-state contracts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import IO, Any, Protocol, cast

import jsonschema
from rich.console import Console, ConsoleOptions, RenderResult
from rich.live import Live
from rich.table import Table
from rich.text import Text

EVENT_CONTRACT = "review-progress-event/v1"
SNAPSHOT_CONTRACT = "review-progress-snapshot/v1"
SNAPSHOT_NAME = "progress.json"
SNAPSHOT_SCHEMA_PATH = Path(__file__).parent / "progress_snapshot.schema.json"
MAX_MESSAGE_LENGTH = 160


class ProgressError(RuntimeError):
    """A retained progress snapshot is absent, unreadable, or invalid."""


class Phase(StrEnum):
    CREDENTIALS = "credentials"
    PR_METADATA = "pr-metadata"
    PROVIDER_DIFF = "provider-diff"
    WORKSPACE = "workspace"
    BOOTSTRAP = "bootstrap"
    REGISTRY = "registry"
    REVIEWERS = "reviewers"
    COORDINATION = "coordination"
    SCHEMA_VALIDATION = "schema-validation"
    DIFF_VALIDATION = "diff-validation"
    HEAD_FRESHNESS = "head-freshness"
    PAYLOAD = "payload"
    POSTING = "posting"
    CLEANUP = "cleanup"


class State(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


TERMINAL_STATES = {
    State.SUCCEEDED,
    State.FAILED,
    State.TIMED_OUT,
    State.SKIPPED,
    State.INTERRUPTED,
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def curated_message(value: str) -> str:
    """Accept only bounded, single-line messages chosen by trusted call sites."""
    if not value or len(value) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"progress message must contain 1-{MAX_MESSAGE_LENGTH} characters")
    if any(ord(char) < 32 and char not in ("\t",) for char in value):
        raise ValueError("progress message contains control characters")
    return value


@dataclass
class WorkItem:
    name: str
    state: State
    timeout_seconds: float
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float = 0.0
    error_summary: str | None = None
    started_monotonic: float | None = None

    def serialize(self, monotonic_now: float) -> dict[str, Any]:
        elapsed = self.elapsed_seconds
        if self.state == State.RUNNING and self.started_monotonic is not None:
            elapsed = max(0.0, monotonic_now - self.started_monotonic)
        return {
            "name": self.name,
            "state": self.state.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": round(elapsed, 3),
            "timeout_seconds": self.timeout_seconds,
            "error_summary": self.error_summary,
        }


class ProgressRenderer(Protocol):
    def render(self, event: dict[str, Any], snapshot: dict[str, Any] | None) -> None: ...

    def close(self) -> None: ...


class NullProgressRenderer:
    def render(self, event: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
        return

    def close(self) -> None:
        return


class PlainProgressRenderer:
    def __init__(self, stream: IO[str]):
        self.stream = stream

    def render(self, event: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
        subject = f"/{event['subject']}" if event.get("subject") else ""
        timeout = f" timeout={event['timeout_seconds']}s" if "timeout_seconds" in event else ""
        self.stream.write(
            f"{event['recorded_at']} #{event['sequence']:03d} "
            f"{event['phase']}{subject} {event['state']} "
            f"elapsed={event['elapsed_seconds']}s{timeout} {event['message']}\n"
        )
        self.stream.flush()

    def close(self) -> None:
        return


class JsonProgressRenderer:
    def __init__(self, stream: IO[str]):
        self.stream = stream

    def render(self, event: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
        self.stream.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
        self.stream.flush()

    def close(self) -> None:
        return


class _LiveProgressView:
    """Rich renderable that recomputes active elapsed values on every refresh."""

    def __init__(self, renderer: RichProgressRenderer):
        self.renderer = renderer

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:  # pragma: no cover - exercised through Rich rendering
        yield self.renderer.build_table()


class RichProgressRenderer:
    _STYLES = {
        State.QUEUED.value: "dim",
        State.RUNNING.value: "bold cyan",
        State.SUCCEEDED.value: "bold green",
        State.FAILED.value: "bold red",
        State.TIMED_OUT.value: "bold yellow",
        State.SKIPPED.value: "dim yellow",
        State.INTERRUPTED.value: "bold magenta",
    }

    def __init__(self, stream: IO[str], no_color: bool = False):
        self._lock = threading.RLock()
        self._snapshot: dict[str, Any] | None = None
        self._event: dict[str, Any] | None = None
        self._console = Console(file=stream, no_color=no_color)
        self._live = Live(
            _LiveProgressView(self),
            console=self._console,
            refresh_per_second=4,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._started = False

    def render(self, event: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
        with self._lock:
            self._event = dict(event)
            self._snapshot = snapshot
            if not self._started:
                self._live.start(refresh=True)
                self._started = True
            else:
                self._live.refresh()

    @staticmethod
    def _live_elapsed(item: dict[str, Any]) -> float:
        elapsed = float(item["elapsed_seconds"])
        started_at = item.get("started_at")
        if item.get("state") == State.RUNNING.value and isinstance(started_at, str):
            try:
                started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                elapsed = max(elapsed, (utc_now() - started).total_seconds())
            except ValueError:
                pass
        return elapsed

    def build_table(self) -> Table:
        with self._lock:
            event = dict(self._event or {})
            snapshot = self._snapshot
        table = Table(title="review-bot progress", expand=True)
        table.add_column("Work")
        table.add_column("State")
        table.add_column("Elapsed", justify="right")
        table.add_column("Timeout", justify="right")
        if snapshot:
            overall = snapshot["overall"]
            assert isinstance(overall, dict)
            state = str(overall["state"])
            table.add_row(
                str(overall["phase"]),
                Text(state, style=self._STYLES.get(state, "")),
                f"{float(event.get('elapsed_seconds', 0.0)):.1f}s",
                "—",
            )
            items = list(snapshot["reviewers"])
            coordinator = snapshot.get("coordinator")
            if coordinator:
                items.append(coordinator)
            for raw in items:
                assert isinstance(raw, dict)
                item_state = str(raw["state"])
                table.add_row(
                    str(raw["name"]),
                    Text(item_state, style=self._STYLES.get(item_state, "")),
                    f"{self._live_elapsed(raw):.1f}s",
                    f"{float(raw['timeout_seconds']):g}s",
                )
        elif event:
            state = str(event["state"])
            table.add_row(
                str(event["phase"]),
                Text(state, style=self._STYLES.get(state, "")),
                f"{float(event['elapsed_seconds']):.1f}s",
                "—",
            )
        return table

    def close(self) -> None:
        with self._lock:
            if self._started:
                self._live.stop()
                self._started = False


def create_renderer(mode: str, stream: IO[str] | None = None) -> ProgressRenderer:
    output = cast(IO[str], stream if stream is not None else sys.stderr)
    selected = mode
    if mode == "auto":
        selected = "rich" if output.isatty() else "plain"
    if selected == "off":
        return NullProgressRenderer()
    if selected == "plain":
        return PlainProgressRenderer(output)
    if selected == "json":
        return JsonProgressRenderer(output)
    if selected == "rich":
        return RichProgressRenderer(output, no_color="NO_COLOR" in os.environ)
    raise ValueError(f"unsupported progress mode: {mode}")


@lru_cache(maxsize=1)
def load_snapshot_schema() -> dict[str, Any]:
    return json.loads(SNAPSHOT_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_snapshot(data: Any) -> None:
    errors = sorted(
        jsonschema.Draft202012Validator(load_snapshot_schema()).iter_errors(data),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ProgressError(f"invalid progress snapshot at {location}: {error.message}")


class AtomicSnapshotStore:
    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir
        self.path = artifact_dir / SNAPSHOT_NAME

    def write(self, snapshot: dict[str, Any]) -> None:
        validate_snapshot(snapshot)
        payload = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.artifact_dir,
                prefix=".progress-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class ProgressController:
    """Serialize progress transitions without participating in review decisions."""

    def __init__(
        self,
        mode: str,
        *,
        stream: IO[str] | None = None,
        wall_clock: Callable[[], datetime] = utc_now,
        monotonic_clock: Callable[[], float] = time.monotonic,
        run_id: str | None = None,
    ):
        self.mode = mode
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self.run_id = run_id or uuid.uuid4().hex
        self.started_at = format_utc(wall_clock())
        self._started_monotonic = monotonic_clock()
        self._lock = threading.RLock()
        self._sequence = 0
        self._renderer: ProgressRenderer = create_renderer(mode, stream)
        self._store: AtomicSnapshotStore | None = None
        self._renderer_healthy = True
        self._store_healthy = True
        self._bound: dict[str, Any] | None = None
        self._overall = {"phase": Phase.REGISTRY.value, "state": State.QUEUED.value}
        self._reviewers: list[WorkItem] = []
        self._reviewers_by_name: dict[str, WorkItem] = {}
        self._coordinator: WorkItem | None = None
        self._finished_at: str | None = None
        self._final_exit_code: int | None = None
        self._review_url: str | None = None

    def _now(self) -> tuple[datetime, float]:
        return self._wall_clock(), self._monotonic_clock()

    def _snapshot(self, wall_now: datetime, mono_now: float) -> dict[str, Any] | None:
        if self._bound is None:
            return None
        return {
            "contract": SNAPSHOT_CONTRACT,
            "run_id": self.run_id,
            **self._bound,
            "overall": dict(self._overall),
            "started_at": self.started_at,
            "updated_at": format_utc(wall_now),
            "finished_at": self._finished_at,
            "reviewers": [item.serialize(mono_now) for item in self._reviewers],
            "coordinator": (self._coordinator.serialize(mono_now) if self._coordinator else None),
            "final_exit_code": self._final_exit_code,
            "review_url": self._review_url,
        }

    def _event(
        self,
        phase: Phase,
        state: State,
        message: str,
        wall_now: datetime,
        mono_now: float,
        *,
        subject: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self._sequence += 1
        event: dict[str, Any] = {
            "contract": EVENT_CONTRACT,
            "run_id": self.run_id,
            "sequence": self._sequence,
            "recorded_at": format_utc(wall_now),
            "elapsed_seconds": round(max(0.0, mono_now - self._started_monotonic), 3),
            "phase": phase.value,
            "state": state.value,
            "message": curated_message(message),
        }
        if subject is not None:
            event["subject"] = subject
        if timeout_seconds is not None:
            event["timeout_seconds"] = timeout_seconds
        return event

    def _publish(
        self,
        phase: Phase,
        state: State,
        message: str,
        *,
        subject: str | None = None,
        timeout_seconds: float | None = None,
        update_overall: bool = True,
    ) -> None:
        with self._lock:
            wall_now, mono_now = self._now()
            if update_overall:
                self._overall = {"phase": phase.value, "state": state.value}
            event = self._event(
                phase,
                state,
                message,
                wall_now,
                mono_now,
                subject=subject,
                timeout_seconds=timeout_seconds,
            )
            snapshot = self._snapshot(wall_now, mono_now)
            if self._store is not None and self._store_healthy and snapshot is not None:
                try:
                    self._store.write(snapshot)
                except (OSError, ProgressError):
                    self._store_healthy = False
            if self._renderer_healthy:
                try:
                    self._renderer.render(event, snapshot)
                except (OSError, RuntimeError, ValueError):
                    self._renderer_healthy = False
                    with suppress(Exception):  # pragma: no cover - best-effort restoration
                        self._renderer.close()

    def phase(
        self, phase: Phase, state: State, message: str, *, update_overall: bool = True
    ) -> None:
        if state == State.SKIPPED:
            with self._lock:
                wall_now, _mono_now = self._now()
                if phase == Phase.REVIEWERS:
                    for item in self._reviewers:
                        if item.state == State.QUEUED:
                            item.state = State.SKIPPED
                            item.finished_at = format_utc(wall_now)
                elif (
                    phase == Phase.COORDINATION
                    and self._coordinator is not None
                    and self._coordinator.state == State.QUEUED
                ):
                    self._coordinator.state = State.SKIPPED
                    self._coordinator.finished_at = format_utc(wall_now)
        self._publish(phase, state, message, update_overall=update_overall)

    def bind_workspace(
        self,
        artifact_dir: Path,
        *,
        repository: str,
        pull_request: int,
        head_sha: str,
        dry_run: bool,
        harness: str,
        max_concurrency: int,
        reviewer_names: list[str],
        coordinator_name: str | None,
        timeout_seconds: float,
    ) -> None:
        with self._lock:
            self._bound = {
                "repository": repository,
                "pull_request": pull_request,
                "head_sha": head_sha,
                "mode": "dry-run" if dry_run else "post",
                "harness": harness,
                "max_concurrency": max_concurrency,
            }
            self._reviewers = [
                WorkItem(name=name, state=State.QUEUED, timeout_seconds=timeout_seconds)
                for name in reviewer_names
            ]
            self._reviewers_by_name = {item.name: item for item in self._reviewers}
            self._coordinator = (
                WorkItem(
                    name=coordinator_name,
                    state=State.QUEUED,
                    timeout_seconds=timeout_seconds,
                )
                if coordinator_name
                else None
            )
            self._store = AtomicSnapshotStore(artifact_dir)
            wall_now, mono_now = self._now()
            snapshot = self._snapshot(wall_now, mono_now)
            assert snapshot is not None
            try:
                self._store.write(snapshot)
            except (OSError, ProgressError):
                self._store_healthy = False

    def reviewer_queued(self, name: str, timeout_seconds: float) -> None:
        self._publish(
            Phase.REVIEWERS,
            State.QUEUED,
            "reviewer queued",
            subject=name,
            timeout_seconds=timeout_seconds,
            update_overall=False,
        )

    def reviewer_started(self, name: str, timeout_seconds: float) -> None:
        with self._lock:
            item = self._reviewers_by_name[name]
            wall_now, mono_now = self._now()
            item.state = State.RUNNING
            item.started_at = format_utc(wall_now)
            item.started_monotonic = mono_now
        self._publish(
            Phase.REVIEWERS,
            State.RUNNING,
            "reviewer running",
            subject=name,
            timeout_seconds=timeout_seconds,
            update_overall=False,
        )

    def reviewer_settled(self, name: str, ok: bool, timed_out: bool = False) -> None:
        state = State.SUCCEEDED if ok else State.TIMED_OUT if timed_out else State.FAILED
        with self._lock:
            item = self._reviewers_by_name[name]
            wall_now, mono_now = self._now()
            item.state = state
            item.finished_at = format_utc(wall_now)
            if item.started_monotonic is not None:
                item.elapsed_seconds = max(0.0, mono_now - item.started_monotonic)
            item.error_summary = (
                None if ok else "reviewer timed out" if timed_out else "reviewer failed"
            )
        self._publish(
            Phase.REVIEWERS,
            state,
            "reviewer succeeded"
            if ok
            else "reviewer timed out"
            if timed_out
            else "reviewer failed",
            subject=name,
            timeout_seconds=item.timeout_seconds,
            update_overall=False,
        )

    def coordinator_started(self) -> None:
        if self._coordinator is None:
            return
        wall_now, mono_now = self._now()
        with self._lock:
            self._coordinator.state = State.RUNNING
            self._coordinator.started_at = format_utc(wall_now)
            self._coordinator.started_monotonic = mono_now
        self._publish(
            Phase.COORDINATION,
            State.RUNNING,
            "coordinator running",
            subject=self._coordinator.name,
            timeout_seconds=self._coordinator.timeout_seconds,
        )

    def coordinator_settled(self, ok: bool, timed_out: bool = False) -> None:
        if self._coordinator is None:
            return
        state = State.SUCCEEDED if ok else State.TIMED_OUT if timed_out else State.FAILED
        wall_now, mono_now = self._now()
        with self._lock:
            self._coordinator.state = state
            self._coordinator.finished_at = format_utc(wall_now)
            if self._coordinator.started_monotonic is not None:
                self._coordinator.elapsed_seconds = max(
                    0.0, mono_now - self._coordinator.started_monotonic
                )
            self._coordinator.error_summary = (
                None if ok else "coordinator timed out" if timed_out else "coordinator failed"
            )
        self._publish(
            Phase.COORDINATION,
            state,
            "coordinator succeeded"
            if ok
            else "coordinator timed out"
            if timed_out
            else "coordinator failed",
            subject=self._coordinator.name,
            timeout_seconds=self._coordinator.timeout_seconds,
        )

    def set_review_url(self, review_url: str | None) -> None:
        if review_url:
            with self._lock:
                self._review_url = review_url

    def finish(self, exit_code: int) -> None:
        with self._lock:
            wall_now, mono_now = self._now()
            for item in [*self._reviewers, self._coordinator]:
                if item is None or item.state in TERMINAL_STATES:
                    continue
                item.state = State.SKIPPED if item.state == State.QUEUED else State.FAILED
                item.finished_at = format_utc(wall_now)
                if item.started_monotonic is not None:
                    item.elapsed_seconds = max(0.0, mono_now - item.started_monotonic)
                if item.state == State.FAILED:
                    item.error_summary = "run stopped"
            self._final_exit_code = exit_code
            self._finished_at = format_utc(wall_now)
            if (
                self._overall["state"] not in (State.INTERRUPTED.value, State.SKIPPED.value)
                or exit_code != 0
            ):
                self._overall["state"] = (
                    State.SUCCEEDED.value if exit_code == 0 else State.FAILED.value
                )
            snapshot = self._snapshot(wall_now, mono_now)
            if self._store is not None and self._store_healthy and snapshot is not None:
                try:
                    self._store.write(snapshot)
                except (OSError, ProgressError):
                    self._store_healthy = False

    def interrupt(self) -> None:
        with self._lock:
            wall_now, mono_now = self._now()
            for item in [*self._reviewers, self._coordinator]:
                if item is not None and item.state == State.RUNNING:
                    item.state = State.INTERRUPTED
                    item.finished_at = format_utc(wall_now)
                    if item.started_monotonic is not None:
                        item.elapsed_seconds = max(0.0, mono_now - item.started_monotonic)
                    item.error_summary = "interrupted"
            self._finished_at = format_utc(wall_now)
        phase = Phase(self._overall["phase"])
        self._publish(phase, State.INTERRUPTED, "run interrupted")

    def detach_store(self) -> None:
        with self._lock:
            self._store = None

    def close(self) -> None:
        with suppress(Exception):  # pragma: no cover - best-effort terminal restoration
            self._renderer.close()


def read_snapshot(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProgressError(f"progress snapshot not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProgressError(f"progress snapshot is unreadable: {path}") from exc
    validate_snapshot(data)
    assert isinstance(data, dict)
    return data


def format_status(snapshot: dict[str, Any]) -> str:
    def elapsed(item: dict[str, Any]) -> float:
        value = float(item["elapsed_seconds"])
        started_at = item.get("started_at")
        if item.get("state") == State.RUNNING.value and isinstance(started_at, str):
            try:
                started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                value = max(value, (utc_now() - started).total_seconds())
            except ValueError:
                pass
        return value

    overall = snapshot["overall"]
    assert isinstance(overall, dict)
    lines = [
        f"review-bot status: {snapshot['repository']}#{snapshot['pull_request']}",
        f"run: {snapshot['run_id']}",
        f"head: {snapshot['head_sha']}",
        f"overall: {overall['phase']} / {overall['state']}",
        f"mode: {snapshot['mode']}  harness: {snapshot['harness']}  "
        f"concurrency: {snapshot['max_concurrency']}",
    ]
    for raw in snapshot["reviewers"]:
        assert isinstance(raw, dict)
        lines.append(
            f"reviewer {raw['name']}: {raw['state']} "
            f"elapsed={elapsed(raw):.1f}s/"
            f"{float(raw['timeout_seconds']):g}s"
        )
    coordinator = snapshot.get("coordinator")
    if isinstance(coordinator, dict):
        lines.append(
            f"coordinator {coordinator['name']}: {coordinator['state']} "
            f"elapsed={elapsed(coordinator):.1f}s/"
            f"{float(coordinator['timeout_seconds']):g}s"
        )
    lines.append(f"exit: {snapshot['final_exit_code']}")
    if snapshot.get("review_url"):
        lines.append(f"review: {snapshot['review_url']}")
    return "\n".join(lines)
