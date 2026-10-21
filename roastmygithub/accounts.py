"""Who is asking, and how many new roasts they have left today.

Sign-in happens on the website (Sign in with GitHub). The site then hands the browser a short-lived
token signed with SESSION_SECRET, a secret the site and the engine share; the engine checks the
signature and trusts the GitHub login and id inside. Nothing here talks to GitHub.

Token format: "v1.<base64url(json)>.<base64url(hmac-sha256)>", json = {"login", "id", "exp"}.
The website's web/lib/session.ts makes the same tokens.

Quotas are counted per GitHub account id per UTC day, in one small JSON file per day on the data
volume, under a file lock so both server processes share the same count.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class AuthError(RuntimeError):
    pass


class QuotaExceeded(RuntimeError):
    def __init__(self, message: str, *, scope: str):
        super().__init__(message)
        self.scope = scope  # "user" or "global"


@dataclass(frozen=True)
class Visitor:
    login: str
    id: int


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, secret: str) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = _b64(hmac.new(secret.encode(), f"v1.{body}".encode(), hashlib.sha256).digest())
    return f"v1.{body}.{mac}"


def verify(token: str, secret: str, *, now: float | None = None) -> Visitor:
    try:
        version, body, mac = token.split(".")
    except ValueError as exc:
        raise AuthError("malformed token") from exc
    if version != "v1":
        raise AuthError("unknown token version")
    expected = _b64(hmac.new(secret.encode(), f"v1.{body}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, mac):
        raise AuthError("bad signature")
    try:
        payload = json.loads(_unb64(body))
    except ValueError as exc:
        raise AuthError("unreadable token") from exc
    if float(payload.get("exp", 0)) < (now or time.time()):
        raise AuthError("expired token")
    login, uid = payload.get("login"), payload.get("id")
    if not isinstance(login, str) or not isinstance(uid, int):
        raise AuthError("token has no account")
    return Visitor(login=login, id=uid)


class Quota:
    """New roasts per account per day, and an overall daily ceiling on what the site pays for."""

    def __init__(self, root: Path, *, per_user: int, global_cap: int):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.per_user = per_user
        self.global_cap = global_cap

    def _file(self, now: datetime | None = None) -> Path:
        day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        return self.root / f"{day}.json"

    def take(self, visitor: Visitor, *, now: datetime | None = None) -> int:
        """Spend one new roast for `visitor`; returns how many they have left today."""
        path = self._file(now)
        with open(path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            raw = fh.read()
            counts: dict[str, int] = json.loads(raw) if raw.strip() else {}
            total = sum(counts.values())
            mine = counts.get(str(visitor.id), 0)
            if total >= self.global_cap:
                raise QuotaExceeded("The site has made as many new roasts as it can today. Wraps already made still open.", scope="global")
            if mine >= self.per_user:
                raise QuotaExceeded(f"You've made your {self.per_user} new roasts for today. Wraps already made still open, and you get {self.per_user} more tomorrow.", scope="user")
            counts[str(visitor.id)] = mine + 1
            fh.seek(0)
            fh.truncate()
            json.dump(counts, fh)
            return self.per_user - mine - 1

    def remaining(self, visitor: Visitor, *, now: datetime | None = None) -> int:
        path = self._file(now)
        try:
            counts = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            counts = {}
        return max(0, self.per_user - counts.get(str(visitor.id), 0))
