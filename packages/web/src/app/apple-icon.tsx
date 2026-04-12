import { ImageResponse } from "next/og";

// Next.js App Router convention: this file becomes /apple-icon.png and
// the <link rel="apple-touch-icon"> tag is auto-injected into <head>.
// Rendered on-demand via next/og so we don't ship a PNG binary in git.

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #3b82f6 0%, #1e40af 100%)",
          borderRadius: 36,
          color: "white",
          fontSize: 100,
          fontWeight: 800,
          letterSpacing: -4,
          fontFamily: "system-ui, -apple-system, Helvetica, Arial, sans-serif",
        }}
      >
        AL
      </div>
    ),
    size
  );
}
