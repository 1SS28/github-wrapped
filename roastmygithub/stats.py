"""Turn the cached GitHub activity into the numbers the roast is written from.

Two scopes, on purpose:
  * counts (commits, streaks, hours, languages, lines) use everything the token can see;
  * text (commit messages, repository names) uses public repositories only, unless the user
    opts in with --include-private. The video is meant to be posted, and the text is sent to
    an LLM, so private names and messages stay out by default.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
AFTER_MIDNIGHT_HOURS = range(0, 5)  # 00:00-04:59 local time
FRIDAY_EVENING_HOUR = 17
RECENT_DAYS = 60
ABANDONED_WITHIN_DAYS = 14  # last push this soon after creation...
ABANDONED_QUIET_DAYS = 60  # ...and nothing since for this long
PRIVATE_REPO = "a private repo"
LOG_LIMIT = 300

# Words that say something about how the year went. Each pattern is matched once per message.
ROAST_WORDS: dict[str, str] = {
    "fix": r"\bfix(?:e[sd]|ing)?\b",
    "wip": r"\bwip\b",
    "final": r"\bfinal(?:[ _-]?v?\d+)?\b",
    "oops": r"\b(?:w?oops(?:ie)?)\b",
    "typo": r"\btypos?\b",
    "update": r"\bupdate[sd]?\b",
    "test": r"\btest(?:s|ing)?\b",
    "temp": r"\b(?:temp|tmp)\b",
    "hack": r"\bhack(?:s|y)?\b",
    "revert": r"\brevert(?:s|ed)?\b",
    "again": r"\bagain\b",
    "please": r"\b(?:please|pls|plz)\b",
    "actually": r"\bactually\b",
    "stuff": r"\bstuff\b",
    "asdf": r"\basdf\w*\b",
    "lol": r"\b(?:lol|lmao)\b",
    "ugh": r"\b(?:ugh+|argh+)\b",
    "try": r"\btry(?:ing)?\b",
    "broken": r"\bbrok(?:e|en)\b",
    "minor": r"\bminor\b",
    "misc": r"\bmisc\b",
    "cleanup": r"\bclean(?:ed)?[ -]?up\b",
    "debug": r"\bdebug(?:ging)?\b",
    "todo": r"\btodo\b",
    "idk": r"\bidk\b",
    "hopefully": r"\bhopefully\b",
    "maybe": r"\bmaybe\b",
    "forgot": r"\bforgot\b",
}
_ROAST_PATTERNS = {word: re.compile(pattern, re.IGNORECASE) for word, pattern in ROAST_WORDS.items()}
_WORD = re.compile(r"[a-z][a-z0-9'+#-]*")
_STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from had has have if in into is it its "
    "my no not of on or our so some than that the their then there these this to up use used "
    "using was we were when which while will with you your i me via per out off all more new "
    "now also just only one two get got set make made add added adds "
    # file extensions, left over from messages like "Update README.md"
    "py js ts tsx jsx md json yml yaml toml txt css html sh go rs rb java cpp".split()
)


class Span(BaseModel):
    days: int = 0
    start: date | None = None
    end: date | None = None


class DayCount(BaseModel):
    date: date
    count: int


class RepoStat(BaseModel):
    name: str
    commits: int
    private: bool
    language: str | None = None
    stars: int = 0


class LanguageStat(BaseModel):
    name: str
    share: float


class WordCount(BaseModel):
    word: str
    count: int


class Quote(BaseModel):
    text: str
    repo: str
    length: int
    count: int = 1


class LogLine(BaseModel):
    """One commit as `git log --oneline` would show it (text scope only)."""

    oid: str
    headline: str
    repo: str
    date: datetime
    additions: int = 0
    deletions: int = 0
    files: int | None = None


class NewRepo(BaseModel):
    name: str
    created: date
    last_push: date
    abandoned: bool


class BigCommit(BaseModel):
    additions: int
    files: int | None
    headline: str | None  # None when the commit is in a private repo and private text is off
    repo: str


class Stats(BaseModel):
    login: str
    name: str | None = None
    since: datetime
    until: datetime
    text_scope: str  # "public" or "all": where commit messages and repo names come from

    # GitHub's own totals for the window
    commits: int = 0
    private_contributions: int = 0
    total_contributions: int = 0
    prs_opened: int = 0
    prs_merged: int = 0
    pr_reviews: int = 0
    issues_opened: int = 0
    repos_committed_to: int = 0

    # Contribution calendar
    days_in_window: int = 0
    active_days: int = 0
    longest_streak: Span = Span()
    current_streak: int = 0
    longest_gap: Span = Span()
    busiest_day: DayCount | None = None
    weekday_contributions: list[int] = [0] * 7  # Monday first
    busiest_weekday: str | None = None
    weekend_share: float = 0.0
    calendar: list[DayCount] = []  # every day in the window, oldest first
    recent_share: float = 0.0  # share of the year's contributions made in the last RECENT_DAYS

    # Clock, from the commits that were sampled
    commits_sampled: int = 0
    commits_truncated: bool = False
    clock: str = ""  # how local time was worked out
    hour_commits: list[int] = [0] * 24
    busiest_hour: int | None = None
    after_midnight_share: float | None = None
    friday_evening_commits: int = 0

    # Code
    languages: list[LanguageStat] = []
    top_repos: list[RepoStat] = []
    lines_added: int = 0
    lines_deleted: int = 0
    biggest_commit: BigCommit | None = None

    # Commit messages (text scope)
    messages_analyzed: int = 0
    top_words: list[WordCount] = []
    roast_words: dict[str, int] = {}
    one_word_share: float | None = None
    average_message_length: float | None = None
    shortest_message: Quote | None = None
    longest_message: Quote | None = None
    most_repeated_message: Quote | None = None
    commit_log: list[LogLine] = []  # newest first, at most LOG_LIMIT

    # Repositories the user owns
    stars_received: int = 0
    stars_capped: bool = False
    stars_all_time: int = 0
    repos_created: int = 0
    repos_abandoned: int = 0
    new_repos: list[NewRepo] = []  # oldest first


def local_timezone(name: str | None = None) -> tzinfo:
    """The IANA zone to read offset-less commits in: `name`, else $TZ, else this machine's zone."""
    for candidate in (name, os.environ.get("TZ")):
        if candidate:
            try:
                return ZoneInfo(candidate)
            except (ZoneInfoNotFoundError, ValueError):
                if candidate == name:
                    raise ValueError(f"unknown timezone '{name}' (use an IANA name like America/Toronto)") from None
    try:
        resolved = str(Path("/etc/localtime").resolve())
        if "zoneinfo/" in resolved:
            return ZoneInfo(resolved.split("zoneinfo/", 1)[1])
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def headline(message: str) -> str:
    return message.strip().split("\n", 1)[0].strip()


