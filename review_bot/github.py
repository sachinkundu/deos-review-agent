"""GitHub App client: JWT + installation token auth, PR fetch, review POST.

Provider contract (verified against the live GitHub REST docs and a real
repository; see openspec change review-bot-phase-1):

- App JWT: RS256-signed with the App private key; claims ``iat`` (now),
  ``exp`` (no more than 10 minutes in the future), ``iss`` (App ID). Passed as
  ``Authorization: Bearer`` (JWTs must use Bearer, not ``token``).
- Installation token: ``POST /app/installations/{installation_id}/access_tokens``
  with the App JWT. Optional body scopes the token to specific repositories
  (``{"repositories": ["owner/repo"]}``). Returns 201 with ``token`` and
  ``expires_at`` (tokens expire one hour from creation; the token string format
  varies, e.g. legacy ``ghs_...`` or the stateless ``ghs_{APPID}_{JWT}`` form,
  so the client must never parse or assume a token shape).
- PR metadata: ``GET /repos/{owner}/{repo}/pulls/{number}`` (``head.sha`` is
  the review target; ``user.login`` is the sender; ``head.repo`` gives the
  clone source).
- PR diff: same endpoint with ``Accept: application/vnd.github.v3.diff``
  returns the raw unified diff.
- Review: ``POST /repos/{owner}/{repo}/pulls/{number}/reviews`` with
  ``commit_id`` (head SHA), ``event`` (APPROVE | REQUEST_CHANGES | COMMENT),
  ``body`` (required for REQUEST_CHANGES and COMMENT), and ``comments`` where
  each comment uses ``path`` + ``side`` (LEFT/RIGHT, default RIGHT) + ``line``
  (line number in the file on that side). A comment whose line is not in the
  diff is rejected by GitHub (422), failing the whole review payload — which
  is why ``diff_validator`` checks every location first.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import jwt
import requests

API_VERSION = "2026-03-10"
JWT_MAX_LIFETIME_SECONDS = 10 * 60
JWT_LIFETIME_SECONDS = 540  # stay under the 10-minute maximum with margin

PR_URL_RE = re.compile(r"^https?://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)(?:/.*)?$")
LINKED_HASH_RE = re.compile(r"#(\d{1,9})")
LINKED_WORD_RE = re.compile(
    r"(?i)\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*:?\s+((?:https?://github\.com/[\w.-]+/[\w.-]+/(?:issues/)?\d+|#\d+))"
)
PROJECT_KEY_RE = re.compile(r"\b([A-Z]{2,10}-\d{1,6})\b")


class GitHubError(Exception):
    """A GitHub API call failed; carries status and the provider error body."""

    def __init__(self, message: str, status: int | None = None, details: object = None):
        self.status = status
        self.details = details
        super().__init__(message)


class CredentialsError(Exception):
    """GitHub App credentials are missing or invalid; fail fast before cloning."""


@dataclass(frozen=True)
class Credentials:
    app_id: str
    installation_id: str
    private_key_path: str
    bot_username: str | None = None  # if unset, derived from GET /app slug + "[bot]"
    base_url: str = "https://api.github.com"


@dataclass
class PRInfo:
    number: int
    title: str
    body: str
    head_sha: str
    base_sha: str
    head_ref: str
    sender_login: str
    head_repo_full_name: str
    head_repo_clone_url: str
    owner: str
    repo: str
    url: str
    changed_files: list[str] = field(default_factory=list)


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Parse ``https://github.com/{owner}/{repo}/pull/{number}`` -> (owner, repo, number)."""
    m = PR_URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"not a GitHub pull request URL: {url!r}")
    return m.group(1), m.group(2), int(m.group(3))


def extract_linked_issue_references(title: str, body: str) -> list[str]:
    """Extract issue references (``Fixes #123``, ``#42``, ``SAC-87``) from PR title/body."""
    text = f"{title}\n{body or ''}"
    refs: list[str] = []

    def add(ref: str) -> None:
        ref = ref.strip()
        if ref and ref not in refs:
            refs.append(ref)

    for m in LINKED_WORD_RE.finditer(text):
        add(m.group(1))
    for m in LINKED_HASH_RE.finditer(text):
        add(f"#{m.group(1)}")
    for m in PROJECT_KEY_RE.finditer(text):
        add(m.group(1))
    return refs


def event_for_findings(findings: list[dict]) -> str:
    """Map the highest-severity finding to the GitHub review event (rubric).

    priority 2 (critical) -> REQUEST_CHANGES; priority 0/1 or no findings ->
    COMMENT. The event follows severity regardless of attachment.
    """
    if any(f.get("priority") == 2 for f in findings):
        return "REQUEST_CHANGES"
    return "COMMENT"


