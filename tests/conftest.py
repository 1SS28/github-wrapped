import json
from datetime import date, timedelta

import httpx
import pytest

SINCE = "2025-10-05T12:00:00Z"
UNTIL = "2026-10-05T12:00:00Z"


def commit(message, when="2026-06-01T15:00:00-04:00", *, repo="me/app", private=False, additions=10, deletions=2, merge=False):
    return {
        "repo": repo, "private": private, "oid": "abc1234", "date": when, "message": message, "message_length": len(message),
        "additions": additions, "deletions": deletions, "files": 1, "merge": merge,
    }


def make_activity(*, days=None, commits=None, repos=None, pull_requests=None, owned=None, totals=None, created_at="2020-01-01T00:00:00Z"):
    """A cached-activity dict like github.collect() returns. `days` maps ISO date -> count."""
    start = date(2025, 10, 5)
    calendar = [{"date": (start + timedelta(days=i)).isoformat(), "count": 0} for i in range(366)]
    for entry in calendar:
        entry["count"] = (days or {}).get(entry["date"], 0)
    commits = commits or []
    repos = repos if repos is not None else [
        {"id": "R1", "name": "me/app", "private": False, "fork": False, "stars": 3, "commits": len(commits), "language": "Python", "languages": {"Python": 900, "Shell": 100}}
    ]
    base = {"commits": sum(r["commits"] for r in repos), "restricted": 0, "pull_requests": 0, "reviews": 0, "issues": 0, "repos_with_commits": len(repos), "contributions": sum(d["count"] for d in calendar)}
    return {
        "schema": 2,
        "fetched_at": UNTIL,
        "since": SINCE,
        "until": UNTIL,
        "viewer": {"login": "me", "name": "Me Myself", "created_at": created_at},
        "totals": {**base, **(totals or {})},
        "days": calendar,
        "repos": repos,
        "commits": commits,
        "commits_truncated": False,
        "pull_requests": pull_requests or [],
        "owned": owned or [],
        "warnings": [],
    }


@pytest.fixture
def busy_year():
    """Enough going on to produce a full set of highlights."""
    days = {(date(2026, 3, 1) + timedelta(days=i)).isoformat(): 4 for i in range(40)}
    days["2026-06-06"] = 30  # a Saturday
    commits = (
        [commit("fix login", f"2026-03-{d:02d}T02:30:00-04:00") for d in range(1, 21)]
        + [commit("wip", f"2026-03-{d:02d}T14:00:00-04:00") for d in range(1, 11)]
        + [commit("final2 for real", "2026-06-06T23:10:00-04:00"), commit(".", "2026-06-05T18:30:00-04:00")]
        + [commit("Add billing export", f"2026-04-{d:02d}T10:00:00-04:00", additions=400) for d in range(1, 11)]
        + [commit("secret roadmap for acme", "2026-05-01T09:00:00-04:00", repo="me/stealth", private=True, additions=9000)]
    )
    repos = [
        {"id": "R1", "name": "me/app", "private": False, "fork": False, "stars": 3, "commits": 300, "language": "Python", "languages": {"Python": 900, "Shell": 100}},
        {"id": "R2", "name": "me/stealth", "private": True, "fork": False, "stars": 0, "commits": 100, "language": "Go", "languages": {"Go": 500}},
    ]
    owned = [
        {"name": "me/app", "private": False, "archived": False, "stars": 3, "created_at": "2024-01-01T00:00:00Z", "pushed_at": "2026-06-06T00:00:00Z", "stars_in_window": 1, "stars_capped": False},
        {"name": "me/idea-1", "private": False, "archived": False, "stars": 0, "created_at": "2026-01-01T00:00:00Z", "pushed_at": "2026-01-03T00:00:00Z", "stars_in_window": 0, "stars_capped": False},
        {"name": "me/idea-2", "private": False, "archived": False, "stars": 0, "created_at": "2026-02-01T00:00:00Z", "pushed_at": "2026-02-02T00:00:00Z", "stars_in_window": 0, "stars_capped": False},
        {"name": "me/idea-3", "private": False, "archived": False, "stars": 0, "created_at": "2026-09-20T00:00:00Z", "pushed_at": "2026-09-21T00:00:00Z", "stars_in_window": 0, "stars_capped": False},
    ]
    return make_activity(days=days, commits=commits, repos=repos, owned=owned)


