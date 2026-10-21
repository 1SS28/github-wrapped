import { ImageResponse } from "next/og";
import { API, type Wrap } from "@/lib/api";
import { BRAND, SITE_URL } from "@/lib/brand";
import { FONT_FAMILY, loadFonts } from "@/lib/fonts";

const THEMES: Record<string, { top: string; bottom: string; accent: string }> = {
  professor: { top: "#161b22", bottom: "#0d1117", accent: "#d29922" },
  hype: { top: "#161b22", bottom: "#0d1117", accent: "#58a6ff" },
  senior: { top: "#161b22", bottom: "#0d1117", accent: "#3fb950" },
};

/** The share card: verdict, handle, the top three figures, and where to make your own. */
export async function GET(request: Request, { params }: { params: Promise<{ login: string }> }) {
  const { login } = await params;
  const search = new URL(request.url).searchParams;
  const asked = search.get("persona") ?? "";
  const persona = Object.hasOwn(THEMES, asked) ? asked : "senior";
  const theme = THEMES[persona];
  const voice = search.get("voice");
  // Crawlers fetch this for any link they see, so it only reads a wrap someone already made (cached=true):
  // a preview never writes a script or spends anything.
  const query = new URLSearchParams({ persona, cached: "true", ...(voice ? { voice } : {}) });
  let wrap: Wrap | null = null;
  try {
    const response = await fetch(`${API}/api/wrap/${encodeURIComponent(login)}?${query}`, { cache: "no-store" });
    if (response.ok) wrap = (await response.json()) as Wrap;
  } catch {
    wrap = null;
  }
  const shown = wrap ? wrap.script.beats.map((b) => wrap!.highlights.find((h) => h.id === b.stat_id)).filter(Boolean).slice(0, 3) : [];
  // Satori fetches the image itself and refuses private addresses, so a local API gets no picture.
  const candidate = wrap?.assets?.art?.find((a) => a) ?? null;
  const art = candidate && !/\/\/(localhost|127\.0\.0\.1|\[::1\]|10\.|192\.168\.)/.test(candidate) ? candidate : null;
  const handle = `@${decodeURIComponent(login)}`;
  const tier = wrap?.rank?.tier ?? null;
  const tierLabel = tier === "Unranked" ? "UNRANKED" : tier ? `TIER ${tier}` : "";
  const tierBig = tier === "Unranked" ? "∞" : tier ?? "";
  const verdict = wrap ? `“${wrap.script.verdict}”` : "12 months of commits, one verdict";

  const fonts = await loadFonts();
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          background: `linear-gradient(135deg, ${theme.top}, ${theme.bottom})`,
          color: "white",
          fontFamily: FONT_FAMILY,
          position: "relative",
        }}
      >
        {tier && !art ? (
          <div style={{ position: "absolute", right: 70, top: 70, display: "flex", flexDirection: "column", alignItems: "center" }}>
            <div style={{ fontSize: 220, fontWeight: 700, lineHeight: 1, color: theme.accent }}>{tierBig}</div>
            <div style={{ fontSize: 28, letterSpacing: 6, color: "#e6e9ef" }}>{tierLabel}</div>
          </div>
        ) : null}
        {art ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={art} alt="" width={420} height={630} style={{ position: "absolute", right: 0, top: 0, height: 630, width: 420, objectFit: "cover", opacity: 0.9 }} />
        ) : null}
        <div style={{ display: "flex", flexDirection: "column", padding: 56, width: art ? 780 : 1200, justifyContent: "space-between" }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 24, letterSpacing: 4, color: "#aab0ba" }}>{BRAND.toUpperCase()}</div>
            <div style={{ fontSize: 60, fontWeight: 700, marginTop: 10 }}>{handle}</div>
            <div style={{ fontSize: 44, fontWeight: 700, color: theme.accent, marginTop: 18, lineHeight: 1.1 }}>{verdict}</div>
            {tier && art ? <div style={{ fontSize: 30, fontWeight: 700, color: "#e6e9ef", marginTop: 14 }}>{tierLabel}</div> : null}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {shown.map((h) => (
              <div key={h!.id} style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
                <div style={{ fontSize: 44, fontWeight: 700, color: theme.accent, minWidth: 170 }}>{h!.value}</div>
                <div style={{ fontSize: 26, color: "#e6e9ef" }}>{h!.label}</div>
              </div>
            ))}
            <div style={{ fontSize: 22, color: "#aab0ba", marginTop: 10 }}>{`Make yours · ${SITE_URL} · made with Magic Hour`}</div>
          </div>
        </div>
      </div>
    ),
    { width: 1200, height: 630, ...(fonts.length ? { fonts } : {}) },
  );
}
