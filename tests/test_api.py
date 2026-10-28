import time

import pytest
from fastapi.testclient import TestClient

from core.llm import LLMResult
from core.magichour import MagicHour
from roastmygithub import github
from roastmygithub.config import Settings
from roastmygithub.service import Service
from tests.conftest import FakeGitHubAPI, FakeMagicHourAPI


class FakeLLM:
    model = "fake"

    def json(self, *, system, prompt, schema, name):
        ids = schema["properties"]["beats"]["items"]["properties"]["stat_id"]["enum"]
        line = " ".join(["word"] * 26)
        beats = [{"stat_id": i, "tone": ("roast", "compliment")[n % 2], "line": line, "visual": f"a picture of {i}"} for n, i in enumerate(ids[:5])]
        return LLMResult(data={"beats": beats, "sign_off": "Go commit something.", "verdict": "Barely Passing"}, provider="fake", model="fake", input_tokens=1, output_tokens=1, usd=0.001)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """An API wired to fake GitHub, LLM and Magic Hour; a sample voice for every persona."""
    from api.app import create_app
    from roastmygithub import personas

    monkeypatch.setattr(personas, "ASSETS", tmp_path / "assets")
    page = [("fix the build", "2026-06-01T01:00:00-04:00")] * 24 + [("wip", "2026-06-02T15:00:00-04:00")] * 6
    gh_api = FakeGitHubAPI(history_pages={"R1": [page]})
    mh_api = FakeMagicHourAPI(tmp_path, seconds_per_character=0.02)
    (tmp_path / "assets" / "voices").mkdir(parents=True)
    for key in personas.PERSONAS:
        (tmp_path / "assets" / "voices" / f"{key}.wav").write_bytes(mh_api._media({"kind": "audio", "seconds": 3}))

    class TestService(Service):
        def make_github(self):
            return github.GitHub("t", transport=gh_api.transport())

        def make_llm(self):
            return FakeLLM()

        def make_magichour(self, key, ledger):
            assert key == "mh-test-key-0123456789"
            return MagicHour(key, ledger=ledger, transport=mh_api.transport(), poll_interval=0)

    service = TestService(Settings(_env_file=None, github_token="t", llm_api_key="k", llm_model="fake"), out_dir=tmp_path / "web")
    return TestClient(create_app(service)), gh_api, mh_api


def wait(client, job):
    for _ in range(400):
        state = client.get(f"/api/jobs/{job['id']}").json()
        if state["status"] in ("done", "error"):
            return state
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_wrap_is_public_cached_and_needs_no_magic_hour(world):
    client, gh_api, _ = world
    first = client.get("/api/wrap/Someone?persona=professor")
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["login"] == "me" and data["scope"] == "public" and data["persona"] == "professor"
    assert len(data["script"]["beats"]) == 5 and data["magic_ready"] is False and data["video"] is None
    assert {"calendar", "hour_commits", "languages"} <= set(data["stats"])
    assert data["rank"]["tier"] is None and "Not enough" in data["rank"]["tagline"]  # one active day in the fake year
    assert len(data["rank"]["parts"]) == 6 and 0 <= data["rank"]["score"] <= 100
    assert all("user(login: $login)" in c["query"] for c in gh_api.calls if "contributionsCollection" in c["query"])
    calls = len(gh_api.calls)
    assert client.get("/api/wrap/someone?persona=professor").json()["cached_at"] == data["cached_at"]
    assert len(gh_api.calls) == calls  # served from the cache


def test_bad_logins_and_opted_out_logins_are_refused(world, monkeypatch):
    client, _, _ = world
    assert client.get("/api/wrap/not a login").status_code == 422
    from roastmygithub import optout

    monkeypatch.setattr(optout, "opted_out", lambda path=None: frozenset({"someone"}))
    refused = client.get("/api/wrap/Someone")
    assert refused.status_code == 451 and "asked not to be included" in refused.json()["error"]


