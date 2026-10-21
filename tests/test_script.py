from zoneinfo import ZoneInfo

import pytest

from core.costs import CostLedger
from core.llm import LLMResult
from roastmygithub import script as s
from roastmygithub.highlights import pick
from roastmygithub.personas import PERSONAS
from roastmygithub.stats import compute_stats

TORONTO = ZoneInfo("America/Toronto")


class FakeLLM:
    model = "fake-model"

    def __init__(self, *drafts):
        self.drafts = list(drafts)
        self.calls = []

    def json(self, *, system, prompt, schema, name):
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        return LLMResult(data=self.drafts.pop(0), provider="fake", model=self.model, input_tokens=900, output_tokens=300, usd=0.01)


def draft(ids, words_per_line=22, sign_off="Class dismissed. Go write a test.", tones=None):
    line = " ".join(["word"] * words_per_line)
    tones = tones or ["roast", "compliment"] * len(ids)
    return {"beats": [{"stat_id": i, "tone": t, "line": line} for i, t in zip(ids, tones)], "sign_off": sign_off, "verdict": "Certified Night Owl"}


@pytest.fixture
def material(busy_year):
    stats = compute_stats(busy_year, tz=TORONTO)
    return stats, pick(stats)


def test_prompt_lists_every_highlight_and_the_length(material):
    stats, highlights = material
    prompt = s.build_prompt(stats, highlights, seconds=60)
    for h in highlights:
        assert f"id: {h.id} |" in prompt and h.fact in prompt
    assert "@me (Me Myself)" in prompt
    assert "about 141 words" in prompt and "between 120 and 158" in prompt
    assert "5 or 6 beats" in prompt
    assert "stealth" not in prompt and "acme" not in prompt  # private repo name and message
    assert "disappointed academic" in s.system_prompt(PERSONAS["professor"].style)
    assert "Go for the throat" in s.system_prompt(PERSONAS["professor"].style) and "never the human" in s.system_prompt(PERSONAS["professor"].style, "gentle")
    assert "At least 3 beats are roasts and at least 1 is a compliment" in prompt
    assert "at least 2 are compliments" in s.build_prompt(stats, highlights, seconds=60, heat="gentle")


def test_schema_only_allows_the_given_stat_ids(material):
    _, highlights = material
    ids = [h.id for h in highlights]
    assert s.schema(ids)["properties"]["beats"]["items"]["properties"]["stat_id"]["enum"] == ids


def test_write_script_returns_beats_and_logs_the_cost(material):
    stats, highlights = material
    ids = [h.id for h in highlights[:6]]
    llm, ledger = FakeLLM(draft(ids)), CostLedger()
    script = s.write_script(stats, highlights, PERSONAS["professor"], llm, seconds=60, ledger=ledger)
    assert [b.stat_id for b in script.beats] == ids
    assert script.persona == "professor" and script.verdict == "Certified Night Owl" and script.model == "fake-model"
    assert script.words == 6 * 22 + 6 and 55 < script.seconds < 62
    assert len(llm.calls) == 1 and ledger.usd_for("llm") == 0.01
    assert ledger.entries[0].kind == "write_script" and ledger.entries[0].status == "complete"


def test_a_draft_of_the_wrong_length_is_sent_back_once(material):
    stats, highlights = material
    ids = [h.id for h in highlights[:5]]
    llm = FakeLLM(draft(ids, words_per_line=60), draft(ids, words_per_line=27))
    script = s.write_script(stats, highlights, PERSONAS["hype"], llm, seconds=60)
    assert len(llm.calls) == 2 and script.words == 5 * 27 + 6
    retry = llm.calls[1]["prompt"]
    assert "it is 306 words; it must be between 120 and 158" in retry and "Your previous draft was:" in retry


def test_a_second_bad_draft_is_kept_rather_than_paid_for_again(material):
    stats, highlights = material
    ids = [h.id for h in highlights[:5]]
    llm = FakeLLM(draft(ids, words_per_line=60), draft(ids, words_per_line=50))
    script = s.write_script(stats, highlights, PERSONAS["senior"], llm, seconds=60)
    assert len(llm.calls) == 2 and script.words == 5 * 50 + 6


def test_repeated_and_unknown_stat_ids_are_dropped(material):
    stats, highlights = material
    ids = [h.id for h in highlights[:5]]
    bad = draft([ids[0], ids[0], "made_up", *ids[1:]], words_per_line=20)
    script = s.write_script(stats, highlights, PERSONAS["professor"], FakeLLM(bad, bad), seconds=60)
    assert [b.stat_id for b in script.beats] == ids


def test_fewer_highlights_means_fewer_beats(material):
    stats, highlights = material
    assert s.beat_range(4) == (4, 4) and s.beat_range(8) == (5, 6)
    assert "4 beats" in s.build_prompt(stats, highlights[:4], seconds=30)
    with pytest.raises(ValueError, match="at least 3"):
        s.write_script(stats, highlights[:2], PERSONAS["professor"], FakeLLM(), seconds=60)


