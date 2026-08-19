"""Isolated local workspace for a PR: clone, checkout, bootstrap, cleanup.

The workspace keeps the exact PR checkout under ``source/`` and every
host-produced review artifact under its sibling ``host-artifacts/``.

- Clone uses the installation token via ``GIT_ASKPASS`` (the token is never on
  the command line or in the URL).
- Checkout is at exactly the head SHA GitHub reported, on a local branch named
  after the PR head branch.
- An optional consumer-provided bootstrap script (``.review-bot/bootstrap.sh``
  in the reviewed repository) prepares project-specific dependencies; a
  bootstrap failure stops the review run.
- The workspace is retained for the review session and removed when the
  single-turn session ends, or explicitly via the ``cleanup`` command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

BOOTSTRAP_SCRIPT = ".review-bot/bootstrap.sh"
DEFAULT_BOOTSTRAP_TIMEOUT = 600
GIT_TIMEOUT = 900


class WorkspaceError(Exception):
    """Clone, checkout, or bootstrap failed; the review run must stop."""


@dataclass
class BootstrapResult:
    ran: bool
    ok: bool
    exit_code: int | None = None
    output_tail: str = ""

    @property
    def summary(self) -> str:
        if not self.ran:
            return "no bootstrap script found"
        if self.ok:
            return "bootstrap succeeded"
        return f"bootstrap failed (exit {self.exit_code}): {self.output_tail[-500:]}"


def workspace_dir_for(root: Path, owner: str, repo: str, number: int) -> Path:
    return Path(root) / f"{owner}-{repo}-pr{number}"


def _git(
    args: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )


def _write_askpass(workdir: Path) -> Path:
    """Write a git askpass helper that reads the token from an env var.

    Keeps the token out of argv (and therefore out of ``ps`` output and git
    error messages that echo URLs).
    """
    script = workdir.parent / f".git-askpass-{workdir.name}.sh"
    script.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  *Username*) echo "x-access-token" ;;\n'
        '  *) echo "$RB_GIT_TOKEN" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script


def _tail(proc: subprocess.CompletedProcess) -> str:
    return (proc.stderr or proc.stdout or "").strip()[-1000:]


# Environment keys that should never be forwarded to an untrusted bootstrap script.
_SENSITIVE_ENV_KEYS: set[str] = {
    "GITHUB_APP_PRIVATE_KEY",
    "GITHUB_APP_ID",
    "GITHUB_APP_INSTALLATION_ID",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CODEX_API_KEY",
    "REVIEW_BOT_PRIVATE_KEY",
}


def _bootstrap_env(extra_env: dict[str, str] | None) -> dict[str, str]:
    """Build a sanitized environment for the consumer bootstrap script.

    Copies standard non-secret variables (PATH, HOME, USER, SHELL, LANG, TZ,
    etc.) and the review-specific non-secret variables, but drops any key that
    looks like a credential.
    """
    safe_keys = {
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TERM",
        "TMPDIR",
        "PWD",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "REVIEW_PR_URL",
        "REVIEW_HEAD_SHA",
        "REVIEW_PR_NUMBER",
    }
    env = {k: v for k, v in os.environ.items() if k in safe_keys}
    env.update(extra_env or {})
    # Also drop any extra_env key that matches a sensitive pattern.
    for key in list(env.keys()):
        upper = key.upper()
        if upper in _SENSITIVE_ENV_KEYS or any(
            pattern in upper for pattern in ("TOKEN", "SECRET", "KEY", "PASSWORD", "CREDENTIAL")
        ):
            env.pop(key, None)
    return env


class PRWorkspace:
    """A workspace bound to one PR under the configured root."""

    def __init__(
        self,
        root: Path,
        owner: str,
        repo: str,
        number: int,
        bootstrap_timeout: int = DEFAULT_BOOTSTRAP_TIMEOUT,
    ):
        self.root = Path(root).expanduser().resolve()
        self.bootstrap_timeout = bootstrap_timeout
        self.workdir = workspace_dir_for(self.root, owner, repo, number)
        self.source_dir = self.workdir / "source"
        self.artifact_dir = self.workdir / "host-artifacts"

    def setup(self, clone_url: str, head_sha: str, branch: str, token: str) -> Path:
        """Clone ``clone_url`` and check out ``head_sha`` on branch ``branch``.

        Raises WorkspaceError when the clone or checkout fails or the checked
        out HEAD does not equal ``head_sha``.
        """
        if self.workdir.exists():
            # A stale workspace from a previous run must not be trusted.
            self.remove()
        self.root.mkdir(parents=True, exist_ok=True)

        askpass = _write_askpass(self.workdir)
        git_env = {"GIT_ASKPASS": str(askpass), "RB_GIT_TOKEN": token}
        try:
            self.workdir.mkdir(parents=True)
            clone = _git(
                ["clone", "--quiet", clone_url, str(self.source_dir)],
                cwd=self.workdir,
                env=git_env,
            )
            if clone.returncode != 0:
                raise WorkspaceError(f"git clone failed: {_tail(clone)}")

            # Fetch the PR head branch so the branch name matches the PR.
            fetch = _git(
                [
                    "fetch",
                    "--quiet",
                    "origin",
                    f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
                ],
                cwd=self.source_dir,
                env=git_env,
            )
            if fetch.returncode != 0:
                raise WorkspaceError(f"git fetch of PR branch {branch!r} failed: {_tail(fetch)}")

            # Ensure the exact head SHA is present (PR refs may hold commits
            # not reachable from the branch tip).
            exists = _git(["cat-file", "-e", f"{head_sha}^{{commit}}"], cwd=self.source_dir)
            if exists.returncode != 0:
                by_sha = _git(
                    ["fetch", "--quiet", "origin", head_sha],
                    cwd=self.source_dir,
                    env=git_env,
                )
                if by_sha.returncode != 0:
                    raise WorkspaceError(
                        f"head SHA {head_sha} could not be fetched: {_tail(by_sha)}"
                    )

            checkout = _git(["checkout", "--quiet", "-B", branch, head_sha], cwd=self.source_dir)
            if checkout.returncode != 0:
                raise WorkspaceError(f"git checkout of head SHA failed: {_tail(checkout)}")

            head = _git(["rev-parse", "HEAD"], cwd=self.source_dir)
            if head.returncode != 0 or head.stdout.strip() != head_sha:
                raise WorkspaceError(
                    f"workspace HEAD is {head.stdout.strip()!r}, expected head SHA {head_sha!r}"
                )
            self.artifact_dir.mkdir()
            return self.source_dir
        finally:
            askpass.unlink(missing_ok=True)

    def run_bootstrap(
        self, workdir: Path, extra_env: dict[str, str] | None = None
    ) -> BootstrapResult:
        """Run the consumer-provided bootstrap script when present.

        The script receives a sanitized environment that excludes App private
        keys, API tokens, and other credentials. It can still read PATH, HOME,
        and review metadata, but cannot exfiltrate host secrets.
        """
        script = workdir / BOOTSTRAP_SCRIPT
        if not script.exists():
            return BootstrapResult(ran=False, ok=True)
        env = _bootstrap_env(extra_env)
        try:
            proc = subprocess.run(
                ["bash", str(script)],
                cwd=str(workdir),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.bootstrap_timeout,
            )
        except subprocess.TimeoutExpired:
            return BootstrapResult(
                ran=True,
                ok=False,
                exit_code=None,
                output_tail=f"timed out after {self.bootstrap_timeout}s",
            )
        output_tail = (proc.stdout + proc.stderr)[-2000:]
        return BootstrapResult(
            ran=True, ok=proc.returncode == 0, exit_code=proc.returncode, output_tail=output_tail
        )

    def remove(self) -> None:
        """Remove the PR workspace (explicit cleanup or session end)."""
        shutil.rmtree(self.workdir, ignore_errors=True)
