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
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from ..schema import SchemaError, load_schema, validate_review_output
from .registry import AgentSkill, package_digest

DEFAULT_AGENT_TIMEOUT = 1800
DEFAULT_MAX_CONCURRENCY = 4
CODEX_ADMIN_SKILLS_ROOT = Path("/etc/codex/skills")


class HarnessError(RuntimeError):
    """The configured command cannot provide the required isolated harness."""


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


def _validate(spec: AgentSpec, data: dict, duration_seconds: float = 0.0) -> AgentResult:
    try:
        validate_review_output(data)
    except SchemaError as e:
        return AgentResult(
            name=spec.name,
            contract_version=spec.contract_version,
            package_digest=spec.package_digest,
            ok=False,
            error=f"agent output failed schema validation: {e}",
            duration_seconds=duration_seconds,
            extra={"invalid_output": data},
        )
    return AgentResult(
        name=spec.name,
        contract_version=spec.contract_version,
        package_digest=spec.package_digest,
        ok=True,
        output=data,
        duration_seconds=duration_seconds,
    )


@dataclass
class AgentResult:
    """Outcome of one review agent run."""

    name: str
    ok: bool
    contract_version: str = ""
    package_digest: str = ""
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
    contract_version: str = ""
    package_digest: str = ""
    skills: tuple[AgentSkill, ...] = ()
    package_dir: Path | None = None