class FakeGitHubAPI:
    """Answers the GraphQL queries github.py sends, and records them."""

    def __init__(self, *, history_pages=None, star_pages=None, errors=None):
        self.calls: list[dict] = []
        self.history_pages = history_pages or {"R1": [[("fix it", "2026-06-01T01:00:00-04:00")]]}
        self.star_pages = star_pages or {}
        self.errors = errors or []
        self.user_missing = False  # answer `user(login:)` queries with null

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append(body)
        query, variables = body["query"], body["variables"]
        root = "user" if "user(login: $login)" in query else "viewer"
        if root == "user" and self.user_missing:
            return httpx.Response(200, json={"data": {"user": None}})
        if "contributionCalendar" in query:
            data = {root: self._overview()}
        elif "history(" in query:
            data = {"node": self._history(variables)}
        elif "pullRequestContributions" in query:
            data = {root: {"contributionsCollection": {"pullRequestContributions": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"pullRequest": {"merged": True, "mergedAt": "2026-05-02T00:00:00Z", "createdAt": "2026-05-01T00:00:00Z", "repository": {"nameWithOwner": "me/app", "isPrivate": False}}}],
            }}}}
        elif "repositories(" in query:
            data = {root: {"repositories": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [self._owned_repo()]}}}
        elif "stargazers(" in query:
            page = self.star_pages[variables["repo"]][int(variables["cursor"])]
            data = {"node": {"stargazers": page}}
        else:
            data = {"viewer": {"login": "me"}}
        payload = {"data": data}
        if self.errors:
            payload["errors"] = self.errors
        return httpx.Response(200, json=payload)

    def _overview(self) -> dict:
        return {
            "id": "U1", "login": "me", "name": "Me Myself", "createdAt": "2020-01-01T00:00:00Z",
            "contributionsCollection": {
                "totalCommitContributions": 42, "restrictedContributionsCount": 5, "totalPullRequestContributions": 1,
                "totalPullRequestReviewContributions": 2, "totalIssueContributions": 3, "totalRepositoriesWithContributedCommits": 1,
                "contributionCalendar": {"totalContributions": 50, "weeks": [{"contributionDays": [{"date": "2026-06-01", "contributionCount": 7}]}]},
                "commitContributionsByRepository": [
                    {"contributions": {"totalCount": 42}, "repository": {
                        "id": "R1", "nameWithOwner": "me/app", "isPrivate": False, "isFork": False, "stargazerCount": 3,
                        "primaryLanguage": {"name": "Python"},
                        "languages": {"totalSize": 1000, "edges": [{"size": 900, "node": {"name": "Python"}}, {"size": 100, "node": {"name": "Shell"}}]},
                    }}
                ],
            },
        }

    def _history(self, variables: dict) -> dict:
        pages = self.history_pages[variables["repo"]]
        index = int(variables["cursor"] or 0)
        nodes = [
            {"abbreviatedOid": "abc1234", "message": message, "additions": 5, "deletions": 1, "changedFilesIfAvailable": 2, "author": {"date": when}, "parents": {"totalCount": 1}}
            for message, when in pages[index][: variables["first"]]
        ]
        more = index + 1 < len(pages)
        return {"defaultBranchRef": {"target": {"history": {"pageInfo": {"hasNextPage": more, "endCursor": str(index + 1) if more else None}, "nodes": nodes}}}}

    def _owned_repo(self) -> dict:
        first = self.star_pages.get("R1", [{"pageInfo": {"hasNextPage": False, "endCursor": None}, "edges": [{"starredAt": "2026-01-01T00:00:00Z"}, {"starredAt": "2024-01-01T00:00:00Z"}]}])[0]
        return {
            "id": "R1", "nameWithOwner": "me/app", "isPrivate": False, "isArchived": False, "stargazerCount": 3,
            "createdAt": "2024-01-01T00:00:00Z", "pushedAt": "2026-06-01T00:00:00Z", "stargazers": first,
        }


@pytest.fixture
def api():
    return FakeGitHubAPI()


