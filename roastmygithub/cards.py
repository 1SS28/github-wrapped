"""Themes, fonts, the contribution graph and the end card. The animated scenes are in scenes.py.

The look follows the website's player and share card: GitHub's dark canvas, the real contribution
graph in GitHub's greens, figures in a monospace face, the verdict and the narrator's lines in a
serif (Tinos on the site; Liberation Serif, which is built from Tinos, or Times New Roman here).
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from roastmygithub.highlights import Highlight
from roastmygithub.script import Script
from roastmygithub.stats import DayCount, Stats

WIDTH, FRAME_HEIGHT = 1080, 1920
MARGIN = 80
PAD = 56  # side margin of the frame chrome, the art scenes and the end card, as on the site

CANVAS = (13, 17, 23)  # GitHub dark: #0d1117
BORDER = (48, 54, 61)  # #30363d
TEXT = (230, 237, 243)  # #e6edf3
SOFT = (201, 209, 217)  # #c9d1d9
DIM = (139, 148, 158)  # #8b949e
# The tone of a beat, written as a word in its colour (no badge): GitHub's diff red and green.
TONE = {"roast": ("roast", (248, 81, 73)), "compliment": ("props", (63, 185, 80))}
# GitHub's contribution-graph greens, from an empty day to the busiest.
LEVELS = [(22, 27, 34), (14, 68, 41), (0, 109, 50), (38, 166, 65), (57, 211, 83)]

_FONTS = {
    "sans-bold": [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "sans": [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
    "serif-bold": [
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
    ],
    "serif": [
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "C:/Windows/Fonts/times.ttf",
    ],
    "mono": [
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "C:/Windows/Fonts/consola.ttf",
    ],
}
_ENV = {"sans-bold": "ROAST_FONT_BOLD", "sans": "ROAST_FONT", "serif-bold": "ROAST_FONT_SERIF_BOLD", "serif": "ROAST_FONT_SERIF", "mono": "ROAST_FONT_MONO"}


@dataclass(frozen=True)
class Theme:
    top: tuple[int, int, int]  # background (flat: top and bottom are the same canvas)
    bottom: tuple[int, int, int]
    accent: tuple[int, int, int]
    text: tuple[int, int, int] = TEXT
    dim: tuple[int, int, int] = DIM

    @property
    def accent_hex(self) -> str:
        return "%02X%02X%02X" % self.accent


# GitHub's dark canvas with one accent per narrator, the same ones the site uses.
THEMES = {
    "professor": Theme(top=CANVAS, bottom=CANVAS, accent=(210, 153, 34)),  # amber
    "hype": Theme(top=CANVAS, bottom=CANVAS, accent=(88, 166, 255)),  # blue
    "senior": Theme(top=CANVAS, bottom=CANVAS, accent=(63, 185, 80)),  # green
}


@functools.lru_cache(maxsize=None)
def _face(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (os.environ.get(_ENV[kind]), *_FONTS[kind]):
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _face("sans-bold" if bold else "sans", size)


def serif(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _face("serif-bold" if bold else "serif", size)


def mono(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _face("mono", size)


def span(stats: Stats) -> str:
    return f"{stats.since:%b %Y} – {stats.until:%b %Y}"


def wrap_text(draw: ImageDraw.ImageDraw, text: str, face, max_width: float) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(trial, font=face) <= max_width:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def level(count: int, top: int) -> tuple[int, int, int]:
    """The site's rule: empty, or one of four greens by share of the busiest day."""
    return LEVELS[min(4, 1 + (3 * count) // max(1, top))] if count > 0 else LEVELS[0]


def calendar_cells(days: list[DayCount], x: float, y: float, width: float, *, gap: int = 5, strip_gap: int = 26) -> tuple[list[tuple[float, float, float, DayCount]], float]:
    """The year as GitHub draws it, Sunday-first weeks in two half-year strips across `width`.

    Returns (x, y, size, day) per cell and the y just below the second strip.
    """
    if not days:
        return [], y
    first = days[0].date
    lead = (first.weekday() + 1) % 7  # Sunday = 0
    weeks = (lead + len(days) + 6) // 7
    half = (weeks + 1) // 2
    cell = (width - (half - 1) * gap) / half
    pitch = cell + gap
    cells = []
    for n, day in enumerate(days):
        week, row = divmod(lead + n, 7)
        strip, column = divmod(week, half)
        cells.append((x + column * pitch, y + strip * (7 * pitch - gap + strip_gap) + row * pitch, cell, day))
    return cells, y + 2 * (7 * pitch - gap) + strip_gap


def draw_calendar(draw: ImageDraw.ImageDraw, days: list[DayCount], x: float, y: float, width: float, **kw) -> float:
    cells, bottom = calendar_cells(days, x, y, width, **kw)
    top = max((d.count for d in days), default=1)
    for cx, cy, size, day in cells:
        draw.rounded_rectangle((cx, cy, cx + size, cy + size), radius=max(2, round(size / 7)), fill=level(day.count, top))
    return bottom


def render_end_card(stats: Stats, script: Script, shown: list[Highlight], dest: Path, *, theme: Theme, persona_title: str, repo_url: str) -> Path:
    """The closing frame, laid out like the site's share card (without the rank, which stays on the site).

    A mono header line, the contribution graph as the picture, the verdict as a serif headline,
    the figures as a ruled list, and where to make your own.
    """
    image = Image.new("RGB", (WIDTH, FRAME_HEIGHT), CANVAS)
    draw = ImageDraw.Draw(image)
    inner = WIDTH - 2 * PAD
    y = 100
    draw.text((PAD, y), f"{stats.login} / {span(stats)}", font=mono(28), fill=DIM)
    draw.text((WIDTH - PAD, y), "github wrapped", font=mono(28), fill=DIM, anchor="ra")

    y = draw_calendar(draw, stats.calendar, PAD, y + 70, inner)
    draw.text((PAD, y + 22), f"{stats.total_contributions:,} contributions · {stats.active_days} active days", font=mono(28), fill=DIM)
    y += 130

    if script.verdict:
        size = 112
        while size > 64:
            face = serif(size, bold=True)
            lines = wrap_text(draw, script.verdict, face, inner)
            if len(lines) <= 3:
                break
            size -= 8
        for line in lines:
            draw.text((PAD, y), line, font=face, fill=TEXT, anchor="la")
            y += round(size * 0.98)
        y += 24
    draw.text((PAD, y), persona_title.lower(), font=font(38), fill=theme.accent)
    y += 90

    footer = FRAME_HEIGHT - 260  # the list stops above the address, however long the verdict ran
    draw.line((PAD, y, WIDTH - PAD, y), fill=BORDER, width=2)
    value_face, label_face = mono(64), font(36, bold=False)
    for highlight in shown[:4]:
        value = highlight.value
        while draw.textlength(value, font=value_face) > 330 and len(value) > 3:
            value_face = mono(value_face.size - 6)
        lines = wrap_text(draw, highlight.label, label_face, inner - 380)[:2]
        row = max(124, 60 + 46 * len(lines))
        if y + row > footer:
            break
        middle = y + row / 2
        draw.text((PAD, middle), highlight.value, font=value_face, fill=TEXT, anchor="lm")
        for n, line in enumerate(lines):
            draw.text((PAD + 380, middle + (n - (len(lines) - 1) / 2) * 46), line, font=label_face, fill=SOFT, anchor="lm")
        y += row
        draw.line((PAD, y, WIDTH - PAD, y), fill=BORDER, width=2)
        value_face = mono(64)

    bottom = FRAME_HEIGHT - 110
    draw.text((PAD, bottom - 52), repo_url, font=mono(34), fill=TEXT, anchor="ls")
    draw.text((PAD, bottom), "made with Magic Hour", font=mono(26), fill=DIM, anchor="ls")
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest)
    return dest