class AgentRunner:
    """Interface for running one agent in a workspace directory."""

    def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup hook (e.g. temporary schema directories)."""


def run_agents_concurrently(
    runner: AgentRunner,
    invocations: list[tuple[AgentSpec, Path]],
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    on_queued: Callable[[AgentSpec], None] | None = None,
    on_started: Callable[[AgentSpec], None] | None = None,
    on_settled: Callable[[AgentResult], None] | None = None,
) -> list[AgentResult]:
    """Run with bounded concurrency, immediate callbacks, and registry order."""

    def _notify(callback: Callable | None, value: object) -> None:
        if callback is None:
            return
        try:
            callback(value)
        except Exception:
            # Progress observers must never replace or reorder review results.
            return

    def _one(invocation: tuple[AgentSpec, Path]) -> AgentResult:
        spec, workdir = invocation
        _notify(on_started, spec)
        return runner.run(spec, workdir)

    if not invocations:
        return []
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")
    for spec, _workdir in invocations:
        verify_spec_package(spec)
    for spec, _workdir in invocations:
        _notify(on_queued, spec)

    results: list[AgentResult | None] = [None] * len(invocations)
    pool = ThreadPoolExecutor(max_workers=min(len(invocations), max_concurrency))
    needs_shutdown = True
    futures: dict[Future[AgentResult], int] = {}
    try:
        futures = {
            pool.submit(_one, invocation): index for index, invocation in enumerate(invocations)
        }
        for future in as_completed(futures):
            result = future.result()
            results[futures[future]] = result
            _notify(on_settled, result)
    except KeyboardInterrupt:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        needs_shutdown = False
        raise
    except BaseException:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        needs_shutdown = False
        raise
    finally:
        if needs_shutdown:
            pool.shutdown(wait=True)
    return [result for result in results if result is not None]


def verify_spec_package(spec: AgentSpec) -> None:
    """Recompute package identity immediately before a harness launch."""
    if spec.package_dir is None:
        return
    current = package_digest(spec.package_dir)
    if current != spec.package_digest:
        raise HarnessError(
            f"agent package {spec.name!r} changed before launch: "
            f"expected {spec.package_digest}, found {current}"
        )


def verify_harness_command(command: str, harness: str) -> str:
    """Verify the installed real CLI exposes the isolation flags we rely on."""
    expected = Path(command).name
    if harness not in ("pi", "codex") or expected != harness:
        raise HarnessError(f"unsupported review harness command: {command!r}")
    help_cmd = [command, "--help"] if harness == "pi" else [command, "exec", "--help"]
    try:
        version = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=15)
        help_result = subprocess.run(help_cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessError(f"cannot inspect {harness} harness {command!r}: {exc}") from exc
    if version.returncode != 0 or help_result.returncode != 0:
        raise HarnessError(f"cannot inspect {harness} harness {command!r}")
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    required = (
        ("--no-skills", "--skill", "--no-extensions", "--no-context-files")
        if harness == "pi"
        else ("--ignore-user-config", "--ignore-rules", "--sandbox", "--ephemeral")
    )
    missing = [flag for flag in required if flag not in help_text]
    if missing:
        raise HarnessError(
            f"{harness} harness {command!r} lacks required isolation flags: {missing}"
        )
    if harness == "codex":
        _verify_codex_admin_skills_absent()
    return (version.stdout or version.stderr).strip()


def _verify_codex_admin_skills_absent() -> None:
    """Reject machine-level skills outside the per-agent invocation capsule."""
    try:
        admin_skills = sorted(CODEX_ADMIN_SKILLS_ROOT.rglob("SKILL.md"))
    except OSError as exc:
        raise HarnessError(
            f"cannot inspect Codex admin skill scope {CODEX_ADMIN_SKILLS_ROOT}: {exc}"
        ) from exc
    if admin_skills:
        raise HarnessError(
            "Codex admin skill scope must be empty for isolated review runs: "
            f"{CODEX_ADMIN_SKILLS_ROOT}"
        )


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
        self._schema = schema or load_schema()
        self._tmpdir = Path(tempfile.mkdtemp(prefix="review-bot-agent-"))
        self._schema_file = self._tmpdir / "review-output.schema.json"
        self._schema_file.write_text(json.dumps(self._schema), encoding="utf-8")

    def close(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
        verify_spec_package(spec)
        started = time.monotonic()
        out_file = self._tmpdir / f"{spec.name}.json"
        out_file.unlink(missing_ok=True)
        staged_skills = workdir / ".agents" / "skills"
        for skill in spec.skills:
            shutil.copytree(skill.skill_dir, staged_skills / skill.name)
        isolated_home = self._tmpdir / f"{spec.name}-home"
        isolated_codex_home = self._tmpdir / f"{spec.name}-codex-home"
        isolated_home.mkdir()
        isolated_codex_home.mkdir()
        env = self._isolated_env(isolated_home, isolated_codex_home)
        cmd = [
            self.command,
            "exec",
            "--sandbox",
            "read-only",
            "--cd",
            str(workdir),
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            str(self._schema_file),
            "-o",
            str(out_file),
            "--ephemeral",
        ]
        if self.model:
            cmd += ["--model", self.model]
        cmd.append("-")

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
                env=env,
            )
        except subprocess.TimeoutExpired:
            return AgentResult(
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent timed out after {self.timeout}s",
                duration_seconds=time.monotonic() - started,
            )
        except OSError as e:
            return AgentResult(
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent command could not be started: {self.command!r} ({e})",
                duration_seconds=time.monotonic() - started,
            )

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-800:]
            return AgentResult(
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent exited {proc.returncode}: {tail}",
                duration_seconds=time.monotonic() - started,
            )
        if not out_file.exists():
            tail = (proc.stderr or "").strip()[-400:]
            return AgentResult(
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent produced no output file ({tail})",
                duration_seconds=time.monotonic() - started,
            )

        try:
            data = json.loads(out_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError, OSError) as e:
            return AgentResult(
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent output is not readable JSON: {e}",
                duration_seconds=time.monotonic() - started,
            )

        return _validate(spec, data, time.monotonic() - started)

    def _isolated_env(self, home: Path, codex_home: Path) -> dict[str, str]:
        allowed = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "TMPDIR")
        env = {name: os.environ[name] for name in allowed if name in os.environ}
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            env["OPENAI_API_KEY"] = api_key
        source_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        source_auth = source_home / "auth.json"
        if not api_key and source_auth.is_file():
            destination = codex_home / "auth.json"
            shutil.copyfile(source_auth, destination)
            destination.chmod(0o600)
        return env


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
        started = time.monotonic()
        # Allow per-agent thinking overrides (e.g. REVIEW_CORRECTNESS_THINKING).
        per_agent_key = f"REVIEW_{spec.name.upper().replace('-', '_')}_THINKING"
        thinking = os.environ.get(per_agent_key) or self.thinking

        cmd = [
            self.command,
            "--print",
            "--mode",
            "text",
            "--no-skills",
            "--no-extensions",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--no-approve",
            "--tools",
            "read,grep,find,ls",
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
        for skill in spec.skills:
            cmd += ["--skill", str(skill.skill_dir)]
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
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent timed out after {self.timeout}s",
                duration_seconds=time.monotonic() - started,
            )
        except OSError as e:
            return AgentResult(
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent command could not be started: {self.command!r} ({e})",
                duration_seconds=time.monotonic() - started,
            )

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[-800:]
            return AgentResult(
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent exited {proc.returncode}: {tail}",
                duration_seconds=time.monotonic() - started,
            )

        try:
            data = _extract_json(proc.stdout)
        except (json.JSONDecodeError, ValueError) as e:
            tail = proc.stdout.strip()[-800:]
            return AgentResult(
                name=spec.name,
                contract_version=spec.contract_version,
                package_digest=spec.package_digest,
                ok=False,
                error=f"agent output is not valid JSON: {e} ({tail})",
                duration_seconds=time.monotonic() - started,
            )

        return _validate(spec, data, time.monotonic() - started)

    def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
        verify_spec_package(spec)
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
        repair_spec = AgentSpec(
            spec.name,
            repair_prompt,
            spec.input_files,
            spec.contract_version,
            spec.package_digest,
            spec.skills,
            spec.package_dir,
        )
        repaired = self._run_once(repair_spec, repair_prompt_file, workdir)
        if not repaired.ok:
            repaired.error = f"{result.error}; schema repair failed: {repaired.error}"
        return repaired