def test_the_heat_sets_how_many_compliments_are_required(material):
    stats, highlights = material
    ids = [h.id for h in highlights[:6]]
    # Brutal: five roasts and one compliment is fine, no retry.
    llm = FakeLLM(draft(ids, tones=["roast"] * 5 + ["compliment"]))
    script = s.write_script(stats, highlights, PERSONAS["professor"], llm, seconds=60)
    assert len(llm.calls) == 1 and script.heat == "brutal" and [b.tone for b in script.beats].count("compliment") == 1
    # Brutal with no compliment at all, or gentle with only one, is sent back.
    llm = FakeLLM(draft(ids, tones=["roast"] * 6), draft(ids))
    s.write_script(stats, highlights, PERSONAS["professor"], llm, seconds=60)
    assert "only 0 beats are a compliment; it needs at least 1" in llm.calls[1]["prompt"]
    llm = FakeLLM(draft(ids, tones=["roast"] * 5 + ["compliment"]), draft(ids))
    gentle = s.write_script(stats, highlights, PERSONAS["professor"], llm, seconds=60, heat="gentle")
    assert "only 1 beats are a compliment; it needs at least 2" in llm.calls[1]["prompt"] and gentle.heat == "gentle"
    with pytest.raises(ValueError, match="heat must be"):
        s.write_script(stats, highlights, PERSONAS["professor"], FakeLLM(), seconds=60, heat="nuclear")


def test_a_script_remembers_its_figures_and_notices_when_they_change(material):
    stats, highlights = material
    ids = [h.id for h in highlights[:5]]
    script = s.write_script(stats, highlights, PERSONAS["professor"], FakeLLM(draft(ids, words_per_line=27)), seconds=60)
    assert script.cards[ids[0]] == highlights[0].value and not script.stale_cards(highlights)
    changed = [h.model_copy(update={"value": "999"}) if h.id == ids[1] else h for h in highlights]
    assert script.stale_cards(changed) == [(ids[1], highlights[1].value, "999")]


def test_numbers_the_facts_do_not_contain_are_sent_back(material):
    stats, highlights = material
    ids = [h.id for h in highlights[:5]]
    bad = draft(ids, words_per_line=27, sign_off="Now go fix all 901 characters of that novel.")
    llm = FakeLLM(bad, draft(ids, words_per_line=27))
    s.write_script(stats, highlights, PERSONAS["senior"], llm, seconds=60)
    assert "numbers that are not in the facts (901)" in llm.calls[1]["prompt"]
    assert s.invented_numbers({"beats": [{"line": "47% of 43 commits"}], "sign_off": ""}, "47% of commits (20 of 43 analysed)") == []
    assert s.invented_numbers({"beats": [{"line": "about 1,234 lines"}], "sign_off": ""}, "1234 lines") == []


def test_a_voice_with_a_known_way_of_talking_shapes_the_script(material):
    trump = s.system_prompt(PERSONAS["senior"].style, "brutal", "Donald Trump")
    assert "impression of Donald Trump" in trump and "Superlatives" in trump and "never say the person's name" in trump
    plain = s.system_prompt(PERSONAS["senior"].style, "brutal", "narrator")
    assert "persona's own way of talking" in plain and "read by an impression of" not in plain
    stats, highlights = material
    ids = [h.id for h in highlights[:5]]
    styled = s.write_script(stats, highlights, PERSONAS["senior"], FakeLLM(draft(ids, words_per_line=27)), seconds=60, voice="Donald Trump")
    unstyled = s.write_script(stats, highlights, PERSONAS["senior"], FakeLLM(draft(ids, words_per_line=27)), seconds=60, voice="Nobody Known")
    assert styled.voice == "Donald Trump" and unstyled.voice is None


def test_machine_written_tells_are_named():
    assert s.tells(["Short. Then a longer sentence that lands somewhere real.", "You pushed at 2 AM again."]) == []
    contrast = s.tells(["That's not a commit, that's a novel.", "The repo wasn't broken, it was hibernating."])
    assert len(contrast) == 1 and "that's not X" in contrast[0] and "hibernating" in contrast[0]
    assert "no colons" in s.tells(["Nit: 2 AM is not a release window"])[0]
    assert "filler words (genuinely)" in s.tells(["That was genuinely impressive."])[0]
    assert s.tells(["Trump would never."], voice="Donald Trump") == ["never say the name of the person whose voice reads this"]
    assert s.tells(["Yoda would never."], voice="Yoda") == []  # characters may be named


def test_a_draft_with_tells_is_sent_back(material):
    stats, highlights = material
    ids = [h.id for h in highlights[:5]]
    bad = draft(ids, words_per_line=27, sign_off="That's not a sign off, that's a cry for help.")
    llm = FakeLLM(bad, draft(ids, words_per_line=27))
    s.write_script(stats, highlights, PERSONAS["senior"], llm, seconds=60)
    assert len(llm.calls) == 2 and "say the joke straight" in llm.calls[1]["prompt"]
    assert "options" in s.schema(ids)["properties"]["beats"]["items"]["required"]
