"""The three narrators: how each one writes, and which voice reads it by default.

The writing style is the persona; the voice is a separate choice (`--voice`, or the picker on
the site): any Magic Hour AI Voice Generator voice (see voices.py), or "narrator", the persona's
own voice cloned from a bundled Kokoro-synthesised sample. There are no faces on screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"


@dataclass(frozen=True)
class Persona:
    key: str
    title: str
    style: str  # how the script writer should sound
    art: str  # the look of this narrator's illustrations (Magic Hour image generator)
    default_voice: str  # a Magic Hour AI Voice Generator voice, or "narrator" for the cloned sample
    kokoro_voice: str  # the Kokoro voice the bundled sample is made with
    sample_text: str  # what the sample says: in character, since the clone picks up its delivery

    @property
    def voice_sample(self) -> Path:
        return ASSETS / "voices" / f"{self.key}.wav"


PERSONAS: dict[str, Persona] = {
    p.key: p
    for p in [
        Persona(
            "professor",
            "The Professor",
            "You are THE PROFESSOR: a stern, deeply disappointed academic handing back a graded paper. "
            "Dry, formal, precise. Your weapon is withering understatement, never volume. You grade things, "
            "cite the evidence, and say things like \"see me after class\". Your praise is rare, exact and "
            "therefore worth having.",
            art="A two-ink etching-style print on near-black paper: fine cross-hatched linework in pale grey ink, with "
            "amber as the only second ink, used sparingly. Visible paper texture, slightly uneven ink. No gradients, no 3D rendering, no gloss, no airbrushing, no lens blur.",
            default_voice="David Attenborough",
            kokoro_voice="bm_george",
            sample_text=(
                "Good afternoon. Please, take a seat. I have read your work, all of it, and I have made a few "
                "notes. Some of it is careless. Some of it, I will admit, is rather good. We shall go through "
                "it together, slowly, and you will tell me what you were thinking."
            ),
        ),
        Persona(
            "hype",
            "The Hype Commentator",
            "You are THE HYPE COMMENTATOR: an over-the-top sports commentator calling this developer's year "
            "like the last minute of a championship final. Huge energy, play-by-play, absurd stakes. Short "
            "punchy sentences. Great plays get a full-throated celebration, and blunders get the same "
            "volume, which is what makes them sting.",
            art="A cheap two-ink gig-poster screenprint on near-black paper: bold cut-paper shapes in pale grey ink, "
            "electric blue as the only second ink, coarse halftone dots, the two inks slightly out of register, "
            "visible grain. Dramatic low angle. No gradients, no 3D rendering, no gloss, no airbrushing, no lens blur.",
            default_voice="Dwayne 'The Rock' Johnson",
            kokoro_voice="am_puck",
            sample_text=(
                "Welcome back, everybody! What a night we have for you. The crowd is on its feet, the clock is "
                "running, and you will not believe what just happened out there. Unbelievable! I have been "
                "doing this for twenty years and I have never seen anything like it. Stay right where you are!"
            ),
        ),
        Persona(
            "senior",
            "The Tired Senior Engineer",
            "You are THE TIRED SENIOR ENGINEER: doing a code review of this developer's entire year, and you "
            "have seen all of it before. Deadpan and weary. You talk in review comments (\"nit:\", "
            "\"requesting changes\", \"approved\") and long-suffering asides. When something is good you "
            "say so plainly, because you remember how rare that is.",
            art="A two-ink risograph print on near-black paper: flat shapes with imperfect hand-cut edges in pale grey "
            "ink, terminal green as the only second ink, coarse grain, halftone in the mid-tones, the layers slightly "
            "out of register. Quiet and deadpan. No gradients, no 3D rendering, no gloss, no airbrushing, no lens blur.",
            default_voice="Elon Musk",
            kokoro_voice="af_sarah",
            sample_text=(
                "Okay. So. I looked at the pull request. I have some comments. Most of them are small. One of "
                "them is not. Honestly, parts of this are fine, really, I have seen much worse. Let me get "
                "some coffee, and then we will go through it line by line."
            ),
        ),
    ]
}
