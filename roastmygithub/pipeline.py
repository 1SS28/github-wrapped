"""Pipeline: collect -> stats -> highlights -> script -> estimate -> voice -> scenes -> video.

Everything up to the estimate costs a few GitHub API calls and one small LLM request, and is
what `--dry-run` runs: the place to get the script right before any Magic Hour credits are
spent. The only paid step is the voice (Magic Hour AI Voice Cloner, ~0.1 credit a character);
lines are cached under `--out` by text and voice, so a rerun with the same script is free.
`--preview` swaps the voice for a silent track timed from the words, so the whole video can be
checked for nothing. The raw GitHub activity is cached per day under the cache directory,
outside the output folder, because it can contain private repository names.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from core import compose
from core.costs import CostLedger
from core.llm import LLM
from core.magichour import MagicHour, MagicHourError
from core.plans import PLANS, Plan, custom_plan, detect_plan
from roastmygithub import art as art_ops
from roastmygithub import cards as card_ops
from roastmygithub import github as github_ops
from roastmygithub import render as render_ops
from roastmygithub import voice as voice_ops
from roastmygithub import voices
from roastmygithub.config import Settings
from roastmygithub.estimate import CHARACTERS_PER_WORD, voice_credits
from roastmygithub.highlights import Highlight, pick
from roastmygithub.personas import PERSONAS
from roastmygithub.rank import compute_rank
from roastmygithub.script import HEATS, MIN_HIGHLIGHTS, WORDS_PER_SECOND, Script, build_prompt, system_prompt, target_words, write_script
from roastmygithub.stats import Stats, compute_stats, local_timezone

WINDOW_DAYS = 365  # contributionsCollection accepts at most one year


compose_errors = (compose.FFmpegError, ValueError, RuntimeError)


class PipelineError(RuntimeError):
    pass


class RunOptions(BaseModel):
    persona: str = "professor"
    out: Path = Path("out")
    dry_run: bool = False
    include_private: bool = False
    refresh: bool = False
    seconds: float = 60.0
    heat: str = "brutal"  # brutal (default) or gentle
    max_commits: int = 3000
    timezone: str | None = None
    show_prompt: bool = False
    preview: bool = False  # free: the whole video with a silent track instead of the voice
    script_file: Path | None = None  # use this script (e.g. an edited script_<persona>.json) instead of the LLM
    yes: bool = False  # do not ask before spending credits
    interactive: bool = False
    max_credits: int | None = None
    voice_sample: Path | None = None  # instead of the persona's bundled sample
    title: str = "GitHub Wrapped"  # top-right of every frame
    voice: str | None = None  # a Magic Hour voice name, "narrator", or None for the persona's default
    style: str = "wrapped"  # wrapped: Magic Hour illustrations under big type; data: charts drawn from the stats
    heroes: int = 2  # how many beats (the opener and the finale first) get an image-to-video clip


class Pipeline:
    def __init__(
        self,
        opts: RunOptions,
        settings: Settings,
        console: Console | None = None,
        *,
        github: github_ops.GitHub | None = None,
        llm: LLM | None = None,
        magichour: MagicHour | None = None,
    ):
        if opts.persona not in PERSONAS:
            raise PipelineError(f"unknown persona '{opts.persona}' (choose from {', '.join(PERSONAS)})")
        self.opts = opts
        self.settings = settings
        self.console = console or Console()
        self.persona = PERSONAS[opts.persona]
        try:
            self.voice = voices.check(opts.voice) if opts.voice else voices.check(self.persona.default_voice)
        except ValueError as exc:
            raise PipelineError(str(exc)) from exc
        self.ledger = CostLedger(opts.out / "ledger.jsonl")
        self._github = github
        self._llm = llm
        self._magichour = magichour
        self._plan: Plan | None = None

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        opts = self.opts
        opts.out.mkdir(parents=True, exist_ok=True)

        with self.ledger.stage("collect"):
            activity = self._collect()
        if opts.style not in ("wrapped", "data"):
            raise PipelineError(f"unknown style '{opts.style}' (wrapped or data)")
        if opts.heat not in HEATS:
            raise PipelineError(f"unknown heat '{opts.heat}' ({' or '.join(HEATS)})")
        with self.ledger.stage("stats"):
            tz = local_timezone(opts.timezone or self.settings.roast_timezone)
            stats = compute_stats(activity, include_private=opts.include_private, tz=tz)
            highlights = pick(stats)
        rank = compute_rank(stats)
        self._write("stats.json", stats.model_dump(mode="json"))
        self._write("highlights.json", [h.model_dump() for h in highlights])
        self._write("rank.json", rank.model_dump())
        self._show_stats(stats, activity)
        breakdown = ", ".join(f"{p.name} {p.points:g}/{p.max:g}" for p in rank.parts)
        self.console.print(f"[bold]Rank: {rank.tier or 'none'}[/] ({rank.score:g}/100: {breakdown}). {rank.tagline}")
        self._show_highlights(highlights)
        if len(highlights) < MIN_HIGHLIGHTS:
            raise PipelineError(
                f"only {len(highlights)} roastable facts in the last 12 months; that is not enough for a video yet"
            )

        with self.ledger.stage("script"):
            script = self._script(stats, highlights)
        estimate = self._show_estimate(script)
        video = None
        if not opts.dry_run:
            assert script is not None  # _script raises without an LLM outside --dry-run
            video = self._render(stats, script, highlights)

        report = {
            "login": stats.login,
            "persona": self.persona.key,
            "voice": self.voice,
            "rank": rank.model_dump(),
            "dry_run": opts.dry_run,
            "script": script.model_dump() if script else None,
            "estimate": estimate,
            "preview": opts.preview,
            "video": str(video) if video else None,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            **self.ledger.to_dict(),
        }
        self._write("report.json", report)
        if video and opts.preview:
            self.console.print(f"\n[green]Preview:[/] {video}\nSilent (no voice yet). Nothing was spent.")
        elif video:
            totals = report["totals"]
            self.console.print(
                f"\n[green]Video:[/] {video}\n"
                f"Spent {totals['magichour_credits']:,} Magic Hour credits (about ${totals['magichour_usd']:.2f}"
                f"{' on ' + self._plan.name if self._plan else ' at pack prices'})."
            )
        return report

    # -- Render -----------------------------------------------------------------

    def _hero_indexes(self, script: Script) -> set[int]:
        order = [0, len(script.beats) - 1] + list(range(1, len(script.beats) - 1))
        return set(dict.fromkeys(order[: max(0, self.opts.heroes)]))

    def _render(self, stats: Stats, script: Script, highlights: list[Highlight]) -> Path:
        """Art and voice (paid, or their free stand-ins), then the animated scenes and the final cut."""
        opts = self.opts
        workdir = opts.out / self.persona.key
        theme = card_ops.THEMES[self.persona.key]
        visuals = [beat.visual for beat in script.beats]
        try:
            if opts.preview:
                track = render_ops.silent_track(script.lines, workdir / "preview", words_per_second=WORDS_PER_SECOND)
                artworks = art_ops.generate(None, visuals, art_direction=self.persona.art, workdir=workdir / "art", heroes=self._hero_indexes(script)) if opts.style == "wrapped" else []
            else:
                track, artworks = self._magic_hour_stages(script)
            with self.ledger.stage("compose"), self.console.status("Animating your year…"):
                by_id = {h.id: h for h in highlights}
                beats = []
                for n, beat in enumerate(script.beats):
                    work = artworks[n] if n < len(artworks) else None
                    beats.append(render_ops.Beat(
                        highlight=by_id[beat.stat_id], tone=beat.tone,
                        art=work.image if work and not work.fallback else None, clip=work.video if work else None,
                    ))
                end_card = card_ops.render_end_card(
                    stats, script, sorted((b.highlight for b in beats), key=lambda h: -h.score), workdir / "end.png",
                    theme=theme, persona_title=self.persona.title, repo_url=self.settings.roast_repo_url,
                )
                name = f"roast_{stats.login}_{self.persona.key}_{voices.slug(self.voice)}{'_preview' if opts.preview else ''}.mp4"
                return render_ops.render_video(
                    stats=stats, beats=beats, track=track, end_card=end_card, dest=opts.out / name, theme=theme,
                    narrator=self._narrator_label(), title=opts.title, style=opts.style,
                )
        except (MagicHourError, *compose_errors) as exc:
            raise PipelineError(str(exc)) from exc

    def _narrator_label(self) -> str:
        return self.persona.title if self.voice == voices.ORIGINAL else f"{self.persona.title} · voice of {self.voice}"

    def _magic_hour_stages(self, script: Script) -> tuple[voice_ops.VoiceTrack, list[art_ops.Artwork]]:
        """Illustrations and the voice, on one Magic Hour client, after one yes."""
        opts = self.opts
        sample = opts.voice_sample or self.persona.voice_sample
        if self.voice == voices.ORIGINAL and not sample.exists():
            hint = "check the path" if opts.voice_sample else "pass --voice-sample, or build it with tools/make_voice_samples.py"
            raise PipelineError(f"no voice sample for {self.persona.title} at {sample}: {hint}")
        workdir = opts.out / self.persona.key
        mh = self._magichour
        if mh is None:
            if not self.settings.magic_hour_api_key:
                raise PipelineError("MAGIC_HOUR_API_KEY is needed for the voice (or use --preview / --dry-run)")
            mh = MagicHour(self.settings.magic_hour_api_key, ledger=self.ledger)
        else:
            mh.ledger = self.ledger
        try:
            heroes = self._hero_indexes(script) if opts.style == "wrapped" else set()
            self._confirm_spend(script, sample, workdir, mh, heroes)
            artworks: list[art_ops.Artwork] = []
            if opts.style == "wrapped":
                with self.ledger.stage("art"), self.console.status("Magic Hour is illustrating each beat…"):
                    artworks = art_ops.generate(mh, [b.visual for b in script.beats], art_direction=self.persona.art, workdir=workdir / "art", heroes=heroes)
                drawn = sum(1 for a in artworks if not a.fallback)
                redrawn = sum(a.faces_found for a in artworks)
                note = f"; {redrawn} redrawn because a face appeared" if redrawn else ""
                self.console.print(f"Art: {drawn} of {len(artworks)} beats illustrated, {sum(1 for a in artworks if a.video)} animated{note}.")
            with self.ledger.stage("voice"), self.console.status(f"Recording the {self.voice if self.voice != voices.ORIGINAL else 'narrator'} voice, one line per beat…"):
                track = voice_ops.synthesize(mh, script.lines, sample, workdir / "voice", voice_name=self.voice)
            self._write(f"{self.persona.key}/voice.json", track.model_dump(mode="json"))
            self.console.print(f"Voice: {track.duration:.1f} s in {len(track.lines)} lines.")
            return track, artworks
        finally:
            if not self._magichour:
                mh.close()
            if self._plan and self._plan.credits_per_usd:
                self.ledger.credits_per_usd = self._plan.credits_per_usd

    def _confirm_spend(self, script: Script, sample: Path, workdir: Path, mh: MagicHour, heroes: set[int]) -> None:
        """Say what is about to be spent (cached work is free) and get a yes before spending it."""
        opts = self.opts
        new_lines = voice_ops.pending(script.lines, sample, workdir / "voice", voice_name=self.voice)
        voice = voice_credits(new_lines)
        images = clips = 0
        if opts.style == "wrapped":
            images, clips = art_ops.pending([b.visual for b in script.beats], art_direction=self.persona.art, workdir=workdir / "art", heroes=heroes)
        pictures = images * art_ops.IMAGE_CREDITS + clips * art_ops.HERO_SECONDS * art_ops.VIDEO_CREDITS_PER_SECOND
        total = voice + pictures
        if not total:
            return
        try:
            balance = mh.account().get("credits")
        except MagicHourError:
            balance = None
        have = f" You have {balance:,}." if balance is not None else ""
        parts = [f"{voice} for {len(new_lines)} voice line(s)"]
        if images:
            parts.append(f"{images * art_ops.IMAGE_CREDITS} for {images} illustration(s)")
        if clips:
            parts.append(f"{clips * art_ops.HERO_SECONDS * art_ops.VIDEO_CREDITS_PER_SECOND} for {clips} animated clip(s)")
        self.console.print(f"\nAbout to spend {total:,} Magic Hour credits: {', '.join(parts)}.{have}")
        if opts.max_credits is not None and total > opts.max_credits:
            raise PipelineError(f"that is over --max-credits {opts.max_credits:,}")
        if balance is not None and balance < total:
            raise PipelineError(f"not enough credits: {total:,} needed, {balance:,} available")
        if opts.yes:
            return
        if not opts.interactive:
            raise PipelineError("pass --yes to spend credits without being asked")
        if not Confirm.ask("Go ahead?", default=True, console=self.console):
            raise PipelineError("stopped before spending anything")

    # -- Collect ----------------------------------------------------------------

    def _collect(self) -> dict[str, Any]:
        opts = self.opts
        gh = self._github or github_ops.GitHub(github_ops.resolve_token(self.settings.github_token))
        try:
            login = gh.whoami()  # the account is whoever owns the token; there is no way to pass another
            until = datetime.now(timezone.utc)
            cache = self.settings.cache_dir / f"activity-{login}-{until:%Y-%m-%d}.json"
            if cache.exists() and not opts.refresh:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                enough = not cached.get("commits_truncated") or cached.get("max_commits", 0) >= opts.max_commits
                if cached.get("schema") == github_ops.SCHEMA_VERSION and enough:
                    self.console.print(f"[dim]Using today's cached GitHub activity for @{login} (--refresh to fetch again).[/]")
                    return cached
            with self.console.status(f"Reading @{login}'s last 12 months from GitHub…") as status:
                activity = github_ops.collect(
                    gh,
                    since=until - timedelta(days=WINDOW_DAYS),
                    until=until,
                    max_commits=opts.max_commits,
                    on_progress=lambda step: status.update(f"Reading @{login}'s last 12 months from GitHub: {step}"),
                )
        finally:
            if not self._github:
                gh.close()
        activity["max_commits"] = opts.max_commits
        # Owner-only: the cache holds private repository names and commit messages.
        fd = os.open(cache, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(activity, fh)
        return activity

    def _write(self, name: str, data: Any) -> Path:
        path = self.opts.out / name
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        return path

    # -- Script -----------------------------------------------------------------

    def _script(self, stats: Stats, highlights: list[Highlight]) -> Script | None:
        opts, settings = self.opts, self.settings
        if opts.show_prompt:
            self.console.print(Panel(system_prompt(self.persona.style, opts.heat, self.voice), title="system prompt", border_style="dim"))
            self.console.print(Panel(build_prompt(stats, highlights, seconds=opts.seconds, heat=opts.heat), title="prompt", border_style="dim"))
        if opts.script_file:
            script = self._load_script(opts.script_file, highlights)
            self._show_script(script, highlights)
            return script
        llm = self._llm
        if llm is None:
            if not (settings.llm_api_key and settings.llm_model):
                if not opts.dry_run:
                    raise PipelineError("LLM_API_KEY and LLM_MODEL are needed to write the script")
                self.console.print(
                    "\n[yellow]No script written:[/] set LLM_API_KEY and LLM_MODEL in .env and "
                    f"{self.persona.title} will write one (about a cent). --show-prompt prints what would be sent."
                )
                return None
            llm = LLM(
                settings.llm_model,
                settings.llm_api_key,
                provider=settings.llm_provider,
                effort=settings.llm_effort,
                usd_per_mtok_in=settings.llm_usd_per_mtok_in,
                usd_per_mtok_out=settings.llm_usd_per_mtok_out,
                base_url=settings.llm_base_url,
            )
        with self.console.status(f"{self.persona.title} is reading your commit history…"):
            script = write_script(stats, highlights, self.persona, llm, seconds=opts.seconds, heat=opts.heat, voice=self.voice, ledger=self.ledger)
        self._write(f"script_{self.persona.key}.json", script.model_dump())
        self._show_script(script, highlights)
        return script

    def _load_script(self, path: Path, highlights: list[Highlight]) -> Script:
        """A script from disk: one the LLM wrote earlier and you edited, or one written by hand."""
        try:
            script = Script.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PipelineError(f"could not read the script at {path}: {exc}") from exc
        known = {h.id for h in highlights}
        unknown = [beat.stat_id for beat in script.beats if beat.stat_id not in known]
        if unknown or not script.beats:
            raise PipelineError(
                f"{path} refers to stats that are not in today's highlights: {', '.join(unknown) or 'no beats'}. "
                f"Available: {', '.join(sorted(known))}"
            )
        for stat_id, then, now in script.stale_cards(highlights):
            self.console.print(
                f"[yellow]{path.name} was written when {stat_id} was {then}; today it is {now}. "
                "The card shows today's figure, so the line may no longer match.[/]"
            )
        return script.model_copy(update={"persona": self.persona.key})

    # -- Output -----------------------------------------------------------------

    def _show_stats(self, s: Stats, activity: dict[str, Any]) -> None:
        def pct(share: float | None) -> str:
            return "–" if share is None else f"{round(share * 100)}%"

        def hour(h: int | None) -> str:
            return "–" if h is None else f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}"

        def span(sp: Any) -> str:
            return f"{sp.days} days ({sp.start:%b %d} – {sp.end:%b %d})" if sp.days and sp.start and sp.end else "–"

        table = Table(title=f"@{s.login}: {s.since:%b %d, %Y} – {s.until:%b %d, %Y}", show_header=False, title_justify="left")
        table.add_column(style="bold")
        table.add_column()
        private = f", {s.private_contributions} of them private" if s.private_contributions else ""
        table.add_row("Commits", f"{s.commits:,} across {s.repos_committed_to} repos ({s.total_contributions:,} contributions{private})")
        table.add_row("Active days", f"{s.active_days} of {s.days_in_window}")
        table.add_row("Longest streak", span(s.longest_streak) + (f"; current: {s.current_streak} days" if s.current_streak else ""))
        table.add_row("Longest silence", span(s.longest_gap))
        if s.busiest_day:
            table.add_row("Busiest day", f"{s.busiest_day.date:%A, %b %d}: {s.busiest_day.count} contributions")
        table.add_row("Busiest weekday", f"{s.busiest_weekday or '–'}; weekends {pct(s.weekend_share)}")
        sampled = f"{s.commits_sampled} commits analysed{' (capped by --max-commits)' if s.commits_truncated else ''}"
        table.add_row("Clock", f"peak {hour(s.busiest_hour)}; after midnight {pct(s.after_midnight_share)}; {sampled}; times in {s.clock}")
        table.add_row("Languages", ", ".join(f"{lang.name} {pct(lang.share)}" for lang in s.languages[:5]) or "–")
        table.add_row("Top repos", ", ".join(f"{r.name} ({r.commits})" for r in s.top_repos[:4]) or "–")
        table.add_row("Lines", f"+{s.lines_added:,} / −{s.lines_deleted:,}")
        table.add_row("Pull requests", f"{s.prs_opened} opened, {s.prs_merged} merged, {s.pr_reviews} reviews given, {s.issues_opened} issues opened")
        table.add_row("Stars received", f"{s.stars_received:,}{'+' if s.stars_capped else ''} ({s.stars_all_time:,} all time)")
        table.add_row("New repos", f"{s.repos_created} started, {s.repos_abandoned} abandoned within two weeks")
        scope = "all repos" if s.text_scope == "all" else "public repos only; --include-private adds the rest"
        words = ", ".join(f"{w.word} ({w.count})" for w in s.top_words[:8]) or "–"
        table.add_row("Commit messages", f"{s.messages_analyzed} analysed ({scope})\nTop words: {words}")
        if s.shortest_message:
            table.add_row("Shortest message", f"“{s.shortest_message.text}”")
        if s.most_repeated_message:
            table.add_row("Most repeated", f"“{s.most_repeated_message.text}” × {s.most_repeated_message.count}")
        self.console.print(table)
        for warning in activity.get("warnings") or []:
            self.console.print(f"[yellow]GitHub:[/] {warning}")

    def _show_highlights(self, highlights: list[Highlight]) -> None:
        table = Table(title="Highlights (what the script is written from)", title_justify="left")
        for column, justify in (("id", "left"), ("On screen", "left"), ("Fact", "left"), ("Kind", "left"), ("Score", "right")):
            table.add_column(column, justify=justify)
        for h in highlights:
            table.add_row(h.id, f"[bold]{h.value}[/]\n{h.label}", h.fact, h.kind, f"{h.score:.2f}")
        self.console.print(table)

    def _show_script(self, script: Script, highlights: list[Highlight]) -> None:
        by_id = {h.id: h for h in highlights}
        lines = []
        for n, beat in enumerate(script.beats, start=1):
            card = by_id[beat.stat_id]
            colour = "green" if beat.tone == "compliment" else "red"
            lines.append(f"[dim]{n}. [{colour}]{beat.tone}[/] · {card.value} · {card.label}[/]\n{beat.line}")
        lines.append(f"[dim]Sign-off[/]\n{script.sign_off}")
        usd = self.ledger.usd_for("llm")
        cost = f" · LLM ${usd:.3f}" if usd is not None else ""
        self.console.print(
            Panel(
                "\n\n".join(lines),
                title=f"{self.persona.title}: “{script.verdict}”",
                subtitle=f"{script.words} words · about {script.seconds:.0f} s{cost}",
                title_align="left",
            )
        )
        target = target_words(self.opts.seconds)
        if abs(script.words - target) > target * 0.15:
            self.console.print(f"[yellow]The script is {script.words} words; the target for {self.opts.seconds:.0f} s is {target}.[/]")

    def _show_estimate(self, script: Script | None) -> dict[str, Any]:
        """Voice (0.1 credit a character) plus, in the wrapped style, one illustration per beat and a clip per hero."""
        if script:
            voice, beats, basis = voice_credits(script.lines), len(script.beats), "this script"
        else:
            words = target_words(self.opts.seconds)
            voice, beats, basis = voice_credits(["x" * round(words * CHARACTERS_PER_WORD)]), 6, f"a {self.opts.seconds:.0f} s script"
        heroes = min(max(self.opts.heroes, 0), beats) if self.opts.style == "wrapped" else 0
        pictures = art_ops.estimate_credits(beats, heroes=heroes) if self.opts.style == "wrapped" else 0
        credits = voice + pictures
        plan = self._plan = self._your_plan()
        rate = plan.credits_per_usd if plan and plan.credits_per_usd else PLANS["pack"].credits_per_usd
        where = f"on {plan.name}" if plan else "at credit-pack prices"
        detail = f"{voice} voice + {beats * art_ops.IMAGE_CREDITS} illustrations + {heroes * art_ops.HERO_SECONDS * art_ops.VIDEO_CREDITS_PER_SECOND} animated clips" if pictures else f"{voice} for the voice"
        self.console.print(f"Rendering {basis} costs about {credits:,} Magic Hour credits ({detail}), about ${credits / rate:.2f} {where}. Cached work is free.")
        return {"voice_credits": voice, "art_credits": pictures, "credits": credits, "usd": round(credits / rate, 4)}

    def _your_plan(self) -> Plan | None:
        settings = self.settings
        if settings.magic_hour_credits_per_usd:
            return custom_plan(settings.magic_hour_credits_per_usd)
        if settings.magic_hour_plan != "auto":
            return PLANS.get(settings.magic_hour_plan)
        if not settings.magic_hour_api_key and not self._magichour:
            return None
        try:
            if self._magichour:
                plan = detect_plan(self._magichour.account())
            else:
                with MagicHour(settings.magic_hour_api_key) as mh:
                    plan = detect_plan(mh.account())
        except MagicHourError:
            return None
        return plan if plan and plan.credits_per_usd else None
