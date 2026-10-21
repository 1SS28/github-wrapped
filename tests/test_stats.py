from datetime import date
from zoneinfo import ZoneInfo

import pytest

from roastmygithub.stats import PRIVATE_REPO, compute_stats, local_timezone
from tests.conftest import commit, make_activity

TORONTO = ZoneInfo("America/Toronto")


def test_calendar_streaks_gaps_and_weekdays(busy_year):
    s = compute_stats(busy_year, tz=TORONTO)
    assert s.days_in_window == 366 and s.active_days == 41
    assert (s.longest_streak.days, s.longest_streak.start, s.longest_streak.end) == (40, date(2026, 3, 1), date(2026, 4, 9))
    assert (s.longest_gap.days, s.longest_gap.start, s.longest_gap.end) == (147, date(2025, 10, 5), date(2026, 2, 28))
    assert s.current_streak == 0
    assert (s.busiest_day.date, s.busiest_day.count) == (date(2026, 6, 6), 30)
    assert s.busiest_weekday == "Saturday"
    assert s.weekend_share == pytest.approx(74 / 190, abs=1e-4)


def test_current_streak_survives_an_empty_today():
    days = {"2026-10-02": 1, "2026-10-03": 2, "2026-10-04": 1}  # nothing yet on the 5th, the last day
    assert compute_stats(make_activity(days=days), tz=TORONTO).current_streak == 3
    days["2026-10-05"] = 1
    assert compute_stats(make_activity(days=days), tz=TORONTO).current_streak == 4


def test_days_before_the_account_existed_are_not_a_gap():
    s = compute_stats(make_activity(days={"2026-09-01": 1}, created_at="2026-08-20T10:00:00Z"), tz=TORONTO)
    assert s.days_in_window == 47  # Aug 20 - Oct 5
    assert s.longest_gap.days == 34 and s.longest_gap.start == date(2026, 9, 2)


def test_clock_uses_the_commit_offset_and_falls_back_to_the_timezone():
    commits = [
        commit("a", "2026-06-01T02:30:00+09:00"),  # 2:30 AM where it was written, whatever the machine says
        commit("b", "2026-06-05T21:30:00Z"),  # no offset: 5:30 PM Friday in Toronto
        commit("c", "2026-01-11T04:30:00Z"),  # 11:30 PM Saturday, in winter time
    ]
    s = compute_stats(make_activity(commits=commits), tz=TORONTO)
    assert s.hour_commits[2] == 1 and s.hour_commits[17] == 1 and s.hour_commits[23] == 1
    assert s.after_midnight_share == pytest.approx(1 / 3, abs=1e-4)
    assert s.friday_evening_commits == 1
    assert s.clock == "America/Toronto"  # most commits had no offset of their own


def test_messages_come_from_public_repos_unless_private_is_included(busy_year):
    public = compute_stats(busy_year, tz=TORONTO)
    assert public.text_scope == "public" and public.messages_analyzed == 42
    assert public.roast_words["fix"] == 20 and public.roast_words["wip"] == 10 and public.roast_words["final"] == 1
    assert (public.most_repeated_message.text, public.most_repeated_message.count) == ("fix login", 20)
    assert public.shortest_message.text == "."
    assert "acme" not in {w.word for w in public.top_words}

    everything = compute_stats(busy_year, include_private=True, tz=TORONTO)
    assert everything.text_scope == "all" and everything.messages_analyzed == 43
    assert everything.longest_message.text == "secret roadmap for acme"


def test_private_names_and_messages_never_reach_public_stats(busy_year):
    dumped = compute_stats(busy_year, tz=TORONTO).model_dump_json()
    assert "stealth" not in dumped and "acme" not in dumped
    s = compute_stats(busy_year, tz=TORONTO)
    assert s.top_repos[1].name == PRIVATE_REPO and s.top_repos[1].commits == 100  # counted, not named
    assert s.biggest_commit.additions == 9000 and s.biggest_commit.headline is None and s.biggest_commit.repo == PRIVATE_REPO
    assert s.lines_added == 13_320  # private lines still count

    opted_in = compute_stats(busy_year, include_private=True, tz=TORONTO)
    assert opted_in.top_repos[1].name == "me/stealth" and opted_in.biggest_commit.headline == "secret roadmap for acme"


def test_merge_commits_count_for_the_clock_but_not_for_messages_or_lines():
    commits = [commit("Merge branch 'main'", merge=True, additions=5000), commit("real work", additions=7)]
    s = compute_stats(make_activity(commits=commits), tz=TORONTO)
    assert s.commits_sampled == 2 and s.messages_analyzed == 1 and s.lines_added == 7


def test_languages_are_weighted_by_commits(busy_year):
    s = compute_stats(busy_year, tz=TORONTO)
    assert [(lang.name, lang.share) for lang in s.languages] == [("Python", 0.675), ("Go", 0.25), ("Shell", 0.075)]


def test_repos_started_abandoned_and_stars(busy_year):
    s = compute_stats(busy_year, tz=TORONTO)
    assert (s.repos_created, s.repos_abandoned) == (3, 2)  # idea-3 is too recent to call abandoned
    assert (s.stars_received, s.stars_all_time) == (1, 3)


def test_merged_pull_requests_are_counted_inside_the_window():
    prs = [
        {"merged": True, "merged_at": "2026-05-01T00:00:00Z", "created_at": "2026-04-30T00:00:00Z", "repo": "me/app", "private": False},
        {"merged": False, "merged_at": None, "created_at": "2026-04-30T00:00:00Z", "repo": "me/app", "private": False},
    ]
    s = compute_stats(make_activity(pull_requests=prs, totals={"pull_requests": 2}), tz=TORONTO)
    assert (s.prs_opened, s.prs_merged) == (2, 1)


def test_unknown_timezone_is_rejected():
    with pytest.raises(ValueError, match="unknown timezone"):
        local_timezone("Mars/Olympus_Mons")
    assert local_timezone("Europe/Berlin").key == "Europe/Berlin"


def test_scene_data_respects_the_text_scope(busy_year):
    s = compute_stats(busy_year, tz=TORONTO)
    assert len(s.calendar) == 366 and s.calendar[0].date == date(2025, 10, 5)
    assert len(s.commit_log) == 42 and s.commit_log[0].headline == "final2 for real"  # newest first, public only
    assert s.commit_log[0].repo == "app" and s.commit_log[0].oid == "abc1234"
    assert [(r.name, r.abandoned) for r in s.new_repos] == [("idea-1", True), ("idea-2", True), ("idea-3", False)]
    assert "stealth" not in s.model_dump_json()
