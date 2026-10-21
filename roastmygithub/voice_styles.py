"""How the most-picked voices talk, so the script is written for the voice that will read it.

Magic Hour's voice generator takes only text and a voice name: there is no emotion or pacing
control, so the words are the only way to get the delivery right. A line written for a deadpan
code reviewer sounds wrong in a voice known for superlatives, and the other way round.

These notes describe speech only: rhythm, sentence shape, word habits. They never put the real
person's life, work, politics or opinions into the script; the persona is still the character
and the facts are still only the developer's GitHub. Voices without a note get the persona's
own way of talking.
"""

from __future__ import annotations

PEOPLE: dict[str, str] = {
    # Real people: verbal habits only.
    "Donald Trump": (
        "Superlatives and absolutes everywhere: the worst, maybe ever, nobody has ever seen anything like it, "
        "tremendous, a disaster, a total disaster. Repeat the key word for emphasis (zero, zero pull requests). "
        "Short declarative bursts, a quick tangent, then back to the point. Asides like 'believe me', 'frankly', "
        "'many people are saying', 'it's true'. Give the habit a mocking nickname. A one-word sentence to finish a "
        "thought: 'Sad.' 'Terrible.' 'Wrong.'"
    ),
    "Elon Musk": (
        "Halting and understated. Start lines with 'So,' or 'Well,' and let the thought stall: 'that's, uh, a lot "
        "of days'. Flat engineering vocabulary (first principles, the obvious failure mode, pretty much, basically, "
        "non-trivial). Deadpan one-word verdicts like 'Concerning.' or 'Wild.' Understate the disaster, never shout."
    ),
    "David Attenborough": (
        "A hushed nature documentary. Describe the developer in the third person as a rare creature observed in its "
        "habitat: 'Here, in the dead of night, the developer emerges.' Present tense, long flowing sentences with "
        "gentle commas, quiet wonder at behaviour that makes no sense for survival. The roast is in the calm."
    ),
    "Morgan Freeman": (
        "A slow, warm storyteller looking back. Past tense, short reflective sentences, a weary wisdom that makes the "
        "mistakes sound like fate: 'It was past midnight. It was always past midnight.' Gentle irony, never a raised voice."
    ),
    "Gordon Ramsay": (
        "A furious head chef tasting a terrible dish. Rapid short bursts, rhetorical questions, disbelief: 'What is "
        "this? WHAT is this?' Kitchen words for code: raw, bland, undercooked, overcooked, binned. 'Come on!' and "
        "'Oh dear.' Swear-adjacent but clean: bloody, donkey."
    ),
    "Snoop Dogg": (
        "Laid back and unbothered, slow and amused. Casual slang (nephew, for real, you feel me, that's wild), easy "
        "rhythm, the burn delivered like a friendly observation. Never in a hurry."
    ),
    "Samuel L. Jackson": (
        "Intense and incredulous. Repeat their own words back as a challenge: 'Zero? You said zero?' Escalating "
        "emphasis, short punches, a demand for answers. Clean language, but it should feel like it almost was not."
    ),
    "Barack Obama": (
        "Measured and professorial with deliberate pauses. 'Now, look.' 'Let me be clear.' 'Folks,' and an "
        "'uh' mid-thought. Reasonable, patient build-up that lands a calm, devastating conclusion. Nothing political."
    ),
    "Joe Rogan": (
        "Amazed podcast host. 'Dude.' 'That's crazy.' 'A hundred percent.' 'Have you ever tried...' Wanders into "
        "a hypothetical, comes back amazed. Casual, run-on, enthusiastic disbelief."
    ),
    "MrBeast": (
        "A hyperactive challenge-video host. Everything is a challenge or an experiment: 'I spent the whole year "
        "watching you not open a pull request.' Fast, loud, countdown energy. Never mention money amounts."
    ),
    "Kim Kardashian": (
        "Flat, unbothered and a little bored. 'Literally.' 'Like,' 'I can't.' Short sentences with long pauses. "
        "Judges the year like a bad outfit."
    ),
    "Dwayne 'The Rock' Johnson": (
        "A booming motivational coach. Gym and grind talk, big encouragement that collapses into disappointment "
        "halfway through a sentence. Direct address, short commands, raised energy."
    ),
    "Arnold Schwarzenegger": (
        "A bodybuilding coach with blunt, simple words. Short commands, gym metaphors (pump, reps, no pain no gain, "
        "skip leg day), slightly formal word order. Disappointment as a training failure."
    ),
    "Keanu Reeves": (
        "Soft, sincere, few words. 'Whoa.' Long pauses, gentle kindness that makes the roast hurt more. Never mean "
        "in tone, only in content."
    ),
    "Kevin Hart": (
        "Fast, high-energy panic. 'No. No, no, no.' 'Listen. LISTEN.' Escalating disbelief, self-interrupting, "
        "physical comedy described in words."
    ),
    "Jeff Goldblum": (
        "Meandering, stammering fascination. 'Well, uh, uh, there it is.' Odd emphasis, trails off, gets "
        "distracted by how interesting the failure is."
    ),
    "Mark Zuckerberg": (
        "A stiff product keynote. 'So,' opens every point. Earnest, slightly robotic, talks about metrics, "
        "connection and shipping, misses the human point entirely."
    ),
}

