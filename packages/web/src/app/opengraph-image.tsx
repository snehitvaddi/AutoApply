import { ImageResponse } from "next/og";

// Next.js App Router convention: this file becomes the default Open Graph
// image for the site. Linkedin / Twitter / Slack / WhatsApp previews pull
// this automatically via the <meta property="og:image"> tag Next injects.
// Rendered server-side via next/og on first request, then edge-cached.

export const alt = "ApplyLoop — AI-powered job application engine";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OGImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          justifyContent: "center",
          padding: "80px",
          background:
            "linear-gradient(135deg, #1e40af 0%, #2563eb 40%, #3b82f6 100%)",
          color: "white",
          fontFamily: "system-ui, -apple-system, Helvetica, Arial, sans-serif",
        }}
      >
        {/* Logo mark + wordmark row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 28,
            marginBottom: 48,
          }}
        >
          <div
            style={{
              width: 120,
              height: 120,
              borderRadius: 28,
              background: "rgba(255,255,255,0.15)",
              border: "2px solid rgba(255,255,255,0.35)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 64,
              fontWeight: 800,
              letterSpacing: -2,
            }}
          >
            AL
          </div>
          <div
            style={{
              fontSize: 64,
              fontWeight: 700,
              letterSpacing: -1.5,
            }}
          >
            ApplyLoop
          </div>
        </div>

        {/* Headline */}
        <div
          style={{
            fontSize: 72,
            fontWeight: 800,
            lineHeight: 1.05,
            letterSpacing: -2,
            maxWidth: 1040,
          }}
        >
          Stop applying manually.
        </div>
        <div
          style={{
            fontSize: 72,
            fontWeight: 800,
            lineHeight: 1.05,
            letterSpacing: -2,
            marginBottom: 32,
            maxWidth: 1040,
            color: "#bfdbfe",
          }}
        >
          Start getting interviews.
        </div>

        {/* Subhead */}
        <div
          style={{
            fontSize: 30,
            color: "rgba(255,255,255,0.85)",
            lineHeight: 1.35,
            maxWidth: 960,
            fontWeight: 400,
          }}
        >
          AI fills applications, tailors resumes, writes cover letters — while you sleep.
        </div>

        {/* Footer tag */}
        <div
          style={{
            position: "absolute",
            bottom: 56,
            right: 80,
            fontSize: 24,
            color: "rgba(255,255,255,0.6)",
            fontWeight: 500,
          }}
        >
          applyloop.vercel.app
        </div>
      </div>
    ),
    size
  );
}
