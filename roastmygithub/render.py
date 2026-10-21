"""Final video: animated scenes, narrator bar, captions and end card, 1080x1920 at 30 fps.

Frames are drawn in Python (Pillow) and piped straight into ffmpeg, which burns in the
captions and adds the voice. Each beat's scene starts when its line starts (the timings come
from the voice lines), slides in over the previous one, and the end card fades in once the
sign-off is done. No credits are spent here.

Layout, top to bottom: story-style progress segments and the handle; the scene (headline plus
an animated visual); the narrator's name with a live waveform of the voice; captions.
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
from roastmygithub.cards import FRAME_HEIGHT, WIDTH, Theme
from roastmygithub.highlights import Highlight
from roastmygithub.scenes import AREA_HEIGHT, Draw, ease_in_out, ease_out, make_scene, mix, phase, rounded, sans
from roastmygithub.stats import Stats
from roastmygithub.voice import TimedLine, VoiceTrack

FPS = 30
END_CARD_SECONDS = 3.5
FADE_TO_END = 0.45
SLIDE_SECONDS = 0.45
AREA_Y = 190
NARRATOR_Y = 1590
CAPTION_Y = 1775
CAPTION_SIZE = 64
CAPTION_WORDS, CAPTION_CHARS = 4, 22
WAVE_BARS = 28


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


def build_ass(words: list[Word], *, speech_end: float, theme: Theme) -> str:
    """Captions near the bottom, the current word in the accent colour."""
    accent, white = compose._ass_colour("%02X%02X%02X" % theme.accent), "&H00FFFFFF"
    events = []

    def dialogue(start: float, end: float, text: str) -> None:
        if end > start:
            events.append(f"Dialogue: 3,{compose._ass_time(start)},{compose._ass_time(end)},Caption,,0,0,0,,{text}")

    chunks = compose.caption_chunks(words, CAPTION_WORDS, CAPTION_CHARS)
    for n, chunk in enumerate(chunks):
        tokens = [compose._ass_text(word.text.upper()) for word in chunk]
        chunk_end = min(chunk[-1].end + 0.3, chunks[n + 1][0].start if n + 1 < len(chunks) else speech_end)
        for i, word in enumerate(chunk):
            start = chunk[0].start if i == 0 else word.start
            end = chunk[i + 1].start if i + 1 < len(chunk) else chunk_end
            parts = [f"{{\\1c{accent}}}{t}{{\\1c{white}}}" if j == i else t for j, t in enumerate(tokens)]
            pop = "\\fscx86\\fscy86\\t(0,110,\\fscx100\\fscy100)" if i == 0 else ""
            dialogue(start, end, f"{{\\pos({WIDTH // 2},{CAPTION_Y}){pop}}}{' '.join(parts)}")

    return "\n".join(
        [
            "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {WIDTH}", f"PlayResY: {FRAME_HEIGHT}",
            "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding",
            f"Style: Caption,Arial,{CAPTION_SIZE},{white},&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,7,0,5,60,60,0,1",
            "", "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events, "",
        ]
    )


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


def _background(theme: Theme) -> Image.Image:
    column = Image.new("RGB", (1, FRAME_HEIGHT))
    for y in range(FRAME_HEIGHT):
        column.putpixel((0, y), mix(theme.top, theme.bottom, y / (FRAME_HEIGHT - 1)))
    return column.resize((WIDTH, FRAME_HEIGHT))


def _chrome(frame: Image.Image, *, t: float, beats: list[Beat], starts: list[float], speech_end: float, login: str, title: str, theme: Theme) -> None:
    """Progress segments (one per beat, like stories) and the handle."""
    draw = ImageDraw.Draw(frame)
    n = len(beats)
    gap, x0, x1 = 10, 40, WIDTH - 40
    width = (x1 - x0 - gap * (n - 1)) / n
    for i in range(n):
        start = starts[i]
        end = starts[i + 1] if i + 1 < n else speech_end
        fill = phase(t, start, max(end - start, 0.1))
        x = x0 + i * (width + gap)
        rounded(draw, (x, 50, x + width, 58), 4, fill=mix(theme.bottom, (255, 255, 255), 0.25))
        if fill > 0:
            rounded(draw, (x, 50, x + max(width * fill, 8), 58), 4, fill=(255, 255, 255))
    draw.text((40, 100), f"@{login}", font=sans(42), fill=theme.text)
    draw.text((WIDTH - 40, 106), title.upper(), font=sans(30), fill=theme.dim, anchor="ra")


def _narrator(frame: Image.Image, *, name: str, level: float, levels_recent: list[float], theme: Theme) -> None:
    """Who is talking, with bars that move with the voice: the narrator, no face needed."""
    draw = ImageDraw.Draw(frame)
    face = sans(34)
    label = name.upper()
    bar_w, bar_gap, bars_h = 8, 6, 54
    bars_width = WAVE_BARS * (bar_w + bar_gap) - bar_gap
    width = draw.textlength(label, font=face) + bars_width + 110
    x = (WIDTH - width) / 2
    y = NARRATOR_Y
    rounded(draw, (x, y, x + width, y + 84), 42, fill=mix(theme.bottom, (255, 255, 255), 0.08))
    dot = 12 + 6 * level
    draw.ellipse((x + 40 - dot / 2, y + 42 - dot / 2, x + 40 + dot / 2, y + 42 + dot / 2), fill=theme.accent)
    draw.text((x + 66, y + 42), label, font=face, fill=theme.text, anchor="lm")
    bx = x + 66 + draw.textlength(label, font=face) + 24
    for i, value in enumerate(levels_recent):
        h = max(6, bars_h * value)
        cx = bx + i * (bar_w + bar_gap)
        rounded(draw, (cx, y + 42 - h / 2, cx + bar_w, y + 42 + h / 2), 4, fill=mix(theme.dim, theme.accent, value))


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

    scenes: list[Draw] = []
    for b in beats:
        frames_of_clip = clip_frames(b.clip, width=WIDTH, height=AREA_HEIGHT) if (b.clip and style == "wrapped") else None
        scenes.append(make_scene(b.highlight, stats, theme, b.tone, art=b.art, clip=frames_of_clip or None, style=style))
    # A scene arrives a touch before its line, so the picture lands with the first word.
    starts = [0.0] + [max(0.0, track.lines[i].start - 0.2) for i in range(1, len(beats))]
    levels = loudness(track, frames)
    background = _background(theme)
    area_background = background.crop((0, AREA_Y, WIDTH, AREA_Y + AREA_HEIGHT))
    with Image.open(end_card) as opened:
        end = opened.convert("RGB").resize((WIDTH, FRAME_HEIGHT))

    def scene_area(index: int, t: float) -> Image.Image:
        area = area_background.copy()
        end_t = starts[index + 1] if index + 1 < len(beats) else speech_end
        scenes[index](area, max(0.0, t - starts[index]), end_t - starts[index])
        return area

    ass_path = workdir / f"{dest.stem}.ass"
    filters = "format=yuv420p"
    if captions:
        ass_path.write_text(build_ass(spread_words(track.lines), speech_end=speech_end, theme=theme), encoding="utf-8")
        filters = f"ass={ass_path.name},format=yuv420p"
    cmd = [
        compose.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{FRAME_HEIGHT}", "-r", str(FPS), "-i", "-",
        "-i", str(track.audio.resolve()),
        "-filter_complex", f"[0:v]{filters}[out];[1:a]apad=pad_dur={END_CARD_SECONDS + 1}[aout]",
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
                    _chrome(frame, t=t, beats=beats, starts=starts, speech_end=speech_end, login=stats.login, title=title, theme=theme)
                    current = max(i for i, s in enumerate(starts) if s <= t)
                    slide = ease_in_out(phase(t, starts[current], SLIDE_SECONDS)) if current else 1.0
                    if slide < 1:
                        offset = round(WIDTH * slide)
                        frame.paste(scene_area(current - 1, t), (-offset, AREA_Y))
                        frame.paste(scene_area(current, t), (WIDTH - offset, AREA_Y))
                    else:
                        frame.paste(scene_area(current, t), (0, AREA_Y))
                    recent = [levels[max(0, f - WAVE_BARS + 1 + i)] for i in range(WAVE_BARS)]
                    _narrator(frame, name=narrator, level=levels[f], levels_recent=recent, theme=theme)
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
