import type { MetadataRoute } from "next";

// PWA web app manifest. Next App Router convention serves this at
// /manifest.webmanifest and auto-injects the <link rel="manifest"> tag.
// theme_color must match the brand (matches the blue that the desktop
// app + favicon + OG card all use) so mobile browser chrome colors in
// correctly when a user adds the site to their home screen.

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ApplyLoop — AI-powered job applications",
    short_name: "ApplyLoop",
    description:
      "AI fills out job applications, tailors resumes, and writes cover letters while you sleep. 30-60 applications/day on autopilot.",
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#3b82f6",
    categories: ["productivity", "business", "jobs"],
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
      },
      {
        src: "/apple-icon.png",
        sizes: "180x180",
        type: "image/png",
        purpose: "any",
      },
    ],
  };
}
