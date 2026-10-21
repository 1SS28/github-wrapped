"""The rank: one tier for the year, from F up through SSS, and past that, Unranked.

The score is six explainable parts out of 100. Tiers are fixed cut-offs on that score, so two
people with the same numbers get the same tier, and the breakdown says why. "Unranked" is the
top: a year so far off the scale that ranking it would be silly. Too little activity to judge
gets no tier at all (`tier=None`).
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from roastmygithub.stats import Stats

TIERS = ["F", "E", "D", "C", "B", "A", "S", "SS", "SSS", "Unranked"]
CUTS = [10, 20, 30, 42, 55, 68, 80, 90, 97]  # a score at or above CUTS[i] is at least TIERS[i + 1]
MIN_CONTRIBUTIONS, MIN_ACTIVE_DAYS = 10, 5

TAGLINES = {
    "F": "Technically a GitHub account.",
    "E": "The repos are there. The commits are shy.",
    "D": "Shows up. Occasionally.",
    "C": "A perfectly average year. Nobody writes songs about those.",
    "B": "Solid. The kind of year a manager calls 'consistent'.",
    "A": "Properly good. Other people's streaks look at yours.",
    "S": "Elite. Your contribution graph could be a screensaver.",
    "SS": "Absurd. Do you sleep? The data says rarely.",
    "SSS": "Legendary. The graph is a solid block of green.",
    "Unranked": "Off the scale. The rank system filed a complaint.",
}


class Part(BaseModel):
    name: str
    points: float
    max: float
    note: str


class Rank(BaseModel):
    tier: str | None  # None: not enough activity to rank
    score: float  # 0-100
    parts: list[Part]
    tagline: str
    next_tier: str | None = None
    points_to_next: float | None = None


def _log_scale(value: float, *, zero: float, full: float, points: float) -> float:
    """0 at `zero`, `points` at `full`, logarithmic in between (volume-type stats)."""
    if value <= zero:
        return 0.0
    return min(points, points * math.log1p(value - zero) / math.log1p(full - zero))


def compute_rank(s: Stats) -> Rank:
    parts: list[Part] = []

    volume = _log_scale(s.commits, zero=0, full=2500, points=30)
    parts.append(Part(name="Volume", points=round(volume, 1), max=30, note=f"{s.commits:,} commits; 2,500 fills the bar"))

    days = max(1, s.days_in_window)
    share = s.active_days / days
    streak_bonus = min(5.0, s.longest_streak.days / 20)  # a 100-day streak is the most it can add
    consistency = min(25.0, 20 * min(1.0, share / 0.6) + streak_bonus)
    parts.append(Part(name="Consistency", points=round(consistency, 1), max=25, note=f"active {s.active_days} of {days} days; longest streak {s.longest_streak.days}"))

    collaboration = min(15.0, _log_scale(s.prs_opened, zero=0, full=60, points=7) + _log_scale(s.prs_merged, zero=0, full=40, points=4) + _log_scale(s.pr_reviews, zero=0, full=60, points=4))
    parts.append(Part(name="Collaboration", points=round(collaboration, 1), max=15, note=f"{s.prs_opened} PRs opened, {s.prs_merged} merged, {s.pr_reviews} reviews"))

    impact = _log_scale(s.stars_received, zero=0, full=1000, points=15)
    parts.append(Part(name="Impact", points=round(impact, 1), max=15, note=f"{s.stars_received:,} stars received this year"))

    craft = 10.0
    if s.messages_analyzed >= 10:
        fix_share = s.roast_words.get("fix", 0) / s.messages_analyzed
        craft -= min(4.0, 10 * max(0.0, fix_share - 0.15))  # up to -4 when a quarter+ of messages are "fix"
        craft -= min(4.0, 12 * (s.one_word_share or 0))  # one-word messages
        if (s.average_message_length or 0) < 15:
            craft -= 2
        craft = max(0.0, craft)
    else:
        craft = 5.0  # not enough public messages to judge: half marks
    parts.append(Part(name="Craft", points=round(craft, 1), max=10, note=f"{s.messages_analyzed} public commit messages judged on 'fix', one-worders and length"))

    breadth = min(5.0, max(0, len([lang for lang in s.languages if lang.share >= 0.03]) - 1) * 1.25)
    parts.append(Part(name="Breadth", points=round(breadth, 1), max=5, note=f"{len(s.languages)} languages, {sum(1 for lang in s.languages if lang.share >= 0.03)} with real share"))

    score = round(min(100.0, sum(p.points for p in parts)), 1)
    if s.total_contributions < MIN_CONTRIBUTIONS or s.active_days < MIN_ACTIVE_DAYS:
        return Rank(tier=None, score=score, parts=parts, tagline="Not enough activity in the last 12 months to rank. Commit something and come back.")

    index = sum(1 for cut in CUTS if score >= cut)
    tier = TIERS[index]
    next_tier = TIERS[index + 1] if index + 1 < len(TIERS) else None
    to_next = round(CUTS[index] - score, 1) if next_tier else None
    return Rank(tier=tier, score=score, parts=parts, tagline=TAGLINES[tier], next_tier=next_tier, points_to_next=to_next)