def _calendar(stats: Stats, days: list[dict[str, Any]], account_created: date) -> None:
    today = stats.until.date()
    series = sorted(
        (date.fromisoformat(d["date"]), d["count"]) for d in days if account_created <= date.fromisoformat(d["date"]) <= today
    )
    stats.days_in_window = len(series)
    stats.calendar = [DayCount(date=day, count=count) for day, count in series]
    if not series:
        return
    stats.active_days = sum(1 for _, count in series if count)
    best_day = max(series, key=lambda dc: dc[1])
    if best_day[1]:
        stats.busiest_day = DayCount(date=best_day[0], count=best_day[1])

    def longest_run(active: bool) -> Span:
        best, start, length = Span(), None, 0
        for day, count in series:
            if bool(count) == active:
                start = start or day
                length += 1
                if length > best.days:
                    best = Span(days=length, start=start, end=day)
            else:
                start, length = None, 0
        return best

    stats.longest_streak = longest_run(True)
    stats.longest_gap = longest_run(False)

    # Today may not have a commit yet; that does not break a running streak.
    tail = series[:-1] if series[-1][1] == 0 else series
    for _, count in reversed(tail):
        if not count:
            break
        stats.current_streak += 1

    whole_year = sum(count for _, count in series)
    if whole_year:
        stats.recent_share = round(sum(count for _, count in series[-RECENT_DAYS:]) / whole_year, 4)

    weekdays = [0] * 7
    for day, count in series:
        weekdays[day.weekday()] += count
    stats.weekday_contributions = weekdays
    total = sum(weekdays)
    if total:
        stats.busiest_weekday = WEEKDAYS[max(range(7), key=weekdays.__getitem__)]
        stats.weekend_share = round((weekdays[5] + weekdays[6]) / total, 4)


