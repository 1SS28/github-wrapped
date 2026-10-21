"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import DemoPhone from "@/components/DemoPhone";
import { ORIGINAL_VOICE, PERSONAS, getSession, getVoices, signInUrl, type VoiceList } from "@/lib/api";
import { BRAND } from "@/lib/brand";

// One real line per narrator (from scripts the engine wrote), so people pick by how it sounds.
const SAMPLES: Record<string, string> = {
  professor: "316 consecutive days without a commit. I had assumed you dropped the course.",
  hype: "316 days without a commit! The crowd went home, had dinner, and forgot your name!",
  senior: "Your repos weren't dormant. They were legally deceased.",
};

const FALLBACK_DEFAULTS: Record<string, string> = { professor: "David Attenborough", hype: "Dwayne 'The Rock' Johnson", senior: "Elon Musk" };

export default function Home() {
  const router = useRouter();
  const [login, setLogin] = useState("");
  const [persona, setPersona] = useState("senior");
  const [voice, setVoice] = useState("");
  const [voices, setVoices] = useState<VoiceList | null>(null);

  const [me, setMe] = useState<string | null>(null);

  useEffect(() => {
    getVoices().then(setVoices).catch(() => setVoices(null));
    getSession().then((sess) => setMe(sess.login));
  }, []);

  const defaults = voices?.defaults ?? FALLBACK_DEFAULTS;
  const shownVoice = voice === ORIGINAL_VOICE ? "the narrator" : voice || defaults[persona];

  function go(event: React.FormEvent) {
    event.preventDefault();
    const clean = login.trim().replace(/^@/, "").replace(/^https?:\/\/github\.com\//, "").split("/")[0];
    const params = new URLSearchParams({ persona, ...(voice ? { voice } : {}) });
    if (clean) router.push(`/${encodeURIComponent(clean)}?${params}`);
  }

  return (
    <main data-persona={persona} className="flex-1 flex flex-col">
      <header className="px-6 sm:px-10 py-5 flex justify-between items-center font-mono text-sm text-dim border-b border-border">
        <span className="text-foreground">{BRAND.toLowerCase()}</span>
        <span className="flex gap-5">
          {me ? (
            <span>
              {me} ·{" "}
              {/* a route handler, not a page: it needs a full navigation, so no <Link> */}
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
              <a href="/api/auth/logout" className="hover:text-foreground">
                sign out
              </a>
            </span>
          ) : (
            <a href={signInUrl("/")} className="hover:text-foreground">
              sign in
            </a>
          )}
          <a href="https://github.com/1SS28/github-wrapped" className="hover:text-foreground">
            source
          </a>
        </span>
      </header>

      <div className="flex-1 w-full max-w-6xl mx-auto px-6 sm:px-10 py-12 lg:py-20 flex flex-col lg:flex-row items-center lg:items-start gap-14 lg:gap-20">
        <section className="flex-1 w-full max-w-xl">
          <h1 className="font-serif font-bold text-6xl sm:text-8xl leading-[0.9] tracking-tight">
            GitHub <span className="text-accent">Wrapped</span>
          </h1>
          <p className="mt-4 font-serif text-2xl sm:text-3xl text-foreground/90">Your year on GitHub, roasted.</p>
          <p className="mt-5 text-lg text-foreground/75 leading-relaxed">
            Type a username. A famous voice reads back twelve months of commits, late nights and empty streaks, then ranks the
            year from F to SSS.
          </p>

          <form onSubmit={go} className="mt-10">
            <div className="flex rounded-md border border-border bg-panel focus-within:border-dim overflow-hidden">
              <span className="hidden sm:flex items-center pl-4 font-mono text-dim select-none">github.com/</span>
              <input
                value={login}
                onChange={(e) => setLogin(e.target.value)}
                placeholder="username"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
                aria-label="GitHub username"
                className="flex-1 min-w-0 bg-transparent font-mono text-lg sm:text-xl px-4 sm:pl-1 py-4 outline-none placeholder:text-dim/60"
              />
              <button type="submit" className="m-1.5 rounded-[5px] bg-[#238636] hover:bg-[#2ea043] text-white font-semibold px-5 text-base">
                Wrap it
              </button>
            </div>

            <div className="mt-10">
              <div className="flex items-baseline justify-between">
                <h2 className="text-sm font-semibold">Who reads it</h2>
                <label className="text-xs text-dim flex items-center gap-2">
                  voice
                  <select
                    value={voice}
                    onChange={(e) => setVoice(e.target.value)}
                    className="bg-transparent border-b border-border focus:border-foreground outline-none py-0.5 text-foreground max-w-[12rem]"
                  >
                    <option value="">{defaults[persona]}</option>
                    {(voices?.popular ?? []).filter((n) => n !== defaults[persona]).map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                    <option value={ORIGINAL_VOICE}>no impression</option>
                  </select>
                </label>
              </div>
              <div className="mt-3 -mx-6 px-6 scroll-px-6 [scrollbar-width:none] flex gap-2 overflow-x-auto snap-x snap-mandatory sm:mx-0 sm:px-0 sm:grid sm:grid-cols-3 sm:overflow-visible">
                {Object.entries(PERSONAS).map(([key, p]) => {
                  const active = persona === key;
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => {
                        setPersona(key);
                        setVoice("");
                      }}
                      data-persona={key}
                      className={`snap-start shrink-0 w-[78%] sm:w-auto text-left rounded-md border p-3.5 transition-colors ${active ? "border-accent bg-panel" : "border-border hover:border-dim"}`}
                    >
                      <div className={`text-sm font-semibold ${active ? "text-accent" : ""}`}>{p.title}</div>
                      <div className="mt-0.5 font-mono text-[11px] text-dim">{defaults[key]}</div>
                      <p className="mt-2.5 font-serif text-[15px] leading-snug text-foreground/85">{SAMPLES[key]}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          </form>

          <p className="mt-10 text-xs text-dim leading-relaxed">
            Public activity only; commit messages come from public repos. Illustrations and voices by Magic Hour, which are
            impressions, not the people themselves.{" "}
            <a className="underline hover:text-foreground" href="https://github.com/1SS28/github-wrapped/issues/new?template=opt-out.yml">
              Opt out
            </a>
            .
          </p>
        </section>

        <aside className="lg:sticky lg:top-12">
          <DemoPhone narrator={PERSONAS[persona].title.replace("The ", "the ")} voice={shownVoice} />
        </aside>
      </div>
    </main>
  );
}
