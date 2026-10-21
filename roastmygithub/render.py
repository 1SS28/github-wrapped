"""Final video: animated scenes, the narrator's lines and the end card, 1080x1920 at 30 fps.

Frames are drawn in Python (Pillow) and piped straight into ffmpeg, which adds the voice. Each
beat's scene starts when its line starts (the timings come from the voice lines), slides in over
the previous one, and the end card fades in once the sign-off is done. No credits are spent here.

The layout is the website's player: story-style progress segments and a mono "login / dates"
line at the top; the scene under them (full-bleed art in the wrapped style); at the bottom, who
is talking, with a small live waveform, and the line itself in a serif, each word lighting up
as it is spoken.
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from typing import Any
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from core import compose
from roastmygithub.cards import FRAME_HEIGHT, PAD, TEXT, WIDTH, Theme, mono, serif, wrap_text
from roastmygithub.highlights import Highlight
from roastmygithub.scenes import AREA_HEIGHT, Draw, ease_in_out, ease_out, make_scene, mix, phase
from roastmygithub.stats import Stats
from roastmygithub.voice import TimedLine, VoiceTrack

FPS = 30
END_CARD_SECONDS = 3.5
FADE_TO_END = 0.45
SLIDE_SECONDS = 0.45
AREA_Y = 190  # where a data scene sits; art scenes fill the whole frame
LINE_BOTTOM = FRAME_HEIGHT - 96  # the narrator's line is set upwards from here
LINE_SIZES = (50, 44, 38)  # serif sizes, largest first, until the line fits in LINE_ROWS
LINE_ROWS = 4
WAVE_BARS = 12


@dataclass
class Word:
    text: str
    start: float
    end: float
    speaker: str | None = None


@dataclass
class Beat:
    highlight: Highlight
    tone: str
    art: Path | None = None  # a Magic Hour illustration for the "wrapped" style
    clip: Path | None = None  # its animated version, for hero beats


def clip_frames(path: Path, *, width: int, height: int, limit: int = 150) -> list[Image.Image]:
    """The first `limit` frames of a clip at FPS, scaled to cover width x height, as images."""
    half = (width // 2 // 2 * 2, height // 2 // 2 * 2)  # decode at half size: 480p sources, memory stays small
    cmd = [
        compose.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", f"fps={FPS},scale={half[0]}:{half[1]}:force_original_aspect_ratio=increase,crop={half[0]}:{half[1]}",
        "-frames:v", str(limit), "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=False).stdout
    size = half[0] * half[1] * 3
    return [Image.frombytes("RGB", half, raw[i : i + size]) for i in range(0, len(raw) - size + 1, size)]


def spread_words(lines: list[TimedLine]) -> list[Word]:
    """Word timings without a transcript: each line's time is shared out by word length."""
    words: list[Word] = []
    for n, line in enumerate(lines):
        tokens = line.text.split()
        weights = [len(token) + 1 for token in tokens]
        cursor, span = line.start, line.end - line.start
        for token, weight in zip(tokens, weights):
            length = span * weight / sum(weights)
            words.append(Word(token, round(cursor, 3), round(cursor + length, 3), speaker=str(n)))
            cursor += length
    return words


@dataclass
class SetWord:
    text: str
    x: float
    y: float
    start: float


@dataclass
class SetLine:
    """One narrator line laid out for the frame: where each word goes and when it is spoken."""

    words: list[SetWord]
    size: int
    top: float


def set_line(words: list[Word], draw: ImageDraw.ImageDraw, *, width: float = WIDTH - 2 * PAD) -> SetLine:
    """Wrap a line's words in the serif, shrinking until it fits in LINE_ROWS, set up from LINE_BOTTOM."""
    for size in LINE_SIZES:
        face = serif(size)
        rows = wrap_text(draw, " ".join(w.text for w in words), face, width)
        if len(rows) <= LINE_ROWS:
            break
    leading = round(size * 1.32)
    top = LINE_BOTTOM - len(rows) * leading
    space = draw.textlength(" ", font=face)
    placed, i = [], 0
    for r, row in enumerate(rows):
        x = PAD
        for token in row.split():
            placed.append(SetWord(token, x, top + r * leading, words[i].start))
            x += draw.textlength(token, font=face) + space
            i += 1
    return SetLine(placed, size, top)


