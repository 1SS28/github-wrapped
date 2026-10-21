"""Build the bundled persona voice samples with Kokoro (Apache-2.0 text-to-speech).

The samples are synthetic: no person's voice is recorded or imitated. Magic Hour's AI Voice
Cloner then speaks each script in the sample's voice.

Kokoro pulls in PyTorch, so it lives in its own environment (Python 3.12), not the project's:

    uv venv --python 3.12 .venv-tools
    uv pip install --python .venv-tools/bin/python "kokoro>=0.9.2" soundfile "transformers>=4.40" \
        https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
    PYTHONPATH=. .venv-tools/bin/python tools/make_voice_samples.py [persona ...]

The first run downloads the Kokoro weights (~330 MB) from Hugging Face.
"""

from __future__ import annotations

import sys

import numpy as np
import soundfile as sf
from kokoro import KPipeline

from roastmygithub.personas import PERSONAS

SAMPLE_RATE = 24000


def main(keys: list[str]) -> None:
    pipelines: dict[str, KPipeline] = {}
    for key in keys or list(PERSONAS):
        persona = PERSONAS[key]
        lang = persona.kokoro_voice[0]  # "a" American, "b" British
        pipeline = pipelines.setdefault(lang, KPipeline(lang_code=lang))
        audio = np.concatenate([np.asarray(chunk) for _, _, chunk in pipeline(persona.sample_text, voice=persona.kokoro_voice)])
        persona.voice_sample.parent.mkdir(parents=True, exist_ok=True)
        sf.write(persona.voice_sample, audio, SAMPLE_RATE)
        print(f"{key}: {persona.voice_sample} ({len(audio) / SAMPLE_RATE:.1f} s, voice {persona.kokoro_voice})")


if __name__ == "__main__":
    main(sys.argv[1:])
