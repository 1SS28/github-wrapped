"""Pick the 6-8 most roastable and most impressive facts from the stats, in balance.

Each candidate carries what a stat card shows (`value`, `label`), the full fact the script
writer is given, and a score from 0 to 1 for how much comedy or bragging it is worth. Scores
are hand-tuned rules of thumb: extremes and oddities beat averages. The picker takes the best
ones while keeping variety, so a year is not summed up by four clock jokes.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Callable, Iterator, Literal

from pydantic import BaseModel

from roastmygithub.stats import Stats

MIN_PER_KIND = 3  # of each kind among the picks, when the year offers that many
GROUP_LIMIT = {"messages": 3}  # commit messages are the funniest material; everything else gets 2
DEFAULT_GROUP_LIMIT = 2

# How funny a word is in a commit message, before counting how often it shows up.
_WORD_WEIGHT = {
    "final": 0.9, "asdf": 0.9, "please": 0.85, "hopefully": 0.85, "idk": 0.85, "oops": 0.8, "lol": 0.8,
    "ugh": 0.8, "forgot": 0.75, "again": 0.75, "maybe": 0.7, "actually": 0.7, "stuff": 0.7, "wip": 0.7,
    "broken": 0.65, "revert": 0.65, "temp": 0.6, "hack": 0.6, "typo": 0.6, "try": 0.55, "misc": 0.5,
    "debug": 0.5, "todo": 0.45, "minor": 0.4,
}


class Highlight(BaseModel):
    id: str
    group: str
    kind: Literal["roast", "flex"]
    value: str  # the big text on the stat card
    label: str  # the short line under it
    fact: str  # the exact fact, for the script writer
    score: float


def _pct(share: float) -> str:
    return f"{round(share * 100)}%"


def _hour(hour: int) -> str:
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


def _day(day: date | None) -> str:
    return f"{day:%B} {day.day}" if day else "?"


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _volume(s: Stats) -> Iterator[Highlight]:
    weeks = max(1, s.days_in_window / 7)
    yield Highlight(
        id="total_commits", group="volume", kind="roast" if s.commits < 365 else "flex",  # under one a day
        value=f"{s.commits:,}", label="commits in 12 months",
        fact=f"{s.commits:,} commits in the last 12 months across {s.repos_committed_to} repositories, about {s.commits / weeks:.1f} per week.",
        score=1.0,
    )
    if s.days_in_window >= 60 and s.active_days:
        ratio = s.active_days / s.days_in_window
        score = 0.6 if ratio < 0.15 else 0.7 if ratio > 0.8 else 0.25
        yield Highlight(
            id="active_days", group="volume", kind="flex" if ratio > 0.5 else "roast",
            value=str(s.active_days), label=f"active days out of {s.days_in_window}",
            fact=f"Contributed on {s.active_days} of the last {s.days_in_window} days ({_pct(ratio)}).",
            score=score,
        )
    if len(s.top_repos) >= 3 and s.commits and s.top_repos[0].commits / s.commits >= 0.75:
        top = s.top_repos[0]
        yield Highlight(
            id="one_repo", group="volume", kind="roast",
            value=_pct(top.commits / s.commits), label="of commits went to one repo",
            fact=f"{top.commits} of {s.commits} commits ({_pct(top.commits / s.commits)}) went to a single repository, {top.name}; the other {s.repos_committed_to - 1} repos shared the rest.",
            score=0.55,
        )


def _clock(s: Stats) -> Iterator[Highlight]:
    if s.commits_sampled < 20 or s.busiest_hour is None:
        return
    share = s.after_midnight_share or 0.0
    if share >= 0.05:
        yield Highlight(
            id="after_midnight", group="clock", kind="roast",
            value=_pct(share), label="of commits after midnight",
            fact=f"{_pct(share)} of commits ({round(share * s.commits_sampled)} of {s.commits_sampled} analysed) were made between midnight and 5 AM local time.",
            score=min(1.0, 0.45 + share * 2),
        )
    hour = s.busiest_hour
    score = 0.75 if hour >= 22 or hour < 5 else 0.6 if hour < 8 else 0.3
    yield Highlight(
        id="busiest_hour", group="clock", kind="roast",
        value=_hour(hour), label="peak commit hour",
        fact=f"The single busiest hour is {_hour(hour)} local time, with {s.hour_commits[hour]} of {s.commits_sampled} analysed commits.",
        score=score,
    )
    if s.friday_evening_commits >= 3:
        yield Highlight(
            id="friday_evening", group="clock", kind="roast",
            value=str(s.friday_evening_commits), label="commits on Friday after 5 PM",
            fact=f"{s.friday_evening_commits} commits were made on a Friday after 5 PM local time.",
            score=min(0.8, 0.4 + s.friday_evening_commits / 20),
        )


def _calendar(s: Stats) -> Iterator[Highlight]:
    total = sum(s.weekday_contributions)
    if s.busiest_weekday and total >= 20:
        count = max(s.weekday_contributions)
        weekend = s.busiest_weekday in ("Saturday", "Sunday")
        yield Highlight(
            id="busiest_weekday", group="calendar", kind="roast",
            value=s.busiest_weekday, label="busiest day of the week",
            fact=f"The busiest day of the week is {s.busiest_weekday}, with {count} of {total} contributions ({_pct(count / total)}).",
            score=0.7 if weekend else 0.45 if s.busiest_weekday == "Friday" else 0.3,
        )
    if total >= 20 and s.weekend_share >= 0.3:  # an even spread would be 29%
        yield Highlight(
            id="weekend_share", group="calendar", kind="roast",
            value=_pct(s.weekend_share), label="of contributions on weekends",
            fact=f"{_pct(s.weekend_share)} of contributions happened on a Saturday or Sunday.",
            score=min(0.9, 0.3 + s.weekend_share),
        )
    streak = s.longest_streak
    if streak.days >= 5:
        yield Highlight(
            id="longest_streak", group="calendar", kind="flex",
            value=str(streak.days), label="day streak",
            fact=f"Longest streak: {streak.days} days in a row with contributions, from {_day(streak.start)} to {_day(streak.end)}.",
            score=min(0.95, 0.35 + streak.days / 60),
        )
    gap = s.longest_gap
    if gap.days >= 10:
        yield Highlight(
            id="longest_gap", group="calendar", kind="roast",
            value=str(gap.days), label="days without a single commit",
            fact=f"Longest silence: {gap.days} days in a row with zero contributions, from {_day(gap.start)} to {_day(gap.end)}.",
            score=min(0.95, 0.4 + gap.days / 90),
        )
    if s.recent_share >= 0.5 and total >= 30 and s.days_in_window >= 180:
        yield Highlight(
            id="momentum", group="calendar", kind="flex",
            value=_pct(s.recent_share), label="of the year's work in the last 60 days",
            fact=f"{_pct(s.recent_share)} of the whole year's contributions were made in the last 60 days: the pace is picking up, not fading.",
            score=min(0.85, 0.35 + s.recent_share / 2),
        )
    if s.current_streak >= 3:
        yield Highlight(
            id="current_streak", group="calendar", kind="flex",
            value=str(s.current_streak), label="day streak, still going",
            fact=f"On a live streak right now: {s.current_streak} days in a row with contributions.",
            score=min(0.8, 0.4 + s.current_streak / 40),
        )
    if s.busiest_day and s.busiest_day.count >= 10:
        day = s.busiest_day
        yield Highlight(
            id="busiest_day", group="calendar", kind="flex",
            value=str(day.count), label=f"contributions on {_day(day.date)}",
            fact=f"The busiest single day was {_day(day.date)} ({day.date:%A}) with {day.count} contributions.",
            score=min(0.85, 0.3 + day.count / 60),
        )


def _messages(s: Stats) -> Iterator[Highlight]:
    n = s.messages_analyzed
    if not n:
        return
    fix = s.roast_words.get("fix", 0)
    if n >= 15 and fix / n >= 0.12:
        yield Highlight(
            id="fix_share", group="messages", kind="roast",
            value=_pct(fix / n), label='of commit messages say "fix"',
            fact=f'{fix} of {n} commit messages ({_pct(fix / n)}) contain the word "fix".',
            score=min(0.95, 0.45 + fix / n),
        )
    update = s.roast_words.get("update", 0)
    if n >= 15 and update / n >= 0.2:
        yield Highlight(
            id="update_share", group="messages", kind="roast",
            value=_pct(update / n), label='of commit messages say "update"',
            fact=f'{update} of {n} commit messages ({_pct(update / n)}) contain the word "update", which describes every commit ever made.',
            score=min(0.8, 0.35 + update / n),
        )

    def word_score(word: str) -> float:
        return _WORD_WEIGHT[word] * (0.6 + 0.4 * min(1.0, s.roast_words[word] / 5))

    funny = [w for w in s.roast_words if w in _WORD_WEIGHT]
    if funny:
        word = max(funny, key=word_score)
        count = s.roast_words[word]
        yield Highlight(
            id=f"word_{word}", group="messages", kind="roast",
            value=f"{count}×", label=f'commit messages containing "{word}"',
            fact=f'{count} commit message{"s" if count != 1 else ""} contain{"" if count != 1 else "s"} "{word}" (matched as a word, including variants).',
            score=word_score(word),
        )

    shortest = s.shortest_message
    if shortest and shortest.length <= 6:
        yield Highlight(
            id="shortest_message", group="messages", kind="roast",
            value=f"“{shortest.text}”", label=f"shortest commit message ({shortest.length} character{'s' if shortest.length != 1 else ''})",
            fact=f'The shortest commit message of the year is "{shortest.text}" ({shortest.length} characters), in {shortest.repo}.',
            score=0.95 if shortest.length <= 1 else 0.85 if shortest.length <= 3 else 0.6,
        )
    longest = s.longest_message
    if longest and longest.length >= 250:
        yield Highlight(
            id="longest_message", group="messages", kind="roast",
            value=f"{longest.length:,}", label="characters in one commit message",
            fact=f'The longest commit message runs {longest.length:,} characters. It starts: "{_clip(longest.text, 90)}".',
            score=min(0.8, 0.4 + longest.length / 2000),
        )
    repeated = s.most_repeated_message
    if repeated and repeated.count >= 3:
        yield Highlight(
            id="repeated_message", group="messages", kind="roast",
            value=f"{repeated.count}×", label=f"“{_clip(repeated.text, 30)}”",
            fact=f'The exact commit message "{_clip(repeated.text, 90)}" was used {repeated.count} times.',
            score=min(0.95, 0.45 + repeated.count / 25),
        )
    if n >= 15 and (s.one_word_share or 0) >= 0.2:
        yield Highlight(
            id="one_word_messages", group="messages", kind="roast",
            value=_pct(s.one_word_share), label="of commit messages are one word",
            fact=f"{_pct(s.one_word_share)} of commit messages are a single word.",
            score=min(0.85, 0.35 + s.one_word_share),
        )


def _code(s: Stats) -> Iterator[Highlight]:
    if s.languages:
        top = s.languages[0]
        others = ", ".join(f"{lang.name} {_pct(lang.share)}" for lang in s.languages[1:4])
        if top.share >= 0.5:
            yield Highlight(
                id="top_language", group="code", kind="roast",
                value=_pct(top.share), label=top.name,
                fact=f"Top language: {top.name}, {_pct(top.share)} of commit activity" + (f" (then {others})." if others else "; nothing else at all."),
                score=min(0.8, 0.35 + (top.share - 0.5)),
            )
        elif len(s.languages) >= 6:
            yield Highlight(
                id="language_count", group="code", kind="roast",
                value=f"{len(s.languages)}+" if len(s.languages) >= 8 else str(len(s.languages)), label="languages, none of them mastered",
                fact=f"Commit activity is spread over at least {len(s.languages)} languages; the biggest, {top.name}, is only {_pct(top.share)} (then {others}).",
                score=0.55,
            )
    if len(s.languages) >= 4:
        names = ", ".join(lang.name for lang in s.languages[:5])
        yield Highlight(
            id="language_range", group="code", kind="flex",
            value=str(len(s.languages)), label="languages shipped this year",
            fact=f"Shipped code in {len(s.languages)} languages this year: {names}.",
            score=min(0.7, 0.35 + len(s.languages) / 20),
        )
    big = s.biggest_commit
    if big and big.additions >= 3000:
        about = f' Its message: "{_clip(big.headline, 80)}".' if big.headline else ""
        files = f" across {big.files} files" if big.files else ""
        yield Highlight(
            id="biggest_commit", group="code", kind="roast",
            value=f"+{big.additions:,}", label="lines in a single commit",
            fact=f"The biggest single commit added {big.additions:,} lines{files}, in {big.repo}.{about}",
            score=min(0.85, 0.45 + big.additions / 50_000),
        )
    churn = s.lines_added + s.lines_deleted
    if churn >= 1000 and s.lines_deleted > s.lines_added:
        yield Highlight(
            id="net_negative", group="code", kind="flex",
            value=f"−{s.lines_deleted - s.lines_added:,}", label="net lines of code",
            fact=f"Deleted more than was written: {s.lines_added:,} lines added, {s.lines_deleted:,} deleted, a net of minus {s.lines_deleted - s.lines_added:,}.",
            score=0.8,
        )
    elif churn >= 1000 and s.commits_sampled:
        yield Highlight(
            id="lines_added", group="code", kind="flex",
            value=f"+{s.lines_added:,}", label="lines added",
            fact=f"{s.lines_added:,} lines added and {s.lines_deleted:,} deleted across {s.commits_sampled} analysed commits, about {round(s.lines_added / s.commits_sampled):,} added per commit.",
            score=0.55 if s.lines_added / s.commits_sampled >= 300 else 0.35,
        )


def _repos(s: Stats) -> Iterator[Highlight]:
    if s.repos_created >= 3 and s.repos_abandoned >= 2:
        yield Highlight(
            id="abandoned_repos", group="repos", kind="roast",
            value=f"{s.repos_abandoned} of {s.repos_created}", label="new repos abandoned within two weeks",
            fact=f"Started {s.repos_created} new repositories this year; {s.repos_abandoned} of them were last touched within two weeks of being created and have been silent for 60+ days.",
            score=min(0.95, 0.5 + 0.45 * s.repos_abandoned / s.repos_created),
        )
    elif s.repos_created >= 3:
        yield Highlight(
            id="repos_created", group="repos", kind="flex",
            value=str(s.repos_created), label="new projects started",
            fact=f"Started {s.repos_created} new repositories in 12 months, and none of them fit the abandoned-within-two-weeks pattern.",
            score=min(0.7, 0.4 + s.repos_created / 30),
        )
    stars = f"{s.stars_received:,}{'+' if s.stars_capped else ''}"
    if s.stars_received >= 25:
        yield Highlight(
            id="stars", group="repos", kind="flex",
            value=stars, label="stars received",
            fact=f"Received {stars} new stars on owned repositories in the last 12 months ({s.stars_all_time:,} all time).",
            score=min(0.9, 0.45 + s.stars_received / 400),
        )
    elif s.stars_received <= 2 and s.commits >= 50:
        yield Highlight(
            id="stars", group="repos", kind="roast",
            value=stars, label="stars received",
            fact=f"{s.commits:,} commits earned {s.stars_received} new star{'s' if s.stars_received != 1 else ''} on owned repositories in 12 months.",
            score=0.65,
        )


def _social(s: Stats) -> Iterator[Highlight]:
    if s.prs_opened == 0 and s.commits >= 30:
        yield Highlight(
            id="no_pull_requests", group="social", kind="roast",
            value="0", label="pull requests. Straight to main.",
            fact=f"{s.commits:,} commits and 0 pull requests opened: everything went straight to the default branch.",
            score=0.8,
        )
    elif s.prs_opened >= 5:
        rate = s.prs_merged / s.prs_opened
        yield Highlight(
            id="pull_requests", group="social", kind="roast" if rate < 0.5 else "flex",
            value=f"{s.prs_merged}/{s.prs_opened}", label="pull requests merged",
            fact=f"Opened {s.prs_opened} pull requests; {s.prs_merged} were merged ({_pct(rate)}).",
            score=0.7 if rate < 0.5 or rate >= 0.95 else 0.45,
        )
    if s.pr_reviews == 0 and s.prs_opened >= 5:
        yield Highlight(
            id="no_reviews", group="social", kind="roast",
            value="0", label="code reviews given",
            fact=f"Opened {s.prs_opened} pull requests for others to review and reviewed 0 in return.",
            score=0.65,
        )
    elif s.pr_reviews >= 50:
        yield Highlight(
            id="reviews", group="social", kind="flex",
            value=f"{s.pr_reviews:,}", label="code reviews given",
            fact=f"Reviewed {s.pr_reviews:,} pull requests in 12 months.",
            score=0.5,
        )


_SOURCES: list[Callable[[Stats], Iterator[Highlight]]] = [_volume, _clock, _calendar, _messages, _code, _repos, _social]


def candidates(stats: Stats) -> list[Highlight]:
    found = [h for source in _SOURCES for h in source(stats)]
    return sorted(found, key=lambda h: -h.score)


def pick(stats: Stats, count: int = 8) -> list[Highlight]:
    """The best `count` highlights, at most a couple per group, best first."""
    ranked = candidates(stats)
    chosen: list[Highlight] = []
    used: Counter[str] = Counter()
    for highlight in ranked:
        if len(chosen) >= count:
            break
        if used[highlight.group] >= GROUP_LIMIT.get(highlight.group, DEFAULT_GROUP_LIMIT):
            continue
        chosen.append(highlight)
        used[highlight.group] += 1
    # A thin year may not fill the list with variety; then take the best of what is left.
    spare = [h for h in ranked if h not in chosen]
    chosen.extend(spare[: max(0, count - len(chosen))])
    # Balance: the script needs things to praise as well as things to tease. Swap the weakest of
    # the over-represented kind for the best unused of the other, keeping the opening fact.
    for kind in ("flex", "roast"):
        spare = [h for h in ranked if h not in chosen and h.kind == kind]
        while spare and sum(h.kind == kind for h in chosen) < MIN_PER_KIND:
            others = [h for h in chosen if h.kind != kind and h.id != "total_commits"]
            if len(others) <= MIN_PER_KIND:
                break
            chosen.remove(min(others, key=lambda h: h.score))
            groups = Counter(h.group for h in chosen)
            # Prefer one whose group still has room; scores break ties (spare is best first).
            fits = [h for h in spare if groups[h.group] < GROUP_LIMIT.get(h.group, DEFAULT_GROUP_LIMIT)]
            best = (fits or spare)[0]
            spare.remove(best)
            chosen.append(best)
    return sorted(chosen, key=lambda h: -h.score)
