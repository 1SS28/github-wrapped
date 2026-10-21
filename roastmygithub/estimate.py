"""What the voice costs in Magic Hour credits, worked out before anything is spent.

AI Voice Generator and AI Voice Cloner both charge 0.1 credit per character, rounded up per
request (docs.magichour.ai/api-reference/models, checked 2026-10-14). A 60 s script is about
850 characters: ~85 credits. In the wrapped style the illustrations and animated clips cost
more on top (`art.estimate_credits`); `Pipeline._show_estimate` adds the two together.
"""

from __future__ import annotations

import math

VOICE_CREDITS_PER_CHARACTER = 0.1
CHARACTERS_PER_WORD = 6.0  # with spaces and punctuation, for estimates made before a script exists


def voice_credits(lines: list[str]) -> int:
    """One voice request per line, each rounded up."""
    return sum(math.ceil(len(line) * VOICE_CREDITS_PER_CHARACTER) for line in lines if line)