def test_magic_then_video_run_on_the_visitors_key(world):
    client, _, mh_api = world
    body = {"persona": "senior", "magic_hour_key": "mh-test-key-0123456789", "heroes": 1}
    job = client.post("/api/wrap/someone/magic", json=body)
    assert job.status_code == 202
    done = wait(client, job.json())
    assert done["status"] == "done", done
    result = done["result"]
    assert len(result["art"]) == 5 and all(a.startswith("http://testserver/files/") for a in result["art"])
    assert result["clips"][0] and result["clips"][1] is None and result["audio"].endswith("/voice.wav")
    assert client.get(result["art"][0].replace("http://testserver", "")).status_code == 200
    paid = [path for path, _ in mh_api.created]
    assert paid.count("/v1/ai-image-generator") == 5 and paid.count("/v1/image-to-video") == 1 and paid.count("/v1/ai-voice-generator") == 6
    assert result["voice"] == "Elon Musk"  # the senior engineer's default

    page = client.get("/api/wrap/someone?persona=senior").json()
    assert page["magic_ready"] and page["assets"]["credits"] == result["credits"] > 0

    video = wait(client, client.post("/api/wrap/someone/video", json=body).json())
    assert video["status"] == "done" and video["result"]["video"].endswith("/wrapped_someone_senior_elon-musk.mp4")
    assert client.get(video["result"]["video"].replace("http://testserver", "")).status_code == 200
    assert len(mh_api.created) == len(paid)  # the video reused everything


def test_voices_are_listed_and_checked(world):
    client, _, _ = world
    listing = client.get("/api/voices").json()
    assert listing["popular"][0] == "Elon Musk" and listing["defaults"]["senior"] == "Elon Musk" and listing["count"] > 1000
    assert client.get("/api/wrap/someone?persona=senior&voice=narrator").json()["voice"] == "narrator"
    assert client.get("/api/wrap/someone?voice=Nobody").status_code == 422


def test_styled_voices_get_their_own_script_and_old_assets_are_not_served(world, tmp_path):
    client, _, _ = world
    elon = client.get("/api/wrap/someone?persona=senior").json()
    trump = client.get("/api/wrap/someone?persona=senior&voice=Donald Trump").json()
    narrator = client.get("/api/wrap/someone?persona=senior&voice=narrator").json()
    assert elon["script"]["voice"] == "Elon Musk" and trump["script"]["voice"] == "Donald Trump" and narrator["script"]["voice"] is None
    folder = tmp_path / "web" / "someone" / "senior"
    assert {p.name for p in folder.glob("wrap*.json")} == {"wrap.json", "wrap_elon-musk.json", "wrap_donald-trump.json"}
    # Art and voice recorded for other lines (an older script) are not offered as this script's.
    (folder / "assets_donald-trump.json").write_text(
        '{"voice": "Donald Trump", "art": [], "clips": [], "audio": "x.wav", "lines": [{"text": "an older line", "start": 0, "end": 1}], "duration": 1, "credits": 9}'
    )
    again = client.get("/api/wrap/someone?persona=senior&voice=Donald Trump").json()
    assert again["magic_ready"] is False and again["video"] is None


def test_only_media_is_served_from_the_output_folder(world, tmp_path):
    client, _, _ = world
    client.get("/api/wrap/someone?persona=senior")
    folder = tmp_path / "web" / "someone" / "senior"
    (folder / "art").mkdir(exist_ok=True)
    (folder / "art" / "beat.png").write_bytes(b"png")
    assert client.get("/files/someone/senior/art/beat.png").status_code == 200
    for private in ("someone/senior/wrap_elon-musk.json", "someone/senior/stats.json", "_jobs/x.json", "someone/senior/ledger.jsonl"):
        assert client.get(f"/files/{private}").status_code == 404, private


