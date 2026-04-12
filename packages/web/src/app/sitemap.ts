import type { MetadataRoute } from "next";

// Next.js App Router convention: this file becomes /sitemap.xml and is
// served from the edge. Keep this list in sync with the public routes —
// dashboard / admin / api routes are explicitly OUT (they're blocked in
// robots.ts because they require auth and have no SEO value).

const BASE_URL =
  process.env.NEXT_PUBLIC_APP_URL || "https://applyloop.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    {
      url: BASE_URL,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 1.0,
    },
    {
      url: `${BASE_URL}/auth/login`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.6,
    },
    {
      url: `${BASE_URL}/onboarding`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.5,
    },
    {
      url: `${BASE_URL}/setup-complete`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.4,
    },
  ];
}