def loudness(track: VoiceTrack, frames: int) -> list[float]:
    """Loudness of the voice per video frame, 0..1, for the narrator's waveform.

    A silent track (the free preview) gets a stand-in that moves while a line is "spoken".
    """
    levels = [0.0] * frames
    try:
        with wave.open(str(track.audio), "rb") as wav:
            rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
            raw = wav.readframes(wav.getnframes())
    except (wave.Error, OSError):
        raw, width, rate, channels = b"", 2, 48000, 1
    if width == 2 and raw:
        samples = array("h", raw)[::channels]
        per_frame = rate / FPS
        for f in range(frames):
            chunk = samples[int(f * per_frame) : int((f + 1) * per_frame) : 8]
            if chunk:
                levels[f] = math.sqrt(sum(s * s for s in chunk) / len(chunk)) / 32768
    peak = max(levels) or 0.0
    if peak < 1e-4:
        for f in range(frames):
            t = f / FPS
            if any(line.start <= t <= line.end for line in track.lines):
                levels[f] = 0.5 + 0.35 * math.sin(t * 17) * math.sin(t * 5.3)
        return levels
    return [min(1.0, level / peak * 1.2) for level in levels]


def _chrome(frame: Image.Image, *, t: float, beats: list[Beat], starts: list[float], speech_end: float, login: str, span: str, title: str) -> None:
    """Progress segments (one per beat, like stories) and the mono "login / dates" line under them."""
    draw = ImageDraw.Draw(frame)
    n = len(beats)
    gap, x0, x1 = 9, PAD - 12, WIDTH - PAD + 12
    width = (x1 - x0 - gap * (n - 1)) / n
    for i in range(n):
        start = starts[i]
        end = starts[i + 1] if i + 1 < n else speech_end
        fill = phase(t, start, max(end - start, 0.1))
        x = x0 + i * (width + gap)
        draw.rectangle((x, 48, x + width, 54), fill=(66, 70, 76))
        if fill > 0:
            draw.rectangle((x, 48, x + width * fill, 54), fill=(232, 233, 234))
    draw.text((PAD - 12, 84), f"{login} / {span}", font=mono(28), fill=(139, 148, 158))
    draw.text((WIDTH - PAD + 12, 84), title.lower(), font=mono(28), fill=(139, 148, 158), anchor="ra")


def _line(frame: Image.Image, *, t: float, line: SetLine | None, name: str, levels_recent: list[float], theme: Theme) -> None:
    """Who is talking, with a small waveform that moves with the voice, and the line, lit word by word."""
    draw = ImageDraw.Draw(frame)
    label_y = (line.top if line else LINE_BOTTOM - 70) - 30
    face = mono(28)
    draw.text((PAD, label_y), name, font=face, fill=theme.dim, anchor="ls")
    x = PAD + draw.textlength(name, font=face) + 22
    for i, value in enumerate(levels_recent):
        h = max(3, 26 * value)
        draw.rectangle((x + i * 9, label_y - 10 - h / 2, x + i * 9 + 4, label_y - 10 + h / 2), fill=mix(theme.dim, theme.accent, value))
    if not line:
        return
    body = serif(line.size)
    for word in line.words:
        spoken = phase(t, word.start - 0.05, 0.12)
        draw.text((word.x, word.y), word.text, font=body, fill=mix((92, 99, 108), TEXT, spoken))


