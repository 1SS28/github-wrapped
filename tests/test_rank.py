from zoneinfo import ZoneInfo

from roastmygithub import rank
from roastmygithub.stats import compute_stats
from tests.conftest import commit, make_activity

TORONTO = ZoneInfo("America/Toronto")


def test_tiers_are_fixed_cuts_on_the_score():
    assert rank.TIERS == ["F", "E", "D", "C", "B", "A", "S", "SS", "SSS", "Unranked"]
    assert len(rank.CUTS) == len(rank.TIERS) - 1 and rank.CUTS == sorted(rank.CUTS)


def test_a_busy_year_gets_a_mid_tier_with_a_breakdown(busy_year):
    r = rank.compute_rank(compute_stats(busy_year, tz=TORONTO))
    assert r.tier in ("D", "C", "B") and 0 < r.score < 100
    assert [p.name for p in r.parts] == ["Volume", "Consistency", "Collaboration", "Impact", "Craft", "Breadth"]
    assert all(0 <= p.points <= p.max for p in r.parts) and abs(sum(p.points for p in r.parts) - r.score) < 0.2
    assert r.next_tier and r.points_to_next and r.points_to_next > 0
    assert r.tagline == rank.TAGLINES[r.tier]


def test_too_little_activity_has_no_tier():
    r = rank.compute_rank(compute_stats(make_activity(days={"2026-09-01": 3}, commits=[commit("x")]), tz=TORONTO))
    assert r.tier is None and "Not enough" in r.tagline


def test_the_scale_tops_out_at_unranked():
    days = {f"2026-{m:02d}-{d:02d}": 12 for m in range(1, 10) for d in range(1, 29)}
    commits = [commit(f"Refactor the {i} module for clarity and tests", f"2026-05-{(i % 28) + 1:02d}T10:00:00-04:00") for i in range(300)]
    repos = [{"id": "R1", "name": "me/app", "private": False, "fork": False, "stars": 5000, "commits": 3000, "language": "Rust",
              "languages": {"Rust": 500, "TypeScript": 300, "Python": 200, "Go": 100, "Shell": 50}}]
    prs = [{"merged": True, "merged_at": "2026-05-02T00:00:00Z", "created_at": "2026-05-01T00:00:00Z", "repo": "me/app", "private": False}] * 80
    owned = [{"name": "me/app", "private": False, "archived": False, "stars": 5000, "created_at": "2024-01-01T00:00:00Z", "pushed_at": "2026-10-01T00:00:00Z", "stars_in_window": 2500, "stars_capped": False}]
    activity = make_activity(days=days, commits=commits, repos=repos, pull_requests=prs, owned=owned, totals={"pull_requests": 80, "reviews": 120})
    r = rank.compute_rank(compute_stats(activity, tz=TORONTO))
    assert r.tier == "Unranked" and r.score >= 97 and r.next_tier is None
