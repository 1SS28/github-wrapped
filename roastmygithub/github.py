"""GitHub GraphQL collection for one account's last 12 months.

Two roots: the CLI collects the token's own account (`viewer`), with private activity the token
can see; the web app collects any public account (`user(login:)`), which GitHub limits to
public activity. Every other query starts from a node id the root query returned. The CLI
never passes a login, so it cannot be pointed at another person (tests enforce that).

`collect()` returns one plain dict (the "activity") that is cached as JSON; `stats.py` turns it
into numbers. Commit messages and timestamps come from each repository's default branch,
filtered to commits the viewer authored.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

GRAPHQL_URL = "https://api.github.com/graphql"
SCHEMA_VERSION = 2  # 2: commits carry their short hash
MESSAGE_LIMIT = 600  # characters of each commit message kept in the cache
MAX_STAR_PAGES = 20  # 100 stars per page, per repository
MAX_PR_PAGES = 5
MAX_OWNED_PAGES = 4  # 50 repositories per page

OVERVIEW = """
query($from: DateTime!, $to: DateTime!{LOGIN_VAR}) {
  {ROOT} {
    id login name createdAt
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      totalRepositoriesWithContributedCommits
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
      commitContributionsByRepository(maxRepositories: 100) {
        contributions { totalCount }
        repository {
          id nameWithOwner isPrivate isFork stargazerCount
          primaryLanguage { name }
          languages(first: 8, orderBy: {field: SIZE, direction: DESC}) { totalSize edges { size node { name } } }
        }
      }
    }
  }
}"""

HISTORY = """
query($repo: ID!, $author: ID!, $since: GitTimestamp!, $until: GitTimestamp!, $first: Int!, $cursor: String) {
  node(id: $repo) { ... on Repository { defaultBranchRef { target { ... on Commit {
    history(first: $first, after: $cursor, since: $since, until: $until, author: {id: $author}) {
      pageInfo { hasNextPage endCursor }
      nodes { abbreviatedOid message additions deletions changedFilesIfAvailable author { date } parents { totalCount } }
    }
  } } } } }
}"""

PULL_REQUESTS = """
query($from: DateTime!, $to: DateTime!, $cursor: String{LOGIN_VAR}) {
  {ROOT} { contributionsCollection(from: $from, to: $to) {
    pullRequestContributions(first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { pullRequest { merged mergedAt createdAt repository { nameWithOwner isPrivate } } }
    }
  } }
}"""

OWNED = """
query($cursor: String{LOGIN_VAR}) {
  {ROOT} { repositories(first: 50, after: $cursor, ownerAffiliations: OWNER, isFork: false,
                        orderBy: {field: STARGAZERS, direction: DESC}) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id nameWithOwner isPrivate isArchived stargazerCount createdAt pushedAt
      stargazers(first: 100, orderBy: {field: STARRED_AT, direction: DESC}) {
        pageInfo { hasNextPage endCursor } edges { starredAt }
      }
    }
  } }
}"""

STARS = """
query($repo: ID!, $cursor: String) {
  node(id: $repo) { ... on Repository {
    stargazers(first: 100, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor } edges { starredAt }
    }
  } }
}"""

def rooted(query: str, login: str | None) -> str:
    """The query for the token owner (`viewer`), or for a public account by login."""
    if login is None:
        return query.replace("{LOGIN_VAR}", "").replace("{ROOT}", "viewer")
    return query.replace("{LOGIN_VAR}", ", $login: String!").replace("{ROOT}", "user(login: $login)")


# Partial failures GitHub reports per field (e.g. an organisation that blocks the token):
# the rest of the response is still usable.
_TOLERATED = {"FORBIDDEN", "NOT_FOUND"}


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


def resolve_token(explicit: str = "") -> str:
    """GITHUB_TOKEN if set, else whatever account the GitHub CLI is logged in to."""
    if explicit:
        return explicit
    gh = shutil.which("gh")
    if gh:
        try:
            proc = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc and proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    raise GitHubError("no GitHub token: set GITHUB_TOKEN, or log in with `gh auth login`")


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GitHub:
    def __init__(self, token: str, *, timeout: float = 60.0, transport: httpx.BaseTransport | None = None):
        if not token:
            raise GitHubError("no GitHub token")
        self.warnings: list[str] = []
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {token}", "User-Agent": "roastmygithub"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GitHub":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def graphql(self, query: str, variables: dict[str, Any] | None = None, *, retries: int = 2) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                response = self._http.post(GRAPHQL_URL, json={"query": query, "variables": variables or {}})
            except httpx.TransportError as exc:
                if attempt < retries:
                    attempt += 1
                    time.sleep(2**attempt)
                    continue
                raise GitHubError(f"GitHub request failed: {exc}", transient=True) from exc
            if response.status_code == 401:
                raise GitHubError("GitHub rejected the token (401). Check GITHUB_TOKEN or run `gh auth login`.")
            # 5xx is usually a query timeout; 403/429 with retry-after is a secondary rate limit.
            retry_after = response.headers.get("retry-after")
            if response.status_code >= 500 or (response.status_code in (403, 429) and retry_after):
                if attempt < retries:
                    attempt += 1
                    time.sleep(min(float(retry_after or 2**attempt), 60))
                    continue
                raise GitHubError(f"GitHub returned HTTP {response.status_code}", transient=True)
            if response.is_error:
                raise GitHubError(f"GitHub returned HTTP {response.status_code}: {response.text[:300]}")
            body = response.json()
            errors = body.get("errors") or []
            fatal = [e for e in errors if e.get("type") not in _TOLERATED]
            if fatal or (errors and not body.get("data")):
                message = "; ".join(e.get("message", "?") for e in (fatal or errors))
                raise GitHubError(f"GitHub GraphQL error: {message}", transient=any("timeout" in e.get("message", "").lower() for e in fatal))
            for error in errors:
                self.warnings.append(error.get("message", "partial GitHub error"))
            return body["data"]

    def whoami(self) -> str:
        return self.graphql("query { viewer { login } }")["viewer"]["login"]

    def exists(self, login: str) -> bool:
        """Whether a public account with this login exists (organisations do not count)."""
        data = self.graphql("query($login: String!) { user(login: $login) { login } }", {"login": login})
        return bool(data.get("user"))


def collect(
    gh: GitHub,
    *,
    since: datetime,
    until: datetime,
    max_commits: int = 3000,
    login: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Everything the roast needs about one account between `since` and `until` (at most one year).

    `login=None` means the token's own account, private activity included. A login means that
    public account: GitHub only returns what anyone could see on its profile.
    """
    say = on_progress or (lambda _message: None)
    window = {"from": _iso(since), "to": _iso(until)}
    if login is not None:
        window["login"] = login
    root = "viewer" if login is None else "user"

    say("contributions")
    viewer = gh.graphql(rooted(OVERVIEW, login), window)[root]
    if viewer is None:
        raise GitHubError(f"no GitHub user named {login!r}")
    contributions = viewer["contributionsCollection"]
    repos = []
    for item in contributions["commitContributionsByRepository"]:
        repo = (item or {}).get("repository")
        if not repo:  # a repository the token cannot see comes back as null
            continue
        repos.append(
            {
                "id": repo["id"],
                "name": repo["nameWithOwner"],
                "private": repo["isPrivate"],
                "fork": repo["isFork"],
                "stars": repo["stargazerCount"],
                "commits": item["contributions"]["totalCount"],
                "language": (repo.get("primaryLanguage") or {}).get("name"),
                "languages": {e["node"]["name"]: e["size"] for e in (repo.get("languages") or {}).get("edges") or []},
            }
        )
    repos.sort(key=lambda r: -r["commits"])

    commits: list[dict[str, Any]] = []
    truncated = False
    for n, repo in enumerate(repos, start=1):
        budget = max_commits - len(commits)
        if budget <= 0:
            truncated = True
            break
        say(f"commits {n}/{len(repos)}")
        fetched, more = _history(gh, repo, viewer["id"], window, budget)
        commits.extend(fetched)
        truncated = truncated or more

    say("pull requests")
    pull_requests = _pull_requests(gh, window, login)
    say("stars")
    owned = _owned(gh, since, login)

    return {
        "schema": SCHEMA_VERSION,
        "fetched_at": _iso(datetime.now(timezone.utc)),
        "since": window["from"],
        "until": window["to"],
        "viewer": {"login": viewer["login"], "name": viewer.get("name"), "created_at": viewer["createdAt"]},
        "scope": "own" if login is None else "public",
        "totals": {
            "commits": contributions["totalCommitContributions"],
            "restricted": contributions["restrictedContributionsCount"],
            "pull_requests": contributions["totalPullRequestContributions"],
            "reviews": contributions["totalPullRequestReviewContributions"],
            "issues": contributions["totalIssueContributions"],
            "repos_with_commits": contributions["totalRepositoriesWithContributedCommits"],
            "contributions": contributions["contributionCalendar"]["totalContributions"],
        },
        "days": [
            {"date": day["date"], "count": day["contributionCount"]}
            for week in contributions["contributionCalendar"]["weeks"]
            for day in week["contributionDays"]
        ],
        "repos": repos,
        "commits": commits,
        "commits_truncated": truncated,
        "pull_requests": pull_requests,
        "owned": owned,
        "warnings": list(gh.warnings),
    }


