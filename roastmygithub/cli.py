"""roastmygithub command line.

There is deliberately no --user option anywhere: the account is whoever owns the GitHub token.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import sys

import httpx
import typer
from rich.console import Console

from roastmygithub.config import Settings

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Turn your own last 12 months on GitHub into a roast video with Magic Hour.")
console = Console()


class PersonaChoice(str, Enum):
    professor = "professor"
    hype = "hype"
    senior = "senior"


@app.command()
def run(
    persona: PersonaChoice = typer.Option(PersonaChoice.professor, "--persona", help="professor (disappointed academic), hype (sports commentator) or senior (tired senior engineer)."),
    out: Path = typer.Option(Path("out"), "--out", help="Output directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Stats, highlights and script only: no Magic Hour calls."),
    preview: bool = typer.Option(False, "--preview", help="Render the whole video with a silent track instead of the voice. Free."),
    script: Optional[Path] = typer.Option(None, "--script", help="Use this script JSON (e.g. an edited out/script_professor.json) instead of asking the LLM."),
    seconds: float = typer.Option(60, "--seconds", min=20, max=90, help="Target length of the script."),
    gentle: bool = typer.Option(False, "--gentle", help="Pull the punches: half the beats are compliments. Default is brutal."),
    include_private: bool = typer.Option(False, "--include-private", help="Also quote commit messages and repo names from private repos (counts always include them)."),
    refresh: bool = typer.Option(False, "--refresh", help="Fetch from GitHub again instead of using today's cache."),
    max_commits: int = typer.Option(3000, "--max-commits", min=100, max=20000, help="Most commits to read for messages and commit times."),
    timezone: Optional[str] = typer.Option(None, "--timezone", help="Timezone for commit times without an offset, e.g. America/Toronto (default: this machine's)."),
    show_prompt: bool = typer.Option(False, "--show-prompt", help="Print the prompt sent to the LLM."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask before spending Magic Hour credits."),
    max_credits: Optional[int] = typer.Option(None, "--max-credits", min=0, help="Refuse to start if the render would spend more than this."),
    voice: Optional[str] = typer.Option(None, "--voice", help='Who reads it: a Magic Hour voice such as "Elon Musk" (see `roastmygithub voices`), or "narrator" for the persona\'s own cloned voice. Default: the persona\'s pick.'),
    voice_sample: Optional[Path] = typer.Option(None, "--voice-sample", help="With --voice narrator: an audio sample to clone instead of the bundled one. Only use a voice you have the right to use."),
    title: str = typer.Option("GitHub Wrapped", "--title", help='Shown at the top of every frame, e.g. "GitHub Wrapped 2026".'),
    style: str = typer.Option("wrapped", "--style", help="wrapped: a Magic Hour illustration per beat under big type (10 credits each). data: charts drawn from your stats, no image credits."),
    heroes: int = typer.Option(2, "--heroes", min=0, max=6, help="Beats that get a 4 s image-to-video clip (opener and finale first), 96 credits each."),
) -> None:
    """Roast the GitHub account your token belongs to."""
    from core.llm import LLMError
    from roastmygithub.github import GitHubError
    from roastmygithub.pipeline import Pipeline, PipelineError, RunOptions

    opts = RunOptions(
        persona=persona.value,
        out=out,
        dry_run=dry_run,
        preview=preview,
        script_file=script,
        seconds=seconds,
        heat="gentle" if gentle else "brutal",
        include_private=include_private,
        refresh=refresh,
        max_commits=max_commits,
        timezone=timezone,
        show_prompt=show_prompt,
        yes=yes,
        interactive=sys.stdin.isatty(),
        max_credits=max_credits,
        voice=voice,
        voice_sample=voice_sample,
        title=title,
        style=style,
        heroes=heroes,
    )
    try:
        report = Pipeline(opts, Settings(), console).run()
    except (PipelineError, GitHubError, LLMError, ValueError, httpx.HTTPError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        raise typer.Exit(2) from exc
    written = ["stats.json", "highlights.json", *([f"script_{persona.value}.json"] if report["script"] and not script else []), "report.json"]
    console.print(f"\nWrote {', '.join(written)} to {out}/")


@app.command()
def voices(all: bool = typer.Option(False, "--all", help="Every voice the API accepts, not just the popular ones.")) -> None:
    """Voices that can read the roast (Magic Hour AI Voice Generator), popular ones first."""
    from roastmygithub import voices as v
    from roastmygithub.personas import PERSONAS

    console.print("narrator  (the persona's own cloned voice)")
    for name in (sorted(v.ALL) if all else v.POPULAR):
        console.print(name)
    console.print("\nDefaults: " + ", ".join(f"{p.key} → {p.default_voice}" for p in PERSONAS.values()) + '. Pick with --voice "Name".')


@app.command()
def personas() -> None:
    """The narrators, and whether their bundled voice samples are in place."""
    from rich.table import Table

    from roastmygithub.personas import PERSONAS

    table = Table(title="Personas", title_justify="left")
    for column in ("key", "Narrator", "Voice sample", "Sounds like"):
        table.add_column(column)
    for p in PERSONAS.values():
        voice = f"[green]✓[/] {p.voice_sample.name} ({p.kokoro_voice})" if p.voice_sample.exists() else "[red]missing[/] (tools/make_voice_samples.py)"
        table.add_row(p.key, p.title, voice, p.style.split(": ", 1)[1].split(".")[0].lower())
    console.print(table)
    console.print("Override per run with --voice-sample.")


@app.command()
def doctor() -> None:
    """Check the GitHub token, LLM settings, Magic Hour key and ffmpeg."""
    from core import compose
    from core.magichour import MagicHour, MagicHourError
    from core.plans import detect_plan
    from roastmygithub.github import GitHub, GitHubError, resolve_token

    settings = Settings()
    ok = True

    def line(good: bool, label: str, detail: str, required: bool = True) -> None:
        nonlocal ok
        ok &= good or not required
        mark = "[green]✓[/]" if good else "[red]✗[/]" if required else "[yellow]–[/]"
        console.print(f"{mark} {label}: {detail}")

    try:
        with GitHub(resolve_token(settings.github_token)) as gh:
            login = gh.whoami()
        source = "GITHUB_TOKEN" if settings.github_token else "gh auth token"
        line(True, "GitHub", f"@{login} (from {source}); this is the only account the tool can roast")
    except GitHubError as exc:
        line(False, "GitHub", str(exc))
    line(bool(settings.llm_api_key and settings.llm_model), "LLM", f"model={settings.llm_model or 'missing'}, key {'set' if settings.llm_api_key else 'missing'}")
    if settings.magic_hour_api_key:
        try:
            with MagicHour(settings.magic_hour_api_key) as mh:
                account = mh.account()
            plan = detect_plan(account)
            rate = f", {plan.credits_per_usd:,.0f} credits/$" if plan and plan.credits_per_usd else ""
            line(True, "MAGIC_HOUR_API_KEY", f"{plan.name if plan else account.get('tier', '?')}{rate}, {account.get('credits', 0):,} credits available")
        except MagicHourError as exc:
            line(False, "MAGIC_HOUR_API_KEY", str(exc))
    else:
        line(False, "MAGIC_HOUR_API_KEY", "missing (only needed to render; --dry-run works without it)", required=False)
    try:
        binary = compose.ffmpeg_bin()
        captions = compose.supports_captions()
        line(captions, "ffmpeg", binary + ("" if captions else " (no libass: install ffmpeg-full or set FFMPEG_BIN)"), required=False)
    except compose.FFmpegError as exc:
        line(False, "ffmpeg", str(exc), required=False)
    from roastmygithub.personas import PERSONAS

    missing = [p.key for p in PERSONAS.values() if not p.voice_sample.exists()]
    line(not missing, "Persona assets", "all bundled" if not missing else f"incomplete for {', '.join(missing)} (see `roastmygithub personas`)", required=False)
    console.print(f"Cache: {settings.cache_dir}")
    if not ok:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
