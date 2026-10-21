"""The engine as three calls, for the web app.

  wrap(login)            public GitHub data -> stats, highlights, script. Runs on the site owner's
                         GitHub token and LLM key; cached per login, persona and day.
  magic(login, key)      Magic Hour art and voice for that wrap, on the VISITOR's own key. The key
                         is used for the calls and never written anywhere.
  video(login, key)      the mp4, from the cached art and voice (drawn locally).

Everything lands under `out_dir/<login>/<persona>/`, which the API serves as static files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from core import compose
from core.costs import CostLedger
from core.llm import LLM
from core.magichour import MagicHour
from roastmygithub import art as art_ops
from roastmygithub import cards as card_ops
from roastmygithub import github as github_ops
from roastmygithub import render as render_ops
from roastmygithub import voice as voice_ops
from roastmygithub import voice_styles, voices
from roastmygithub.config import Settings
from roastmygithub.highlights import Highlight, pick
from roastmygithub.optout import is_opted_out
from roastmygithub.personas import PERSONAS, Persona
from roastmygithub.rank import Rank, compute_rank
from roastmygithub.script import HEATS, MIN_HIGHLIGHTS, Script, write_script
from roastmygithub.stats import Stats, compute_stats, local_timezone

WINDOW_DAYS = 365
LOGIN_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")


log = logging.getLogger("roastmygithub.service")


class ServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 400, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code  # machine-readable reason for the site, e.g. "sign_in_required" or "quota"


class Wrap(BaseModel):
    login: str
    name: str | None
    persona: str
    since: datetime
    until: datetime
    scope: str
    highlights: list[Highlight]
    script: Script
    rank: Rank
    stats: dict[str, Any]  # the subset the page draws
    cached_at: datetime


class Assets(BaseModel):
    """Paths relative to the service's file root; the API turns them into URLs."""

    voice: str = voices.ORIGINAL
    art: list[str | None]
    clips: list[str | None]
    audio: str
    lines: list[dict[str, Any]]
    duration: float
    credits: int


def check_login(login: str) -> str:
    login = login.strip().lstrip("@")
    if not login or len(login) > 39 or set(login) - LOGIN_OK or login.startswith("-") or login.endswith("-"):
        raise ServiceError("that is not a GitHub login", 422)
    if is_opted_out(login):
        raise ServiceError(f"@{login} has asked not to be included", 451)
    return login


def _stats_for_page(stats: Stats) -> dict[str, Any]:
    keep = (
        "commits", "total_contributions", "active_days", "days_in_window", "longest_streak", "longest_gap",
        "busiest_day", "busiest_weekday", "weekend_share", "calendar", "hour_commits", "busiest_hour",
        "after_midnight_share", "languages", "top_repos", "lines_added", "lines_deleted", "top_words",
        "roast_words", "shortest_message", "most_repeated_message", "commit_log", "prs_opened", "prs_merged",
        "stars_received", "repos_created", "repos_abandoned", "new_repos", "clock", "text_scope",
    )
    data = stats.model_dump(mode="json", include=set(keep))
    data["commit_log"] = data.get("commit_log", [])[:40]
    return data


