"""The opt-out list: logins that are never looked up, however they are asked for."""

from __future__ import annotations

import functools
import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "OPTOUT.md"


def parse(text: str) -> frozenset[str]:
    logins = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and " " not in line:
            logins.add(line.lstrip("@").lower())
    return frozenset(logins)


@functools.lru_cache(maxsize=1)
def opted_out(path: Path | None = None) -> frozenset[str]:
    path = path or Path(os.environ.get("ROAST_OPTOUT_FILE", DEFAULT_PATH))
    try:
        return parse(path.read_text(encoding="utf-8"))
    except OSError:
        return frozenset()


def is_opted_out(login: str) -> bool:
    return login.lower() in opted_out()
