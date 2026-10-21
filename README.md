# Roast My GitHub

Turn your own last 12 months on GitHub into a 60-second vertical video. Your year plays out
as animated scenes drawn from your real data (your contribution graph, a 24-hour clock of
when you commit, your actual `git log`, your language bar, your repos), while a narrator
voiced with [Magic Hour](https://magichour.ai) roasts the bad habits and gives real credit
for the good ones.

> **Status: in progress.** The whole pipeline runs end to end. Still to do: a demo video,
> measured costs across several accounts, and publishing.

## Privacy rule

The tool only roasts the account that owns the GitHub token. There is no `--user` option and no
query that takes a username: everything starts from GitHub's `viewer`. You cannot point it at
someone else.

Counts (commits, streaks, hours, languages) include everything your token can see. Commit
messages and repository names are taken from **public repos only** unless you pass
`--include-private`, because they are sent to the LLM and shown in a video you will post;
private repos appear as "private repo".

## Quickstart

```bash
pip install -e .
cp .env.example .env        # add LLM_API_KEY and MAGIC_HOUR_API_KEY; GITHUB_TOKEN is optional if `gh` is logged in
roastmygithub doctor
```

Then, in order of cost:

```bash
roastmygithub run --persona professor --dry-run   # stats, highlights and the script; no Magic Hour calls
roastmygithub run --persona professor --preview   # the whole video with a silent track: free
roastmygithub run --persona professor             # with the voice: ~85 credits, asks first
```

`--script out/script_professor.json` reuses a script (edit it first if you like) instead of
asking the LLM again. Voice lines are cached, so a rerun of the same script is free.
`--title "GitHub Wrapped 2026"` changes the title on every frame.

Narrators: `professor` (a stern, disappointed academic), `hype` (an over-the-top sports
commentator), `senior` (a tired senior engineer reviewing your year).

## Cost

The only paid step is the voice: Magic Hour's AI Voice Cloner at 0.1 credit per character,
about 85 credits for a 60-second script ($0.08–$0.21 depending on plan). The script costs
about $0.04 with Claude Opus 5.5. The animation is drawn locally with Pillow and ffmpeg.

## Voices

No narrator is a real person. Each voice is cloned by Magic Hour's AI Voice Cloner from a short
bundled sample that was itself synthesised with [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M)
(Apache-2.0). `tools/make_voice_samples.py` rebuilds them. `--voice-sample` swaps in your own:
only use a voice you have the right to use.

## License

MIT