def verdict_for_findings(findings: list[dict]) -> str:
    """Rubric: any finding (warning or critical) means the patch is incorrect."""
    return "patch is incorrect" if findings else "patch is correct"


class GitHubAppClient:
    """Talks to the GitHub REST API as a GitHub App installation.

    A fresh installation token is minted for every operation group (per review
    run); tokens are never logged.
    """

    def __init__(self, credentials: Credentials, session: requests.Session | None = None):
        self._creds = credentials
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "review-bot-phase-2",
            }
        )

    # -- authentication -----------------------------------------------------

    @staticmethod
    def _load_private_key(path: str) -> bytes:
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as e:
            raise CredentialsError(f"cannot read App private key at {path!r}: {e}") from e

    def mint_app_jwt(self) -> str:
        """Mint a short-lived App JWT (RS256; iat=now, exp<10min, iss=App ID)."""
        key = self._load_private_key(self._creds.private_key_path)
        now = int(time.time())
        try:
            return jwt.encode(
                {"iat": now, "exp": now + JWT_LIFETIME_SECONDS, "iss": self._creds.app_id},
                key,
                algorithm="RS256",
            )
        except Exception as e:  # bad key material / bad app id
            raise CredentialsError(f"failed to mint App JWT: {e}") from e

    def _app_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.mint_app_jwt()}"}

    def mint_installation_token(self, repository: str | None = None) -> str:
        """Exchange the App JWT for a short-lived installation token.

        ``repository`` (``owner/repo``) scopes the token to that repository when
        the installation is configured for selected repositories. For
        all-repositories installations, or when GitHub has not yet propagated
        a newly created repo to the scoped-token path, we fall back to an
        unscoped token. Raises CredentialsError on auth failure.
        """
        url = (
            f"{self._creds.base_url}/app/installations/{self._creds.installation_id}/access_tokens"
        )

        def _request(body: dict[str, Any] | None) -> requests.Response:
            return self._session.post(url, headers=self._app_auth_headers(), json=body, timeout=30)

        try:
            if repository:
                resp = _request({"repositories": [repository]})
                if resp.status_code == 201:
                    token = resp.json().get("token")
                    if token:
                        return token
                # Fall back to an unscoped token for all-repositories
                # installations or when the repo is still propagating.
                resp = _request(None)
            else:
                resp = _request(None)
        except requests.RequestException as e:
            raise GitHubError(f"installation token request failed: {e}") from e
        if resp.status_code != 201:
            raise CredentialsError(
                f"installation token minting failed (HTTP {resp.status_code}): {_error_body(resp)}"
            )
        token = resp.json().get("token")
        if not token:
            raise CredentialsError("installation token response did not include a token")
        return token

    def bot_username(self) -> str:
        """The App's bot username, e.g. ``my-app[bot]`` (from GET /app slug)."""
        if self._creds.bot_username:
            return self._creds.bot_username
        resp = self._session.get(
            f"{self._creds.base_url}/app", headers=self._app_auth_headers(), timeout=30
        )
        if resp.status_code != 200:
            raise GitHubError(f"GET /app failed (HTTP {resp.status_code}): {_error_body(resp)}")
        slug = resp.json().get("slug")
        if not slug:
            raise GitHubError("GET /app response did not include a slug")
        return f"{slug}[bot]"

    # -- PR data ------------------------------------------------------------

    def _installation_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"token {token}"}

    def fetch_pr(self, owner: str, repo: str, number: int, token: str | None = None) -> PRInfo:
        token = token or self.mint_installation_token(f"{owner}/{repo}")
        url = f"{self._creds.base_url}/repos/{owner}/{repo}/pulls/{number}"
        resp = self._session.get(url, headers=self._installation_headers(token), timeout=30)
        if resp.status_code != 200:
            raise GitHubError(
                f"PR metadata fetch failed (HTTP {resp.status_code}): {_error_body(resp)}"
            )
        data = resp.json()
        head = data.get("head", {})
        head_repo = head.get("repo", {})
        base = data.get("base", {})
        sender = data.get("user", {}).get("login", "")
        pr = PRInfo(
            number=number,
            title=data.get("title", ""),
            body=data.get("body") or "",
            head_sha=head.get("sha", ""),
            base_sha=base.get("sha", ""),
            head_ref=head.get("ref", ""),
            sender_login=sender,
            head_repo_full_name=head_repo.get("full_name", ""),
            head_repo_clone_url=head_repo.get("clone_url", ""),
            owner=owner,
            repo=repo,
            url=data.get("url", url),
        )
        pr.changed_files = self._fetch_changed_files(owner, repo, number, token)
        if not pr.head_sha:
            raise GitHubError("PR metadata did not include head.sha")
        return pr

    def _fetch_changed_files(self, owner: str, repo: str, number: int, token: str) -> list[str]:
        files: list[str] = []
        page = 1
        while True:
            url = (
                f"{self._creds.base_url}/repos/{owner}/{repo}/pulls/{number}/files"
                f"?per_page=100&page={page}"
            )
            resp = self._session.get(url, headers=self._installation_headers(token), timeout=30)
            if resp.status_code != 200:
                raise GitHubError(
                    f"changed-files fetch failed (HTTP {resp.status_code}): {_error_body(resp)}"
                )
            batch = resp.json()
            files.extend(item.get("filename", "") for item in batch)
            if len(batch) < 100:
                return files
            page += 1

    def fetch_pr_diff(self, owner: str, repo: str, number: int, token: str | None = None) -> str:
        """Fetch the raw unified diff for the PR (right-side lines parseable)."""
        token = token or self.mint_installation_token(f"{owner}/{repo}")
        url = f"{self._creds.base_url}/repos/{owner}/{repo}/pulls/{number}"
        headers = self._installation_headers(token)
        headers["Accept"] = "application/vnd.github.v3.diff"
        resp = self._session.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise GitHubError(
                f"PR diff fetch failed (HTTP {resp.status_code}): {_error_body(resp)}"
            )
        return resp.text

    # -- review -------------------------------------------------------------

    def post_review(
        self,
        owner: str,
        repo: str,
        number: int,
        commit_id: str,
        event: str,
        body: str,
        comments: list[dict],
        token: str | None = None,
    ) -> dict:
        """Post the review bound to ``commit_id`` (the fetched head SHA).

        ``comments`` items must already be diff-validated:
        ``{"path": ..., "side": "RIGHT", "line": n, "start_line"?: m, "body": ...}``.
        Surfaces provider errors (e.g. 422 "Line could not be resolved") to the
        caller; findings are never silently dropped.
        """
        token = token or self.mint_installation_token(f"{owner}/{repo}")
        url = f"{self._creds.base_url}/repos/{owner}/{repo}/pulls/{number}/reviews"
        payload = {"commit_id": commit_id, "body": body, "event": event, "comments": comments}
        resp = self._session.post(
            url, headers=self._installation_headers(token), json=payload, timeout=60
        )
        if resp.status_code not in (200, 201):
            raise GitHubError(
                f"review POST failed (HTTP {resp.status_code}): {_error_body(resp)}",
                status=resp.status_code,
                details=resp.text[:2000],
            )
        return resp.json()


