import json

import pytest
from rich.console import Console

from core.llm import LLMResult
from roastmygithub import github
from roastmygithub.config import Settings
from roastmygithub.pipeline import Pipeline, PipelineError, RunOptions
from tests.conftest import FakeGitHubAPI


class FakeLLM:
    model = "fake-model"

    def __init__(self):
        self.prompts = []

    def json(self, *, system, prompt, schema, name):
        self.prompts.append(prompt)
        ids = schema["properties"]["beats"]["items"]["properties"]["stat_id"]["enum"]
        line = " ".join(["word"] * 26)
        data = {"beats": [{"stat_id": i, "tone": ("roast", "compliment")[n % 2], "line": line} for n, i in enumerate(ids[:5])], "sign_off": "Now go and commit something.", "verdict": "Barely Passing"}
        return LLMResult(data=data, provider="fake", model=self.model, input_tokens=1000, output_tokens=400, usd=0.012)


@pytest.fixture
def api():
    # Enough history for the clock and message highlights: 30 commits at 1 AM, most saying "fix".
    page = [("fix the build", "2026-06-01T01:00:00-04:00")] * 24 + [("wip", "2026-06-02T15:00:00-04:00")] * 6
    return FakeGitHubAPI(history_pages={"R1": [page]})


def make(tmp_path, api, *, llm=None, **opts):
    settings = Settings(_env_file=None, roastmygithub_cache_dir=tmp_path / "cache", llm_api_key="", llm_model="", magic_hour_api_key="", github_token="")
    console = Console(record=True, width=200)
    gh = github.GitHub("token", transport=api.transport())
    pipeline = Pipeline(RunOptions(out=tmp_path / "out", **opts), settings, console, github=gh, llm=llm)
    return pipeline, console


