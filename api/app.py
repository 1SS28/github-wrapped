"""HTTP front for the engine (FastAPI), deployed on Fly.io behind the Vercel site.

  GET  /api/wrap/{login}?persona=senior        the free part: stats, highlights, script (written once, then kept)
  POST /api/wrap/{login}/magic                 {persona, magic_hour_key} -> job: Magic Hour art + voice on that key
  POST /api/wrap/{login}/video                 {persona, magic_hour_key} -> job: the mp4
  GET  /api/jobs/{id}                          job status; `result` carries file URLs when done
  GET  /files/...                              generated images, clips, audio and videos
  GET  /api/health

Magic Hour keys travel in request bodies over HTTPS, are used for that job's calls, and are
never stored or logged (logs carry an 8-character fingerprint). Jobs are tracked as JSON files
under the output directory so several workers see the same state.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from roastmygithub import voices
from roastmygithub.accounts import AuthError, Quota, QuotaExceeded, Visitor, verify
from roastmygithub.personas import PERSONAS
from roastmygithub.service import Gate, Service, ServiceError, key_fingerprint

log = logging.getLogger("roastmygithub.api")
JOB_WORKERS = int(os.environ.get("ROAST_JOB_WORKERS", "4"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("ROAST_RATE_LIMIT", "20"))
ROASTS_PER_DAY = int(os.environ.get("ROAST_ROASTS_PER_DAY", "3"))  # new roasts per signed-in account per UTC day
DAILY_ROAST_CAP = int(os.environ.get("ROAST_DAILY_CAP", "300"))  # new roasts per day for the whole site (~$12 of LLM)


class BalanceRequest(BaseModel):
    magic_hour_key: str = Field(min_length=1, max_length=400)


class MagicRequest(BaseModel):
    persona: str = "senior"
    voice: str | None = None  # a Magic Hour voice name, "narrator", or the persona's default
    heat: str = "brutal"  # or "gentle"
    magic_hour_key: str = Field(min_length=1, max_length=400)
    heroes: int = Field(default=2, ge=0, le=6)


class Jobs:
    """A tiny job queue: state on disk, work on a thread pool."""

    def __init__(self, root: Path, workers: int = JOB_WORKERS):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=workers)

    def path(self, job_id: str) -> Path:
        if not all(c in "0123456789abcdef" for c in job_id) or len(job_id) != 32:
            raise HTTPException(404, "no such job")
        return self.root / f"{job_id}.json"

    def _write(self, job_id: str, **fields: Any) -> dict[str, Any]:
        state = {"id": job_id, **fields, "updated_at": time.time()}
        tmp = self.path(job_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(self.path(job_id))
        return state

    def submit(self, kind: str, work: Callable[[], Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        state = self._write(job_id, kind=kind, status="queued")

        def run() -> None:
            self._write(job_id, kind=kind, status="running")
            try:
                result = work()
                self._write(job_id, kind=kind, status="done", result=result)
            except ServiceError as exc:
                self._write(job_id, kind=kind, status="error", error=str(exc), code=exc.status)
            except Exception as exc:  # noqa: BLE001
                log.exception("job %s failed", job_id)
                self._write(job_id, kind=kind, status="error", error=f"{type(exc).__name__}: {exc}", code=500)

        self.pool.submit(run)
        return state

    def get(self, job_id: str) -> dict[str, Any]:
        path = self.path(job_id)
        if not path.exists():
            raise HTTPException(404, "no such job")
        return json.loads(path.read_text(encoding="utf-8"))


class MediaFiles(StaticFiles):
    """The generated pictures, clips, audio and videos, and nothing else from the output directory:
    job files, cost ledgers, cached GitHub activity and scripts sit beside them and stay private."""

    MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".wav", ".mp3"}

    async def get_response(self, path: str, scope: Any) -> Any:
        if Path(path).suffix.lower() not in self.MEDIA or path.replace("\\", "/").startswith("_jobs"):
            raise HTTPException(404, "not found")
        response = await super().get_response(path, scope)
        # The site is on another origin, so a plain <a download> would only open the file; ?download=1 saves it.
        if b"download=1" in scope.get("query_string", b"") and response.status_code == 200:
            response.headers["content-disposition"] = f'attachment; filename="{Path(path).name}"'
        return response


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.time()
        with self.lock:
            recent = [t for t in self.hits.get(key, []) if now - t < 60]
            if len(recent) >= self.per_minute:
                raise HTTPException(429, "slow down a little")
            recent.append(now)
            self.hits[key] = recent


def create_app(service: Service | None = None, *, session_secret: str | None = None) -> FastAPI:
    service = service or Service()
    jobs = Jobs(service.out_dir / "_jobs")
    limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)
    quota = Quota(service.out_dir / "_quota", per_user=ROASTS_PER_DAY, global_cap=DAILY_ROAST_CAP)
    secret = session_secret if session_secret is not None else os.environ.get("SESSION_SECRET", "")
    if not secret:
        log.warning("SESSION_SECRET is not set: new roasts do not need sign-in (local development only)")
    app = FastAPI(title="GitHub Wrapped", docs_url=None, redoc_url=None)
    app.state.service = service
    origins = [o for o in os.environ.get("ROAST_WEB_ORIGIN", "http://localhost:3000").split(",") if o]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])
    app.mount("/files", MediaFiles(directory=str(service.out_dir)), name="files")

    def client_key(request: Request) -> str:
        # Fly's proxy puts the caller's real address in Fly-Client-IP. X-Forwarded-For is not used: its first
        # entry is whatever the caller sent, so a script could rotate it to dodge the rate limit.
        return request.headers.get("fly-client-ip") or (request.client.host if request.client else "?")

    def file_url(request: Request, rel: str | None) -> str | None:
        return str(request.base_url).rstrip("/") + f"/files/{rel}" if rel else None

    @app.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse({"error": str(exc), **({"code": exc.code} if exc.code else {})}, status_code=exc.status)

    def visitor_of(request: Request) -> Visitor | None:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer ") or not secret:
            return None
        try:
            return verify(header[7:].strip(), secret)
        except AuthError:
            return None

    def gate(visitor: Visitor | None) -> Gate:
        """Runs only when a wrap has to be written from scratch: that is the step the site pays for.
        The same gate guards the job routes, which write the wrap too when it does not exist yet."""
        if not secret:
            return Gate()

        def check() -> None:
            if visitor is None:
                raise ServiceError("Sign in with GitHub to make a new roast. Wraps someone already made open without signing in.", 401, "sign_in_required")

        def spend() -> None:
            try:
                quota.take(visitor)  # type: ignore[arg-type]  # check() ran first
            except QuotaExceeded as exc:
                raise ServiceError(str(exc), 429, "quota" if exc.scope == "user" else "site_quota") from exc

        return Gate(check, spend, lambda: quota.give_back(visitor))  # type: ignore[arg-type]

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "personas": list(PERSONAS)}

    @app.get("/api/voices")
    def voice_list() -> dict[str, Any]:
        return {
            "original": voices.ORIGINAL,
            "popular": list(voices.POPULAR),
            "defaults": {p.key: p.default_voice for p in PERSONAS.values()},
            "count": len(voices.ALL),
        }

    @app.get("/api/personas")
    def personas() -> list[dict[str, str]]:
        return [{"key": p.key, "title": p.title, "style": p.style.split(": ", 1)[1].split(".")[0]} for p in PERSONAS.values()]

    @app.get("/api/wrap/{login}")
    def wrap(login: str, request: Request, persona: str = "senior", voice: str | None = None, heat: str = "brutal", cached: bool = False) -> dict[str, Any]:
        """The wrap, made on first request. With cached=true (share images, link previews) only an existing one
        is returned: that costs nothing, so it is not rate limited. There is no public way to force a rewrite."""
        chosen = service.resolve_voice(persona, voice)
        if cached:
            result = service.cached_wrap(login, persona, heat=heat, voice=chosen)
            if result is None:
                raise HTTPException(404, "no wrap for that login yet")
        else:
            limiter.check(client_key(request))
            visitor = visitor_of(request)
            result = service.wrap(login, persona, heat=heat, voice=chosen, gate=gate(visitor))
        clean = login.strip().lstrip("@")  # folders are keyed by the requested login
        assets = service.assets_for(clean, persona, chosen, heat, result.script)  # only art and voice made for these lines
        data = result.model_dump(mode="json")
        data["voice"] = chosen
        if not cached:
            viewer = visitor_of(request)
            data["remaining"] = quota.remaining(viewer) if viewer else None
        data["magic_ready"] = assets is not None
        if assets:
            data["assets"] = _asset_urls(request, assets)
        video = service.video_path(clean, persona, chosen, heat)
        data["video"] = file_url(request, str(video.relative_to(service.out_dir))) if assets and service.video_ready(clean, persona, chosen, heat) else None
        return data

    def _asset_urls(request: Request, assets: dict[str, Any]) -> dict[str, Any]:
        return {
            **assets,
            "art": [file_url(request, a) for a in assets["art"]],
            "clips": [file_url(request, c) for c in assets["clips"]],
            "audio": file_url(request, assets["audio"]),
        }

    @app.post("/api/wrap/{login}/magic", status_code=202)
    def magic(login: str, body: MagicRequest, request: Request) -> dict[str, Any]:
        limiter.check(client_key(request))
        log.info("magic for %s by key %s", login, key_fingerprint(body.magic_hour_key))
        key, who = body.magic_hour_key, gate(visitor_of(request))

        def work() -> dict[str, Any]:
            assets = service.magic(login, body.persona, key, heroes=body.heroes, voice=body.voice, heat=body.heat, gate=who)
            return _asset_urls(request, assets.model_dump())

        return jobs.submit("magic", work)

    @app.post("/api/wrap/{login}/video", status_code=202)
    def video(login: str, body: MagicRequest, request: Request) -> dict[str, Any]:
        limiter.check(client_key(request))
        key, who = body.magic_hour_key, gate(visitor_of(request))

        def work() -> dict[str, Any]:
            return {"video": file_url(request, service.video(login, body.persona, key, voice=body.voice, heat=body.heat, gate=who))}

        return jobs.submit("video", work)

    @app.post("/api/magic-hour/balance")
    def balance(body: BalanceRequest, request: Request) -> dict[str, Any]:
        """The visitor's Magic Hour credit balance, so the site can offer what their account can pay for."""
        limiter.check(client_key(request))
        from core.costs import CostLedger
        from core.magichour import MagicHourError

        try:
            with service.make_magichour(body.magic_hour_key, CostLedger()) as mh:
                account = mh.account()
        except MagicHourError as exc:
            raise ServiceError("Magic Hour didn't accept that key.", 401, "bad_key") from exc
        return {"credits": account.get("credits"), "tier": account.get("tier")}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        return jobs.get(job_id)

    return app


app = create_app() if os.environ.get("ROAST_APP_EAGER", "1") == "1" and __name__ != "__main__" else None  # type: ignore[assignment]