CHARACTERS: dict[str, str] = {
    # Fictional characters: their catchphrases are part of the voice.
    "Yoda": (
        "Inverted word order, always: 'Committed at midnight, you have.' Short riddles, 'Hmm.' and 'Yes, hmm.' Ancient "
        "patience, disappointed teacher."
    ),
    "Darth Vader": (
        "Slow, ominous, absolute. 'I find your lack of pull requests disturbing.' Threatening calm, imperial "
        "formality, talk of failure and consequences."
    ),
    "GLaDOS": (
        "A clinical, passive-aggressive test-lab AI. Calm reports of the subject's failures, fake encouragement, "
        "test results, science. Cruelty in a customer-service tone."
    ),
    "SpongeBob SquarePants": (
        "Manic, relentless optimism that keeps cracking. 'I'm ready!' Over-enthusiastic, high-pitched excitement "
        "about terrible news, then sudden panic."
    ),
    "Shrek": (
        "A grumpy ogre who wants to be left alone. Blunt, unimpressed, swamp and onion metaphors, 'Better out than "
        "in.' Gruff, short, secretly fond."
    ),
    "Homer Simpson": (
        "Dim, easily distracted dad. 'D'oh!' 'Mmm... merge conflicts.' 'Woo-hoo!' at the wrong moment. Simple words, "
        "food comparisons, cheerful stupidity."
    ),
    "Rick Sanchez": (
        "A nihilist genius, rambling and contemptuous, stammering on the hard consonants. Calls the developer "
        "'Morty'. Everything is beneath him and science says so."
    ),
    "Bender (Futurama)": (
        "An arrogant, lazy robot who approves of bad behaviour for the wrong reasons. Boasting, 'we're boned', "
        "mock respect for their worst habits."
    ),
    "Gollum Smeagol": (
        "Talks to itself in two voices and argues. 'Precious', 'nasty', hissing plurals like 'commitses'. Third "
        "person, wheedling, then snapping."
    ),
    "Kermit the Frog": (
        "Nervous, earnest showman losing control of the show. 'Hi-ho!' flustered asides, 'Yaaay!' that turns into "
        "a groan."
    ),
}


STYLES: dict[str, str] = {**PEOPLE, **CHARACTERS}


def style_for(voice: str | None) -> str | None:
    """The speaking style for this voice, or None to use the persona's own."""
    return STYLES.get(voice or "")


def name_parts(voice: str | None) -> list[str]:
    """Words of a real person's name that must never appear in a line ("Donald Trump" -> donald, trump)."""
    if voice not in PEOPLE:
        return []
    plain = voice.split("'")[0] + voice.split("'")[-1] if "'" in voice else voice  # drop a quoted nickname
    return [w.lower().strip(".") for w in plain.split() if len(w.strip(".")) >= 4]