def _clock(stats: Stats, commits: list[dict[str, Any]], tz: tzinfo) -> None:
    hours = [0] * 24
    own_offset = friday = 0
    for commit in commits:
        moment = _parse(commit["date"])
        if moment.utcoffset():
            own_offset += 1  # the committer's own clock, wherever they were
        else:
            moment = moment.astimezone(tz)
        hours[moment.hour] += 1
        if moment.weekday() == 4 and moment.hour >= FRIDAY_EVENING_HOUR:
            friday += 1
    stats.commits_sampled = len(commits)
    stats.hour_commits = hours
    stats.friday_evening_commits = friday
    zone = getattr(tz, "key", None) or str(tz)
    stats.clock = "commit timestamps" if own_offset > len(commits) / 2 else zone
    if commits:
        stats.busiest_hour = max(range(24), key=hours.__getitem__)
        stats.after_midnight_share = round(sum(hours[h] for h in AFTER_MIDNIGHT_HOURS) / len(commits), 4)


def _languages(repos: list[dict[str, Any]]) -> list[LanguageStat]:
    """Commit-weighted: each repo's commits are split across its languages by code size."""
    weights: Counter[str] = Counter()
    for repo in repos:
        sizes = repo.get("languages") or {}
        total = sum(sizes.values())
        if total:
            for language, size in sizes.items():
                weights[language] += repo["commits"] * size / total
        elif repo.get("language"):
            weights[repo["language"]] += repo["commits"]
    total = sum(weights.values())
    return [LanguageStat(name=name, share=round(weight / total, 4)) for name, weight in weights.most_common(8)] if total else []


def _messages(stats: Stats, commits: list[dict[str, Any]]) -> None:
    rows = [(headline(c["message"]), c) for c in commits]
    rows = [(text, c) for text, c in rows if text]
    stats.messages_analyzed = len(rows)
    if not rows:
        return
    newest = sorted(rows, key=lambda row: row[1]["date"], reverse=True)[:LOG_LIMIT]
    stats.commit_log = [
        LogLine(
            oid=(c.get("oid") or "")[:7], headline=text[:200], repo=c["repo"].split("/")[-1], date=_parse(c["date"]),
            additions=c["additions"], deletions=c["deletions"], files=c.get("files"),
        )
        for text, c in newest
    ]

    words: Counter[str] = Counter()
    roast: Counter[str] = Counter()
    repeated: Counter[str] = Counter()
    one_word = 0
    for text, _ in rows:
        lowered = text.lower()
        words.update(w for w in _WORD.findall(lowered) if len(w) > 1 and w not in _STOPWORDS)
        roast.update(word for word, pattern in _ROAST_PATTERNS.items() if pattern.search(lowered))
        repeated[lowered] += 1
        one_word += len(text.split()) == 1

    stats.top_words = [WordCount(word=w, count=n) for w, n in words.most_common(12)]
    stats.roast_words = dict(roast.most_common())
    stats.one_word_share = round(one_word / len(rows), 4)
    stats.average_message_length = round(sum(len(text) for text, _ in rows) / len(rows), 1)

    def quote(text: str, commit: dict[str, Any], length: int, count: int = 1) -> Quote:
        return Quote(text=text[:140], repo=commit["repo"], length=length, count=count)

    text, commit = min(rows, key=lambda row: len(row[0]))
    stats.shortest_message = quote(text, commit, len(text))
    text, commit = max(rows, key=lambda row: row[1].get("message_length", len(row[0])))
    stats.longest_message = quote(text, commit, commit.get("message_length", len(text)))
    top, count = repeated.most_common(1)[0]
    if count > 1:
        text, commit = next(row for row in rows if row[0].lower() == top)
        stats.most_repeated_message = quote(text, commit, len(text), count)