def _error_body(resp: requests.Response) -> str:
    try:
        data = resp.json()
        message = data.get("message", "")
        errors = data.get("errors")
        if errors:
            return f"{message} {json.dumps(errors)[:500]}"
        return message or resp.text[:500]
    except ValueError:
        return resp.text[:500]


def build_inline_comments(attachable: list[tuple[dict, int]]) -> list[dict]:
    """Build GitHub review comment objects for attachable findings.

    Uses ``side`` + ``line`` (line number in the new file) rather than the
    legacy ``position``. Single-line locations send ``line`` only; ranges send
    ``start_line`` + ``line``. ``attachable`` items are
    ``(finding, original_index)`` pairs from ``validate_findings_locations``.
    """
    comments: list[dict] = []
    for finding, _original_index in attachable:
        location = finding["code_location"]
        start = location["line_range"]["start"]
        end = location["line_range"]["end"]
        comment = {
            "path": location["absolute_file_path"],
            "side": "RIGHT",
            "line": end,
            "body": format_comment_body(finding),
        }
        if end > start:
            comment["start_line"] = start
            comment["start_side"] = "RIGHT"
        comments.append(comment)
    return comments


def format_comment_body(finding: dict[str, Any]) -> str:
    """One GitHub comment body per finding: evidence/problem/failure + fix."""
    priority = finding.get("priority")
    label = (
        {0: "suggestion", 1: "warning", 2: "critical"}.get(priority)
        if isinstance(priority, int)
        else None
    )
    label = label or "warning"
    confidence = finding.get("confidence_score")
    parts = [f"**{finding['title']}** ({label}, confidence {confidence})\n"]
    parts.append(finding["body"])
    fix = finding.get("suggested_fix") or {}
    if fix.get("description"):
        parts.append(f"\n**Suggested fix:** {fix['description']}")
        if fix.get("replacement"):
            parts.append(f"\n```\n{fix['replacement']}\n```")
    return "\n".join(parts)
