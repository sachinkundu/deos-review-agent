"""Agent runner: drives an LLM agent CLI with a prompt and a JSON schema.

The wiring is provider-agnostic: any CLI that accepts a prompt and returns the
final message as JSON works. The default driver is ``codex exec`` (read-only
sandbox, structured final message via ``--output-schema``). Tests inject a
fake runner so no live model calls happen in the test suite.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..schema import SchemaError, validate_review_output

DEFAULT_AGENT_TIMEOUT = 1800


@dataclass
class AgentResult:
    """Outcome of one review agent run."""

    name: str
    ok: bool
    output: dict | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if self.ok:
            count = len(self.output.get("findings", [])) if self.output else 0
            return f"completed with {count} finding(s)"
        return f"failed: {self.error}"


class AgentRunner:
    """Interface for running one agent in a workspace directory."""

    def run(self, name: str, prompt: str, workdir: Path) -> AgentResult:
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup hook (e.g. temporary schema directories)."""


def run_agents_concurrently(
    runner: AgentRunner, specs: list[tuple[str, str]], workdir: Path
) -> list[AgentResult]:
    """Run every (name, prompt) spec concurrently; results keep spec order."""

    def _one(spec: tuple[str, str]) -> AgentResult:
        name, prompt = spec
        return runner.run(name, prompt, workdir)

    if not specs:
        return []
    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        return list(pool.map(_one, specs))


class CodexAgentRunner(AgentRunner):
    """Runs agents through ``codex exec`` with structured JSON output.

    Flags used:
      --sandbox read-only   agents only read the workspace (no writes)
      --cd <workdir>        the agent works inside the PR checkout
      --output-schema FILE  the model's final message must match the schema
      -o FILE               the final message is written to a file
      --ephemeral           no session files persisted
      -                     the prompt is read from stdin (keeps argv clean)
    """

    def __init__(
        self,
        command: str = "codex",
        model: str | None = None,
        timeout: int = DEFAULT_AGENT_TIMEOUT,
        schema: dict | None = None,
    ):
        self.command = command
        self.model = model
        self.timeout = timeout
        self._schema = schema
        self._tmpdir = Path(tempfile.mkdtemp(prefix="review-bot-agent-"))
        self._schema_file = self._tmpdir / "review-output.schema.json"
        if self._schema is not None:
            self._schema_file.write_text(json.dumps(self._schema), encoding="utf-8")

    def close(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def run(self, name: str, prompt: str, workdir: Path) -> AgentResult:
        out_file = self._tmpdir / f"{name}.json"
        out_file.unlink(missing_ok=True)
        cmd = [
            self.command,
            "exec",
            "--sandbox",
            "read-only",
            "--cd",
            str(workdir),
            "--output-schema",
            str(self._schema_file),
            "-o",
            str(out_file),
            "--ephemeral",
            "-",
        ]
        if self.model:
            cmd += ["--model", self.model]

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(workdir),
            )
        except subprocess.TimeoutExpired:
            return AgentResult(name=name, ok=False, error=f"agent timed out after {self.timeout}s")
        except FileNotFoundError as e:
            return AgentResult(
                name=name, ok=False, error=f"agent command not found: {self.command!r} ({e})"
            )

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-800:]
            return AgentResult(name=name, ok=False, error=f"agent exited {proc.returncode}: {tail}")
        if not out_file.exists():
            tail = (proc.stderr or "").strip()[-400:]
            return AgentResult(name=name, ok=False, error=f"agent produced no output file ({tail})")

        try:
            data = json.loads(out_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return AgentResult(name=name, ok=False, error=f"agent output is not valid JSON: {e}")

        try:
            validate_review_output(data)
        except SchemaError as e:
            return AgentResult(
                name=name, ok=False, error=f"agent output failed schema validation: {e}"
            )

        return AgentResult(name=name, ok=True, output=data)
