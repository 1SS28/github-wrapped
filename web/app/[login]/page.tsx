import type { Metadata } from "next";
import { Suspense } from "react";
import Wrapped from "@/components/Wrapped";
import { PERSONAS } from "@/lib/api";
import { BRAND } from "@/lib/brand";

type Params = Promise<{ login: string }>;
type Search = Promise<{ persona?: string; voice?: string }>;

export async function generateMetadata({ params, searchParams }: { params: Params; searchParams: Search }): Promise<Metadata> {
  const { login } = await params;
  const search = await searchParams;
  const persona = search.persona && Object.hasOwn(PERSONAS, search.persona) ? search.persona : "senior";
  const title = `@${decodeURIComponent(login)}'s ${BRAND}`;
  const image = `/api/og/${encodeURIComponent(decodeURIComponent(login))}?${new URLSearchParams({ persona, ...(search.voice ? { voice: search.voice } : {}) })}`;
  return {
    title,
    // Someone's roast should not come up when people search their name. Shared links and previews still work.
    robots: { index: false, follow: true },
    description: "12 months of commits, one verdict. Make yours.",
    openGraph: { title, images: [{ url: image, width: 1200, height: 630 }] },
    twitter: { card: "summary_large_image", title, images: [image] },
  };
}

async function Player({ params, searchParams }: { params: Params; searchParams: Search }) {
  const { login } = await params;
  const search = await searchParams;
  return <Wrapped login={decodeURIComponent(login)} persona={search.persona ?? "senior"} voice={search.voice} />;
}

export default function Page(props: { params: Params; searchParams: Search }) {
  return (
    <Suspense fallback={<main className="stage flex-1" />}>
      <Player {...props} />
    </Suspense>
  );
}
