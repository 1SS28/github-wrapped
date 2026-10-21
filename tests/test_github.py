import inspect
import re
from datetime import datetime, timezone

import httpx
import pytest
import typer

from roastmygithub import cli, github
from tests.conftest import FakeGitHubAPI

SINCE = datetime(2025, 10, 5, 12, tzinfo=timezone.utc)
UNTIL = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
QUERIES = [github.rooted(q, None) for q in (github.OVERVIEW, github.PULL_REQUESTS, github.OWNED)] + [github.HISTORY, github.STARS]


def client(api):
    return github.GitHub("token", transport=api.transport())


# -- The privacy rule ---------------------------------------------------------------


def test_every_query_starts_from_the_token_owner():
    for query in QUERIES:
        body = query[query.index("{") :]
        root = re.match(r"\{\s*(\w+)", body).group(1)
        assert root in ("viewer", "node"), query
        # No way to look up a person or search by name.
        assert not re.search(r"\b(user|organization|search|repositoryOwner)\s*\(", query)
        assert "login:" not in query and "$login" not in query and "$user" not in query


def test_the_cli_never_takes_a_username():
    forbidden = {"user", "username", "login", "account", "handle", "owner"}
    for command in typer.main.get_command(cli.app).commands.values():
        for param in command.params:
            assert param.name not in forbidden and not any(opt.lstrip("-") in forbidden for opt in param.opts)


def test_collect_only_sends_the_viewer_and_node_ids(api):
    with client(api) as gh:
        github.collect(gh, since=SINCE, until=UNTIL)
    for call in api.calls:
        assert set(call["variables"]) <= {"from", "to", "repo", "author", "since", "until", "first", "cursor"}
        assert "user(" not in call["query"]
    history = next(c for c in api.calls if "history(" in c["query"])
    assert history["variables"]["author"] == "U1" and history["variables"]["repo"] == "R1"


# -- Collection ---------------------------------------------------------------------


def test_collect_shapes_the_activity(api):
    with client(api) as gh:
        activity = github.collect(gh, since=SINCE, until=UNTIL)
    assert activity["viewer"] == {"login": "me", "name": "Me Myself", "created_at": "2020-01-01T00:00:00Z"}
    assert activity["since"] == "2025-10-05T12:00:00Z" and activity["until"] == "2026-10-05T12:00:00Z"
    assert activity["totals"] == {"commits": 42, "restricted": 5, "pull_requests": 1, "reviews": 2, "issues": 3, "repos_with_commits": 1, "contributions": 50}
    assert activity["days"] == [{"date": "2026-06-01", "count": 7}]
    assert activity["repos"][0]["languages"] == {"Python": 900, "Shell": 100}
    assert activity["commits"] == [
        {"repo": "me/app", "private": False, "oid": "abc1234", "date": "2026-06-01T01:00:00-04:00", "message": "fix it", "message_length": 6,
         "additions": 5, "deletions": 1, "files": 2, "merge": False}
    ]
    assert activity["pull_requests"][0]["merged"] is True
    assert activity["owned"][0]["stars_in_window"] == 1 and activity["commits_truncated"] is False


def test_history_is_paged_until_the_commit_budget_runs_out():
    page = [(f"commit {i}", "2026-06-01T01:00:00-04:00") for i in range(100)]
    api = FakeGitHubAPI(history_pages={"R1": [page, page, page]})
    with client(api) as gh:
        activity = github.collect(gh, since=SINCE, until=UNTIL, max_commits=150)
    assert len(activity["commits"]) == 150 and activity["commits_truncated"] is True
    assert [c["variables"]["first"] for c in api.calls if "history(" in c["query"]] == [100, 50]

    api = FakeGitHubAPI(history_pages={"R1": [page, page[:10]]})
    with client(api) as gh:
        activity = github.collect(gh, since=SINCE, until=UNTIL, max_commits=3000)
    assert len(activity["commits"]) == 110 and activity["commits_truncated"] is False


def test_long_commit_messages_are_trimmed_but_their_length_is_kept():
    api = FakeGitHubAPI(history_pages={"R1": [[("x" * 5000, "2026-06-01T01:00:00Z")]]})
    with client(api) as gh:
        only = github.collect(gh, since=SINCE, until=UNTIL)["commits"][0]
    assert len(only["message"]) == github.MESSAGE_LIMIT and only["message_length"] == 5000


def test_recent_stars_are_counted_across_pages():
    def page(stamps, more, cursor):
        return {"pageInfo": {"hasNextPage": more, "endCursor": cursor}, "edges": [{"starredAt": s} for s in stamps]}

    recent, old = "2026-02-01T00:00:00Z", "2025-01-01T00:00:00Z"
    api = FakeGitHubAPI(star_pages={"R1": [page([recent] * 100, True, "1"), page([recent] * 30 + [old] * 70, True, "2")]})
    with client(api) as gh:
        owned = github.collect(gh, since=SINCE, until=UNTIL)["owned"][0]
    assert owned["stars_in_window"] == 130 and owned["stars_capped"] is False
    assert sum("stargazers(first: 100, after" in c["query"] and "node(" in c["query"] for c in api.calls) == 1


def test_partial_errors_become_warnings_and_fatal_ones_raise():
    api = FakeGitHubAPI(errors=[{"type": "FORBIDDEN", "message": "Resource protected by organization SAML enforcement."}])
    with client(api) as gh:
        activity = github.collect(gh, since=SINCE, until=UNTIL)
    assert any("SAML" in w for w in activity["warnings"])

    api = FakeGitHubAPI(errors=[{"type": "INTERNAL", "message": "Something went wrong"}])
    with client(api) as gh, pytest.raises(github.GitHubError, match="Something went wrong"):
        gh.whoami()


def test_a_rejected_token_is_explained():
    gh = github.GitHub("bad", transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"message": "Bad credentials"})))
    with pytest.raises(github.GitHubError, match="rejected the token"):
        gh.whoami()


def test_token_comes_from_the_setting_or_the_github_cli(monkeypatch):
    assert github.resolve_token("explicit") == "explicit"
    monkeypatch.setattr(github.shutil, "which", lambda name: None)
    with pytest.raises(github.GitHubError, match="gh auth login"):
        github.resolve_token("")


def test_a_public_login_roots_every_query_at_that_user(api):
    with client(api) as gh:
        activity = github.collect(gh, since=SINCE, until=UNTIL, login="someone")
    assert activity["scope"] == "public" and activity["viewer"]["login"] == "me"  # whatever GitHub returns for it
    rooted = [c for c in api.calls if "contributionsCollection" in c["query"] or "repositories(" in c["query"]]
    assert rooted and all("user(login: $login)" in c["query"] and c["variables"]["login"] == "someone" for c in rooted)
    assert all("viewer" not in c["query"] for c in rooted)


def test_an_unknown_login_is_a_clear_error(api):
    api.user_missing = True
    with client(api) as gh, pytest.raises(github.GitHubError, match="no GitHub user named 'ghost'"):
        github.collect(gh, since=SINCE, until=UNTIL, login="ghost")


def test_repositories_hidden_from_the_token_are_skipped(api):
    original = api._owned_repo
    api._owned_repo = lambda: None  # what GitHub returns for a private repo a public-only token cannot read
    with client(api) as gh:
        activity = github.collect(gh, since=SINCE, until=UNTIL, login="someone")
    assert activity["owned"] == []
    api._owned_repo = original
