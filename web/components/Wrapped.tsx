"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  PERSONAS,
  getBalance,
  signInUrl,
  TIERS,
  getWrap,
  readingSeconds,
  startMagic,
  startVideo,
  waitForJob,
  type Assets,
  type DayCount,
  type Highlight,
  type Job,
  type Rank,
  type Wrap,
} from "@/lib/api";
import { BRAND, SITE_URL } from "@/lib/brand";

const END = -1; // the closing card
const RANK = -2; // the rank reveal, between the last beat and the closing card

const TIER_COLOURS: Record<string, string> = {
  F: "#8b949e", E: "#8b949e", D: "#c9d1d9", C: "#3fb950", B: "#58a6ff", A: "#a371f7", S: "#d29922", SS: "#f0883e", SSS: "#f85149", Unranked: "#e6edf3",
};

/** The counting animation keeps the figure's own format: "1,234" counts in thousands, "48%" keeps its sign. */
function counting(value: string, k: number): string {
  const match = /^([^\d]*)([\d,]+(?:\.\d+)?)(.*)$/.exec(value);
  if (!match || k >= 1) return value;
  const [, prefix, number, suffix] = match;
  const target = parseFloat(number.replace(/,/g, ""));
  const decimals = number.includes(".") ? number.split(".")[1].length : 0;
  const current = (target * k).toFixed(decimals);
  const text = number.includes(",") ? Number(current).toLocaleString("en-US", { minimumFractionDigits: decimals }) : current;
  return `${prefix}${text}${suffix}`;
}

