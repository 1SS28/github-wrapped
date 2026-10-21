// Fonts for the image routes. The image renderer (Satori) only knows the fonts it is handed and has
// no bold of its own, so the share images load a few faces from Google Fonts once per server
// instance: Tinos (Times New Roman's open twin) for the headline, Geist Mono for figures, Geist for
// the rest. It needs ttf, otf or woff (no woff2), hence the old browser user agent.

const TTF_UA = "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:27.0) Gecko/20100101 Firefox/27.0";
const WANTED = [
  ["Tinos", 700],
  ["Geist Mono", 500],
  ["Geist", 400],
  ["Geist", 600],
] as const;

export interface ImageFont {
  name: string;
  data: ArrayBuffer;
  weight: 400 | 500 | 600 | 700;
  style: "normal";
}

let cache: Promise<ImageFont[]> | null = null;

async function fetchFace(family: string, weight: ImageFont["weight"]): Promise<ImageFont | null> {
  try {
    const css = await fetch(`https://fonts.googleapis.com/css2?family=${family.replace(/ /g, "+")}:wght@${weight}&display=swap`, {
      headers: { "user-agent": TTF_UA },
      cache: "force-cache",
    }).then((r) => r.text());
    const url = css.match(/src:\s*url\(([^)]+\.(?:ttf|otf|woff))\)/)?.[1];
    if (!url) return null;
    const data = await fetch(url, { cache: "force-cache" }).then((r) => r.arrayBuffer());
    return { name: family, data, weight, style: "normal" };
  } catch {
    return null;
  }
}

/** The fonts to pass to ImageResponse; empty when Google Fonts is unreachable, and the default font steps in. */
export function loadFonts(): Promise<ImageFont[]> {
  cache ??= Promise.all(WANTED.map(([family, weight]) => fetchFace(family, weight))).then((fonts) => fonts.filter((f): f is ImageFont => f !== null));
  return cache;
}

export const SERIF = `Tinos, "Times New Roman", serif`;
export const MONO = `"Geist Mono", ui-monospace, monospace`;
export const SANS = `Geist, system-ui, sans-serif`;
export const FONT_FAMILY = SANS;