def render_video(
    *,
    stats: Stats,
    beats: list[Beat],
    track: VoiceTrack,
    end_card: Path,
    dest: Path,
    theme: Theme,
    narrator: str,
    title: str = "GitHub Wrapped",
    captions: bool = True,
    style: str = "wrapped",
) -> Path:
    """`beats[i]` plays during `track.lines[i]`; the sign-off (the last line) stays on the last scene."""
    if len(beats) != len(track.lines) - 1:
        raise ValueError(f"{len(beats)} scenes for {len(track.lines) - 1} beats")
    workdir = dest.parent
    workdir.mkdir(parents=True, exist_ok=True)
    speech_end = track.duration
    total = speech_end + END_CARD_SECONDS
    frames = math.ceil(total * FPS)
    full = style == "wrapped"
    area_y, area_h = (0, FRAME_HEIGHT) if full else (AREA_Y, AREA_HEIGHT)

    scenes: list[Draw] = []
    for b in beats:
        frames_of_clip = clip_frames(b.clip, width=WIDTH, height=area_h) if (b.clip and full) else None
        scenes.append(make_scene(b.highlight, stats, theme, b.tone, art=b.art, clip=frames_of_clip or None, style=style))
    # A scene arrives a touch before its line, so the picture lands with the first word.
    starts = [0.0] + [max(0.0, track.lines[i].start - 0.2) for i in range(1, len(beats))]
    levels = loudness(track, frames)
    background = Image.new("RGB", (WIDTH, FRAME_HEIGHT), theme.bottom)
    area_background = Image.new("RGB", (WIDTH, area_h), theme.bottom)
    with Image.open(end_card) as opened:
        end = opened.convert("RGB").resize((WIDTH, FRAME_HEIGHT))
    who, _, voice = narrator.partition(" · ")  # "The Tired Senior Engineer · voice of Elon Musk"
    name = who.lower() + (f" · {voice}" if voice else "")
    measure = ImageDraw.Draw(background)
    by_line: dict[str, list[Word]] = {}
    for word in spread_words(track.lines):
        by_line.setdefault(word.speaker or "0", []).append(word)
    set_lines = [set_line(by_line[str(n)], measure) if str(n) in by_line else None for n in range(len(track.lines))]
    dates = f"{stats.since:%b %Y} – {stats.until:%b %Y}"

    def scene_area(index: int, t: float) -> Image.Image:
        area = area_background.copy()
        end_t = starts[index + 1] if index + 1 < len(beats) else speech_end
        scenes[index](area, max(0.0, t - starts[index]), end_t - starts[index])
        return area

    def line_at(t: float) -> SetLine | None:
        """The line being spoken, held until the next one starts."""
        current = None
        for n, line in enumerate(track.lines):
            if line.start - 0.15 <= t:
                current = set_lines[n]
        return current

    cmd = [
        compose.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{FRAME_HEIGHT}", "-r", str(FPS), "-i", "-",
        "-i", str(track.audio.resolve()),
        "-filter_complex", f"[0:v]format=yuv420p[out];[1:a]apad=pad_dur={END_CARD_SECONDS + 1}[aout]",
        "-map", "[out]", "-map", "[aout]", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
        dest.name,
    ]
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errors, cwd=workdir)
        try:
            for f in range(frames):
                t = f / FPS
                if t >= speech_end + FADE_TO_END:
                    frame = end
                else:
                    frame = background.copy()
                    current = max(i for i, s in enumerate(starts) if s <= t)
                    slide = ease_in_out(phase(t, starts[current], SLIDE_SECONDS)) if current else 1.0
                    if slide < 1:
                        offset = round(WIDTH * slide)
                        frame.paste(scene_area(current - 1, t), (-offset, area_y))
                        frame.paste(scene_area(current, t), (WIDTH - offset, area_y))
                    else:
                        frame.paste(scene_area(current, t), (0, area_y))
                    _chrome(frame, t=t, beats=beats, starts=starts, speech_end=speech_end, login=stats.login, span=dates, title=title)
                    recent = [levels[max(0, f - WAVE_BARS + 1 + i)] for i in range(WAVE_BARS)]
                    _line(frame, t=t, line=line_at(t) if captions else None, name=name, levels_recent=recent, theme=theme)
                    if t >= speech_end:
                        frame = Image.blend(frame, end, ease_out(phase(t, speech_end, FADE_TO_END)))
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        code = proc.wait()
        if code != 0:
            errors.seek(0)
            tail = "\n".join(errors.read().decode(errors="replace").strip().splitlines()[-20:])
            raise compose.FFmpegError(f"ffmpeg failed ({code}):\n{tail}")
    return dest


def silent_track(lines: list[str], workdir: Path, *, words_per_second: float, gap: float = 0.35, tail: float = 0.6) -> VoiceTrack:
    """A soundless stand-in for the voice, timed from word counts: the free preview's clock."""
    workdir.mkdir(parents=True, exist_ok=True)
    timed, cursor = [], 0.0
    for n, text in enumerate(lines):
        length = max(0.8, len(text.split()) / words_per_second)
        timed.append(TimedLine(text=text, start=round(cursor, 3), end=round(cursor + length, 3)))
        cursor += length + (tail if n == len(lines) - 1 else gap)
    audio = workdir / "silence.wav"
    compose.run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{cursor:.3f}", "-c:a", "pcm_s16le", audio.resolve()])
    return VoiceTrack(audio=audio, duration=round(cursor, 3), lines=timed)
