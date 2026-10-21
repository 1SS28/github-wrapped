"""Snapshot the AI Voice Generator voice list from the Magic Hour OpenAPI spec into roastmygithub/voices.py."""
import json
import sys
import urllib.request

spec = json.load(urllib.request.urlopen("https://docs.magichour.ai/api-reference/openapi.json", timeout=60))


def deref(o):
    if isinstance(o, dict):
        if "$ref" in o:
            return deref(spec["components"]["schemas"][o["$ref"].split("/")[-1]])
        return {k: deref(v) for k, v in o.items()}
    if isinstance(o, list):
        return [deref(x) for x in o]
    return o


schema = deref(spec["paths"]["/v1/ai-voice-generator"]["post"]["requestBody"]["content"]["application/json"]["schema"])
names = schema["properties"]["style"]["properties"]["voice_name"]["enum"]
popular = [
    "Elon Musk", "Morgan Freeman", "David Attenborough", "Gordon Ramsay", "Snoop Dogg", "Samuel L. Jackson",
    "Barack Obama", "Donald Trump", "Kim Kardashian", "MrBeast", "Joe Rogan", "Dwayne 'The Rock' Johnson",
    "Arnold Schwarzenegger", "Keanu Reeves", "Scarlett Johansson", "Taylor Swift", "Kevin Hart", "Jeff Goldblum",
    "SpongeBob SquarePants", "GLaDOS", "Darth Vader", "Yoda", "Shrek", "Kermit the Frog", "Homer Simpson",
    "Rick Sanchez", "Bender (Futurama)", "Gollum Smeagol", "Mark Zuckerberg", "Linus (LTT)",
]
missing = [p for p in popular if p not in names]
assert not missing, missing

out = f'''"""Voices the Magic Hour AI Voice Generator offers (`voice_name`), snapshotted from the OpenAPI spec
on 2026-10-17 by tools/make_voices.py.

Every one is an impression of a real person or a well-known character. The script never names the
person whose voice is used and never puts their opinions in their mouth: it is a narrator's voice,
nothing more. POPULAR is the shortlist shown first; ALL is the full list the API accepts.
"""

from __future__ import annotations

ORIGINAL = "narrator"  # the persona's own cloned Kokoro voice

POPULAR: tuple[str, ...] = (
{chr(10).join(f"    {json.dumps(p)}," for p in popular)}
)

ALL: frozenset[str] = frozenset(
    [
{chr(10).join(f"        {json.dumps(n)}," for n in names)}
    ]
)


def slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "voice"


def check(name: str | None) -> str:
    """`narrator`, or a voice the API accepts (case-insensitive); anything else is an error."""
    if not name or name == ORIGINAL:
        return ORIGINAL
    lookup = {{n.lower(): n for n in ALL}}
    if name.lower() in lookup:
        return lookup[name.lower()]
    raise ValueError(f"unknown voice {{name!r}}; see `roastmygithub voices`")
'''
target = sys.argv[1]
open(target, "w").write(out)
print(len(names), "voices,", len(popular), "popular ->", target)
