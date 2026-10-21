from pathlib import Path

from core.magichour import MagicHour
from roastmygithub import art
from tests.conftest import FakeMagicHourAPI


def client(fake):
    return MagicHour("key", transport=fake.transport(), poll_interval=0)


def test_prompts_carry_the_art_direction_and_the_no_people_rule():
    prompt = art.prompt_for("a desk lamp at 3 AM", "Flat vector, green and yellow.")
    assert prompt.startswith("a desk lamp at 3 AM. Drawn like a single frame") and "no border" in prompt and "Flat vector, green and yellow." in prompt
    assert "No people" in prompt and "no numbers" in prompt
    assert "empty desk" in art.prompt_for("", "x")


def test_one_image_per_beat_plus_clips_for_heroes(tmp_path):
    fake = FakeMagicHourAPI(tmp_path)
    with client(fake) as mh:
        works = art.generate(mh, ["lamp", "rocket", "highway"], art_direction="Flat.", workdir=tmp_path / "art", heroes={0, 2})
    assert [path for path, _ in fake.created].count("/v1/ai-image-generator") == 3
    assert [path for path, _ in fake.created].count("/v1/image-to-video") == 2
    assert all(w.image.exists() and not w.fallback for w in works)
    assert works[0].video and works[0].video.exists() and works[1].video is None and works[2].video
    assert fake.face_checks == 3
    assert art.estimate_credits(3, heroes=2) == 30 + 2 * 4 * 24
    assert art.pending(["lamp", "rocket", "highway"], art_direction="Flat.", workdir=tmp_path / "art", heroes={0, 2}) == (0, 0)
    assert art.pending(["lamp", "new"], art_direction="Flat.", workdir=tmp_path / "art", heroes={1}) == (1, 1)


def test_a_face_means_a_redraw_then_a_fallback(tmp_path):
    fake = FakeMagicHourAPI(tmp_path)
    fake.faces_on_checks = {1, 2}  # first beat: both attempts show a face; second beat: clean
    with client(fake) as mh:
        works = art.generate(mh, ["crowd", "lamp"], art_direction="Flat.", workdir=tmp_path / "art", concurrency=1)
    assert works[0].fallback and works[0].faces_found == 2 and not works[0].image.exists()
    assert not works[1].fallback and works[1].image.exists()
    prompts = [body["style"]["prompt"] for path, body in fake.created if path == "/v1/ai-image-generator"]
    assert len(prompts) == 3 and prompts[1].endswith(art.RETRY_SUFFIX)


def test_without_magic_hour_only_cached_art_is_used(tmp_path):
    fake = FakeMagicHourAPI(tmp_path)
    with client(fake) as mh:
        art.generate(mh, ["lamp"], art_direction="Flat.", workdir=tmp_path / "art")
    works = art.generate(None, ["lamp", "rocket"], art_direction="Flat.", workdir=tmp_path / "art", heroes={0})
    assert works[0].image.exists() and not works[0].fallback and works[0].video is None
    assert works[1].fallback
