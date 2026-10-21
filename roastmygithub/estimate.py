"""What a render costs in Magic Hour credits, worked out before anything is spent.

The only paid step is the voice: AI Voice Cloner, 0.1 credit per character, rounded up per
request (docs.magichour.ai/api-reference/models, checked 2026-10-14). The animation is drawn
locally. A 60 s script is about 850 characters: ~85 credits.
"""

from __future__ import annotations

import math

VOICE_CREDITS_PER_CHARACTER = 0.1
CHARACTERS_PER_WORD = 6.0  # with spaces and punctuation, for estimates made before a script exists


def voice_credits(lines: list[str]) -> int:
    """One voice request per line, each rounded up."""
    return sum(math.ceil(len(line) * VOICE_CREDITS_PER_CHARACTER) for line in lines if line)
