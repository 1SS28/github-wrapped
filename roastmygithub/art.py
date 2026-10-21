"""Illustrations for each beat, from the Magic Hour AI Image Generator (and, for a couple of
hero beats, Image-to-Video).

The script writer describes each beat's picture (`Beat.visual`); the narrator's art direction
sets the look; this module turns that into a 9:16 image per beat with `krea-2` (10 credits,
the cleanest of the cheap models in our tests: no stray lettering). Every image is checked with
Magic Hour's free face detection, because the rule is no people on screen; one with a face is
drawn again with a firmer prompt, and if that fails too the beat falls back to a plain
background. Images are cached by prompt, so an edited line only redraws its own beat.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from core.costs import LedgerEntry
from core.magichour import MagicHour, MagicHourError, MagicHourJobFailed

IMAGE_MODEL = "krea-2"
IMAGE_CREDITS = 10  # per image at 1k, krea-2
VIDEO_MODEL = "ltx-2.5"
VIDEO_RESOLUTION = "480p"
VIDEO_CREDITS_PER_SECOND = 24  # ltx-2.5 at 480p
HERO_SECONDS = 4
NO_PEOPLE = "No people, no faces, no hands, no figures, no silhouettes. No text, no words, no letters, no numbers, no logos."
RETRY_SUFFIX = " An empty scene: objects and environment only, nobody present at all."
MOTION_PROMPT = "Subtle, slow, looping motion: gentle drift and parallax, soft light changes. The camera barely moves. Nothing new appears. No people."


@dataclass
class Artwork:
    image: Path
    video: Path | None = None  # a short animated version, for hero beats
    faces_found: int = 0  # how many attempts turned up a face (for the report)
    fallback: bool = False  # True when no acceptable image came back


def prompt_for(visual: str, art_direction: str) -> str:
    """The beat's scene is the subject; the narrator's art direction only sets palette and style."""
    scene = visual.strip().rstrip(".") or "an abstract arrangement of soft geometric shapes"
    return (
        f"{scene}. One clear subject, large and centred in the upper two thirds of a tall frame, against a simple "
        f"background, with calm empty space across the lower third. {art_direction} {NO_PEOPLE}"
    )


def _key(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:12]


def estimate_credits(beats: int, *, heroes: int = 0, hero_seconds: int = HERO_SECONDS) -> int:
    return beats * IMAGE_CREDITS + heroes * hero_seconds * VIDEO_CREDITS_PER_SECOND


def pending(visuals: list[str], *, art_direction: str, workdir: Path, heroes: set[int] = frozenset()) -> tuple[int, int]:
    """(images, clips) that are not cached yet, so the spend can be stated before it happens."""
    images = clips = 0
    for index, visual in enumerate(visuals):
        prompt = prompt_for(visual, art_direction)
        if not (workdir / f"beat_{index:02d}_{_key(prompt, IMAGE_MODEL)}.png").exists():
            images += 1
        if index in heroes and not (workdir / f"beat_{index:02d}_{_key(prompt, VIDEO_MODEL, VIDEO_RESOLUTION, str(HERO_SECONDS))}.mp4").exists():
            clips += 1
    return images, clips


def generate(
    mh: MagicHour | None,
    visuals: list[str],
    *,
    art_direction: str,
    workdir: Path,
    heroes: set[int] = frozenset(),
    concurrency: int = 3,
) -> list[Artwork]:
    """One illustration per visual (and a short clip for the indexes in `heroes`), cached in `workdir`.

    With `mh=None` nothing is generated: cached files are used and the rest fall back.
    """
    workdir.mkdir(parents=True, exist_ok=True)

    def draw(job: tuple[int, str]) -> Artwork:
        index, visual = job
        prompt = prompt_for(visual, art_direction)
        image = workdir / f"beat_{index:02d}_{_key(prompt, IMAGE_MODEL)}.png"
        art = Artwork(image=image)
        if image.exists():
            if mh:
                mh.ledger.add(LedgerEntry(provider="magichour", kind="image_generate", label=f"art {index + 1}", status="cached", credits=0))
        elif mh is None:
            art.fallback = True
            return art
        else:
            for attempt, text in enumerate((prompt, prompt + RETRY_SUFFIX)):
                try:
                    job_id = mh.image_generate(prompt=text, model=IMAGE_MODEL, aspect_ratio="9:16", resolution="1k", label=f"art {index + 1}")
                    mh.download_result(job_id, "image", image)
                except MagicHourJobFailed:
                    if attempt:
                        raise
                    continue
                if not mh.detect_faces(image):
                    break
                art.faces_found += 1
                image.unlink(missing_ok=True)
            else:
                art.fallback = True  # both attempts drew somebody; the renderer uses a plain background
                return art
        if index in heroes:
            video = workdir / f"beat_{index:02d}_{_key(prompt, VIDEO_MODEL, VIDEO_RESOLUTION, str(HERO_SECONDS))}.mp4"
            if video.exists():
                if mh:
                    mh.ledger.add(LedgerEntry(provider="magichour", kind="image_to_video", label=f"art {index + 1} motion", status="cached", credits=0))
            elif mh is None:
                video = None
            else:
                try:
                    job_id = mh.image_to_video(image=image, seconds=HERO_SECONDS, prompt=MOTION_PROMPT, model=VIDEO_MODEL, resolution=VIDEO_RESOLUTION, label=f"art {index + 1} motion")
                    mh.download_result(job_id, "video", video)
                except MagicHourError:
                    video = None  # the still is fine on its own; the failure is in the ledger
            art.video = video
        return art

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(draw, enumerate(visuals)))
