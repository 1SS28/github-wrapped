import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/brand";

// Only the homepage: individual wraps are kept out of search results (see app/[login]/page.tsx).
export default function sitemap(): MetadataRoute.Sitemap {
  return [{ url: `https://${SITE_URL}/`, changeFrequency: "weekly", priority: 1 }];
}
