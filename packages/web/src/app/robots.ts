import type { MetadataRoute } from "next";

// Next.js App Router convention: this file becomes /robots.txt served from
// the edge. Only the landing + auth + onboarding surfaces are crawlable —
// everything behind a worker token or user session is explicitly blocked.

const BASE_URL =
  process.env.NEXT_PUBLIC_APP_URL || "https://applyloop.vercel.app";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: [
          "/",
          "/auth/login",
          "/onboarding",
          "/setup-complete",
        ],
        disallow: [
          "/api/",         // all server routes — not useful to crawl, often auth-gated
          "/dashboard/",   // user-private
          "/admin",        // admin-only
          "/auth/rejected",
          "/auth/pending",
        ],
      },
    ],
    sitemap: `${BASE_URL}/sitemap.xml`,
    host: BASE_URL,
  };
}
