from collections import Counter
from zoneinfo import ZoneInfo

from roastmygithub.highlights import DEFAULT_GROUP_LIMIT, GROUP_LIMIT, candidates, pick
from roastmygithub.stats import compute_stats
from tests.conftest import commit, make_activity

TORONTO = ZoneInfo("America/Toronto")


def by_id(highlights):
    return {h.id: h for h in highlights}


def test_candidates_carry_the_real_numbers(busy_year):
    found = by_id(candidates(compute_stats(busy_year, tz=TORONTO)))
    assert found["total_commits"].value == "400" and found["total_commits"].kind == "flex"
    assert found["after_midnight"].value == "47%" and "20 of 43" in found["after_midnight"].fact
    assert found["fix_share"].value == "48%"
    assert found["repeated_message"].value == "20×" and "fix login" in found["repeated_message"].label
    assert found["shortest_message"].value == "“.”"
    assert found["longest_streak"].value == "40" and "March 1 to April 9" in found["longest_streak"].fact
    assert found["longest_gap"].value == "147"
    assert found["busiest_weekday"].value == "Saturday"
    assert found["abandoned_repos"].value == "2 of 3"
    assert found["no_pull_requests"].value == "0"
    assert found["busiest_hour"].value == "2 AM"
    assert found["word_wip"].value == "10×"  # ten "wip"s outrank a single "final2"
    assert found["biggest_commit"].value == "+9,000" and "roadmap" not in found["biggest_commit"].fact


def test_pick_keeps_variety_and_leads_with_the_strongest(busy_year):
    chosen = pick(compute_stats(busy_year, tz=TORONTO))
    assert len(chosen) == 8 and len({h.id for h in chosen}) == 8
    assert chosen[0].score == 1.0 and "total_commits" in {h.id for h in chosen}
    assert [h.score for h in chosen] == sorted((h.score for h in chosen), reverse=True)
    for group, used in Counter(h.group for h in chosen).items():
        assert used <= GROUP_LIMIT.get(group, DEFAULT_GROUP_LIMIT)
    assert len({h.group for h in chosen}) >= 5


def test_private_text_stays_out_of_highlights(busy_year):
    for h in candidates(compute_stats(busy_year, tz=TORONTO)):
        assert "stealth" not in h.fact + h.label + h.value and "acme" not in h.fact + h.label + h.value


def test_a_quiet_year_still_gets_highlights():
    activity = make_activity(days={"2026-09-01": 3}, commits=[commit("first"), commit("second"), commit("third")])
    chosen = pick(compute_stats(activity, tz=TORONTO))
    assert chosen[0].id == "total_commits" and chosen[0].kind == "roast"
    assert "longest_gap" in {h.id for h in chosen}
    # Too few commits to say anything about the clock or message habits.
    assert not {"after_midnight", "busiest_hour", "fix_share"} & {h.id for h in chosen}


def test_pick_fills_up_past_the_group_limits_when_variety_runs_out(busy_year):
    stats = compute_stats(busy_year, tz=TORONTO)
    everything = candidates(stats)
    assert len(pick(stats, count=len(everything))) == len(everything)


def test_pick_is_balanced_between_praise_and_teasing(busy_year):
    kinds = Counter(h.kind for h in pick(compute_stats(busy_year, tz=TORONTO)))
    assert kinds["flex"] >= 3 and kinds["roast"] >= 3