function CountUp({ value, duration = 900 }: { value: string; duration?: number }) {
  const [shown, setShown] = useState(() => counting(value, 0));
  useEffect(() => {
    let frame = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const k = Math.min(1, (now - started) / duration);
      setShown(counting(value, 1 - Math.pow(1 - k, 3)));
      if (k < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return <>{shown}</>;
}

function span(wrap: Wrap): string {
  const f = (iso: string) => new Date(iso).toLocaleString("en", { month: "short", year: "numeric" });
  return `${f(wrap.since)} – ${f(wrap.until)}`;
}

function tierSentence(rank: Rank): string {
  const score = Math.round(rank.score);
  if (!rank.tier) return "No rank yet. Not enough activity to judge.";
  if (rank.tier === "Unranked") return `Unranked. ${score} out of 100; the scale stops at SSS.`;
  const next = rank.next_tier && rank.points_to_next != null ? ` ${Math.ceil(rank.points_to_next)} short of ${rank.next_tier}.` : "";
  return `Tier ${rank.tier}. ${score} out of 100.${next}`;
}

/** The year as GitHub draws it, in two half-year strips so the cells read as a picture. */
export function Calendar({ days, className = "", animate = true }: { days: DayCount[]; className?: string; animate?: boolean }) {
  const max = Math.max(1, ...days.map((d) => d.count));
  const first = new Date((days[0]?.date ?? "2026-01-04") + "T00:00:00Z");
  const padded: (DayCount | null)[] = [...Array<null>(first.getUTCDay()).fill(null), ...days];
  const weeks: (DayCount | null)[][] = [];
  for (let i = 0; i < padded.length; i += 7) weeks.push(padded.slice(i, i + 7));
  const half = Math.ceil(weeks.length / 2);
  const strips = [weeks.slice(0, half), weeks.slice(half)];
  const level = (count: number) => (count ? `var(--lv${Math.min(4, 1 + Math.floor((3 * count) / max))})` : "var(--lv0)");
  let n = 0;
  return (
    <div className={`flex flex-col gap-3 ${className}`} aria-hidden>
      {strips.map((strip, s) => (
        <div key={s} className="flex gap-[3px]">
          {strip.map((week, w) => (
            <div key={w} className="flex flex-col gap-[3px] flex-1">
              {Array.from({ length: 7 }).map((_, d) => {
                const day = week[d];
                const i = n++;
                return (
                  <div
                    key={d}
                    className="aspect-square rounded-[2px]"
                    style={{
                      background: day ? level(day.count) : "transparent",
                      animation: animate ? `pop 0.25s ${Math.min(1.1, i * 0.0025)}s both` : undefined,
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/** A phone turned on its side: too short for a portrait story, so the player asks to be turned back and waits. */
const SIDEWAYS = "(orientation: landscape) and (max-height: 500px) and (pointer: coarse)";

function useSideways(): boolean {
  const [sideways, setSideways] = useState(false);
  useEffect(() => {
    const query = window.matchMedia(SIDEWAYS);
    const update = () => setSideways(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return sideways;
}

function Header({ wrap, index, progress, beats }: { wrap: Wrap; index: number; progress: number; beats: number }) {
  return (
    <div className="absolute top-0 inset-x-0 z-10 px-5 pt-[max(0.75rem,env(safe-area-inset-top))]">
      <div className="flex gap-1">
        {Array.from({ length: beats }).map((_, i) => (
          <div key={i} className="h-[3px] flex-1 bg-white/15 overflow-hidden">
            <div className="h-full bg-white/90" style={{ width: `${index === END || index === RANK || i < index ? 100 : i === index ? progress * 100 : 0}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between font-mono text-[11px] text-dim">
        <span>
          {wrap.login} / {span(wrap)}
        </span>
        {/* Above the tap zones, so it closes the story instead of skipping a beat */}
        <Link href="/" aria-label="Close and wrap another username" className="-my-2 -mr-2 p-2 text-lg leading-none text-foreground/80 hover:text-foreground">
          ✕
        </Link>
      </div>
    </div>
  );
}

function Scene({ wrap, index, highlight, tone }: { wrap: Wrap; index: number; highlight: Highlight; tone: string }) {
  const art = wrap.assets?.art?.[index] ?? null;
  const clip = wrap.assets?.clips?.[index] ?? null;
  return (
    <div className="absolute inset-0 overflow-hidden" key={index}>
      {clip ? (
        <video src={clip} className="absolute inset-0 h-full w-full object-cover" autoPlay muted loop playsInline />
      ) : art ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={art} alt="" className="kenburns absolute inset-0 h-full w-full object-cover" />
      ) : (
        <Calendar days={wrap.stats.calendar} className="absolute inset-x-5 top-[16%]" />
      )}
      {art || clip ? <div className="scrim absolute inset-0" /> : null}
      <div className="absolute inset-x-0 bottom-[26%] px-5">
        <div className={`font-mono text-xs ${tone === "compliment" ? "text-props" : "text-roast"}`}>{tone === "compliment" ? "props" : "roast"}</div>
        <div className="rise mt-1 font-mono text-[clamp(3.6rem,19vw,6.5rem)] leading-none tracking-tight break-words">
          <CountUp value={highlight.value} />
        </div>
        <div className="rise mt-2 text-xl leading-snug text-foreground/90 max-w-[22ch]" style={{ animationDelay: "0.1s" }}>
          {highlight.label}
        </div>
      </div>
    </div>
  );
}

/** The rank, revealed like a verdict: a drum of tiers, a slam, then the breakdown. Not in the video on purpose. */
function RankReveal({ rank, onNext }: { rank: Rank; onNext: () => void }) {
  const [stage, setStage] = useState<"drum" | "slam" | "detail">("drum");
  const [spin, setSpin] = useState(0);
  useEffect(() => {
    const drum = window.setInterval(() => setSpin((n) => n + 1), 80);
    const slam = window.setTimeout(() => {
      window.clearInterval(drum);
      setStage("slam");
    }, 1700);
    const detail = window.setTimeout(() => setStage("detail"), 2500);
    return () => {
      window.clearInterval(drum);
      window.clearTimeout(slam);
      window.clearTimeout(detail);
    };
  }, []);
  const tier = rank.tier;
  const colour = tier ? TIER_COLOURS[tier] : "#8b949e";
  const big = tier === "Unranked" ? "∞" : tier ?? "—";
  const pieces = useMemo(() => Array.from({ length: 36 }, (_, i) => ({ left: (i * 37) % 100, delay: (i % 9) * 0.12, duration: 2.2 + (i % 5) * 0.3, hue: (i * 47) % 360 })), []);
  // The letter and sentence scale with the screen's height, the breakdown scrolls if it still does not fit,
  // and the way out stays pinned to the bottom so short phones can always reach it.
  return (
    <div className="absolute inset-0 flex flex-col overflow-hidden" style={{ "--tier": colour } as React.CSSProperties}>
      {stage !== "drum" && tier && TIERS.indexOf(tier) >= 6
        ? pieces.map((c, i) => (
            <span key={i} className="confetti" style={{ left: `${c.left}%`, animationDelay: `${c.delay}s`, animationDuration: `${c.duration}s`, background: `hsl(${c.hue} 90% 60%)` }} />
          ))
        : null}
      <div className="flex-1 min-h-0 overflow-y-auto px-5 pt-[clamp(3.5rem,9dvh,5rem)]">
        <div className="font-mono text-xs text-dim">rank for the year</div>
        {stage === "drum" ? (
          <div className="mt-2 font-mono text-[clamp(4.5rem,17dvh,9rem)] leading-none text-dim/60">{TIERS[spin % (TIERS.length - 1)]}</div>
        ) : (
          <div className={`mt-2 font-mono text-[clamp(4.5rem,17dvh,9rem)] leading-none glow ${stage === "slam" ? "slam" : ""}`} style={{ color: colour }}>
            {big}
          </div>
        )}
        {stage !== "drum" ? (
          <p className={`mt-3 font-serif text-[clamp(1.5rem,4.4dvh,1.875rem)] leading-tight ${stage === "slam" ? "shake" : ""}`}>{tierSentence(rank)}</p>
        ) : null}
        {stage === "detail" ? (
          <div className="rise mt-4 pb-3">
            <p className="text-sm text-dim">{rank.tagline}</p>
            <ul className="mt-4 rule">
              {rank.parts.map((p) => (
                <li key={p.name} className="py-[clamp(0.375rem,1.2dvh,0.625rem)] border-b border-border">
                  <div className="flex justify-between text-sm">
                    <span>{p.name}</span>
                    <span className="font-mono text-dim">
                      {p.points} / {p.max}
                    </span>
                  </div>
                  <div className="mt-1.5 h-[3px] bg-white/10">
                    <div className="h-full" style={{ width: `${(100 * p.points) / p.max}%`, background: colour, transition: "width 0.8s ease-out" }} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      {stage === "detail" ? (
        <div className="rise px-5 pt-3 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
          <button onClick={onNext} className="btn w-full">
            The verdict →
          </button>
        </div>
      ) : null}
    </div>
  );
}

function EndCard({ wrap, shown, onMagic, onReplay, busy }: { wrap: Wrap; shown: Highlight[]; onMagic: () => void; onReplay: () => void; busy: boolean }) {
  const card = `/api/card/${encodeURIComponent(wrap.login)}?${new URLSearchParams({ persona: wrap.persona, voice: wrap.voice })}`;
  const shareUrl = typeof window !== "undefined" ? window.location.href : `https://${SITE_URL}/${wrap.login}`;
  const tier = wrap.rank.tier === "Unranked" ? "Unranked" : wrap.rank.tier ? `Tier ${wrap.rank.tier}` : null;
  const text = `${wrap.script.verdict}${tier ? ` — ${tier}` : ""}. My ${BRAND}:`;
  const tweet = `https://twitter.com/intent/tweet?${new URLSearchParams({ text, url: shareUrl })}`;
  // The card scrolls on short screens; the buttons sit outside the scroll so they are always on screen.
  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="flex-1 min-h-0 overflow-y-auto px-5 pt-16 pb-3">
        <Calendar days={wrap.stats.calendar} animate={false} className="max-w-[86%]" />
        <div className="mt-2 font-mono text-xs text-dim">
          {wrap.stats.total_contributions.toLocaleString("en")} contributions · {wrap.stats.active_days} active days
        </div>
        <h2 className="mt-5 font-serif font-bold text-[2.6rem] leading-[0.98] tracking-tight">{wrap.script.verdict}</h2>
        <p className="mt-2.5 text-[15px] font-semibold text-accent">{tierSentence(wrap.rank)}</p>
        <ul className="mt-4 rule">
          {shown.slice(0, 4).map((h) => (
            <li key={h.id} className="flex items-baseline gap-4 py-2 border-b border-border">
              <span className="font-mono text-2xl w-24 shrink-0">{h.value}</span>
              <span className="text-sm text-foreground/85">{h.label}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="px-5 pt-3 pb-[max(1.25rem,env(safe-area-inset-bottom))] flex flex-col gap-2 border-t border-border bg-background">
        {!wrap.magic_ready ? (
          <button onClick={onMagic} disabled={busy} className="btn btn-primary disabled:opacity-60">
            {busy ? "Magic Hour is drawing…" : "Illustrate and voice it with Magic Hour"}
          </button>
        ) : wrap.video ? (
          <a href={`${wrap.video}?download=1`} className="btn btn-primary">
            Download the video
          </a>
        ) : (
          <button onClick={onMagic} disabled={busy} className="btn btn-primary disabled:opacity-60">
            {busy ? "Rendering…" : "Make the video"}
          </button>
        )}
        <div className="flex gap-2">
          <a href={card} download={`github-wrapped-${wrap.login}.png`} className="btn flex-1">
            Save card
          </a>
          <a href={tweet} target="_blank" rel="noreferrer" className="btn flex-1">
            Post on X
          </a>
        </div>
        <div className="mt-1 flex justify-center gap-6 text-sm text-dim">
          <button type="button" onClick={onReplay} className="py-1 hover:text-foreground">
            ↺ Watch again
          </button>
          <Link href="/" className="py-1 hover:text-foreground">
            Try another username
          </Link>
        </div>
      </div>
    </div>
  );
}

function MagicHourPanel({ wrap, onClose, onDone }: { wrap: Wrap; onClose: () => void; onDone: (assets: Assets | null, video: string | null) => void }) {
  const [key, setKey] = useState("");
  const [withVideo, setWithVideo] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const beats = wrap.script.beats.length;
  const voiceCredits = Math.ceil(wrap.script.beats.reduce((n, b) => n + b.line.length, 0) / 10) + Math.ceil(wrap.script.sign_off.length / 10);
  const full = beats * 10 + 2 * 96 + voiceCredits; // illustrations, two animated clips, the voice
  const light = beats * 10 + voiceCredits; // illustrations and the voice, no animation
  const credits = wrap.magic_ready ? 0 : full;
  const who = wrap.voice === "narrator" ? "the narrator's own voice" : `the voice of ${wrap.voice}`;

  async function run() {
    setError(null);
    try {
      let assets: Assets | null = wrap.assets ?? null;
      if (!wrap.magic_ready) {
        setStatus("Checking your Magic Hour balance.");
        const { credits: balance } = await getBalance(key);
        let heroes = 2;
        if (balance != null && balance < full) {
          if (balance < light) {
            throw new Error(`Your Magic Hour account has ${balance} credits. This needs about ${light} (pictures and voice) or ${full} with animation.`);
          }
          heroes = 0;
          setStatus(`You have ${balance} credits, so this one skips the animated clips (about ${light} credits).`);
          await new Promise((resolve) => setTimeout(resolve, 1800));
        }
        setStatus("Drawing each beat and recording the lines. About a minute.");
        const job = await waitForJob(await startMagic(wrap.login, wrap.persona, wrap.voice, key, heroes), (j: Job) => setStatus(j.status === "running" ? "Magic Hour is working." : "Queued."));
        if (job.status !== "done") throw new Error(job.error ?? "Magic Hour failed");
        assets = job.result as unknown as Assets;
      }
      let video: string | null = wrap.video;
      if (withVideo && !video) {
        setStatus("Rendering the video. About a minute.");
        const job = await waitForJob(await startVideo(wrap.login, wrap.persona, wrap.voice, key));
        if (job.status !== "done") throw new Error(job.error ?? "the render failed");
        video = (job.result as { video: string }).video;
      }
      onDone(assets, video);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus(null);
    }
  }

  return (
    <div className="absolute inset-0 z-20 bg-black/80 flex items-end sm:items-center justify-center p-4" role="dialog" aria-modal>
      <div className="w-full max-w-md panel rounded-md p-6 text-sm">
        <h2 className="font-serif text-2xl font-bold">Finish it with Magic Hour</h2>
        <p className="mt-3 text-foreground/85 leading-relaxed">
          One illustration per beat, two of them animated, and the lines read in {who}. It runs on your own Magic Hour account,
          {wrap.magic_ready
            ? " and the pictures are already done, so the video itself costs nothing."
            : ` about ${credits} credits. A new Magic Hour account starts with 400, enough for one. With less, it skips the animation (about ${light}).`}
        </p>
        <p className="mt-3 text-dim leading-relaxed">
          Get a key at{" "}
          <a className="underline text-foreground" href="https://magichour.ai/developer?tab=api-keys" target="_blank" rel="noreferrer">
            magichour.ai/developer
          </a>
          . It is used for this run and not stored.
        </p>
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="Magic Hour API key"
          className="mt-4 w-full bg-background border border-border rounded-md px-3 py-2.5 font-mono outline-none focus:border-foreground"
          autoComplete="off"
        />
        <label className="mt-3 flex items-center gap-2 text-dim">
          <input type="checkbox" checked={withVideo} onChange={(e) => setWithVideo(e.target.checked)} /> also render the mp4
        </label>
        {status ? <p className="mt-3 text-accent">{status}</p> : null}
        {error ? <p className="mt-3 text-roast">{error}</p> : null}
        <div className="mt-5 flex gap-2">
          <button onClick={onClose} className="btn flex-1">
            Not now
          </button>
          <button onClick={run} disabled={!!status || key.length < 20} className="btn btn-primary flex-1 disabled:opacity-50">
            Go
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Wrapped({ login, persona, voice }: { login: string; persona: string; voice?: string }) {
  const [wrap, setWrap] = useState<Wrap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [progress, setProgress] = useState(0); // 0..1 within the current beat
  const [paused, setPaused] = useState(false);
  const [panel, setPanel] = useState(false);
  const [busy, setBusy] = useState(false);
  const sideways = useSideways();
  const halted = paused || sideways;
  const audio = useRef<HTMLAudioElement | null>(null);
  const frame = useRef<HTMLDivElement | null>(null);
  const timer = useRef<number | null>(null);
  const seekingUntil = useRef(0); // ignore stale timeupdate events right after a tap seeks the voice

  useEffect(() => {
    let alive = true;
    getWrap(login, persona, voice)
      .then((w) => alive && setWrap(w))
      .catch((e: unknown) => {
        if (!alive) return;
        setErrorCode(e instanceof ApiError ? (e.code ?? null) : null);
        setError(e instanceof ApiError ? e.message : "The server is not answering. Try again in a moment.");
      });
    return () => {
      alive = false;
    };
  }, [login, persona, voice]);

  const beats = useMemo(() => wrap?.script.beats ?? [], [wrap]);
  const byId = useMemo(() => new Map((wrap?.highlights ?? []).map((h) => [h.id, h])), [wrap]);
  const lines = wrap?.assets?.lines ?? null;

  const go = useCallback(
    (next: number) => {
      if (!wrap) return;
      const clamped = next >= beats.length ? RANK : Math.max(0, next);
      setIndex(clamped);
      setProgress(0);
      if (audio.current && lines) {
        if (clamped === RANK || clamped === END) audio.current.pause();
        else {
          seekingUntil.current = performance.now() + 500;
          audio.current.currentTime = lines[clamped].start;
          if (!paused) void audio.current.play().catch(() => undefined);
        }
      }
    },
    [wrap, beats.length, lines, paused],
  );

  // The clock: the voice when there is one, reading time when there is not.
  useEffect(() => {
    if (!wrap || index === END || index === RANK || halted) return;
    if (lines && audio.current) {
      const el = audio.current;
      const onTime = () => {
        if (performance.now() < seekingUntil.current) return;
        const t = el.currentTime;
        const current = lines.findIndex((l, i) => t < (lines[i + 1]?.start ?? Infinity));
        if (current >= 0 && current < beats.length && current !== index) {
          setIndex(current);
          setProgress(0);
        } else if (current >= beats.length) go(RANK);
        const line = lines[Math.min(index, lines.length - 1)];
        setProgress(Math.min(1, Math.max(0, (t - line.start) / Math.max(0.1, (lines[index + 1]?.start ?? el.duration) - line.start))));
      };
      const onEnded = () => go(RANK);
      el.addEventListener("timeupdate", onTime);
      el.addEventListener("ended", onEnded);
      void el.play().catch(() => undefined);
      return () => {
        el.removeEventListener("timeupdate", onTime);
        el.removeEventListener("ended", onEnded);
      };
    }
    const seconds = readingSeconds(beats[index].line) * 1000;
    const started = performance.now();
    const tick = () => {
      const k = (performance.now() - started) / seconds;
      setProgress(Math.min(1, k));
      if (k >= 1) go(index + 1);
      else timer.current = requestAnimationFrame(tick);
    };
    timer.current = requestAnimationFrame(tick);
    return () => {
      if (timer.current) cancelAnimationFrame(timer.current);
    };
  }, [wrap, index, halted, lines, beats, go]);

  // Leaving the page (the close button, Back) only hides it: Next keeps the route mounted so Back can restore
  // it, and hidden <audio>/<video> keep playing. Effects do run on hide and show, so stop the media on hide
  // and restart the clips on show; the clock above restarts the voice by itself.
  const media = useCallback((action: "play" | "pause") => {
    const videos = frame.current?.querySelectorAll("video") ?? [];
    if (action === "pause") {
      audio.current?.pause();
      videos.forEach((v) => v.pause());
    } else videos.forEach((v) => void v.play().catch(() => undefined));
  }, []);
  useLayoutEffect(() => {
    media("play");
    return () => media("pause");
  }, [media]);

  // The clock stops while the phone is sideways; stop the voice with it.
  useEffect(() => {
    if (sideways) audio.current?.pause();
  }, [sideways]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") {
        if (index === RANK) setIndex(END);
        else if (index !== END) go(index + 1);
      }
      if (e.key === "ArrowLeft") go(index === END || index === RANK ? beats.length - 1 : index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, index, beats.length]);

  if (errorCode === "sign_in_required") {
    return (
      <main data-persona={persona} className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <div className="font-mono text-xs text-dim">{login} / not wrapped yet</div>
        <p className="mt-4 font-serif text-4xl max-w-md leading-tight">Sign in to make this roast.</p>
        <p className="mt-3 text-dim max-w-sm">Nobody has wrapped @{login} with this narrator yet. Signing in with GitHub gets you three new roasts a day; finished ones open for anyone.</p>
        <a href={signInUrl()} className="btn btn-primary mt-8 px-6">
          Sign in with GitHub
        </a>
        <Link href="/" className="mt-5 text-sm underline text-dim">
          Back
        </Link>
      </main>
    );
  }
  if (error) {
    return (
      <main data-persona={persona} className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        {errorCode === "quota" || errorCode === "site_quota" ? <div className="font-mono text-xs text-dim">{login} / limit reached</div> : null}
        <p className="mt-3 font-serif text-3xl max-w-lg leading-tight">{error}</p>
        <Link href="/" className="mt-6 underline text-dim">
          {errorCode === "quota" ? "Back" : "Try another username"}
        </Link>
      </main>
    );
  }
  if (!wrap) {
    return (
      <main data-persona={persona} className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <div className="font-mono text-xs text-dim">{login} / reading twelve months</div>
        <p className="mt-4 font-serif text-3xl animate-pulse">{PERSONAS[persona]?.title ?? "The narrator"} is going through the commits.</p>
        <p className="mt-2 text-dim text-sm">About twenty seconds the first time; a busy year takes a minute.</p>
      </main>
    );
  }

  const shown = beats.map((b) => byId.get(b.stat_id)).filter((h): h is Highlight => !!h);
  const beat = index === END || index === RANK ? null : beats[index];
  const highlight = beat ? byId.get(beat.stat_id) : null;
  const narrator = PERSONAS[wrap.persona]?.title.replace("The ", "the ") ?? wrap.persona;

  return (
    <main data-persona={persona} className="flex-1 flex items-center justify-center bg-background">
      <div ref={frame} className="relative w-full max-w-[480px] h-[100dvh] sm:h-[min(100dvh,900px)] sm:border sm:border-border overflow-hidden select-none bg-background">
        {lines && wrap.assets ? <audio ref={audio} src={wrap.assets.audio} preload="auto" /> : null}
        <Header wrap={wrap} index={index} progress={progress} beats={beats.length} />

        {beat && highlight ? <Scene wrap={wrap} index={index} highlight={highlight} tone={beat.tone} /> : null}
        {index === RANK ? <RankReveal rank={wrap.rank} onNext={() => setIndex(END)} /> : null}
        {index === END ? <EndCard wrap={wrap} shown={shown} onMagic={() => setPanel(true)} onReplay={() => go(0)} busy={busy} /> : null}

        {/* The line, and who is saying it */}
        {beat ? (
          <div className="absolute inset-x-0 bottom-0 px-5 pb-[max(1.5rem,env(safe-area-inset-bottom))] z-10">
            <div className="font-mono text-[11px] text-dim mb-2">
              {narrator}
              {wrap.voice !== "narrator" ? ` · voice of ${wrap.voice}` : ""}
              {lines ? "" : " · silent until Magic Hour runs"}
            </div>
            <p className="font-serif text-xl leading-snug">{beat.line}</p>
          </div>
        ) : null}

        {/* Tap zones */}
        {index !== END && index !== RANK ? (
          <>
            <button aria-label="Previous" className="absolute inset-y-0 left-0 w-1/3 z-[5]" onClick={() => go(index - 1)} />
            <button
              aria-label="Next"
              className="absolute inset-y-0 right-0 w-2/3 z-[5]"
              onClick={() => go(index + 1)}
              onPointerDown={() => setPaused(true)}
              onPointerUp={() => setPaused(false)}
              onPointerLeave={() => setPaused(false)}
            />
          </>
        ) : null}

        {sideways ? (
          <div className="fixed inset-0 z-30 bg-background flex flex-col items-center justify-center p-8 text-center">
            <p className="font-serif text-2xl">Turn your phone upright.</p>
            <p className="mt-2 text-sm text-dim">Wraps are made to be watched in portrait. It picks up where it left off.</p>
          </div>
        ) : null}

        {panel ? (
          <MagicHourPanel
            wrap={wrap}
            onClose={() => setPanel(false)}
            onDone={(assets, video) => {
              setPanel(false);
              setBusy(false);
              setWrap({ ...wrap, magic_ready: !!assets, assets: assets ?? wrap.assets, video });
              setIndex(0);
            }}
          />
        ) : null}
      </div>
    </main>
  );
}
