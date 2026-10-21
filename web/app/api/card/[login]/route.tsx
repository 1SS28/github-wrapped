import { ImageResponse } from "next/og";
import { API, type DayCount, type Wrap } from "@/lib/api";
import { BRAND, SITE_URL } from "@/lib/brand";
import { MONO, SANS, SERIF, loadFonts } from "@/lib/fonts";

// GitHub's own contribution-graph greens.
const LEVELS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"];
const ACCENTS: Record<string, string> = { professor: "#d29922", hype: "#58a6ff", senior: "#3fb950" };

function level(count: number, max: number): string {
  if (!count) return LEVELS[0];
  return LEVELS[Math.min(4, 1 + Math.floor((3 * count) / Math.max(1, max)))];
}

/** Weeks of the year as columns of seven, Sunday first, the way GitHub draws it. */
function weeks(days: DayCount[]): DayCount[][] {
  if (!days.length) return [];
  const first = new Date(days[0].date + "T00:00:00Z");
  const lead = first.getUTCDay();
  const padded: (DayCount | null)[] = [...Array<null>(lead).fill(null), ...days];
  const out: DayCount[][] = [];
  for (let i = 0; i < padded.length; i += 7) out.push(padded.slice(i, i + 7).map((d) => d ?? { date: "", count: -1 }));
  return out;
}

function tierLine(wrap: Wrap): string {
  const r = wrap.rank;
  const score = Math.round(r.score);
  if (!r.tier) return "No rank yet. Not enough activity to judge.";
  if (r.tier === "Unranked") return `Unranked. ${score} out of 100; the scale stops at SSS.`;
  const next = r.next_tier && r.points_to_next != null ? ` ${Math.ceil(r.points_to_next)} short of ${r.next_tier}.` : "";
  return `Tier ${r.tier}. ${score} out of 100.${next}`;
}

/** The card people post: the contribution graph as the picture, the verdict as the headline, the figures as a plain list. */
export async function GET(request: Request, { params }: { params: Promise<{ login: string }> }) {
  const { login } = await params;
  const search = new URL(request.url).searchParams;
  const asked = search.get("persona") ?? "";
  const persona = Object.hasOwn(ACCENTS, asked) ? asked : "senior";
  const accent = ACCENTS[persona];
  let wrap: Wrap | null = null;
  try {
    const voice = search.get("voice");
    // Only a wrap that already exists: the card is for sharing one, not for making one.
    const query = new URLSearchParams({ persona, cached: "true", ...(voice ? { voice } : {}) });
    const response = await fetch(`${API}/api/wrap/${encodeURIComponent(login)}?${query}`, { cache: "no-store" });
    if (response.ok) wrap = (await response.json()) as Wrap;
  } catch {
    wrap = null;
  }
  if (!wrap) return new Response("no wrap for that login yet", { status: 404 });

  const shown = wrap.script.beats.map((b) => wrap!.highlights.find((h) => h.id === b.stat_id)).filter(Boolean).slice(0, 4);
  const calendar = wrap.stats.calendar;
  const max = Math.max(1, ...calendar.map((d) => d.count));
  const columns = weeks(calendar);
  // Two half-year strips: the cells are big enough to read as the picture, not a texture.
  const half = Math.ceil(columns.length / 2);
  const strips = [columns.slice(0, half), columns.slice(half)];
  const gap = 5;
  const cell = Math.floor((1080 - 2 * 72 - (half - 1) * gap) / Math.max(1, half));
  const since = new Date(wrap.since);
  const until = new Date(wrap.until);
  const span = `${since.toLocaleString("en", { month: "short", year: "numeric" })} – ${until.toLocaleString("en", { month: "short", year: "numeric" })}`;
  const fonts = await loadFonts();

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", padding: "64px 72px 56px", background: "#0d1117", color: "#e6edf3", fontFamily: SANS }}>
        {/* Who, when: one quiet mono line, the way a repo header reads. */}
        <div style={{ display: "flex", justifyContent: "space-between", fontFamily: MONO, fontSize: 26, color: "#8b949e" }}>
          <div>{`${wrap.login} / ${span}`}</div>
          <div>{BRAND.toLowerCase()}</div>
        </div>

        {/* The picture: their actual year, in two strips. */}
        <div style={{ display: "flex", flexDirection: "column", gap: 26, marginTop: 48 }}>
          {strips.map((strip, n) => (
            <div key={n} style={{ display: "flex", gap }}>
              {strip.map((week, i) => (
                <div key={i} style={{ display: "flex", flexDirection: "column", gap }}>
                  {week.map((d, j) => (
                    <div key={j} style={{ width: cell, height: cell, borderRadius: 4, background: d.count < 0 ? "transparent" : level(d.count, max) }} />
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", fontFamily: MONO, fontSize: 26, color: "#8b949e", marginTop: 18 }}>
          {`${wrap.stats.total_contributions.toLocaleString("en")} contributions · ${wrap.stats.active_days} active days`}
        </div>

        {/* The headline. */}
        <div style={{ display: "flex", fontFamily: SERIF, fontWeight: 700, fontSize: 118, lineHeight: 0.98, marginTop: 84, letterSpacing: -3 }}>{wrap.script.verdict}</div>
        <div style={{ display: "flex", fontSize: 38, color: accent, marginTop: 34, fontWeight: 600 }}>{tierLine(wrap)}</div>

        {/* The figures, as a plain ruled list. */}
        <div style={{ display: "flex", flexDirection: "column", marginTop: 72, borderTop: "1px solid #30363d" }}>
          {shown.map((h) => (
            <div key={h!.id} style={{ display: "flex", alignItems: "baseline", padding: "30px 0", borderBottom: "1px solid #30363d" }}>
              <div style={{ fontFamily: MONO, fontSize: 66, fontWeight: 500, width: 360, color: "#e6edf3" }}>{h!.value}</div>
              <div style={{ fontSize: 36, color: "#c9d1d9", flex: 1, minWidth: 0 }}>{h!.label}</div>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", flex: 1 }} />
        <div style={{ display: "flex", fontFamily: MONO, fontSize: 24, color: "#8b949e" }}>{SITE_URL}</div>
      </div>
    ),
    { width: 1080, height: 1920, ...(fonts.length ? { fonts } : {}) },
  );
}
