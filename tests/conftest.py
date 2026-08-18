"""Shared fixtures: valid review outputs, fake HTTP session, fake agents."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import jwt as pyjwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from review_bot.agents.runner import AgentResult, AgentRunner, AgentSpec


def make_finding(
    title: str = "Off-by-one in pagination",
    path: str = "src/widget/paginate.py",
    start: int = 12,
    end: int = 12,
    priority: int = 2,
    confidence: float = 0.9,
    body: str | None = None,
    replacement: str | None = None,
) -> dict:
    if body is None:
        body = (
            "The code computes `limit * page` but the first page is 1-indexed, so "
            "requesting page 2 skips the first 20 items. Failure scenario: a client "
            "requesting page 2 receives page 3's data."
        )
    return {
        "title": title,
        "body": body,
        "confidence_score": confidence,
        "priority": priority,
        "code_location": {
            "absolute_file_path": path,
            "line_range": {"start": start, "end": end},
        },
        "suggested_fix": {
            "description": "Subtract one from the 1-indexed page before multiplying.",
            "replacement": replacement if replacement else "",
        },
    }


def make_review(findings: list[dict] | None = None, **overrides) -> dict:
    data = {
        "findings": findings if findings is not None else [make_finding()],
        "overall_correctness": "patch is incorrect",
        "overall_explanation": "Found one definite bug in pagination.",
        "overall_confidence_score": 0.85,
        "status": "no_further_concerns",
    }
    data.update(overrides)
    return data


SAMPLE_DIFF = """diff --git a/src/widget/paginate.py b/src/widget/paginate.py
index 1111111..2222222 100644
--- a/src/widget/paginate.py
+++ b/src/widget/paginate.py
@@ -8,2 +8,10 @@
 def paginate(items, page, limit):
+    start = limit * page
+    end = start + limit
+    if page < 1:
+        raise ValueError("page must be >= 1")
     return items[start:end]
+
+
+def page_count(items, limit):
+    return (len(items) + limit - 1) // limit
diff --git a/README.md b/README.md
index 3333333..4444444 100644
--- a/README.md
+++ b/README.md
@@ -1,3 +1,5 @@
 # widget
+
+New section added.
 More text.
"""


@pytest.fixture
def rsa_pem(tmp_path: Path) -> tuple[Path, str]:
    """Generate an RSA keypair; return (private_key_pem_path, public_key_pem)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path = tmp_path / "app.pem"
    path.write_bytes(pem)
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return path, public_pem.decode()


@pytest.fixture
def sample_diff() -> str:
    return SAMPLE_DIFF


class FakeResponse:
    def __init__(self, status_code: int, payload: object | None = None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self._text = text

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json payload")
        return self._payload

    @property
    def text(self) -> str:
        if self._text is not None:
            return self._text
        return json.dumps(self._payload or {})


class FakeSession(requests.Session):
    """Routes (method, url-suffix) -> handler for deterministic API tests."""

    def __init__(self):
        super().__init__()
        self.routes: dict[
            tuple[str, str],
            Callable[[dict[str, str], dict[str, object] | None], object | FakeResponse],
        ] = {}
        self.calls: list[tuple[str, str, dict[str, str], dict[str, object]]] = []
        self.headers: dict[str, str] = {}

    def route(self, method: str, url_suffix: str, handler) -> None:
        self.routes[(method.upper(), url_suffix)] = handler  # type: ignore[assignment]

    def _handle(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> FakeResponse:
        self.calls.append((method.upper(), url, dict(headers or {}), json_body or {}))
        base_url = url.split("?", 1)[0].rstrip("/")
        for (m, suffix), handler in self.routes.items():
            if m == method.upper() and base_url.endswith(suffix.rstrip("/")):
                result = handler(headers or {}, json_body)
                return result if isinstance(result, FakeResponse) else FakeResponse(200, result)
        return FakeResponse(404, {"message": f"no fake route for {method} {url}"})

    def get(self, url, headers=None, timeout=None, **kwargs) -> FakeResponse:
        return self._handle("GET", url, headers, {})

    def post(self, url, headers=None, json=None, timeout=None, **kwargs) -> FakeResponse:
        return self._handle("POST", url, headers, json)


class FakeAgentRunner(AgentRunner):
    """A deterministic AgentRunner returning canned results per agent name."""

    def __init__(self, results: dict[str, object]):
        self.results = results
        self.calls: list[str] = []
        self.specs: list[AgentSpec] = []
        self.closed = False

    def run(self, spec: AgentSpec, workdir: Path) -> AgentResult:
        self.calls.append(spec.name)
        self.specs.append(spec)
        result = self.results.get(spec.name)
        if result is None:
            return AgentResult(name=spec.name, ok=False, error="no canned result")
        if isinstance(result, Exception):
            return AgentResult(name=spec.name, ok=False, error=str(result))
        if isinstance(result, AgentResult):
            return result
        return AgentResult(name=spec.name, ok=True, output=cast(dict[str, Any], result))

    def close(self) -> None:
        self.closed = True


def decode_jwt(token: str, public_pem: str) -> tuple[dict, dict]:
    header = pyjwt.get_unverified_header(token)
    payload = pyjwt.decode(
        token, public_pem.encode(), algorithms=["RS256"], options={"verify_exp": False}
    )
    return payload, header
