// Typed client for the engine (api/app.py). The API's origin comes from NEXT_PUBLIC_API_URL.

export const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080").replace(/\/$/, "");

export type Tone = "roast" | "compliment";

export interface Highlight {
  id: string;
  group: string;
  kind: "roast" | "flex";
  value: string;
  label: string;
  fact: string;
  score: number;
}

export interface Beat {
  stat_id: string;
  tone: Tone;
  line: string;
  visual: string;
}

export interface Script {
  persona: string;
  verdict: string;
  beats: Beat[];
  sign_off: string;
  cards: Record<string, string>;
}

export interface DayCount {
  date: string;
  count: number;
}

export interface Stats {
  commits: number;
  total_contributions: number;
  active_days: number;
  days_in_window: number;
  calendar: DayCount[];
  hour_commits: number[];
  languages: { name: string; share: number }[];
  top_repos: { name: string; commits: number }[];
  [key: string]: unknown;
}

export interface TimedLine {
  text: string;
  start: number;
  end: number;
}

export interface Assets {
  voice: string;
  art: (string | null)[];
  clips: (string | null)[];
  audio: string;
  lines: TimedLine[];
  duration: number;
  credits: number;
}

export interface RankPart {
  name: string;
  points: number;
  max: number;
  note: string;
}

export interface Rank {
  tier: string | null;
  score: number;
  parts: RankPart[];
  tagline: string;
  next_tier: string | null;
  points_to_next: number | null;
}

export const TIERS = ["F", "E", "D", "C", "B", "A", "S", "SS", "SSS", "Unranked"];

export interface Wrap {
  login: string;
  name: string | null;
  persona: string;
  voice: string;
  rank: Rank;
  since: string;
  until: string;
  scope: string;
  highlights: Highlight[];
  script: Script;
  stats: Stats;
  cached_at: string;
  magic_ready: boolean;
  remaining?: number | null; // new roasts the signed-in visitor has left today
  assets?: Assets;
  video: string | null;
}

export interface Job {
  id: string;
  kind: "magic" | "video";
  status: "queued" | "running" | "done" | "error";
  result?: Record<string, unknown>;
  error?: string;
  code?: number;
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message);
  }
}

export interface Session {
  login: string | null;
  token: string | null;
}

let session: Promise<Session> | null = null;

/** Who is signed in (asks this site, which holds the cookie). The token it returns is what the engine checks. */
export function getSession(): Promise<Session> {
  session ??= fetch("/api/auth/token", { cache: "no-store" })
    .then((r) => (r.ok ? (r.json() as Promise<Session>) : { login: null, token: null }))
    .catch(() => ({ login: null, token: null }));
  return session;
}

export function signInUrl(next?: string): string {
  const here = next ?? (typeof window !== "undefined" ? window.location.pathname + window.location.search : "/");
  return `/api/auth/login?next=${encodeURIComponent(here)}`;
}

async function call<T>(path: string, init?: RequestInit, auth = false): Promise<T> {
  const token = auth ? (await getSession()).token : null;
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}), ...(init?.headers ?? {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(body.error ?? body.detail ?? `HTTP ${response.status}`, response.status, body.code);
  return body as T;
}

export function getWrap(login: string, persona: string, voice?: string): Promise<Wrap> {
  const params = new URLSearchParams({ persona, ...(voice ? { voice } : {}) });
  return call<Wrap>(`/api/wrap/${encodeURIComponent(login)}?${params}`, undefined, true);
}

export function getBalance(magicHourKey: string): Promise<{ credits: number | null; tier: string | null }> {
  return call(`/api/magic-hour/balance`, { method: "POST", body: JSON.stringify({ magic_hour_key: magicHourKey }) });
}

export function startMagic(login: string, persona: string, voice: string, magicHourKey: string, heroes = 2): Promise<Job> {
  return call<Job>(`/api/wrap/${encodeURIComponent(login)}/magic`, {
    method: "POST",
    body: JSON.stringify({ persona, voice, magic_hour_key: magicHourKey, heroes }),
  });
}

export function startVideo(login: string, persona: string, voice: string, magicHourKey: string): Promise<Job> {
  return call<Job>(`/api/wrap/${encodeURIComponent(login)}/video`, {
    method: "POST",
    body: JSON.stringify({ persona, voice, magic_hour_key: magicHourKey }),
  });
}

export interface VoiceList {
  original: string;
  popular: string[];
  defaults: Record<string, string>;
  count: number;
}

export function getVoices(): Promise<VoiceList> {
  return call<VoiceList>("/api/voices");
}

export const ORIGINAL_VOICE = "narrator";

export async function waitForJob(job: Job, onUpdate?: (job: Job) => void, intervalMs = 2500): Promise<Job> {
  let current = job;
  while (current.status === "queued" || current.status === "running") {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    current = await call<Job>(`/api/jobs/${job.id}`);
    onUpdate?.(current);
  }
  return current;
}

export const PERSONAS: Record<string, { title: string; blurb: string }> = {
  professor: { title: "The Professor", blurb: "a stern, disappointed academic" },
  hype: { title: "The Hype Commentator", blurb: "an over-the-top sports commentator" },
  senior: { title: "The Tired Senior Engineer", blurb: "a weary senior doing a code review of your year" },
};

/** Seconds a line takes to read aloud, for the silent (pre-voice) timing. */
export function readingSeconds(text: string): number {
  return Math.max(2.2, text.split(/\s+/).length / 2.35 + 0.8);
}