def test_dry_run_writes_stats_highlights_script_and_an_estimate(tmp_path, api):
    llm = FakeLLM()
    pipeline, console = make(tmp_path, api, llm=llm, dry_run=True, persona="senior")
    report = pipeline.run()
    out = tmp_path / "out"
    stats = json.loads((out / "stats.json").read_text())
    highlights = json.loads((out / "highlights.json").read_text())
    script = json.loads((out / "script_senior.json").read_text())
    assert stats["login"] == "me" and stats["commits"] == 42
    assert {"total_commits", "after_midnight", "repeated_message"} <= {h["id"] for h in highlights}
    assert len(script["beats"]) == 5 and script["persona"] == "senior"
    assert report["dry_run"] is True and report["script"]["verdict"] == "Barely Passing"
    # Only the voice is paid for: 0.1 credit a character, rounded up per line.
    assert report["estimate"]["voice_credits"] == sum(-(-len(line) // 10) for line in [b["line"] for b in script["beats"]] + [script["sign_off"]])
    assert report["totals"]["llm_usd"] == 0.012 and report["totals"]["magichour_credits"] == 0
    assert set(report["stage_seconds"]) == {"collect", "stats", "script"}
    text = console.export_text()
    assert "The Tired Senior Engineer" in text and "Cached work is free" in text
    assert report["estimate"]["art_credits"] == 5 * 10 + 2 * 96  # five illustrations, two animated


def test_second_run_uses_the_cache_and_refresh_ignores_it(tmp_path, api):
    make(tmp_path, api, dry_run=True)[0].run()
    cache = list((tmp_path / "cache").glob("activity-me-*.json"))
    assert len(cache) == 1 and cache[0].stat().st_mode & 0o077 == 0  # owner-only
    first = len(api.calls)

    make(tmp_path, api, dry_run=True)[0].run()
    assert len(api.calls) == first + 1  # only the "who am I" check

    make(tmp_path, api, dry_run=True, refresh=True)[0].run()
    assert len(api.calls) == 2 * first + 1


def test_dry_run_without_an_llm_still_reports_and_shows_the_prompt(tmp_path, api):
    pipeline, console = make(tmp_path, api, dry_run=True, show_prompt=True)
    report = pipeline.run()
    assert report["script"] is None and report["estimate"]["voice_credits"] == 85
    text = console.export_text()
    assert "No script written" in text and "<facts>" in text
    assert not (tmp_path / "out" / "script_professor.json").exists()


def render_setup(tmp_path, api, *, pace=0.02, **opts):
    """A pipeline with a fake Magic Hour behind it and a voice sample."""
    from core.magichour import MagicHour
    from tests.conftest import FakeMagicHourAPI

    fake = FakeMagicHourAPI(tmp_path, seconds_per_character=pace)  # short voice by default: quick tests
    sample = tmp_path / "sample.wav"
    if not sample.exists():
        sample.write_bytes(fake._media({"kind": "audio", "seconds": 4}))
    opts = {"yes": True, "voice_sample": sample, **opts}
    pipeline, console = make(tmp_path, api, llm=FakeLLM(), **opts)
    pipeline._magichour = MagicHour("key", transport=fake.transport(), poll_interval=0)
    return pipeline, console, fake


def test_render_clones_each_line_and_animates_the_year_without_a_presenter(tmp_path, api):
    from core import compose

    pipeline, console, fake = render_setup(tmp_path, api)
    report = pipeline.run()

    from collections import Counter

    calls = Counter(path for path, _ in fake.created)
    assert calls == {"/v1/ai-voice-generator": 6, "/v1/ai-image-generator": 5, "/v1/image-to-video": 2}  # one line each, one picture per beat, opener and finale animated
    assert {body["style"]["voice_name"] for path, body in fake.created if path == "/v1/ai-voice-generator"} == {"David Attenborough"}  # the professor's default voice
    assert report["voice"] == "David Attenborough" and report["video"].endswith("roast_me_professor_david-attenborough.mp4")
    prompts = [body["style"]["prompt"] for path, body in fake.created if path == "/v1/ai-image-generator"]
    assert all("No people" in p and "etching-style print" in p for p in prompts)
    voice = json.loads((tmp_path / "out" / "professor" / "voice.json").read_text())
    assert len(voice["lines"]) == 6 and voice["lines"][0]["start"] == 0
    assert all(a["end"] < b["start"] for a, b in zip(voice["lines"], voice["lines"][1:]))  # a pause between lines

    video = tmp_path / "out" / "roast_me_professor_david-attenborough.mp4"
    assert report["video"] == str(video) and report["preview"] is False
    assert compose.probe_duration(video) == pytest.approx(voice["duration"] + 3.5, abs=0.15)  # plus the end card
    expected = sum(job["credits"] for job in fake.jobs.values())
    assert report["totals"]["magichour_credits"] == expected and report["totals"]["failures"] == 0
    assert {"art", "voice", "compose"} <= set(report["stage_seconds"])
    assert "5 of 5 beats illustrated, 2 animated" in console.export_text(clear=False)
    assert "Video:" in console.export_text()


def test_a_second_render_of_the_same_script_is_free(tmp_path, api):
    render_setup(tmp_path, api)[0].run()
    pipeline, _, fake = render_setup(tmp_path, api)
    report = pipeline.run()
    assert fake.created == [] and report["totals"]["magichour_credits"] == 0


def test_preview_is_free_and_needs_no_keys_or_assets(tmp_path, api, monkeypatch):
    from core import compose

    monkeypatch.setattr("roastmygithub.personas.ASSETS", tmp_path / "no-bundled-assets")
    pipeline, console = make(tmp_path, api, llm=FakeLLM(), preview=True, seconds=20)
    report = pipeline.run()
    video = tmp_path / "out" / "roast_me_professor_david-attenborough_preview.mp4"
    assert report["video"] == str(video) and report["preview"] is True
    assert report["totals"]["magichour_credits"] == 0
    assert 55 < compose.probe_duration(video) < 70  # timed from the script's words, not from --seconds
    assert "Nothing was spent" in console.export_text()


def test_an_edited_script_file_replaces_the_llm(tmp_path, api):
    pipeline, _ = make(tmp_path, api, llm=FakeLLM(), dry_run=True)
    script = pipeline.run()["script"]
    script["beats"][0]["line"] = "Edited by hand."
    path = tmp_path / "mine.json"
    path.write_text(json.dumps(script))

    pipeline, console = make(tmp_path, api, dry_run=True, script_file=path, persona="hype")  # no LLM configured
    report = pipeline.run()
    assert report["script"]["beats"][0]["line"] == "Edited by hand." and report["script"]["persona"] == "hype"

    script["beats"][0]["stat_id"] = "not_a_stat"
    path.write_text(json.dumps(script))
    with pytest.raises(PipelineError, match="not in today's highlights: not_a_stat"):
        make(tmp_path, api, dry_run=True, script_file=path)[0].run()


def test_spending_needs_a_yes_a_budget_and_the_assets(tmp_path, api, monkeypatch):
    monkeypatch.setattr("roastmygithub.personas.ASSETS", tmp_path / "no-bundled-assets")
    with pytest.raises(PipelineError, match="--yes"):
        render_setup(tmp_path, api, yes=False)[0].run()
    with pytest.raises(PipelineError, match="over --max-credits 10"):
        render_setup(tmp_path, api, max_credits=10)[0].run()
    pipeline, _, fake = render_setup(tmp_path, api)
    fake.credits = 10
    with pytest.raises(PipelineError, match="not enough credits"):
        pipeline.run()
    assert fake.created == []
    with pytest.raises(PipelineError, match="--voice-sample"):
        render_setup(tmp_path, api, voice_sample=None, voice="narrator")[0].run()  # only the cloned voice needs a sample
    with pytest.raises(PipelineError, match="LLM_API_KEY"):
        make(tmp_path, api)[0].run()


def test_unknown_persona_is_rejected(tmp_path, api):
    with pytest.raises(PipelineError, match="unknown persona"):
        make(tmp_path, api, persona="clown")


def test_the_data_style_needs_no_pictures(tmp_path, api):
    pipeline, _, fake = render_setup(tmp_path, api, style="data")
    report = pipeline.run()
    assert {path for path, _ in fake.created} == {"/v1/ai-voice-generator"}
    assert report["estimate"]["art_credits"] == 0 and report["video"].endswith("roast_me_professor_david-attenborough.mp4")


def test_the_narrator_voice_is_cloned_and_other_voices_are_checked(tmp_path, api):
    pipeline, _, fake = render_setup(tmp_path, api, style="data", voice="narrator")
    pipeline.run()
    assert {path for path, _ in fake.created} == {"/v1/ai-voice-cloner"}
    pipeline, _, fake = render_setup(tmp_path, api, style="data", voice="elon musk")
    report = pipeline.run()
    assert report["voice"] == "Elon Musk" and {body["style"]["voice_name"] for _, body in fake.created} == {"Elon Musk"}
    with pytest.raises(PipelineError, match="unknown voice"):
        render_setup(tmp_path, api, voice="Nobody Famous")