def _history(gh: GitHub, repo: dict[str, Any], author_id: str, window: dict[str, str], budget: int) -> tuple[list[dict[str, Any]], bool]:
    """The viewer's commits on the repo's default branch, newest first. Returns (commits, more_exist)."""
    out: list[dict[str, Any]] = []
    cursor = None
    page_size = 100
    while len(out) < budget:
        variables = {
            "repo": repo["id"], "author": author_id, "since": window["from"], "until": window["to"],
            "first": min(page_size, budget - len(out)), "cursor": cursor,
        }
        try:
            data = gh.graphql(HISTORY, variables)
        except GitHubError as exc:
            # Diff stats on large commits can time the query out: ask for fewer per page.
            if exc.transient and page_size > 10:
                page_size = max(10, page_size // 3)
                continue
            gh.warnings.append(f"skipped the rest of {repo['name']}: {exc}")
            return out, True
        target = ((data.get("node") or {}).get("defaultBranchRef") or {}).get("target") or {}
        history = target.get("history")
        if not history:  # empty repository, or one the token can no longer read
            return out, False
        for node in history["nodes"]:
            message = node.get("message") or ""
            out.append(
                {
                    "repo": repo["name"],
                    "private": repo["private"],
                    "oid": node.get("abbreviatedOid") or "",
                    "date": node["author"]["date"],
                    "message": message[:MESSAGE_LIMIT],
                    "message_length": len(message),
                    "additions": node.get("additions") or 0,
                    "deletions": node.get("deletions") or 0,
                    "files": node.get("changedFilesIfAvailable"),
                    "merge": node["parents"]["totalCount"] > 1,
                }
            )
        if not history["pageInfo"]["hasNextPage"]:
            return out, False
        cursor = history["pageInfo"]["endCursor"]
    return out, True


def _pull_requests(gh: GitHub, window: dict[str, str], login: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = None
    root = "viewer" if login is None else "user"
    for _ in range(MAX_PR_PAGES):
        data = gh.graphql(rooted(PULL_REQUESTS, login), {**window, "cursor": cursor})
        page = data[root]["contributionsCollection"]["pullRequestContributions"]
        for node in page["nodes"] or []:
            pr = (node or {}).get("pullRequest")
            if not pr:
                continue
            out.append(
                {
                    "merged": pr["merged"],
                    "merged_at": pr.get("mergedAt"),
                    "created_at": pr["createdAt"],
                    "repo": pr["repository"]["nameWithOwner"],
                    "private": pr["repository"]["isPrivate"],
                }
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return out


def _owned(gh: GitHub, since: datetime, login: str | None) -> list[dict[str, Any]]:
    """Repositories the account owns (not forks), with the stars each received since `since`."""
    cutoff = _iso(since)
    out: list[dict[str, Any]] = []
    cursor = None
    root = "viewer" if login is None else "user"
    variables: dict[str, Any] = {} if login is None else {"login": login}
    for _ in range(MAX_OWNED_PAGES):
        page = gh.graphql(rooted(OWNED, login), {**variables, "cursor": cursor})[root]["repositories"]
        for repo in page["nodes"] or []:
            if not repo:  # hidden from this token (e.g. private repos with a public-only token)
                continue
            stars = repo.get("stargazers") or {"edges": [], "pageInfo": {"hasNextPage": False}}
            recent, capped = _count_recent_stars(gh, repo["id"], stars, cutoff)
            out.append(
                {
                    "name": repo["nameWithOwner"],
                    "private": repo["isPrivate"],
                    "archived": repo["isArchived"],
                    "stars": repo["stargazerCount"],
                    "created_at": repo["createdAt"],
                    "pushed_at": repo.get("pushedAt"),
                    "stars_in_window": recent,
                    "stars_capped": capped,
                }
            )
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return out


def _count_recent_stars(gh: GitHub, repo_id: str, first_page: dict[str, Any], cutoff: str) -> tuple[int, bool]:
    """Count stars newer than `cutoff`, paging while a whole page is still inside the window."""
    count, page, pages = 0, first_page, 1
    while True:
        edges = page.get("edges") or []
        inside = sum(1 for e in edges if e["starredAt"] >= cutoff)
        count += inside
        if inside < len(edges) or not page["pageInfo"]["hasNextPage"]:
            return count, False
        if pages >= MAX_STAR_PAGES:
            return count, True
        data = gh.graphql(STARS, {"repo": repo_id, "cursor": page["pageInfo"]["endCursor"]})
        page = (data.get("node") or {}).get("stargazers") or {"edges": [], "pageInfo": {"hasNextPage": False}}
        pages += 1