class FakeMagicHourAPI:
    """Voice Cloner and Talking Photo, with real (tiny) audio and video files behind them."""

    def __init__(self, tmp_path, *, credits=50_000, seconds_per_character=0.07):
        self.tmp = tmp_path / "fake-magichour"
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.credits = credits
        self.seconds_per_character = seconds_per_character
        self.jobs: dict[str, dict] = {}
        self.created: list[tuple[str, dict]] = []
        self.face_checks = 0
        self.faces_on_checks: set[int] = set()  # which face checks (1-based) report a face

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "storage.test":
            if request.method == "PUT":
                return httpx.Response(200)
            return httpx.Response(200, content=self._media(self.jobs[path.rsplit("/", 1)[1]]))
        if path == "/v1/account":
            return httpx.Response(200, json={"credits": self.credits, "tier": "creator", "subscription": None})
        if path == "/v1/files/upload-urls":
            item = json.loads(request.content)["items"][0]
            n = len(self.created) + len(self.jobs) + request.content.__hash__() % 1000
            return httpx.Response(200, json={"items": [{"upload_url": f"https://storage.test/put/{n}", "file_path": f"api-assets/{n}.{item['extension']}"}]})
        if path == "/v1/face-detection":
            job_id = f"face{len(self.jobs)}"
            self.jobs[job_id] = {"kind": "faces", "credits": 0}
            return httpx.Response(200, json={"id": job_id, "credits_charged": 0})
        if path.startswith("/v1/face-detection/"):
            self.face_checks += 1
            faces = [{"path": "x"}] if self.face_checks in self.faces_on_checks else []
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[1], "status": "complete", "faces": faces})
        if request.method == "POST":
            body = json.loads(request.content)
            job_id = f"job{len(self.jobs)}"
            if path == "/v1/ai-image-generator":
                self.jobs[job_id] = {"kind": "image", "credits": 10, "prompt": body["style"]["prompt"]}
            elif path == "/v1/image-to-video":
                self.jobs[job_id] = {"kind": "video", "seconds": body["end_seconds"], "credits": body["end_seconds"] * 24}
            elif path in ("/v1/ai-voice-cloner", "/v1/ai-voice-generator"):
                charged = -(-len(body["style"]["prompt"]) // 10)
                self.jobs[job_id] = {"kind": "audio", "seconds": len(body["style"]["prompt"]) * self.seconds_per_character, "credits": charged, "voice": body["style"].get("voice_name")}
            else:
                seconds = body["end_seconds"] - body["start_seconds"]
                rate = 24 if body["style"]["generation_mode"] == "prompted" else 48
                self.jobs[job_id] = {"kind": "video", "seconds": seconds, "credits": round(seconds * rate)}
            self.created.append((path, body))
            return httpx.Response(200, json={"id": job_id, "credits_charged": self.jobs[job_id]["credits"]})
        job_id = path.rsplit("/", 1)[1]
        job = self.jobs[job_id]
        return httpx.Response(200, json={"id": job_id, "status": "complete", "credits_charged": job["credits"], "downloads": [{"url": f"https://storage.test/get/{job_id}", "expires_at": "2030-01-01T00:00:00Z"}]})

    def _media(self, job: dict) -> bytes:
        import subprocess

        from core import compose

        import uuid

        # Unique per call: downloads run on several threads at once.
        if job["kind"] == "image":
            from io import BytesIO

            from PIL import Image

            buffer = BytesIO()
            Image.new("RGB", (768, 1344), (40, 90, 160)).save(buffer, format="PNG")
            return buffer.getvalue()
        dest = self.tmp / f"{uuid.uuid4().hex}.{'wav' if job['kind'] == 'audio' else 'mp4'}"
        source = ["-f", "lavfi", "-i", f"sine=frequency=220:duration={job['seconds']:.3f}"] if job["kind"] == "audio" else [
            "-f", "lavfi", "-i", f"color=c=gray:s=544x960:r=25:d={job['seconds']:.3f}", "-pix_fmt", "yuv420p"]
        subprocess.run([compose.ffmpeg_bin(), "-loglevel", "error", "-y", *source, str(dest)], check=True)
        return dest.read_bytes()
