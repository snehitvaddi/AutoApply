import "./globals.css";
import type { Metadata, Viewport } from "next";

const BASE_URL =
  process.env.NEXT_PUBLIC_APP_URL || "https://applyloop.vercel.app";

// Primary metadata. Next emits the <head> tags automatically from this
// object + from the co-located App Router convention files (icon.svg,
// apple-icon.tsx, opengraph-image.tsx, sitemap.ts, robots.ts,
// manifest.ts). Keep the two in sync — the metadata below mostly points
// at the convention files, not at literal URLs in public/.
export const metadata: Metadata = {
  metadataBase: new URL(BASE_URL),
  title: {
    default: "ApplyLoop — AI-Powered Job Application Engine",
    template: "%s · ApplyLoop",
  },
  description:
    "Stop applying manually. ApplyLoop's AI fills out job applications, tailors resumes per role, writes cover letters, and submits them automatically — 30-60 applications per day on autopilot.",
  applicationName: "ApplyLoop",
  keywords: [
    "automated job applications",
    "AI job search",
    "resume tailoring",
    "ATS automation",
    "Greenhouse",
    "Lever",
    "Ashby",
    "Workday",
    "job application bot",
    "AI cover letter",
    "job scout",
    "LinkedIn automation",
    "Indeed automation",
    "applyloop",
  ],
  authors: [{ name: "ApplyLoop", url: BASE_URL }],
  creator: "ApplyLoop",
  publisher: "ApplyLoop",
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  alternates: {
    canonical: "/",
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: BASE_URL,
    siteName: "ApplyLoop",
    title: "ApplyLoop — Stop Applying Manually. Start Getting Interviews.",
    description:
      "AI fills applications, tailors resumes, writes cover letters — while you sleep. 30-60 applications per day on autopilot.",
    // opengraph-image.tsx in this directory is auto-wired; no need to
    // list `images:` here. Next resolves the convention file on build.
  },
  twitter: {
    card: "summary_large_image",
    title: "ApplyLoop — Stop Applying Manually. Start Getting Interviews.",
    description:
      "AI fills applications, tailors resumes, writes cover letters — while you sleep. 30-60 applications per day on autopilot.",
    creator: "@applyloop",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  category: "productivity",
};

// Separate viewport export (Next 14.2+). theme-color drives the mobile
// browser chrome — matches the brand blue so the URL bar / status bar
// tint consistently when the site is added to a phone home screen.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#3b82f6" },
    { media: "(prefers-color-scheme: dark)", color: "#1e40af" },
  ],
  colorScheme: "light dark",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="scroll-smooth">
      <body>{children}</body>
    </html>
  );
}
