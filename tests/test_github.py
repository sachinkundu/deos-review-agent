"""Deterministic tests for the GitHub App client."""

from __future__ import annotations

from typing import Any, cast

import pytest

from review_bot.github import (
    Credentials,
    CredentialsError,
    GitHubAppClient,
    GitHubError,
    event_for_findings,
    extract_linked_issue_references,
    parse_pr_url,
)
from tests.conftest import FakeResponse, FakeSession, decode_jwt, make_finding


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/owner/repo/pull/42", ("owner", "repo", 42)),
        ("https://github.com/some-org/repo-name/pull/1/", ("some-org", "repo-name", 1)),
        (
            "https://github.com/owner/repo/pull/7/files#diff-abc",
            ("owner", "repo", 7),
        ),
    ],
)
def test_parse_pr_url(url, expected):
    assert parse_pr_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "https://github.com/owner/repo/issues/42",
        "https://gitlab.com/owner/repo/pull/42",
    ],
)
def test_parse_pr_url_rejects_bad_input(url):
    with pytest.raises(ValueError, match="not a GitHub pull request URL"):
        parse_pr_url(url)


@pytest.mark.parametrize(
    "title,body,expected",
    [
        ("Fix bug", "Closes #123", ["#123"]),
        ("Fix #456", "", ["#456"]),
        (
            "SAC-87 fix",
            "Fixes #1 and resolves https://github.com/o/r/issues/2",
            ["#1", "https://github.com/o/r/issues/2", "SAC-87"],
        ),
        ("Work", "Just work", []),
    ],
)
def test_extract_linked_issue_references(title, body, expected):
    assert extract_linked_issue_references(title, body) == expected


def test_event_for_findings():
    assert event_for_findings([]) == "COMMENT"
    assert event_for_findings([make_finding(priority=0)]) == "COMMENT"
    assert event_for_findings([make_finding(priority=1)]) == "COMMENT"
    assert event_for_findings([make_finding(priority=2)]) == "REQUEST_CHANGES"
    assert (
        event_for_findings([make_finding(priority=1), make_finding(priority=2)])
        == "REQUEST_CHANGES"
    )


def test_mint_app_jwt_claims(rsa_pem):
    key_path, public_pem = rsa_pem
    creds = Credentials(
        app_id="123456",
        installation_id="98765432",
        private_key_path=str(key_path),
    )
    client = GitHubAppClient(creds)
    token = client.mint_app_jwt()
    payload, header = decode_jwt(token, public_pem)
    assert header["alg"] == "RS256"
    assert payload["iss"] == "123456"
    assert payload["iat"] <= payload["exp"]
    assert payload["exp"] - payload["iat"] <= 10 * 60


def test_mint_app_jwt_fails_fast_with_bad_key(tmp_path):
    bad_key = tmp_path / "bad.pem"
    bad_key.write_text("not a key")
    creds = Credentials(
        app_id="123",
        installation_id="456",
        private_key_path=str(bad_key),
    )
    client = GitHubAppClient(creds)
    with pytest.raises(CredentialsError):
        client.mint_app_jwt()


