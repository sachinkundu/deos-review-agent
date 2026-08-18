"""Agent runner: drives an LLM agent CLI with a prompt and a JSON schema.

The wiring is provider-agnostic: any CLI that accepts a prompt and returns the
final message as JSON works. The default driver is ``pi`` (the local pi coding
agent); ``codex exec`` is also supported. Tests inject a fake runner so no live
model calls happen in the test suite.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..schema import SchemaError, validate_review_output

DEFAULT_AGENT_TIMEOUT = 1800


def _extract_json(text: str) -> dict:
    """Extract the first JSON object from agent output.

    Models sometimes wrap JSON in markdown fences or add explanatory prose;
    this finds the outermost ``{...}`` object.
    """
    # Try the whole text first.
    stripped = text.strip()
    if stripped.startswith("{"):
        # Find the matching closing brace by counting braces.
        depth = 0
        for i, ch in enumerate(stripped):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(stripped[: i + 1])

    # Fallback: look for a fenced JSON block.
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))

    raise ValueError("no JSON object found in agent output")


def _validate(name: str, data: dict) -> AgentResult:
    try:
        validate_review_output(data)
    except SchemaError as e:
        return AgentResult(
            name=name,
            ok=False,
            error=f"agent output failed schema validation: {e}",
            extra={"invalid_output": data},
        )
    return AgentResult(name=name, ok=True, output=data)


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


@dataclass(frozen=True)
class AgentSpec:
    """One agent role with its prompt and explicitly assigned workspace inputs."""

    name: str
    prompt: str
    input_files: tuple[str, ...]


class AgentRunner:
    """Interface for running one agent in a workspace directory."""

    def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup hook (e.g. temporary schema directories)."""


def run_agents_concurrently(
    runner: AgentRunner, specs: list[AgentSpec], workdir: Path
) -> list[AgentResult]:
    """Run every explicit agent spec concurrently; results keep roster order."""

    def _one(spec: AgentSpec) -> AgentResult:
        return runner.run(spec, workdir)

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

    def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
        out_file = self._tmpdir / f"{spec.name}.json"
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

        assigned_inputs = "\n".join(f"- `{name}`" for name in spec.input_files)
        prompt = (
            f"{spec.prompt}\n\n## Assigned input files\n\n{assigned_inputs}\n\n"
            "Read every assigned input file before reviewing.\n"
        )

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
            return AgentResult(
                name=spec.name, ok=False, error=f"agent timed out after {self.timeout}s"
            )
        except FileNotFoundError as e:
            return AgentResult(
                name=spec.name,
                ok=False,
                error=f"agent command not found: {self.command!r} ({e})",
            )

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-800:]
            return AgentResult(
                name=spec.name, ok=False, error=f"agent exited {proc.returncode}: {tail}"
            )
        if not out_file.exists():
            tail = (proc.stderr or "").strip()[-400:]
            return AgentResult(
                name=spec.name, ok=False, error=f"agent produced no output file ({tail})"
            )

        try:
            data = json.loads(out_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return AgentResult(
                name=spec.name, ok=False, error=f"agent output is not valid JSON: {e}"
            )

        return _validate(spec.name, data)


class PiAgentRunner(AgentRunner):
    """Runs agents through the local ``pi`` coding agent.

    Flags used:
      --print               non-interactive, process prompt and exit
      --name NAME           label the persisted session by review stage
      --no-session          optional ephemeral mode when explicitly requested
      --mode text           plain text output (we extract JSON ourselves)
      --thinking <level>    thinking effort (off/minimal/low/medium/high/xhigh/max)
      --model <pattern>     provider/model pattern, e.g. hetzner/kimi-k2.7-code
      --system-prompt FILE  system prompt loaded from a file
      @FILE                 include a workspace file as context
    """

    def __init__(
        self,
        command: str = "pi",
        model: str | None = None,
        thinking: str | None = None,
        timeout: int = DEFAULT_AGENT_TIMEOUT,
        persist_session: bool = True,
    ):
        self.command = command
        self.model = model
        self.thinking = thinking
        self.timeout = timeout
        self.persist_session = persist_session
        self._tmpdir = Path(tempfile.mkdtemp(prefix="review-bot-agent-"))

    def close(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run_once(self, spec: AgentSpec, prompt_file: Path, workdir: Path) -> AgentResult:
        # Allow per-agent thinking overrides (e.g. REVIEW_CORRECTNESS_THINKING).
        per_agent_key = f"REVIEW_{spec.name.upper().replace('-', '_')}_THINKING"
        thinking = os.environ.get(per_agent_key) or self.thinking

        cmd = [
            self.command,
            "--print",
            "--mode",
            "text",
        ]
        if self.persist_session:
            cmd += ["--name", f"review-bot-{spec.name}"]
        else:
            cmd.append("--no-session")
        if thinking:
            cmd += ["--thinking", thinking]
        if self.model:
            cmd += ["--model", self.model]
        cmd += ["--system-prompt", str(prompt_file)]
        cmd += [f"@{input_file}" for input_file in spec.input_files]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(workdir),
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                name=spec.name, ok=False, error=f"agent timed out after {self.timeout}s"
            )
        except FileNotFoundError as e:
            return AgentResult(
                name=spec.name,
                ok=False,
                error=f"agent command not found: {self.command!r} ({e})",
            )

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-800:]
            return AgentResult(
                name=spec.name, ok=False, error=f"agent exited {proc.returncode}: {tail}"
            )

        try:
            data = _extract_json(proc.stdout)
        except (json.JSONDecodeError, ValueError) as e:
            tail = proc.stdout.strip()[-800:]
            return AgentResult(
                name=spec.name,
                ok=False,
                error=f"agent output is not valid JSON: {e} ({tail})",
            )

        return _validate(spec.name, data)

    def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
        prompt_file = self._tmpdir / f"{spec.name}-prompt.md"
        prompt_file.write_text(spec.prompt, encoding="utf-8")

        result = self._run_once(spec, prompt_file, workdir)
        invalid_output = result.extra.get("invalid_output")
        if result.ok or invalid_output is None:
            return result

        repair_prompt = (
            f"{spec.prompt}\n\n"
            "## Schema repair\n\n"
            "Your previous JSON response contained the completed review but failed schema "
            "validation. Correct only its structure and constrained values; preserve the "
            "substantive findings and verdict. Return only the complete corrected JSON object.\n\n"
            f"Validation errors:\n{result.error}\n\n"
            f"Previous JSON:\n```json\n{json.dumps(invalid_output, ensure_ascii=False)}\n```\n"
        )
        repair_prompt_file = self._tmpdir / f"{spec.name}-repair-prompt.md"
        repair_prompt_file.write_text(repair_prompt, encoding="utf-8")
        repair_spec = AgentSpec(spec.name, repair_prompt, spec.input_files)
        repaired = self._run_once(repair_spec, repair_prompt_file, workdir)
        if not repaired.ok:
            repaired.error = f"{result.error}; schema repair failed: {repaired.error}"
        return repaired
