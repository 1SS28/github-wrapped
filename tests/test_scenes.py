from datetime import date
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from roastmygithub import scenes
from roastmygithub.cards import THEMES
from roastmygithub.highlights import Highlight, candidates
from roastmygithub.stats import compute_stats

TORONTO = ZoneInfo("America/Toronto")


@pytest.fixture
def stats(busy_year):
    return compute_stats(busy_year, tz=TORONTO)


def frame(scene, t, duration=6.0, theme="senior"):
    area = Image.new("RGB", (scenes.WIDTH, scenes.AREA_HEIGHT), THEMES[theme].bottom)
    scene(area, t, duration)
    return area


def test_every_candidate_has_a_scene_that_draws(stats):
    for h in candidates(stats):
        scene = scenes.make_scene(h, stats, THEMES["professor"], "roast")
        before = frame(scene, 0.0)
        after = frame(scene, 3.0)
        assert after.getbbox() is not None
        assert after.tobytes() != before.tobytes(), h.id  # it moves


def test_unknown_highlights_fall_back_to_the_headline(stats):
    h = Highlight(id="something_new", group="x", kind="roast", value="7", label="mystery", fact="", score=0.1)
    assert frame(scenes.make_scene(h, stats, THEMES["hype"], "roast"), 2.0).getbbox() is not None


def test_numbers_count_up_in_their_own_format():
    assert scenes.counting("1,234", 0.5) == "617"
    assert scenes.counting("48%", 0.5) == "24%"
    assert scenes.counting("+9,000", 0.5) == "+4,500"
    assert scenes.counting("2 of 3", 0.5) == "1 of 3"
    assert scenes.counting("Saturday", 0.2) == "Saturday"
    assert scenes.counting("1 AM", 1.0) == "1 AM"


def test_the_terminal_shows_matching_commits_and_highlights_the_word(stats):
    ctx = scenes.Ctx(Highlight(id="word_wip", group="messages", kind="roast", value="10×", label="", fact="", score=0.5), stats, THEMES["senior"], "roast")
    lines, pattern, stop = scenes._log_lines(ctx, "word:wip")
    assert len(lines) == 10 and all(pattern.search(line.headline) for line in lines) and stop is None
    lines, _, stop = scenes._log_lines(ctx, "shortest")
    assert lines[stop].headline == "."


def test_private_repos_stay_anonymous_in_scenes(stats):
    assert all("stealth" not in line.repo for line in stats.commit_log)
    assert [r.name for r in stats.new_repos] == ["idea-1", "idea-2", "idea-3"]
    assert stats.calendar[-1].date == date(2026, 10, 5)