def test_mint_installation_token(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route(
        "POST",
        "/app/installations/123/access_tokens",
        lambda _h, _b: FakeResponse(
            201, {"token": "ghs_install_token", "expires_at": "2026-01-01T00:00:00Z"}
        ),
    )
    creds = Credentials(
        app_id="1",
        installation_id="123",
        private_key_path=str(key_path),
    )
    client = GitHubAppClient(creds, session=session)
    token = client.mint_installation_token("owner/repo")
    assert token == "ghs_install_token"
    assert session.calls[-1][0] == "POST"
    assert "repositories" in session.calls[-1][3]


def test_mint_installation_token_fails_fast_on_401(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route(
        "POST",
        "/app/installations/123/access_tokens",
        lambda _h, _b: FakeResponse(401, {"message": "Bad credentials"}),
    )
    creds = Credentials(
        app_id="1",
        installation_id="123",
        private_key_path=str(key_path),
    )
    client = GitHubAppClient(creds, session=session)
    with pytest.raises(CredentialsError):
        client.mint_installation_token("owner/repo")


def test_fetch_pr(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route(
        "GET",
        "/repos/owner/repo/pulls/7",
        lambda _h, _b: {
            "title": "A PR",
            "body": "Fixes #42",
            "head": {
                "sha": "abc123",
                "ref": "feature-branch",
                "repo": {
                    "full_name": "owner/repo",
                    "clone_url": "https://github.com/owner/repo.git",
                },
            },
            "base": {"sha": "def456"},
            "user": {"login": "human"},
            "url": "https://api.github.com/repos/owner/repo/pulls/7",
        },
    )
    session.route(
        "GET",
        "/repos/owner/repo/pulls/7/files",
        lambda _h, _b: [{"filename": "src/a.py"}],
    )
    creds = Credentials(
        app_id="1",
        installation_id="123",
        private_key_path=str(key_path),
    )
    client = GitHubAppClient(creds, session=session)
    pr = client.fetch_pr("owner", "repo", 7, token="tok")
    assert pr.number == 7
    assert pr.title == "A PR"
    assert pr.head_sha == "abc123"
    assert pr.base_sha == "def456"
    assert pr.sender_login == "human"
    assert pr.head_ref == "feature-branch"
    assert pr.changed_files == ["src/a.py"]


def test_fetch_pr_diff(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route(
        "GET", "/repos/owner/repo/pulls/7", lambda _h, _b: FakeResponse(200, text="diff text")
    )
    creds = Credentials(
        app_id="1",
        installation_id="123",
        private_key_path=str(key_path),
    )
    client = GitHubAppClient(creds, session=session)
    diff = client.fetch_pr_diff("owner", "repo", 7, token="tok")
    assert diff == "diff text"
    _, _, headers, _ = session.calls[-1]
    assert headers["Accept"] == "application/vnd.github.v3.diff"


def test_bot_username_derived_from_app_slug(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route("GET", "/app", lambda _h, _b: {"slug": "reviewy-bot"})
    creds = Credentials(
        app_id="1",
        installation_id="123",
        private_key_path=str(key_path),
    )
    client = GitHubAppClient(creds, session=session)
    assert client.bot_username() == "reviewy-bot[bot]"


def test_bot_username_override(rsa_pem):
    key_path, _ = rsa_pem
    creds = Credentials(
        app_id="1",
        installation_id="123",
        private_key_path=str(key_path),
        bot_username="custom[bot]",
    )
    client = GitHubAppClient(creds, session=FakeSession())
    assert client.bot_username() == "custom[bot]"


def test_post_review(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route(
        "POST",
        "/repos/owner/repo/pulls/7/reviews",
        lambda _h, b: {"id": 99, "state": "REQUESTED_CHANGES"},
    )
    creds = Credentials(
        app_id="1",
        installation_id="123",
        private_key_path=str(key_path),
    )
    client = GitHubAppClient(creds, session=session)
    result = client.post_review(
        "owner",
        "repo",
        7,
        commit_id="abc123",
        event="REQUEST_CHANGES",
        body="summary",
        comments=[{"path": "a.py", "side": "RIGHT", "line": 3, "body": "bug"}],
        token="tok",
    )
    assert result["id"] == 99
    _, _, _headers, body = session.calls[-1]
    body = cast(dict[str, Any], body)
    assert body["commit_id"] == "abc123"
    assert body["event"] == "REQUEST_CHANGES"
    comments = cast(list[dict[str, Any]], body["comments"])
    assert comments[0]["side"] == "RIGHT"


def test_build_inline_comments_includes_start_side_for_multiline():
    from review_bot.github import build_inline_comments

    finding = make_finding(path="a.py", start=3, end=7)
    comments = build_inline_comments([(finding, 0)])
    assert comments[0]["path"] == "a.py"
    assert comments[0]["line"] == 7
    assert comments[0]["start_line"] == 3
    assert comments[0]["start_side"] == "RIGHT"


def test_post_review_surfaces_provider_error(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route(
        "POST",
        "/repos/owner/repo/pulls/7/reviews",
        lambda _h, _b: FakeResponse(
            422, {"message": "Validation Failed", "errors": ["Line not in diff"]}
        ),
    )
    creds = Credentials(
        app_id="1",
        installation_id="123",
        private_key_path=str(key_path),
    )
    client = GitHubAppClient(creds, session=session)
    with pytest.raises(GitHubError, match="Line not in diff"):
        client.post_review("owner", "repo", 7, "abc", "COMMENT", "body", [], token="tok")


def test_required_history_rest_feeds_follow_link_pagination(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    review_calls = 0

    def reviews(_headers, _body):
        nonlocal review_calls
        review_calls += 1
        if review_calls == 1:
            return FakeResponse(
                200,
                [{"id": 1}],
                headers={
                    "Link": (
                        "<https://api.github.com/repos/owner/repo/pulls/7/reviews?page=2>; "
                        'rel="next"'
                    )
                },
            )
        return FakeResponse(200, [{"id": 2}])

    session.route("GET", "/repos/owner/repo/pulls/7/reviews", reviews)
    session.route("GET", "/repos/owner/repo/pulls/7/comments", lambda _h, _b: [])
    session.route("GET", "/repos/owner/repo/issues/7/comments", lambda _h, _b: [])
    session.route("POST", "/graphql", lambda _h, _b: FakeResponse(403, {"message": "forbidden"}))
    client = GitHubAppClient(
        Credentials(app_id="1", installation_id="2", private_key_path=str(key_path)),
        session=session,
    )
    history = client.fetch_complete_history("owner", "repo", 7, "a" * 40, "tok")
    assert [review["id"] for review in history["reviews"]] == [1, 2]
    assert review_calls == 2
    assert history["resolution_source"] == "unknown"


def test_required_history_rest_failure_stops_instead_of_returning_partial(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route(
        "GET",
        "/repos/owner/repo/pulls/7/reviews",
        lambda _h, _b: FakeResponse(500, {"message": "provider failure"}),
    )
    client = GitHubAppClient(
        Credentials(app_id="1", installation_id="2", private_key_path=str(key_path)),
        session=session,
    )
    with pytest.raises(GitHubError, match="provider failure"):
        client.fetch_reviews("owner", "repo", 7, "tok")


def test_graphql_paginates_threads_and_each_comment_connection(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()

    def graphql(_headers, body):
        variables = body["variables"]
        if "thread" in variables:
            return {
                "data": {
                    "node": {
                        "comments": {
                            "nodes": [{"id": "C2"}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        if variables["cursor"] is None:
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [
                                    {
                                        "id": "T1",
                                        "isResolved": False,
                                        "comments": {
                                            "nodes": [{"id": "C1"}],
                                            "pageInfo": {
                                                "hasNextPage": True,
                                                "endCursor": "comments-1",
                                            },
                                        },
                                    }
                                ],
                                "pageInfo": {"hasNextPage": True, "endCursor": "threads-1"},
                            }
                        }
                    }
                }
            }
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "id": "T2",
                                    "isResolved": True,
                                    "comments": {
                                        "nodes": [{"id": "C3"}],
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    },
                                }
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        }

    session.route("POST", "/graphql", graphql)
    client = GitHubAppClient(
        Credentials(app_id="1", installation_id="2", private_key_path=str(key_path)),
        session=session,
    )
    threads, source = client.fetch_review_threads("owner", "repo", 7, "tok")
    assert source == "graphql"
    assert threads == [
        {"node_id": "T1", "is_resolved": False, "comments": [{"id": "C1"}, {"id": "C2"}]},
        {"node_id": "T2", "is_resolved": True, "comments": [{"id": "C3"}]},
    ]


def test_reply_and_general_comment_use_distinct_provider_surfaces(rsa_pem):
    key_path, _ = rsa_pem
    session = FakeSession()
    session.route(
        "POST",
        "/repos/owner/repo/pulls/7/comments/10/replies",
        lambda _h, body: FakeResponse(201, {"id": 11, "body": body["body"]}),
    )
    session.route(
        "POST",
        "/repos/owner/repo/issues/7/comments",
        lambda _h, body: FakeResponse(201, {"id": 12, "body": body["body"]}),
    )
    client = GitHubAppClient(
        Credentials(app_id="1", installation_id="2", private_key_path=str(key_path)),
        session=session,
    )
    assert client.post_review_reply("owner", "repo", 7, 10, "fixed", "tok")["id"] == 11
    assert client.post_issue_comment("owner", "repo", 7, "fixed", "tok")["id"] == 12
    assert session.calls[-2][1].endswith("/comments/10/replies")
    assert session.calls[-1][1].endswith("/issues/7/comments")