class Service:
    def __init__(self, settings: Settings | None = None, *, out_dir: Path | None = None):
        self.settings = settings or Settings()
        self.out_dir = Path(out_dir or os.environ.get("ROAST_OUT_DIR", "out/web"))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # Factories, so tests can point the service at fakes.
    def make_github(self) -> github_ops.GitHub:
        return github_ops.GitHub(github_ops.resolve_token(self.settings.github_token))

    def make_llm(self) -> LLM:
        s = self.settings
        if not (s.llm_api_key and s.llm_model):
            raise ServiceError("the service has no LLM configured", 503)
        return LLM(s.llm_model, s.llm_api_key, provider=s.llm_provider, effort=s.llm_effort, base_url=s.llm_base_url,
                   usd_per_mtok_in=s.llm_usd_per_mtok_in, usd_per_mtok_out=s.llm_usd_per_mtok_out)

    def make_magichour(self, key: str, ledger: CostLedger) -> MagicHour:
        return MagicHour(key, ledger=ledger)

    def _lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def folder(self, login: str, persona: str) -> Path:
        path = self.out_dir / login.lower() / persona
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- 1. The free part -----------------------------------------------------------

    def wrap(
        self,
        login: str,
        persona: str = "senior",
        *,
        refresh: bool = False,
        heat: str = "brutal",
        voice: str | None = None,
        before_generate: Callable[[], None] | None = None,
    ) -> Wrap:
        """Stats and script for one login, persona and heat, cached for a day.

        Voices with a known way of talking (voice_styles) get a script of their own; every other voice
        shares the persona's. A wrap that already has paid art and voice is kept past the day, so the
        visitor's credits are never thrown away by a rewrite.
        """
        login = check_login(login)
        if persona not in PERSONAS:
            raise ServiceError(f"unknown persona '{persona}'", 422)
        if heat not in HEATS:
            raise ServiceError(f"unknown heat '{heat}'", 422)
        voice = self.resolve_voice(persona, voice)
        styled = voice if voice_styles.style_for(voice) else None
        folder = self.folder(login, persona)
        cache = self.wrap_path(login, persona, heat, voice)
        with self._lock(f"{login}/{persona}/{heat}/{styled}"):
            if cache.exists() and not refresh:
                try:
                    wrap = Wrap.model_validate_json(cache.read_text(encoding="utf-8"))
                except ValueError:
                    wrap = None  # written by an older version: rebuild it
                fresh = wrap and datetime.now(timezone.utc) - wrap.cached_at < timedelta(hours=24)
                if wrap and (fresh or self.assets_for(login, persona, voice, heat, wrap.script)):
                    return wrap
            if before_generate:
                before_generate()  # a new roast is about to be paid for: sign-in and quota checks go here
            activity = self._activity(login, refresh=refresh)
            stats = compute_stats(activity, include_private=False, tz=local_timezone(self.settings.roast_timezone))
            highlights = pick(stats)
            if len(highlights) < MIN_HIGHLIGHTS:
                raise ServiceError(f"@{login} has too little public activity in the last 12 months to wrap", 404)
            ledger = CostLedger(folder / "ledger.jsonl")
            llm = self.make_llm()
            try:
                script = write_script(stats, highlights, PERSONAS[persona], llm, seconds=60, heat=heat, voice=styled, ledger=ledger)
            except Exception as exc:  # the monthly spend limit, an outage, or a script with nothing usable in it
                log.warning("script for %s/%s failed: %s", login, persona, exc)
                raise ServiceError("Couldn't write a new roast right now. Try again in a little while.", 503) from exc
            wrap = Wrap(
                login=stats.login, name=stats.name, persona=persona, since=stats.since, until=stats.until,
                scope=activity.get("scope", "public"), highlights=highlights, script=script, rank=compute_rank(stats),
                stats=_stats_for_page(stats), cached_at=datetime.now(timezone.utc),
            )
            (folder / "stats.json").write_text(stats.model_dump_json(indent=2), encoding="utf-8")
            cache.write_text(wrap.model_dump_json(), encoding="utf-8")
            return wrap

    def wrap_path(self, login: str, persona: str, heat: str, voice: str) -> Path:
        styled = voice if voice_styles.style_for(voice) else None
        name = "wrap" + (f"_{voices.slug(styled)}" if styled else "") + ("" if heat == "brutal" else f"_{heat}") + ".json"
        return self.out_dir / login.lower() / persona / name

    def cached_wrap(self, login: str, persona: str = "senior", *, heat: str = "brutal", voice: str | None = None) -> Wrap | None:
        """A wrap someone already made, whatever its age, or None. Never calls GitHub or the LLM, so it is
        safe for link previews and share images, which crawlers fetch for any URL they see."""
        login = check_login(login)
        if persona not in PERSONAS or heat not in HEATS:
            raise ServiceError("unknown persona or heat", 422)
        path = self.wrap_path(login, persona, heat, self.resolve_voice(persona, voice))
        try:
            return Wrap.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None
        except ValueError:
            return None

    def _activity(self, login: str, *, refresh: bool) -> dict[str, Any]:
        """Public GitHub activity for `login`, cached per day (shared across personas)."""
        until = datetime.now(timezone.utc)
        cache = self.out_dir / login.lower() / f"activity-{until:%Y-%m-%d}.json"
        if cache.exists() and not refresh:
            return json.loads(cache.read_text(encoding="utf-8"))
        with self.make_github() as gh:
            try:
                activity = github_ops.collect(gh, since=until - timedelta(days=WINDOW_DAYS), until=until, login=login, max_commits=1500)
            except github_ops.GitHubError as exc:
                raise ServiceError(str(exc), 404 if "no GitHub user" in str(exc) else 502) from exc
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(activity), encoding="utf-8")
        return activity

    # -- 2. Magic Hour, on the visitor's key --------------------------------------------

    def resolve_voice(self, persona: str, voice: str | None) -> str:
        try:
            return voices.check(voice) if voice else voices.check(PERSONAS[persona].default_voice)
        except ValueError as exc:
            raise ServiceError(str(exc), 422) from exc

    def assets_path(self, login: str, persona: str, voice: str, heat: str = "brutal") -> Path:
        suffix = "" if heat == "brutal" else f"_{heat}"
        return self.folder(login, persona) / f"assets_{voices.slug(voice)}{suffix}.json"

    def assets_for(self, login: str, persona: str, voice: str, heat: str, script: Script) -> dict[str, Any] | None:
        """The paid art and voice for this script, or None when there are none or they were made for older lines."""
        path = self.assets_path(login.strip().lstrip("@"), persona, voice, heat)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if [line.get("text") for line in data.get("lines", [])] == script.lines else None

    def magic(self, login: str, persona: str, magic_hour_key: str, *, heroes: int = 2, voice: str | None = None, heat: str = "brutal") -> Assets:
        if not magic_hour_key or len(magic_hour_key) < 20:
            raise ServiceError("a Magic Hour API key is needed for the art and the voice", 401)
        voice = self.resolve_voice(persona, voice)
        wrap = self.wrap(login, persona, heat=heat, voice=voice)
        folder = self.folder(login, persona)
        p: Persona = PERSONAS[persona]
        script = wrap.script
        order = [0, len(script.beats) - 1] + list(range(1, len(script.beats) - 1))
        hero_set = set(dict.fromkeys(order[: max(0, heroes)]))
        ledger = CostLedger(folder / "ledger.jsonl")
        with self._lock(f"{login}/{persona}/magic"), self.make_magichour(magic_hour_key, ledger) as mh:
            try:
                works = art_ops.generate(mh, [b.visual for b in script.beats], art_direction=p.art, workdir=folder / "art", heroes=hero_set)
                track = voice_ops.synthesize(mh, script.lines, p.voice_sample, folder / "voice", voice_name=voice)
            except Exception as exc:  # the key may be wrong, out of credits, or Magic Hour may be down
                raise ServiceError(f"Magic Hour: {exc}", 502) from exc
        rel = lambda path: str(path.relative_to(self.out_dir)) if path else None  # noqa: E731
        assets = Assets(
            voice=voice,
            art=[rel(w.image) if not w.fallback else None for w in works],
            clips=[rel(w.video) for w in works],
            audio=rel(track.audio),
            lines=[line.model_dump() for line in track.lines],
            duration=track.duration,
            credits=ledger.magichour_credits(),
        )
        self.assets_path(login, persona, voice, heat).write_text(assets.model_dump_json(), encoding="utf-8")
        return assets

    # -- 3. The video -----------------------------------------------------------------

    def video_path(self, login: str, persona: str, voice: str, heat: str = "brutal") -> Path:
        suffix = "" if heat == "brutal" else f"_{heat}"
        return self.folder(login, persona) / f"wrapped_{login.strip().lstrip('@')}_{persona}_{voices.slug(voice)}{suffix}.mp4"

    def video_ready(self, login: str, persona: str, voice: str, heat: str = "brutal") -> bool:
        """The mp4 exists and was rendered from the current art and voice, not an older script's."""
        login = login.strip().lstrip("@")
        dest, assets = self.video_path(login, persona, voice, heat), self.assets_path(login, persona, voice, heat)
        return dest.exists() and assets.exists() and dest.stat().st_mtime >= assets.stat().st_mtime

    def video(self, login: str, persona: str, magic_hour_key: str, *, voice: str | None = None, heat: str = "brutal") -> str:
        """The mp4, as a path relative to the file root. Needs the art and voice (made here if missing)."""
        voice = self.resolve_voice(persona, voice)
        wrap = self.wrap(login, persona, heat=heat, voice=voice)
        folder = self.folder(login, persona)
        current = self.assets_for(login, persona, voice, heat, wrap.script)
        assets = Assets.model_validate(current) if current else self.magic(login, persona, magic_hour_key, voice=voice, heat=heat)
        dest = self.video_path(login, persona, voice, heat)
        with self._lock(f"{login}/{persona}/{voice}/video"):
            if self.video_ready(login, persona, voice, heat):
                return str(dest.relative_to(self.out_dir))
            stats = Stats.model_validate_json((folder / "stats.json").read_text(encoding="utf-8"))
            track = voice_ops.VoiceTrack(audio=self.out_dir / assets.audio, duration=assets.duration, lines=[voice_ops.TimedLine(**line) for line in assets.lines])
            by_id = {h.id: h for h in wrap.highlights}
            beats = [
                render_ops.Beat(
                    highlight=by_id[beat.stat_id], tone=beat.tone,
                    art=self.out_dir / assets.art[n] if assets.art[n] else None,
                    clip=self.out_dir / assets.clips[n] if assets.clips[n] else None,
                )
                for n, beat in enumerate(wrap.script.beats)
            ]
            theme = card_ops.THEMES[persona]
            end_card = card_ops.render_end_card(stats, wrap.script, sorted((b.highlight for b in beats), key=lambda h: -h.score), folder / "end.png",
                                                theme=theme, persona_title=PERSONAS[persona].title, repo_url=self.settings.roast_repo_url)
            narrator = PERSONAS[persona].title if voice == voices.ORIGINAL else f"{PERSONAS[persona].title} · voice of {voice}"
            render_ops.render_video(stats=stats, beats=beats, track=track, end_card=end_card, dest=dest, theme=theme,
                                    narrator=narrator, title=os.environ.get("ROAST_TITLE", "GitHub Wrapped"),
                                    captions=compose.supports_captions())
        return str(dest.relative_to(self.out_dir))


def key_fingerprint(key: str) -> str:
    """For logs: enough to tell two keys apart, never the key."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]
