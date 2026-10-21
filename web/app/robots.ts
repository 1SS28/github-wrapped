import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/brand";

// Crawlers may read everything except the sign-in routes. Wrap pages stay crawlable on purpose: link
// previews (X, Slack, iMessage) obey robots.txt, and blocking a page would also hide its "noindex" tag.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: "/api/auth/" },
    sitemap: `https://${SITE_URL}/sitemap.xml`,
  };
}