def compute_stats(activity: dict[str, Any], *, include_private: bool = False, tz: tzinfo | None = None) -> Stats:
    tz = tz or local_timezone()
    viewer, totals = activity["viewer"], activity["totals"]
    since, until = _parse(activity["since"]), _parse(activity["until"])
    stats = Stats(
        login=viewer["login"],
        name=viewer.get("name"),
        since=since,
        until=until,
        text_scope="all" if include_private else "public",
        commits=totals["commits"],
        private_contributions=totals["restricted"],
        total_contributions=totals["contributions"],
        prs_opened=totals["pull_requests"],
        pr_reviews=totals["reviews"],
        issues_opened=totals["issues"],
        repos_committed_to=totals["repos_with_commits"],
        commits_truncated=activity.get("commits_truncated", False),
    )

    def shown(name: str, private: bool) -> str:
        return name if include_private or not private else PRIVATE_REPO

    _calendar(stats, activity["days"], _parse(viewer["created_at"]).date())

    authored = [c for c in activity["commits"] if not c.get("merge")]
    _clock(stats, activity["commits"], tz)
    stats.languages = _languages(activity["repos"])
    stats.top_repos = [
        RepoStat(name=shown(r["name"], r["private"]), commits=r["commits"], private=r["private"], language=r.get("language"), stars=r["stars"])
        for r in activity["repos"][:8]
    ]
    stats.lines_added = sum(c["additions"] for c in authored)
    stats.lines_deleted = sum(c["deletions"] for c in authored)
    if authored:
        biggest = max(authored, key=lambda c: c["additions"])
        visible = include_private or not biggest["private"]
        stats.biggest_commit = BigCommit(
            additions=biggest["additions"],
            files=biggest.get("files"),
            headline=headline(biggest["message"])[:140] if visible else None,
            repo=shown(biggest["repo"], biggest["private"]),
        )

    _messages(stats, [c for c in authored if include_private or not c["private"]])

    stats.prs_merged = sum(
        1 for pr in activity["pull_requests"] if pr["merged"] and pr.get("merged_at") and since <= _parse(pr["merged_at"]) <= until
    )

    owned = activity["owned"]
    stats.stars_received = sum(r["stars_in_window"] for r in owned)
    stats.stars_capped = any(r["stars_capped"] for r in owned)
    stats.stars_all_time = sum(r["stars"] for r in owned)
    for repo in owned:
        created = _parse(repo["created_at"])
        if created < since:
            continue
        stats.repos_created += 1
        pushed = _parse(repo["pushed_at"]) if repo.get("pushed_at") else created
        abandoned = pushed - created <= timedelta(days=ABANDONED_WITHIN_DAYS) and until - pushed >= timedelta(days=ABANDONED_QUIET_DAYS)
        stats.repos_abandoned += abandoned
        name = repo["name"].split("/")[-1] if include_private or not repo["private"] else "private repo"
        stats.new_repos.append(NewRepo(name=name, created=created.date(), last_push=pushed.date(), abandoned=abandoned))
    stats.new_repos.sort(key=lambda r: r.created)
    return stats