def test_the_rate_limit_ignores_a_forged_forwarded_for(world, monkeypatch):
    client, _, _ = world
    from api import app as app_module

    monkeypatch.setattr(app_module, "RATE_LIMIT_PER_MINUTE", 3)
    from api.app import create_app

    limited = TestClient(create_app(client.app.state.service))
    codes = [limited.get("/api/wrap/someone", headers={"x-forwarded-for": f"10.0.0.{n}"}).status_code for n in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_share_images_only_read_existing_wraps_and_nothing_can_force_a_rewrite(world):
    client, gh_api, _ = world
    assert client.get("/api/wrap/someone?persona=hype&cached=true").status_code == 404
    assert not gh_api.calls  # a preview of an unknown login never reaches GitHub or the LLM
    made = client.get("/api/wrap/someone?persona=hype").json()
    calls = len(gh_api.calls)
    assert client.get("/api/wrap/someone?persona=hype&cached=true").json()["cached_at"] == made["cached_at"]
    assert client.get("/api/wrap/someone?persona=hype&refresh=true").json()["cached_at"] == made["cached_at"]
    assert len(gh_api.calls) == calls


def test_when_the_llm_refuses_visitors_get_a_plain_message(world, monkeypatch):
    client, _, _ = world

    class Refusing:
        model = "fake"

        def json(self, **_):
            raise RuntimeError("400 credit balance too low / spend limit reached")

    monkeypatch.setattr(client.app.state.service, "make_llm", lambda: Refusing())
    response = client.get("/api/wrap/someone?persona=professor")
    assert response.status_code == 503 and response.json()["error"] == "Couldn't write a new roast right now. Try again in a little while."


def test_a_bad_key_fails_the_job_not_the_server(world):
    client, _, _ = world
    job = client.post("/api/wrap/someone/magic", json={"persona": "senior", "magic_hour_key": "wrong-key-but-long-enough"})
    done = wait(client, job.json())
    assert done["status"] == "error" and done["code"] == 500
    assert client.get("/api/health").json()["ok"] is True


@pytest.fixture
def signed_world(world, tmp_path):
    """The same fakes, but with sign-in switched on (SESSION_SECRET set)."""
    from api.app import create_app

    client, gh_api, mh_api = world
    service = client.app.state.service
    return TestClient(create_app(service, session_secret="test-secret")), gh_api, mh_api


def token(login="alice", uid=42, secret="test-secret", ttl=3600):
    import time as _time

    from roastmygithub.accounts import sign

    return {"Authorization": f"Bearer {sign({'login': login, 'id': uid, 'exp': _time.time() + ttl}, secret)}"}


def test_a_new_roast_needs_sign_in_but_an_existing_one_does_not(signed_world):
    client, _, _ = signed_world
    refused = client.get("/api/wrap/someone?persona=professor")
    assert refused.status_code == 401 and refused.json()["code"] == "sign_in_required"
    made = client.get("/api/wrap/someone?persona=professor", headers=token())
    assert made.status_code == 200 and made.json()["remaining"] == 2
    again = client.get("/api/wrap/someone?persona=professor")  # anyone, no sign-in, no quota spent
    assert again.status_code == 200 and again.json()["cached_at"] == made.json()["cached_at"]
    assert client.get("/api/wrap/someone?persona=professor", headers=token()).json()["remaining"] == 2


def test_three_new_roasts_a_day_per_account(signed_world):
    client, _, _ = signed_world
    for n, login in enumerate(["one", "two", "three"]):
        response = client.get(f"/api/wrap/{login}?persona=senior", headers=token())
        assert response.status_code == 200 and response.json()["remaining"] == 2 - n
    fourth = client.get("/api/wrap/four?persona=senior", headers=token())
    assert fourth.status_code == 429 and fourth.json()["code"] == "quota"
    assert client.get("/api/wrap/four?persona=senior", headers=token(login="bob", uid=7)).status_code == 200  # a different account


def test_forged_or_expired_tokens_count_as_signed_out(signed_world):
    client, _, _ = signed_world
    assert client.get("/api/wrap/someone", headers=token(secret="wrong")).json()["code"] == "sign_in_required"
    assert client.get("/api/wrap/someone", headers=token(ttl=-10)).json()["code"] == "sign_in_required"


def test_balance_reads_the_visitors_magic_hour_account(signed_world):
    client, _, _ = signed_world
    ok = client.post("/api/magic-hour/balance", json={"magic_hour_key": "mh-test-key-0123456789"})
    assert ok.status_code == 200 and ok.json()["credits"] == 50_000


def test_the_job_routes_need_sign_in_for_a_wrap_that_does_not_exist_yet(signed_world):
    client, gh_api, _ = signed_world
    body = {"persona": "senior", "magic_hour_key": "mh-test-key-0123456789", "heroes": 0}
    refused = wait(client, client.post("/api/wrap/newcomer/magic", json=body).json())
    assert refused["status"] == "error" and refused["code"] == 401
    refused = wait(client, client.post("/api/wrap/newcomer/video", json=body).json())
    assert refused["status"] == "error" and refused["code"] == 401
    assert not gh_api.calls  # nothing was looked up, let alone written, for an anonymous caller
    done = wait(client, client.post("/api/wrap/newcomer/magic", json=body, headers=token()).json())
    assert done["status"] == "done"
    assert client.get("/api/wrap/newcomer?persona=senior", headers=token()).json()["remaining"] == 2  # that roast was counted


def test_a_typo_or_a_failed_script_does_not_cost_a_roast(signed_world, monkeypatch):
    client, gh_api, _ = signed_world
    gh_api.user_missing = True
    missing = client.get("/api/wrap/nobody?persona=senior", headers=token())
    assert missing.status_code == 404
    gh_api.user_missing = False

    class Refusing:
        model = "fake"

        def json(self, **_):
            raise RuntimeError("spend limit reached")

    service = client.app.state.service
    working = service.make_llm
    monkeypatch.setattr(service, "make_llm", lambda: Refusing())
    assert client.get("/api/wrap/someone?persona=senior", headers=token()).status_code == 503
    assert client.get("/api/wrap/four?persona=senior", headers=token()).status_code == 503
    monkeypatch.setattr(service, "make_llm", working)
    assert client.get("/api/wrap/four?persona=senior", headers=token()).json()["remaining"] == 2  # all three were still there


def test_an_old_wrap_still_opens_for_anyone(signed_world):
    import json

    client, _, _ = signed_world
    made = client.get("/api/wrap/someone?persona=hype", headers=token()).json()
    path = client.app.state.service.wrap_path("someone", "hype", "brutal", made["voice"])
    data = json.loads(path.read_text())
    data["cached_at"] = "2026-01-01T00:00:00Z"  # months old, and no Magic Hour assets
    path.write_text(json.dumps(data))
    again = client.get("/api/wrap/someone?persona=hype")  # a shared link, no sign-in
    assert again.status_code == 200 and again.json()["cached_at"].startswith("2026-01-01")


def test_an_unknown_persona_is_a_422_not_a_crash(world):
    client, _, _ = world
    for url in ("/api/wrap/someone?persona=bogus", "/api/wrap/someone?persona=bogus&cached=true"):
        response = client.get(url)
        assert response.status_code == 422 and "unknown persona" in response.json()["error"]


def test_files_save_as_a_download_when_asked(world):
    client, _, _ = world
    client.get("/api/wrap/someone?persona=senior")
    job = wait(client, client.post("/api/wrap/someone/magic", json={"persona": "senior", "magic_hour_key": "mh-test-key-0123456789", "heroes": 0}).json())
    audio = job["result"]["audio"].split("/files/", 1)[1]
    assert "content-disposition" not in client.get(f"/files/{audio}").headers
    saved = client.get(f"/files/{audio}?download=1")
    assert saved.status_code == 200 and saved.headers["content-disposition"] == 'attachment; filename="voice.wav"'
