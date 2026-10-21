"""Script -> speech with Magic Hour: the AI Voice Generator (a named voice such as "Elon Musk")
or the AI Voice Cloner (the persona's own bundled sample).

One request per line (each beat, then the sign-off), not one for the whole script. It costs the
same (0.1 credit per character) and gives exact timings for free: each line's audio has a known
length, so the stat cards and captions can switch on the beat without a transcription pass.
Lines are cached by text and voice sample, so changing one beat only pays for that beat.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

from core import compose
from core.costs import LedgerEntry
from core.magichour import MagicHour
from roastmygithub.voices import ORIGINAL, slug

GAP = 0.35  # seconds of silence between lines
TAIL = 0.6  # after the sign-off
SAMPLE_RATE = 48000


class TimedLine(BaseModel):
    text: str
    start: float
    end: float


class VoiceTrack(BaseModel):
    audio: Path
    duration: float
    lines: list[TimedLine]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def line_path(workdir: Path, index: int, text: str, voice_key: str) -> Path:
    key = hashlib.sha256(f"{voice_key}\n{text}".encode()).hexdigest()[:12]
    return workdir / f"line_{index:02d}_{key}.wav"


def _voice_key(sample: Path, voice_name: str | None) -> tuple[str, str]:
    """(cache key, sub-folder) for a voice: the generator voice's name, or the sample's hash."""
    if voice_name and voice_name != ORIGINAL:
        return f"generator:{voice_name}", slug(voice_name)
    return _sha(sample), ORIGINAL


def pending(lines: list[str], sample: Path, workdir: Path, *, voice_name: str | None = None) -> list[str]:
    """The lines that would be paid for (not yet in the cache)."""
    key, folder = _voice_key(sample, voice_name)
    return [text for i, text in enumerate(lines) if not line_path(workdir / folder, i, text, key).exists()]


def synthesize(mh: MagicHour | None, lines: list[str], sample: Path, workdir: Path, *, voice_name: str | None = None, concurrency: int = 3) -> VoiceTrack:
    """Speak every line (in the named voice, or the sample's) and join them into one track with known timings."""
    key, folder = _voice_key(sample, voice_name)
    workdir = workdir / folder
    workdir.mkdir(parents=True, exist_ok=True)
    named = voice_name if voice_name and voice_name != ORIGINAL else None
    paths = [line_path(workdir, i, text, key) for i, text in enumerate(lines)]

    def speak(job: tuple[int, str, Path]) -> None:
        index, text, path = job
        if path.exists():
            if mh:
                mh.ledger.add(LedgerEntry(provider="magichour", kind="voice_generate" if named else "voice_clone", label=f"voice line {index + 1}", status="cached", credits=0))
            return
        if mh is None:
            raise RuntimeError("MAGIC_HOUR_API_KEY is needed to generate the voice")
        if named:
            job_id = mh.voice_generate(text=text, voice_name=named, label=f"voice line {index + 1}")
        else:
            job_id = mh.voice_clone(text=text, sample=sample, label=f"voice line {index + 1}")
        mh.download_result(job_id, "audio", path)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(speak, zip(range(len(lines)), lines, paths)))

    timed: list[TimedLine] = []
    cursor = 0.0
    filters = []
    for i, (text, path) in enumerate(zip(lines, paths)):
        length = compose.probe_duration(path)
        pad = TAIL if i == len(lines) - 1 else GAP
        timed.append(TimedLine(text=text, start=round(cursor, 3), end=round(cursor + length, 3)))
        cursor += length + pad
        filters.append(f"[{i}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=mono,apad=pad_dur={pad}[a{i}]")
    joined = "".join(f"[a{i}]" for i in range(len(paths)))
    audio = workdir / "voice.wav"
    compose.run_ffmpeg(
        [
            *[arg for path in paths for arg in ("-i", path.resolve())],
            "-filter_complex", ";".join(filters) + f";{joined}concat=n={len(paths)}:v=0:a=1[out]",
            "-map", "[out]", "-ar", SAMPLE_RATE, "-c:a", "pcm_s16le", audio.resolve(),
        ]
    )
    return VoiceTrack(audio=audio, duration=round(compose.probe_duration(audio), 3), lines=timed)
