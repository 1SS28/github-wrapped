"use client";

import { useEffect, useState } from "react";
import type { DayCount } from "@/lib/api";
import { Calendar } from "@/components/Wrapped";

// A made-up year that tells the classic story: nothing for ten months, then a panic.
function exampleYear(): DayCount[] {
  const days: DayCount[] = [];
  let seed = 7;
  const next = () => (seed = (seed * 48271) % 2147483647) / 2147483647;
  const start = Date.UTC(2025, 9, 19);
  for (let i = 0; i < 366; i++) {
    const date = new Date(start + i * 86_400_000).toISOString().slice(0, 10);
    const late = i > 300;
    const r = next();
    days.push({ date, count: late ? (r < 0.55 ? Math.ceil(r * 14) : 0) : r < 0.03 ? 1 : 0 });
  }
  return days;
}

const YEAR = exampleYear();

const SLIDES = [
  { kind: "beat", tone: "roast", value: "316", label: "days without a single commit", line: "Your repos weren't dormant. They were legally deceased." },
  { kind: "beat", tone: "roast", value: "43%", label: "of commits after midnight", line: "That's not momentum. That's a deadline you invented and then panicked about." },
  { kind: "beat", tone: "props", value: "12", label: "new projects, none abandoned", line: "I checked twice. Rarer than a green test suite on a Friday." },
  { kind: "rank" },
] as const;

/** A phone showing an example wrap on a loop: the thing people get, before they type anything. */
export default function DemoPhone({ narrator, voice }: { narrator: string; voice: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setI((n) => (n + 1) % SLIDES.length), 3400);
    return () => window.clearInterval(t);
  }, []);
  const slide = SLIDES[i];
  return (
    <div className="relative w-[300px] h-[610px] shrink-0 rounded-[34px] border border-border bg-background p-[10px] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8)]">
      <div className="relative h-full w-full overflow-hidden rounded-[26px] bg-background border border-border/60">
        <div className="absolute top-0 inset-x-0 px-4 pt-3 z-10">
          <div className="flex gap-1">
            {SLIDES.map((_, n) => (
              <div key={n} className="h-[2px] flex-1 bg-white/15 overflow-hidden">
                <div className="h-full bg-white/90 transition-[width] duration-300" style={{ width: n < i ? "100%" : n === i ? "60%" : "0%" }} />
              </div>
            ))}
          </div>
          <div className="mt-2 flex justify-between font-mono text-[9px] text-dim">
            <span>example / Oct 2025 – Oct 2026</span>
            <span>wrapped</span>
          </div>
        </div>

        {slide.kind === "beat" ? (
          <div key={i} className="absolute inset-0">
            <Calendar days={YEAR} className="absolute inset-x-4 top-[15%]" />
            <div className="absolute inset-x-0 bottom-[30%] px-4">
              <div className={`font-mono text-[10px] ${slide.tone === "props" ? "text-props" : "text-roast"}`}>{slide.tone}</div>
              <div className="rise font-mono text-6xl leading-none tracking-tight">{slide.value}</div>
              <div className="rise mt-1.5 text-sm text-foreground/85" style={{ animationDelay: "0.08s" }}>
                {slide.label}
              </div>
            </div>
            <div className="absolute inset-x-0 bottom-0 px-4 pb-5">
              <div className="font-mono text-[9px] text-dim mb-1">
                {narrator} · voice of {voice}
              </div>
              <p className="rise font-serif text-[15px] leading-snug" style={{ animationDelay: "0.2s" }}>
                {slide.line}
              </p>
            </div>
          </div>
        ) : (
          <div key={i} className="absolute inset-0 px-4 pt-14" style={{ "--tier": "#3fb950" } as React.CSSProperties}>
            <div className="font-mono text-[10px] text-dim">rank for the year</div>
            <div className="slam glow font-mono text-[5.5rem] leading-none mt-1" style={{ color: "#3fb950" }}>
              C
            </div>
            <p className="rise mt-3 font-serif text-xl leading-tight" style={{ animationDelay: "0.4s" }}>
              Tier C. 33 out of 100. 10 short of B.
            </p>
            <ul className="rise mt-4 rule text-[11px]" style={{ animationDelay: "0.6s" }}>
              {[
                ["Volume", 62],
                ["Consistency", 7],
                ["Collaboration", 0],
                ["Craft", 100],
              ].map(([name, pct]) => (
                <li key={name} className="py-1.5 border-b border-border">
                  <div className="flex justify-between">
                    <span>{name}</span>
                  </div>
                  <div className="mt-1 h-[2px] bg-white/10">
                    <div className="h-full bg-[#3fb950]" style={{ width: `${pct}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
