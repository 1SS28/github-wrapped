"""Themes, fonts and the end card. The animated scenes themselves are in scenes.py."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from roastmygithub.highlights import Highlight
from roastmygithub.script import Script
from roastmygithub.stats import Stats

WIDTH, FRAME_HEIGHT = 1080, 1920
MARGIN = 80
TONE_TAG = {"roast": ("ROAST", (248, 81, 73)), "compliment": ("PROPS", (63, 185, 80))}

_FONTS = {
    True: [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    False: [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
}


@dataclass(frozen=True)
class Theme:
    top: tuple[int, int, int]  # background gradient
    bottom: tuple[int, int, int]
    accent: tuple[int, int, int]
    text: tuple[int, int, int] = (230, 237, 243)
    dim: tuple[int, int, int] = (139, 148, 158)

    @property
    def accent_hex(self) -> str:
        return "%02X%02X%02X" % self.accent


# GitHub's dark palette (canvas #0d1117, panel #161b22) with one accent per narrator.
THEMES = {
    "professor": Theme(top=(22, 27, 34), bottom=(13, 17, 23), accent=(210, 153, 34)),  # amber
    "hype": Theme(top=(22, 27, 34), bottom=(13, 17, 23), accent=(88, 166, 255)),  # blue
    "senior": Theme(top=(22, 27, 34), bottom=(13, 17, 23), accent=(63, 185, 80)),  # green
}


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (os.environ.get("ROAST_FONT_BOLD" if bold else "ROAST_FONT"), *_FONTS[bold]):
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def _background(theme: Theme, height: int) -> Image.Image:
    column = Image.new("RGB", (1, height))
    for y in range(height):
        k = y / max(1, height - 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * k) for a, b in zip(theme.top, theme.bottom)))
    return column.resize((WIDTH, height))


def _fit(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, smallest: int, bold: bool = True):
    """The largest font from `start` down to `smallest` at which `text` fits on one line."""
    size = start
    while size > smallest and draw.textlength(text, font=font(size, bold)) > max_width:
        size -= 6
    return font(size, bold)


def _wrap(draw: ImageDraw.ImageDraw, text: str, face, max_width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(trial, font=face) <= max_width:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def _centred(draw: ImageDraw.ImageDraw, y: int, text: str, face, fill) -> int:
    """Draw one centred line with its top at `y`; returns the y below it."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=face)
    draw.text(((WIDTH - (right - left)) / 2 - left, y - top), text, font=face, fill=fill)
    return y + (bottom - top)


def _pill(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, colour) -> None:
    face = font(34)
    width = draw.textlength(text, font=face)
    draw.rounded_rectangle((x, y, x + width + 48, y + 60), radius=30, fill=colour)
    draw.text((x + 24, y + 30), text, font=face, fill=(12, 14, 18), anchor="lm")


def render_end_card(stats: Stats, script: Script, shown: list[Highlight], dest: Path, *, theme: Theme, persona_title: str, repo_url: str) -> Path:
    """Full-frame closing card: who, the verdict, their top stats, and where to make your own."""
    image = _background(theme, FRAME_HEIGHT)
    draw = ImageDraw.Draw(image)
    inner = WIDTH - 2 * MARGIN
    draw.rectangle((0, 0, WIDTH, 12), fill=theme.accent)
    y = _centred(draw, 150, "GITHUB WRAPPED", font(44), theme.dim) + 60
    y = _centred(draw, y, f"@{stats.login}", _fit(draw, f"@{stats.login}", inner, 120, 60), theme.text) + 34
    y = _centred(draw, y, f"{stats.since:%b %Y} – {stats.until:%b %Y}", font(40, bold=False), theme.dim) + 80
    if script.verdict:
        verdict = f"“{script.verdict}”"
        y = _centred(draw, y, verdict, _fit(draw, verdict, inner, 92, 48), theme.accent) + 26
        y = _centred(draw, y, f"verdict of {persona_title}", font(36, bold=False), theme.dim) + 80

    row_height = 190
    for highlight in shown[:4]:
        draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + row_height - 26), radius=28, fill=tuple(min(255, c + 16) for c in theme.top))
        value_face = _fit(draw, highlight.value, 330, 100, 44)
        draw.text((MARGIN + 44, y + (row_height - 26) / 2), highlight.value, font=value_face, fill=theme.accent, anchor="lm")
        label_face = font(38, bold=False)
        lines = _wrap(draw, highlight.label, label_face, inner - 430)[:2]
        top = y + (row_height - 26) / 2 - (len(lines) - 1) * 24
        for n, line in enumerate(lines):
            draw.text((MARGIN + 410, top + n * 48), line, font=label_face, fill=theme.text, anchor="lm")
        y += row_height

    y = max(y + 50, FRAME_HEIGHT - 330)
    y = _centred(draw, y, "Make yours", font(72), theme.text) + 34
    _centred(draw, y, repo_url, _fit(draw, repo_url, inner, 48, 30, bold=False), theme.accent)
    _centred(draw, FRAME_HEIGHT - 90, "made with Magic Hour", font(32, bold=False), theme.dim)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest)
    return dest
