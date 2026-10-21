from pathlib import Path

from PIL import Image

from roastmygithub import cards, render
from roastmygithub.voice import TimedLine, VoiceTrack


def test_end_card_is_a_full_frame(tmp_path, busy_year):
    from zoneinfo import ZoneInfo

    from roastmygithub.highlights import pick
    from roastmygithub.script import Script
    from roastmygithub.stats import compute_stats

    stats = compute_stats(busy_year, tz=ZoneInfo("America/Toronto"))
    script = Script(persona="hype", verdict="A Very Long Verdict That Has To Shrink To Fit", beats=[], sign_off="")
    path = cards.render_end_card(stats, script, pick(stats)[:4], tmp_path / "end.png", theme=cards.THEMES["hype"], persona_title="The Hype Commentator", repo_url="github.com/me/x")
    with Image.open(path) as image:
        assert image.size == (1080, 1920)


def test_words_share_out_each_line_by_length():
    words = render.spread_words([TimedLine(text="I am disappointed", start=1.0, end=3.0), TimedLine(text="Truly.", start=3.4, end=4.0)])
    assert [w.text for w in words] == ["I", "am", "disappointed", "Truly."]
    assert words[0].start == 1.0 and words[2].end == 3.0 and words[3].start == 3.4
    assert words[2].end - words[2].start > words[0].end - words[0].start
    assert all(a.end <= b.start + 1e-6 for a, b in zip(words, words[1:]))


def test_a_line_is_set_in_the_frame_word_by_word_and_shrinks_to_fit():
    from PIL import ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (cards.WIDTH, cards.FRAME_HEIGHT)))
    short = render.set_line(render.spread_words([TimedLine(text="Sit down. Now.", start=0.0, end=2.0)]), draw)
    assert [w.text for w in short.words] == ["Sit", "down.", "Now."] and short.size == render.LINE_SIZES[0]
    assert short.words[0].start == 0.0 and short.words[2].start > short.words[1].start

    long = render.set_line(render.spread_words([TimedLine(text="word " * 80, start=0.0, end=20.0)]), draw)
    assert long.size < short.size
    assert all(cards.PAD <= w.x < cards.WIDTH - cards.PAD for w in long.words)
    assert max(w.y for w in long.words) < render.LINE_BOTTOM


def test_silent_track_times_lines_from_their_word_counts(tmp_path):
    track = render.silent_track(["one two three four five six", "seven"], tmp_path, words_per_second=2.0)
    assert (track.lines[0].start, track.lines[0].end) == (0.0, 3.0)
    assert track.lines[1].start == 3.35 and track.duration == 3.35 + 0.8 + 0.6
    assert track.audio.exists()
